//! Parallel step scheduler — depth-based wave execution with threads.
//!
//! Organizes steps into execution waves based on dependency depth (from D15's
//! `DependencyGraph`). Steps at the same depth have no mutual dependencies
//! and can safely execute in parallel.
//!
//! Execution model:
//!   Wave 0: all root steps (no dependencies) — execute in parallel
//!   Wave 1: steps that depend only on wave-0 steps — execute in parallel
//!   Wave N: steps at depth N — execute after waves 0..N-1 complete
//!
//! Between waves, results synchronize back into the shared context so that
//! the next wave can read them via `${StepName}` interpolation.
//!
//! Thread model: uses `std::thread::scope` for safe, borrow-friendly parallelism
//! within each wave. No heap allocation for thread handles needed.

use std::collections::HashMap;

use crate::step_deps::{DependencyGraph, StepDependency};

// ── Schedule structures ───────────────────────────────────────────────────

/// A single execution wave — a group of steps that can run concurrently.
#[derive(Debug, Clone)]
pub struct Wave {
    /// Depth level of this wave (0 = root steps).
    pub depth: usize,
    /// Step names in this wave, sorted alphabetically.
    pub steps: Vec<String>,
    /// Whether this wave has multiple steps (actual parallelism possible).
    pub is_parallel: bool,
}

/// Execution schedule — ordered sequence of waves derived from dependency analysis.
#[derive(Debug, Clone)]
pub struct Schedule {
    /// Waves in execution order (depth 0 first).
    pub waves: Vec<Wave>,
    /// Total number of steps across all waves.
    pub total_steps: usize,
    /// Number of waves with actual parallelism (more than 1 step).
    pub parallel_waves: usize,
    /// Maximum parallelism (largest wave size).
    pub max_parallelism: usize,
}

impl Schedule {
    /// Check if the schedule contains any parallelizable waves.
    pub fn has_parallelism(&self) -> bool {
        self.parallel_waves > 0
    }

    /// Get the wave index for a given step name.
    pub fn wave_of(&self, step_name: &str) -> Option<usize> {
        for (i, wave) in self.waves.iter().enumerate() {
            if wave.steps.iter().any(|s| s == step_name) {
                return Some(i);
            }
        }
        None
    }

    /// Format the schedule as a compact summary string.
    pub fn summary(&self) -> String {
        if self.waves.is_empty() {
            return "empty schedule".to_string();
        }
        let wave_desc: Vec<String> = self
            .waves
            .iter()
            .map(|w| {
                if w.is_parallel {
                    format!("[{}]", w.steps.join(" | "))
                } else {
                    w.steps[0].clone()
                }
            })
            .collect();
        format!(
            "{} → {} waves, {} parallel",
            wave_desc.join(" → "),
            self.waves.len(),
            self.parallel_waves,
        )
    }
}

// ── Schedule builder ──────────────────────────────────────────────────────

/// Build an execution schedule from a dependency graph.
pub fn build_schedule(graph: &DependencyGraph) -> Schedule {
    if graph.steps.is_empty() {
        return Schedule {
            waves: Vec::new(),
            total_steps: 0,
            parallel_waves: 0,
            max_parallelism: 0,
        };
    }

    // Calculate depth for each step
    let depths = calculate_depths(&graph.steps);

    // Group steps by depth level
    let max_depth = depths.values().copied().max().unwrap_or(0);
    let mut waves: Vec<Wave> = Vec::new();

    for d in 0..=max_depth {
        let mut steps: Vec<String> = depths
            .iter()
            .filter(|(_, &dep)| dep == d)
            .map(|(name, _)| name.clone())
            .collect();
        if steps.is_empty() {
            continue;
        }
        steps.sort();
        let is_parallel = steps.len() > 1;
        waves.push(Wave {
            depth: d,
            steps,
            is_parallel,
        });
    }

    let total_steps = graph.steps.len();
    let parallel_waves = waves.iter().filter(|w| w.is_parallel).count();
    let max_parallelism = waves.iter().map(|w| w.steps.len()).max().unwrap_or(0);

    Schedule {
        waves,
        total_steps,
        parallel_waves,
        max_parallelism,
    }
}

/// Calculate depth for each step via transitive dependency resolution.
fn calculate_depths(deps: &[StepDependency]) -> HashMap<String, usize> {
    let dep_map: HashMap<&str, &StepDependency> =
        deps.iter().map(|d| (d.name.as_str(), d)).collect();
    let mut cache: HashMap<String, usize> = HashMap::new();

    fn step_depth(
        name: &str,
        dep_map: &HashMap<&str, &StepDependency>,
        cache: &mut HashMap<String, usize>,
    ) -> usize {
        if let Some(&cached) = cache.get(name) {
            return cached;
        }
        let d = match dep_map.get(name) {
            Some(d) => d,
            None => return 0,
        };
        if d.depends_on.is_empty() {
            cache.insert(name.to_string(), 0);
            return 0;
        }
        let max_child = d
            .depends_on
            .iter()
            .map(|dep| step_depth(dep, dep_map, cache))
            .max()
            .unwrap_or(0);
        let result = max_child + 1;
        cache.insert(name.to_string(), result);
        result
    }

    for d in deps {
        step_depth(&d.name, &dep_map, &mut cache);
    }

    cache
}

// ── Wave executor ─────────────────────────────────────────────────────────

/// Result of a single step execution within a wave.
#[derive(Debug, Clone)]
pub struct WaveStepResult {
    pub step_name: String,
    pub output: String,
    pub success: bool,
}

/// Execute a wave of steps in parallel using scoped threads.
///
/// The `execute_fn` closure is called once per step, receiving the step name.
/// It must be `Send + Sync` since it runs across threads.
///
/// Returns results for all steps in the wave (order not guaranteed for parallel).
pub fn execute_wave<F>(wave: &Wave, execute_fn: F) -> Vec<WaveStepResult>
where
    F: Fn(&str) -> WaveStepResult + Send + Sync,
{
    if !wave.is_parallel || wave.steps.len() <= 1 {
        // Sequential execution — no threads needed
        return wave.steps.iter().map(|s| execute_fn(s)).collect();
    }

    // Parallel execution with scoped threads
    let mut results: Vec<WaveStepResult> = Vec::with_capacity(wave.steps.len());

    std::thread::scope(|scope| {
        let handles: Vec<_> = wave
            .steps
            .iter()
            .map(|step_name| {
                let func = &execute_fn;
                scope.spawn(move || func(step_name))
            })
            .collect();

        for handle in handles {
            match handle.join() {
                Ok(result) => results.push(result),
                Err(_) => results.push(WaveStepResult {
                    step_name: "unknown".to_string(),
                    output: "thread panicked".to_string(),
                    success: false,
                }),
            }
        }
    });

    results
}

// ── Tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::step_deps::{analyze, StepInfo};

    // ── Schedule building ─────────────────────────────────────────

    #[test]
    fn schedule_empty() {
        let graph = analyze(&[]);
        let sched = build_schedule(&graph);
        assert!(sched.waves.is_empty());
        assert_eq!(sched.total_steps, 0);
        assert_eq!(sched.parallel_waves, 0);
        assert!(!sched.has_parallelism());
    }

    #[test]
    fn schedule_single_step() {
        let steps = vec![StepInfo {
            name: "A".into(),
            step_type: "step".into(),
            user_prompt: "do A".into(),
            argument: String::new(),
        }];
        let graph = analyze(&steps);
        let sched = build_schedule(&graph);

        assert_eq!(sched.waves.len(), 1);
        assert_eq!(sched.waves[0].steps, vec!["A"]);
        assert!(!sched.waves[0].is_parallel);
        assert_eq!(sched.parallel_waves, 0);
        assert!(!sched.has_parallelism());
    }

    #[test]
    fn schedule_linear_chain() {
        // A → B → C (all sequential)
        let steps = vec![
            StepInfo { name: "A".into(), step_type: "step".into(), user_prompt: "do A".into(), argument: String::new() },
            StepInfo { name: "B".into(), step_type: "step".into(), user_prompt: "use $A".into(), argument: String::new() },
            StepInfo { name: "C".into(), step_type: "step".into(), user_prompt: "use $B".into(), argument: String::new() },
        ];
        let graph = analyze(&steps);
        let sched = build_schedule(&graph);

        assert_eq!(sched.waves.len(), 3);
        assert_eq!(sched.waves[0].steps, vec!["A"]);
        assert_eq!(sched.waves[1].steps, vec!["B"]);
        assert_eq!(sched.waves[2].steps, vec!["C"]);
        assert_eq!(sched.parallel_waves, 0);
        assert!(!sched.has_parallelism());
    }

    #[test]
    fn schedule_diamond_pattern() {
        // A → B, A → C, B+C → D
        let steps = vec![
            StepInfo { name: "A".into(), step_type: "step".into(), user_prompt: "start".into(), argument: String::new() },
            StepInfo { name: "B".into(), step_type: "step".into(), user_prompt: "use $A path1".into(), argument: String::new() },
            StepInfo { name: "C".into(), step_type: "step".into(), user_prompt: "use $A path2".into(), argument: String::new() },
            StepInfo { name: "D".into(), step_type: "step".into(), user_prompt: "combine $B and $C".into(), argument: String::new() },
        ];
        let graph = analyze(&steps);
        let sched = build_schedule(&graph);

        assert_eq!(sched.waves.len(), 3);
        assert_eq!(sched.waves[0].steps, vec!["A"]);          // depth 0
        assert_eq!(sched.waves[1].steps, vec!["B", "C"]);     // depth 1 — PARALLEL
        assert_eq!(sched.waves[2].steps, vec!["D"]);           // depth 2
        assert!(sched.waves[1].is_parallel);
        assert_eq!(sched.parallel_waves, 1);
        assert_eq!(sched.max_parallelism, 2);
        assert!(sched.has_parallelism());
    }

    #[test]
    fn schedule_all_independent() {
        // A, B, C — no dependencies, all can run in parallel
        let steps = vec![
            StepInfo { name: "A".into(), step_type: "step".into(), user_prompt: "do A".into(), argument: String::new() },
            StepInfo { name: "B".into(), step_type: "step".into(), user_prompt: "do B".into(), argument: String::new() },
            StepInfo { name: "C".into(), step_type: "step".into(), user_prompt: "do C".into(), argument: String::new() },
        ];
        let graph = analyze(&steps);
        let sched = build_schedule(&graph);

        assert_eq!(sched.waves.len(), 1);
        assert_eq!(sched.waves[0].steps, vec!["A", "B", "C"]);
        assert!(sched.waves[0].is_parallel);
        assert_eq!(sched.max_parallelism, 3);
    }

    #[test]
    fn schedule_wide_diamond() {
        // Root → B, C, D (parallel) → E
        let steps = vec![
            StepInfo { name: "Root".into(), step_type: "step".into(), user_prompt: "start".into(), argument: String::new() },
            StepInfo { name: "B".into(), step_type: "step".into(), user_prompt: "$Root b".into(), argument: String::new() },
            StepInfo { name: "C".into(), step_type: "step".into(), user_prompt: "$Root c".into(), argument: String::new() },
            StepInfo { name: "D".into(), step_type: "step".into(), user_prompt: "$Root d".into(), argument: String::new() },
            StepInfo { name: "E".into(), step_type: "step".into(), user_prompt: "$B $C $D".into(), argument: String::new() },
        ];
        let graph = analyze(&steps);
        let sched = build_schedule(&graph);

        assert_eq!(sched.waves.len(), 3);
        assert_eq!(sched.waves[0].steps, vec!["Root"]);
        assert_eq!(sched.waves[1].steps, vec!["B", "C", "D"]);
        assert!(sched.waves[1].is_parallel);
        assert_eq!(sched.waves[2].steps, vec!["E"]);
        assert_eq!(sched.max_parallelism, 3);
    }

    // ── Wave of ───────────────────────────────────────────────────

    #[test]
    fn wave_of_lookup() {
        let steps = vec![
            StepInfo { name: "A".into(), step_type: "step".into(), user_prompt: "start".into(), argument: String::new() },
            StepInfo { name: "B".into(), step_type: "step".into(), user_prompt: "$A".into(), argument: String::new() },
        ];
        let graph = analyze(&steps);
        let sched = build_schedule(&graph);

        assert_eq!(sched.wave_of("A"), Some(0));
        assert_eq!(sched.wave_of("B"), Some(1));
        assert_eq!(sched.wave_of("Z"), None);
    }

    // ── Summary ───────────────────────────────────────────────────

    #[test]
    fn schedule_summary_format() {
        let steps = vec![
            StepInfo { name: "A".into(), step_type: "step".into(), user_prompt: "start".into(), argument: String::new() },
            StepInfo { name: "B".into(), step_type: "step".into(), user_prompt: "$A b".into(), argument: String::new() },
            StepInfo { name: "C".into(), step_type: "step".into(), user_prompt: "$A c".into(), argument: String::new() },
            StepInfo { name: "D".into(), step_type: "step".into(), user_prompt: "$B $C".into(), argument: String::new() },
        ];
        let graph = analyze(&steps);
        let sched = build_schedule(&graph);
        let summary = sched.summary();

        assert!(summary.contains("A"));
        assert!(summary.contains("B | C"));
        assert!(summary.contains("D"));
        assert!(summary.contains("3 waves"));
        assert!(summary.contains("1 parallel"));
    }

    // ── Wave execution ────────────────────────────────────────────

    #[test]
    fn execute_wave_sequential() {
        let wave = Wave {
            depth: 0,
            steps: vec!["A".into()],
            is_parallel: false,
        };

        let results = execute_wave(&wave, |name| WaveStepResult {
            step_name: name.to_string(),
            output: format!("result_{name}"),
            success: true,
        });

        assert_eq!(results.len(), 1);
        assert_eq!(results[0].step_name, "A");
        assert_eq!(results[0].output, "result_A");
    }

    #[test]
    fn execute_wave_parallel() {
        use std::sync::atomic::{AtomicUsize, Ordering};

        let wave = Wave {
            depth: 1,
            steps: vec!["B".into(), "C".into(), "D".into()],
            is_parallel: true,
        };

        let counter = AtomicUsize::new(0);

        let results = execute_wave(&wave, |name| {
            counter.fetch_add(1, Ordering::SeqCst);
            // Simulate some work
            std::thread::sleep(std::time::Duration::from_millis(10));
            WaveStepResult {
                step_name: name.to_string(),
                output: format!("done_{name}"),
                success: true,
            }
        });

        // All 3 steps executed
        assert_eq!(results.len(), 3);
        assert_eq!(counter.load(Ordering::SeqCst), 3);

        // All results present (order may vary)
        let mut names: Vec<String> = results.iter().map(|r| r.step_name.clone()).collect();
        names.sort();
        assert_eq!(names, vec!["B", "C", "D"]);
    }

    #[test]
    fn execute_wave_thread_safety() {
        use std::sync::{Arc, Mutex};

        let wave = Wave {
            depth: 0,
            steps: vec!["X".into(), "Y".into()],
            is_parallel: true,
        };

        let log = Arc::new(Mutex::new(Vec::<String>::new()));

        let results = execute_wave(&wave, |name| {
            log.lock().unwrap().push(name.to_string());
            WaveStepResult {
                step_name: name.to_string(),
                output: "ok".to_string(),
                success: true,
            }
        });

        assert_eq!(results.len(), 2);
        let entries = log.lock().unwrap();
        assert_eq!(entries.len(), 2);
        assert!(entries.contains(&"X".to_string()));
        assert!(entries.contains(&"Y".to_string()));
    }
}

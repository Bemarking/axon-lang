//! Execution hooks — pre/post step callbacks for instrumentation.
//!
//! Provides timing, token tracking, and metrics collection at the
//! step and unit level. The `HookManager` accumulates events during
//! execution and produces a summary at completion.
//!
//! Hook events:
//!   UnitStart   — fired when an execution unit begins
//!   StepStart   — fired before each step executes
//!   StepEnd     — fired after each step completes
//!   UnitEnd     — fired when an execution unit completes
//!
//! Metrics tracked:
//!   - Per-step wall-clock duration (milliseconds)
//!   - Per-step input/output token counts
//!   - Per-unit aggregated timing and tokens
//!   - Anchor breach count per step
//!   - Total execution summary

use std::time::Instant;

/// A recorded step timing with associated metrics.
#[derive(Debug, Clone)]
pub struct StepMetrics {
    pub unit_name: String,
    pub step_name: String,
    pub step_type: String,
    pub duration_ms: u64,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub anchor_breaches: u32,
    pub chain_activations: u32,
    pub was_retried: bool,
}

/// A recorded unit timing with aggregated metrics.
#[derive(Debug, Clone)]
pub struct UnitMetrics {
    pub unit_name: String,
    pub persona_name: String,
    pub duration_ms: u64,
    pub total_steps: usize,
    pub total_input_tokens: u64,
    pub total_output_tokens: u64,
    pub total_anchor_breaches: u32,
    pub total_chain_activations: u32,
}

/// Hook manager — accumulates execution metrics.
#[derive(Debug)]
pub struct HookManager {
    step_metrics: Vec<StepMetrics>,
    unit_metrics: Vec<UnitMetrics>,
    // In-flight tracking
    current_unit_start: Option<Instant>,
    current_unit_name: String,
    current_persona: String,
    current_step_start: Option<Instant>,
    current_step_name: String,
    current_step_type: String,
}

impl HookManager {
    /// Create a new hook manager.
    pub fn new() -> Self {
        HookManager {
            step_metrics: Vec::new(),
            unit_metrics: Vec::new(),
            current_unit_start: None,
            current_unit_name: String::new(),
            current_persona: String::new(),
            current_step_start: None,
            current_step_name: String::new(),
            current_step_type: String::new(),
        }
    }

    /// Signal the start of an execution unit.
    pub fn on_unit_start(&mut self, unit_name: &str, persona_name: &str) {
        self.current_unit_start = Some(Instant::now());
        self.current_unit_name = unit_name.to_string();
        self.current_persona = persona_name.to_string();
    }

    /// Signal the end of an execution unit.
    pub fn on_unit_end(&mut self) {
        let duration_ms = self
            .current_unit_start
            .map(|s| s.elapsed().as_millis() as u64)
            .unwrap_or(0);

        // Aggregate step metrics for this unit
        let unit_steps: Vec<&StepMetrics> = self
            .step_metrics
            .iter()
            .filter(|s| s.unit_name == self.current_unit_name)
            .collect();

        self.unit_metrics.push(UnitMetrics {
            unit_name: self.current_unit_name.clone(),
            persona_name: self.current_persona.clone(),
            duration_ms,
            total_steps: unit_steps.len(),
            total_input_tokens: unit_steps.iter().map(|s| s.input_tokens).sum(),
            total_output_tokens: unit_steps.iter().map(|s| s.output_tokens).sum(),
            total_anchor_breaches: unit_steps.iter().map(|s| s.anchor_breaches).sum(),
            total_chain_activations: unit_steps.iter().map(|s| s.chain_activations).sum(),
        });

        self.current_unit_start = None;
    }

    /// Signal the start of a step.
    pub fn on_step_start(&mut self, step_name: &str, step_type: &str) {
        self.current_step_start = Some(Instant::now());
        self.current_step_name = step_name.to_string();
        self.current_step_type = step_type.to_string();
    }

    /// Signal the end of a step with metrics.
    pub fn on_step_end(
        &mut self,
        input_tokens: u64,
        output_tokens: u64,
        anchor_breaches: u32,
        chain_activations: u32,
        was_retried: bool,
    ) {
        let duration_ms = self
            .current_step_start
            .map(|s| s.elapsed().as_millis() as u64)
            .unwrap_or(0);

        self.step_metrics.push(StepMetrics {
            unit_name: self.current_unit_name.clone(),
            step_name: self.current_step_name.clone(),
            step_type: self.current_step_type.clone(),
            duration_ms,
            input_tokens,
            output_tokens,
            anchor_breaches,
            chain_activations,
            was_retried,
        });

        self.current_step_start = None;
    }

    /// Get all step metrics.
    pub fn step_metrics(&self) -> &[StepMetrics] {
        &self.step_metrics
    }

    /// Get all unit metrics.
    pub fn unit_metrics(&self) -> &[UnitMetrics] {
        &self.unit_metrics
    }

    /// Total execution time across all units.
    pub fn total_duration_ms(&self) -> u64 {
        self.unit_metrics.iter().map(|u| u.duration_ms).sum()
    }

    /// Total input tokens across all steps.
    pub fn total_input_tokens(&self) -> u64 {
        self.step_metrics.iter().map(|s| s.input_tokens).sum()
    }

    /// Total output tokens across all steps.
    pub fn total_output_tokens(&self) -> u64 {
        self.step_metrics.iter().map(|s| s.output_tokens).sum()
    }

    /// Total steps executed.
    pub fn total_steps(&self) -> usize {
        self.step_metrics.len()
    }

    /// Number of steps that were retried.
    pub fn retried_steps(&self) -> usize {
        self.step_metrics.iter().filter(|s| s.was_retried).count()
    }

    /// Slowest step by duration.
    pub fn slowest_step(&self) -> Option<&StepMetrics> {
        self.step_metrics.iter().max_by_key(|s| s.duration_ms)
    }

    /// Most expensive step by total tokens.
    pub fn most_expensive_step(&self) -> Option<&StepMetrics> {
        self.step_metrics
            .iter()
            .max_by_key(|s| s.input_tokens + s.output_tokens)
    }

    /// Average step duration in milliseconds.
    pub fn avg_step_duration_ms(&self) -> u64 {
        if self.step_metrics.is_empty() {
            return 0;
        }
        let total: u64 = self.step_metrics.iter().map(|s| s.duration_ms).sum();
        total / self.step_metrics.len() as u64
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn new_hook_manager_is_empty() {
        let hm = HookManager::new();
        assert_eq!(hm.total_steps(), 0);
        assert_eq!(hm.total_duration_ms(), 0);
        assert_eq!(hm.total_input_tokens(), 0);
        assert_eq!(hm.total_output_tokens(), 0);
        assert_eq!(hm.retried_steps(), 0);
        assert!(hm.slowest_step().is_none());
        assert!(hm.most_expensive_step().is_none());
        assert_eq!(hm.avg_step_duration_ms(), 0);
    }

    #[test]
    fn step_lifecycle() {
        let mut hm = HookManager::new();
        hm.on_unit_start("Flow1", "Expert");
        hm.on_step_start("Analyze", "step");
        // Simulate some work
        thread::sleep(Duration::from_millis(5));
        hm.on_step_end(100, 50, 0, 0, false);
        hm.on_unit_end();

        assert_eq!(hm.total_steps(), 1);
        let s = &hm.step_metrics()[0];
        assert_eq!(s.unit_name, "Flow1");
        assert_eq!(s.step_name, "Analyze");
        assert_eq!(s.step_type, "step");
        assert_eq!(s.input_tokens, 100);
        assert_eq!(s.output_tokens, 50);
        assert!(s.duration_ms >= 4); // At least ~5ms
        assert!(!s.was_retried);
    }

    #[test]
    fn unit_aggregates_steps() {
        let mut hm = HookManager::new();
        hm.on_unit_start("Flow1", "Expert");

        hm.on_step_start("Step1", "step");
        hm.on_step_end(100, 50, 1, 0, false);

        hm.on_step_start("Step2", "step");
        hm.on_step_end(200, 100, 0, 1, true);

        hm.on_unit_end();

        let u = &hm.unit_metrics()[0];
        assert_eq!(u.unit_name, "Flow1");
        assert_eq!(u.total_steps, 2);
        assert_eq!(u.total_input_tokens, 300);
        assert_eq!(u.total_output_tokens, 150);
        assert_eq!(u.total_anchor_breaches, 1);
        assert_eq!(u.total_chain_activations, 1);
    }

    #[test]
    fn multiple_units() {
        let mut hm = HookManager::new();

        hm.on_unit_start("Flow1", "P1");
        hm.on_step_start("S1", "step");
        hm.on_step_end(10, 5, 0, 0, false);
        hm.on_unit_end();

        hm.on_unit_start("Flow2", "P2");
        hm.on_step_start("S2", "step");
        hm.on_step_end(20, 10, 0, 0, false);
        hm.on_unit_end();

        assert_eq!(hm.unit_metrics().len(), 2);
        assert_eq!(hm.total_steps(), 2);
        assert_eq!(hm.total_input_tokens(), 30);
        assert_eq!(hm.total_output_tokens(), 15);
    }

    #[test]
    fn retried_steps_count() {
        let mut hm = HookManager::new();
        hm.on_unit_start("F", "P");
        hm.on_step_start("S1", "step");
        hm.on_step_end(10, 5, 0, 0, false);
        hm.on_step_start("S2", "step");
        hm.on_step_end(20, 10, 2, 0, true);
        hm.on_step_start("S3", "step");
        hm.on_step_end(15, 8, 0, 0, false);
        hm.on_unit_end();

        assert_eq!(hm.retried_steps(), 1);
    }

    #[test]
    fn slowest_step() {
        let mut hm = HookManager::new();
        hm.on_unit_start("F", "P");

        hm.on_step_start("Fast", "step");
        hm.on_step_end(10, 5, 0, 0, false);

        hm.on_step_start("Slow", "step");
        thread::sleep(Duration::from_millis(10));
        hm.on_step_end(10, 5, 0, 0, false);

        hm.on_unit_end();

        let slowest = hm.slowest_step().unwrap();
        assert_eq!(slowest.step_name, "Slow");
    }

    #[test]
    fn most_expensive_step() {
        let mut hm = HookManager::new();
        hm.on_unit_start("F", "P");

        hm.on_step_start("Cheap", "step");
        hm.on_step_end(10, 5, 0, 0, false);

        hm.on_step_start("Expensive", "step");
        hm.on_step_end(1000, 500, 0, 0, false);

        hm.on_unit_end();

        let expensive = hm.most_expensive_step().unwrap();
        assert_eq!(expensive.step_name, "Expensive");
        assert_eq!(expensive.input_tokens + expensive.output_tokens, 1500);
    }

    #[test]
    fn avg_step_duration() {
        let mut hm = HookManager::new();
        hm.on_unit_start("F", "P");

        // Manually create metrics to avoid timing flakiness
        hm.step_metrics.push(StepMetrics {
            unit_name: "F".into(),
            step_name: "S1".into(),
            step_type: "step".into(),
            duration_ms: 100,
            input_tokens: 0,
            output_tokens: 0,
            anchor_breaches: 0,
            chain_activations: 0,
            was_retried: false,
        });
        hm.step_metrics.push(StepMetrics {
            unit_name: "F".into(),
            step_name: "S2".into(),
            step_type: "step".into(),
            duration_ms: 200,
            input_tokens: 0,
            output_tokens: 0,
            anchor_breaches: 0,
            chain_activations: 0,
            was_retried: false,
        });

        assert_eq!(hm.avg_step_duration_ms(), 150);
    }

    #[test]
    fn step_with_anchor_breaches_and_chains() {
        let mut hm = HookManager::new();
        hm.on_unit_start("F", "P");
        hm.on_step_start("S1", "step");
        hm.on_step_end(100, 50, 3, 2, true);
        hm.on_unit_end();

        let s = &hm.step_metrics()[0];
        assert_eq!(s.anchor_breaches, 3);
        assert_eq!(s.chain_activations, 2);
        assert!(s.was_retried);
    }
}

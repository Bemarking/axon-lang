//! Anchor runtime checkers — validate LLM output against AXON anchor constraints.
//!
//! Each checker returns `(passed: bool, violations: Vec<String>)`.
//! Checkers perform lightweight text analysis — they are heuristic guards,
//! not formal verification. They complement the system prompt instructions.
//!
//! Supported anchors (12):
//!   Core:      NoHallucination, FactualOnly, SafeOutput, PrivacyGuard,
//!              NoBias, ChildSafe, NoCodeExecution, AuditTrail
//!   Epistemic: SyllogismChecker, ChainOfThoughtValidator,
//!              RequiresCitation, AgnosticFallback

use crate::ir_nodes::IRAnchor;

/// Result of checking one anchor against LLM output.
#[derive(Debug, Clone)]
pub struct AnchorResult {
    pub anchor_name: String,
    pub passed: bool,
    pub violations: Vec<String>,
    pub severity: &'static str,
    /// Confidence score (0.0–1.0) indicating how well the output adheres to this anchor.
    pub confidence: f64,
}

/// Check all resolved anchors against LLM output text.
pub fn check_all(anchors: &[IRAnchor], output: &str) -> Vec<AnchorResult> {
    anchors.iter().map(|a| check_one(a, output)).collect()
}

/// Check a single anchor against output text.
/// Enforces `confidence_floor` when set: if the computed confidence
/// is below the floor, the anchor is marked as breached regardless
/// of whether the heuristic check passed.
fn check_one(anchor: &IRAnchor, output: &str) -> AnchorResult {
    let (mut passed, mut violations, severity, confidence) = match anchor.name.as_str() {
        "NoHallucination" => check_no_hallucination(output),
        "FactualOnly" => check_factual_only(output),
        "SafeOutput" => check_safe_output(output),
        "PrivacyGuard" => check_privacy_guard(output),
        "NoBias" => check_no_bias(output),
        "ChildSafe" => check_child_safe(output),
        "NoCodeExecution" => check_no_code_execution(output),
        "AuditTrail" => check_audit_trail(output),
        "SyllogismChecker" => check_syllogism(output),
        "ChainOfThoughtValidator" => check_chain_of_thought(output),
        "RequiresCitation" => check_requires_citation(output),
        "AgnosticFallback" => check_agnostic_fallback(output),
        _ => {
            // Unknown anchor — pass by default with a note
            (true, vec![format!("Unknown anchor '{}' — skipped", anchor.name)], "warning", 1.0)
        }
    };

    // Enforce confidence_floor
    if let Some(floor) = anchor.confidence_floor {
        if confidence < floor && passed {
            passed = false;
            violations.push(format!(
                "Confidence {:.2} below floor {:.2}",
                confidence, floor
            ));
        }
    }

    AnchorResult {
        anchor_name: anchor.name.clone(),
        passed,
        violations,
        severity,
        confidence,
    }
}

// ── Core anchors ────────────────────────────────────────────────────────────

/// NoHallucination: Detect hedging phrases without citations.
fn check_no_hallucination(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();
    let hedging = [
        "i believe", "i think", "probably", "it seems",
        "might be", "could be", "presumably", "supposedly",
    ];
    let has_citation = lower.contains('[') && lower.contains(']')
        || lower.contains("source:")
        || lower.contains("according to")
        || lower.contains("cited");

    let mut violations = Vec::new();
    let mut hit_count = 0usize;
    for phrase in &hedging {
        if lower.contains(phrase) {
            hit_count += 1;
            if !has_citation {
                violations.push(format!("Hedging phrase '{phrase}' without citation"));
            }
        }
    }

    // Confidence: start at 1.0, penalize per hedging hit, bonus for citations
    let penalty = hit_count as f64 * 0.15;
    let citation_bonus = if has_citation { 0.10 } else { 0.0 };
    let confidence = (1.0 - penalty + citation_bonus).clamp(0.0, 1.0);

    (violations.is_empty(), violations, "error", confidence)
}

/// FactualOnly: Detect opinion markers.
fn check_factual_only(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();
    let opinion_markers = [
        "in my opinion", "i feel", "i believe", "personally",
        "i prefer", "my view", "my take", "i would say",
    ];

    let mut violations = Vec::new();
    let mut hit_count = 0usize;
    for marker in &opinion_markers {
        if lower.contains(marker) {
            hit_count += 1;
            violations.push(format!("Opinion marker detected: '{marker}'"));
        }
    }

    let confidence = (1.0 - hit_count as f64 * 0.20).clamp(0.0, 1.0);
    (violations.is_empty(), violations, "error", confidence)
}

/// SafeOutput: Detect harmful content keywords.
fn check_safe_output(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();
    let harmful = [
        "kill", "murder", "attack", "bomb", "weapon",
        "hate speech", "racial slur", "ethnic cleansing",
    ];

    let mut violations = Vec::new();
    let mut hit_count = 0usize;
    for word in &harmful {
        if lower.contains(word) {
            hit_count += 1;
            violations.push(format!("Potentially harmful content: '{word}'"));
        }
    }

    // Harmful content is severe: each hit drops confidence sharply
    let confidence = (1.0 - hit_count as f64 * 0.30).clamp(0.0, 1.0);
    (violations.is_empty(), violations, "error", confidence)
}

/// PrivacyGuard: Detect PII patterns (SSN, credit card, email, phone).
fn check_privacy_guard(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let mut violations = Vec::new();

    // SSN pattern: NNN-NN-NNNN
    if contains_pattern(output, r"\d{3}-\d{2}-\d{4}") {
        violations.push("SSN pattern detected (NNN-NN-NNNN)".to_string());
    }

    // Credit card: 16 digits with optional separators
    if contains_pattern(output, r"\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}") {
        violations.push("Credit card pattern detected".to_string());
    }

    // Email
    if contains_pattern(output, r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}") {
        violations.push("Email address detected".to_string());
    }

    // Phone: various formats
    if contains_pattern(output, r"\+?\d{1,3}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}") {
        violations.push("Phone number pattern detected".to_string());
    }

    // PII is critical: each type detected drops confidence sharply
    let confidence = (1.0 - violations.len() as f64 * 0.25).clamp(0.0, 1.0);
    (violations.is_empty(), violations, "error", confidence)
}

/// NoBias: Detect bias markers.
fn check_no_bias(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();
    let bias_markers = [
        "obviously", "clearly everyone knows", "all men", "all women",
        "those people", "naturally superior", "inherently inferior",
    ];

    let mut violations = Vec::new();
    let mut hit_count = 0usize;
    for marker in &bias_markers {
        if lower.contains(marker) {
            hit_count += 1;
            violations.push(format!("Potential bias marker: '{marker}'"));
        }
    }

    let confidence = (1.0 - hit_count as f64 * 0.20).clamp(0.0, 1.0);
    (violations.is_empty(), violations, "warning", confidence)
}

/// ChildSafe: Detect age-inappropriate content.
fn check_child_safe(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();
    let inappropriate = [
        "explicit", "graphic violence", "sexual content",
        "drug use", "alcohol abuse", "profanity",
    ];

    let mut violations = Vec::new();
    let mut hit_count = 0usize;
    for marker in &inappropriate {
        if lower.contains(marker) {
            hit_count += 1;
            violations.push(format!("Age-inappropriate content: '{marker}'"));
        }
    }

    let confidence = (1.0 - hit_count as f64 * 0.30).clamp(0.0, 1.0);
    (violations.is_empty(), violations, "error", confidence)
}

/// NoCodeExecution: Detect dangerous code patterns.
fn check_no_code_execution(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();
    let dangerous = [
        "exec(", "eval(", "system(", "os.system",
        "subprocess", "rm -rf", "del /f", "format c:",
        "import os", "import sys", "__import__",
    ];

    let mut violations = Vec::new();
    let mut hit_count = 0usize;
    for pattern in &dangerous {
        if lower.contains(pattern) {
            hit_count += 1;
            violations.push(format!("Code execution pattern: '{pattern}'"));
        }
    }

    let confidence = (1.0 - hit_count as f64 * 0.25).clamp(0.0, 1.0);
    (violations.is_empty(), violations, "error", confidence)
}

/// AuditTrail: Require reasoning markers in output.
fn check_audit_trail(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();
    let reasoning_markers = [
        "reasoning:", "therefore", "because", "since",
        "step 1", "first,", "analysis:", "conclusion:",
    ];

    let marker_count = reasoning_markers.iter().filter(|m| lower.contains(**m)).count();
    // Confidence scales with how many reasoning markers are present
    let confidence = (marker_count as f64 * 0.20).clamp(0.0, 1.0);

    if marker_count > 0 {
        (true, Vec::new(), "warning", confidence)
    } else {
        (false, vec!["No reasoning markers found (expected: reasoning:, therefore, because, step N, etc.)".to_string()], "warning", 0.0)
    }
}

// ── Logic & Epistemic anchors ───────────────────────────────────────────────

/// SyllogismChecker: Enforce Premise: and Conclusion: format.
fn check_syllogism(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let mut violations = Vec::new();

    let has_premise = output.contains("Premise:") || output.contains("premise:");
    let premise_count = output.matches("Premise:").count() + output.matches("premise:").count();
    let conclusion_count = output.matches("Conclusion:").count()
        + output.matches("conclusion:").count();

    if !has_premise {
        violations.push("No 'Premise:' identifier found".to_string());
    }
    if conclusion_count == 0 {
        violations.push("No 'Conclusion:' identifier found".to_string());
    }
    if conclusion_count > 1 {
        violations.push(format!("Multiple conclusions found ({conclusion_count}), expected exactly 1"));
    }

    // Confidence: having premises + exactly one conclusion = high confidence
    let mut score = 0.0;
    if has_premise { score += 0.30 + (premise_count.min(3) as f64 - 1.0) * 0.10; }
    if conclusion_count == 1 { score += 0.40; }
    let confidence = score.clamp(0.0, 1.0);

    (violations.is_empty(), violations, "error", confidence)
}

/// ChainOfThoughtValidator: Require step-by-step markers.
fn check_chain_of_thought(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();
    let step_markers = [
        "step 1", "step 2", "first,", "second,", "third,",
        "firstly", "secondly", "next,", "finally,", "then,",
    ];

    let marker_count = step_markers.iter().filter(|m| lower.contains(**m)).count();
    // Confidence scales with number of step markers (2 = pass, more = higher confidence)
    let confidence = (marker_count as f64 * 0.25).clamp(0.0, 1.0);

    if marker_count >= 2 {
        (true, Vec::new(), "error", confidence)
    } else {
        (false, vec![format!("Only {marker_count} step markers found, need at least 2 (step N, first/second/third, etc.)")], "error", confidence)
    }
}

/// RequiresCitation: Require inline citations or URLs.
fn check_requires_citation(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    // Check for bracket citations [1], [2] etc.
    let has_bracket = contains_pattern(output, r"\[\d+\]");
    // Check for author-year (Smith, 2024)
    let has_author_year = contains_pattern(output, r"\([A-Z][a-z]+,?\s*\d{4}\)");
    // Check for DOI
    let has_doi = output.contains("doi:") || output.contains("DOI:");
    // Check for URL
    let has_url = output.contains("http://") || output.contains("https://");

    let citation_types = [has_bracket, has_author_year, has_doi, has_url];
    let type_count = citation_types.iter().filter(|&&b| b).count();
    // Confidence: more diverse citation types = higher confidence
    let confidence = (type_count as f64 * 0.35).clamp(0.0, 1.0);

    if type_count > 0 {
        (true, Vec::new(), "error", confidence)
    } else {
        (false, vec!["No citations found (expected: [N], (Author, Year), doi:, or URL)".to_string()], "error", 0.0)
    }
}

/// AgnosticFallback: Detect unwarranted guessing vs honest ignorance.
fn check_agnostic_fallback(output: &str) -> (bool, Vec<String>, &'static str, f64) {
    let lower = output.to_lowercase();

    let guessing_markers = [
        "i guess", "my guess is", "probably", "i'd assume",
        "i would guess", "if i had to guess",
    ];
    let honesty_markers = [
        "i don't know", "i'm not sure", "i cannot determine",
        "insufficient information", "unable to verify",
        "i lack the information", "beyond my knowledge",
    ];

    let guess_count = guessing_markers.iter().filter(|m| lower.contains(**m)).count();
    let honesty_count = honesty_markers.iter().filter(|m| lower.contains(**m)).count();

    let mut violations = Vec::new();
    if guess_count > 0 && honesty_count == 0 {
        violations.push("Unwarranted guessing detected without epistemic honesty markers".to_string());
    }

    // Confidence: penalize guessing, reward honesty
    let guess_penalty = guess_count as f64 * 0.20;
    let honesty_bonus = honesty_count as f64 * 0.15;
    let confidence = (1.0 - guess_penalty + honesty_bonus).clamp(0.0, 1.0);

    (violations.is_empty(), violations, "error", confidence)
}

// ── Utility ─────────────────────────────────────────────────────────────────

/// Simple pattern matching without regex dependency.
/// Supports: \d (digit), \s (whitespace), \[ \] (literal brackets),
/// literal chars, and basic character classes [a-zA-Z].
fn contains_pattern(text: &str, pattern: &str) -> bool {
    // For common patterns, use string-based heuristics
    // This avoids pulling in the regex crate
    match pattern {
        r"\d{3}-\d{2}-\d{4}" => {
            // SSN: 3 digits - 2 digits - 4 digits
            text.as_bytes().windows(11).any(|w| {
                w[0].is_ascii_digit() && w[1].is_ascii_digit() && w[2].is_ascii_digit()
                    && w[3] == b'-'
                    && w[4].is_ascii_digit() && w[5].is_ascii_digit()
                    && w[6] == b'-'
                    && w[7].is_ascii_digit() && w[8].is_ascii_digit()
                    && w[9].is_ascii_digit() && w[10].is_ascii_digit()
            })
        }
        r"\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}" => {
            // Credit card: 4 groups of 4 digits
            let digits: String = text.chars().filter(|c| c.is_ascii_digit()).collect();
            digits.len() >= 16 && digits[..16].chars().all(|c| c.is_ascii_digit())
        }
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}" => {
            // Email: something @ something . something
            text.contains('@') && {
                text.split_whitespace().any(|word| {
                    let parts: Vec<&str> = word.split('@').collect();
                    parts.len() == 2
                        && !parts[0].is_empty()
                        && parts[1].contains('.')
                        && parts[1].split('.').last().map_or(false, |tld| tld.len() >= 2)
                })
            }
        }
        r"\+?\d{1,3}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}" => {
            // Phone: sequence of 10+ digits with optional separators
            let digits: usize = text.chars().filter(|c| c.is_ascii_digit()).count();
            digits >= 10 && (text.contains('(') || text.contains('+') || text.contains('-'))
        }
        r"\[\d+\]" => {
            // Bracket citation: [N]
            let bytes = text.as_bytes();
            for i in 0..bytes.len().saturating_sub(2) {
                if bytes[i] == b'[' {
                    let mut j = i + 1;
                    while j < bytes.len() && bytes[j].is_ascii_digit() {
                        j += 1;
                    }
                    if j > i + 1 && j < bytes.len() && bytes[j] == b']' {
                        return true;
                    }
                }
            }
            false
        }
        r"\([A-Z][a-z]+,?\s*\d{4}\)" => {
            // Author-year: (Smith, 2024) or (Smith 2024)
            let bytes = text.as_bytes();
            for i in 0..bytes.len().saturating_sub(8) {
                if bytes[i] == b'(' && bytes[i + 1].is_ascii_uppercase() {
                    // Find closing paren with year
                    if let Some(close) = text[i..].find(')') {
                        let inner = &text[i + 1..i + close];
                        if inner.len() >= 6 {
                            let last4 = &inner[inner.len() - 4..];
                            if last4.chars().all(|c| c.is_ascii_digit()) {
                                return true;
                            }
                        }
                    }
                }
            }
            false
        }
        _ => false,
    }
}

/// Build a retry feedback string from anchor results.
/// Returns `None` if there are no error-severity breaches.
pub fn build_retry_feedback(results: &[AnchorResult]) -> Option<String> {
    let breaches: Vec<String> = results
        .iter()
        .filter(|r| !r.passed && r.severity == "error")
        .flat_map(|r| {
            r.violations
                .iter()
                .map(move |v| format!("{}: {}", r.anchor_name, v))
        })
        .collect();

    if breaches.is_empty() {
        return None;
    }

    let numbered: Vec<String> = breaches
        .iter()
        .enumerate()
        .map(|(i, v)| format!("{}. {}", i + 1, v))
        .collect();

    Some(numbered.join("\n"))
}

/// Count error-severity breaches in results.
pub fn error_breach_count(results: &[AnchorResult]) -> usize {
    results.iter().filter(|r| !r.passed && r.severity == "error").count()
}

// ── Anchor chaining ──────────────────────────────────────────────────────

/// An anchor chain rule: when `trigger` breaches, `enforced` is also checked.
#[derive(Debug, Clone)]
pub struct AnchorChain {
    pub trigger: &'static str,
    pub enforced: &'static str,
    pub reason: &'static str,
}

/// Built-in anchor chain rules.
///
/// These define defense-in-depth relationships: a breach in one anchor
/// triggers validation of a related anchor even if it wasn't originally
/// in the program's anchor set.
///
/// Rules:
///   NoHallucination → RequiresCitation   (hedging → demand sources)
///   FactualOnly     → RequiresCitation   (opinions → demand backing)
///   NoBias          → AgnosticFallback   (bias → demand neutrality)
///   SafeOutput      → ChildSafe          (harmful → also check child safety)
///   NoCodeExecution → SafeOutput         (dangerous code → verify safe)
pub fn chain_rules() -> Vec<AnchorChain> {
    vec![
        AnchorChain {
            trigger: "NoHallucination",
            enforced: "RequiresCitation",
            reason: "hedging detected — requiring citation backup",
        },
        AnchorChain {
            trigger: "FactualOnly",
            enforced: "RequiresCitation",
            reason: "opinion markers detected — requiring citation backup",
        },
        AnchorChain {
            trigger: "NoBias",
            enforced: "AgnosticFallback",
            reason: "bias detected — requiring agnostic language",
        },
        AnchorChain {
            trigger: "SafeOutput",
            enforced: "ChildSafe",
            reason: "harmful content detected — verifying child safety",
        },
        AnchorChain {
            trigger: "NoCodeExecution",
            enforced: "SafeOutput",
            reason: "dangerous code detected — verifying safe output",
        },
    ]
}

/// Resolve which chained anchors should be checked based on breaches.
///
/// For each breached anchor, looks up chain rules. If a chain's `enforced`
/// anchor is not already in the original set (by name), it creates a
/// synthetic IRAnchor for the chained check.
///
/// Returns a list of (chain_rule, synthetic_anchor) pairs to check.
pub fn resolve_chains(
    results: &[AnchorResult],
    existing_anchors: &[IRAnchor],
) -> Vec<(AnchorChain, IRAnchor)> {
    let rules = chain_rules();
    let existing_names: Vec<&str> = existing_anchors.iter().map(|a| a.name.as_str()).collect();
    let breached: Vec<&str> = results
        .iter()
        .filter(|r| !r.passed && r.severity == "error")
        .map(|r| r.anchor_name.as_str())
        .collect();

    let mut chained = Vec::new();
    let mut already_chained: Vec<&str> = Vec::new();

    for rule in &rules {
        if breached.contains(&rule.trigger)
            && !existing_names.contains(&rule.enforced)
            && !already_chained.contains(&rule.enforced)
        {
            let synthetic = IRAnchor {
                node_type: "anchor",
                source_line: 0,
                source_column: 0,
                name: rule.enforced.to_string(),
                description: format!("Chained from {} breach", rule.trigger),
                require: String::new(),
                reject: Vec::new(),
                enforce: String::new(),
                confidence_floor: None,
                unknown_response: String::new(),
                on_violation: String::new(),
                on_violation_target: String::new(),
            };
            already_chained.push(rule.enforced);
            chained.push((rule.clone(), synthetic));
        }
    }

    chained
}

/// Execute chained anchor checks on LLM output.
///
/// Returns the chain results (one AnchorResult per chained anchor).
pub fn check_chained(
    results: &[AnchorResult],
    existing_anchors: &[IRAnchor],
    output: &str,
) -> Vec<(AnchorChain, AnchorResult)> {
    let chains = resolve_chains(results, existing_anchors);
    chains
        .into_iter()
        .map(|(rule, anchor)| {
            let result = check_one(&anchor, output);
            (rule, result)
        })
        .collect()
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn make_anchor(name: &str) -> IRAnchor {
        IRAnchor {
            node_type: "anchor",
            source_line: 0,
            source_column: 0,
            name: name.to_string(),
            description: String::new(),
            require: String::new(),
            reject: Vec::new(),
            enforce: String::new(),
            confidence_floor: None,
            unknown_response: String::new(),
            on_violation: String::new(),
            on_violation_target: String::new(),
        }
    }

    #[test]
    fn no_hallucination_passes_with_citation() {
        let a = make_anchor("NoHallucination");
        let r = check_one(&a, "According to [1], the result is 42.");
        assert!(r.passed);
    }

    #[test]
    fn no_hallucination_fails_with_hedging() {
        let a = make_anchor("NoHallucination");
        let r = check_one(&a, "I think the answer might be 42.");
        assert!(!r.passed);
        assert!(!r.violations.is_empty());
    }

    #[test]
    fn factual_only_passes_clean() {
        let a = make_anchor("FactualOnly");
        let r = check_one(&a, "The temperature is 22 degrees Celsius.");
        assert!(r.passed);
    }

    #[test]
    fn factual_only_fails_opinion() {
        let a = make_anchor("FactualOnly");
        let r = check_one(&a, "In my opinion, the answer is 42.");
        assert!(!r.passed);
    }

    #[test]
    fn privacy_guard_detects_ssn() {
        let a = make_anchor("PrivacyGuard");
        let r = check_one(&a, "SSN: 123-45-6789");
        assert!(!r.passed);
        assert!(r.violations[0].contains("SSN"));
    }

    #[test]
    fn privacy_guard_detects_email() {
        let a = make_anchor("PrivacyGuard");
        let r = check_one(&a, "Contact me at user@example.com");
        assert!(!r.passed);
        assert!(r.violations[0].contains("Email"));
    }

    #[test]
    fn privacy_guard_passes_clean() {
        let a = make_anchor("PrivacyGuard");
        let r = check_one(&a, "The report contains no personal information.");
        assert!(r.passed);
    }

    #[test]
    fn audit_trail_passes_with_reasoning() {
        let a = make_anchor("AuditTrail");
        let r = check_one(&a, "Step 1: Analyze the data. Therefore, the result is correct.");
        assert!(r.passed);
    }

    #[test]
    fn audit_trail_fails_no_reasoning() {
        let a = make_anchor("AuditTrail");
        let r = check_one(&a, "The answer is 42.");
        assert!(!r.passed);
    }

    #[test]
    fn syllogism_passes() {
        let a = make_anchor("SyllogismChecker");
        let r = check_one(&a, "Premise: All humans are mortal.\nPremise: Socrates is human.\nConclusion: Socrates is mortal.");
        assert!(r.passed);
    }

    #[test]
    fn syllogism_fails_no_conclusion() {
        let a = make_anchor("SyllogismChecker");
        let r = check_one(&a, "Premise: All humans are mortal. Socrates is human.");
        assert!(!r.passed);
    }

    #[test]
    fn chain_of_thought_passes() {
        let a = make_anchor("ChainOfThoughtValidator");
        let r = check_one(&a, "First, we analyze the data. Second, we verify the results. Finally, we conclude.");
        assert!(r.passed);
    }

    #[test]
    fn chain_of_thought_fails() {
        let a = make_anchor("ChainOfThoughtValidator");
        let r = check_one(&a, "The answer is 42.");
        assert!(!r.passed);
    }

    #[test]
    fn requires_citation_passes_bracket() {
        let a = make_anchor("RequiresCitation");
        let r = check_one(&a, "Studies show [1] that the result is significant.");
        assert!(r.passed);
    }

    #[test]
    fn requires_citation_passes_author_year() {
        let a = make_anchor("RequiresCitation");
        let r = check_one(&a, "As noted by (Smith, 2024), the findings are robust.");
        assert!(r.passed);
    }

    #[test]
    fn requires_citation_fails() {
        let a = make_anchor("RequiresCitation");
        let r = check_one(&a, "The findings are robust and well-established.");
        assert!(!r.passed);
    }

    #[test]
    fn agnostic_fallback_passes_honest() {
        let a = make_anchor("AgnosticFallback");
        let r = check_one(&a, "I don't know the exact figure, but data suggests around 42.");
        assert!(r.passed);
    }

    #[test]
    fn agnostic_fallback_fails_guessing() {
        let a = make_anchor("AgnosticFallback");
        let r = check_one(&a, "I guess the answer is probably 42.");
        assert!(!r.passed);
    }

    #[test]
    fn check_all_returns_results_per_anchor() {
        let anchors = vec![
            make_anchor("NoHallucination"),
            make_anchor("FactualOnly"),
        ];
        let results = check_all(&anchors, "The temperature is 22 degrees.");
        assert_eq!(results.len(), 2);
        assert!(results[0].passed); // NoHallucination: no hedging
        assert!(results[1].passed); // FactualOnly: no opinion markers
    }

    #[test]
    fn unknown_anchor_passes() {
        let a = make_anchor("CustomAnchor");
        let r = check_one(&a, "Any text");
        assert!(r.passed);
    }

    #[test]
    fn build_retry_feedback_with_breaches() {
        let results = vec![
            AnchorResult {
                anchor_name: "FactualOnly".to_string(),
                passed: false,
                violations: vec!["Opinion marker: 'in my opinion'".to_string()],
                severity: "error",
                confidence: 0.80,
            },
            AnchorResult {
                anchor_name: "AuditTrail".to_string(),
                passed: false,
                violations: vec!["No reasoning markers found".to_string()],
                severity: "warning", // warning — should NOT be in feedback
                confidence: 0.0,
            },
        ];
        let feedback = build_retry_feedback(&results);
        assert!(feedback.is_some());
        let fb = feedback.unwrap();
        assert!(fb.contains("FactualOnly"));
        assert!(!fb.contains("AuditTrail")); // warning excluded
    }

    #[test]
    fn build_retry_feedback_none_when_clean() {
        let results = vec![
            AnchorResult {
                anchor_name: "FactualOnly".to_string(),
                passed: true,
                violations: Vec::new(),
                severity: "error",
                confidence: 1.0,
            },
        ];
        assert!(build_retry_feedback(&results).is_none());
    }

    // ── Confidence scoring tests ──────────────────────────────────

    #[test]
    fn confidence_clean_text_is_high() {
        let a = make_anchor("NoHallucination");
        let r = check_one(&a, "The boiling point of water is 100 degrees Celsius at sea level.");
        assert!(r.passed);
        assert!(r.confidence > 0.90, "Clean text should have high confidence, got {}", r.confidence);
    }

    #[test]
    fn confidence_hedging_reduces_score() {
        let a = make_anchor("NoHallucination");
        let r = check_one(&a, "I think the answer might be probably correct.");
        assert!(!r.passed);
        assert!(r.confidence < 0.70, "Multiple hedging should lower confidence, got {}", r.confidence);
    }

    #[test]
    fn confidence_floor_enforced() {
        let mut a = make_anchor("AuditTrail");
        a.confidence_floor = Some(0.80);
        // Text has one reasoning marker ("therefore") → confidence = 0.20
        let r = check_one(&a, "Therefore the answer is 42.");
        assert!(!r.passed, "Should fail: confidence below floor");
        assert!(r.violations.iter().any(|v| v.contains("below floor")));
    }

    #[test]
    fn confidence_floor_passes_when_met() {
        let mut a = make_anchor("AuditTrail");
        a.confidence_floor = Some(0.50);
        // Text with 3 reasoning markers → confidence = 0.60
        let r = check_one(&a, "Step 1: analyze. Therefore, because the data shows, the conclusion is valid.");
        assert!(r.passed, "Should pass: confidence meets floor");
        assert!(r.confidence >= 0.50);
    }

    #[test]
    fn confidence_floor_none_does_not_enforce() {
        let a = make_anchor("AuditTrail");
        // No confidence_floor set — even low confidence should pass if heuristic passes
        let r = check_one(&a, "Therefore the answer is 42.");
        assert!(r.passed, "Should pass without floor enforcement");
    }

    #[test]
    fn confidence_citation_diversity_increases_score() {
        let a = make_anchor("RequiresCitation");
        let r1 = check_one(&a, "As stated in [1], the finding is robust.");
        let r2 = check_one(&a, "As stated in [1] (Smith, 2024) at https://example.com, the finding is robust.");
        assert!(r2.confidence > r1.confidence, "Multiple citation types should increase confidence");
    }

    #[test]
    fn confidence_chain_of_thought_scales() {
        let a = make_anchor("ChainOfThoughtValidator");
        let r1 = check_one(&a, "First, analyze. Second, conclude.");
        let r2 = check_one(&a, "Step 1: gather data. Step 2: analyze. Then, verify. Finally, conclude.");
        assert!(r2.confidence > r1.confidence, "More step markers should increase confidence");
    }

    #[test]
    fn confidence_pii_multiple_types_drops_sharply() {
        let a = make_anchor("PrivacyGuard");
        let r = check_one(&a, "SSN 123-45-6789 email test@example.com");
        assert!(r.confidence <= 0.50, "Multiple PII types should drop confidence sharply, got {}", r.confidence);
    }

    #[test]
    fn error_breach_count_mixed() {
        let results = vec![
            AnchorResult { anchor_name: "A".into(), passed: false, violations: vec!["x".into()], severity: "error", confidence: 0.50 },
            AnchorResult { anchor_name: "B".into(), passed: true, violations: Vec::new(), severity: "error", confidence: 1.0 },
            AnchorResult { anchor_name: "C".into(), passed: false, violations: vec!["y".into()], severity: "warning", confidence: 0.60 },
        ];
        assert_eq!(error_breach_count(&results), 1);
    }

    // ── Chain tests ──────────────────────────────────────────────

    #[test]
    fn chain_rules_has_5_rules() {
        let rules = chain_rules();
        assert_eq!(rules.len(), 5);
        // Check first rule
        assert_eq!(rules[0].trigger, "NoHallucination");
        assert_eq!(rules[0].enforced, "RequiresCitation");
    }

    #[test]
    fn resolve_chains_on_hallucination_breach() {
        let existing = vec![make_anchor("NoHallucination")];
        let results = vec![AnchorResult {
            anchor_name: "NoHallucination".into(),
            passed: false,
            violations: vec!["hedging".into()],
            severity: "error",
            confidence: 0.40,
        }];

        let chains = resolve_chains(&results, &existing);
        assert_eq!(chains.len(), 1);
        assert_eq!(chains[0].0.enforced, "RequiresCitation");
        assert_eq!(chains[0].1.name, "RequiresCitation");
    }

    #[test]
    fn resolve_chains_skips_already_present() {
        // If RequiresCitation is already in the anchor set, don't chain it
        let existing = vec![
            make_anchor("NoHallucination"),
            make_anchor("RequiresCitation"),
        ];
        let results = vec![AnchorResult {
            anchor_name: "NoHallucination".into(),
            passed: false,
            violations: vec!["hedging".into()],
            severity: "error",
            confidence: 0.40,
        }];

        let chains = resolve_chains(&results, &existing);
        assert_eq!(chains.len(), 0); // Already present — no chain
    }

    #[test]
    fn resolve_chains_no_breach_no_chain() {
        let existing = vec![make_anchor("NoHallucination")];
        let results = vec![AnchorResult {
            anchor_name: "NoHallucination".into(),
            passed: true,
            violations: Vec::new(),
            severity: "error",
            confidence: 0.95,
        }];

        let chains = resolve_chains(&results, &existing);
        assert_eq!(chains.len(), 0); // No breach — no chain
    }

    #[test]
    fn resolve_chains_warning_breach_no_chain() {
        let existing = vec![make_anchor("NoBias")];
        let results = vec![AnchorResult {
            anchor_name: "NoBias".into(),
            passed: false,
            violations: vec!["bias".into()],
            severity: "warning", // Only error-severity triggers chains
            confidence: 0.50,
        }];

        let chains = resolve_chains(&results, &existing);
        assert_eq!(chains.len(), 0);
    }

    #[test]
    fn resolve_chains_multiple_breaches() {
        let existing = vec![
            make_anchor("NoHallucination"),
            make_anchor("FactualOnly"),
        ];
        let results = vec![
            AnchorResult {
                anchor_name: "NoHallucination".into(),
                passed: false,
                violations: vec!["hedging".into()],
                severity: "error",
                confidence: 0.40,
            },
            AnchorResult {
                anchor_name: "FactualOnly".into(),
                passed: false,
                violations: vec!["opinion".into()],
                severity: "error",
                confidence: 0.30,
            },
        ];

        let chains = resolve_chains(&results, &existing);
        // Both trigger RequiresCitation, but deduplicated
        assert_eq!(chains.len(), 1);
        assert_eq!(chains[0].0.enforced, "RequiresCitation");
    }

    #[test]
    fn check_chained_runs_checks() {
        let existing = vec![make_anchor("NoHallucination")];
        let results = vec![AnchorResult {
            anchor_name: "NoHallucination".into(),
            passed: false,
            violations: vec!["hedging".into()],
            severity: "error",
            confidence: 0.40,
        }];

        // Output with no citations — RequiresCitation should fail
        let output = "I think this might be correct, probably.";
        let chain_results = check_chained(&results, &existing, output);
        assert_eq!(chain_results.len(), 1);
        assert_eq!(chain_results[0].1.anchor_name, "RequiresCitation");
        // RequiresCitation checks for citation markers — this output has none
        assert!(!chain_results[0].1.passed);
    }

    #[test]
    fn check_chained_passes_when_enforced_met() {
        let existing = vec![make_anchor("NoHallucination")];
        let results = vec![AnchorResult {
            anchor_name: "NoHallucination".into(),
            passed: false,
            violations: vec!["hedging".into()],
            severity: "error",
            confidence: 0.40,
        }];

        // Output with hedging BUT has citations
        let output = "I think this might be correct [1]. According to Smith (2024), the data supports this.";
        let chain_results = check_chained(&results, &existing, output);
        assert_eq!(chain_results.len(), 1);
        assert_eq!(chain_results[0].1.anchor_name, "RequiresCitation");
        assert!(chain_results[0].1.passed); // Citations present
    }
}

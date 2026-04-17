//! Conversation history — multi-turn message accumulation between steps.
//!
//! Maintains an ordered sequence of user/assistant messages within an
//! execution unit, enabling contextual dialogue where each LLM step
//! sees the full conversation history from prior steps.
//!
//! Message roles:
//!   "user"      — user prompt sent to the LLM
//!   "assistant" — LLM response text
//!
//! The system prompt is NOT part of the history — it is rebuilt per step
//! (unit-level + step-level) and passed separately to the backend.
//!
//! Context window management:
//!   The `ContextWindow` struct enforces a character budget on conversation
//!   history. When history exceeds the budget, oldest turn pairs are dropped
//!   (sliding window). Characters are used as a proxy for tokens (~4 chars/token).
//!
//!   Default budget: 100,000 characters (~25k tokens).
//!   Budget 0 means unlimited (no truncation).

use serde::{Deserialize, Serialize};

/// A single message in a conversation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub role: String,
    pub content: String,
}

impl Message {
    /// Create a user message.
    pub fn user(content: &str) -> Self {
        Message {
            role: "user".to_string(),
            content: content.to_string(),
        }
    }

    /// Create an assistant message.
    pub fn assistant(content: &str) -> Self {
        Message {
            role: "assistant".to_string(),
            content: content.to_string(),
        }
    }
}

/// Conversation history — accumulates messages within an execution unit.
#[derive(Debug, Clone)]
pub struct ConversationHistory {
    messages: Vec<Message>,
}

impl ConversationHistory {
    /// Create an empty conversation history.
    pub fn new() -> Self {
        ConversationHistory {
            messages: Vec::new(),
        }
    }

    /// Add a user message to the history.
    pub fn add_user(&mut self, content: &str) {
        self.messages.push(Message::user(content));
    }

    /// Add an assistant message to the history.
    pub fn add_assistant(&mut self, content: &str) {
        self.messages.push(Message::assistant(content));
    }

    /// Get all messages as a slice.
    pub fn messages(&self) -> &[Message] {
        &self.messages
    }

    /// Number of messages in the history.
    pub fn len(&self) -> usize {
        self.messages.len()
    }

    /// Whether the history is empty.
    pub fn is_empty(&self) -> bool {
        self.messages.is_empty()
    }

    /// Number of turn pairs (user+assistant) completed.
    pub fn turn_count(&self) -> usize {
        self.messages.len() / 2
    }

    /// Total character count across all messages (for context budget estimation).
    pub fn total_chars(&self) -> usize {
        self.messages.iter().map(|m| m.content.len()).sum()
    }

    /// Clear all messages.
    pub fn clear(&mut self) {
        self.messages.clear();
    }

    /// Enforce a character budget by dropping the oldest turn pairs.
    ///
    /// Removes messages from the front in pairs (user + assistant) until
    /// `total_chars()` is at or below `max_chars`. If a single turn exceeds
    /// the budget, it is kept (we never drop all context — at minimum the
    /// most recent turn is preserved).
    ///
    /// Returns the number of messages dropped.
    pub fn truncate_to_budget(&mut self, max_chars: usize) -> usize {
        if max_chars == 0 || self.total_chars() <= max_chars {
            return 0;
        }

        let mut dropped = 0;

        // Drop oldest turn pairs (2 messages at a time) while over budget
        // Always keep at least 2 messages (the most recent turn).
        while self.messages.len() > 2 && self.total_chars() > max_chars {
            // Remove first two messages (user + assistant pair)
            self.messages.remove(0);
            self.messages.remove(0);
            dropped += 2;
        }

        dropped
    }

    /// Count of messages that would be dropped to meet a budget,
    /// without actually modifying the history.
    pub fn overflow_count(&self, max_chars: usize) -> usize {
        if max_chars == 0 || self.total_chars() <= max_chars {
            return 0;
        }

        let mut chars = self.total_chars();
        let mut dropped = 0;
        let mut idx = 0;

        while (self.messages.len() - dropped) > 2 && chars > max_chars {
            chars -= self.messages[idx].content.len();
            chars -= self.messages[idx + 1].content.len();
            dropped += 2;
            idx += 2;
        }

        dropped
    }
}

/// Context window configuration — controls conversation budget.
///
/// Characters are used as a proxy for tokens. A rough heuristic:
///   ~4 characters ≈ 1 token (English text average).
///
/// The budget covers only conversation history messages, not the
/// system prompt (which is always sent separately).
#[derive(Debug, Clone)]
pub struct ContextWindow {
    /// Maximum characters allowed in conversation history.
    /// 0 means unlimited.
    pub max_chars: usize,
    /// Total messages dropped across all truncations in this unit.
    pub total_dropped: usize,
    /// Number of truncation events.
    pub truncation_count: usize,
}

/// Default budget: 100,000 chars (~25k tokens).
const DEFAULT_CONTEXT_BUDGET: usize = 100_000;

impl ContextWindow {
    /// Create with default budget (100k chars).
    pub fn new() -> Self {
        ContextWindow {
            max_chars: DEFAULT_CONTEXT_BUDGET,
            total_dropped: 0,
            truncation_count: 0,
        }
    }

    /// Create with a custom character budget. 0 = unlimited.
    pub fn with_budget(max_chars: usize) -> Self {
        ContextWindow {
            max_chars,
            total_dropped: 0,
            truncation_count: 0,
        }
    }

    /// Create with unlimited budget (no truncation).
    pub fn unlimited() -> Self {
        ContextWindow {
            max_chars: 0,
            total_dropped: 0,
            truncation_count: 0,
        }
    }

    /// Enforce the budget on a conversation history.
    /// Returns the number of messages dropped (0 if within budget).
    pub fn enforce(&mut self, history: &mut ConversationHistory) -> usize {
        let dropped = history.truncate_to_budget(self.max_chars);
        if dropped > 0 {
            self.total_dropped += dropped;
            self.truncation_count += 1;
        }
        dropped
    }

    /// Whether any truncation has occurred.
    pub fn was_truncated(&self) -> bool {
        self.total_dropped > 0
    }

    /// Estimated token count from character count (~4 chars/token).
    pub fn estimate_tokens(chars: usize) -> usize {
        (chars + 3) / 4 // ceiling division
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_history_is_empty() {
        let h = ConversationHistory::new();
        assert!(h.is_empty());
        assert_eq!(h.len(), 0);
        assert_eq!(h.turn_count(), 0);
        assert_eq!(h.total_chars(), 0);
    }

    #[test]
    fn add_user_and_assistant() {
        let mut h = ConversationHistory::new();
        h.add_user("Hello");
        h.add_assistant("Hi there");
        assert_eq!(h.len(), 2);
        assert_eq!(h.turn_count(), 1);
        assert!(!h.is_empty());
    }

    #[test]
    fn messages_preserve_order() {
        let mut h = ConversationHistory::new();
        h.add_user("First");
        h.add_assistant("Second");
        h.add_user("Third");
        h.add_assistant("Fourth");

        let msgs = h.messages();
        assert_eq!(msgs.len(), 4);
        assert_eq!(msgs[0].role, "user");
        assert_eq!(msgs[0].content, "First");
        assert_eq!(msgs[1].role, "assistant");
        assert_eq!(msgs[1].content, "Second");
        assert_eq!(msgs[2].role, "user");
        assert_eq!(msgs[2].content, "Third");
        assert_eq!(msgs[3].role, "assistant");
        assert_eq!(msgs[3].content, "Fourth");
    }

    #[test]
    fn total_chars_sums_all() {
        let mut h = ConversationHistory::new();
        h.add_user("abc");     // 3
        h.add_assistant("de"); // 2
        h.add_user("f");       // 1
        assert_eq!(h.total_chars(), 6);
    }

    #[test]
    fn clear_resets() {
        let mut h = ConversationHistory::new();
        h.add_user("Hello");
        h.add_assistant("Hi");
        h.clear();
        assert!(h.is_empty());
        assert_eq!(h.len(), 0);
        assert_eq!(h.turn_count(), 0);
    }

    #[test]
    fn message_constructors() {
        let u = Message::user("question");
        assert_eq!(u.role, "user");
        assert_eq!(u.content, "question");

        let a = Message::assistant("answer");
        assert_eq!(a.role, "assistant");
        assert_eq!(a.content, "answer");
    }

    #[test]
    fn turn_count_with_odd_messages() {
        let mut h = ConversationHistory::new();
        h.add_user("Hello");
        // No assistant response yet
        assert_eq!(h.turn_count(), 0); // integer division: 1/2 = 0
        h.add_assistant("Hi");
        assert_eq!(h.turn_count(), 1);
        h.add_user("Next");
        assert_eq!(h.turn_count(), 1); // 3/2 = 1
    }

    #[test]
    fn multi_turn_accumulation() {
        let mut h = ConversationHistory::new();
        for i in 0..5 {
            h.add_user(&format!("Q{i}"));
            h.add_assistant(&format!("A{i}"));
        }
        assert_eq!(h.len(), 10);
        assert_eq!(h.turn_count(), 5);
        // Verify last pair
        let msgs = h.messages();
        assert_eq!(msgs[8].content, "Q4");
        assert_eq!(msgs[9].content, "A4");
    }

    // ── Context window tests ──────────────────────────────────────────

    #[test]
    fn truncate_within_budget_is_noop() {
        let mut h = ConversationHistory::new();
        h.add_user("short");
        h.add_assistant("also short");
        let dropped = h.truncate_to_budget(1000);
        assert_eq!(dropped, 0);
        assert_eq!(h.len(), 2);
    }

    #[test]
    fn truncate_drops_oldest_turns() {
        let mut h = ConversationHistory::new();
        // 5 turns, each pair = "QN" (2) + "AN" (2) = 4 chars
        for i in 0..5 {
            h.add_user(&format!("Q{i}"));
            h.add_assistant(&format!("A{i}"));
        }
        assert_eq!(h.total_chars(), 20); // 10 messages × 2 chars

        // Budget = 8 chars → should keep 2 turns (8 chars), drop 3 turns (6 msgs)
        let dropped = h.truncate_to_budget(8);
        assert_eq!(dropped, 6);
        assert_eq!(h.len(), 4);
        assert_eq!(h.turn_count(), 2);

        // Oldest surviving should be Q3
        let msgs = h.messages();
        assert_eq!(msgs[0].content, "Q3");
        assert_eq!(msgs[1].content, "A3");
        assert_eq!(msgs[2].content, "Q4");
        assert_eq!(msgs[3].content, "A4");
    }

    #[test]
    fn truncate_preserves_minimum_turn() {
        let mut h = ConversationHistory::new();
        h.add_user(&"x".repeat(500));
        h.add_assistant(&"y".repeat(500));
        // Budget = 10 → way under, but we keep at least the most recent turn
        let dropped = h.truncate_to_budget(10);
        assert_eq!(dropped, 0);
        assert_eq!(h.len(), 2); // preserved
    }

    #[test]
    fn truncate_unlimited_budget_is_noop() {
        let mut h = ConversationHistory::new();
        for i in 0..100 {
            h.add_user(&format!("Question {i}"));
            h.add_assistant(&format!("Answer {i}"));
        }
        let dropped = h.truncate_to_budget(0); // 0 = unlimited
        assert_eq!(dropped, 0);
        assert_eq!(h.len(), 200);
    }

    #[test]
    fn overflow_count_without_mutation() {
        let mut h = ConversationHistory::new();
        for i in 0..5 {
            h.add_user(&format!("Q{i}"));
            h.add_assistant(&format!("A{i}"));
        }
        let count = h.overflow_count(8);
        assert_eq!(count, 6); // Same as truncate would drop
        assert_eq!(h.len(), 10); // Not modified
    }

    #[test]
    fn context_window_default_budget() {
        let cw = ContextWindow::new();
        assert_eq!(cw.max_chars, 100_000);
        assert_eq!(cw.total_dropped, 0);
        assert_eq!(cw.truncation_count, 0);
        assert!(!cw.was_truncated());
    }

    #[test]
    fn context_window_custom_budget() {
        let cw = ContextWindow::with_budget(50_000);
        assert_eq!(cw.max_chars, 50_000);
    }

    #[test]
    fn context_window_unlimited() {
        let cw = ContextWindow::unlimited();
        assert_eq!(cw.max_chars, 0);
    }

    #[test]
    fn context_window_enforce_tracks_stats() {
        let mut cw = ContextWindow::with_budget(8);
        let mut h = ConversationHistory::new();
        for i in 0..5 {
            h.add_user(&format!("Q{i}"));
            h.add_assistant(&format!("A{i}"));
        }

        let dropped = cw.enforce(&mut h);
        assert_eq!(dropped, 6);
        assert!(cw.was_truncated());
        assert_eq!(cw.total_dropped, 6);
        assert_eq!(cw.truncation_count, 1);

        // Second enforce — still within budget
        let dropped2 = cw.enforce(&mut h);
        assert_eq!(dropped2, 0);
        assert_eq!(cw.truncation_count, 1); // No new truncation
    }

    #[test]
    fn context_window_enforce_multiple_truncations() {
        let mut cw = ContextWindow::with_budget(20);
        let mut h = ConversationHistory::new();

        // First batch: add 3 turns
        for i in 0..3 {
            h.add_user(&format!("Q{i}"));
            h.add_assistant(&format!("A{i}"));
        }
        cw.enforce(&mut h); // 12 chars < 20, no truncation

        // Second batch: add 5 more turns
        for i in 3..8 {
            h.add_user(&format!("Q{i}"));
            h.add_assistant(&format!("A{i}"));
        }
        let dropped = cw.enforce(&mut h); // 32 chars > 20
        assert!(dropped > 0);
        assert_eq!(cw.truncation_count, 1);
        assert!(h.total_chars() <= 20);
    }

    #[test]
    fn estimate_tokens() {
        assert_eq!(ContextWindow::estimate_tokens(0), 0);
        assert_eq!(ContextWindow::estimate_tokens(4), 1);
        assert_eq!(ContextWindow::estimate_tokens(5), 2);
        assert_eq!(ContextWindow::estimate_tokens(100), 25);
        assert_eq!(ContextWindow::estimate_tokens(100_000), 25_000);
    }
}

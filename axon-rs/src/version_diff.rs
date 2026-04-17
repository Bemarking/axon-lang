//! Version Diff — line-based source diff between flow versions.
//!
//! Compares source snapshots stored in the VersionRegistry to show what
//! changed between two deployments of the same flow.
//!
//! Uses a longest-common-subsequence (LCS) algorithm for line-level diffs,
//! producing a unified-style output with context lines.

use std::io::IsTerminal;

use crate::flow_version::VersionRegistry;

// ── Diff structures ─────────────────────────────────────────────────────

/// A line-level diff between two source texts.
#[derive(Debug, Clone, serde::Serialize)]
pub struct VersionDiff {
    pub flow_name: String,
    pub from_version: u32,
    pub to_version: u32,
    pub from_hash: String,
    pub to_hash: String,
    pub identical: bool,
    pub hunks: Vec<DiffHunk>,
    pub summary: DiffSummary,
}

/// A contiguous region of changes with surrounding context.
#[derive(Debug, Clone, serde::Serialize)]
pub struct DiffHunk {
    pub old_start: usize,
    pub old_count: usize,
    pub new_start: usize,
    pub new_count: usize,
    pub lines: Vec<DiffLine>,
}

/// A single line in the diff output.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct DiffLine {
    pub kind: LineKind,
    pub content: String,
}

/// Kind of a diff line.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum LineKind {
    Context,
    Added,
    Removed,
}

/// Summary statistics for a diff.
#[derive(Debug, Clone, serde::Serialize)]
pub struct DiffSummary {
    pub lines_added: usize,
    pub lines_removed: usize,
    pub lines_unchanged: usize,
    pub hunks: usize,
}

// ── LCS-based diff ──────────────────────────────────────────────────────

/// Compute a line-level diff between two source strings.
pub fn diff_lines(old: &str, new: &str) -> Vec<DiffLine> {
    let old_lines: Vec<&str> = old.lines().collect();
    let new_lines: Vec<&str> = new.lines().collect();

    let edits = lcs_diff(&old_lines, &new_lines);
    edits
}

/// LCS-based diff producing a sequence of DiffLine entries.
fn lcs_diff(old: &[&str], new: &[&str]) -> Vec<DiffLine> {
    let m = old.len();
    let n = new.len();

    // Build LCS table
    let mut table = vec![vec![0u32; n + 1]; m + 1];
    for i in 1..=m {
        for j in 1..=n {
            if old[i - 1] == new[j - 1] {
                table[i][j] = table[i - 1][j - 1] + 1;
            } else {
                table[i][j] = table[i - 1][j].max(table[i][j - 1]);
            }
        }
    }

    // Backtrack to produce diff
    let mut result = Vec::new();
    let mut i = m;
    let mut j = n;

    while i > 0 || j > 0 {
        if i > 0 && j > 0 && old[i - 1] == new[j - 1] {
            result.push(DiffLine {
                kind: LineKind::Context,
                content: old[i - 1].to_string(),
            });
            i -= 1;
            j -= 1;
        } else if j > 0 && (i == 0 || table[i][j - 1] >= table[i - 1][j]) {
            result.push(DiffLine {
                kind: LineKind::Added,
                content: new[j - 1].to_string(),
            });
            j -= 1;
        } else {
            result.push(DiffLine {
                kind: LineKind::Removed,
                content: old[i - 1].to_string(),
            });
            i -= 1;
        }
    }

    result.reverse();
    result
}

/// Group diff lines into hunks with context.
pub fn make_hunks(lines: &[DiffLine], context: usize) -> Vec<DiffHunk> {
    if lines.is_empty() {
        return Vec::new();
    }

    // Find ranges of changed lines
    let mut change_positions: Vec<usize> = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        if line.kind != LineKind::Context {
            change_positions.push(i);
        }
    }

    if change_positions.is_empty() {
        return Vec::new();
    }

    // Group changes into hunks (merge if context overlaps)
    let mut hunks: Vec<DiffHunk> = Vec::new();
    let mut hunk_start = change_positions[0].saturating_sub(context);
    let mut hunk_end = (change_positions[0] + context + 1).min(lines.len());

    for &pos in &change_positions[1..] {
        let this_start = pos.saturating_sub(context);
        let this_end = (pos + context + 1).min(lines.len());

        if this_start <= hunk_end {
            // Merge with current hunk
            hunk_end = this_end;
        } else {
            // Emit current hunk and start new one
            hunks.push(build_hunk(&lines[hunk_start..hunk_end], hunk_start, lines));
            hunk_start = this_start;
            hunk_end = this_end;
        }
    }
    hunks.push(build_hunk(&lines[hunk_start..hunk_end], hunk_start, lines));

    hunks
}

fn build_hunk(hunk_lines: &[DiffLine], start_in_diff: usize, all_lines: &[DiffLine]) -> DiffHunk {
    // Compute old/new line numbers
    let mut old_start = 1usize;
    let mut new_start = 1usize;
    for line in &all_lines[..start_in_diff] {
        match line.kind {
            LineKind::Context => { old_start += 1; new_start += 1; }
            LineKind::Removed => { old_start += 1; }
            LineKind::Added => { new_start += 1; }
        }
    }

    let mut old_count = 0;
    let mut new_count = 0;
    for line in hunk_lines {
        match line.kind {
            LineKind::Context => { old_count += 1; new_count += 1; }
            LineKind::Removed => { old_count += 1; }
            LineKind::Added => { new_count += 1; }
        }
    }

    DiffHunk {
        old_start,
        old_count,
        new_start,
        new_count,
        lines: hunk_lines.to_vec(),
    }
}

// ── Version-aware diff ──────────────────────────────────────────────────

/// Diff two versions of a flow from the registry.
pub fn diff_versions(
    registry: &VersionRegistry,
    flow_name: &str,
    from_version: u32,
    to_version: u32,
) -> Result<VersionDiff, String> {
    let from = registry.get_version(flow_name, from_version)
        .ok_or_else(|| format!("version {} not found for flow '{}'", from_version, flow_name))?;
    let to = registry.get_version(flow_name, to_version)
        .ok_or_else(|| format!("version {} not found for flow '{}'", to_version, flow_name))?;

    let lines = diff_lines(&from.source, &to.source);

    let lines_added = lines.iter().filter(|l| l.kind == LineKind::Added).count();
    let lines_removed = lines.iter().filter(|l| l.kind == LineKind::Removed).count();
    let lines_unchanged = lines.iter().filter(|l| l.kind == LineKind::Context).count();
    let identical = lines_added == 0 && lines_removed == 0;

    let hunks = make_hunks(&lines, 3);

    Ok(VersionDiff {
        flow_name: flow_name.to_string(),
        from_version,
        to_version,
        from_hash: from.source_hash.clone(),
        to_hash: to.source_hash.clone(),
        identical,
        hunks: hunks.clone(),
        summary: DiffSummary {
            lines_added,
            lines_removed,
            lines_unchanged,
            hunks: hunks.len(),
        },
    })
}

// ── Display ─────────────────────────────────────────────────────────────

/// Print a version diff in human-readable unified format.
pub fn print_version_diff(diff: &VersionDiff) {
    let use_color = std::io::stdout().is_terminal();

    let bold = if use_color { "\x1b[1m" } else { "" };
    let red = if use_color { "\x1b[31m" } else { "" };
    let green = if use_color { "\x1b[32m" } else { "" };
    let cyan = if use_color { "\x1b[36m" } else { "" };
    let dim = if use_color { "\x1b[2m" } else { "" };
    let reset = if use_color { "\x1b[0m" } else { "" };

    println!("{}--- {}/v{} ({}){}",
        bold, diff.flow_name, diff.from_version, diff.from_hash, reset);
    println!("{}+++ {}/v{} ({}){}",
        bold, diff.flow_name, diff.to_version, diff.to_hash, reset);

    if diff.identical {
        println!("{}(identical){}", dim, reset);
        return;
    }

    for hunk in &diff.hunks {
        println!("{}@@ -{},{} +{},{} @@{}",
            cyan, hunk.old_start, hunk.old_count,
            hunk.new_start, hunk.new_count, reset);

        for line in &hunk.lines {
            match line.kind {
                LineKind::Context => println!(" {}", line.content),
                LineKind::Added => println!("{}+{}{}", green, line.content, reset),
                LineKind::Removed => println!("{}-{}{}", red, line.content, reset),
            }
        }
    }

    println!();
    println!("{}{} added, {} removed, {} unchanged{}",
        dim, diff.summary.lines_added, diff.summary.lines_removed,
        diff.summary.lines_unchanged, reset);
}

// ── Tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flow_version::VersionRegistry;

    #[test]
    fn diff_identical_sources() {
        let src = "line1\nline2\nline3";
        let lines = diff_lines(src, src);
        assert!(lines.iter().all(|l| l.kind == LineKind::Context));
        assert_eq!(lines.len(), 3);
    }

    #[test]
    fn diff_added_lines() {
        let old = "line1\nline3";
        let new = "line1\nline2\nline3";
        let lines = diff_lines(old, new);

        let added: Vec<_> = lines.iter().filter(|l| l.kind == LineKind::Added).collect();
        assert_eq!(added.len(), 1);
        assert_eq!(added[0].content, "line2");
    }

    #[test]
    fn diff_removed_lines() {
        let old = "line1\nline2\nline3";
        let new = "line1\nline3";
        let lines = diff_lines(old, new);

        let removed: Vec<_> = lines.iter().filter(|l| l.kind == LineKind::Removed).collect();
        assert_eq!(removed.len(), 1);
        assert_eq!(removed[0].content, "line2");
    }

    #[test]
    fn diff_modified_line() {
        let old = "line1\nold content\nline3";
        let new = "line1\nnew content\nline3";
        let lines = diff_lines(old, new);

        let removed: Vec<_> = lines.iter().filter(|l| l.kind == LineKind::Removed).collect();
        let added: Vec<_> = lines.iter().filter(|l| l.kind == LineKind::Added).collect();
        assert_eq!(removed.len(), 1);
        assert_eq!(removed[0].content, "old content");
        assert_eq!(added.len(), 1);
        assert_eq!(added[0].content, "new content");
    }

    #[test]
    fn diff_empty_to_content() {
        let lines = diff_lines("", "line1\nline2");
        let added: Vec<_> = lines.iter().filter(|l| l.kind == LineKind::Added).collect();
        assert_eq!(added.len(), 2);
    }

    #[test]
    fn diff_content_to_empty() {
        let lines = diff_lines("line1\nline2", "");
        let removed: Vec<_> = lines.iter().filter(|l| l.kind == LineKind::Removed).collect();
        assert_eq!(removed.len(), 2);
    }

    #[test]
    fn diff_both_empty() {
        let lines = diff_lines("", "");
        assert!(lines.is_empty());
    }

    #[test]
    fn hunks_with_context() {
        let old = "a\nb\nc\nd\ne\nf\ng\nh";
        let new = "a\nb\nX\nd\ne\nf\ng\nh";
        let lines = diff_lines(old, new);
        let hunks = make_hunks(&lines, 2);

        assert_eq!(hunks.len(), 1);
        // Context of 2 around the change at line 3
        assert!(hunks[0].lines.len() <= 7); // 2 before + removed + added + 2 after (up to available)
    }

    #[test]
    fn hunks_separate_changes() {
        // Two changes far apart (more than 2*context lines between them)
        let old = "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12";
        let new = "1\nX\n3\n4\n5\n6\n7\n8\n9\n10\nY\n12";
        let lines = diff_lines(old, new);
        let hunks = make_hunks(&lines, 1);

        assert_eq!(hunks.len(), 2);
    }

    #[test]
    fn hunks_empty_for_identical() {
        let src = "a\nb\nc";
        let lines = diff_lines(src, src);
        let hunks = make_hunks(&lines, 3);
        assert!(hunks.is_empty());
    }

    #[test]
    fn diff_versions_from_registry() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];
        reg.record_deploy(&flows, "line1\nline2\nline3", "f.axon", "anthropic");
        reg.record_deploy(&flows, "line1\nmodified\nline3\nline4", "f.axon", "anthropic");

        let diff = diff_versions(&reg, "F", 1, 2).unwrap();
        assert!(!diff.identical);
        assert_eq!(diff.flow_name, "F");
        assert_eq!(diff.from_version, 1);
        assert_eq!(diff.to_version, 2);
        assert_eq!(diff.summary.lines_added, 2); // "modified" + "line4"
        assert_eq!(diff.summary.lines_removed, 1); // "line2"
    }

    #[test]
    fn diff_versions_identical() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];
        let src = "same source";
        reg.record_deploy(&flows, src, "f.axon", "anthropic");
        reg.record_deploy(&flows, src, "f.axon", "anthropic");

        let diff = diff_versions(&reg, "F", 1, 2).unwrap();
        assert!(diff.identical);
        assert_eq!(diff.summary.lines_added, 0);
        assert_eq!(diff.summary.lines_removed, 0);
        assert!(diff.hunks.is_empty());
    }

    #[test]
    fn diff_versions_not_found() {
        let reg = VersionRegistry::new();
        assert!(diff_versions(&reg, "NoFlow", 1, 2).is_err());
    }

    #[test]
    fn diff_versions_version_not_found() {
        let mut reg = VersionRegistry::new();
        let flows = vec!["F".to_string()];
        reg.record_deploy(&flows, "src", "f.axon", "anthropic");
        assert!(diff_versions(&reg, "F", 1, 99).is_err());
    }

    #[test]
    fn diff_summary_serializes() {
        let summary = DiffSummary {
            lines_added: 5,
            lines_removed: 3,
            lines_unchanged: 10,
            hunks: 2,
        };
        let json = serde_json::to_value(&summary).unwrap();
        assert_eq!(json["lines_added"], 5);
        assert_eq!(json["hunks"], 2);
    }

    #[test]
    fn line_kind_serializes_lowercase() {
        let line = DiffLine { kind: LineKind::Added, content: "x".into() };
        let json = serde_json::to_value(&line).unwrap();
        assert_eq!(json["kind"], "added");
    }

    #[test]
    fn hunk_line_numbers_correct() {
        let old = "a\nb\nc";
        let new = "a\nX\nc";
        let lines = diff_lines(old, new);
        let hunks = make_hunks(&lines, 1);

        assert_eq!(hunks.len(), 1);
        assert_eq!(hunks[0].old_start, 1); // starts at line 1 (context)
        assert_eq!(hunks[0].new_start, 1);
    }
}

# Codex Offline Compression Summary

This is a candidate Claude Code JSONL compact summary generated outside Claude. It summarizes only older records from the selected active chain. Rewound, inactive, and unattributed records are excluded.

## 1. Scope

- Source file label: {input_path}
- Original record count: {total_records}
- Active-chain records selected for summary: {omitted_record_count} records before the preserved active-chain window
- Recent raw active-chain records preserved: {recent_record_count} records
- Physical line window of preserved records: {recent_start} to {recent_end}
- Time span summarized: {first_ts} to {last_omitted_ts}
- Time span preserved: {first_kept_ts} to {last_kept_ts}
- Session distribution: {session_counts}
- Common working directories: {cwd_counts}
- Claude Code versions: {version_counts}

## 2. Structural Overview

- Record types: {type_counts}
- System subtypes: {subtype_counts}
- Tool invocation overview: {tool_counts}
- Attachment / hook overview: {attachment_counts}
- File history snapshots: {file_history_count}
- Existing compact summaries summarized into this layer: {existing_compact_count}
- Human user prompts: {human_user_count}
- Tool-result user records: {tool_result_user_count}

## 3. Long-Term Memory Ledger

{long_term_memory}

## 4. Early / Middle Summary

### 4.1 Early
{early_summary}

### 4.2 Middle
{middle_summary}

## 5. Assistant Behavior and Evidence

### 5.1 Assistant research decisions and rationales
{assistant_decision_items}

### 5.2 Key assistant outputs
{assistant_items}

### 5.3 Key paths and filenames
{path_counts}

### 5.4 Errors and anomalies
{error_section}

## 6. Existing Compact Records

### 6.1 compact_boundary layer
{compact_boundary_items}

### 6.2 isCompactSummary layer
{compact_items}

### 6.3 Repeated compression policy
- Treat previous compact layers as prior memory, not as live stacked context.
- Fold still-relevant facts into the current compact summary.
- Keep provenance, hashes, file labels, and line ranges in metadata or sidecars.
- If prior layers themselves are too large, switch to a long-term memory ledger.

## 7. Recent Raw Preservation

{recent_preservation_notes}

## 8. Important Reminders

- Exact wording lives in the source JSONL or external archives.
- This file is a candidate transcript rewrite, not a proof of Claude runtime behavior.
- For humanities, law, art, strategy, planning, history, feasibility, and document-research sessions, preserve user goals, reasons, rejected alternatives, version changes, provenance, unresolved questions, and risk judgments.
- Project-specific facts must come from the JSONL or an explicit handoff summary, not from hardcoded skill memory.

---
name: claude-jsonl-compressor
description: Compress one Claude Code JSONL session with strict active-branch isolation, model-authored semantic summaries by default, recent raw context for rewind, validated compact-style output, transactional backup/replacement for one live .claude/projects file, and an independent byte-preserving Read.pages compatibility repair. Use for compressing, shrinking, summarizing, preflighting, replacing, or repairing Claude CLI/Claude Code JSONL transcripts.
---

# Claude JSONL Compressor

Operate on exactly one authoritative JSONL. Never merge another branch or session automatically.

Public package: `1.0.0-rc.1`. Internal engine: `v10`. Model-pack schema: `v11`.

## Safety Invariants

1. Model-assisted semantic summary generation is the default. Use deterministic summary only when the user explicitly requests fallback.
2. Determine the active branch from structure before reading text for semantic importance.
3. The physically last `type: "last-prompt"` record is the automatic authority. Do not skip a malformed latest pointer to revive an older one.
4. Rewound/inactive branch text must not enter the model pack, model summary, deterministic appendix, prior-summary verbatim block, recent raw records, side records, or output API-message chain.
5. Only the active-chain old segment may be summarized. The model cannot select a leaf, change the partition, or restore excluded records.
6. Preserve the recent active suffix byte-for-field except for the single parent edge that connects its first record to the new compact summary and optional explicit `sessionId` normalization.
7. Preserve unknown fields on retained records. Project the authoritative `last-prompt` object and retain its unknown fields; output exactly one final pointer.
8. Never install `tiktoken`, `regex`, PyYAML, or another package for this workflow. Runtime code uses the Python standard library.
9. Never write process files inside `.claude`. A live replacement may leave only the requested JSONL and its numbered backup beside it.
10. Do not run Claude CLI for validation unless the user explicitly asks. Structural validation is mandatory regardless.
11. Do not put project-specific facts, paths, identifiers, or prior-session content into this skill.
12. Treat the model summary as model-authored and source-anchored, not model-validated truth. Require v11 request binding and one exact source excerpt per mandatory semantic/prior-summary record.

## Resolve The Operation First

### Candidate Mode

Use when the user provides distinct input and output paths.

- Do not modify the input.
- Write the candidate to the requested output.
- Write `<output>.report.md` and `<output>.validation.json` beside it.
- Refuse identical input/output paths.
- Refuse a direct output under `.claude/projects`; use live replacement mode there.

### Live Replacement Mode

Use when the user explicitly asks to compress one existing `.claude/projects/<project>/<session>.jsonl` in place, including prompts that give the same path as input and output.

- Treat the path as `--input`; do not pass `--output`.
- Require an existing regular `.jsonl` target under `.claude/projects`; use `--replace-original`, `--confirm-session-closed`, and a work directory outside the entire `.claude` tree. The flag records caller acknowledgement; it does not detect a process lock.
- The script creates `<session>.jsonl.backup`, then `.backup1`, `.backup2`, and so on with exclusive creation.
- Candidate, model pack, model summary, validation and report files stay under `--work-dir`.
- The filename stem remains the target session ID unless the user explicitly supplies another one.
- Replacement occurs only after candidate validation and a full-byte SHA-256 source recheck.
- A failed post-replacement validation restores the original bytes and returns an error.

### Read.pages Compatibility Repair

This is a separate operation. Do not invoke it implicitly during compression.

- It removes only the exact `pages` member from structured assistant `tool_use` blocks whose name is exactly `Read`, whose `input.file_path` exists, and whose tool ID has a matching `tool_result` in the selected scope.
- Default scope is the strict active chain. `--scope all` is explicit.
- Pending calls are reported and left unchanged.
- All bytes outside the planned JSON-member deletion spans remain identical, including BOM, CRLF/LF, escaping, Unicode and unknown fields.

## Mandatory Preflight

Resolve the skill root without hardcoding a user's machine:

```powershell
$skill = "$env:USERPROFILE\.codex\skills\claude-jsonl-compressor"
```

Analyze the authoritative resume path before making a model pack or candidate:

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\path\session.jsonl" `
  --analyze-resume-path
```

Strict active mode stops before writing any pack, candidate, sidecar or backup when the authority is absent, malformed, dangling, cyclic, has unsafe/recurring session lineage, has ordinary-message physical parent inversion, contains a malformed `parentUuid`, or is UUID-ambiguous.

After partitioning, run the shared validator on the authoritative logical active chain plus its projected pointer. Old malformed tool exchanges, duplicate tool IDs, or compact-pair metadata on that chain must stop before semantic evidence generation; damage confined to excluded inactive branches remains excluded and does not become summary text.

When strict preflight reports an unusual or ambiguous topology, stop with zero writes and explain the structural status without copying excluded transcript text. Ask the user to confirm a specific recovery control only when one is applicable. Do not infer confirmation from the original compression request, and never retry automatically in compatibility mode. The Python CLI remains non-interactive.

Recovery controls:

- Use `--resume-leaf UUID` only when the user explicitly identifies the desired leaf. The report marks `manualOverride: true` and labels the mode `active-chain-manual-override`, not default strict `active-chain`.
- Use `--preserve-physical-tail` only when the user explicitly requests compatibility behavior. It does not provide inactive-branch exclusion guarantees.
- Default post-pointer extension is zero. Use `--max-post-last-prompt-extension N` only for a physically post-pointer, direct, same-session, tool-result-only closure of every pending tool ID. Ordinary user/assistant conversation, system/hook records, partial closure and unrelated results are rejected.

Observed-format compatibility remains narrow and deterministic:

- An acyclic parent chain may contain physically inverted edges only when every such edge is same-session `attachment -> attachment`. Output serializes those records in logical parent order.
- A mixed-session active chain is accepted only when session runs move forward without returning to an earlier session and both the final leaf and authoritative pointer use the final session. Every earlier session is forced into `summaryIndexes`; the recent raw suffix contains only the final session.
- If tool pairing would move the raw cut back across that session transition, stop. Do not normalize or invent a cross-session raw exchange.

## Default Model-Assisted Workflow

The Python program does not call a model. Codex performs the semantic step between two deterministic script passes.

This addresses the 1M-versus-200k context problem by removing inactive branches, recent raw records, low-value payload repetition and non-semantic structure before model review. The bounded pack contains a complete full-text ledger of every non-empty older active human message and every older active assistant `text`/`thinking` message, plus selected source/tool evidence and line anchors. A source-text warning such as U+FFFD is reported but does not discard the rest of a mandatory record. The default pack ceilings are 500,000 characters and a conservative 150,000-token local estimate, leaving room in a typical 200k summarizer context. If mandatory evidence does not fit, generation stops instead of sampling it away; raise a ceiling only when the chosen model can read the result.

### Pass 1: Generate The Evidence Pack

Use identical selection settings in both passes:

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\path\session.jsonl" `
  --write-model-pack "C:\work\run\session.model-pack.md" `
  --target-ratio 0.30 `
  --min-recent-records 120 `
  --summary-char-budget 60000 `
  --target-estimated-tokens 150000 `
  --model-pack-char-budget 500000 `
  --model-pack-estimated-token-budget 150000
```

The two pack ceilings apply together. Complete human/assistant semantic records,
prior summaries, handoff lines and required groups are mandatory. Optional
source/tool/system/error evidence stops at either ceiling and reports
`evidence_truncated`. Never install a tokenizer for this workflow.

When the user gives an approximate compressed Messages-token ceiling, pass it directly instead of inventing a tokenizer workflow:

```powershell
  --target-estimated-tokens 150000
```

This candidate-output gate is distinct from `--model-pack-estimated-token-budget`.
It is the built-in zero-dependency estimate for transcript Messages only. It
covers complete retained structured message payloads, including thinking,
`tool_use.input`, `tool_result`, and `toolUseResult`. It excludes the system
prompt, tool schemas, MCP, agents, skills, memory files and runtime additions.
Never claim it predicts Claude `/context` total exactly. Treat `--target-ratio`
only as approximate byte planning; only an explicit
`--target-estimated-tokens` value is a hard candidate-output estimate gate.

Require `--summary-char-budget >= 4000`. Do not weaken this floor or publish a blank compact summary.

For `.claude` input, the pack path must be outside `.claude`.

### Model Step: Write The Summary

Read the generated pack and write a Markdown summary from that pack only.

Copy its leading metadata comment exactly. Schema v11 binds:

- `source_sha256`
- `summary_source_sha256`
- `evidence_anchor_lines_digest`
- `required_anchor_groups_digest`
- `handoff_summary_digest`
- `pack_request_digest`
- `required_claim_sources_digest`

Summary rules:

1. Cite every substantive JSONL-backed statement with one or more displayed `L<number>` anchors.
2. Cite every handoff-backed statement with a displayed `H<number>` anchor.
3. Never cite lines or H anchors absent from the pack. Cite at least one displayed L anchor from every required coverage group, including every individual human/assistant semantic record and each prior compact summary group.
4. Preserve chronology and event time. When decisions conflict, identify the later current decision and retain the earlier decision as superseded history with its reason.
5. Preserve user goals, exact constraints, final instructions, questions and wording that changes interpretation.
6. Preserve assistant/model research decisions, reasons, evidence checks, rejected routes, uncertainty and supersessions in any language.
7. Weight evidence in this order:
   - hard user constraints and current goals
   - current decisions and supersessions
   - assistant/model research conclusions with reasons and verification
   - source/tool/file evidence supporting those decisions
   - unresolved risks and unknowns
   - ordinary progress, repeated commands and low-information logs
8. For humanities, law, art, design, brand strategy, planning, history, feasibility and document research, preserve historical nuance, provenance, interpretive changes and minority/abandoned positions that explain the current conclusion.
9. For software and engineering, preserve contracts, architecture decisions, failure causes, migrations, compatibility constraints, tests and operational state.
10. Use all nine exact `##` sections printed under `Required Final Summary Shape`, in order; every section needs an L or H evidence anchor. Do not add HTML comments or Markdown headings beyond the exact leading metadata comment and required headings.
11. Use the exact whole line `Unknown from provided anchors.` when evidence is insufficient. Do not append a claim to that line; every other substantive line needs visible L/H support.
12. Treat every explicitly supplied handoff line as complete evidence. Cite every generated early/middle/late/latest H coverage group. If the complete handoff and mandatory pack sections do not fit either pack ceiling, stop; raise `--model-pack-char-budget` or `--model-pack-estimated-token-budget` only within the summarizing model's capacity.
13. Do not edit JSONL, UUIDs, parent links, tool pairs, compact records or pointer records manually.
14. Under `## Evidence and Source Anchors`, include exactly one `### Mandatory Evidence Coverage` subsection. For every anchor under `Required Claim Support`, add exactly `- L42 support_text_json="exact source substring" disposition=covered`; the JSON string must be a meaningful exact substring of that L record. Do not substitute generic anchor prose.

Schema v11 gives each non-empty older active human message and each older active assistant `text`/`thinking` message its own full-text required L group and claim-source entry. It also reserves early/middle/late/latest, source/tool and prior-summary coverage. Every active-chain prior compact summary and every physical line of an explicitly supplied handoff are included in full. If mandatory evidence does not fit either pack ceiling, stop and report the capacity boundary. Do not truncate, sample or bypass the gate.

### Pass 2: Validate And Compress

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\path\session.jsonl" `
  --output "C:\path\compressed.jsonl" `
  --target-ratio 0.30 `
  --min-recent-records 120 `
  --summary-char-budget 60000 `
  --target-estimated-tokens 150000 `
  --model-pack-char-budget 500000 `
  --model-pack-estimated-token-budget 150000 `
  --model-summary "C:\work\run\session.model-summary.md"
```

Repeat every non-default pass-1 option in pass 2, including candidate token target, checkpoint policy, explicit leaf, handoff file, both model-pack budgets, templates and prior-summary policy. The v11 `pack_request_digest` binds those options and loaded resources; the script rejects a summary whose request, source, evidence, claim-source hashes or anchors do not match the regenerated pack.

Use this only on explicit request for deterministic fallback:

```powershell
  --deterministic-summary
```

Do not silently choose deterministic fallback because model authoring is inconvenient.

## Live Replacement Commands

Generate the model pack outside `.claude`, write the model summary, then run:

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "$env:USERPROFILE\.claude\projects\PROJECT\SESSION.jsonl" `
  --replace-original `
  --confirm-session-closed `
  --work-dir "C:\work\claude-compression\SESSION-TIMESTAMP" `
  --model-pack-estimated-token-budget 150000 `
  --target-estimated-tokens 150000 `
  --model-summary "C:\work\claude-compression\SESSION-TIMESTAMP\session.model-summary.md"
```

By default the backup stays beside the live JSONL. Use an external backup directory only when explicitly requested:

```powershell
  --backup-dir "C:\work\claude-compression\SESSION-TIMESTAMP\backups"
```

Do not hand-copy a candidate over a live session after a refusal.

## Checkpoint Policy

Conversation rewind topology and file checkpoints are separate planes.

- `--checkpoint-policy active-correlated` is the default. It keeps only recent UUID-less `file-history-snapshot` records that structurally correlate to retained active records.
- `--checkpoint-policy none` keeps no UUID-less file-history snapshots.
- `--checkpoint-policy preserve-recent` is rejected in strict active-chain mode. It is meaningful only with explicit `--preserve-physical-tail`, whose report is labeled `physical-tail-compatibility` and which has no inactive-branch isolation guarantee.
- `--max-file-history-snapshots N` caps retained snapshots.

Never claim that compressed JSONL alone guarantees complete file-state rewind. The report states what snapshot side records were retained.

## Repeated Compression

Default behavior folds old compact summaries into one current compact summary. The output must contain one current compact pair.

Treat an older `preservedMessages` list as a historical snapshot. A later rewind may make its tail diverge from the current authoritative chain; report that warning, exclude the old tail, and continue only when the current chain itself is valid. Require every newly generated candidate to rebuild the snapshot so it exactly matches the candidate's current chain.

When the user explicitly asks to preserve existing summaries verbatim, repeat this flag in both model-pack and compression passes:

```powershell
  --preserve-prior-summaries-verbatim
```

The script may expand the summary character budget to 1.5x. If exact preservation still does not fit, it uses the normal folded path and reports `fallback-folded`. It does not stack old compact pairs into the active chain.

For third and later rounds, apply chronology again. Prior summaries are historical evidence, not automatically current truth. Preserve old decisions and reasons while marking later supersessions.

## Read.pages Repair Commands

Scan without writing:

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "C:\path\session.jsonl" `
  --scan-only
```

Write a separate candidate and require the expected patch count:

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "C:\path\session.jsonl" `
  --output "C:\path\session.repaired.jsonl" `
  --expect-matches 2
```

Replace one live session transactionally:

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "$env:USERPROFILE\.claude\projects\PROJECT\SESSION.jsonl" `
  --replace-original `
  --confirm-session-closed `
  --work-dir "C:\work\claude-repair\SESSION-TIMESTAMP" `
  --expect-matches 2
```

Use `--scope all` only when the user explicitly wants inactive physical branches repaired too.

An automatic repair additionally requires exactly one later result with the same non-empty `sessionId` and a `sourceToolAssistantUUID` equal to the Read tool-use assistant UUID. Candidate publication must re-read and validate the actual published bytes and prove an idempotent second scan before success.

## Validation And Stop Condition

Before reporting success, require fresh evidence for the selected operation:

Compression:

- candidate validation `ok: true`
- no duplicate UUID, missing parent, cross-session parent or tool-pair error
- no empty/duplicate active tool ID; a partial ordered-subset result is accepted only as an explicit compatibility warning and count
- exactly one current Codex compact boundary/summary pair on the final pointer chain
- one projected final `last-prompt`
- dead-branch counts reported without branch text
- any observed attachment-order/session-lineage compatibility is explicitly reported, and output raw records remain one current-session chain
- explicit `--target-estimated-tokens` ceiling met under the complete-structure local estimate; an approximate ratio alone is not a hard success claim
- input unchanged in candidate mode
- backup bytes equal original bytes in live mode
- replacement validation `ok: true` in live mode

Repair:

- expected match count satisfied when supplied
- byte validation `ok: true`
- UUID/parent and tool-ID signatures unchanged
- second pass finds zero patchable matches
- shared full-transcript validation `ok: true`
- input unchanged in candidate mode
- numbered backup equals original in live mode

Structural validation alone is an observed-format check, not an Anthropic format guarantee. If the user permits Claude CLI testing, report `/resume`, `/context`, recent conversation rewind and recent file rewind as separate observations.

## Session Location

Prefer an exact path or filename. To locate one session without reading transcript bodies:

```powershell
python "$skill\scripts\claude_session_tools.py" `
  --root "$env:USERPROFILE\.claude\projects" `
  --query "SESSION.jsonl"
```

Use `--scan-titles` only when the user supplies a title and permits title scanning. Multiple matches are an error. Never broaden a single-target run into directory-wide compression.

## Failure Rules

- A strict topology failure produces no pack, candidate, sidecar or backup.
- For a special or ambiguous topology, report the strict failure and pause. Offer only the exact explicit control that matches the diagnosis, state the lost guarantee, and require a new user confirmation before running it. Manual/spliced files generally require `--preserve-physical-tail`, which forfeits inactive-branch and rewind isolation.
- A model-summary validation failure requires regenerating the pack/summary with identical settings; do not weaken validation.
- A tool-pair failure requires moving the cut earlier or diagnosing source inconsistency; do not invent tool results.
- A source hash change aborts live replacement.
- Live replacement requires the Claude process for that session to be closed. The transaction validates immutable candidate bytes, exclusively creates and verifies a numbered backup, captures the actual old target, verifies its full SHA-256, installs the candidate, and verifies the published bytes and structure. If another process recreates the target during capture, preserve the external target and recovery backups and fail without publishing. Parent-directory fsync is best effort and reported because platform support differs.
- A write/fsync/validation/replace failure returns nonzero. The transaction restores the captured original bytes when replacement began; if restoration itself fails, it raises a high-priority error and retains the numbered backup for recovery.
- If a valid live replacement commits but final sidecar/report publication fails, return exit code 3 with `committed-report-failed` and the committed hashes/backup labels. Do not rerun blindly or describe that state as an uncommitted failure.
- Keep reports and temporary work outside `.claude`; do not leave ad hoc files in live session directories.

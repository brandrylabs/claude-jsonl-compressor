<p align="center">
  <a href="README.md"><img alt="English" src="https://img.shields.io/badge/English-2563eb?style=for-the-badge"></a>
  <a href="docs/README.zh-CN.md"><img alt="简体中文" src="https://img.shields.io/badge/%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-6b7280?style=for-the-badge"></a>
  <a href="docs/README.ja.md"><img alt="日本語" src="https://img.shields.io/badge/%E6%97%A5%E6%9C%AC%E8%AA%9E-6b7280?style=for-the-badge"></a>
</p>

# Claude JSONL Compressor

Strict, model-assisted compression for one Claude Code session transcript, plus an independent byte-preserving compatibility repair for historical `Read.pages` records.

**Release:** [`1.0.0-rc.1`](CHANGELOG.md)<br>
**Engine:** `v10`<br>
**Model-pack schema:** `v11`<br>
**License:** GPL-3.0-only<br>
**Repository:** [brandrylabs/claude-jsonl-compressor](https://github.com/brandrylabs/claude-jsonl-compressor)

This project is not affiliated with Anthropic. Claude Code's transcript JSONL is an observed internal format, not a published stable storage API. Always keep the original file or a verified backup.

## What It Does

- Compresses one Claude Code JSONL into one current compact-style summary pair plus a recent raw active suffix.
- Uses a model-authored semantic summary by default, with deterministic evidence selection and validation around it.
- Excludes rewound/inactive branch text from every Claude-readable output layer.
- Preserves recent conversation records for Claude rewind.
- Projects one final `last-prompt` while retaining unknown source fields.
- Validates UUIDs, parents, sessions, compact metadata and API-level tool pairing.
- Supports candidate output and transactional replacement of one live `.claude/projects` session.
- Handles repeated compression, including an explicit prior-summary verbatim mode.
- Offers an independent byte-level repair that removes unsupported historical `Read.pages` members without reserializing the JSONL.
- Runs with Python's standard library. No tokenizer or YAML dependency is required.

## Quick Start

With this repository installed as a Codex skill, ask Codex:

```text
Use the claude-jsonl-compressor skill on exactly one Claude Code JSONL.
Input: C:\data\session.jsonl
Output: C:\data\session.compressed.jsonl
Target: about 150k estimated Messages tokens.
Keep recent raw records for rewind, use the default model-assisted summary, and run validation.
```

For a live `.claude/projects` file, explicitly request a numbered backup and in-place replacement, confirm that the session is closed, and provide a work directory outside `.claude`. The detailed two-pass CLI workflow appears below.

## Why Model-Assisted By Default

Deterministic code can select topology and validate bytes, but it cannot decide which historical arguments, legal distinctions, design rationale or research conclusions matter. Python therefore freezes the active branch and builds a bounded, source-anchored evidence pack; a host model writes the summary; Python then verifies request/evidence digests, anchors, required source excerpts and the final JSONL.

The script itself never calls a model or the network. The evidence pack bridges the practical 1M-session-versus-smaller-summarizer gap by including every non-empty older active human message and assistant `text`/`thinking` message in full while excluding inactive branches, recent raw records and low-value structural repetition. U+FFFD is reported without discarding the rest of a mandatory record. If mandatory evidence exceeds either pack ceiling, generation stops instead of sampling semantic history.

## Safety Properties

### Strict resume authority

The physically last `type: "last-prompt"` record is authoritative in automatic mode. A malformed latest pointer is an error; the program does not search backward for an older valid pointer and accidentally revive an obsolete branch.

Strict active mode rejects:

- missing or malformed authority
- missing leaf or parent
- parent loops or malformed non-string/empty `parentUuid` values
- ordinary-message/non-attachment physical parent inversion
- recurring, pointer-mismatched or otherwise unsafe session lineage
- duplicate UUIDs anywhere in the file
- unsafe post-pointer extension

Use `--resume-leaf UUID` only for an explicit recovery decision. It is reported as `active-chain-manual-override`, distinct from default strict `active-chain`. Use `--preserve-physical-tail` only as an explicit compatibility mode; it does not provide inactive-branch isolation.

An unusual or ambiguous topology is a stop, not an automatic fallback. The CLI exits before creating a pack, candidate, report, backup or other sidecar. A hosting agent may explain one applicable explicit recovery control and ask the user to confirm it in a new instruction; it must not infer that confirmation from the original compression request. Manually spliced transcripts generally require physical-tail compatibility and therefore lose branch/rewind isolation.

Current Claude Code reconstructs a conversation from a UUID map and parent links, so physical line order is not universally chronological. This project accepts only same-session `attachment -> attachment` physical inversions on an otherwise complete acyclic chain and writes them back in logical parent order. It also accepts one-way A->B (or A->B->C) session lineage only when a session never recurs and the final leaf and pointer match the final session. All earlier-session records become summary evidence; recent raw records remain entirely in the final session. A tool pair crossing that forced cut is a hard stop.

### Rewound branches stay out

The source indexes are partitioned into mutually exclusive sets:

| Set | Meaning | May enter summary? | May remain raw? |
| --- | --- | --- | --- |
| `summaryIndexes` | Older active-chain records | Yes | No |
| `rawKeepIndexes` | Recent active-chain records | No | Yes |
| `sideKeepIndexes` | Policy-approved checkpoint side records | No | Side records only |
| `controlProjectionIndexes` | Pointer and safe global control records | No | Projected only |
| `excludedBranchIndexes` | Inactive UUID branches | No | No |
| `excludedUnattributedIndexes` | Unattributed non-chain records | No | No |

Excluded records appear in reports only as counts and digests. Their text is not copied into the model pack, compact summary, deterministic appendix, verbatim prior-summary block or output message chain.

### Transactional writes

- Input and candidate bytes are bound by full SHA-256; candidates are staged, flushed, validated and atomically published.
- Numbered backups use exclusive creation and byte verification. Live replacement also captures and verifies the actual old target before installing the candidate.
- Failed post-replacement validation restores the captured original. A rollback failure is raised prominently while verified recovery assets remain available.
- Concurrent target recreation preserves the external target and recovery backups, then fails without publishing the candidate.
- Parent-directory fsync is best effort and reported; this is not a cross-platform power-loss guarantee.
- If the live JSONL commits but final report publication fails, the CLI does not undo valid committed data. It prints a `committed-report-failed` receipt with hashes and backup/candidate labels and exits with code 3.

## Requirements

- Python 3.10 or newer. An older interpreter is reported as a warning at startup and the run continues, because the code avoids 3.10-only syntax; unexpected failures on an older version are not supported.
- Node.js 22 or newer only when using the npm command wrappers
- Claude Code is optional; it is needed only for an explicitly requested runtime `/resume` or `/context` smoke test
- Hard-link support on the volume holding the target file, for `--replace-original` only

No Python package installation is required.

### Hard-link requirement for live replacement

`--replace-original` publishes the candidate with `os.link` so that it never overwrites a concurrent claimant, and the rollback path restores the captured original the same way. Both therefore require hard-link support on the volume holding the session file.

The compressor probes this before it stages, backs up or moves anything. If the filesystem rejects `os.link`, the run stops with the target still in place and nothing written. Filesystems that typically cannot satisfy the requirement include FAT32/exFAT removable media, some SMB/NFS mounts and some container bind mounts. NTFS and ext4 are fine.

Candidate output is unaffected: it publishes through `os.replace` and has no hard-link dependency.

## Installation

### Install As A Codex Skill

Clone the repository into the Codex skill directory:

```bash
skill="${CODEX_HOME:-$HOME/.codex}/skills/claude-jsonl-compressor"
mkdir -p "$(dirname "$skill")"
git clone https://github.com/brandrylabs/claude-jsonl-compressor.git "$skill"
```

Windows PowerShell:

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skill = Join-Path $codexHome 'skills\claude-jsonl-compressor'
New-Item -ItemType Directory -Force (Split-Path -Parent $skill) | Out-Null
git clone https://github.com/brandrylabs/claude-jsonl-compressor.git $skill
```

Update or uninstall the skill:

```bash
git -C "${CODEX_HOME:-$HOME/.codex}/skills/claude-jsonl-compressor" pull --ff-only
rm -rf "${CODEX_HOME:-$HOME/.codex}/skills/claude-jsonl-compressor"
```

```powershell
git -C $skill pull --ff-only
Remove-Item -LiteralPath $skill -Recurse -Force
```

The installed directory must contain `SKILL.md`, `scripts/`, `config/`, `templates/` and `references/`.

### Install The npm CLI

After the RC is published:

```bash
npm install --global @brandry/claude-jsonl-compressor@rc
```

This installs two commands:

```text
claude-jsonl-compressor
claude-jsonl-repair-read-pages
```

The npm package is a zero-dependency Node shim over the bundled Python implementation. It forwards arguments, stdio, exit codes and signals with `shell: false`. The tarball also contains `SKILL.md`, `agents/` and `references/`, but npm installation does not register the directory as a Codex skill; skill installation remains a separate copy/link step.

Upgrade or uninstall the global CLI:

```bash
npm install --global @brandry/claude-jsonl-compressor@rc
npm update --global @brandry/claude-jsonl-compressor
npm uninstall --global @brandry/claude-jsonl-compressor
```

Local development install and invocation:

```bash
npm install --save-dev @brandry/claude-jsonl-compressor@rc
npm update @brandry/claude-jsonl-compressor
npm exec -- claude-jsonl-compressor --version
npm exec -- claude-jsonl-repair-read-pages --version
npm uninstall @brandry/claude-jsonl-compressor
```

Run without retaining an installation:

```bash
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-compressor --version
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-repair-read-pages --version
```

Actual npm/npx operations use the same Python CLI options:

```bash
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-compressor --input session.jsonl --write-model-pack run/session.model-pack.md
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-repair-read-pages --input session.jsonl --scan-only
```

### Use From Source Without Installing

```bash
python scripts/compress_claude_jsonl.py --version
python scripts/repair_claude_jsonl.py --version
```

### Can Claude Code Install This Skill?

`SKILL.md` is a Codex skill definition, not a native Claude Code skill/plugin format. Claude Code can still run the Python or npm commands when instructed, but installing this directory into Claude's configuration does not automatically create an equivalent Claude-native skill.

## Detailed Workflow

The examples below use PowerShell and a local skill installation:

```powershell
$skill = "$env:USERPROFILE\.codex\skills\claude-jsonl-compressor"
```

### 1. Analyze The Resume Path

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --analyze-resume-path
```

This is read-only. A nonzero result must be resolved before model-pack generation.

### 2. Generate A Model Evidence Pack

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --write-model-pack "C:\work\run\session.model-pack.md" `
  --target-ratio 0.30 `
  --min-recent-records 120 `
  --summary-char-budget 60000 `
  --target-estimated-tokens 150000 `
  --model-pack-char-budget 500000 `
  --model-pack-estimated-token-budget 150000
```

The evidence pack has two independent default ceilings: 500,000 characters
and a conservative 150,000-token local estimate. The token ceiling leaves
working room in a typical 200k summarizer context. Mandatory human/assistant
semantic records, prior compact summaries, handoff lines, and required coverage
groups are never sampled or clipped; generation stops if they do not fit.
Optional source/tool/system/error evidence is added by importance and chronology
until either ceiling is reached, and the pack/report state whether that optional
evidence was truncated. Do not install a tokenizer to change this workflow.

`--target-ratio` is an approximate byte-ratio planning input, not a hard release gate. For a hard local Messages estimate ceiling, use:

```powershell
  --target-estimated-tokens 150000
```

This candidate-output estimate is separate from the model-pack reading ceiling.
It covers complete retained structured message payloads, including full thinking,
`tool_use.input`, `tool_result`, and `toolUseResult` data. It does not include
Claude's system prompt, tool schemas, MCP servers, agents, skills, memory files
or runtime-loaded context. It is not a promise about total `/context` usage.

`--summary-char-budget` has a hard minimum of 4000 characters. A smaller value or a blank compact summary is rejected instead of publishing unusable memory.

### 3. Write The Model Summary

The model reads the pack and writes `session.model-summary.md`.

The first HTML comment must be copied exactly and contains:

```text
source_sha256
summary_source_sha256
evidence_anchor_lines_digest
required_anchor_groups_digest
handoff_summary_digest
pack_request_digest
required_claim_sources_digest
```

Every substantive transcript claim needs a displayed `L<number>` anchor. Every external-handoff claim needs a displayed `H<number>` anchor. The validator rejects invented or hidden anchors. It also requires at least one cited anchor from every generated coverage group and an anchored body under each of the nine exact headings printed in the pack. Only the exact leading metadata comment and exact required headings are exempt from line grounding; extra HTML comments or headings are errors. The exact whole line `Unknown from provided anchors.` is the only unanchored uncertainty placeholder; adding other text to that line removes the exemption.

Schema v11 assigns a required full-text L-anchor group to every non-empty older active human message and every older active assistant `text`/`thinking` message. It binds every selection/resource option through `pack_request_digest`. Under the exact `### Mandatory Evidence Coverage` subsection, the model must provide exactly one line per mandatory semantic/prior-summary record:

```text
- L42 support_text_json="exact source substring" disposition=covered
```

The JSON string must decode to a meaningful exact substring of that L record. This mechanical gate blocks anchor-only boilerplate and leaves a checkable source excerpt; it does not prove that all natural-language interpretation is correct. Schema v11 also reserves early/middle/late/latest, source/tool and prior-summary coverage. Prior compact summaries and every physical line of an explicitly supplied handoff enter the pack in full; handoff early/middle/late/latest H groups must be cited. Pack generation stops instead of truncating or sampling mandatory evidence when either the character or estimated-token ceiling is insufficient. Raise `--model-pack-char-budget` or `--model-pack-estimated-token-budget` only when the summarizing model can read the resulting pack.

The summary should preserve:

- current state
- chronology and supersessions
- user constraints and wording
- assistant/model research decisions and reasons
- evidence provenance
- rejected alternatives
- risks, unknowns and follow-ups
- recent raw boundary

Later events control current state, but earlier decisions and their reasons remain as superseded history.

### 4. Build A Candidate

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --output "C:\data\session.compressed.jsonl" `
  --target-ratio 0.30 `
  --min-recent-records 120 `
  --summary-char-budget 60000 `
  --target-estimated-tokens 150000 `
  --model-pack-char-budget 500000 `
  --model-pack-estimated-token-budget 150000 `
  --model-summary "C:\work\run\session.model-summary.md"
```

Pass exactly the same selection options used for the model pack. In particular,
repeat both non-default model-pack ceilings so the second pass regenerates the
same evidence contract.

The command writes:

```text
session.compressed.jsonl
session.compressed.jsonl.validation.json
session.compressed.jsonl.report.md
```

The input remains unchanged.

## Live Session Replacement

Close the Claude Code process using that session before replacement. The live target must be an existing regular `.jsonl` file under `.claude/projects`.

Generate the model pack and model summary outside `.claude`, then run:

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

The default backup is placed beside the live file:

```text
SESSION.jsonl.backup
SESSION.jsonl.backup1
SESSION.jsonl.backup2
```

To keep backups outside `.claude`:

```powershell
  --backup-dir "C:\work\claude-compression\SESSION-TIMESTAMP\backups"
```

Candidate, report, validation, model pack and model summary files remain under the external work directory. Do not manually copy a refused candidate over a live session. Exit code 3 with `committed-report-failed` means the live JSONL was already replaced and validated but final report publication failed; inspect the printed hashes and numbered backup instead of rerunning blindly.

## Checkpoint And Rewind Behavior

Conversation rewind and file rewind are separate mechanisms.

Default:

```text
--checkpoint-policy active-correlated
```

It retains only UUID-less `file-history-snapshot` records with structural identifiers that correlate to recent retained active records.

Other controls:

```text
--checkpoint-policy none
--max-file-history-snapshots N
```

`--checkpoint-policy preserve-recent` is rejected in strict active-chain mode. It is available only together with explicit `--preserve-physical-tail`, which is labeled compatibility mode and does not isolate rewound branches. JSONL compression alone does not guarantee complete file-state rewind.

## Repeated Compression

The default behavior folds previous compact summaries into one new current summary. Old decisions must be checked against later supersessions; old summary text is not automatically current truth.

An older Codex compact boundary may retain a `preservedMessages` snapshot from the time it was created. If a later rewind diverges from that snapshot, source validation reports a historical-snapshot warning and follows only the current authoritative parent chain; the rewound tail stays excluded. Every newly generated candidate must rebuild this metadata to match its current chain exactly.

For an explicit exact-text request:

```text
--preserve-prior-summaries-verbatim
```

Use the flag in both passes. The compressor allows up to 1.5 times the configured summary character budget. If the exact block still does not fit, it reports `fallback-folded` and uses normal semantic folding. It never leaves stacked old compact pairs on the current active chain.

## Deterministic Fallback

Model-assisted summary is the default. Use deterministic fallback only on explicit request:

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --output "C:\data\session.compressed.jsonl" `
  --deterministic-summary
```

The CLI otherwise requires `--model-summary`.

## Read.pages Compatibility Repair

Claude's native Read tool can legitimately use `pages` for long PDFs. This repair exists for a separate compatibility failure where a historical bridge cannot accept that member. Compression never runs it automatically.

### Scan

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --scan-only
```

### Write A Candidate

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --output "C:\data\session.repaired.jsonl" `
  --expect-matches 2
```

### Replace One Live File

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "$env:USERPROFILE\.claude\projects\PROJECT\SESSION.jsonl" `
  --replace-original `
  --confirm-session-closed `
  --work-dir "C:\work\claude-repair\SESSION-TIMESTAMP" `
  --expect-matches 2
```

Default scope is the strict active chain. `--scope all` must be explicit.

The repair requires:

- assistant API message
- structured `tool_use`
- exact tool name `Read`
- object `input`
- present `pages` member
- non-empty `file_path`
- exactly one later matching `tool_result` in scope
- the same non-empty `sessionId` on use and result
- result `sourceToolAssistantUUID` equal to the tool-use assistant UUID

Pending calls and near matches are reported but unchanged. Duplicate JSON keys or ambiguous spans stop the run before editing. Candidate publication re-reads the actual published bytes, binds them to the expected SHA-256, validates the repair plan, requires an idempotent second scan, and runs the shared full-transcript UUID/parent/compact/tool validator. Exit code 3 with `operationState: committed-report-failed` has the same already-committed meaning as live compression.

## CLI Reference

Important compression options:

| Option | Purpose |
| --- | --- |
| `--analyze-resume-path` | Read-only strict topology report |
| `--write-model-pack PATH` | Write bounded semantic evidence and stop |
| `--model-summary PATH` | Validate and embed model-authored summary |
| `--deterministic-summary` | Explicit model opt-out |
| `--target-ratio R` | Approximate output byte-ratio planning value; not a hard gate |
| `--target-estimated-tokens N` | Hard ceiling under the local complete-structure Messages estimate |
| `--min-recent-records N` | Raw active-suffix floor |
| `--summary-char-budget N` | Compact-summary character budget; minimum 4000 |
| `--model-pack-char-budget N` | Evidence-pack character budget |
| `--model-pack-estimated-token-budget N` | Evidence-pack local token estimate ceiling; default 150000 |
| `--resume-leaf UUID` | Explicit recovery leaf override |
| `--max-post-last-prompt-extension N` | Explicit complete tool-result-only closure limit; default 0 |
| `--checkpoint-policy POLICY` | Strict mode: `active-correlated` or `none`; `preserve-recent` only with physical-tail compatibility |
| `--preserve-prior-summaries-verbatim` | Explicit repeated-compression exact-text mode |
| `--preserve-physical-tail` | Compatibility mode without branch-isolation guarantee |
| `--replace-original` | Transactionally replace one live session |
| `--confirm-session-closed` | Required caller acknowledgement for live replacement; not process-lock detection |
| `--work-dir PATH` | External process directory for live replacement |
| `--backup-dir PATH` | Optional external backup directory |
| `--validate-only PATH` | Structural validation only |

Run `--help` for the complete list.

## Validation Scope

The validator checks:

- JSON object per non-empty line
- UUID uniqueness
- parent existence and session consistency
- final pointer target
- active chain closure
- narrow attachment-order and one-way session-lineage compatibility, with unsafe variants rejected
- one current compact boundary and compact summary
- compact metadata consistency
- merged assistant fragments and split user tool results
- API-level `tool_use` / `tool_result` order and pairing
- non-empty, unique active tool IDs; partial multi-tool ordered subsets remain a reported branch-compatibility warning
- absence of internal scratch fields

Validation checks internal consistency under the observed-format rules; Claude Code versions may still build runtime context differently.

When runtime testing is explicitly allowed, check these separately:

1. `/resume` lists and opens the session.
2. `/context` shows expected Messages usage.
3. Recent conversation rewind works.
4. Recent file rewind works for retained checkpoints.

High total `/context` with low Messages can come from system prompt, tools, MCP, agents, skills, memory files or newly read content. Recompressing JSONL does not reduce those categories.

## Session Locator

Locate exactly one file by filename or session ID without reading transcript bodies:

```powershell
python "$skill\scripts\claude_session_tools.py" `
  --root "$env:USERPROFILE\.claude\projects" `
  --query "SESSION.jsonl"
```

`--scan-titles` reads candidate files only when title matching is explicitly needed. Multiple matches are an error. The compressor never performs directory-wide multi-session compression.

## Development And Verification

Run the complete standard-library suite:

```bash
python -B -m unittest discover -s tests -v
python -B tests/test_compressor.py
python -B tests/test_repair.py
python -B tests/test_package.py
python -B tests/test_transaction_races.py
python -B tests/test_semantic_evidence_contracts.py
python -B tests/test_structural_safety_contracts.py
python -B tests/test_protocol_contracts.py
```

Additional release checks:

```bash
pycache="$(mktemp -d)"
if ! PYTHONPYCACHEPREFIX="$pycache" python -m compileall -q scripts tests; then
  rm -rf "$pycache"
  exit 1
fi
rm -rf "$pycache"
python -B -I -S scripts/compress_claude_jsonl.py --version
python -B -I -S scripts/repair_claude_jsonl.py --version
npm test
npm pack --dry-run --json
npm publish --dry-run --access public --tag rc
```

The release suite covers active/dead branch partitioning, fixed-seed topology transformations, strict pointer failures, dual model-pack budgets, complete structured token accounting, multilingual semantic ledgers and thinking, handoffs, request/claim digests, mandatory support excerpts, tool pairs, repeated compression, checkpoint policies, transaction races and committed-report states, exact byte repair, BOM/CRLF, npm tarball allowlisting and offline tarball installation.

### Maintainer RC Release Checklist

1. Confirm a clean public tree and matching `1.0.0-rc.1` values in `package.json`, Python version output, docs, and tests.
2. Run the Python, npm, isolated-Python, tarball, privacy, and offline-install gates above.
3. Inspect `npm pack --dry-run --json`; publish only the allowlisted files.
4. Require a clean worktree, create annotated tag `v1.0.0-rc.1`, and push the commit and tag.
5. For the first manual RC, publish from an authenticated maintainer machine with npm 2FA:

```bash
npm publish --access public --tag rc
```

6. Verify the npm version and `rc` dist-tag, then create the GitHub prerelease from the already-pushed tag.

Do not append `--provenance` to a local publish. npm provenance requires a supported cloud CI runner. For later releases, prefer npm trusted publishing from a public GitHub repository on a GitHub-hosted runner with `id-token: write`, a protected release tag, and a matching protected environment; trusted publishing generates provenance automatically.

Registry ownership, npm trusted-publisher configuration, credentials, tag push, GitHub prerelease creation, and npm publication are external maintainer actions and are not claimed by the local test suite.

## Repository Layout

```text
SKILL.md
CHANGELOG.md
README.md
LICENSE
package.json
bin/
config/
scripts/
templates/
references/
tests/
```

## Privacy

- The public project contains only anonymous synthetic fixtures.
- Model packs and candidate metadata use generic labels such as `SOURCE_JSONL`; generated reports expose basenames, never full local paths.
- npm publication uses an extension-level file allowlist.
- JSONL, backups, reports, model packs, model summaries, caches and compiled Python files are excluded from the package.
- Review generated evidence packs before sharing them; they intentionally contain selected transcript evidence.

## License

GPL-3.0-only. You may use, study, modify and redistribute the project under the GPL terms. Distribution of modified or incorporated versions may require corresponding source and the same license; review the license when integrating it into a distributed commercial product.

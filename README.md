# Claude JSONL Compressor

[English](https://github.com/brandrylabs/claude-jsonl-compressor/blob/v1.2.0/README.md) | [简体中文](https://github.com/brandrylabs/claude-jsonl-compressor/blob/v1.2.0/docs/README.zh-CN.md) | [日本語](https://github.com/brandrylabs/claude-jsonl-compressor/blob/v1.2.0/docs/README.ja.md)

Resume a long Claude Code session with less context to load and the reasoning behind your decisions close at hand. The summary follows the branch you kept after a rewind, carrying forward key quotations and open questions. Recent turns stay in their original form for `/rewind`, including tool calls and results.

## Ask Codex

> Compress the session named “Exhibition plan” with v12. Keep the agreed budget, the artist’s exact wording, why we ruled out the other venues and which permissions we still need. Keep the last two turns I started, including their tool calls and results. Write a candidate file for me to review.

With the skill installed, Codex finds the session by its final title, writes and submits the summaries, and produces the candidate. Give the file path if two sessions share a title. On a later pass you can ask, “Keep the previous summary word for word and append what changed.”

## Install

Use Python 3.10 or later. The npm commands require Node.js 22 or later.

```powershell
npm install --global @brandry/claude-jsonl-compressor@1.2.0
claude-jsonl-compressor --version
claude-jsonl-compressor v12 --help
```

To add the installed package to Codex, run the following in PowerShell.

```powershell
$packagePath = Join-Path (npm root -g) '@brandry/claude-jsonl-compressor'
$skillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex/skills' }
$installed = Join-Path $skillRoot 'claude-jsonl-compressor'
New-Item -ItemType Directory -Force -Path $installed | Out-Null
Copy-Item -Path (Join-Path $packagePath '*') -Destination $installed -Recurse -Force
```

On Linux or macOS, copy the package from `npm root -g` into `~/.codex/skills/claude-jsonl-compressor`, or into `skills/claude-jsonl-compressor` under your configured `CODEX_HOME`. The Python scripts run offline. You choose the model that reads the material. [License](LICENSE)

## Run v12 from the command line

**1. Plan and prepare.** Substitute your source path and a new run directory. This example targets 150,000 estimated tokens for the candidate and keeps at least two complete recent turns. The plan previews the retained history and writing tasks. Preparation backs up the source and writes a request for each task.

```powershell
claude-jsonl-compressor v12 plan --input "C:\data\session.jsonl" --min-recent-turns 2 --target-estimated-tokens 150000
claude-jsonl-compressor v12 prepare --input "C:\data\session.jsonl" --min-recent-turns 2 --target-estimated-tokens 150000 --run "C:\work\first-run"
claude-jsonl-compressor v12 status --run "C:\work\first-run"
```

**2. Write and submit.** For each ID in `pending`, give a writing model the matching request (such as `map-001.md`) and the writing guide in a fresh context. Save its short Markdown draft with source tags. Compact models can follow the same steps. The script checks the draft and assembles the JSONL. [Writing guide](references/v12-memory.md)

```powershell
claude-jsonl-compressor v12 submit --run "C:\work\first-run" --task map-001 --draft "C:\work\draft.md"
claude-jsonl-compressor v12 status --run "C:\work\first-run"
```

Repeat with the IDs returned by `status`, including any merge task (Reduce). The merge reconciles current decisions with the ones they replace. If a draft fails a check, correct that draft and submit it again.

**3. Create the candidate.** When `pending` is empty and `finalJob` names the accepted task, run the following command. The run directory now contains `candidate.jsonl` for the next conversation, alongside separate evidence, receipts and cost estimates.

```powershell
claude-jsonl-compressor v12 finish --run "C:\work\first-run"
```

### What to carry forward

| Option | Use it to… |
|---|---|
| `--prior resynthesize` | Combine old and new evidence into a fresh summary. This is the v12 default. |
| `--prior verbatim-locked` | Keep the entire earlier summary word for word, including whitespace, and append new work. |
| `--prior clean-and-merge` | Review the earlier summary and its unique quotations, then merge what still matters. |
| `--min-recent-turns N` | Keep at least N complete turns started by the user, with their tool calls and results. |
| `--media archive` | With the user’s permission, mark unread media and keep the original in the backup. |

A revised budget can carry both figures, their units and the date the new amount takes effect. A permission can name who granted it, to whom and on what terms. Contract clauses and research notes can carry exact quotations with line ranges. Adjacent passages from the same source can share an attribution. [Source excerpts](references/v12-excerpts.md)

## Backups and recovery

The candidate leaves the original file in place. Preparation puts `session.jsonl.backup` beside it, or `session.jsonl.backup1` if the first name is taken. To replace a live session, close it and request replacement explicitly. File rewind uses the Claude file-history snapshots associated with retained turns. Recovery can identify the final reply of a completed tool turn even when an attachment follows it. Mixed text and media results retain readable text and captions.

The v11 two-pass CLI is also available. Use the same selection settings for both passes and prepare a fresh pack after upgrading. Set its evidence limit with `--model-pack-estimated-token-budget`.

- [Skill instructions and v11 commands](SKILL.md)
- [v12 commands, budgets and recovery](references/v12-workflow.md)
- [Memory writing and migration](references/v12-memory.md)
- [JSONL structure, repair and transactions](references/claude-jsonl-compression-format.md)
- [Release history](CHANGELOG.md)

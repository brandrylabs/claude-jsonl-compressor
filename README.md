# Claude JSONL Compressor

[English](https://github.com/brandrylabs/claude-jsonl-compressor/blob/v1.2.2/README.md) | [简体中文](https://github.com/brandrylabs/claude-jsonl-compressor/blob/v1.2.2/docs/README.zh-CN.md) | [日本語](https://github.com/brandrylabs/claude-jsonl-compressor/blob/v1.2.2/docs/README.ja.md)

Resume a long Claude Code session with less context to load. Codex summarizes the branch you kept, preserving the decisions, reasons, evidence and open questions you need to continue. Exchanges discarded by `/rewind` stay out of the summary.

## Ask Codex

Use the price difference between GPT and Claude to your advantage. GPT summarizes the history in Codex, so Claude has less context to read and less to write when its cache is rebuilt. You set the budget and choose what to keep. Codex verifies the result before replacing the session.

Close the target session in Claude Code before asking for in-place replacement. Paste the following into Codex and fill in the input line.

```text
Please use the claude-jsonl-compressor skill to compress this Claude JSONL.
Input and output: [exact .jsonl file path or final Claude session title]
Aim for 100k estimated tokens or less. Summarize as much of the active history as possible. Keep only a few recent raw records for /rewind. If retaining a rewind point would exceed the target, prioritize the token limit.
If this is a project session, I’ve closed it. Back up the original and validate the compressed file. Once it passes, replace the original project session. For a standalone export, save the verified result separately.
Tell me the estimated size, what I can still rewind and where to find the output and backup.
```

Codex looks up a session by its final title. If more than one session matches, give the full path. A JSONL exported outside the Claude projects directory also works as input.

## What you can ask for

| Setting | What to tell Codex | What it does |
|---|---|---|
| Target size | “Aim for 100k tokens or less.” | Sets an estimated upper limit for the compressed session. Choose a size that fits your next task. |
| Recent turns and rewind | “Keep the last two turns I started, including tool results.” | Keeps those turns together. If size matters more, say whether Codex may give up rewind points to meet the limit. File rewind also uses Claude’s saved snapshots. |
| Earlier summaries | “Keep the old summary word for word and append new work.” | Preserves the earlier text exactly. You can also ask for a fresh combined summary, or ask Codex to remove repetition while checking quotations unique to an older summary. |
| Details to carry forward | “Keep the reasons we changed direction and the exact wording of the open question.” | Directs attention to the details you will need next. You can name sources, decisions, alternatives or passages to quote. |
| Long sessions and review | “Review the history in sections. Have a second reviewer check the key decisions.” | Codex chooses a writing budget for the material. It writes one summary when the history fits and otherwise works in large, consecutive sections. Request an extra review or a subagent when you want one. |
| Per-task input | “Keep each writing task under 100k estimated input tokens.” | Splits long histories into smaller tasks. This limit applies to the writer’s input separately from the size of the final session. |
| Attachments | “Keep the turn containing the image intact.” | Extends the retained recent history to include that turn and its tool result. You can instead authorize archiving unread media in the backup and marking it as unread in the summary. |
| Output and backup | “Replace the closed project session after validation,” or “Save a separate compressed file.” | A replacement reuses the verified backup beside the original, named `session.jsonl.backup`, then `session.jsonl.backup1` if needed. A separate output leaves the source available. |

## Install

The skill uses Python 3.10 or later. With Node.js 22 or later installed, run the following in PowerShell.

```powershell
npm install --global @brandry/claude-jsonl-compressor@1.2.2
$packagePath = Join-Path (npm root -g) '@brandry/claude-jsonl-compressor'
$skillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex/skills' }
$installed = Join-Path $skillRoot 'claude-jsonl-compressor'
New-Item -ItemType Directory -Force -Path $installed | Out-Null
Copy-Item -Path (Join-Path $packagePath '*') -Destination $installed -Recurse -Force
```

On Linux or macOS, run the same npm install command and copy the package from `npm root -g` into `~/.codex/skills/claude-jsonl-compressor`, or into `skills/claude-jsonl-compressor` under your configured `CODEX_HOME`.

[Skill instructions](SKILL.md) · [Technical reference](references/v12-workflow.md) · [How summaries are written](references/v12-memory.md) · [Release history](CHANGELOG.md)

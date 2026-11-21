# Claude JSONL Compressor

[English](../README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

把 Claude Code 的长会话压短，下次还能接着讨论当初为什么这样决定。摘要沿当前分支整理早期对话，保留方案取舍、关键原话和未决事项，减少下一轮要读的上下文。近期对话按原样保留，可用 `/rewind` 回退。已经回退放弃的分支不会混入摘要。

## 请 Codex 压缩会话

> 用 v12 压缩名为“展览策划”的会话。保留议定的预算、艺术家的原话、排除其他场地的理由，以及还要向谁取得哪些授权。把最近两轮由我发起的对话连同工具调用和结果原样留下。先生成候选文件给我看。

安装技能后，把这段话发给 Codex 即可。它会按最终会话名查找文件，写好并提交摘要，生成候选文件。有重名时直接给出文件路径。再次压缩时，也可以说“旧摘要逐字保留，把这次的新进展追加在后面”。

## 安装

需要 Python 3.10 或更高版本。使用 npm 命令还需要 Node.js 22 或更高版本。运行 `npm install --global @brandry/claude-jsonl-compressor@1.2.0`，将安装好的包复制到 Codex 的 `skills/claude-jsonl-compressor` 目录。脚本在本机离线运行，读材料的模型由你选择。[PowerShell 安装命令及 Linux、macOS 路径](../README.md#install)

## 在命令行使用 v12

**1. 预估并准备。** 将示例路径换成自己的源文件和一个新的工作目录。示例将候选文件的目标设为估算 15 万 token，至少保留最近两个完整轮次。`plan` 预览保留范围和写作任务，`prepare` 备份源文件并生成任务说明。

```powershell
claude-jsonl-compressor v12 plan --input "C:\data\session.jsonl" --min-recent-turns 2 --target-estimated-tokens 150000
claude-jsonl-compressor v12 prepare --input "C:\data\session.jsonl" --min-recent-turns 2 --target-estimated-tokens 150000 --run "C:\work\first-run"
claude-jsonl-compressor v12 status --run "C:\work\first-run"
```

**2. 写稿并提交。** 对 `pending` 中的每个任务，把同名说明文件（如 `map-001.md`）和写作指南交给模型，在独立上下文中写一份带出处的 Markdown 短稿。低成本模型也可按这套步骤写，脚本负责校验草稿和组装 JSONL。[写作指南](../references/v12-memory.md)

```powershell
claude-jsonl-compressor v12 submit --run "C:\work\first-run" --task map-001 --draft "C:\work\draft.md"
claude-jsonl-compressor v12 status --run "C:\work\first-run"
```

按 `status` 给出的任务编号继续。若出现合并任务（Reduce），同样写稿并提交，把仍然有效和已被取代的决定交代清楚。一份草稿检查失败时，只需修正并重交那一份。

**3. 生成候选文件。** 等 `pending` 为空、`finalJob` 显示已通过的任务编号，再运行下面的命令。工作目录中的 `candidate.jsonl` 可用于继续对话。证据、校验记录和成本估算另存于同一目录。

```powershell
claude-jsonl-compressor v12 finish --run "C:\work\first-run"
```

### 选择要保留的内容

| 选项 | 用途 |
|---|---|
| `--prior resynthesize` | 把旧知识和新证据重写成一份摘要。v12 默认使用此项。 |
| `--prior verbatim-locked` | 旧摘要逐字保留，包括空白和换行，把新进展追加在后面。 |
| `--prior clean-and-merge` | 复核旧摘要及其中独有的引文，把仍然有用的内容并入新稿。 |
| `--min-recent-turns N` | 至少保留最近 N 轮由用户发起的完整对话，包括工具调用和结果。 |
| `--media archive` | 经用户同意，把未解析的媒体标为未读，原件保存在备份中。 |

预算有变，可以把旧金额、新金额、单位和生效条件放在一起。涉及授权时，写明授权人、获授权方及使用范围。合同条款和史料可按原文摘录，附出处和行号。同一来源的连续摘录可以共用出处，各段仍有自己的行号。[原文摘录](../references/v12-excerpts.md)

## 备份与恢复

候选文件与源文件分开。准备阶段默认在源文件旁创建 `session.jsonl.backup`，重名时依次使用 `session.jsonl.backup1`、`session.jsonl.backup2`。如需原地替换，先关闭目标会话并明确提出替换。回退文件改动需要保留轮次对应的 Claude 文件快照。即使工具回合的最后一条回复后面还有附件，恢复检查也能定位该回复。工具同时返回文字和媒体时，会保留可读正文和图注。

v11 的两遍命令仍可使用，升级后请重新生成证据包。[技能说明与 v11 命令](../SKILL.md) · [v12 操作与恢复](../references/v12-workflow.md) · [摘要写作与迁移](../references/v12-memory.md) · [格式与修复](../references/claude-jsonl-compression-format.md) · [更新日志](../CHANGELOG.md)

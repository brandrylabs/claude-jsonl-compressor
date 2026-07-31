<p align="center">
  <a href="../README.md"><img alt="English" src="https://img.shields.io/badge/English-6b7280?style=for-the-badge"></a>
  <a href="README.zh-CN.md"><img alt="简体中文" src="https://img.shields.io/badge/%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-2563eb?style=for-the-badge"></a>
  <a href="README.ja.md"><img alt="日本語" src="https://img.shields.io/badge/%E6%97%A5%E6%9C%AC%E8%AA%9E-6b7280?style=for-the-badge"></a>
</p>

# Claude JSONL Compressor

针对单个 Claude Code 会话记录的严格的模型辅助压缩，另外提供一个独立的、保持字节不变的兼容性修复，用于处理历史 `Read.pages` 记录。

**版本：** [`1.0.0-rc.1`](../CHANGELOG.md)<br>
**引擎：** `v10`<br>
**模型包 schema：** `v11`<br>
**许可证：** GPL-3.0-only<br>
**仓库：** [brandrylabs/claude-jsonl-compressor](https://github.com/brandrylabs/claude-jsonl-compressor)

本项目与 Anthropic 无关联。Claude Code 的会话记录 JSONL 是一种观察得到的内部格式，并非公开发布的稳定存储 API。请始终保留原始文件或一份经过校验的备份。

## 功能

- 将单个 Claude Code JSONL 压缩为一对当前的 compact 风格摘要，加上一段最近的原始活动后缀。
- 默认使用由模型撰写的语义摘要，并在其周围配以确定性的证据选取与校验。
- 在每一个 Claude 可读的输出层中排除已回退/非活动分支的文本。
- 保留最近的对话记录以供 Claude 回退使用。
- 投影出一条最终的 `last-prompt`，同时保留来源中未知的字段。
- 校验 UUID、父记录、会话、compact 元数据以及 API 层面的工具配对。
- 支持候选文件输出，以及对一个正在使用的 `.claude/projects` 会话的事务性替换。
- 支持重复压缩，包括一种显式的既有摘要原文保留模式。
- 提供一项独立的字节级修复，在不重新序列化 JSONL 的前提下移除不受支持的历史 `Read.pages` 成员。
- 仅依赖 Python 标准库运行。不需要分词器或 YAML 依赖。

## 快速开始

在本仓库已安装为 Codex skill 的情况下，向 Codex 提出请求：

```text
Use the claude-jsonl-compressor skill on exactly one Claude Code JSONL.
Input: C:\data\session.jsonl
Output: C:\data\session.compressed.jsonl
Target: about 150k estimated Messages tokens.
Keep recent raw records for rewind, use the default model-assisted summary, and run validation.
```

对于正在使用的 `.claude/projects` 文件，需显式要求编号备份与原地替换，确认该会话已关闭，并提供一个位于 `.claude` 之外的工作目录。详细的两阶段 CLI 流程见下文。

## 为什么默认采用模型辅助

确定性代码可以选取拓扑结构并校验字节，但它无法判断哪些历史论据、法律区别、设计理由或研究结论是重要的。因此，Python 先冻结活动分支并构建一个有界的、锚定到来源的证据包；由宿主模型撰写摘要；随后 Python 校验请求/证据摘要值、锚点、必需的来源摘录以及最终的 JSONL。

脚本本身从不调用模型或网络。证据包弥合了实际存在的“100 万 token 会话对较小摘要器”的差距：它完整收录每一条非空的较早期活动人类消息以及助手的 `text`/`thinking` 消息，同时排除非活动分支、最近的原始记录和低价值的结构性重复内容。U+FFFD 会被报告，但不会因此丢弃一条必需记录的其余部分。如果必需证据超出任一证据包上限，生成将停止，而不会对语义历史进行抽样。

## 安全特性

### 严格的恢复权威

在自动模式下，物理位置最后的 `type: "last-prompt"` 记录具有权威性。最新指针格式错误即为错误；程序不会向后搜索一个更早的有效指针，从而避免意外复活一个已过时的分支。

严格活动模式会拒绝以下情况：

- 权威记录缺失或格式错误
- 叶节点或父记录缺失
- 父记录成环，或 `parentUuid` 为非字符串/空值等格式错误
- 普通消息/非附件的物理父子顺序倒置
- 会话血缘重复出现、与指针不匹配，或存在其他不安全情形
- 文件中任何位置出现重复 UUID
- 指针之后存在不安全的延伸内容

仅在做出显式恢复决定时使用 `--resume-leaf UUID`。它会被报告为 `active-chain-manual-override`，与默认严格模式的 `active-chain` 相区别。仅在作为显式兼容模式时使用 `--preserve-physical-tail`；它不提供非活动分支隔离。

异常或含义不明的拓扑将导致停止，而不是自动回退。CLI 会在创建证据包、候选文件、报告、备份或其他附属文件之前退出。宿主 agent 可以说明一项适用的显式恢复控制项，并要求用户在一条新指令中确认；它不得从原始压缩请求中推断出该确认。人工拼接的会话记录通常需要物理尾部兼容模式，因此会失去分支/回退隔离。

当前的 Claude Code 会依据 UUID 映射和父链接重建对话，因此物理行顺序并非在所有情况下都按时间排列。本项目仅接受同一会话内、位于一条在其他方面完整且无环的链上的 `attachment -> attachment` 物理顺序倒置，并按逻辑父子顺序写回。它也仅在会话从不重复出现、且最终叶节点与指针都匹配最终会话时，接受单向的 A->B（或 A->B->C）会话血缘。所有较早会话的记录都会成为摘要证据；最近的原始记录完全保留在最终会话中。跨越该强制切分点的工具配对属于硬性停止条件。

### 已回退分支不会进入输出

来源索引被划分为若干互斥的集合：

| 集合 | 含义 | 可否进入摘要？ | 可否保留为原始记录？ |
| --- | --- | --- | --- |
| `summaryIndexes` | 较早期的活动链记录 | 可以 | 不可以 |
| `rawKeepIndexes` | 最近的活动链记录 | 不可以 | 可以 |
| `sideKeepIndexes` | 策略批准的检查点旁路记录 | 不可以 | 仅旁路记录 |
| `controlProjectionIndexes` | 指针与安全的全局控制记录 | 不可以 | 仅投影 |
| `excludedBranchIndexes` | 非活动 UUID 分支 | 不可以 | 不可以 |
| `excludedUnattributedIndexes` | 无归属的非链上记录 | 不可以 | 不可以 |

被排除的记录仅以计数和摘要值的形式出现在报告中。它们的文本不会被复制进模型包、compact 摘要、确定性附录、既有摘要原文块或输出消息链。

### 事务性写入

- 输入字节与候选字节通过完整的 SHA-256 绑定；候选文件经过暂存、刷新、校验，然后原子性地发布。
- 编号备份使用排他性创建与字节校验。原地替换还会捕获并校验实际的旧目标文件，然后再安装候选文件。
- 替换后校验失败会恢复此前捕获的原始文件。回滚失败会被显著报出，同时经过校验的恢复资产仍然可用。
- 若目标文件被并发重新创建，则保留外部目标文件与恢复备份，然后在不发布候选文件的情况下失败。
- 父目录 fsync 属于尽力而为并会被报告；这不构成跨平台的断电保证。
- 如果正在使用的 JSONL 已提交，但最终报告发布失败，CLI 不会撤销已提交的有效数据。它会打印一条包含哈希值与备份/候选文件标签的 `committed-report-failed` 回执，并以退出码 3 退出。

## 环境要求

- Python 3.10 或更新版本。使用更旧的解释器时，启动阶段会给出警告并继续运行——因为代码未使用 3.10 专属语法；但更旧版本上出现的意外失败不在支持范围内。
- 仅在使用 npm 命令包装器时需要 Node.js 22 或更新版本
- Claude Code 为可选项；仅在显式要求进行运行时 `/resume` 或 `/context` 冒烟测试时才需要
- 目标文件所在卷需支持硬链接，**仅** `--replace-original` 需要

无需安装任何 Python 包。

### 原地替换对硬链接的要求

`--replace-original` 使用 `os.link` 发布候选文件，以确保绝不覆盖并发写入者；回滚路径同样用它把此前捕获的原始文件放回原位。因此两者都要求会话文件所在卷支持硬链接。

压缩器会在暂存、备份或移动任何文件**之前**先行探测。若文件系统拒绝 `os.link`，运行会立即停止，此时目标文件仍在原位，且没有写入任何内容。通常无法满足该要求的文件系统包括：FAT32/exFAT 移动介质、部分 SMB/NFS 挂载、部分容器绑定挂载。NTFS 与 ext4 没有问题。

候选文件输出不受影响：它通过 `os.replace` 发布，不依赖硬链接。

## 安装

### 安装为 Codex skill

将仓库克隆到 Codex skill 目录：

```bash
skill="${CODEX_HOME:-$HOME/.codex}/skills/claude-jsonl-compressor"
mkdir -p "$(dirname "$skill")"
git clone https://github.com/brandrylabs/claude-jsonl-compressor.git "$skill"
```

Windows PowerShell：

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skill = Join-Path $codexHome 'skills\claude-jsonl-compressor'
New-Item -ItemType Directory -Force (Split-Path -Parent $skill) | Out-Null
git clone https://github.com/brandrylabs/claude-jsonl-compressor.git $skill
```

更新或卸载该 skill：

```bash
git -C "${CODEX_HOME:-$HOME/.codex}/skills/claude-jsonl-compressor" pull --ff-only
rm -rf "${CODEX_HOME:-$HOME/.codex}/skills/claude-jsonl-compressor"
```

```powershell
git -C $skill pull --ff-only
Remove-Item -LiteralPath $skill -Recurse -Force
```

安装后的目录必须包含 `SKILL.md`、`scripts/`、`config/`、`templates/` 和 `references/`。

### 安装 npm CLI

在 RC 发布之后：

```bash
npm install --global @brandry/claude-jsonl-compressor@rc
```

这会安装两个命令：

```text
claude-jsonl-compressor
claude-jsonl-repair-read-pages
```

该 npm 包是对包内自带的 Python 实现的零依赖 Node 包装层。它以 `shell: false` 转发参数、stdio、退出码和信号。压缩包中同样包含 `SKILL.md`、`agents/` 和 `references/`，但 npm 安装不会将该目录注册为 Codex skill；skill 的安装仍是一个独立的复制/链接步骤。

升级或卸载全局 CLI：

```bash
npm install --global @brandry/claude-jsonl-compressor@rc
npm update --global @brandry/claude-jsonl-compressor
npm uninstall --global @brandry/claude-jsonl-compressor
```

本地开发安装与调用：

```bash
npm install --save-dev @brandry/claude-jsonl-compressor@rc
npm update @brandry/claude-jsonl-compressor
npm exec -- claude-jsonl-compressor --version
npm exec -- claude-jsonl-repair-read-pages --version
npm uninstall @brandry/claude-jsonl-compressor
```

在不保留安装的情况下运行：

```bash
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-compressor --version
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-repair-read-pages --version
```

实际的 npm/npx 操作使用相同的 Python CLI 选项：

```bash
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-compressor --input session.jsonl --write-model-pack run/session.model-pack.md
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-repair-read-pages --input session.jsonl --scan-only
```

### 不安装、直接从源码使用

```bash
python scripts/compress_claude_jsonl.py --version
python scripts/repair_claude_jsonl.py --version
```

### Claude Code 能安装这个 skill 吗？

`SKILL.md` 是 Codex skill 定义，不是 Claude Code 原生的 skill/插件格式。在收到指令时，Claude Code 仍然可以运行这些 Python 或 npm 命令，但把该目录安装进 Claude 的配置并不会自动创建一个等效的 Claude 原生 skill。

## 详细流程

下面的示例使用 PowerShell 和本地 skill 安装：

```powershell
$skill = "$env:USERPROFILE\.codex\skills\claude-jsonl-compressor"
```

### 1. 分析恢复路径

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --analyze-resume-path
```

这一步是只读的。非零结果必须先解决，然后才能生成模型包。

### 2. 生成模型证据包

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

证据包有两个相互独立的默认上限：500,000 个字符
以及一个保守的 150,000 token 本地估算值。该 token 上限会在典型的
200k 摘要器上下文中留出工作余量。必需的人类/助手
语义记录、既有 compact 摘要、交接行以及必需的覆盖
分组，永远不会被抽样或截断；如果它们放不下，生成就会停止。
可选的来源/工具/系统/错误证据会按重要性和时间顺序添加，
直到触及任一上限为止，证据包与报告会说明这些可选
证据是否被截断。不要为了改变这一流程而安装分词器。

`--target-ratio` 是一个近似的字节比例规划输入值，而不是硬性的发布关卡。若需要一个硬性的本地 Messages 估算上限，请使用：

```powershell
  --target-estimated-tokens 150000
```

该候选输出估算值与模型包的阅读上限是分开的。
它覆盖完整保留下来的结构化消息负载，包括完整的 thinking、
`tool_use.input`、`tool_result` 和 `toolUseResult` 数据。它不包括
Claude 的系统提示词、工具 schema、MCP 服务器、agents、skills、记忆文件
或运行时加载的上下文。它并不构成对 `/context` 总用量的承诺。

`--summary-char-budget` 有 4000 字符的硬性最小值。更小的值或空白的 compact 摘要会被拒绝，而不会发布不可用的记忆内容。

### 3. 撰写模型摘要

模型阅读证据包，并撰写 `session.model-summary.md`。

第一个 HTML 注释必须被逐字复制，其中包含：

```text
source_sha256
summary_source_sha256
evidence_anchor_lines_digest
required_anchor_groups_digest
handoff_summary_digest
pack_request_digest
required_claim_sources_digest
```

每一条实质性的会话记录论断都需要一个显示出来的 `L<number>` 锚点。每一条外部交接论断都需要一个显示出来的 `H<number>` 锚点。校验器会拒绝凭空编造或隐藏的锚点。它还要求每一个生成的覆盖分组都至少有一个被引用的锚点，并且在证据包中打印出的九个精确标题之下，各有一段带锚点的正文。只有开头那段精确的元数据注释以及那些精确的必需标题可以免于逐行溯源；额外的 HTML 注释或标题都属于错误。整行恰好为 `Unknown from provided anchors.` 是唯一可用的无锚点不确定性占位符；在该行添加其他文本会使这项豁免失效。

Schema v11 会为每一条非空的较早期活动人类消息、以及每一条较早期活动助手 `text`/`thinking` 消息，分配一个必需的全文 L 锚点分组。它通过 `pack_request_digest` 绑定每一个选取/资源选项。在精确的 `### Mandatory Evidence Coverage` 子章节之下，模型必须为每一条必需的语义/既有摘要记录提供恰好一行：

```text
- L42 support_text_json="exact source substring" disposition=covered
```

该 JSON 字符串必须能解码为该 L 记录中一个有意义的、精确的子串。这道机械式关卡会挡住只有锚点的套话，并留下一段可核对的来源摘录；但它并不能证明所有自然语言层面的解读都是正确的。Schema v11 还预留了早期/中期/后期/最新、来源/工具以及既有摘要等覆盖分组。既有 compact 摘要以及显式提供的交接内容的每一个物理行，都会被完整收录进证据包；交接内容的早期/中期/后期/最新 H 分组必须被引用。当字符上限或估算 token 上限不足时，证据包生成会停止，而不是截断或抽样必需证据。只有在做摘要的模型能够读完由此产生的证据包时，才提高 `--model-pack-char-budget` 或 `--model-pack-estimated-token-budget`。

摘要应当保留：

- 当前状态
- 时间顺序与取代关系
- 用户约束及其原话表述
- 助手/模型的研究决策及其理由
- 证据来源出处
- 被否决的备选方案
- 风险、未知事项与后续待办
- 最近的原始记录边界

后发生的事件决定当前状态，但更早的决策及其理由会作为已被取代的历史保留下来。

### 4. 构建候选文件

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

传入与生成模型包时完全相同的选取选项。特别是，
要重复传入那两个非默认的模型包上限，这样第二阶段才会重新生成
相同的证据契约。

该命令会写出：

```text
session.compressed.jsonl
session.compressed.jsonl.validation.json
session.compressed.jsonl.report.md
```

输入文件保持不变。

## 替换正在使用的会话

在替换之前，请关闭正在使用该会话的 Claude Code 进程。目标文件必须是 `.claude/projects` 之下一个已存在的常规 `.jsonl` 文件。

在 `.claude` 之外生成模型包与模型摘要，然后运行：

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

默认备份放在正在使用的文件旁边：

```text
SESSION.jsonl.backup
SESSION.jsonl.backup1
SESSION.jsonl.backup2
```

若要把备份保存在 `.claude` 之外：

```powershell
  --backup-dir "C:\work\claude-compression\SESSION-TIMESTAMP\backups"
```

候选文件、报告、校验结果、模型包与模型摘要文件都保留在外部工作目录之下。不要手动用被拒绝的候选文件覆盖正在使用的会话。退出码 3 并伴随 `committed-report-failed` 表示正在使用的 JSONL 已经被替换并通过校验，但最终报告发布失败；此时应检查打印出的哈希值和编号备份，而不要盲目重跑。

## 检查点与回退行为

对话回退与文件回退是两套彼此独立的机制。

默认：

```text
--checkpoint-policy active-correlated
```

它只保留那些不带 UUID、且其结构标识符与最近保留的活动记录相关联的 `file-history-snapshot` 记录。

其他控制项：

```text
--checkpoint-policy none
--max-file-history-snapshots N
```

`--checkpoint-policy preserve-recent` 在严格活动链模式下会被拒绝。它仅在与显式的 `--preserve-physical-tail` 一同使用时可用，而后者被标记为兼容模式，并不隔离已回退的分支。仅靠 JSONL 压缩并不能保证完整的文件状态回退。

## 重复压缩

默认行为会把此前的 compact 摘要折叠进一个新的当前摘要。旧的决策必须对照后来的取代关系逐一核对；旧摘要文本不会自动成为当前的事实。

较早的 Codex compact 边界可能保留着创建当时的 `preservedMessages` 快照。如果后来的回退与该快照产生分歧，来源校验会报告一条历史快照警告，并只沿当前权威父链前进；被回退的尾部内容仍然排除在外。每一个新生成的候选文件都必须重建这份元数据，使其与自身当前的链完全一致。

对于显式的原文保留请求：

```text
--preserve-prior-summaries-verbatim
```

两个阶段都要使用该标志。压缩器允许最多为所配置摘要字符预算的 1.5 倍。如果原文块仍然放不下，它会报告 `fallback-folded` 并改用常规的语义折叠。它绝不会在当前活动链上留下层层堆叠的旧 compact 摘要对。

## 确定性回退方案

模型辅助摘要是默认方案。只在显式要求时才使用确定性回退方案：

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --output "C:\data\session.compressed.jsonl" `
  --deterministic-summary
```

除此之外，CLI 要求必须提供 `--model-summary`。

## Read.pages 兼容性修复

Claude 原生的 Read 工具在处理长 PDF 时可以合理地使用 `pages`。这项修复针对的是另一种情况：某个历史桥接层无法接受该成员所导致的兼容性故障。压缩过程绝不会自动运行它。

### 扫描

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --scan-only
```

### 写出候选文件

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --output "C:\data\session.repaired.jsonl" `
  --expect-matches 2
```

### 替换一个正在使用的文件

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "$env:USERPROFILE\.claude\projects\PROJECT\SESSION.jsonl" `
  --replace-original `
  --confirm-session-closed `
  --work-dir "C:\work\claude-repair\SESSION-TIMESTAMP" `
  --expect-matches 2
```

默认作用范围是严格活动链。`--scope all` 必须显式指定。

该修复要求满足：

- 助手 API 消息
- 结构化的 `tool_use`
- 工具名精确为 `Read`
- `input` 为对象
- 存在 `pages` 成员
- `file_path` 非空
- 在作用范围内恰好有一条位于其后的匹配 `tool_result`
- 工具调用与结果上具有相同的非空 `sessionId`
- 结果的 `sourceToolAssistantUUID` 等于该工具调用所属助手记录的 UUID

待处理的调用与近似匹配会被报告，但不会被改动。重复的 JSON 键或含义不明的区段会在编辑前终止本次运行。候选文件发布时会重新读取实际发布出的字节、将其绑定到预期的 SHA-256、校验修复计划、要求第二次扫描具备幂等性，并运行共用的全量会话记录 UUID/父记录/compact/工具校验器。退出码 3 并伴随 `operationState: committed-report-failed`，其“已提交”的含义与正在使用的会话压缩相同。

## CLI 参考

重要的压缩选项：

| 选项 | 用途 |
| --- | --- |
| `--analyze-resume-path` | 只读的严格拓扑报告 |
| `--write-model-pack PATH` | 写出有界的语义证据并停止 |
| `--model-summary PATH` | 校验并嵌入由模型撰写的摘要 |
| `--deterministic-summary` | 显式放弃使用模型 |
| `--target-ratio R` | 近似的输出字节比例规划值；不是硬性关卡 |
| `--target-estimated-tokens N` | 本地完整结构 Messages 估算下的硬性上限 |
| `--min-recent-records N` | 原始活动后缀的下限 |
| `--summary-char-budget N` | compact 摘要字符预算；最小 4000 |
| `--model-pack-char-budget N` | 证据包字符预算 |
| `--model-pack-estimated-token-budget N` | 证据包本地 token 估算上限；默认 150000 |
| `--resume-leaf UUID` | 显式指定恢复叶节点以覆盖默认值 |
| `--max-post-last-prompt-extension N` | 显式的、仅含完整 tool-result 的收尾上限；默认 0 |
| `--checkpoint-policy POLICY` | 严格模式：`active-correlated` 或 `none`；`preserve-recent` 仅在物理尾部兼容模式下可用 |
| `--preserve-prior-summaries-verbatim` | 显式的重复压缩原文保留模式 |
| `--preserve-physical-tail` | 不提供分支隔离保证的兼容模式 |
| `--replace-original` | 事务性替换一个正在使用的会话 |
| `--confirm-session-closed` | 原地替换所需的调用方确认；并非进程锁检测 |
| `--work-dir PATH` | 原地替换所用的外部处理目录 |
| `--backup-dir PATH` | 可选的外部备份目录 |
| `--validate-only PATH` | 仅做结构校验 |

运行 `--help` 查看完整列表。

## 校验范围

校验器会检查：

- 每个非空行都是一个 JSON 对象
- UUID 唯一性
- 父记录存在性与会话一致性
- 最终指针的目标
- 活动链闭合性
- 范围收窄的附件顺序与单向会话血缘兼容性，不安全的变体会被拒绝
- 只有一个当前的 compact 边界与 compact 摘要
- compact 元数据一致性
- 合并后的助手片段与被拆分的用户工具结果
- API 层面的 `tool_use` / `tool_result` 顺序与配对
- 活动工具 ID 非空且唯一；部分多工具有序子集仍作为分支兼容性警告被报告
- 不存在内部临时字段

校验按观察得到的格式规则检查内部一致性；不同 Claude Code 版本仍可能以不同方式构建运行时上下文。

在显式允许进行运行时测试的情况下，请另外检查这些项：

1. `/resume` 能列出并打开该会话。
2. `/context` 显示出预期的 Messages 用量。
3. 最近的对话回退可用。
4. 对保留下来的检查点，最近的文件回退可用。

`/context` 总量偏高而 Messages 偏低，可能来自系统提示词、工具、MCP、agents、skills、记忆文件或新读取的内容。重新压缩 JSONL 并不会减少这些类别的占用。

## 会话定位器

在不读取会话记录正文的前提下，按文件名或会话 ID 定位恰好一个文件：

```powershell
python "$skill\scripts\claude_session_tools.py" `
  --root "$env:USERPROFILE\.claude\projects" `
  --query "SESSION.jsonl"
```

只有在确实需要按标题匹配时，`--scan-titles` 才会读取候选文件。匹配到多个结果属于错误。压缩器绝不会执行覆盖整个目录的多会话压缩。

## 开发与验证

运行完整的标准库测试套件：

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

其他发布前检查：

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

发布测试套件覆盖活动/失效分支划分、固定随机种子的拓扑变换、严格指针失败、双重模型包预算、完整结构化 token 计量、多语言语义账目与 thinking、交接内容、请求/论断摘要值、必需的支撑摘录、工具配对、重复压缩、检查点策略、事务竞态与已提交报告状态、精确字节修复、BOM/CRLF、npm 压缩包白名单以及离线压缩包安装。

### 维护者 RC 发布清单

1. 确认公共代码树干净，并且 `package.json`、Python 版本输出、文档和测试中的 `1.0.0-rc.1` 取值一致。
2. 运行上面的 Python、npm、隔离 Python、压缩包、隐私与离线安装各项关卡。
3. 检查 `npm pack --dry-run --json`；只发布白名单内的文件。
4. 要求工作区干净，创建带注释的标签 `v1.0.0-rc.1`，并推送该提交与标签。
5. 对于第一次手动 RC，请在已认证并启用 npm 双因素认证的维护者机器上发布：

```bash
npm publish --access public --tag rc
```

6. 核实 npm 版本与 `rc` dist-tag，然后基于已推送的标签创建 GitHub 预发布。

不要在本地发布命令后追加 `--provenance`。npm provenance 需要受支持的云端 CI runner。对于后续版本，更推荐从一个公开 GitHub 仓库、在 GitHub 托管的 runner 上使用 npm trusted publishing，并配合 `id-token: write`、受保护的发布标签以及匹配的受保护环境；trusted publishing 会自动生成 provenance。

registry 所有权、npm trusted-publisher 配置、凭据、标签推送、GitHub 预发布创建以及 npm 发布，都属于外部维护者操作，本地测试套件不对其作出任何保证。

## 仓库结构

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

## 隐私

- 公开项目中只包含匿名的合成测试数据。
- 模型包与候选文件元数据使用诸如 `SOURCE_JSONL` 的通用标签；生成的报告只暴露文件基名，绝不暴露完整本地路径。
- npm 发布使用基于扩展名的文件白名单。
- JSONL、备份、报告、模型包、模型摘要、缓存以及编译后的 Python 文件都被排除在包之外。
- 在分享生成的证据包之前请先审阅；它们有意包含经过选取的会话记录证据。

## 许可证

GPL-3.0-only。你可以在 GPL 条款下使用、研究、修改和再分发本项目。分发修改版或包含本项目的版本，可能需要一并提供相应源码并采用相同许可证；将其集成进对外分发的商业产品时，请先查阅许可证。


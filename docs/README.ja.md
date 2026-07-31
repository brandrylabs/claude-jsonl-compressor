<p align="center">
  <a href="../README.md"><img alt="English" src="https://img.shields.io/badge/English-6b7280?style=for-the-badge"></a>
  <a href="README.zh-CN.md"><img alt="简体中文" src="https://img.shields.io/badge/%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-6b7280?style=for-the-badge"></a>
  <a href="README.ja.md"><img alt="日本語" src="https://img.shields.io/badge/%E6%97%A5%E6%9C%AC%E8%AA%9E-2563eb?style=for-the-badge"></a>
</p>

# Claude JSONL Compressor

Claude Code のセッショントランスクリプト 1 件に対する厳格なモデル支援型の圧縮と、過去の `Read.pages` レコードを対象とした、バイト列を保持する独立した互換性修復を提供します。

**リリース：** [`1.0.0-rc.1`](../CHANGELOG.md)<br>
**エンジン：** `v10`<br>
**モデルパック schema：** `v11`<br>
**ライセンス：** GPL-3.0-only<br>
**リポジトリ：** [brandrylabs/claude-jsonl-compressor](https://github.com/brandrylabs/claude-jsonl-compressor)

本プロジェクトは Anthropic とは無関係です。Claude Code のトランスクリプト JSONL は観察によって把握された内部形式であり、公開された安定したストレージ API ではありません。元のファイル、または検証済みのバックアップを必ず保持してください。

## 機能

- Claude Code の JSONL 1 件を、現在の compact 形式のサマリー 1 組と、直近の生の active サフィックスへ圧縮します。
- 既定ではモデルが作成した意味的サマリーを使い、その周囲を決定的な証拠選択と検証で固めます。
- Claude が読み取るすべての出力層から、巻き戻された/非 active なブランチのテキストを除外します。
- Claude の巻き戻し用に、直近の会話レコードを保持します。
- 最終的な `last-prompt` を 1 件投影しつつ、ソース側の未知フィールドを保持します。
- UUID、親レコード、セッション、compact メタデータ、および API レベルのツール対応関係を検証します。
- 候補ファイルの出力と、稼働中の `.claude/projects` セッション 1 件に対するトランザクショナルな置き換えに対応します。
- 明示的な既存サマリーの原文保持モードを含め、繰り返しの圧縮に対応します。
- JSONL を再シリアライズせずに、サポートされない過去の `Read.pages` メンバーを取り除く独立したバイトレベル修復を提供します。
- Python 標準ライブラリのみで動作します。トークナイザーや YAML の依存関係は不要です。

## クイックスタート

本リポジトリを Codex skill としてインストールした状態で、Codex に次のように依頼します。

```text
Use the claude-jsonl-compressor skill on exactly one Claude Code JSONL.
Input: C:\data\session.jsonl
Output: C:\data\session.compressed.jsonl
Target: about 150k estimated Messages tokens.
Keep recent raw records for rewind, use the default model-assisted summary, and run validation.
```

稼働中の `.claude/projects` ファイルを対象にする場合は、連番バックアップとインプレース置き換えを明示的に指示し、対象セッションが閉じていることを確認し、`.claude` の外に作業ディレクトリを指定してください。詳細な 2 パス CLI ワークフローは後述します。

## 既定でモデル支援を採用する理由

決定的なコードはトポロジーを選択しバイト列を検証できますが、どの過去の論拠、法的な区別、設計上の根拠、研究上の結論が重要かを判断することはできません。そのため Python はまず active ブランチを凍結し、上限のあるソース由来の証拠パックを構築します。サマリーはホスト側のモデルが記述し、その後 Python がリクエスト/証拠のダイジェスト、アンカー、必須のソース抜粋、そして最終的な JSONL を検証します。

スクリプト自体はモデルもネットワークも一切呼び出しません。証拠パックは、100 万トークン規模のセッションと、それより小さい要約モデルとの実務上のギャップを埋めます。具体的には、空でない過去の active な human メッセージと、assistant の `text`/`thinking` メッセージをすべて全文で収録し、その一方で非 active ブランチ、直近の生レコード、価値の低い構造的な繰り返しを除外します。U+FFFD は報告されますが、必須レコードの残りの部分が破棄されることはありません。必須の証拠がいずれかのパック上限を超える場合、意味的な履歴をサンプリングするのではなく、生成を停止します。

## 安全性に関する性質

### 厳格な resume 権限

自動モードでは、物理的に最後に位置する `type: "last-prompt"` レコードが権威を持ちます。最新ポインタが不正な形式であればエラーとなります。プログラムはより古い有効なポインタを後方に探索することはなく、廃止済みのブランチを誤って復活させることもありません。

厳格 active モードは次のケースを拒否します。

- 権限レコードの欠落または不正な形式
- リーフまたは親レコードの欠落
- 親レコードのループ、および `parentUuid` が文字列でない/空であるといった不正な値
- 通常メッセージ／非 attachment における物理的な親子順序の反転
- 再帰するセッション系統、ポインタと不一致なセッション系統、その他の安全でないセッション系統
- ファイル内のいずれかの位置における UUID の重複
- ポインタ以降の安全でない延長

`--resume-leaf UUID` は、明示的な復旧判断を下す場合にのみ使用してください。これは `active-chain-manual-override` として報告され、既定の厳格モードの `active-chain` とは区別されます。`--preserve-physical-tail` は明示的な互換モードとしてのみ使用してください。非 active ブランチの分離は提供されません。

異常なトポロジーや判別できないトポロジーは、自動フォールバックではなく停止として扱われます。CLI はパック、候補ファイル、レポート、バックアップ、その他のサイドカーファイルを作成する前に終了します。ホスト側のエージェントは、該当する明示的な復旧オプション 1 つを説明し、新しい指示のなかでユーザーに確認を求めることができます。その確認を元の圧縮リクエストから推測してはなりません。手作業で継ぎ合わせたトランスクリプトは一般に physical-tail 互換モードを必要とし、その結果としてブランチ／巻き戻しの分離は失われます。

現行の Claude Code は UUID マップと親リンクから会話を再構成するため、物理的な行順序は必ずしも時系列とは一致しません。本プロジェクトは、他の点では完全かつ非循環であるチェーン上での、同一セッション内の `attachment -> attachment` の物理的な反転のみを受け入れ、論理的な親子順序で書き戻します。また、セッションが再帰せず、最終リーフと最終ポインタがいずれも最終セッションと一致する場合に限り、一方向の A->B（または A->B->C）のセッション系統を受け入れます。それより前のセッションのレコードはすべてサマリーの証拠となり、直近の生レコードは完全に最終セッション内に残ります。この強制的な切断点をまたぐツールのペアは、無条件の停止条件です。

### 巻き戻されたブランチは出力に入らない

ソースのインデックスは、互いに排他的な集合へ分割されます。

| 集合 | 意味 | サマリーに入れられるか | 生のまま残せるか |
| --- | --- | --- | --- |
| `summaryIndexes` | 過去の active チェーンのレコード | はい | いいえ |
| `rawKeepIndexes` | 直近の active チェーンのレコード | いいえ | はい |
| `sideKeepIndexes` | ポリシーで承認されたチェックポイントの side レコード | いいえ | side レコードのみ |
| `controlProjectionIndexes` | ポインタおよび安全なグローバル制御レコード | いいえ | 投影のみ |
| `excludedBranchIndexes` | 非 active な UUID ブランチ | いいえ | いいえ |
| `excludedUnattributedIndexes` | 帰属不明でチェーン上にないレコード | いいえ | いいえ |

除外されたレコードは、レポート上では件数とダイジェストとしてのみ現れます。そのテキストがモデルパック、compact サマリー、決定的な付録、既存サマリーの原文ブロック、出力メッセージチェーンへコピーされることはありません。

### トランザクショナルな書き込み

- 入力バイト列と候補バイト列は完全な SHA-256 で束縛されます。候補ファイルはステージング、フラッシュ、検証を経て、アトミックに公開されます。
- 連番バックアップは排他的な作成とバイト単位の検証を行います。稼働中ファイルの置き換えでは、候補ファイルをインストールする前に、実際の旧対象ファイルも取得して検証します。
- 置き換え後の検証に失敗した場合は、取得しておいた元のファイルを復元します。ロールバックの失敗は目立つ形で通知され、その間も検証済みの復旧用資産は利用可能なまま維持されます。
- 対象ファイルが並行して再作成された場合は、外部で作成された対象ファイルと復旧用バックアップを保持したうえで、候補ファイルを公開せずに失敗します。
- 親ディレクトリの fsync はベストエフォートで実行され、その結果が報告されます。これはクロスプラットフォームでの電源喪失に対する保証ではありません。
- 稼働中の JSONL のコミットは成功したものの最終レポートの公開に失敗した場合、CLI はコミット済みの有効なデータを取り消しません。ハッシュ値とバックアップ／候補ファイルのラベルを含む `committed-report-failed` のレシートを表示し、終了コード 3 で終了します。

## 要件

- Python 3.10 以降
- npm コマンドラッパーを使う場合にのみ Node.js 22 以降
- Claude Code は任意です。実行時の `/resume` または `/context` のスモークテストを明示的に依頼する場合にのみ必要です。

Python パッケージのインストールは不要です。

## インストール

### Codex skill としてインストール

リポジトリを Codex の skill ディレクトリへクローンします。

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

skill の更新またはアンインストール：

```bash
git -C "${CODEX_HOME:-$HOME/.codex}/skills/claude-jsonl-compressor" pull --ff-only
rm -rf "${CODEX_HOME:-$HOME/.codex}/skills/claude-jsonl-compressor"
```

```powershell
git -C $skill pull --ff-only
Remove-Item -LiteralPath $skill -Recurse -Force
```

インストール先のディレクトリには `SKILL.md`、`scripts/`、`config/`、`templates/`、`references/` が含まれている必要があります。

### npm CLI のインストール

RC が公開された後：

```bash
npm install --global @brandry/claude-jsonl-compressor@rc
```

これにより 2 つのコマンドがインストールされます。

```text
claude-jsonl-compressor
claude-jsonl-repair-read-pages
```

npm パッケージは、同梱の Python 実装に対する依存関係ゼロの Node シムです。引数、stdio、終了コード、シグナルを `shell: false` で転送します。tarball には `SKILL.md`、`agents/`、`references/` も含まれますが、npm でインストールしてもそのディレクトリが Codex skill として登録されるわけではありません。skill のインストールは、別途コピーまたはリンクを行う手順のままです。

グローバル CLI のアップグレードまたはアンインストール：

```bash
npm install --global @brandry/claude-jsonl-compressor@rc
npm update --global @brandry/claude-jsonl-compressor
npm uninstall --global @brandry/claude-jsonl-compressor
```

ローカル開発向けのインストールと実行：

```bash
npm install --save-dev @brandry/claude-jsonl-compressor@rc
npm update @brandry/claude-jsonl-compressor
npm exec -- claude-jsonl-compressor --version
npm exec -- claude-jsonl-repair-read-pages --version
npm uninstall @brandry/claude-jsonl-compressor
```

インストールを残さずに実行：

```bash
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-compressor --version
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-repair-read-pages --version
```

実際の npm/npx 操作でも、同じ Python CLI オプションを使用します。

```bash
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-compressor --input session.jsonl --write-model-pack run/session.model-pack.md
npx --yes --package @brandry/claude-jsonl-compressor@rc claude-jsonl-repair-read-pages --input session.jsonl --scan-only
```

### インストールせずにソースから使う

```bash
python scripts/compress_claude_jsonl.py --version
python scripts/repair_claude_jsonl.py --version
```

### Claude Code はこの skill をインストールできますか？

`SKILL.md` は Codex の skill 定義であり、Claude Code ネイティブの skill／プラグイン形式ではありません。指示を与えれば Claude Code でも Python や npm のコマンドを実行できますが、このディレクトリを Claude の設定へ配置しても、同等の Claude ネイティブ skill が自動的に作られることはありません。

## 詳細なワークフロー

以下の例では PowerShell と、ローカルへの skill インストールを前提とします。

```powershell
$skill = "$env:USERPROFILE\.codex\skills\claude-jsonl-compressor"
```

### 1. resume パスを解析する

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --analyze-resume-path
```

この処理は読み取り専用です。結果がゼロ以外の場合は、モデルパックを生成する前に解消しなければなりません。

### 2. モデル証拠パックを生成する

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

証拠パックには互いに独立した 2 つの既定上限があります。500,000 文字と、
控えめな 150,000 トークンのローカル推定値です。このトークン上限は、
一般的な 200k の要約モデルのコンテキストに作業上の余裕を残します。必須の human／assistant
の意味的レコード、既存の compact サマリー、ハンドオフ行、必須のカバレッジ
グループがサンプリングされたり切り詰められたりすることはありません。収まらない場合は生成が停止します。
任意のソース／ツール／システム／エラーの証拠は、重要度と時系列に従って
いずれかの上限に達するまで追加され、その任意の証拠が切り詰められたかどうかは
パックとレポートに記載されます。このワークフローを変えるためにトークナイザーをインストールしないでください。

`--target-ratio` はおおよそのバイト比率を指定する計画用の入力値であり、リリースを判定する厳格なゲートではありません。ローカルの Messages 推定に対する厳格な上限が必要な場合は、次を使用してください。

```powershell
  --target-estimated-tokens 150000
```

この候補出力の推定値は、モデルパックの読み取り上限とは別物です。
保持される構造化メッセージのペイロード全体を対象とし、完全な thinking、
`tool_use.input`、`tool_result`、`toolUseResult` のデータを含みます。一方で
Claude のシステムプロンプト、ツールの schema、MCP サーバー、agents、skills、メモリファイル、
実行時に読み込まれるコンテキストは含みません。これは `/context` の総使用量に関する保証ではありません。

`--summary-char-budget` には 4000 文字という厳格な下限があります。これを下回る値や空の compact サマリーは、使用不能なメモリを公開する代わりに拒否されます。

### 3. モデルサマリーを記述する

モデルがパックを読み、`session.model-summary.md` を記述します。

先頭の HTML コメントはそのまま正確にコピーする必要があり、次の項目を含みます。

```text
source_sha256
summary_source_sha256
evidence_anchor_lines_digest
required_anchor_groups_digest
handoff_summary_digest
pack_request_digest
required_claim_sources_digest
```

トランスクリプトに関する実質的な主張には、表示された `L<number>` アンカーが必要です。外部ハンドオフに関する主張には、表示された `H<number>` アンカーが必要です。バリデーターは、捏造されたアンカーや隠されたアンカーを拒否します。さらに、生成されたすべてのカバレッジグループから少なくとも 1 つのアンカーが引用されていること、そしてパックに出力される 9 つの厳密な見出しそれぞれの下にアンカー付きの本文があることを要求します。行単位の根拠付けが免除されるのは、先頭の厳密なメタデータコメントと、厳密な必須見出しのみです。それ以外の HTML コメントや見出しはエラーになります。アンカーのない不確実性のプレースホルダーとして使えるのは、行全体が厳密に `Unknown from provided anchors.` である場合のみです。この行に他のテキストを加えると、免除は失われます。

Schema v11 は、空でない過去の active な human メッセージ、および過去の active な assistant の `text`/`thinking` メッセージのそれぞれに、必須の全文 L アンカーグループを割り当てます。また、すべての選択オプションおよびリソースオプションを `pack_request_digest` によって束縛します。厳密な `### Mandatory Evidence Coverage` サブセクションの下で、モデルは必須の意味的レコードおよび既存サマリーのレコードごとに、ちょうど 1 行を記述しなければなりません。

```text
- L42 support_text_json="exact source substring" disposition=covered
```

この JSON 文字列は、当該 L レコード内の意味のある厳密な部分文字列へデコードできなければなりません。この機械的なゲートは、アンカーだけを並べた形式的な文章を排除し、検証可能なソース抜粋を残します。ただし、自然言語としての解釈がすべて正しいことを証明するものではありません。Schema v11 は、前半／中盤／後半／最新、ソース／ツール、既存サマリーのカバレッジも確保します。既存の compact サマリーと、明示的に与えられたハンドオフの物理行はすべて全文でパックへ入ります。ハンドオフの前半／中盤／後半／最新の H グループは引用しなければなりません。文字数の上限、または推定トークン数の上限が足りない場合、パックの生成は必須の証拠を切り詰めたりサンプリングしたりするのではなく停止します。`--model-pack-char-budget` や `--model-pack-estimated-token-budget` を引き上げるのは、要約するモデルが生成後のパックを読み切れる場合に限ってください。

サマリーでは次の内容を保持してください。

- 現在の状態
- 時系列と、何が何を置き換えたか
- ユーザーの制約とその言い回し
- assistant／モデルによる調査上の判断とその理由
- 証拠の出所
- 却下された代替案
- リスク、未解明点、フォローアップ
- 直近の生レコードの境界

現在の状態を決めるのは後に起きた出来事ですが、それより前の判断とその理由は、置き換えられた履歴として残ります。

### 4. 候補ファイルを構築する

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

モデルパックの生成時に使ったものとまったく同じ選択オプションを渡してください。特に、
既定値ではない 2 つのモデルパック上限は必ず再指定し、2 回目のパスでも同じ
証拠契約が再生成されるようにします。

このコマンドは次のファイルを書き出します。

```text
session.compressed.jsonl
session.compressed.jsonl.validation.json
session.compressed.jsonl.report.md
```

入力ファイルは変更されません。

## 稼働中セッションの置き換え

置き換えの前に、そのセッションを使用している Claude Code のプロセスを終了してください。対象は `.claude/projects` 配下に実在する通常の `.jsonl` ファイルでなければなりません。

モデルパックとモデルサマリーを `.claude` の外で生成し、その後に次を実行します。

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

既定のバックアップは、稼働中のファイルと同じ場所に置かれます。

```text
SESSION.jsonl.backup
SESSION.jsonl.backup1
SESSION.jsonl.backup2
```

バックアップを `.claude` の外に置く場合：

```powershell
  --backup-dir "C:\work\claude-compression\SESSION-TIMESTAMP\backups"
```

候補ファイル、レポート、検証結果、モデルパック、モデルサマリーの各ファイルは、外部の作業ディレクトリ配下に残ります。拒否された候補ファイルを、稼働中のセッションへ手作業でコピーしないでください。終了コード 3 と `committed-report-failed` は、稼働中の JSONL の置き換えと検証は既に完了しているが、最終レポートの公開に失敗したことを意味します。やみくもに再実行せず、表示されたハッシュ値と連番バックアップを確認してください。

## チェックポイントと巻き戻しの挙動

会話の巻き戻しとファイルの巻き戻しは、別々の仕組みです。

既定値：

```text
--checkpoint-policy active-correlated
```

これは、UUID を持たない `file-history-snapshot` レコードのうち、構造上の識別子が直近の保持された active レコードと対応づくものだけを保持します。

その他の制御オプション：

```text
--checkpoint-policy none
--max-file-history-snapshots N
```

`--checkpoint-policy preserve-recent` は、厳格な active チェーンモードでは拒否されます。これは明示的な `--preserve-physical-tail` と併用する場合にのみ利用できますが、後者は互換モードと位置づけられており、巻き戻されたブランチを分離しません。JSONL の圧縮だけでは、ファイル状態の完全な巻き戻しは保証されません。

## 繰り返しの圧縮

既定の挙動では、以前の compact サマリーを 1 つの新しい現在のサマリーへ畳み込みます。古い判断は、後の置き換えと突き合わせて確認しなければなりません。古いサマリーの記述が自動的に現在の事実になるわけではありません。

過去の Codex の compact 境界には、作成された時点の `preservedMessages` スナップショットが残っている場合があります。その後の巻き戻しがそのスナップショットから乖離した場合、ソース検証は履歴スナップショットに関する警告を報告し、現在の権威ある親チェーンのみをたどります。巻き戻された末尾は除外されたままです。新しく生成される候補ファイルはいずれも、このメタデータを自身の現在のチェーンと完全に一致するよう再構築しなければなりません。

原文どおりのテキストを明示的に要求する場合：

```text
--preserve-prior-summaries-verbatim
```

このフラグは 2 回のパスの両方で使用してください。圧縮側は、設定されたサマリー文字数予算の最大 1.5 倍まで許容します。それでも原文ブロックが収まらない場合は `fallback-folded` を報告し、通常の意味的な畳み込みに切り替えます。現在の active チェーン上に、古い compact サマリーの組が積み重なったまま残ることはありません。

## 決定的なフォールバック

既定はモデル支援によるサマリーです。決定的なフォールバックは、明示的に要求された場合にのみ使用してください。

```powershell
python "$skill\scripts\compress_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --output "C:\data\session.compressed.jsonl" `
  --deterministic-summary
```

それ以外の場合、CLI は `--model-summary` を必須とします。

## Read.pages 互換性修復

Claude ネイティブの Read ツールは、長い PDF に対して `pages` を正当に使用できます。この修復が対象とするのは、それとは別に、過去のブリッジがそのメンバーを受け付けないことで生じる互換性の不具合です。圧縮処理がこれを自動的に実行することはありません。

### スキャン

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --scan-only
```

### 候補ファイルを書き出す

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "C:\data\session.jsonl" `
  --output "C:\data\session.repaired.jsonl" `
  --expect-matches 2
```

### 稼働中のファイル 1 件を置き換える

```powershell
python "$skill\scripts\repair_claude_jsonl.py" `
  --input "$env:USERPROFILE\.claude\projects\PROJECT\SESSION.jsonl" `
  --replace-original `
  --confirm-session-closed `
  --work-dir "C:\work\claude-repair\SESSION-TIMESTAMP" `
  --expect-matches 2
```

既定の対象範囲は厳格な active チェーンです。`--scope all` は明示的に指定する必要があります。

この修復は次の条件を必要とします。

- assistant の API メッセージ
- 構造化された `tool_use`
- ツール名が厳密に `Read`
- `input` がオブジェクトであること
- `pages` メンバーが存在すること
- `file_path` が空でないこと
- 対象範囲内に、後続する一致した `tool_result` がちょうど 1 件あること
- ツール呼び出しと結果に、同一かつ空でない `sessionId` があること
- 結果の `sourceToolAssistantUUID` が、ツール呼び出し元 assistant の UUID と一致すること

保留中の呼び出しや近い一致は報告されますが、変更はされません。JSON キーの重複や判別できない範囲がある場合は、編集前に実行を停止します。候補ファイルの公開時には、実際に公開されたバイト列を読み直し、期待される SHA-256 に束縛し、修復計画を検証し、2 回目のスキャンが冪等であることを要求し、共通のトランスクリプト全体に対する UUID／親レコード／compact／ツールのバリデーターを実行します。終了コード 3 と `operationState: committed-report-failed` は、稼働中セッションの圧縮の場合と同じく、既にコミット済みであることを意味します。

## CLI リファレンス

主な圧縮オプション：

| オプション | 用途 |
| --- | --- |
| `--analyze-resume-path` | 読み取り専用の厳格なトポロジーレポート |
| `--write-model-pack PATH` | 上限のある意味的証拠を書き出して停止する |
| `--model-summary PATH` | モデルが作成したサマリーを検証して埋め込む |
| `--deterministic-summary` | モデル利用の明示的な無効化 |
| `--target-ratio R` | 出力バイト比率のおおよその計画値。厳格なゲートではない |
| `--target-estimated-tokens N` | ローカルの完全構造 Messages 推定における厳格な上限 |
| `--min-recent-records N` | 生の active サフィックスの下限 |
| `--summary-char-budget N` | compact サマリーの文字数予算。最小 4000 |
| `--model-pack-char-budget N` | 証拠パックの文字数予算 |
| `--model-pack-estimated-token-budget N` | 証拠パックのローカルトークン推定上限。既定値 150000 |
| `--resume-leaf UUID` | 復旧用リーフの明示的な上書き |
| `--max-post-last-prompt-extension N` | 完全な tool-result のみによる明示的なクローズ上限。既定値 0 |
| `--checkpoint-policy POLICY` | 厳格モード：`active-correlated` または `none`。`preserve-recent` は physical-tail 互換モードでのみ可 |
| `--preserve-prior-summaries-verbatim` | 繰り返し圧縮時の明示的な原文保持モード |
| `--preserve-physical-tail` | ブランチ分離の保証がない互換モード |
| `--replace-original` | 稼働中セッション 1 件をトランザクショナルに置き換える |
| `--confirm-session-closed` | 稼働中ファイルの置き換えに必要な呼び出し側の確認。プロセスロックの検出ではない |
| `--work-dir PATH` | 稼働中ファイルの置き換えに使う外部の処理ディレクトリ |
| `--backup-dir PATH` | 任意の外部バックアップディレクトリ |
| `--validate-only PATH` | 構造検証のみ |

完全な一覧は `--help` で確認してください。

## 検証の範囲

バリデーターは次の項目を確認します。

- 空でない行がそれぞれ JSON オブジェクトであること
- UUID の一意性
- 親レコードの存在とセッションの整合性
- 最終ポインタの参照先
- active チェーンが閉じていること
- 限定された attachment 順序および一方向セッション系統の互換性。安全でない変種は拒否される
- 現在の compact 境界と compact サマリーがそれぞれ 1 つであること
- compact メタデータの整合性
- 結合された assistant のフラグメントと、分割された user のツール結果
- API レベルでの `tool_use` / `tool_result` の順序と対応関係
- active なツール ID が空でなく一意であること。複数ツールの一部だけが順序どおりに揃った部分集合は、ブランチ互換性の警告として報告される
- 内部作業用フィールドが存在しないこと

検証は、観察によって把握された形式のルールに基づいて内部整合性を確認するものです。Claude Code のバージョンによっては、実行時のコンテキストの構築方法が異なる場合があります。

実行時テストが明示的に許可されている場合は、次の項目を個別に確認してください。

1. `/resume` でセッションが一覧表示され、開けること。
2. `/context` に想定どおりの Messages 使用量が表示されること。
3. 直近の会話の巻き戻しが機能すること。
4. 保持されたチェックポイントについて、直近のファイルの巻き戻しが機能すること。

`/context` の合計が大きいのに Messages が小さい場合、その原因はシステムプロンプト、ツール、MCP、agents、skills、メモリファイル、または新しく読み込まれた内容にある可能性があります。JSONL を再圧縮しても、これらのカテゴリは減りません。

## セッションロケーター

トランスクリプトの本文を読まずに、ファイル名またはセッション ID からちょうど 1 件のファイルを特定します。

```powershell
python "$skill\scripts\claude_session_tools.py" `
  --root "$env:USERPROFILE\.claude\projects" `
  --query "SESSION.jsonl"
```

`--scan-titles` は、タイトルによる照合が明示的に必要な場合にのみ候補ファイルを読み取ります。複数件が一致した場合はエラーです。圧縮側が、ディレクトリ全体を対象とした複数セッションの圧縮を行うことはありません。

## 開発と検証

標準ライブラリによるテストスイート一式を実行します。

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

リリース時の追加チェック：

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

リリーススイートは、active／不要ブランチの分割、固定シードによるトポロジー変換、厳格なポインタ失敗、2 系統のモデルパック予算、完全な構造化トークン計上、多言語の意味的な記録と thinking、ハンドオフ、リクエスト／主張のダイジェスト、必須の裏付け抜粋、ツールのペア、繰り返しの圧縮、チェックポイントポリシー、トランザクションの競合とコミット済みレポート状態、厳密なバイト単位の修復、BOM／CRLF、npm tarball の許可リスト、オフラインでの tarball インストールを対象とします。

### メンテナー向け RC リリースチェックリスト

1. 公開ツリーがクリーンであること、および `package.json`、Python のバージョン出力、ドキュメント、テストにおける `1.0.0-rc.1` の値が一致していることを確認する。
2. 上記の Python、npm、隔離 Python、tarball、プライバシー、オフラインインストールの各ゲートを実行する。
3. `npm pack --dry-run --json` を確認し、許可リストに載っているファイルのみを公開する。
4. ワークツリーがクリーンであることを要求し、注釈付きタグ `v1.0.0-rc.1` を作成して、コミットとタグをプッシュする。
5. 最初の手動 RC は、npm の 2 要素認証を有効にした認証済みのメンテナーのマシンから公開する。

```bash
npm publish --access public --tag rc
```

6. npm のバージョンと `rc` dist-tag を確認したうえで、既にプッシュ済みのタグから GitHub のプレリリースを作成する。

ローカルでの公開コマンドに `--provenance` を付けないでください。npm の provenance には、サポートされたクラウド CI ランナーが必要です。以降のリリースでは、公開 GitHub リポジトリから、GitHub ホストのランナー上で `id-token: write`、保護されたリリースタグ、対応する保護環境を用いた npm trusted publishing を推奨します。trusted publishing では provenance が自動生成されます。

レジストリの所有権、npm trusted-publisher の設定、認証情報、タグのプッシュ、GitHub プレリリースの作成、npm への公開は、いずれも外部のメンテナー作業であり、ローカルのテストスイートが保証するものではありません。

## リポジトリ構成

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

## プライバシー

- 公開プロジェクトに含まれるのは、匿名の合成フィクスチャのみです。
- モデルパックと候補ファイルのメタデータは `SOURCE_JSONL` のような汎用ラベルを使用します。生成されるレポートが公開するのはベース名のみで、ローカルのフルパスを公開することはありません。
- npm への公開では、拡張子レベルのファイル許可リストを使用します。
- JSONL、バックアップ、レポート、モデルパック、モデルサマリー、キャッシュ、コンパイル済み Python ファイルは、パッケージから除外されます。
- 生成された証拠パックは、共有する前に内容を確認してください。これらには選択されたトランスクリプトの証拠が意図的に含まれています。

## ライセンス

GPL-3.0-only。GPL の条項の下で、本プロジェクトを使用、調査、改変、再配布できます。改変版や本プロジェクトを組み込んだ版を配布する場合、対応するソースコードの提供と同一ライセンスの適用が必要になることがあります。配布される商用製品へ組み込む際は、ライセンスを確認してください。


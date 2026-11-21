# Claude JSONL Compressor

[English](../README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

Claude Code の長い会話を短くしても、なぜその案を選んだのか、何が未決なのかを手元に残せます。現在の分岐に沿って古いやり取りをまとめ、次のターンで読み込む量を減らします。大切な発言は原文のまま引用でき、直近のやり取りは `/rewind` に使える形で残ります。巻き戻しで取り消した分岐は要約から除きます。

## Codex への依頼例

> 「展覧会企画」というセッションを v12 で圧縮してください。合意した予算、作家の言葉、ほかの会場を見送った理由、まだ誰からどの許可を取る必要があるかを残してください。私が始めた直近2ターンは、ツールの呼び出しと結果も含めてそのまま残し、まず確認用の候補ファイルを作ってください。

スキルをインストールしたら、このように Codex に依頼できます。Codex が最終タイトルからセッションを探し、要約の執筆と提出、候補ファイルの作成まで進めます。同名のセッションがある場合はパスを指定します。再び圧縮するときは「前の要約を一字も変えず、その後の進展を追記して」と頼むこともできます。

## インストール

Python 3.10 以降を使います。npm コマンドには Node.js 22 以降が必要です。`npm install --global @brandry/claude-jsonl-compressor@1.2.0` を実行し、インストールしたパッケージを Codex の `skills/claude-jsonl-compressor` にコピーします。スクリプトはオフラインで動作し、資料を読むモデルは自分で選べます。[PowerShell の手順と Linux・macOS の配置先](../README.md#install)

## CLI で v12 を使う

**1. 計画を確認し、準備する。** 入力ファイルと新しい作業ディレクトリを指定します。この例では候補ファイルを推定15万トークン以内に収め、直近のやり取りを少なくとも2ターン残します。`plan` で残す範囲と執筆タスクを確認し、`prepare` でバックアップと各タスクの依頼書を作成します。

```powershell
claude-jsonl-compressor v12 plan --input "C:\data\session.jsonl" --min-recent-turns 2 --target-estimated-tokens 150000
claude-jsonl-compressor v12 prepare --input "C:\data\session.jsonl" --min-recent-turns 2 --target-estimated-tokens 150000 --run "C:\work\first-run"
claude-jsonl-compressor v12 status --run "C:\work\first-run"
```

**2. 草稿を書いて提出する。** `pending` に表示されたタスクごとに、対応する依頼書（例 `map-001.md`）と執筆ガイドをモデルに渡します。タスクごとに新しいコンテキストを使い、出典を添えた短い Markdown の草稿を保存します。低コストのモデルでも手順は同じです。草稿の検査と JSONL の組み立てはスクリプトが行います。[執筆ガイド](../references/v12-memory.md)

```powershell
claude-jsonl-compressor v12 submit --run "C:\work\first-run" --task map-001 --draft "C:\work\draft.md"
claude-jsonl-compressor v12 status --run "C:\work\first-run"
```

以降は `status` のタスク ID に従います。統合タスク（Reduce）が現れたら、現在有効な決定と、後に変更された決定を整理して提出します。検査で指摘があった草稿は、その一件だけ修正して再提出できます。

**3. 候補ファイルを作る。** `pending` が空になり、`finalJob` に受理済みのタスク ID が表示されたら、次のコマンドを実行します。作業ディレクトリにできた `candidate.jsonl` で会話を続けられます。根拠資料、検査記録、費用の試算は同じディレクトリに別途保存されます。

```powershell
claude-jsonl-compressor v12 finish --run "C:\work\first-run"
```

### 引き継ぐ内容を選ぶ

| オプション | 用途 |
|---|---|
| `--prior resynthesize` | 既存の知識と新しい根拠を一つの要約にまとめ直す。v12 の既定値。 |
| `--prior verbatim-locked` | 空白や改行を含めて以前の要約をそのまま残し、新しい内容を追記する。 |
| `--prior clean-and-merge` | 以前の要約とそこにしかない引用を見直し、引き続き必要な内容を新しい要約にまとめる。 |
| `--min-recent-turns N` | ユーザーが始めた直近 N ターン以上を、ツールの呼び出しと結果も含めて残す。 |
| `--media archive` | ユーザーの許可を得て、読み取っていないメディアを明記し、元データをバックアップに保存する。 |

予算の改定では、変更前後の金額と単位、いつから適用されるかを一緒に残せます。許諾については、誰が誰に、どの範囲で利用を認めたかを記します。契約条項や史料は、出典と行番号を添えて原文のまま引用できます。同じ出典の連続する引用は出典を一度だけ示し、行番号は各箇所に残せます。[原文の引用](../references/v12-excerpts.md)

## バックアップと復元

候補ファイルは元ファイルとは別に作成します。準備時に元ファイルの隣に `session.jsonl.backup` を作り、同名ファイルがあれば `session.jsonl.backup1`、`session.jsonl.backup2` と番号を付けます。元ファイルを置き換える場合は対象セッションを閉じ、置き換えを明示します。ファイル変更を巻き戻すには、残したターンに対応する Claude のスナップショットが必要です。ツールを使ったターンの最後の応答に添付記録が続いても、復元時にはその応答を特定できます。ツールがテキストとメディアを一緒に返す場合は、読める本文とキャプションを残します。

v11 の2段階コマンドも使えます。アップグレード後は根拠資料のパックを作り直してください。[スキルの説明と v11 コマンド](../SKILL.md) · [v12 の操作と復元](../references/v12-workflow.md) · [要約の書き方と移行](../references/v12-memory.md) · [形式と修復](../references/claude-jsonl-compression-format.md) · [変更履歴](../CHANGELOG.md)

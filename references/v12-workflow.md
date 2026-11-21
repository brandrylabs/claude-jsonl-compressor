# v12 commands and private run files

Codex uses the `v12` subcommand internally for ordinary compression requests. It is also available through the Python and npm command-line entry points. The Python scripts use the standard library. A writing model supplies the semantic drafts.

## Plan and freeze

Run `v12 plan --input FILE` with the selected budget, recent record/turn minimums and prior policy. Use `v12 prepare` with the same options. Add `--run NEW_DIRECTORY` to choose the destination or take the run path printed by prepare. The default is a per-user persistent runs directory under LocalAppData, XDG state, or Application Support. Both the configured `CLAUDE_CONFIG_DIR` and directories named `.claude` receive live-tree protection.

A standalone-file example targets 100,000 estimated tokens and sets a floor of three recent raw records. The active branch and complete tool exchanges determine how many records actually stay. Use a new run directory.

```powershell
claude-jsonl-compressor v12 plan --input "C:\data\session.jsonl" --min-recent-records 3 --target-estimated-tokens 100000
claude-jsonl-compressor v12 prepare --input "C:\data\session.jsonl" --min-recent-records 3 --target-estimated-tokens 100000 --run "C:\work\first-run"
claude-jsonl-compressor v12 status --run "C:\work\first-run"
```

Prepare freezes the source digest, identity, selection, policy, implementation fingerprint, budgets and request digests. It creates and verifies an independent numbered backup beside the source. Supply `--backup-dir DIRECTORY` for an external backup, including a read-only source directory. All request, audit and recovery files contain private material and belong in the run directory.

Use the default `--prior resynthesize` to develop a new memory from the evidence. Choose `verbatim-locked` for an exact copy of every selected prior summary followed by the delta. Choose `clean-and-merge` to inspect recognized spans, resolve residual excerpts and record their disposition. Preserve empty or unfamiliar historical structures in their original source when the workflow diagnoses an unsupported shape. See [writing and migration](v12-memory.md).

`--min-recent-turns N` protects full recent human turns. `--min-recent-records N` sets a raw-record floor. `--resume-leaf UUID` requires an explicitly identified recovery endpoint. Raw retention preserves tool payloads and native thinking signatures. `--media block` diagnoses unread binary media in the old region. Either keep the affected turn raw or obtain authorization for `--media archive`, then record its unread status in the working memory. Only the explicitly known read range can support a claim about a document.

## Complete a request

Use the optional passage catalog to keep unique clauses, dated evidence or attributed wording inside the JSONL. `--excerpts N` sets the number of passages offered per window. The writer selects each retained passage and records its status. Each final selection must fit the character and structured token ceilings. [Source excerpts](v12-excerpts.md)

Give the writer its assigned `map-001.md` and the [writing protocol](v12-memory.md). Each task uses its own context. Repeated tool text can use a single exact definition within the request. Source IDs bind claims to the original material. For a locked prior, the request shows character ranges and a bounded reference. Offsets start at zero and exclude the end. Using `--locked-range P1:20-75` for both plan and prepare selects 55 characters of the first locked summary (offsets 20 through 74). `--locked-context-chars` sets the shared character allowance. The request estimate includes the displayed text and its labels. Choose a writer authorized to receive the assigned material.

```powershell
claude-jsonl-compressor v12 submit --run "C:\work\first-run" --task map-001 --draft "C:\work\draft.md"
claude-jsonl-compressor v12 status --run "C:\work\first-run"
```

Use status to obtain the next task ID. Two or more Maps produce a Reduce request. Hierarchical Reduce requests carry the validated notes forward when their combined input exceeds a window. Reconcile decisions in time order, including the scope of superseded decisions, the alternatives rejected and the reason. When `pending` is empty and `finalJob` names the accepted task, finish the run.

```powershell
claude-jsonl-compressor v12 finish --run "C:\work\first-run"
```

Finish verifies the final draft and writes `candidate.jsonl`, `audit.json` and `result.json`. The summary message contains the knowledge text. The compact boundary binds the audit and the audit binds the summary digest, task receipts and original source.

Submit records failures and leaves accepted independent work available. Each intermediate draft and the literal passages it carries must fit together in the next Reduce input. If the diagnostic names an oversized draft, shorten that draft or narrow its selected lines and resubmit it. Supply the writer's reported stop reason with `--stop-reason max_tokens` or `length` when appropriate. An incomplete draft or a failed source check requires a corrected draft for that task. The default allowance is three attempts per task. Reopen a run with status after an interruption. If its recorded implementation or source has changed, prepare a new run. If an interrupted process leaves an operation lock, confirm its recorded process has stopped before removing that lock.

## Budgets and cost

One tool exchange or a set of fragments from one native message must fit together. If the plan reports that such a group exceeds the input limit, increase the profile within the host's supported window or retain that complete turn in the raw portion. Historical summary text and its residual obligations can be divided across writing tasks. The next Reduce input still has to fit each accepted parent note together with the quotations it carries.

`--target-estimated-tokens` sets the final conservative structured ceiling. The profile also bounds each independent model request. Codex chooses a suitable input budget when the user leaves it open. Each task takes the longest consecutive group of complete evidence units that fits the rendered input and the reserved output for reviewing earlier quotations. One accepted Map finishes directly. Use `--other-input` for all instructions, tools, prior turns and extra reads, `--generation` for the draft and audit output, `--thinking` for reasoning, `--margin` for estimation error and `--output-limit` for the host's actual maximum. Set `--window` and `--input-limit` to the supported window and requested input ceiling. Each prepared request fits below 300,000 estimated input tokens and, including generation, thinking and margin, within 372,000 or the chosen smaller window. If available, check the complete outgoing request with the host's counter before sending. Provide measured totals at submit with `--observed-input` and `--observed-output`. The intermediate allowance scales with Map count; the final draft is independently bounded.

The result reports the conservative structural estimate, message-content estimate and most recent recorded API input usage (including cache read and creation). The last value refers to a historical request. A three-scenario cost estimate uses one-time authoring and the first rebuild difference, then compares later warm, cold and half-warm requests. Relative prices can be supplied with `--prices FILE`; illustrative weights are writer input/output 0.1, consumer input 1.0, cache read 0.1 and cache write 1.25. Use comparable units for all entries. No account credentials are needed.

## Closed live sessions

For in-place work add `--live --confirm-session-closed` at prepare, then `--replace-original --confirm-session-closed` at finish. The target must be one verified project session. The transaction reuses this run's verified backup and checks the source again, then installs and rereads the candidate. A failed filesystem capability check leaves the candidate available. Inspect the replacement receipt after a committed report or cleanup failure (exit 3). File rewind depends on the original tracked file snapshots.

For the v11 two-pass CLI and the separate byte-preserving Read.pages repair, see [the skill](../SKILL.md) and [the format reference](claude-jsonl-compression-format.md).

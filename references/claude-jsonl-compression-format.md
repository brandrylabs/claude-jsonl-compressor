# Claude Code JSONL Compression Format Notes

This document describes the empirical format handled by
`@brandry/claude-jsonl-compressor` package `1.0.0-rc.1` and engine `v10`.

Claude Code transcript JSONL is an observed internal format, not a published
stable storage API. The rules below are deliberately strict where ambiguity
could restore a rewound branch, break resume topology, or make a tool exchange
incoherent.

## Version Domains

The project keeps four independent version domains:

| Domain | Current value | Meaning |
| --- | --- | --- |
| Package | `1.0.0-rc.1` | GitHub/npm release version |
| Compression engine | `v10` | Topology, partition, and rewrite behavior |
| Model-pack schema | `v11` | Evidence-pack and model-summary binding protocol |
| Report schema | `1` | Compression and repair report fields |

A change to one domain does not imply the other domains changed.

## Three Physical and Logical Layers

A transcript can contain records that play very different roles:

1. **Active API-message chain.** `user` and `assistant` records connected from
   the selected resume leaf through `parentUuid`. This is the history that the
   compressor may summarize or preserve verbatim.
2. **Control and side records.** `last-prompt`, titles, modes, attachments,
   hooks, and `file-history-snapshot` records may exist physically in the file
   without becoming ordinary API messages. They require explicit projection or
   attribution rules.
3. **Inactive or unattributed records.** Rewound branches and records that
   cannot be structurally attributed to the active branch remain useful only
   for diagnostics. Engine v10 excludes their content from every Claude-readable
   output layer and from every model-summary evidence channel.

Physical line order alone is therefore not a definition of current context.

## Common Observed Record Types

| `type` | Observed purpose |
| --- | --- |
| `user` | User content or user-side `tool_result` blocks |
| `assistant` | Assistant text, thinking, `tool_use`, model metadata, and usage |
| `system` | Claude Code events, including `subtype: compact_boundary` |
| `attachment` | Hook, image, file, or environment attachment metadata |
| `last-prompt` | UI/session pointer containing the current `leafUuid` |
| `file-history-snapshot` | File checkpoint metadata, commonly without UUID links |
| `mode` / `permission-mode` | Session mode state |
| `ai-title` / `custom-title` | Conversation title metadata |
| `queue-operation` | Queued-input or editing metadata |
| `agent-name` | Agent label metadata |

Open-schema handling is required: unknown fields are preserved on retained
records unless the operation explicitly projects a control record.

## UUID, Parent, Session, and Resume Relationships

### UUID chain

Message-like records commonly carry:

- `uuid`: record identity;
- `parentUuid`: preceding record on that branch, or `null` at a root;
- `sessionId`: session identity.

Engine v10 treats duplicate UUIDs anywhere in the input as blocking because a
UUID index would be ambiguous. A non-null `parentUuid` must be a non-empty
string; any other value is malformed. A missing parent, malformed parent or loop
on the selected active chain is blocking. Physical inversion is blocking except
for same-session `attachment -> attachment` edges on an otherwise complete,
acyclic chain; accepted attachments are emitted in logical parent order.
Equivalent non-UUID-ambiguity damage wholly inside an excluded branch does not
revive that branch.

Mixed `sessionId` ancestry is not rejected merely because two IDs occur. A
lineage is accepted only when its contiguous session runs never return to an
earlier ID and the final run matches both the selected leaf and authoritative
pointer. Planning forces every earlier run into `summaryIndexes` and preserves
only the final run as recent raw records. A tool relationship that would move
the cut across the lineage transition stops compression. This covers observed
historical branch/resume files without admitting A-B-A or arbitrary cross-session
raw chains.

### Authoritative `last-prompt`

Automatic active-chain mode uses the physically last record whose
`type` is `last-prompt`. Its `leafUuid` is authoritative. The engine does not
skip a malformed latest pointer to search for an older usable pointer because
that could resurrect a state the user already left.

Strict topology statuses include:

- `absent`
- `malformed`
- `malformed-parent`
- `duplicate-uuid`
- `dangling`
- `loop`
- `non-monotonic`
- `session-mismatch`
- `extension-limit`
- `extension-branch`
- `extension-unsafe`
- `valid`

`--resume-leaf UUID` is an explicit recovery override. It is reported as
`active-chain-manual-override`, distinct from default strict `active-chain`.
`--preserve-physical-tail` is a separate legacy compatibility
mode and does not provide active-branch exclusion guarantees.

Strict failures are zero-write outcomes. The CLI does not prompt or retry in a
different mode. A hosting agent may ask for a new, explicit user confirmation
when one diagnosed recovery control applies, but the initial compression request
is not confirmation. Manually spliced or otherwise ambiguous files normally
require physical-tail compatibility and therefore forfeit branch/rewind
isolation.

### Records after `last-prompt`

The default `--max-post-last-prompt-extension 0` excludes all UUID records
physically after the authoritative pointer. A nonzero value is explicit and
accepts only a direct, physically later, same-session linear closure consisting
of tool-result-only user records that close every pending tool ID. Ordinary
conversation, system/hook records, unrelated results and partial closure are
rejected as unsafe.

## Six-Way Source Partition

After strict topology succeeds, every source line belongs to exactly one set:

| Set | Meaning | May reach Claude-readable output? |
| --- | --- | --- |
| `summaryIndexes` | Older active-chain records selected for semantic summary | Yes, only through the new summary |
| `rawKeepIndexes` | Recent active-chain records kept byte-semantically as JSON objects | Yes, as recent raw history |
| `sideKeepIndexes` | Explicitly attributed side/checkpoint records | Yes, as non-chain side records |
| `controlProjectionIndexes` | Control metadata used to construct the final projected state | Yes, only through controlled projection |
| `excludedBranchIndexes` | UUID records outside the selected active branch | No |
| `excludedUnattributedIndexes` | Records with no accepted structural attribution | No |

The sets are mutually exclusive and cover every source index. The legacy
internal/report name `omittedIndexes` is only a compatibility alias for
`summaryIndexes`; it no longer means every physically discarded record.

Before a model pack or candidate is written, the engine copies only the
authoritative logical active chain, projects its selected leaf into one pointer,
and runs the shared transcript validator on that source view. Malformed old tool
exchanges, duplicate tool IDs, or compact metadata on the active chain therefore
cannot be hidden by summarization. Damage confined to an excluded inactive
branch remains excluded and does not block or enter the summary.

Inactive and unattributed record bodies are absent from:

- the model evidence pack;
- model-authored summary validation input;
- deterministic fallback summary input;
- prior-summary verbatim blocks;
- recent raw records;
- side records;
- the final candidate JSONL.

Reports may expose only counts and content-free line-set digests for excluded
sets.

## Compact-Style Output Pair

The engine emits exactly one current Codex-created compact pair:

1. a `system` record with `subtype: "compact_boundary"`;
2. its direct `user` child with `isCompactSummary: true`.

Simplified synthetic shape:

```json
{"type":"system","subtype":"compact_boundary","uuid":"BOUNDARY_UUID","parentUuid":null,"compactMetadata":{"codexOfflineCompression":true,"codexOfflineCompressionVersion":"v10","modelPackSchemaVersion":11,"reportSchemaVersion":1,"summaryUuid":"SUMMARY_UUID","preserveMode":"active-chain","resumeLeafInfo":{"status":"valid","selectedLeafUuid":"ACTIVE_LEAF"}}}
{"type":"user","uuid":"SUMMARY_UUID","parentUuid":"BOUNDARY_UUID","isCompactSummary":true,"message":{"role":"user","content":"SUMMARY_TEXT"}}
```

The exact open-schema object contains additional observed metadata. The current
pair is followed by the recent active suffix. In strict active-chain mode, only
the first recent record has its parent changed to `SUMMARY_UUID`; every later
recent parent/session edge must already be coherent. A final `last-prompt` is
deep-copied from the authoritative source pointer so unknown fields survive,
then only its projected leaf/session values are updated.

Validation requires the final pointer's active chain to contain the exact
current boundary and summary, not merely an older compact pair.

## Model-Assisted Summary Protocol v11

Model-assisted semantic summary is the default. Deterministic code owns all
topology, source partitioning, JSONL construction, UUID generation, parent
rewrites, and validation. The model receives only the frozen evidence pack and
writes summary prose.

### Evidence binding

The generated pack contains:

- a generic `SOURCE_JSONL` label, never the original filename or full local path;
- full source-file SHA-256;
- SHA-256 of the exact active records selected for summary;
- the digest of the displayed evidence-anchor set;
- the digest of all required evidence-coverage groups;
- the digest of an optional external handoff summary;
- a canonical request digest binding all selection/budget/policy options and the
  loaded importance/topic/template resource content;
- a digest of the mandatory claim-source map;
- a full-text `L<number>` record for every non-empty older active human message
  and every older active assistant `text`/`thinking` message;
- selected line-numbered source/tool/error evidence;
- `H<number>` anchors for displayed handoff lines;
- explicit current-state, chronology, supersession, decision, rationale,
  rejected-option, uncertainty, and recent-boundary instructions.

The model summary must begin with the exact comment copied from the pack:

```html
<!-- claude-jsonl-compressor:model-summary v11
source_sha256: SOURCE_SHA256
summary_source_sha256: SUMMARY_SOURCE_SHA256
evidence_anchor_lines_digest: EVIDENCE_ANCHOR_LINES_DIGEST
required_anchor_groups_digest: REQUIRED_ANCHOR_GROUPS_DIGEST
handoff_summary_digest: HANDOFF_SUMMARY_DIGEST_OR_NONE
pack_request_digest: PACK_REQUEST_DIGEST
required_claim_sources_digest: REQUIRED_CLAIM_SOURCES_DIGEST
-->
```

Substantive factual lines cite displayed `L<number>` and, when used, `H<number>`
anchors. The exact whole line `Unknown from provided anchors.` is the only
unanchored uncertainty placeholder; a longer line containing that text has no
exemption. Validation rejects wrong digests, invisible or out-of-range anchors,
unanchored substantive lines, too little evidence coverage, and common
no-access boilerplate. It requires at least one cited L anchor from each
generated group. Every non-empty human/assistant semantic record has its own
required L group, and prior summaries remain independently required. It also
requires all nine exact semantic sections printed in the pack, each with an L
or H anchor. A nonempty handoff generates early/middle/late/latest H coverage
groups that must all be cited. Handoff text is not trusted merely because it
contains a special phrase; only generated H anchors are accepted.

Only the exact leading metadata comment and the exact required headings are
exempt from line grounding. A second/unclosed HTML comment, an extra Markdown
heading, duplicate metadata, renamed/reordered sections, or unsupported body
line is an error. Under `## Evidence and Source Anchors`, the summary must contain
exactly one `### Mandatory Evidence Coverage` subsection. Every mandatory
semantic/prior-summary L anchor appears exactly once as:

```text
- L42 support_text_json="exact source substring" disposition=covered
```

The JSON string must decode to a meaningful exact substring of that source
record. This blocks a content-free anchor dump and leaves a mechanically
checkable excerpt; it does not prove perfect natural-language interpretation.

Every active-chain prior compact summary is inserted as a complete dedicated
evidence record. An explicitly supplied external handoff is inserted in full,
one JSON-escaped `H<number> full_text_json` line per source line. Two default
pack ceilings apply together: 500,000 characters and a conservative 150,000
local estimated tokens. The latter leaves working space in a typical 200k
summarizer context. If the complete semantic ledger, prior summaries, handoff,
and minimum structural coverage do not fit, pack generation stops; it does not
trim or sample mandatory evidence. Optional source/tool/system/error evidence
is ranked and added only while both ceilings permit, and truncation is reported.
The caller should raise `--model-pack-char-budget` or
`--model-pack-estimated-token-budget` only when the summarizing model can read
the resulting pack. No external tokenizer is installed. Once a model summary
passes validation, its text is not truncated to meet `--summary-char-budget`;
insufficient composition space is a hard error. The summary character budget
has a hard minimum of 4000, and blank compact summaries are invalid.

These controls reduce stale-summary and unsupported-claim risk. They do not
mathematically prove that a natural-language summary has perfect semantics.
The deterministic safety appendix and recent raw suffix remain independent
evidence layers.

### Weighting and chronology

The evidence pack requires every non-empty older active human message and every
older active assistant `text`/`thinking` message, regardless of language or
keyword score. Source-text warnings such as U+FFFD are reported but do not make
mandatory records optional. Within the remaining optional source/tool capacity it gives
priority to:

1. explicit user constraints and requested outcomes;
2. final/current decisions and their reasons;
3. supersessions and chronology needed to avoid reviving old decisions;
4. model research conclusions, implementation decisions, and rationale;
5. unresolved risks, exact identifiers, source references, and validation
   results;
6. file/tool content that materially supports the above;
7. repetitive logs or mechanically recoverable detail.

Important evidence can be Chinese, English, Japanese, Korean, Arabic, Russian,
Hindi, Greek, Hebrew, Armenian, Thai, Georgian, Ethiopic, Bengali, Tamil,
Telugu, Malayalam, Spanish, French, German, Portuguese, or another language.
All assistant thinking is semantic evidence without a language-keyword gate;
multilingual terms and script detection only improve classification and optional
weighting. Language is not treated as a proxy for importance.

## Token Ceilings

`--model-pack-estimated-token-budget N` limits the evidence pack read by the
summary-authoring model. It defaults to 150,000 and is enforced together with
the character budget. The same non-default value must be supplied when
generating the pack and when applying the model summary. Mandatory semantic and
handoff evidence cannot be dropped to satisfy it; optional evidence can be
truncated and this state is recorded in the pack, compact metadata, and report.

`--target-estimated-tokens N` uses a dependency-free heuristic over complete
retained structured message payloads, including full thinking,
`tool_use.input`, `tool_result`, and `toolUseResult` data. ASCII is estimated at
one token per four characters;
Han/Kana/Hangul at 1.3 each; non-BMP, symbol and combining-mark code points at
1.5 each; other non-ASCII at 0.8 each; and each record adds a small allowance.
It narrows the byte-ratio plan and rejects a generated candidate whose
estimated message tokens exceed `N`. This candidate-output gate is independent
of the model-pack reading ceiling.

This estimate excludes system prompts, tools, MCP schemas, skills, runtime
injections, and any Claude-side accounting. It is a reproducible local planning
gate, not a promise that `/context` or an API relay will report the same total.
`--target-ratio` is only an approximate byte-ratio planning input and is not a
hard publication gate.

## Tool Use and Tool Result Pairing

One API turn may be split across several JSONL records:

- multiple `tool_use` blocks in one assistant message;
- adjacent assistant fragments sharing one `message.id`;
- split user records carrying `tool_result` blocks;
- hook or attachment records between result fragments.

Validation rebuilds the selected active chain, filters API messages, merges
compatible assistant and user fragments, and checks tool IDs and order. It
rejects orphan results, wrong IDs, and out-of-order results. The compression cut
cannot divide a required tool-use/result relationship.

## File-History Checkpoint Policies

Conversation topology and file checkpoint metadata are separate planes.
`file-history-snapshot` records commonly lack `uuid` and `parentUuid`, so they
cannot be relinked into the API-message chain.

Policies:

- `active-correlated` (default): retain a bounded set only when structural
  identifiers correlate the snapshot to recent active records;
- `preserve-recent`: rejected in strict active-chain mode; accepted only with
  explicit `--preserve-physical-tail`, which is labeled compatibility mode and
  has no inactive-branch isolation guarantee;
- `none`: retain no snapshot side records.

Preserved snapshots are emitted as side records before the compact pair. JSONL
compression alone does not guarantee complete file-state rewind because Claude
Code checkpoint storage and lifecycle have behavior beyond the message chain.

## Repeated Compression

Old compact pairs on the active chain are part of `summaryIndexes` when they
fall before the recent suffix. Normal repeated compression folds their useful
meaning into one new current summary rather than stacking live compact pairs.

`compactMetadata.preservedMessages` and `preservedSegment` describe the raw
suffix that existed when that compact pair was created. Later work can extend
that suffix, and a later rewind can leave part of the recorded snapshot on an
inactive branch. A structurally valid historical divergence is therefore a
source warning, not authority to restore those UUIDs and not a topology error.
Selection continues from the current `last-prompt` parent chain. Candidate
publication is stricter: the newly emitted snapshot must match the candidate's
current chain exactly or publication stops before writing.

`--preserve-prior-summaries-verbatim` is an explicit exception. It attempts to
embed prior `isCompactSummary.message.content` text verbatim inside the one new
summary and permits the summary text to grow to `1.5 * --summary-char-budget`.
If the prior summaries still do not fit, the engine uses the normal folded
model-summary path and reports the fallback reason. Excluded-branch summaries
are never eligible for either path.

## Branch Session Files

Observed `/branch` files are not guaranteed to be full physical copies. They
may retain source UUIDs, rewrite `sessionId`, add `forkedFrom`, relink parents,
and omit source history outside the branch-relevant chain.

The compressor treats exactly one selected JSONL as authoritative. It does not
merge a branch file with its source. Compress the branch to continue the branch;
compress or archive the source separately when its physical history matters.

## External References

JSONL may contain inline tool results, file excerpts, attachment metadata, or
paths/references to external artifacts such as tool-result storage. Offline
compression reads the selected JSONL and an explicitly supplied handoff file
only. It does not dereference, delete, or rewrite external project files,
`tool-results`, subagent artifacts, settings, or other sessions.

If a referenced artifact's contents are not embedded in the JSONL or handoff,
the model pack knows only the reference, not the external contents.

## `Read.pages` Compatibility Repair

Claude Code legitimately uses `Read.input.pages`, including for paged document
reads. The independent repair command exists only for a known downstream
compatibility case where historical serialized `pages` members must be removed.
Compression never invokes this repair implicitly.

The repairer:

- matches only assistant `tool_use` blocks with exact tool name `Read` and an
  `input` object containing `pages`;
- requires a nonempty `file_path`, exactly one later matching `tool_result`, the
  same nonempty `sessionId`, and result `sourceToolAssistantUUID` equal to the
  tool-use assistant UUID before automatic repair;
- reports pending calls without changing them;
- defaults to the strict active chain; `--scope all` is explicit;
- deletes the exact JSON member byte span without reserializing other data;
- blocks duplicate-key or overlapping-span ambiguity;
- preserves BOM, newline style, Unicode spelling, unknown fields, record count,
  UUID/parent signature, and tool ID sequences;
- re-reads the actual published candidate, verifies exact expected bytes and
  SHA-256, validates the repair invariants, requires an idempotent second scan
  with zero remaining patches, and runs the shared full-transcript
  UUID/parent/compact/tool validator on the published bytes.

Candidate and live replacement modes use the same atomic-write, full-hash,
numbered-backup, source-race, validation, and rollback principles as compression.

## Candidate and Live Replacement Transactions

Candidate mode requires distinct input and output paths. Candidate JSONL,
reports, validation, model packs, summaries and work directories must remain
outside the entire `.claude` tree.

Live replacement mode requires one existing regular `.jsonl` input under
`.claude/projects`, an external `--work-dir`, and caller acknowledgement
`--confirm-session-closed`. The acknowledgement is an operational assertion,
not process-lock detection. It:

1. reads and hashes the complete original bytes;
2. writes and validates a candidate outside `.claude`;
3. rechecks that the source bytes did not change;
4. creates an exclusive `.backup`, `.backup1`, and so on;
5. validates immutable candidate bytes and writes a unique same-directory stage
   with flush/fsync;
6. captures the actual old target, verifies its full bytes against the frozen
   source, and publishes the staged candidate with an atomic no-clobber claim;
7. verifies published bytes and structure, restoring the captured original on
   failure. If restoration fails, the numbered verified backup remains and the
   error is promoted.

If another process recreates the target after capture begins, the transaction
does not overwrite the external target. It preserves the verified numbered
backup and, when necessary, places the captured original in another numbered
backup, then fails without publishing the candidate.

Candidate-mode reports are written with the candidate. Live compression delays
its final sidecar/report until replacement metadata is available, so it does not
leave a stale pre-commit report. If the JSONL commits and validates but final
report publication fails, compression returns exit code 3 with
`operation_state: committed-report-failed`; repair uses the camelCase equivalent
`operationState`. The receipt includes public artifact labels and frozen,
candidate, and published hashes. This is a committed state and is not rolled
back or reported as an ordinary uncommitted failure.

Once a numbered backup is created and verified, later failure cleanup never
deletes that path. This preserves an audit/recovery asset even when publication
or rollback fails or another process races on a nearby name.

Claude Code should be closed for that session during replacement. No other
session or Claude settings file is part of the transaction. Parent-directory
fsync is best effort and reported; the project does not promise cross-platform
power-loss atomicity.

## Validation Boundary

The validator checks observed-format coherence, including:

- parseability and object-per-line structure;
- unique UUIDs and resolvable parent/session links;
- exactly one current compact pair;
- current compact pair reachability from the final pointer;
- compact preserved-message metadata;
- non-empty, unique active tool IDs and tool-use/result pairing after fragment
  merging; partial multi-tool ordered subsets are accepted only with an explicit
  compatibility warning/count;
- absence of internal planning fields in output;
- source hashes, model-pack metadata, anchor sets, and target estimates where
  applicable.

Passing these checks proves coherence under this project's empirical rules. It
does not make the private transcript format an Anthropic-supported public API.
When runtime testing is explicitly requested, `/resume`, `/context`, recent
conversation rewind, and recent file rewind are separate observations.

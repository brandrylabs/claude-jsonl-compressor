# Tests

The release test suite is dependency-free and uses only Python's standard
library plus synthetic Claude-style transcripts. It does not read real Claude
sessions, invoke Claude Code, or require network access. The package tests use
the locally installed Node/npm executables to build and install a temporary
tarball offline.

## Run

From the project root on Windows:

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B tests\test_compressor.py
python -B tests\test_repair.py
python -B tests\test_package.py
python -B tests\test_transaction_races.py
python -B tests\test_semantic_evidence_contracts.py
python -B tests\test_structural_safety_contracts.py
python -B tests\test_protocol_contracts.py
npm test
npm pack --dry-run --json
```

On POSIX, replace backslashes with slashes.

The seven direct test-file invocations intentionally complement discovery and
exercise standalone entry points. Release verification also runs CLI smoke tests under
`python -I -S` to prove that runtime behavior does not import site packages.

## Layout

- `_fixtures.py`: import bootstrap, transcript builder, synthetic branches,
  fragments, tool pairs, compact pairs, snapshots, and pointer helpers.
- `test_compressor.py`: topology, partition, semantic-summary protocol,
  candidate generation, validation, repeated compression, transaction failure
  injection, session location, and built-in token ceiling.
- `test_repair.py`: exact byte-span `Read.pages` repair, active/all scope,
  pending calls, duplicate keys, BOM/newlines/Unicode, idempotence, candidate
  mode, and live numbered backup.
- `test_package.py`: manifest policy, Node wrapper syntax/version parity, actual
  npm tarball allowlist/privacy scan, offline install, and CLI invocation.
- `test_transaction_races.py`: publication-race and immutable-candidate fault
  injection regressions that cross compressor and repair transaction layers.
- `test_semantic_evidence_contracts.py`: complete full-text human/assistant semantic
  ledger, multilingual thinking, handoff H coverage, exact unknown placeholder,
  schema-v11 gates, default 150k pack estimate, optional evidence truncation,
  and mandatory-ledger overflow failure.
- `test_structural_safety_contracts.py`: no-clobber install/rollback races,
  persistent audit backups, whole-`.claude` process isolation, strict snapshot
  shape, locator containment, and live-session acknowledgement.
- `test_protocol_contracts.py`: request/claim digest binding, mandatory support
  excerpts, visible Markdown grounding, strict handoff decoding, source-chain
  preflight, tool-ID multiplicity, exact locator semantics, committed-report
  states, full repair validation, zero-write, and template parity.

## Required Behavioral Gates

### Resume topology and rewind isolation

- The physically last `last-prompt` is authoritative; malformed latest
  pointers are not skipped.
- Missing leaves, bad active parents, loops, recurring/authority-mismatched
  session lineage, ordinary-message forward edges, and global duplicate UUIDs
  block strict mode.
- Same-session attachment-only physical inversions normalize to logical order;
  one-way session lineage forces every prior session into summary evidence and
  keeps only the final session raw. Tool pairs cannot cross that forced cut.
- Inactive branches never appear in model packs, deterministic summaries,
  model summaries, prior-summary verbatim blocks, side records, raw records, or
  candidate JSONL.
- The six source partitions are mutually exclusive and complete, including in
  fixed-seed generated branch topologies.
- Post-pointer closure is opt-in, linear, same-session, tool-result-only, and
  must close every pending tool ID; ordinary conversation, system/hook records,
  unrelated results and partial closure are rejected.

### Compression and semantic summaries

- Engine `v10`, model-pack schema `v11`, report schema `1`, and package version
  fields remain distinct.
- Model-assisted summary is the default; deterministic fallback is explicit.
- Full source and summary-source hashes, canonical request/resource settings,
  claim-source maps, visible L/H anchor sets, and handoff digest binding reject
  stale or fabricated summary artifacts.
- Every non-empty older active human message and assistant `text`/`thinking`
  message is full-text evidence with an individual mandatory anchor group and
  exact support excerpt. A U+FFFD warning does not discard mandatory content.
  Early/middle/late/latest, source/tool, prior summaries, and nonempty-handoff H
  coverage remain required, and all nine semantic sections require anchors.
- Recent tool-use/result relationships are not cut across the compression
  boundary.
- The authoritative source chain itself passes shared compact/tool validation
  before semantic evidence generation; duplicate/empty tool IDs are errors and
  partial ordered subsets are explicit compatibility warnings.
- Repeated compression creates one current compact pair; explicit prior-summary
  verbatim preservation follows the 1.5x character-budget guard.
- A prior compact snapshot may diverge after a later rewind and must produce a
  source warning without restoring the inactive tail; a newly published
  candidate must have a current, exact compact snapshot.
- `--target-estimated-tokens` rejects an over-ceiling candidate before
  publication using complete structured retained payloads, without installing
  a tokenizer. Ratio-only targeting remains approximate planning.
- `--model-pack-estimated-token-budget` makes the model evidence pack
  independently enforce both 500,000 characters and a default 150,000-token
  local estimate. Optional evidence may truncate with an explicit diagnostic;
  complete user/model semantic evidence may not.
- Summary budgets below 4000, blank compact summaries, truncated handoffs,
  unanchored placeholder injection, and lost multilingual decisions fail.

### Checkpoint and transaction behavior

- Default snapshot retention requires active correlation; unattributed
  snapshots are excluded. `preserve-recent` is rejected in strict mode and is
  available only through explicit physical-tail compatibility.
- Candidate publication is temp-write, fsync, validate, and atomic replace.
- Live replacement uses full-byte source hashes, exclusive numbered backups,
  no-clobber target publication/restoration, source-race detection,
  post-replacement validation, persistent audit backups, and rollback on
  failure. It requires an existing regular `.jsonl` target plus explicit caller
  acknowledgement that the session is closed before any live write.
- Concurrent target recreation preserves the external target plus verified
  recovery backups and never reports candidate publication.
- Failure injection covers write, fsync, validation, backup, source recheck,
  replacement, and post-validation stages.
- Live commit followed by report failure returns exit code 3 and a
  `committed-report-failed` receipt instead of pretending no commit occurred.

### Repair and release behavior

- Repair changes only the planned `Read.input.pages` member spans and preserves
  every other byte.
- Pending or ambiguous matches fail closed or remain report-only as specified.
- Repair pairs only one later same-session result whose source assistant UUID
  matches, then revalidates the actual published candidate bytes with both the
  repair-specific and shared full-transcript validators.
- Package manifests have no runtime dependency or install-hook fields.
- The real npm tarball contains only the public allowlist, including the skill
  definition and public references, contains no test or generated artifact,
  installs offline, and exposes both commands through the installed `.bin`.

## Fixture Policy

All fixtures must remain anonymous and synthetic. Do not copy real paths,
session IDs, UUIDs, project names, reports, summaries, or transcript text into
this directory.

# Changelog

Notable public changes are recorded here. This project follows Semantic Versioning.

## [Unreleased]

## [1.0.0] - 2026-08-11

### Added

- Simplified Chinese and Japanese documentation for the public project.
- Stable machine-readable `reasonCode` values for resume-path rejection.

### Fixed

- Enumerate Claude project sessions correctly beneath Windows 8.3 short-name roots.
- Bound public diagnostics for malformed JSONL metadata without changing the
  underlying validation or compression decisions.
- Preflight file hard-link capability in the target directory and any explicit
  backup directory before a live session is staged, backed up, or moved.
- Retain and report live-transaction temporary paths whose observed identity or
  bytes change before cleanup, including cleanup residue after an earlier
  transaction failure.

### Changed

- Run the hard-link and transaction suite on Windows, Linux, and macOS CI
  runner volumes and print their filesystem type as diagnostic evidence.
- Promote the public npm package from release candidate to stable `1.0.0` on
  the `latest` dist-tag.

## [1.0.0-rc.1] - 2026-07-28

Initial public release candidate.

### Added

- Source-anchored, model-assisted semantic compression for one Claude Code JSONL session.
- Strict active-chain isolation that excludes rewound and inactive branches.
- Recent raw conversation retention and correlated file-history snapshots for rewind.
- Repeated compression, including explicit prior-summary verbatim preservation.
- Transactional live-session backup, replacement, validation, and recovery handling.
- Independent byte-preserving repair for historical `Read.pages` compatibility failures.
- Scoped npm packaging with two zero-dependency command wrappers.
- Anonymous regression coverage for topology, semantic evidence, transactions, repair, and packaging.

### Release Notes

- Internal engine: `v10`; model-pack schema: `v11`.
- The JSONL rules are based on observed Claude Code behavior, not a stable Anthropic storage API.
- Live replacement handles one closed session at a time and requires Python 3.10 or newer.
- Parent-directory durability is best effort where the platform does not support directory fsync.

[Unreleased]: https://github.com/brandrylabs/claude-jsonl-compressor/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/brandrylabs/claude-jsonl-compressor/releases/tag/v1.0.0
[1.0.0-rc.1]: https://github.com/brandrylabs/claude-jsonl-compressor/releases/tag/v1.0.0-rc.1

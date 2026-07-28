# Changelog

Notable public changes are recorded here. This project follows Semantic Versioning.

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

[1.0.0-rc.1]: https://github.com/brandrylabs/claude-jsonl-compressor/releases/tag/v1.0.0-rc.1

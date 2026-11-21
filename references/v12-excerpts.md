# Retaining literal evidence in v12

Choose passages whose exact wording matters to the next reader. A short decision can refer to a longer acceptance rule, a dated exception or the reason a proposal was rejected. Read the passage in context before choosing its ID. Keep the decision and its current effect in the normal sourced memory. The excerpt supplies exact details the decision depends on.

## Writer selections

The private directory identifies each available passage, its source, inclusive line range, size and a preview. `file` denotes line numbers recorded by the source. `source` refers to the lines of this task's frozen support text. Use the ID from the directory. Select a whole passage or a narrower inclusive range. Place each selection on its own line before the memory completion marker.

```markdown
@keep X0123456789abcd #42-43 | current | Workshop manual v3, inspection after heating
@keep Xabcdef01234567 | superseded | March review, interim rule before manual v3
<!-- end-memory -->
```

Replace the example IDs with directory entries. Describe the document or speaker, version or date where known, and the applicable condition. Use `current` for a confirmed rule in force, `history` for an earlier event or rationale, `superseded` for a rule later replaced, and `unresolved` for an open question or unconfirmed proposal. Select all lines needed to understand a qualification or exception. A later reducer can narrow the selection, revise the label against later evidence, or keep the existing attribution by writing just `@keep ID`. A reducer includes each passage it wants carried forward. Whole document copying is optional even for short files.

## Private API

When consecutive selections share the same source identity, attribution and status, the final memory can show their heading once. Individual literal passages and their displayed ranges remain distinct. A later compression can recover those passages from the conversation even after moving it to another machine.

A Reduce request shows each inherited passage in full with its line numbers. Its input estimate includes those lines. Read the full conditions before keeping a passage or changing its status. New choices drawn from the parent note use an index because the note text is already visible in the same request.

- `catalog_request(sources, limit)` takes a mapping of frozen source IDs to decoded text. The limit counts directory entries. The returned dictionary maps stable passage IDs to private records with literal text, headings, inclusive display ranges, source offsets and SHA-256 bindings. Candidate generation distributes available places across sources and passages. Directory ordering expresses source order.
- `catalog_index(catalog)` formats a compact private lookup. Use `full=True` for a per-line view with the selectable numbers. Count the rendered catalog in the host's request budget. Passages can also be inspected in the original Map evidence or through their private records.
- `parse_selections(markdown, catalog)` returns the remaining Markdown and a JSON-serializable list of choices. Validate the remaining draft through the ordinary v12 memory validator. Initial choices require an attribution and disposition. Overlapping choices within one source are rejected.
- `carry_catalog(selections)` reconstructs the directory for a reducer from accepted parent choices. Preserve the original Map bindings across multiple levels. An accepted intermediate choice can be reused directly from the private receipt.
- `verify_selected(selections, sources)` checks source digests, literal offsets and selected contents against the frozen Map support. Source names must resolve to the same text as in the originating Map. Workflow artifact hashes bind the author-supplied dispositions and attributions.
- `render_selected(selections, limit)` creates the final human-readable excerpt section. This limit counts Unicode characters including headings and fences. Recheck the combined memory and entire candidate through the workflow's structured token ceiling. Exceeding either ceiling calls for an explicit new selection or a shorter draft.

The selection mechanism skips recognizable transport fields, progress receipts, credential forms and opaque encoded payloads. The writer reviews the original support and the rendered selection for sensitive material, conflicting versions and unsupported attributions. Private records contain session data and belong in the private run directory.

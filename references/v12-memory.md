# Writing a v12 memory draft

Use the evidence supplied for this task. Write the knowledge a colleague needs to resume the work. State the current decision, its reason and conditions, the result, and which earlier decision it replaces when those details are known. Preserve exact user wording where it defines permission, and distinguish documents read in full from excerpts, unavailable pages and pending work.

Choose the headings that have content. The accepted English headings are `## Current State`, `## Source Registry`, `## Decisions and Rejected Alternatives`, `## Unresolved`, and `## Handoff Boundary`. Chinese equivalents are 当前状态、来源登记、决策与否决方案、未决事项、交接边界. Japanese equivalents are 現在の状態、資料一覧、決定と却下案、未解決事項、引き継ぎ境界. Single-pass and final merged drafts require a current-state item. Map drafts may use any of the headings.

Within a long module you may group adjacent items under `### Topic name`. Use a short subject name that appears verbatim in an item in that group and in its quoted evidence. A short module can go directly to its items.

Before submitting, use the same evidence window to check the claims that would change a successor's decision. For each, match the speaker, proposal or authorization, condition, and later correction to the original passage. For file research, record which sections or lines the tool actually returned, including gaps or clipped lines. Attribute another participant’s claim of reading a file to that participant. Add a missing fact to the earliest Map that contains its source and carry its effect into Reduce. A requested independent review can focus on these passages.

When a speaker proposes wording for an audience and also describes the underlying situation, retain both clauses with their speaker. Record a later adviser’s alternative and whether the speaker adopted it. When a change was proposed, use the actual edit or readback to say which parts took effect. If reports conflict, preserve their dates and comparison points. One or two sourced sentences usually suffice. You can quote an exact short phrase from any assigned source directly in a claim even when it has no passage ID.

Write each item on one line. End it with the IDs of its evidence in brackets. When the entire item appears verbatim in a source, its citation alone suffices. Otherwise add a support line with a short exact excerpt from that source. Cite the full relevant clause for numbers, units, negation and document-access boundaries. Use separate support lines when sources contribute different details. Every source must be accounted for. IDs are local to the task. Comma-separated lists and inclusive ranges such as `E2-E4` and `E7.1-E7.3` can group repeated evidence. A shared support line requires the excerpt to appear in every source listed.

For a correction, put the earlier estimate, the current value, and the applicable subject together. Keep the original currency, unit, scale, and degree of certainty. Include the date and reason if supplied. Keep an authorization with the person, action, conditions, and exceptions it covers. Quote each supporting clause with enough words to distinguish repeated occurrences. For technical labels, locale-specific numbers, and qualifications, keeping the source wording avoids ambiguity.

A claim can use the language of its source. When an important translation cannot be checked against shared wording, write the complete source-language clause in the item. The local audit records whether the wording was literal or had lexical overlap. A reader must still evaluate the meaning of a translation or paraphrase. Keep credential values out of topics and knowledge items.

```markdown
## Current State
- The trial still has an 8 ms deadline. [E1]
> E1 | the trial deadline remains 8 ms
## Handoff Boundary
- Appendix B remains unread. [E2-E3]
> E2-E3 | Appendix B remains unread.
<!-- end-memory -->
```

For a migration residual, cite its ID on the item that incorporates its fact or already expresses the same knowledge. Add its exact supporting excerpt and mark it `merged` or `duplicate`. Give each residual one disposition. A generic receipt such as “covered” cannot carry a claim. Residuals may supply the only evidence for an item.

```markdown
## 当前状态
- 试点阈值保持为 8 ms。 [E1,P1R1]
> E1 | 试点阈值保持为 8 ms。
> P1R1 duplicate | 保持为 8 ms
<!-- end-memory -->
```

End every draft with the displayed completion line. Write to the assigned output file and check that writing finished. When the generator reports a length stop or a file ends without the marker, retry that task within its output allowance. After multiple Maps, Reduce writes a single new draft from all validated Map items. Preserve corrections and the source of each claim through the Map audits. The final JSONL contains the Markdown headings and knowledge items. Local audit data links the model's supporting excerpts and migration decisions to those items.

## Migration

`resynthesize` presents prior knowledge for one new synthesis. `clean-and-merge` also requires explicit reconciliation of unique quotations and appendix excerpts. Both verify recognized preserved-summary frames by their declared character length, order, exact boundary, and SHA-256 prefix. Unknown material is retained intact as input. `verbatim-locked` additionally carries the original text, including whitespace, into the new summary and can be consulted locally. A broken recognized frame stops the task. The migration audit records classified source spans, exact reassembly, and source and reassembly fingerprints.

Verify checks source membership, support substrings, numeric literals and units, and common negation and unread-boundary changes in the supported clauses. General semantic entailment and the completeness of knowledge recovered from a long source require reading and semantic evaluation.

#!/usr/bin/env python3
"""Synthetic regressions for public semantic, structural, and transaction contracts."""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import _fixtures as fx
from test_repair import RepairBase, add_pages_to_latest_read


ccj = fx.ccj
cst = fx.cst
rcj = fx.rcj


class ProtocolBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cjc_protocol_")
        self.tmp = pathlib.Path(self._tmp.name)
        ccj._SUMMARY_RESOURCES_CONFIGURED = False

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def build_pack(self, records, name="source", handoff_path=None, **overrides):
        source = fx.write_jsonl(self.tmp / f"{name}.jsonl", records)
        options = {
            "target_ratio": 0.20,
            "min_recent_records": 6,
            "summary_char_budget": 12000,
            "model_pack_char_budget": 500000,
        }
        options.update(overrides)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=source,
            handoff_summary_path=handoff_path,
            **options,
        )
        return source, pack

    @staticmethod
    def _support_excerpt(text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return text
        return stripped[:160]

    def model_summary(self, pack, *, include_coverage=True, extra_lines=()):
        required = []
        for group_lines in pack["required_anchor_groups"].values():
            for line in group_lines:
                if line not in required:
                    required.append(line)
        scoped = pack.get("citation_style") == "scoped"
        refs = ", ".join(f"[@L{line}]" if scoped else f"L{line}" for line in required)
        handoff_required = []
        for group_lines in pack.get("required_handoff_anchor_groups", {}).values():
            for line in group_lines:
                if line not in handoff_required:
                    handoff_required.append(line)
        handoff_refs = ", ".join(f"[@H{line}]" if scoped else f"H{line}" for line in handoff_required)
        all_refs = refs + (f", {handoff_refs}" if handoff_refs else "")
        metadata = [
            f"<!-- {ccj.MODEL_SUMMARY_MARKER}",
            f"source_sha256: {pack['source_sha256']}",
            f"summary_source_sha256: {pack['summary_source_sha256']}",
            f"evidence_anchor_lines_digest: {pack['evidence_anchor_lines_digest']}",
            f"required_anchor_groups_digest: {pack['required_anchor_groups_digest']}",
            f"handoff_summary_digest: {pack.get('handoff_summary_sha256_prefix') or 'none'}",
        ]
        if pack.get("pack_request_digest"):
            metadata.append(f"pack_request_digest: {pack['pack_request_digest']}")
        if pack.get("required_claim_sources_digest"):
            metadata.append(f"required_claim_sources_digest: {pack['required_claim_sources_digest']}")
        metadata.append("-->")
        headings = [
            "Current State",
            "Timeline and Supersessions",
            "Decisions and Reasons",
            "Assistant Research Decisions and Rationales",
            "Rejected or Superseded Alternatives",
            "Evidence and Source Anchors",
            "User Wording and Constraints",
            "Risks, Unknowns, and Follow-Ups",
            "Recent Raw Context Boundary",
        ]
        body = metadata + ["# Model-Assisted Semantic Compression Summary"]
        for index, heading in enumerate(headings):
            body.extend([
                "",
                f"## {heading}",
                f"Synthetic section {index} uses only displayed evidence and preserves chronology. {all_refs}",
            ])
            if heading == "Current State":
                body.extend(extra_lines)
            if heading == "Evidence and Source Anchors" and include_coverage:
                body.extend(["", "### Mandatory Evidence Coverage"])
                for raw_line, source_text in sorted((pack.get("required_claim_sources") or {}).items(), key=lambda item: int(item[0])):
                    line = int(raw_line)
                    excerpt = self._support_excerpt(str(source_text))
                    body.append(
                        f"- L{line} support_text_json={json.dumps(excerpt, ensure_ascii=False)} disposition=covered"
                    )
        return "\n".join(body) + "\n"

    def validate_summary(self, pack, text, total_records):
        kwargs = {
            "citation_style": pack.get("citation_style", "legacy"),
            "text": text,
            "source_digest": pack["source_sha256"],
            "omitted_digest": pack["summary_source_sha256"],
            "total_records": total_records,
            "omitted_indexes": [line - 1 for line in pack["summary_source_lines"]],
            "allowed_anchor_lines": pack["evidence_anchor_lines"],
            "expected_evidence_anchor_lines_digest": pack["evidence_anchor_lines_digest"],
            "required_anchor_groups": pack["required_anchor_groups"],
            "expected_required_anchor_groups_digest": pack["required_anchor_groups_digest"],
            "expected_handoff_summary_digest": pack.get("handoff_summary_sha256_prefix"),
            "allowed_handoff_anchor_count": max(ccj.model_pack_handoff_anchor_lines(pack["text"]), default=0),
        }
        parameters = inspect.signature(ccj.validate_model_summary_text).parameters
        if "expected_pack_request_digest" in parameters:
            kwargs["expected_pack_request_digest"] = pack.get("pack_request_digest")
        if "required_claim_sources" in parameters:
            kwargs["required_claim_sources"] = pack.get("required_claim_sources") or {}
            kwargs["expected_required_claim_sources_digest"] = pack.get("required_claim_sources_digest")
        return ccj.validate_model_summary_text(**kwargs)


class TestSemanticProtocolContracts(ProtocolBase):
    def test_mixed_reminders_protect_the_complete_human_turn(self):
        before = "<system-reminder>Before note.</system-reminder>"
        after = "<system-reminder>After note.</system-reminder>"
        request = "My actual request: retain this review turn."
        for as_blocks in (False, True):
            with self.subTest(as_blocks=as_blocks):
                tb = fx.build_linear("dddddddd-1111-4111-8111-dddddddddddd", turns=30)
                tb.records.pop()
                tb.compact_pair("Previous phase ended.")
                uid = tb.user("\n".join((before, request, after)))
                human = tb.records[-1]
                if as_blocks:
                    human["message"]["content"] = [{"type": "text", "text": text} for text in (before, request, after)]
                for _ in range(12):
                    tb.tool_call_pair()
                tb.assistant_text("Completed current work.")
                tb.last_prompt()
                source = fx.write_jsonl(self.tmp / f"mixed-{as_blocks}.jsonl", tb.records)
                options = dict(target_ratio=.05, min_recent_records=2, summary_char_budget=12000, min_recent_turns=1)
                pre = ccj.preflight_jsonl(source, **options)
                self.assertTrue(pre["ok"], pre)
                self.assertEqual(pre["partition"]["availableRecentTurns"], 1)
                self.assertEqual(pre["partition"]["rawHumanMessages"], 1)
                pack = ccj.build_model_summary_pack_for_input(source, **options)
                line = next(i + 1 for i, r in enumerate(tb.records) if r.get("uuid") == uid)
                self.assertNotIn(line, pack["summary_source_lines"])
                output = self.tmp / f"mixed-output-{as_blocks}.jsonl"
                ccj.compress_jsonl(source, output, deterministic_summary=True, **options)
                kept_user = next(r for r in fx.read_jsonl(output) if r.get("uuid") == uid)
                self.assertEqual(kept_user["message"], human["message"])
        for text in (before, before + "\n\n" + after):
            obj = {"type": "user", "message": {"role": "user", "content": text}}
            self.assertEqual(ccj.user_record_origin(obj), "injected")

    def test_title_locator_derives_session_from_the_authoritative_chain(self):
        for missing_leaf_session in (False, True):
            with self.subTest(missing_leaf_session=missing_leaf_session):
                folder = self.tmp / f"title-{missing_leaf_session}"
                folder.mkdir()
                a = fx.build_linear("eeeeeeee-1111-4111-8111-eeeeeeeeeeee", turns=30)
                pointer = a.records.pop()
                pointer.pop("sessionId")
                if missing_leaf_session:
                    a.records[-1].pop("sessionId")
                b = fx.build_linear("ffffffff-2222-4222-8222-ffffffffffff", turns=1)
                a.records.extend(b.records[:-1])
                a.records.append({"type": "custom-title", "customTitle": "Final review name", "sessionId": a.session_id})
                a.records.append(pointer)
                source = fx.write_jsonl(folder / "source.jsonl", a.records)
                self.assertTrue(ccj.choose_resume_leaf_info(a.records)["ok"])
                self.assertEqual(cst.extract_hint(source), "Final review name")
                self.assertEqual(cst.find_unique_session(folder, "Final review name", scan_titles=True), source)
                output = folder / "candidate.jsonl"
                report = ccj.compress_jsonl(source, output, .05, 4, 12000, deterministic_summary=True)
                self.assertTrue(report["validation"]["ok"])
                self.assertEqual(cst.extract_hint(output), "Final review name")

    def test_title_locator_does_not_guess_from_a_broken_pointer_chain(self):
        titles = [{"type": "custom-title", "customTitle": sid, "sessionId": sid} for sid in ("session-a", "session-b")]
        for nodes in (
            [],
            [{"uuid": "leaf", "parentUuid": None, "sessionId": sid} for sid in ("session-a", "session-b")],
            [{"uuid": "leaf", "parentUuid": "loop", "sessionId": "session-a"}, {"uuid": "loop", "parentUuid": "leaf"}],
            [{"uuid": "leaf", "parentUuid": "missing", "sessionId": "session-a"}],
        ):
            with self.subTest(nodes=nodes):
                records = nodes + titles + [{"type": "last-prompt", "leafUuid": "leaf"}]
                self.assertIsNone(cst.select_session_title(records)["record"])

    def test_prior_summary_spans_point_to_the_embedded_body(self):
        tb = fx.TranscriptBuilder("abababab-4444-4444-8444-abababababab")
        tb.compact_pair("Prior")
        text, info = ccj.apply_prior_summary_verbatim_policy(
            "New layer.", tb.records, list(range(len(tb.records))), 12000, True, "error")
        span = info["preservedSpans"][0]
        self.assertEqual(text[span["start"]:span["end"]], "Prior")
        self.assertGreater(span["start"], text.index("## Prior Compact Summary 1"))
        self.assertTrue(text[span["end"]:].startswith("\n\n# Current Compression Layer"))

    def test_strict_old_summary_capacity_stops_before_pack_write(self):
        tb = fx.TranscriptBuilder("08080808-8888-4888-8888-080808080808")
        tb.compact_pair("Earlier legal interpretation. " * 800)
        for index in range(20):
            tb.user(f"New phase {index}")
            tb.assistant_text("Current decision.")
        tb.last_prompt()
        source = fx.write_jsonl(self.tmp / "prior.jsonl", tb.records)
        result = ccj.preflight_jsonl(source, .05, 4, 4000, preserve_prior_summaries_verbatim=True, prior_summary_overflow="error")
        self.assertEqual(result["state"], "pack-unavailable")
        self.assertIn("strict preservation", result["error"])
        self.assertEqual(list(self.tmp.iterdir()), [source])

    def test_turn_protection_stays_after_compact_and_current_session(self):
        tb = fx.build_linear("09090909-9999-4999-8999-090909090909", turns=20)
        tb.records.pop()
        tb.compact_pair("Historic context.")
        for index in range(3):
            tb.user(f"Current turn {index}")
            tb.tool_call_pair()
            tb.assistant_text("Current reply.")
        tb.last_prompt()
        source = fx.write_jsonl(self.tmp / "compact-turn.jsonl", tb.records)
        result = ccj.preflight_jsonl(source, .05, 2, 12000, min_recent_turns=50)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["partition"]["availableRecentTurns"], 3)
        self.assertEqual(result["partition"]["rawHumanMessages"], 3)
        # All available post-compact turns remain raw; the prior compact is summarized.
        pack = ccj.build_model_summary_pack_for_input(source, .05, 2, 12000, min_recent_turns=50)
        self.assertEqual(pack["prior_summary_count"], 1)

    def test_exact_locator_wins_over_title_and_invalid_title_does_not_replace_name(self):
        a = fx.build_linear("abababab-1111-4111-8111-abababababab", turns=3)
        a.records.extend([
            {"type": "custom-title", "customTitle": "Final", "sessionId": a.session_id},
            {"type": "custom-title", "customTitle": []},
            {"type": "custom-title", "customTitle": "Wrong leaf", "uuid": "bad-control", "sessionId": a.session_id},
        ])
        source = fx.write_jsonl(self.tmp / "exact.jsonl", a.records)
        b = fx.build_linear("bcbcbcbc-2222-4222-8222-bcbcbcbcbcbc", turns=3)
        b.custom_title("exact.jsonl")
        fx.write_jsonl(self.tmp / "other.jsonl", b.records)
        self.assertEqual(cst.extract_hint(source), "Final")
        self.assertEqual(cst.find_unique_session(self.tmp, "exact.jsonl", scan_titles=True), source)

    def test_three_rounds_keep_exact_prior_text_and_current_title(self):
        tb = fx.build_linear("cdcdcdcd-3333-4333-8333-cdcdcdcdcdcd", turns=24)
        tb.records.pop()
        original = "旧裁断：不准扩大目录。Later: limited to review only.  \r\n\r\n\r\n"
        tb.compact_pair(original)
        for index in range(12):
            tb.user(f"New review phase {index}")
            tb.assistant_text("Retain history; current deadline remains unknown.")
        tb.last_prompt()
        for round_index in range(3):
            tb.records.append({"type": "custom-title", "customTitle": f"Review {round_index}", "sessionId": tb.session_id})
            source = fx.write_jsonl(self.tmp / f"round-{round_index}.jsonl", tb.records)
            opts = dict(target_ratio=.05, min_recent_records=4, summary_char_budget=200000,
                        preserve_prior_summaries_verbatim=True, prior_summary_overflow="error", citation_style="scoped")
            pack = ccj.build_model_summary_pack_for_input(source, **opts)
            model = self.tmp / f"round-{round_index}.md"
            model.write_text(self.model_summary(pack), encoding="utf-8")
            output = self.tmp / f"output-{round_index}.jsonl"
            report = ccj.compress_jsonl(source, output, model_summary_path=model, **opts)
            self.assertTrue(report["validation"]["ok"])
            records = fx.read_jsonl(output)
            summaries = [r for r in records if r.get("isCompactSummary") is True]
            self.assertEqual(len(summaries), 1)
            text = ccj.compact_summary_message_content(summaries[0])
            self.assertIn(original, text)
            original = text
            self.assertEqual(cst.extract_hint(output), f"Review {round_index}")
            pointer = records.pop()
            tb.records = records
            tb.prev_uuid = pointer["leafUuid"]
            for index in range(8):
                tb.user(f"Round {round_index} next request {index}")
                tb.assistant_text("Only the final review directory is authorized.")
            tb.last_prompt()

    def test_scoped_citations_keep_source_identifiers_and_historical_unknowns(self):
        tb = fx.build_linear("01010101-1111-4111-8111-010101010101", turns=40)
        user = next(r for r in tb.records if r.get("type") == "user")
        user["message"]["content"] = "The source labels are H1 and L999999. The information was not available in that historical phase."
        _, pack = self.build_pack(tb.records, citation_style="scoped")
        line = next(k for k, v in pack["required_claim_sources"].items() if v == user["message"]["content"])
        text = self.model_summary(pack, extra_lines=(user["message"]["content"] + f" [@L{line}]",))
        self.assertTrue(self.validate_summary(pack, text, len(tb.records))["ok"])
        self.assertFalse(self.validate_summary(pack, text + "Unsupported claim [@L999999]\n", len(tb.records))["ok"])

    def test_full_result_deduplicates_exact_strings_and_keeps_distinct_preview(self):
        body = "完整结果：不可改写。" * 200 + " FINAL_关键条件\ufffd"
        record = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call", "content": body, "is_error": True}]},
            "toolUseResult": {"stdout": body, "stderr": "short distinct preview"}}
        item = ccj.model_evidence_record(record, 2, tool_evidence="full")
        self.assertTrue(item["mandatorySemantic"])
        self.assertEqual(item["claimSource"].count("FINAL_关键条件"), 1)
        self.assertIn("exact_string_alias_of=", item["claimSource"])
        self.assertIn("short distinct preview", item["claimSource"])
        self.assertIn('is_error', item["claimSource"])
        self.assertTrue(item["sourceTextWarning"])

    def test_full_pack_overflow_is_read_only_and_does_not_sample_payload(self):
        tb = fx.build_linear("02020202-2222-4222-8222-020202020202", turns=40, with_tools_every=3)
        block = next(b for r in tb.records for b in ccj.content_blocks(r) if isinstance(b, dict) and b.get("type") == "tool_use")
        block["input"]["content"] = "密集文档" * 70000
        source = fx.write_jsonl(self.tmp / "large.jsonl", tb.records)
        before = source.read_bytes()
        result = ccj.preflight_jsonl(source, .05, 4, 12000, tool_evidence="full")
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "pack-unavailable")
        self.assertFalse(result["pack"]["fits"])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(list(self.tmp.iterdir()), [source])

    def test_preflight_distinguishes_pending_pointer_from_closed_descendant(self):
        tb = fx.TranscriptBuilder("03030303-3333-4333-8333-030303030303")
        tb.user("Read evidence.")
        tb.tool_call_pair()
        pending = tb.records[-2]["uuid"]
        tb.last_prompt(pending)
        tb.assistant_text("Research complete.")
        tb.records[-1]["message"]["stop_reason"] = "end_turn"
        source = fx.write_jsonl(self.tmp / "pending.jsonl", tb.records)
        result = ccj.preflight_jsonl(source)
        self.assertTrue(result["topology"]["ok"])
        self.assertFalse(result["activeChain"]["ok"])
        self.assertTrue(result["physicalTailCandidate"]["isSelectedChainPrefix"])
        self.assertTrue(result["physicalTailCandidate"]["chainValidation"]["ok"])
        self.assertFalse(result["physicalTailCandidate"]["selected"])

    def test_preflight_no_old_segment_keeps_diagnostics(self):
        source = fx.write_jsonl(self.tmp / "tiny.jsonl", fx.build_linear("04040404-4444-4444-8444-040404040404", turns=2).records)
        result = ccj.preflight_jsonl(source, min_recent_records=120)
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "nothing-to-summarize")
        self.assertEqual(result["partition"]["oldRecords"], 0)

    def test_recent_turns_protect_complete_turn_and_do_not_count_injections(self):
        tb = fx.build_linear("05050505-5555-4555-8555-050505050505", turns=40)
        tb.records.pop()
        protected = tb.user("Final review request.")
        for _ in range(8):
            tb.tool_call_pair()
        tb.user("<system-reminder>Display note.</system-reminder>")
        tb.assistant_text("Ready.")
        tb.last_prompt()
        source = fx.write_jsonl(self.tmp / "turns.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(source, .05, 2, 12000, min_recent_turns=1)
        line = next(i + 1 for i, r in enumerate(tb.records) if r.get("uuid") == protected)
        self.assertNotIn(line, pack["summary_source_lines"])
        self.assertGreater(pack["recent_record_count"], 16)
        with self.assertRaisesRegex(ValueError, "strict active-chain"):
            ccj.build_model_summary_pack_for_input(source, .05, 2, 12000, min_recent_turns=1, preserve_active_chain=False)

    def test_title_selection_uses_final_session_and_preserves_unknown_fields(self):
        tb = fx.build_linear("06060606-6666-4666-8666-060606060606", turns=40)
        tb.records.insert(0, {"type": "custom-title", "customTitle": "Wrong old session", "sessionId": "old"})
        tb.records.append({"type": "ai-title", "aiTitle": "Current automatic", "sessionId": tb.session_id, "x": 42})
        tb.records.append({"type": "custom-title", "customTitle": "Ambiguous unowned"})
        source = fx.write_jsonl(self.tmp / "fork.jsonl", tb.records)
        self.assertEqual(cst.extract_hint(source), "Current automatic")
        output = self.tmp / "fork-out.jsonl"
        report = ccj.compress_jsonl(source, output, .05, 4, 12000, target_session_id="new-target", deterministic_summary=True)
        title = cst.select_session_title(fx.read_jsonl(output), "new-target")["record"]
        self.assertEqual(title, {"type": "ai-title", "aiTitle": "Current automatic", "sessionId": "new-target", "x": 42})
        self.assertEqual(report["session_title"]["ambiguous_count"], 2)

    def test_new_options_are_bound_across_both_passes(self):
        tb = fx.build_linear("07070707-7777-4777-8777-070707070707", turns=40, with_tools_every=5)
        source, pack = self.build_pack(tb.records, tool_evidence="full", citation_style="scoped", min_recent_turns=1, summary_char_budget=30000)
        model = self.tmp / "model.md"
        model.write_text(self.model_summary(pack), encoding="utf-8")
        output = self.tmp / "candidate.jsonl"
        settings = dict(target_ratio=.2, min_recent_records=6, summary_char_budget=30000,
                        model_summary_path=model, tool_evidence="full", citation_style="scoped", min_recent_turns=1)
        good = ccj.compress_jsonl(source, output, **settings)
        self.assertTrue(good["validation"]["ok"])
        original = output.read_bytes()
        for key, value in (("tool_evidence", "excerpt"), ("citation_style", "legacy"), ("min_recent_turns", 0)):
            with self.assertRaisesRegex(ValueError, "model summary validation"):
                ccj.compress_jsonl(source, output, **dict(settings, **{key: value}))
            self.assertEqual(output.read_bytes(), original)

    def test_complete_tool_payload_and_injected_provenance(self):
        record = {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Read the evidence."},
            {"type": "tool_use", "id": "call", "name": "Bash", "input": {
                "command": "x" * 4000 + " FINAL_CONDITION_保持历史否定"}}]}}
        evidence = ccj.model_evidence_record(record, 1, tool_evidence="full")
        self.assertIn("FINAL_CONDITION_保持历史否定", evidence["claimSource"])
        self.assertTrue(evidence["mandatorySemantic"])
        injected = {"type": "user", "isMeta": True, "message": {"role": "user", "content":
            "<system-reminder>Do not edit outside the review directory.</system-reminder>"}}
        self.assertFalse(ccj.is_human_user_record(injected))
        item = ccj.model_evidence_record(injected, 2)
        self.assertTrue(item["mandatorySemantic"])
        self.assertIn("injected", item["classes"])

    def test_latest_native_title_is_shared_with_output(self):
        tb = fx.build_linear("11111111-2222-4333-8444-555555555555", turns=64)
        tb.records.extend([
            {"type": "custom-title", "sessionId": tb.session_id, "customTitle": "Old name"},
            {"type": "custom-title", "sessionId": tb.session_id, "customTitle": "Final name", "extra": "kept"},
        ])
        source = fx.write_jsonl(self.tmp / "named.jsonl", tb.records)
        self.assertEqual(cst.extract_hint(source), "Final name")
        output = self.tmp / "result.jsonl"
        report = ccj.compress_jsonl(source, output, .2, 6, 12000, deterministic_summary=True)
        self.assertTrue(report["validation"]["ok"])
        titles = [r for r in fx.read_jsonl(output) if r.get("type") == "custom-title"]
        self.assertEqual(titles, [tb.records[-1]])

    def test_verbatim_keeps_trailing_whitespace_and_strict_overflow_stops(self):
        old = "Earlier research result.  \r\n\r\n\r\n"
        record = {"type": "user", "isCompactSummary": True, "message": {"role": "user", "content": old}}
        output, policy = ccj.apply_prior_summary_verbatim_policy("New layer.", [record], [0], 4000, True)
        self.assertEqual(policy["mode"], "verbatim-preserved")
        self.assertIn(old, output)
        record["message"]["content"] = old * 1000
        with self.assertRaisesRegex(ValueError, "verbatim"):
            ccj.apply_prior_summary_verbatim_policy("New layer.", [record], [0], 4000, True, overflow="error")

    def test_content_free_anchor_dump_does_not_satisfy_fact_coverage(self):
        tb = fx.build_linear("11111111-aaaa-4111-8111-111111111111", turns=64)
        _source, pack = self.build_pack(tb.records, "content-free")
        summary = self.model_summary(pack, include_coverage=False)
        result = self.validate_summary(pack, summary, len(tb.records))
        self.assertFalse(result["ok"], "generic anchor-only prose was accepted as semantic fact coverage")

    def test_secondary_html_comment_cannot_bypass_grounding(self):
        tb = fx.build_linear("22222222-bbbb-4222-8222-222222222222", turns=64)
        _source, pack = self.build_pack(tb.records, "comment-bypass")
        summary = self.model_summary(pack, extra_lines=("<!-- UNANCHORED_SYNTHETIC_CLAIM -->",))
        result = self.validate_summary(pack, summary, len(tb.records))
        self.assertFalse(result["ok"], "a second HTML comment bypassed substantive-line grounding")

    def test_html_comment_literal_inside_support_json_is_source_evidence(self):
        tb = fx.build_linear("23232323-bcbc-4232-8232-232323232323", turns=64)
        literal = "Keep the exact source literal <!-- SYNTHETIC_SOURCE_MARKER --> in the historical record."
        first_user = next(record for record in tb.records if record.get("type") == "user")
        first_user["message"]["content"] = literal
        _source, pack = self.build_pack(tb.records, "comment-source-literal")
        summary = self.model_summary(pack)
        self.assertIn(json.dumps(literal, ensure_ascii=False), summary)
        result = self.validate_summary(pack, summary, len(tb.records))
        self.assertTrue(result["ok"], result["errors"])

    def test_extra_unanchored_heading_cannot_bypass_grounding(self):
        tb = fx.build_linear("33333333-cccc-4333-8333-333333333333", turns=64)
        _source, pack = self.build_pack(tb.records, "heading-bypass")
        summary = self.model_summary(pack, extra_lines=("### Unanchored synthetic conclusion",))
        result = self.validate_summary(pack, summary, len(tb.records))
        self.assertFalse(result["ok"], "an arbitrary Markdown heading bypassed grounding")

    def test_mixed_tool_result_user_text_is_mandatory_semantic_evidence(self):
        tb = fx.TranscriptBuilder("44444444-dddd-4444-8444-444444444444")
        tb.user("setup")
        marker = "MIXED_HUMAN_CONSTRAINT must remain complete despite a neighboring tool result."
        assistant_uuid = tb.assistant_text("placeholder")
        tb.records[-1]["message"]["content"] = [
            {
                "type": "tool_use",
                "id": "toolu_synthetic",
                "name": "Read",
                "input": {"file_path": "C:\\synthetic\\source.txt"},
            }
        ]
        mixed_uuid = tb.user("placeholder")
        tb.records[-1]["message"]["content"] = [
            {"type": "tool_result", "tool_use_id": "toolu_synthetic", "content": "transport"},
            {"type": "text", "text": marker},
        ]
        tb.records[-1]["sourceToolAssistantUUID"] = assistant_uuid
        for index in range(48):
            tb.user(f"recent user {index}")
            tb.assistant_text(f"recent assistant {index}")
        tb.last_prompt()
        _source, pack = self.build_pack(tb.records, "mixed-human")
        source_line = next(index + 1 for index, record in enumerate(tb.records) if record.get("uuid") == mixed_uuid)
        self.assertIn(source_line, pack["summary_source_lines"])
        self.assertIn(marker, pack["text"])
        self.assertTrue(
            any(
                name.startswith("semantic-human-user-") and list(lines) == [source_line]
                for name, lines in pack["required_anchor_groups"].items()
            ),
            "mixed human text had no individual mandatory coverage group",
        )

    def test_replacement_character_does_not_drop_human_or_assistant_semantics(self):
        tb = fx.TranscriptBuilder("55555555-eeee-4555-8555-555555555555")
        expected = []
        human = "HUMAN_REPLACEMENT \ufffd preserve the remaining critical constraint."
        tb.user(human)
        expected.append((len(tb.records), human))
        assistant = "ASSISTANT_REPLACEMENT \ufffd final decision because evidence changed."
        tb.assistant_text(assistant)
        expected.append((len(tb.records), assistant))
        for index in range(48):
            tb.user(f"tail user {index}")
            tb.assistant_text(f"tail assistant {index}")
        tb.last_prompt()
        _source, pack = self.build_pack(tb.records, "replacement-char")
        for line, text in expected:
            self.assertIn(line, pack["summary_source_lines"])
            self.assertIn(text, pack["text"])
            self.assertTrue(any(list(lines) == [line] for lines in pack["required_anchor_groups"].values()))

    def test_replacement_character_does_not_drop_prior_compact_summary(self):
        tb = fx.TranscriptBuilder("66666666-ffff-4666-8666-666666666666")
        marker = "PRIOR_REPLACEMENT \ufffd keep this historical reason."
        tb.compact_pair(marker, codex=True)
        for index in range(48):
            tb.user(f"new user {index}")
            tb.assistant_text(f"new assistant {index}")
        tb.last_prompt()
        _source, pack = self.build_pack(tb.records, "prior-replacement")
        self.assertEqual(pack["prior_summary_count"], 1)
        self.assertIn(marker, pack["text"])

    def test_handoff_decode_is_strict_and_physical_lines_are_lossless(self):
        tb = fx.build_linear("77777777-aaaa-4777-8777-777777777777", turns=48)
        invalid = self.tmp / "invalid-handoff.md"
        invalid.write_bytes(b"alpha\xffbeta")
        with self.assertRaises(UnicodeDecodeError):
            self.build_pack(tb.records, "invalid-handoff", handoff_path=invalid)

        handoff = self.tmp / "line-handoff.md"
        handoff.write_bytes(b"alpha\r\n\r\nbeta\n  \nend")
        _source, pack = self.build_pack(tb.records, "line-handoff", handoff_path=handoff)
        anchors = ccj.model_pack_handoff_anchor_lines(pack["text"])
        self.assertEqual(anchors, [1, 2, 3, 4, 5])
        for encoded in ('full_text_json="alpha\\r\\n"', 'full_text_json="\\r\\n"', 'full_text_json="  \\n"'):
            self.assertIn(encoded, pack["text"])

    def test_pass_two_rejects_a_different_checkpoint_policy(self):
        tb = fx.build_linear("88888888-bbbb-4888-8888-888888888888", turns=72)
        pointer = tb.records.pop()
        tb.file_history_snapshot("synthetic.txt", source_uuid=tb.prev_uuid)
        tb.add_raw(pointer)
        source, pack = self.build_pack(tb.records, "option-bind", checkpoint_policy="active-correlated")
        summary_path = self.tmp / "option-bind.summary.md"
        summary_path.write_text(self.model_summary(pack), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "request|option|digest|settings"):
            ccj.compress_jsonl(
                input_path=source,
                output_path=self.tmp / "option-bind.out.jsonl",
                target_ratio=0.20,
                min_recent_records=6,
                summary_char_budget=12000,
                preserve_active_chain=True,
                checkpoint_policy="none",
                model_summary_path=summary_path,
                model_pack_char_budget=500000,
            )

    def test_zero_priority_optional_evidence_is_reported_as_truncated(self):
        tb = fx.TranscriptBuilder("99999999-cccc-4999-8999-999999999999")
        tb.user("old semantic instruction")
        tb.add_raw(tb._base("system", uuid="optional-zero", subtype="progress", content="ordinary progress"))
        for index in range(48):
            tb.user(f"tail user {index}")
            tb.assistant_text(f"tail assistant {index}")
        tb.last_prompt()
        _source, pack = self.build_pack(tb.records, "optional-omission")
        self.assertTrue(pack["evidence_truncated"])
        self.assertGreater(pack.get("optional_evidence_omitted_count", 0), 0)


class TestStructuralProtocolContracts(ProtocolBase):
    def test_malformed_old_tool_pair_blocks_pack_and_candidate_before_writes(self):
        tb = fx.TranscriptBuilder("aaaaaaaa-dddd-4aaa-8aaa-aaaaaaaaaaaa")
        tb.user("old read")
        tb.tool_call_pair()
        tb.records[-1]["message"]["content"][0]["tool_use_id"] = "toolu_wrong"
        for index in range(72):
            tb.user(f"tail user {index}")
            tb.assistant_text(f"tail assistant {index}")
        tb.last_prompt()
        source = fx.write_jsonl(self.tmp / "bad-tool-source.jsonl", tb.records)
        pack_path = self.tmp / "bad-tool.pack.md"
        output = self.tmp / "bad-tool.out.jsonl"
        with self.assertRaisesRegex(ValueError, "source|tool"):
            ccj.build_model_summary_pack_for_input(
                input_path=source,
                target_ratio=0.20,
                min_recent_records=6,
                summary_char_budget=12000,
            )
        self.assertFalse(pack_path.exists())
        with self.assertRaisesRegex(ValueError, "source|tool"):
            ccj.compress_jsonl(
                input_path=source,
                output_path=output,
                target_ratio=0.20,
                min_recent_records=6,
                summary_char_budget=12000,
                deterministic_summary=True,
            )
        self.assertFalse(output.exists())

    def test_malformed_old_compact_metadata_blocks_pack(self):
        tb = fx.TranscriptBuilder("bbbbbbbb-eeee-4bbb-8bbb-bbbbbbbbbbbb")
        tb.compact_pair("prior synthetic summary", codex=True)
        boundary = next(record for record in tb.records if record.get("subtype") == "compact_boundary")
        boundary["compactMetadata"]["preserved"] = {"uuids": "not-an-array"}
        for index in range(48):
            tb.user(f"tail user {index}")
            tb.assistant_text(f"tail assistant {index}")
        tb.last_prompt()
        source = fx.write_jsonl(self.tmp / "bad-compact-source.jsonl", tb.records)
        with self.assertRaisesRegex(ValueError, "source|compact"):
            ccj.build_model_summary_pack_for_input(
                input_path=source,
                target_ratio=0.20,
                min_recent_records=6,
                summary_char_budget=12000,
            )

    def test_historical_compact_snapshot_may_diverge_after_rewind(self):
        session_id = "bcbcbcbc-eeee-4bcb-8bcb-bcbcbcbcbcbc"
        source = fx.write_jsonl(
            self.tmp / "historical-prefix-source.jsonl",
            fx.build_linear(session_id, turns=72).records,
        )
        candidate = self.tmp / "historical-prefix-candidate.jsonl"
        ccj.compress_jsonl(
            input_path=source,
            output_path=candidate,
            target_ratio=0.20,
            min_recent_records=8,
            summary_char_budget=12000,
            deterministic_summary=True,
        )
        records = fx.read_jsonl(candidate)
        pointer = records.pop()
        boundary = next(record for record in records if record.get("subtype") == "compact_boundary")
        preserved = boundary["compactMetadata"]["preservedMessages"]["uuids"]
        builder = fx.TranscriptBuilder(session_id)
        builder.records = records
        builder.prev_uuid = preserved[-2]
        for index in range(6):
            builder.user(f"later user {index}")
            builder.assistant_text(f"later assistant {index}")
        builder.last_prompt()

        validation = ccj.validate_records(builder.records)
        self.assertTrue(validation["ok"], validation["errors"])
        self.assertGreater(validation["compact_metadata_chain_mismatch_count"], 0)
        self.assertTrue(any("historical" in warning.lower() for warning in validation["warnings"]))

        evolved = fx.write_jsonl(self.tmp / "historical-prefix-evolved.jsonl", builder.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=evolved,
            target_ratio=0.20,
            min_recent_records=8,
            summary_char_budget=12000,
        )
        self.assertTrue(any("historical" in warning.lower() for warning in pack["source_active_chain_validation_warnings"]))

        strict_output = self.tmp / "historical-prefix-strict-output.jsonl"
        with self.assertRaisesRegex(ValueError, "compactMetadata snapshot"):
            ccj.publish_validated_jsonl(strict_output, builder.records)
        self.assertFalse(strict_output.exists())
        self.assertNotEqual(pointer["leafUuid"], builder.records[-1]["leafUuid"])

    def test_duplicate_tool_use_ids_are_validation_errors(self):
        tb = fx.TranscriptBuilder("cccccccc-ffff-4ccc-8ccc-cccccccccccc")
        tb.user("run two tools")
        assistant_uuid = tb.assistant_text("placeholder")
        duplicate = "toolu_duplicate"
        tb.records[-1]["message"]["content"] = [
            {"type": "tool_use", "id": duplicate, "name": "Read", "input": {"file_path": "C:\\synthetic\\a"}},
            {"type": "tool_use", "id": duplicate, "name": "Read", "input": {"file_path": "C:\\synthetic\\b"}},
        ]
        result_uuid = tb.user("placeholder")
        tb.records[-1]["sourceToolAssistantUUID"] = assistant_uuid
        tb.records[-1]["message"]["content"] = [
            {"type": "tool_result", "tool_use_id": duplicate, "content": "ok"},
        ]
        tb.last_prompt(result_uuid)
        validation = ccj.validate_records(tb.records)
        self.assertFalse(validation["ok"])
        self.assertGreater(validation["tool_pair_error_count"], 0)

    def test_partial_multi_tool_results_are_explicit_compatibility_warnings(self):
        tb = fx.TranscriptBuilder("dddddddd-aaaa-4ddd-8ddd-dddddddddddd")
        for index in range(12):
            tb.user(f"historical user {index}")
            tb.assistant_text(f"historical assistant {index}")
        tb.user("run two tools")
        assistant_uuid = tb.assistant_text("placeholder")
        tb.records[-1]["message"]["content"] = [
            {"type": "tool_use", "id": "toolu_one", "name": "Read", "input": {"file_path": "C:\\synthetic\\a"}},
            {"type": "tool_use", "id": "toolu_two", "name": "Read", "input": {"file_path": "C:\\synthetic\\b"}},
        ]
        result_uuid = tb.user("placeholder")
        tb.records[-1]["sourceToolAssistantUUID"] = assistant_uuid
        tb.records[-1]["message"]["content"] = [
            {"type": "tool_result", "tool_use_id": "toolu_one", "content": "ok"},
        ]
        tb.last_prompt(result_uuid)
        validation = ccj.validate_records(tb.records)
        self.assertTrue(validation["ok"], validation["errors"])
        self.assertEqual(validation["tool_pair_partial_result_count"], 1)
        self.assertTrue(
            any("partial" in warning.lower() for warning in validation["warnings"]),
            "partial multi-tool compatibility was accepted without an explicit warning",
        )
        _source, pack = self.build_pack(
            tb.records,
            "partial-multi-tool",
            target_ratio=0.20,
            min_recent_records=1,
        )
        self.assertEqual(pack["source_active_chain_tool_pair_partial_result_count"], 1)
        self.assertTrue(
            any("partial" in warning.lower() for warning in pack["source_active_chain_validation_warnings"]),
            "model-pack diagnostics hid the accepted source partial-tool compatibility",
        )

    def test_recent_cut_keeps_all_assistant_fragments_with_same_message_id(self):
        tb = fx.TranscriptBuilder("eeeeeeee-bbbb-4eee-8eee-eeeeeeeeeeee")
        tb.user("fragmented assistant")
        first_uuid = tb.assistant_text("first fragment")
        second_uuid = tb.assistant_text("second fragment")
        tb.records[-2]["message"]["id"] = "msg_shared"
        tb.records[-1]["message"]["id"] = "msg_shared"
        tb.records[-1]["message"]["content"].append(
            {"type": "tool_use", "id": "toolu_fragment", "name": "Read", "input": {"file_path": "C:\\synthetic\\a"}}
        )
        result_uuid = tb.user("placeholder")
        tb.records[-1]["sourceToolAssistantUUID"] = second_uuid
        tb.records[-1]["message"]["content"] = [
            {"type": "tool_result", "tool_use_id": "toolu_fragment", "content": "ok"},
        ]
        start = next(index for index, record in enumerate(tb.records) if record.get("uuid") == second_uuid)
        first = next(index for index, record in enumerate(tb.records) if record.get("uuid") == first_uuid)
        self.assertEqual(ccj.adjust_recent_start_for_tool_pairs(tb.records, start), first)
        self.assertNotEqual(result_uuid, first_uuid)

    def test_session_locator_requires_exact_filename_or_stem(self):
        root = self.tmp / "sessions"
        root.mkdir()
        session = root / "session-ABCDEF.jsonl"
        session.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            cst.find_unique_session(root, "ABC")
        self.assertEqual(cst.find_unique_session(root, "session-ABCDEF"), session)
        self.assertEqual(cst.find_unique_session(root, "session-ABCDEF.jsonl"), session)


class TestTransactionAndRepairContracts(ProtocolBase):
    def _live_source(self, session_id, turns=48):
        path = self.tmp / ".claude" / "projects" / "synthetic" / f"{session_id}.jsonl"
        return fx.write_jsonl(path, fx.build_linear(session_id, turns=turns).records)

    def _repair_live_source(self, session_id):
        fixture = RepairBase(methodName="runTest")
        fixture.setUp()
        try:
            tb, _source = fixture.build_source(["1"])
        finally:
            fixture.tearDown()
        for record in tb.records:
            if "sessionId" in record:
                record["sessionId"] = session_id
        path = self.tmp / ".claude" / "projects" / "synthetic" / f"{session_id}.jsonl"
        return fx.write_jsonl(path, tb.records)

    def test_strict_live_topology_failure_creates_no_work_or_backup_directory(self):
        session_id = "ffffffff-cccc-4fff-8fff-ffffffffffff"
        live = self._live_source(session_id)
        records = fx.read_jsonl(live)
        records[-1]["leafUuid"] = None
        fx.write_jsonl(live, records)
        work = self.tmp / "work"
        backups = self.tmp / "backups"
        original = live.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = ccj.main([
                "--input", str(live), "--replace-original", "--confirm-session-closed",
                "--work-dir", str(work), "--backup-dir", str(backups),
                "--summary-char-budget", "4000", "--deterministic-summary",
            ])
        self.assertEqual(code, 1)
        self.assertEqual(live.read_bytes(), original)
        self.assertFalse(work.exists())
        self.assertFalse(backups.exists())

    def test_live_compression_reports_committed_state_when_final_sidecar_fails(self):
        session_id = "12121212-dddd-4121-8121-121212121212"
        live = self._live_source(session_id)
        original = live.read_bytes()
        work = self.tmp / "work-compress"
        calls = 0

        def fail_final_sidecar(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise OSError("synthetic final sidecar failure")

        stdout = io.StringIO()
        with mock.patch.object(ccj, "write_sidecars", side_effect=fail_final_sidecar):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                code = ccj.main([
                    "--input", str(live), "--replace-original", "--confirm-session-closed",
                    "--work-dir", str(work), "--summary-char-budget", "4000",
                    "--min-recent-records", "6", "--target-ratio", "0.20",
                    "--deterministic-summary",
                ])
        self.assertEqual(code, 3)
        self.assertNotEqual(live.read_bytes(), original)
        state = json.loads(stdout.getvalue())
        self.assertEqual(state["operation_state"], "committed-report-failed")
        self.assertEqual(calls, 1, "live compression wrote a stale pre-commit sidecar")
        self.assertTrue(live.with_suffix(live.suffix + ".backup").exists())

    def test_live_compression_reports_committed_state_when_transaction_cleanup_fails(self):
        session_id = "13131313-dddd-4131-8131-131313131313"
        live = self._live_source(session_id)
        original = live.read_bytes()
        work = self.tmp / "work-compress-cleanup"
        real_unlink = pathlib.Path.unlink

        def fail_replacement_cleanup(path, *args, **kwargs):
            if f".{live.name}.replace-" in path.name:
                raise PermissionError("synthetic committed cleanup failure")
            return real_unlink(path, *args, **kwargs)

        stdout = io.StringIO()
        try:
            with mock.patch.object(pathlib.Path, "unlink", new=fail_replacement_cleanup):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                    code = ccj.main([
                        "--input", str(live), "--replace-original", "--confirm-session-closed",
                        "--work-dir", str(work), "--summary-char-budget", "4000",
                        "--min-recent-records", "6", "--target-ratio", "0.20",
                        "--deterministic-summary",
                    ])
            self.assertEqual(code, 3, stdout.getvalue())
            state = json.loads(stdout.getvalue())
            self.assertEqual(state["operation_state"], "committed-cleanup-failed")
            self.assertNotEqual(live.read_bytes(), original)
            self.assertTrue(live.with_suffix(live.suffix + ".backup").exists())
            self.assertTrue(state["replacement_cleanup_errors"])
            self.assertEqual(len(list(live.parent.glob(f".{live.name}.replace-*.tmp"))), 1)
        finally:
            for residue in live.parent.glob(f".{live.name}.replace-*.tmp"):
                if residue.exists():
                    real_unlink(residue)

    def test_live_repair_reports_committed_state_when_report_fails(self):
        session_id = "23232323-eeee-4232-8232-232323232323"
        live = self._repair_live_source(session_id)
        original = live.read_bytes()
        work = self.tmp / "work-repair"
        stdout = io.StringIO()
        with mock.patch.object(ccj, "atomic_write_text", side_effect=OSError("synthetic report failure")):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                code = rcj.main([
                    "--input", str(live), "--replace-original", "--confirm-session-closed",
                    "--work-dir", str(work), "--expect-matches", "1",
                ])
        self.assertEqual(code, 3)
        self.assertNotEqual(live.read_bytes(), original)
        state = json.loads(stdout.getvalue())
        self.assertEqual(state["operationState"], "committed-report-failed")
        self.assertTrue(live.with_suffix(live.suffix + ".backup").exists())

    def test_live_repair_reports_committed_state_when_transaction_cleanup_fails(self):
        session_id = "24242424-eeee-4242-8242-242424242424"
        live = self._repair_live_source(session_id)
        original = live.read_bytes()
        work = self.tmp / "work-repair-cleanup"
        real_unlink = pathlib.Path.unlink

        def fail_replacement_cleanup(path, *args, **kwargs):
            if f".{live.name}.replace-" in path.name:
                raise PermissionError("synthetic committed cleanup failure")
            return real_unlink(path, *args, **kwargs)

        stdout = io.StringIO()
        try:
            with mock.patch.object(pathlib.Path, "unlink", new=fail_replacement_cleanup):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                    code = rcj.main([
                        "--input", str(live), "--replace-original", "--confirm-session-closed",
                        "--work-dir", str(work), "--expect-matches", "1",
                    ])
            self.assertEqual(code, 3, stdout.getvalue())
            state = json.loads(stdout.getvalue())
            self.assertEqual(state["operationState"], "committed-cleanup-failed")
            self.assertNotEqual(live.read_bytes(), original)
            self.assertTrue(live.with_suffix(live.suffix + ".backup").exists())
            self.assertTrue(state["replacementCleanupErrors"])
            self.assertEqual(len(list(live.parent.glob(f".{live.name}.replace-*.tmp"))), 1)
        finally:
            for residue in live.parent.glob(f".{live.name}.replace-*.tmp"):
                if residue.exists():
                    real_unlink(residue)

    def test_repair_candidate_requires_full_transcript_validation(self):
        fixture = RepairBase(methodName="runTest")
        fixture.setUp()
        try:
            records = fixture.build_read_pair()
        finally:
            fixture.tearDown()
        records[0]["parentUuid"] = []
        source = ccj.jsonl_bytes(records)
        plan = rcj.plan_read_pages_repairs(source, scope="all")
        repaired = rcj.apply_patch_plan(source, plan)
        output = self.tmp / "invalid-repair-candidate.jsonl"
        with self.assertRaisesRegex(ValueError, "transcript|validation"):
            rcj.publish_repair_candidate(output, source, repaired, plan)
        self.assertFalse(output.exists())

    def test_negative_min_recent_records_is_rejected_before_output(self):
        source = fx.write_jsonl(
            self.tmp / "negative-source.jsonl",
            fx.build_linear("34343434-ffff-4343-8343-343434343434", turns=24).records,
        )
        output = self.tmp / "negative-output.jsonl"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = ccj.main([
                "--input", str(source), "--output", str(output),
                "--min-recent-records", "-1", "--summary-char-budget", "4000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())

    def test_packaged_and_embedded_summary_templates_match(self):
        packaged = (fx.SKILL_ROOT / "templates" / "summary_template_en.md").read_text(encoding="utf-8-sig")
        self.assertEqual(packaged, ccj.default_summary_template())


if __name__ == "__main__":
    unittest.main(verbosity=2)

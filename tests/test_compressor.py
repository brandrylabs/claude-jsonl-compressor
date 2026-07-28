#!/usr/bin/env python3
"""End-to-end and unit tests for claude-jsonl-compressor.

Dependency-free: uses only the standard library `unittest`. Run with either:

    python -m unittest discover -s tests -v
    python tests/test_compressor.py

These tests fixate the behaviours that were validated during the v5-v10
read-only and real-session reviews: active-chain selection, tool_use/tool_result
pairing across the cut, split tool_result serialization, second/Nth compression
de-duplication, robust handling of malformed/edge inputs, session locating +
numbered backups, and the validator catching broken chains.

NOTE on file-history-snapshot: strict active-chain mode keeps only bounded,
structurally correlated UUID-less snapshots from before the authoritative
pointer. The legacy physical window is available only in explicit physical-tail
compatibility mode.
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import random
import tempfile
import unittest
from unittest import mock

import _fixtures as fx

ccj = fx.ccj
cst = fx.cst


class CompressBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cjc_test_")
        self.tmp = pathlib.Path(self._tmp.name)
        # Compression mutates module-level summary resources lazily; reset each test.
        ccj._SUMMARY_RESOURCES_CONFIGURED = False

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def compress(self, src_records, out_name="out.jsonl", **kwargs):
        src = fx.write_jsonl(self.tmp / "src.jsonl", src_records)
        out = self.tmp / out_name
        defaults = dict(
            target_ratio=0.30,
            min_recent_records=120,
            summary_char_budget=60000,
            append_final_prompt=True,
            preserve_active_chain=True,
            deterministic_summary=True,
        )
        defaults.update(kwargs)
        report = ccj.compress_jsonl(input_path=src, output_path=out, **defaults)
        return report, out


class TestBasicCompression(CompressBase):
    def test_happy_path_validates(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=60, with_tools_every=5)
        report, out = self.compress(tb.records)
        v = report["validation"]
        self.assertTrue(v["ok"], v["errors"])
        self.assertEqual(v["errors"], [])
        self.assertEqual(report["preserve_mode"], "active-chain")
        self.assertTrue(v["active_chain_has_compact_boundary"])
        self.assertTrue(v["active_chain_has_compact_summary"])
        self.assertEqual(v["tool_pair_error_count"], 0)
        self.assertEqual(v["compact_boundary_count"], 1)
        self.assertEqual(v["compact_summary_count"], 1)
        self.assertEqual(report["package_version"], "1.0.0-rc.1")
        self.assertEqual(report["codex_offline_compression_version"], "v10")
        self.assertEqual(report["model_pack_schema_version"], 11)
        self.assertEqual(report["report_schema_version"], 1)
        self.assertEqual(report["input"], "src.jsonl")
        self.assertEqual(report["output"], "out.jsonl")
        self.assertAlmostEqual(
            report["ratio"],
            out.stat().st_size / (self.tmp / "src.jsonl").stat().st_size,
        )
        recs = fx.read_jsonl(out)
        boundary = next(r for r in recs if r.get("type") == "system" and r.get("subtype") == "compact_boundary")
        self.assertEqual(boundary["compactMetadata"]["codexOfflineCompressionVersion"], "v10")
        report_text = out.with_suffix(out.suffix + ".report.md").read_text(encoding="utf-8")
        self.assertIn("Active-chain records summarized", report_text)
        self.assertIn("Excluded inactive-branch records", report_text)
        self.assertIn("Source SHA-256", report_text)
        self.assertNotIn("- Omitted digest:", report_text)

    def test_output_records_parse_and_chain_resolves(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=50, with_tools_every=5)
        _report, out = self.compress(tb.records, summary_char_budget=6000, min_recent_records=8, target_ratio=0.2)
        recs = fx.read_jsonl(out)
        uuids = {r.get("uuid") for r in recs if isinstance(r.get("uuid"), str)}
        dangling = [r.get("uuid") for r in recs if r.get("parentUuid") not in (None,) and r.get("parentUuid") not in uuids]
        self.assertEqual(dangling, [], "no parentUuid should dangle")
        self.assertEqual(recs[-1]["type"], "last-prompt")

    def test_target_ratio_met_on_large_file(self):
        tb = fx.build_linear("dddddddd-dddd-dddd-dddd-dddddddddddd", turns=1000)
        report, _out = self.compress(tb.records, summary_char_budget=40000)
        self.assertTrue(report["validation"]["ok"])
        self.assertLess(report["ratio"], 0.5)

    def test_target_estimated_tokens_uses_built_in_estimator_and_reports_ceiling(self):
        tb = fx.build_linear("dededede-dede-dede-dede-dededededede", turns=300)
        report, _out = self.compress(
            tb.records,
            summary_char_budget=6000,
            min_recent_records=6,
            target_ratio=0.9,
            target_estimated_tokens=5000,
        )
        self.assertEqual(report["target_estimated_tokens"], 5000)
        self.assertLessEqual(report["output_estimated_message_tokens"], 5000)
        self.assertLess(report["effective_target_ratio"], report["requested_target_ratio"])

    def test_recent_raw_records_are_field_identical_except_first_parent_splice(self):
        tb = fx.build_linear("dfdfdfdf-dfdf-dfdf-dfdf-dfdfdfdfdfdf", turns=90, with_tools_every=7)
        for record in tb.records:
            if isinstance(record.get("uuid"), str):
                record["unknownRetainedField"] = {"nested": [1, "two", True]}
        report, out = self.compress(
            tb.records,
            summary_char_budget=8000,
            min_recent_records=10,
            target_ratio=0.22,
        )
        output_by_uuid = {
            record["uuid"]: record for record in fx.read_jsonl(out) if isinstance(record.get("uuid"), str)
        }
        raw_lines = report["raw_keep_source_lines"]
        self.assertGreater(len(raw_lines), 1)
        for position, source_line in enumerate(raw_lines):
            source_record = json.loads(json.dumps(tb.records[source_line - 1]))
            output_record = json.loads(json.dumps(output_by_uuid[source_record["uuid"]]))
            if position == 0:
                source_record.pop("parentUuid", None)
                output_record.pop("parentUuid", None)
            self.assertEqual(output_record, source_record, source_line)


class TestModelAssistedSummary(CompressBase):
    def _append_unscored_active_record_before_recent_tail(self, tb, marker):
        tb.records.pop()
        source_line = len(tb.records) + 1
        tb._add(
            tb._base(
                "system",
                uuid=str(ccj.uuid.uuid4()),
                subtype="progress",
                content=marker,
            )
        )
        for index in range(12):
            tb.user(f"recent prompt after optional system record {index}")
            tb.assistant_text(f"recent response after optional system record {index}")
        tb.last_prompt()
        return source_line

    def _model_summary_from_pack(self, pack):
        required_anchors = []
        for group_lines in pack.get("required_anchor_groups", {}).values():
            for line in group_lines:
                if line not in required_anchors:
                    required_anchors.append(line)
        anchors = list(required_anchors)
        for line in pack.get("evidence_anchor_lines", []):
            if line not in anchors:
                anchors.append(line)
            if len(anchors) >= max(24, len(required_anchors)):
                break
        if not anchors:
            self.fail("model summary pack should expose line anchors")
        short_refs = ", ".join(f"L{x}" for x in anchors[:8])
        claim_anchor_lines = {int(line) for line in (pack.get("required_claim_sources") or {})}
        non_claim_required_refs = ", ".join(
            f"L{x}" for x in required_anchors if x not in claim_anchor_lines
        )
        handoff_anchors = []
        for group_lines in pack.get("required_handoff_anchor_groups", {}).values():
            for line in group_lines:
                if line not in handoff_anchors:
                    handoff_anchors.append(line)
        handoff_refs = ", ".join(f"H{x}" for x in handoff_anchors)
        complete_refs = short_refs
        if non_claim_required_refs:
            complete_refs += f", {non_claim_required_refs}"
        if handoff_refs:
            complete_refs += f", {handoff_refs}"
        claim_coverage = "\n".join(
            f"- L{int(line)} support_text_json={json.dumps(str(source).strip()[:32], ensure_ascii=False)} disposition=covered"
            for line, source in sorted(
                (pack.get("required_claim_sources") or {}).items(),
                key=lambda item: int(item[0]),
            )
        )
        body = f"""<!-- {ccj.MODEL_SUMMARY_MARKER}
source_sha256: {pack['source_sha256']}
summary_source_sha256: {pack['summary_source_sha256']}
evidence_anchor_lines_digest: {pack['evidence_anchor_lines_digest']}
required_anchor_groups_digest: {pack['required_anchor_groups_digest']}
handoff_summary_digest: {pack.get('handoff_summary_sha256_prefix') or 'none'}
pack_request_digest: {pack['pack_request_digest']}
required_claim_sources_digest: {pack['required_claim_sources_digest']}
-->
# Model-Assisted Semantic Compression Summary

## Current State
The current state must be read from anchored evidence only. Relevant anchors: {short_refs}.

## Timeline and Supersessions
Chronology is preserved by line order. Earlier items may be superseded by later anchored evidence: {short_refs}.

## Decisions and Reasons
Decisions, reasons, constraints, and user wording are retained only when they have line anchors: {short_refs}.

## Assistant Research Decisions and Rationales
Assistant research choices, evidence checks, and reasons are retained with anchors: {short_refs}.

## Rejected or Superseded Alternatives
Rejected or superseded alternatives must not be treated as current final decisions. Evidence anchors: {short_refs}.

## Evidence and Source Anchors
Every mandatory semantic and handoff coverage group is cited here exactly once: {complete_refs}.

### Mandatory Evidence Coverage
{claim_coverage}

## User Wording and Constraints
The summary preserves user goals, wording constraints, and risk judgments when anchored: {short_refs}.

## Risks, Unknowns, and Follow-Ups
Unknowns are marked as unknown from provided anchors instead of guessed. Risk evidence: {short_refs}.

## Recent Raw Context Boundary
Recent raw JSONL records remain outside this model summary for rewind. This synthetic test summary avoids unsupported project facts. {short_refs}
"""
        return body

    def test_model_summary_pack_and_validated_model_summary(self):
        tb = fx.build_linear("77777777-7777-7777-7777-777777777777", turns=160, with_tools_every=8)
        src = fx.write_jsonl(self.tmp / "model_src.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.30,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
        )
        self.assertIn(ccj.MODEL_SUMMARY_MARKER, pack["text"])
        self.assertIn("evidence_anchor_lines_digest", pack)
        model_path = self.tmp / "model_summary.md"
        model_path.write_text(self._model_summary_from_pack(pack), encoding="utf-8")
        out = self.tmp / "model_out.jsonl"
        report = ccj.compress_jsonl(
            input_path=src,
            output_path=out,
            target_ratio=0.30,
            min_recent_records=8,
            summary_char_budget=30000,
            append_final_prompt=True,
            preserve_active_chain=True,
            model_summary_path=model_path,
            model_pack_char_budget=500000,
        )
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])
        self.assertEqual(report["semantic_summary_mode"], "model-assisted-v11")
        self.assertTrue(report["model_summary_validation"]["ok"], report["model_summary_validation"])
        recs = fx.read_jsonl(out)
        boundary = next(r for r in recs if r.get("type") == "system" and r.get("subtype") == "compact_boundary")
        summary = next(r for r in recs if r.get("isCompactSummary"))
        self.assertEqual(boundary["compactMetadata"]["codexOfflineCompressionVersion"], "v10")
        self.assertEqual(boundary["compactMetadata"]["semanticSummaryMode"], "model-assisted-v11")
        self.assertIn("Model-Assisted Semantic Summary", summary["message"]["content"])
        self.assertIn("Deterministic Safety Appendix", summary["message"]["content"])

    def test_unknown_placeholder_exemption_applies_only_to_the_entire_line(self):
        tb = fx.build_linear("67676767-6767-6767-6767-676767676767", turns=150, with_tools_every=11)
        src = fx.write_jsonl(self.tmp / "unknown-placeholder-source.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.25,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
        )
        base_summary = self._model_summary_from_pack(pack)
        risk_line = next(
            line for line in base_summary.splitlines()
            if line.startswith("Unknowns are marked as unknown from provided anchors")
        )
        refs = ", ".join(f"L{line}" for line in pack["evidence_anchor_lines"][:8])
        exact_placeholder = base_summary.replace(
            risk_line,
            f"Unknown from provided anchors.\nRisk status is supported by {refs}.",
            1,
        )
        exact_path = self.tmp / "exact-unknown-placeholder.md"
        exact_path.write_text(exact_placeholder, encoding="utf-8")
        exact_report = ccj.compress_jsonl(
            input_path=src,
            output_path=self.tmp / "exact-unknown-placeholder.jsonl",
            target_ratio=0.25,
            min_recent_records=8,
            summary_char_budget=30000,
            append_final_prompt=True,
            preserve_active_chain=True,
            model_summary_path=exact_path,
            model_pack_char_budget=500000,
        )
        self.assertTrue(exact_report["model_summary_validation"]["ok"])

        mixed_lines = {
            "unknown": "The synthetic archive uses the quartz index; Unknown from provided anchors.",
            "recent-context": "The synthetic archive uses the quartz index; recent raw JSONL records remain elsewhere.",
        }
        for label, mixed_line in mixed_lines.items():
            with self.subTest(label=label):
                unsupported_fact = exact_placeholder.replace("Unknown from provided anchors.", mixed_line, 1)
                unsupported_path = self.tmp / f"mixed-{label}-placeholder.md"
                unsupported_path.write_text(unsupported_fact, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "substantive lines without line anchors"):
                    ccj.compress_jsonl(
                        input_path=src,
                        output_path=self.tmp / f"mixed-{label}-placeholder.jsonl",
                        target_ratio=0.25,
                        min_recent_records=8,
                        summary_char_budget=30000,
                        append_final_prompt=True,
                        preserve_active_chain=True,
                        model_summary_path=unsupported_path,
                        model_pack_char_budget=500000,
                    )

    def test_markerless_multilingual_assistant_decisions_are_classified_and_packed(self):
        tb = fx.TranscriptBuilder("68686868-6868-6868-6868-686868686868")
        decisions = {
            24: "Final decision: adopt the cedar route because verified evidence rejects the former route.",
            70: "结论：采用青玉路径，因为核对证据后否定了旧路径。",
            116: "結論として瑠璃の経路を採用する。検証した証拠により旧案は不採用である。",
            162: "결론은 비취 경로를 채택하는 것이다. 검증한 증거 때문에 이전 안을 폐기한다.",
            208: "القرار النهائي هو اعتماد مسار الياقوت لأن الأدلة المتحققة تستبعد المسار السابق.",
            254: "Окончательное решение: выбрать янтарный маршрут, потому что проверенные доказательства отвергают прежний.",
            300: "अंतिम निर्णय नीलम मार्ग अपनाना है, क्योंकि सत्यापित प्रमाण पुराने मार्ग को अस्वीकार करते हैं।",
            346: "La decisión final adopta la ruta coral porque la evidencia verificada descarta la anterior.",
            378: "La décision finale retient la voie indigo parce que les preuves vérifiées écartent l'ancienne.",
            410: "Die endgültige Entscheidung übernimmt den Silberpfad, weil geprüfte Belege den alten verwerfen.",
            442: "A decisão final adota a rota violeta porque a evidência verificada rejeita a anterior.",
            474: "القرار الأحدث يعتمد مسار الزمرد ويلغي القرار الإنجليزي السابق استنادا إلى الأدلة المتحققة.",
            492: "Final decision: the obsidian route supersedes the earlier Chinese decision because the latest evidence was verified.",
        }
        decision_records = []
        for index in range(540):
            text = decisions.get(index, f"Routine assistant heartbeat {index}: processing synthetic batch.")
            tb.assistant_text(text)
            if index in decisions:
                decision_records.append((text, tb.records[-1]))
        tb.last_prompt()

        for text, record in decision_records:
            with self.subTest(text=text):
                self.assertTrue(ccj.is_assistant_research_decision(record, text))

        src = fx.write_jsonl(self.tmp / "multilingual-decisions.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.12,
            min_recent_records=8,
            summary_char_budget=16000,
            model_pack_char_budget=500000,
        )
        self.assertLessEqual(pack["pack_chars"], 500000)
        for text in decisions.values():
            with self.subTest(packed=text):
                self.assertIn(text, pack["text"])

    def test_all_distinct_hard_user_constraints_survive_verbose_assistant_decisions(self):
        constraints = [
            "The export must remain newline-delimited JSON.",
            "The final report must not contain absolute source paths.",
            "Every retained tool call must keep its matching result.",
            "The current session identifier must remain unchanged.",
            "No candidate may be published before validation succeeds.",
            "The rollback copy must preserve the exact original bytes.",
        ]
        tb = fx.TranscriptBuilder("69696969-6969-6969-6969-696969696969")
        for index in range(180):
            if index in (8, 36, 64, 92, 120, 148):
                tb.user(constraints[(8, 36, 64, 92, 120, 148).index(index)])
            tb.assistant_text(
                f"Final decision {index}: adopt the verbose synthetic route because verified evidence "
                + ("supports this detailed rationale and rejects the previous option. " * 24)
            )
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "hard-constraints.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.12,
            min_recent_records=8,
            summary_char_budget=14000,
            model_pack_char_budget=500000,
        )
        for constraint in constraints:
            with self.subTest(constraint=constraint):
                self.assertIn(constraint, pack["text"])

    def test_long_handoff_final_superseding_line_is_preserved_or_rejected_explicitly(self):
        tb = fx.build_linear("6a6a6a6a-6a6a-6a6a-6a6a-6a6a6a6a6a6a", turns=120)
        src = fx.write_jsonl(self.tmp / "long-handoff-source.jsonl", tb.records)
        final_line = "Final handoff decision: the heliotrope route supersedes every earlier route."
        handoff = self.tmp / "long-handoff.md"
        handoff.write_text(
            "\n".join(
                [f"Background handoff line {index}: " + ("synthetic context " * 12) for index in range(70)]
                + [final_line]
            ),
            encoding="utf-8",
        )
        try:
            pack = ccj.build_model_summary_pack_for_input(
                input_path=src,
                target_ratio=0.20,
                min_recent_records=8,
                summary_char_budget=12000,
                model_pack_char_budget=14000,
                handoff_summary_path=handoff,
            )
        except ValueError as exc:
            self.assertIn("handoff", str(exc).lower())
        else:
            self.assertIn(final_line, pack["text"])

    def test_model_pack_digest_only_allows_visible_evidence_anchors(self):
        tb = fx.build_linear("78787878-7878-7878-7878-787878787878", turns=260, with_tools_every=9)
        src = fx.write_jsonl(self.tmp / "small_pack_src.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.30,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
        )
        anchors = sorted(set(ccj.model_summary_anchor_lines(pack["text"])))
        evidence_anchors = sorted(set(ccj.model_pack_evidence_anchor_lines(pack["text"])))
        self.assertEqual(pack["evidence_anchor_lines"], evidence_anchors)
        self.assertEqual(pack["evidence_anchor_lines_digest"], ccj.anchor_lines_digest(evidence_anchors))
        self.assertEqual(sorted(set(pack["evidence_anchor_lines"])), evidence_anchors)
        self.assertLessEqual(len(pack["text"]), 500000)
        self.assertGreater(len(evidence_anchors), 0)
        self.assertTrue(set(evidence_anchors).issubset(set(anchors)))

    def test_model_pack_evidence_anchor_lines_ignore_body_line_references(self):
        pack_text = """# Claude JSONL Compression Evidence Pack

## Evidence Records
- L394 type=assistant role=assistant
  Body mentions unrelated labels L2, L25, L98, and a quoted audit note L1/L2/L3.
  - L25 type=assistant role=assistant is quoted text, not an evidence record prefix.
- L512 type=user role=user
  Another body line mentions L30 but it is not an evidence item prefix.

## External Handoff Summary
"""
        self.assertEqual(ccj.model_pack_evidence_anchor_lines(pack_text), [394, 512])

    def test_model_summary_rejects_anchor_not_visible_in_actual_pack(self):
        tb = fx.build_linear("79797979-7979-7979-7979-797979797979", turns=260, with_tools_every=9)
        invisible_line = self._append_unscored_active_record_before_recent_tail(
            tb,
            "heartbeat 12345",
        )
        src = fx.write_jsonl(self.tmp / "small_pack_src.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.30,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
        )
        visible = sorted(set(pack["evidence_anchor_lines"]))
        records, raw_lines = ccj.read_jsonl(src)
        plan = ccj.select_preservation_plan(
            records,
            raw_lines,
            src.stat().st_size,
            0.30,
            8,
            30000,
            True,
            120,
            80,
        )
        omitted = {idx + 1 for idx in plan["omitted_indexes"]}
        self.assertIn(invisible_line, omitted)
        self.assertNotIn(invisible_line, visible)
        bad_anchor = invisible_line
        refs = ", ".join(f"L{x}" for x in visible[:8])
        body = f"""<!-- {ccj.MODEL_SUMMARY_MARKER}
source_sha256: {pack['source_sha256']}
summary_source_sha256: {pack['summary_source_sha256']}
evidence_anchor_lines_digest: {pack['evidence_anchor_lines_digest']}
required_anchor_groups_digest: {pack['required_anchor_groups_digest']}
handoff_summary_digest: {pack.get('handoff_summary_sha256_prefix') or 'none'}
-->
# Model-Assisted Semantic Compression Summary

## Current State
Visible anchors are used here: {refs}.

## Timeline and Supersessions
This intentionally cites an omitted but non-visible line anchor L{bad_anchor} to prove rejection.
"""
        body += ("More anchored text. " + refs + " ") * 80
        model_path = self.tmp / "bad_invisible_anchor_summary.md"
        model_path.write_text(body, encoding="utf-8")
        out = self.tmp / "bad_invisible_anchor_out.jsonl"
        with self.assertRaisesRegex(ValueError, "not included in the generated evidence pack"):
            ccj.compress_jsonl(
                input_path=src,
                output_path=out,
                target_ratio=0.30,
                min_recent_records=8,
                summary_char_budget=30000,
                append_final_prompt=True,
                preserve_active_chain=True,
                model_summary_path=model_path,
                model_pack_char_budget=500000,
            )

    def test_model_pack_prioritizes_assistant_research_decisions_and_rationales(self):
        tb = fx.TranscriptBuilder("76767676-7676-7676-7676-767676767676")
        tb.custom_title("Multilingual research decision memory")
        important_markers = [
            "ASSISTANT_DECISION_CN_SLOT",
            "ASSISTANT_DECISION_EN_ARCH",
            "ASSISTANT_DECISION_JA_VERIFY",
            "ASSISTANT_DECISION_KO_RISK",
        ]
        for i in range(260):
            tb.user(f"routine user note {i}")
            if i == 70:
                tb.assistant_text(
                    "ASSISTANT_DECISION_CN_SLOT 结论：本阶段不用 Slot，因为导出 React 时页面壳不应锁死；"
                    "采纳侧栏组件方案，否定整壳组件方案，依据是官方组件行为和后续可编辑性。"
                )
            elif i == 120:
                tb.assistant_text(
                    "ASSISTANT_DECISION_EN_ARCH Critical finding: choose the self-hosted evidence system because "
                    "the verified evidence shows the managed publishing route would conflict with audit ownership; reject the older hosting route."
                )
            elif i == 170:
                tb.assistant_text(
                    "ASSISTANT_DECISION_JA_VERIFY 結論：この案を採用します。なぜなら検証した証拠があり、"
                    "旧案は不採用です。"
                )
            elif i == 210:
                tb.assistant_text(
                    "ASSISTANT_DECISION_KO_RISK 결론: 이 경로를 선택합니다. 왜냐하면 검증된 근거가 있고 "
                    "이전 대안은 거부되었습니다."
                )
            else:
                tb.assistant_text(f"routine assistant progress {i}")
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "assistant_decision_pack_src.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.15,
            min_recent_records=8,
            summary_char_budget=24000,
            model_pack_char_budget=500000,
        )
        for marker in important_markers:
            self.assertIn(marker, pack["text"])

    def test_model_pack_reserves_temporal_and_evidence_class_coverage(self):
        tb = fx.TranscriptBuilder("75757575-7575-7575-7575-757575757575")
        for i in range(240):
            tb.user(f"human constraint and decision {i}")
            if i % 17 == 0:
                tb.tool_call_pair(file_path=f"C:\\synthetic\\source{i}.md")
            else:
                tb.assistant_text(f"research conclusion {i} because verified evidence supersedes option {i - 1}")
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "coverage.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.18,
            min_recent_records=8,
            summary_char_budget=26000,
            model_pack_char_budget=500000,
        )
        groups = pack["required_anchor_groups"]
        visible = set(pack["evidence_anchor_lines"])
        for name in (
            "temporal-early", "temporal-middle", "temporal-late",
            "human-user", "assistant-research", "source-tool",
        ):
            self.assertIn(name, groups)
            self.assertTrue(groups[name], name)
            self.assertTrue(set(groups[name]).issubset(visible), name)
        summary_lines = pack["summary_source_lines"]
        late_threshold = summary_lines[(len(summary_lines) * 2) // 3]
        self.assertGreaterEqual(max(groups["temporal-late"]), late_threshold)
        self.assertEqual(
            pack["required_anchor_groups_digest"],
            ccj.anchor_groups_digest(groups),
        )

    def test_prior_compact_summary_is_full_dedicated_model_evidence(self):
        marker = "PRIOR_SUMMARY_FINAL_TAIL_MUST_REACH_MODEL"
        prior = "PRIOR START\n" + ("historical detail and reason\n" * 260) + marker
        tb = fx.TranscriptBuilder("74747474-7474-7474-7474-747474747474")
        tb.compact_pair(prior, codex=True)
        for i in range(80):
            tb.user(f"later prompt {i} current constraint")
            tb.assistant_text(f"later decision {i} because evidence")
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "prior-full.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.20,
            min_recent_records=8,
            summary_char_budget=24000,
            model_pack_char_budget=500000,
        )
        self.assertIn(marker, pack["text"])
        prior_groups = [name for name in pack["required_anchor_groups"] if name.startswith("prior-summary-L")]
        self.assertEqual(len(prior_groups), 1)
        self.assertEqual(len(pack["required_anchor_groups"][prior_groups[0]]), 1)

    def test_prior_compact_summary_that_cannot_fit_pack_budget_fails_closed(self):
        prior = "PRIOR START\n" + ("historical detail that must not be clipped\n" * 500)
        tb = fx.TranscriptBuilder("73737373-7373-7373-7373-737373737373")
        tb.compact_pair(prior, codex=True)
        for i in range(40):
            tb.user(f"new turn {i}")
            tb.assistant_text(f"new answer {i}")
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "prior-too-large.jsonl", tb.records)
        with self.assertRaisesRegex(ValueError, "prior compact summary evidence"):
            ccj.build_model_summary_pack_for_input(
                input_path=src,
                target_ratio=0.20,
                min_recent_records=6,
                summary_char_budget=12000,
                model_pack_char_budget=10000,
            )

    def test_missing_required_model_summary_heading_is_rejected(self):
        tb = fx.build_linear("72727272-7272-7272-7272-727272727272", turns=140, with_tools_every=9)
        src = fx.write_jsonl(self.tmp / "missing-heading.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.25,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
        )
        model_text = self._model_summary_from_pack(pack).replace(
            "## Assistant Research Decisions and Rationales",
            "## Miscellaneous Notes",
            1,
        )
        model_path = self.tmp / "missing-heading.md"
        model_path.write_text(model_text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "required semantic sections"):
            ccj.compress_jsonl(
                input_path=src,
                output_path=self.tmp / "missing-heading-out.jsonl",
                target_ratio=0.25,
                min_recent_records=8,
                summary_char_budget=30000,
                append_final_prompt=True,
                preserve_active_chain=True,
                model_summary_path=model_path,
                model_pack_char_budget=500000,
            )

    def test_model_composition_never_silently_truncates_accepted_text(self):
        tail = "MODEL_SUMMARY_TAIL_MARKER"
        model_text = ("anchored model detail L1. " * 90) + tail
        composed = ccj.compose_model_assisted_summary(model_text, "safety detail " * 500, 9000)
        self.assertIn(tail, composed)
        self.assertLessEqual(len(composed), 9000)
        with self.assertRaisesRegex(ValueError, "summary character budget"):
            ccj.compose_model_assisted_summary(model_text * 4, "safety", 5000)

    def test_unicode_token_estimate_is_conservative_for_dense_scripts_and_symbols(self):
        self.assertGreaterEqual(ccj.estimate_tokens("かなカナ" * 20), 100)
        self.assertGreaterEqual(ccj.estimate_tokens("한글" * 40), 90)
        self.assertGreaterEqual(ccj.estimate_tokens("😀" * 40), 60)

    def test_two_valid_model_summaries_produce_identical_topology(self):
        tb = fx.build_linear("70707070-7070-7070-7070-707070707070", turns=150, with_tools_every=10)
        src = fx.write_jsonl(self.tmp / "topology-source.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.25,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
        )
        summary_a = self._model_summary_from_pack(pack)
        refs = ", ".join(f"L{x}" for x in pack["evidence_anchor_lines"][:8])
        summary_b = summary_a.replace(
            "The current state must be read from anchored evidence only.",
            f"A distinct valid model wording preserves the same frozen source topology and cites {refs}.",
            1,
        )

        def make_output(name, summary_text):
            model_path = self.tmp / f"{name}.md"
            model_path.write_text(summary_text, encoding="utf-8")
            out = self.tmp / f"{name}.jsonl"
            ccj.compress_jsonl(
                input_path=src,
                output_path=out,
                target_ratio=0.25,
                min_recent_records=8,
                summary_char_budget=30000,
                append_final_prompt=True,
                preserve_active_chain=True,
                model_summary_path=model_path,
                model_pack_char_budget=500000,
            )
            return fx.read_jsonl(out)

        def topology(records):
            uuid_to_index = {
                record.get("uuid"): index
                for index, record in enumerate(records)
                if isinstance(record.get("uuid"), str)
            }
            shape = []
            for record in records:
                parent = record.get("parentUuid")
                leaf = record.get("leafUuid") if record.get("type") == "last-prompt" else None
                shape.append((
                    record.get("type"),
                    record.get("subtype"),
                    record.get("isCompactSummary") is True,
                    ccj.api_role(record),
                    uuid_to_index.get(parent, parent),
                    uuid_to_index.get(leaf, leaf),
                    tuple(ccj.tool_use_ids(record)),
                    tuple(ccj.tool_result_ids(record)),
                ))
            return shape

        self.assertEqual(topology(make_output("model-a", summary_a)), topology(make_output("model-b", summary_b)))

    def test_rewound_branch_text_is_absent_from_every_readable_sink(self):
        sentinels = [
            "DEAD_USER_SENTINEL",
            "DEAD_ASSISTANT_SENTINEL",
            "DEAD_TOOL_SENTINEL",
            "DEAD_PRIOR_SUMMARY_SENTINEL",
            "DEAD_SNAPSHOT_SENTINEL",
        ]
        tb = fx.build_linear("6f6f6f6f-6f6f-6f6f-6f6f-6f6f6f6f6f6f", turns=100, with_tools_every=13)
        active_leaf = tb.records[-1]["leafUuid"]
        tb.prev_uuid = tb.records[12]["uuid"]
        tb.user(sentinels[0])
        tb.assistant_text(sentinels[1])
        tb.tool_call_pair(file_path=f"C:\\synthetic\\{sentinels[2]}.md")
        tb.compact_pair(sentinels[3], codex=False)
        tb.file_history_snapshot(sentinels[4], source_uuid=active_leaf)
        src = fx.write_jsonl(self.tmp / "dead-sinks-source.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.22,
            min_recent_records=8,
            summary_char_budget=12000,
            model_pack_char_budget=500000,
        )
        out = self.tmp / "dead-sinks-out.jsonl"
        ccj.compress_jsonl(
            input_path=src,
            output_path=out,
            target_ratio=0.22,
            min_recent_records=8,
            summary_char_budget=12000,
            append_final_prompt=True,
            preserve_active_chain=True,
            deterministic_summary=True,
            model_pack_char_budget=500000,
        )
        readable = "\n".join([
            pack["text"],
            out.read_text(encoding="utf-8"),
            out.with_suffix(out.suffix + ".report.md").read_text(encoding="utf-8"),
            out.with_suffix(out.suffix + ".validation.json").read_text(encoding="utf-8"),
        ])
        for sentinel in sentinels:
            self.assertNotIn(sentinel, readable)

    def test_deterministic_evidence_sampling_keeps_late_research_decision(self):
        marker = "LATE_RESEARCH_DECISION_SENTINEL"
        tb = fx.TranscriptBuilder("71717171-7171-7171-7171-717171717171")
        for i in range(280):
            tb.user(f"routine prompt {i}")
            text = f"routine response {i}"
            if i == 260:
                text = marker + " final conclusion because verified evidence supersedes the previous plan"
            tb.assistant_text(text)
        info = ccj.collect_summary_inputs(tb.records)
        self.assertIn(marker, "\n".join(text for _line, text in info["assistant_decision_items"]))

    def test_model_summary_wrong_digest_is_rejected(self):
        tb = fx.build_linear("78787878-7878-7878-7878-787878787878", turns=140, with_tools_every=10)
        src = fx.write_jsonl(self.tmp / "bad_model_src.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.30,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
        )
        bad = self._model_summary_from_pack(pack).replace(pack["omitted_digest"], "badbadbadbadbadb", 1)
        model_path = self.tmp / "bad_model_summary.md"
        model_path.write_text(bad, encoding="utf-8")
        with self.assertRaises(ValueError):
            ccj.compress_jsonl(
                input_path=src,
                output_path=self.tmp / "bad_model_out.jsonl",
                target_ratio=0.30,
                min_recent_records=8,
            summary_char_budget=30000,
            append_final_prompt=True,
            preserve_active_chain=True,
            model_summary_path=model_path,
                model_pack_char_budget=500000,
            )

    def test_model_summary_handoff_digest_mismatch_is_rejected(self):
        tb = fx.build_linear("7c7c7c7c-7c7c-7c7c-7c7c-7c7c7c7c7c7c", turns=120, with_tools_every=8)
        src = fx.write_jsonl(self.tmp / "handoff_src.jsonl", tb.records)
        handoff_a = self.tmp / "handoff_a.md"
        handoff_b = self.tmp / "handoff_b.md"
        handoff_a.write_text("handoff A: current state L2\n", encoding="utf-8")
        handoff_b.write_text("handoff B: changed context L2\n", encoding="utf-8")
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.30,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
            handoff_summary_path=handoff_a,
        )
        self.assertEqual(pack["handoff_summary_file"], "HANDOFF_SUMMARY")
        self.assertNotIn(handoff_a.name, pack["text"])
        self.assertNotIn(str(handoff_a.parent), json.dumps(pack, ensure_ascii=False))
        model_path = self.tmp / "handoff_model_summary.md"
        model_path.write_text(self._model_summary_from_pack(pack), encoding="utf-8")
        with self.assertRaises(ValueError):
            ccj.compress_jsonl(
                input_path=src,
                output_path=self.tmp / "handoff_out.jsonl",
                target_ratio=0.30,
                min_recent_records=8,
                summary_char_budget=30000,
                append_final_prompt=True,
                preserve_active_chain=True,
                handoff_summary_path=handoff_b,
                model_summary_path=model_path,
                model_pack_char_budget=500000,
            )

    def test_handoff_facts_require_visible_h_anchors(self):
        tb = fx.build_linear("7f7f7f7f-7f7f-7f7f-7f7f-7f7f7f7f7f7f", turns=120)
        src = fx.write_jsonl(self.tmp / "handoff_anchor_src.jsonl", tb.records)
        handoff = self.tmp / "handoff_anchor.md"
        handoff.write_text("User-provided background constraint for this run.\n", encoding="utf-8")
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.3,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
            handoff_summary_path=handoff,
        )
        handoff_line = handoff.read_bytes().decode("utf-8")
        self.assertIn(f"- H1 full_text_json={ccj.pack_json_string(handoff_line)}", pack["text"])
        good_path = self.tmp / "handoff_anchor_good.md"
        good_path.write_text(
            self._model_summary_from_pack(pack) + "\nThis handoff-only statement is explicitly supported by H1.\n",
            encoding="utf-8",
        )
        report = ccj.compress_jsonl(
            input_path=src,
            output_path=self.tmp / "handoff_anchor_out.jsonl",
            target_ratio=0.3,
            min_recent_records=8,
            summary_char_budget=30000,
            handoff_summary_path=handoff,
            model_summary_path=good_path,
            model_pack_char_budget=500000,
        )
        self.assertTrue(report["model_summary_validation"]["ok"])
        bad_path = self.tmp / "handoff_anchor_bad.md"
        bad_path.write_text(
            self._model_summary_from_pack(pack) + "\nThis statement cites an anchor that was never shown: H2.\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "handoff anchors not shown"):
            ccj.compress_jsonl(
                input_path=src,
                output_path=self.tmp / "handoff_anchor_bad_out.jsonl",
                target_ratio=0.3,
                min_recent_records=8,
                summary_char_budget=30000,
                handoff_summary_path=handoff,
                model_summary_path=bad_path,
                model_pack_char_budget=500000,
            )

    def test_library_requires_explicit_summary_mode(self):
        tb = fx.build_linear("7d7d7d7d-7d7d-7d7d-7d7d-7d7d7d7d7d7d", turns=80, with_tools_every=8)
        src = fx.write_jsonl(self.tmp / "library_default_src.jsonl", tb.records)
        with self.assertRaises(ValueError):
            ccj.compress_jsonl(
                input_path=src,
                output_path=self.tmp / "library_default_out.jsonl",
                target_ratio=0.30,
                min_recent_records=8,
                summary_char_budget=12000,
                append_final_prompt=True,
                preserve_active_chain=True,
            )

    def test_library_rejects_model_summary_and_deterministic_summary_together(self):
        tb = fx.build_linear("7e7e7e7e-7e7e-7e7e-7e7e-7e7e7e7e7e7e", turns=80, with_tools_every=8)
        src = fx.write_jsonl(self.tmp / "library_mutual_exclusion_src.jsonl", tb.records)
        model_path = self.tmp / "placeholder_model_summary.md"
        model_path.write_text("placeholder", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            ccj.compress_jsonl(
                input_path=src,
                output_path=self.tmp / "library_mutual_exclusion_out.jsonl",
                target_ratio=0.30,
                min_recent_records=8,
                summary_char_budget=12000,
                append_final_prompt=True,
                preserve_active_chain=True,
                model_summary_path=model_path,
                deterministic_summary=True,
            )

    def test_model_summary_cannot_cite_unshown_omitted_line(self):
        tb = fx.build_linear("7b7b7b7b-7b7b-7b7b-7b7b-7b7b7b7b7b7b", turns=180, with_tools_every=10)
        invisible_line = self._append_unscored_active_record_before_recent_tail(
            tb,
            "heartbeat 12345",
        )
        src = fx.write_jsonl(self.tmp / "unshown_anchor_src.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.30,
            min_recent_records=8,
            summary_char_budget=30000,
            model_pack_char_budget=500000,
        )
        allowed = set(ccj.model_pack_evidence_anchor_lines(pack["text"]))
        records, raw_lines = ccj.read_jsonl(src)
        plan = ccj.select_preservation_plan(
            records,
            raw_lines,
            src.stat().st_size,
            0.30,
            8,
            30000,
            True,
            120,
            80,
        )
        all_omitted = {idx + 1 for idx in plan["omitted_indexes"]}
        self.assertIn(invisible_line, all_omitted)
        self.assertNotIn(invisible_line, allowed)
        unshown = invisible_line
        model_text = self._model_summary_from_pack(pack) + f"\nUnsupported extra citation L{unshown}.\n"
        model_path = self.tmp / "unshown_anchor_summary.md"
        model_path.write_text(model_text, encoding="utf-8")
        with self.assertRaises(ValueError):
            ccj.compress_jsonl(
                input_path=src,
                output_path=self.tmp / "unshown_anchor_out.jsonl",
                target_ratio=0.30,
                min_recent_records=8,
                summary_char_budget=30000,
                append_final_prompt=True,
                preserve_active_chain=True,
                model_summary_path=model_path,
                model_pack_char_budget=500000,
            )

    def test_cli_requires_model_summary_by_default(self):
        tb = fx.build_linear("79797979-7979-7979-7979-797979797979", turns=80, with_tools_every=8)
        src = fx.write_jsonl(self.tmp / "cli_default_src.jsonl", tb.records)
        out = self.tmp / "cli_default_out.jsonl"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = ccj.main(["--input", str(src), "--output", str(out), "--summary-char-budget", "12000"])
        self.assertEqual(code, 1)
        self.assertIn("--model-summary", err.getvalue())
        self.assertFalse(out.exists())

    def test_cli_write_model_pack_refuses_output_inside_claude_root_for_claude_input(self):
        session_id = "77777777-7777-7777-7777-777777777777"
        tb = fx.build_linear(session_id, turns=80)
        src = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        pack_path = self.tmp / ".claude" / "pack.md"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = ccj.main([
                "--input", str(src),
                "--write-model-pack", str(pack_path),
                "--target-ratio", "0.30",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
            ])
        self.assertEqual(code, 1)
        self.assertIn("--write-model-pack process files must be outside the entire .claude directory", err.getvalue())
        self.assertFalse(pack_path.exists())

    def test_cli_deterministic_summary_requires_explicit_flag(self):
        tb = fx.build_linear("7a7a7a7a-7a7a-7a7a-7a7a-7a7a7a7a7a7a", turns=80, with_tools_every=8)
        src = fx.write_jsonl(self.tmp / "cli_fallback_src.jsonl", tb.records)
        out = self.tmp / "cli_fallback_out.jsonl"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = ccj.main([
                "--input", str(src),
                "--output", str(out),
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertTrue(out.exists())


class TestActiveChain(CompressBase):
    def test_prefers_last_prompt_chain_over_physical_dead_branch(self):
        tb = fx.TranscriptBuilder("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        main_leaf = None
        for i in range(40):
            tb.user(f"main {i} 决定 goal constraint")
            main_leaf = tb.assistant_text(f"reply {i} 结论 because")
        tb.last_prompt(main_leaf)
        # Dead branch hanging off an early node, placed physically at the tail.
        early_parent = tb.records[3]["uuid"]
        tb.prev_uuid = early_parent
        for i in range(15):
            tb.user(f"DEAD branch {i}", parent="__chain__")
            tb.assistant_text(f"dead {i}")
        report, out = self.compress(
            tb.records, summary_char_budget=6000, min_recent_records=6, target_ratio=0.3,
            target_session_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )
        v = report["validation"]
        self.assertTrue(v["ok"], v["errors"])
        self.assertEqual(report["selected_leaf_uuid"], main_leaf)
        # Rewound branch text must not appear in any Claude-readable output layer.
        recs = fx.read_jsonl(out)
        self.assertNotIn("DEAD branch", json.dumps(recs, ensure_ascii=False))
        src = fx.write_jsonl(self.tmp / "dead_pack_src.jsonl", tb.records)
        pack = ccj.build_model_summary_pack_for_input(
            input_path=src,
            target_ratio=0.3,
            min_recent_records=6,
            summary_char_budget=6000,
            model_pack_char_budget=500000,
        )
        self.assertNotIn("DEAD branch", pack["text"])
        self.assertEqual(report["excluded_branch_count"], 30)

    def test_broken_last_prompt_leaf_fails_closed(self):
        tb = fx.build_linear("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", turns=30)
        for r in tb.records:
            if r.get("type") == "last-prompt":
                r["leafUuid"] = "dead-uuid-does-not-exist"
        with self.assertRaisesRegex(ValueError, "missing uuid"):
            self.compress(tb.records, summary_char_budget=6000, min_recent_records=5, target_ratio=0.3)

    def test_no_last_prompt_requires_explicit_physical_tail(self):
        tb = fx.build_linear("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", turns=30)
        tb.records = [r for r in tb.records if r.get("type") != "last-prompt"]
        with self.assertRaisesRegex(ValueError, "requires a last-prompt"):
            self.compress(tb.records, summary_char_budget=6000, min_recent_records=5, target_ratio=0.3)
        report, _out = self.compress(
            tb.records,
            summary_char_budget=6000,
            min_recent_records=5,
            target_ratio=0.3,
            preserve_active_chain=False,
        )
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])
        self.assertEqual(report["preserve_mode"], "physical-tail")

    def test_active_chain_default_excludes_unattributed_file_history_snapshots(self):
        tb = fx.TranscriptBuilder("cccccccc-cccc-cccc-cccc-cccccccccccc")
        for i in range(40):
            tb.user(f"edit file {i}")
            tb.assistant_text(f"done {i}")
            tb.file_history_snapshot(f"file{i}.txt")
        tb.last_prompt()
        report, out = self.compress(tb.records, summary_char_budget=5000, min_recent_records=6, target_ratio=0.3)
        recs = fx.read_jsonl(out)
        fhs = [r for r in recs if r.get("type") == "file-history-snapshot"]
        self.assertEqual(len(fhs), 0)
        self.assertEqual(report["file_history_snapshots_preserved"], len(fhs))
        self.assertEqual(report["checkpoint_policy"], "active-correlated")

    def test_active_chain_keeps_structurally_correlated_file_history_snapshot(self):
        tb = fx.TranscriptBuilder("cccccccc-cccc-cccc-cccc-cccccccccccc")
        for i in range(40):
            tb.user(f"edit file {i}")
            assistant_uuid = tb.assistant_text(f"done {i}")
            assistant_message_id = tb.records[-1]["message"]["id"]
            tb.file_history_snapshot(
                f"file{i}.txt", message_id=assistant_message_id, source_uuid=assistant_uuid
            )
        tb.last_prompt()
        report, out = self.compress(tb.records, summary_char_budget=5000, min_recent_records=6, target_ratio=0.3)
        fhs = [r for r in fx.read_jsonl(out) if r.get("type") == "file-history-snapshot"]
        self.assertGreater(len(fhs), 0)
        self.assertEqual(report["file_history_snapshots_preserved"], len(fhs))

    def test_strict_active_chain_rejects_legacy_preserve_recent_checkpoint_policy(self):
        tb = fx.TranscriptBuilder("cccccccc-cccc-cccc-cccc-cccccccccccc")
        for i in range(40):
            tb.user(f"edit file {i}")
            tb.assistant_text(f"done {i}")
            tb.file_history_snapshot(f"file{i}.txt")
        tb.last_prompt()
        with self.assertRaisesRegex(ValueError, "not available in strict active-chain mode"):
            self.compress(
                tb.records, summary_char_budget=5000, min_recent_records=6, target_ratio=0.3,
                checkpoint_policy="preserve-recent",
            )

    def test_post_pointer_correlated_snapshot_is_excluded_from_strict_side_keep(self):
        marker = "POST_POINTER_REWOUND_SNAPSHOT_SENTINEL"
        tb = fx.build_linear("c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1", turns=45)
        active_leaf = tb.records[-1]["leafUuid"]
        tb.file_history_snapshot(marker, source_uuid=active_leaf)
        report, out = self.compress(
            tb.records, summary_char_budget=5000, min_recent_records=6, target_ratio=0.25,
        )
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])
        self.assertNotIn(marker, out.read_text(encoding="utf-8"))

    def test_active_chain_can_disable_file_history_snapshot_side_records(self):
        tb = fx.TranscriptBuilder("cccccccc-cccc-cccc-cccc-cccccccccccc")
        for i in range(20):
            tb.user(f"edit file {i}")
            tb.assistant_text(f"done {i}")
            tb.file_history_snapshot(f"file{i}.txt")
        tb.last_prompt()
        report, out = self.compress(
            tb.records,
            summary_char_budget=5000,
            min_recent_records=6,
            target_ratio=0.3,
            max_file_history_snapshots=0,
        )
        recs = fx.read_jsonl(out)
        fhs = [r for r in recs if r.get("type") == "file-history-snapshot"]
        self.assertEqual(len(fhs), 0)
        self.assertEqual(report["file_history_snapshots_preserved"], 0)

    def test_physical_tail_mode_keeps_recent_file_history_snapshots(self):
        tb = fx.TranscriptBuilder("cccccccc-cccc-cccc-cccc-cccccccccccc")
        for i in range(40):
            tb.user(f"edit file {i}")
            tb.assistant_text(f"done {i}")
            tb.file_history_snapshot(f"file{i}.txt")
        tb.last_prompt()
        _report, out = self.compress(
            tb.records, summary_char_budget=5000, min_recent_records=6, target_ratio=0.3,
            preserve_active_chain=False,
        )
        recs = fx.read_jsonl(out)
        fhs = [r for r in recs if r.get("type") == "file-history-snapshot"]
        self.assertGreater(len(fhs), 0, "physical-tail mode should keep recent file-history-snapshots")

    def test_latest_malformed_pointer_is_not_skipped_for_older_valid_pointer(self):
        tb = fx.build_linear("cdcdcdcd-cdcd-cdcd-cdcd-cdcdcdcdcdcd", turns=40)
        tb.add_raw({"type": "last-prompt", "leafUuid": 7, "sessionId": tb.session_id})
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "malformed")

    def test_physical_last_valid_pointer_wins_when_two_are_present(self):
        tb = fx.build_linear("cacacaca-caca-caca-caca-cacacacacaca", turns=35)
        older_leaf = tb.records[-1]["leafUuid"]
        newer_leaf = tb.records[20]["uuid"]
        tb.last_prompt(newer_leaf)
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertTrue(info["ok"], info["errors"])
        self.assertEqual(info["selectedLeafUuid"], newer_leaf)
        self.assertNotEqual(info["selectedLeafUuid"], older_leaf)
        self.assertEqual(info["lastPromptLine"], len(tb.records))

    def test_active_chain_missing_parent_fails_closed(self):
        tb = fx.build_linear("c2c2c2c2-c2c2-c2c2-c2c2-c2c2c2c2c2c2", turns=35)
        tb.records[30]["parentUuid"] = "missing-active-parent"
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "dangling")

    def test_active_chain_loop_fails_closed(self):
        tb = fx.build_linear("c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3", turns=35)
        first_uuid_record = next(record for record in tb.records if isinstance(record.get("uuid"), str))
        first_uuid_record["parentUuid"] = tb.records[-1]["leafUuid"]
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "loop")

    def test_active_chain_cross_session_fails_closed(self):
        tb = fx.build_linear("c4c4c4c4-c4c4-c4c4-c4c4-c4c4c4c4c4c4", turns=35)
        tb.records[30]["sessionId"] = "other-session"
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "session-mismatch")

    def test_active_chain_non_monotonic_parent_order_fails_closed(self):
        tb = fx.build_linear("c5c5c5c5-c5c5-c5c5-c5c5-c5c5c5c5c5c5", turns=35)
        tb.records[-1]["leafUuid"] = tb.records[35]["uuid"]
        tb.records[25]["parentUuid"] = tb.records[45]["uuid"]
        tb.records[45]["parentUuid"] = tb.records[5]["uuid"]
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "non-monotonic")

    def test_attachment_only_physical_inversion_is_normalized_in_output(self):
        tb = fx.build_linear("c7c7c7c7-c7c7-c7c7-c7c7-c7c7c7c7c7c7", turns=25)
        tb.records.pop()
        base_parent = tb.prev_uuid
        first_uuid = "71717171-7171-7171-7171-717171717171"
        second_uuid = "72727272-7272-7272-7272-727272727272"
        common = {
            "type": "attachment",
            "sessionId": tb.session_id,
            "isSidechain": False,
            "attachment": {"type": "synthetic-context", "content": "anonymous"},
        }
        tb.add_raw({**common, "uuid": second_uuid, "parentUuid": first_uuid})
        tb.add_raw({**common, "uuid": first_uuid, "parentUuid": base_parent})
        tb.prev_uuid = second_uuid
        for i in range(30):
            tb.user(f"later user {i}")
            tb.assistant_text(f"later answer {i}")
        tb.last_prompt()

        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertTrue(info["ok"], info["errors"])
        self.assertEqual(info["nonMonotonicCompatibilityEdgeCount"], 1)
        self.assertTrue(info["warnings"])
        report, out = self.compress(
            tb.records, summary_char_budget=6000, min_recent_records=80, target_ratio=0.8,
        )
        output = fx.read_jsonl(out)
        positions = {record.get("uuid"): index for index, record in enumerate(output)}
        self.assertLess(positions[first_uuid], positions[second_uuid])
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])

    def test_attachment_physical_inversion_requires_explicit_same_session(self):
        records = [
            {"type": "user", "uuid": "73737373-7373-7373-7373-737373737373", "parentUuid": None,
             "message": {"role": "user", "content": "synthetic"}},
            {"type": "attachment", "uuid": "75757575-7575-7575-7575-757575757575",
             "parentUuid": "74747474-7474-7474-7474-747474747474", "attachment": {"type": "synthetic"}},
            {"type": "attachment", "uuid": "74747474-7474-7474-7474-747474747474",
             "parentUuid": "73737373-7373-7373-7373-737373737373", "attachment": {"type": "synthetic"}},
            {"type": "last-prompt", "leafUuid": "75757575-7575-7575-7575-757575757575"},
        ]
        info = ccj.choose_resume_leaf_info(records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "non-monotonic")

    def test_one_way_session_lineage_summarizes_old_sessions_and_keeps_current_raw(self):
        old_session = "81818181-8181-8181-8181-818181818181"
        current_session = "82828282-8282-8282-8282-828282828282"
        tb = fx.build_linear(old_session, turns=100)
        transition = 150
        old_uuid = tb.records[transition - 1]["uuid"]
        for record in tb.records[transition:]:
            if isinstance(record.get("uuid"), str):
                record["sessionId"] = current_session
                record["forkedFrom"] = {"sessionId": old_session, "messageUuid": record["uuid"]}
        tb.records[-1]["sessionId"] = current_session

        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertTrue(info["ok"], info["errors"])
        self.assertTrue(info["sessionLineageCompatibility"])
        self.assertEqual(info["sessionLineageTransitionCount"], 1)
        report, out = self.compress(
            tb.records, summary_char_budget=6000, min_recent_records=8, target_ratio=0.8,
        )
        output = fx.read_jsonl(out)
        self.assertNotIn(old_uuid, {record.get("uuid") for record in output})
        output_sessions = {
            record.get("sessionId") for record in output if isinstance(record.get("uuid"), str)
        }
        self.assertEqual(output_sessions, {current_session})
        output_by_uuid = {
            record["uuid"]: record for record in output if isinstance(record.get("uuid"), str)
        }
        for position, source_line in enumerate(report["raw_keep_source_lines"]):
            source_record = json.loads(json.dumps(tb.records[source_line - 1]))
            output_record = json.loads(json.dumps(output_by_uuid[source_record["uuid"]]))
            if position == 0:
                source_record.pop("parentUuid", None)
                output_record.pop("parentUuid", None)
            self.assertEqual(output_record, source_record, source_line)
        self.assertTrue(report["session_lineage_compatibility"])
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])

    def test_session_lineage_pointer_must_match_final_session(self):
        old_session = "83838383-8383-8383-8383-838383838383"
        current_session = "84848484-8484-8484-8484-848484848484"
        tb = fx.build_linear(old_session, turns=40)
        for record in tb.records[50:-1]:
            record["sessionId"] = current_session
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "session-mismatch")

    def test_session_lineage_tool_pair_crossing_transition_fails_closed(self):
        old_session = "85858585-8585-8585-8585-858585858585"
        current_session = "86868686-8686-8686-8686-868686868686"
        tb = fx.build_linear(old_session, turns=40)
        tb.records.pop()
        tb.tool_call_pair()
        tb.records[-1]["sessionId"] = current_session
        for i in range(12):
            tb.user(f"current user {i}")
            tb.records[-1]["sessionId"] = current_session
            tb.assistant_text(f"current answer {i}")
            tb.records[-1]["sessionId"] = current_session
        tb.last_prompt()
        tb.records[-1]["sessionId"] = current_session
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertTrue(info["ok"], info["errors"])
        with self.assertRaisesRegex(ValueError, "tool relationship crosses session lineage"):
            ccj.select_preservation_plan(
                records=tb.records,
                raw_lines=[json.dumps(record, ensure_ascii=False) for record in tb.records],
                input_bytes=10_000_000,
                target_ratio=0.9,
                min_recent_records=8,
                summary_char_budget=1000,
                preserve_active_chain=True,
                max_post_prompt_extension=0,
                max_file_history_snapshots=0,
            )

    def test_active_chain_non_string_parent_fails_closed(self):
        tb = fx.build_linear("c6c6c6c6-c6c6-c6c6-c6c6-c6c6c6c6c6c6", turns=35)
        tb.records[30]["parentUuid"] = {"not": "a uuid"}
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "malformed-parent")

    def test_manual_resume_leaf_override_is_explicit_and_projected(self):
        tb = fx.build_linear("cececece-cece-cece-cece-cececececece", turns=50)
        valid_leaf = tb.records[-2]["uuid"]
        tb.records[-1]["leafUuid"] = "missing"
        tb.records[-1]["unknownControlField"] = {"keep": True}
        report, out = self.compress(
            tb.records, summary_char_budget=5000, min_recent_records=6, target_ratio=0.3,
            resume_leaf_override=valid_leaf,
        )
        self.assertTrue(report["resume_leaf_info"]["manualOverride"])
        self.assertEqual(report["preserve_mode"], "active-chain-manual-override")
        pointers = [r for r in fx.read_jsonl(out) if r.get("type") == "last-prompt"]
        self.assertEqual(len(pointers), 1)
        self.assertEqual(pointers[0]["unknownControlField"], {"keep": True})
        boundary = next(r for r in fx.read_jsonl(out) if r.get("subtype") == "compact_boundary")
        self.assertEqual(boundary["compactMetadata"]["preserveMode"], "active-chain-manual-override")

    def test_active_partition_is_complete_and_mutually_exclusive(self):
        tb = fx.TranscriptBuilder("cfcfcfcf-cfcf-cfcf-cfcf-cfcfcfcfcfcf")
        for i in range(50):
            tb.user(f"active {i}")
            leaf = tb.assistant_text(f"answer {i}")
        tb.last_prompt(leaf)
        tb.prev_uuid = tb.records[3]["uuid"]
        tb.user("INACTIVE SENTINEL")
        tb.assistant_text("inactive answer")
        src = fx.write_jsonl(self.tmp / "partition.jsonl", tb.records)
        records, raw = ccj.read_jsonl(src)
        plan = ccj.select_preservation_plan(records, raw, src.stat().st_size, 0.2, 6, 5000, True, 0, 80)
        keys = (
            "summary_indexes", "raw_keep_indexes", "side_keep_indexes",
            "control_projection_indexes", "excluded_branch_indexes", "excluded_unattributed_indexes",
        )
        sets = [set(plan[key]) for key in keys]
        self.assertEqual(set().union(*sets), set(range(len(records))))
        self.assertEqual(sum(len(s) for s in sets), len(records))
        self.assertNotIn("INACTIVE SENTINEL", "\n".join(raw[i] for i in plan["summary_indexes"]))

    def test_fixed_seed_branch_partition_depends_on_topology_not_body_text(self):
        rng = random.Random(20260727)
        tb = fx.TranscriptBuilder("d0d0d0d0-d0d0-d0d0-d0d0-d0d0d0d0d0d0")
        active_uuids = []
        for i in range(80):
            active_uuids.append(tb.user(f"active prompt {i}"))
            active_uuids.append(tb.assistant_text(f"active answer {i}"))
        active_leaf = active_uuids[-1]
        tb.last_prompt(active_leaf)
        for branch in range(12):
            tb.prev_uuid = rng.choice(active_uuids[:80])
            for depth in range(rng.randint(1, 5)):
                tb.user(f"DEAD_{branch}_{depth}")
                tb.assistant_text(f"dead answer {branch}_{depth}")
        src = fx.write_jsonl(self.tmp / "fixed_seed.jsonl", tb.records)
        records, raw = ccj.read_jsonl(src)
        plan_a = ccj.select_preservation_plan(records, raw, src.stat().st_size, 0.2, 8, 5000, True, 0, 0)
        mutated = json.loads(json.dumps(records))
        for idx, record in enumerate(mutated):
            message = record.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                message["content"] = f"randomized body {rng.random()} record {idx}"
        mutated_src = fx.write_jsonl(self.tmp / "fixed_seed_mutated.jsonl", mutated)
        mutated_records, mutated_raw = ccj.read_jsonl(mutated_src)
        plan_b = ccj.select_preservation_plan(
            mutated_records, mutated_raw, mutated_src.stat().st_size, 0.2, 8, 5000, True, 0, 0
        )
        for key in ("excluded_branch_indexes", "control_projection_indexes", "side_keep_indexes"):
            self.assertEqual(plan_a[key], plan_b[key], key)
        self.assertEqual(plan_a["selected_leaf_uuid"], active_leaf)
        self.assertEqual(plan_b["selected_leaf_uuid"], active_leaf)

    def test_broken_non_active_branch_does_not_block_valid_authoritative_chain(self):
        tb = fx.build_linear("d1d1d1d1-d1d1-d1d1-d1d1-d1d1d1d1d1d1", turns=50)
        tb.add_raw({
            "type": "assistant", "uuid": "dead-child", "parentUuid": "dead-missing-parent",
            "sessionId": tb.session_id, "message": {"role": "assistant", "content": [{"type": "text", "text": "dead"}]},
        })
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertTrue(info["ok"], info["errors"])
        src = fx.write_jsonl(self.tmp / "inactive_broken.jsonl", tb.records)
        records, raw = ccj.read_jsonl(src)
        plan = ccj.select_preservation_plan(records, raw, src.stat().st_size, 0.2, 6, 5000, True, 0, 0)
        self.assertIn(len(records) - 1, plan["excluded_branch_indexes"])

    def test_duplicate_uuid_anywhere_blocks_topology(self):
        tb = fx.build_linear("d2d2d2d2-d2d2-d2d2-d2d2-d2d2d2d2d2d2", turns=30)
        duplicate = dict(tb.records[4])
        duplicate["message"] = {"role": "assistant", "content": [{"type": "text", "text": "dead duplicate"}]}
        tb.add_raw(duplicate)
        info = ccj.choose_resume_leaf_info(tb.records)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "duplicate-uuid")

    def test_post_pointer_tool_result_requires_explicit_closure_limit(self):
        tb = fx.TranscriptBuilder("d3d3d3d3-d3d3-d3d3-d3d3-d3d3d3d3d3d3")
        tb.user("read one file")
        tb.tool_call_pair(file_path="C:\\synthetic\\evidence.md")
        result = tb.records.pop()
        assistant_leaf = tb.records[-1]["uuid"]
        tb.prev_uuid = assistant_leaf
        tb.last_prompt(assistant_leaf)
        tb.add_raw(result)
        default_info = ccj.choose_resume_leaf_info(tb.records)
        self.assertTrue(default_info["ok"])
        self.assertEqual(default_info["selectedLeafUuid"], assistant_leaf)
        closure_info = ccj.choose_resume_leaf_info(tb.records, max_post_prompt_extension=1)
        self.assertTrue(closure_info["ok"], closure_info["errors"])
        self.assertEqual(closure_info["selectedLeafUuid"], result["uuid"])
        self.assertEqual(closure_info["postLastPromptExtensionReasons"], ["tool_result_closure"])

    def test_post_pointer_ordinary_api_message_is_rejected_when_extension_requested(self):
        tb = fx.build_linear("d4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d4", turns=30)
        tb.user("new prompt after pointer")
        info = ccj.choose_resume_leaf_info(tb.records, max_post_prompt_extension=2)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "extension-unsafe")

    def test_post_pointer_system_record_is_not_a_safe_extension(self):
        tb = fx.build_linear("d5d5d5d5-d5d5-d5d5-d5d5-d5d5d5d5d5d5", turns=30)
        pointer_leaf = tb.records[-1]["leafUuid"]
        tb.add_raw({
            "type": "system",
            "subtype": "hook_response",
            "uuid": "post-system",
            "parentUuid": pointer_leaf,
            "sessionId": tb.session_id,
            "content": "not a tool closure",
        })
        info = ccj.choose_resume_leaf_info(tb.records, max_post_prompt_extension=1)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "extension-unsafe")

    def test_post_pointer_partial_tool_result_closure_is_rejected(self):
        tb = fx.TranscriptBuilder("d6d6d6d6-d6d6-d6d6-d6d6-d6d6d6d6d6d6")
        tb.user("read two sources")
        tb.split_tool_result_pair()
        _second_result = tb.records.pop()
        first_result = tb.records.pop()
        assistant_leaf = tb.records[-1]["uuid"]
        tb.prev_uuid = assistant_leaf
        tb.last_prompt(assistant_leaf)
        tb.add_raw(first_result)
        info = ccj.choose_resume_leaf_info(tb.records, max_post_prompt_extension=1)
        self.assertFalse(info["ok"])
        self.assertEqual(info["status"], "extension-unsafe")
        self.assertIn("pending tool_use", " ".join(info["errors"]))


class TestToolPairing(CompressBase):
    def test_tool_pairs_never_cut_across_boundary(self):
        tb = fx.TranscriptBuilder("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
        for i in range(50):
            tb.user(f"q{i}")
            tb.tool_call_pair(file_path=f"C:\\w\\doc{i}.md")
        tb.last_prompt()
        # Try several aggressive cut points; pairing must stay intact at every one.
        for mr in (4, 5, 7, 10):
            report, _out = self.compress(
                tb.records, out_name=f"tp_{mr}.jsonl",
                summary_char_budget=4000, min_recent_records=mr, target_ratio=0.2,
            )
            v = report["validation"]
            self.assertTrue(v["ok"], (mr, v["errors"]))
            self.assertEqual(v["tool_pair_error_count"], 0, (mr, v["tool_pair_error_samples"]))

    def test_split_tool_results_validate_as_one_api_user_message(self):
        tb = fx.TranscriptBuilder("e1e1e1e1-e1e1-e1e1-e1e1-e1e1e1e1e1e1")
        tb.user("read two files")
        tb.split_tool_result_pair(assistant_fragments=False)
        tb.assistant_text("used both results")
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "split_tool_results.jsonl", tb.records)
        v = ccj.validate_jsonl(src)
        self.assertTrue(v["ok"], v["errors"])
        self.assertEqual(v["tool_pair_error_count"], 0, v["tool_pair_error_samples"])
        self.assertEqual(
            v["tool_pair_validation_mode"],
            "active-chain-api-message-ordered-subset-with-explicit-partial-warning",
        )
        self.assertEqual(v["tool_pair_merge_strategy"], "merge-assistant-fragments-and-split-tool-result-users")

    def test_split_tool_results_with_assistant_fragments_validate(self):
        tb = fx.TranscriptBuilder("e2e2e2e2-e2e2-e2e2-e2e2-e2e2e2e2e2e2")
        tb.user("read two files through fragmented assistant records")
        tb.split_tool_result_pair(assistant_fragments=True)
        tb.assistant_text("done")
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "split_tool_results_fragments.jsonl", tb.records)
        v = ccj.validate_jsonl(src)
        self.assertTrue(v["ok"], v["errors"])
        self.assertEqual(v["tool_pair_error_count"], 0, v["tool_pair_error_samples"])

    def test_split_tool_results_wrong_id_fails_validation(self):
        tb = fx.TranscriptBuilder("e3e3e3e3-e3e3-e3e3-e3e3-e3e3e3e3e3e3")
        tb.user("read two files but second result is wrong")
        tb.split_tool_result_pair(bad_second_result=True)
        tb.assistant_text("done")
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "split_tool_results_bad.jsonl", tb.records)
        v = ccj.validate_jsonl(src)
        self.assertFalse(v["ok"])
        self.assertGreater(v["tool_pair_error_count"], 0)


class TestRepeatedCompression(CompressBase):
    def test_second_compression_does_not_stack_compact_pairs(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=60, with_tools_every=5)
        _r1, out1 = self.compress(tb.records, out_name="round1.jsonl")
        out2 = self.tmp / "round2.jsonl"
        report2 = ccj.compress_jsonl(
            input_path=out1, output_path=out2,
            target_ratio=0.30, min_recent_records=5, summary_char_budget=8000,
            append_final_prompt=True, preserve_active_chain=True,
            deterministic_summary=True,
        )
        v = report2["validation"]
        self.assertTrue(v["ok"], v["errors"])
        self.assertEqual(v["compact_boundary_count"], 1)
        self.assertEqual(v["compact_summary_count"], 1)
        self.assertEqual(v["codex_compact_boundary_count"], 1)

    def test_official_compact_pair_is_folded_in(self):
        tb = fx.TranscriptBuilder("ffffffff-ffff-ffff-ffff-ffffffffffff")
        tb.compact_pair("OFFICIAL CLAUDE SUMMARY: prior history about contract law", codex=False)
        for i in range(40):
            tb.user(f"turn {i} 决定")
            tb.assistant_text(f"r{i}")
        tb.last_prompt()
        report, out = self.compress(tb.records, summary_char_budget=6000, min_recent_records=6, target_ratio=0.3)
        v = report["validation"]
        self.assertTrue(v["ok"], v["errors"])
        self.assertEqual(v["compact_boundary_count"], 1)
        self.assertEqual(v["compact_summary_count"], 1)
        # The folded summary should reference the prior official summary content.
        recs = fx.read_jsonl(out)
        summary = next(r for r in recs if r.get("isCompactSummary"))
        self.assertIn("OFFICIAL CLAUDE SUMMARY", summary["message"]["content"])

    def test_explicit_prior_summary_verbatim_preserves_old_summary_text(self):
        marker = "TAIL-MARKER-PRIOR-SUMMARY-KEEP-EXACTLY"
        prior_summary = "PRIOR SUMMARY START\n" + ("important preserved detail.\n" * 180) + marker
        tb = fx.TranscriptBuilder("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        tb.compact_pair(prior_summary, codex=True)
        for i in range(50):
            tb.user(f"new research turn {i} final current decision")
            tb.assistant_text(f"assistant rationale {i} because evidence")
        tb.last_prompt()
        report, out = self.compress(
            tb.records,
            summary_char_budget=20000,
            min_recent_records=6,
            target_ratio=0.3,
            preserve_prior_summaries_verbatim=True,
        )
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])
        policy = report["prior_summary_verbatim_policy"]
        self.assertEqual(policy["mode"], "verbatim-preserved")
        self.assertEqual(policy["preservedCount"], 1)
        recs = fx.read_jsonl(out)
        self.assertEqual(sum(1 for r in recs if r.get("isCompactSummary")), 1)
        summary = next(r for r in recs if r.get("isCompactSummary"))
        self.assertIn(marker, summary["message"]["content"])
        boundary = next(r for r in recs if r.get("type") == "system" and r.get("subtype") == "compact_boundary")
        self.assertEqual(boundary["compactMetadata"]["priorSummaryVerbatimPolicy"]["mode"], "verbatim-preserved")

    def test_explicit_prior_summary_verbatim_falls_back_when_too_large(self):
        marker = "TAIL-MARKER-TOO-LARGE-PRIOR-SUMMARY"
        prior_summary = "PRIOR HUGE SUMMARY START\n" + ("large historical layer.\n" * 700) + marker
        tb = fx.TranscriptBuilder("bbbbbbbb-cccc-dddd-eeee-ffffffffffff")
        tb.compact_pair(prior_summary, codex=True)
        for i in range(45):
            tb.user(f"new work turn {i} final current decision")
            tb.assistant_text(f"assistant rationale {i} because evidence")
        tb.last_prompt()
        report, out = self.compress(
            tb.records,
            summary_char_budget=4000,
            min_recent_records=6,
            target_ratio=0.3,
            preserve_prior_summaries_verbatim=True,
        )
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])
        policy = report["prior_summary_verbatim_policy"]
        self.assertEqual(policy["mode"], "fallback-folded")
        self.assertIn("exceeding expanded budget", policy["fallbackReason"])
        recs = fx.read_jsonl(out)
        summary = next(r for r in recs if r.get("isCompactSummary"))
        self.assertNotIn(marker, summary["message"]["content"])

    def test_refuses_to_stack_when_no_raw_after_prior_compact(self):
        tb = fx.TranscriptBuilder("99999999-9999-9999-9999-999999999999")
        for i in range(10):
            tb.user(f"t{i}")
            tb.assistant_text(f"r{i}")
        summ = tb.compact_pair("prev summary", codex=True)
        tb.last_prompt(summ)
        src = fx.write_jsonl(self.tmp / "stack.jsonl", tb.records)
        out = self.tmp / "stack_out.jsonl"
        with self.assertRaises(ValueError):
            ccj.compress_jsonl(
                input_path=src, output_path=out,
                target_ratio=0.3, min_recent_records=3, summary_char_budget=4000,
                append_final_prompt=True, preserve_active_chain=True,
            )

    def test_three_model_assisted_rounds_keep_one_compact_pair(self):
        session_id = "98989898-9898-9898-9898-989898989898"
        current = fx.write_jsonl(
            self.tmp / "model-round-source.jsonl",
            fx.build_linear(session_id, turns=120, with_tools_every=11).records,
        )
        for round_index in range(1, 4):
            pack = ccj.build_model_summary_pack_for_input(
                input_path=current,
                target_ratio=0.28,
                min_recent_records=8,
                summary_char_budget=30000,
                model_pack_char_budget=500000,
            )
            model_text = TestModelAssistedSummary._model_summary_from_pack(self, pack)
            model_path = self.tmp / f"round-{round_index}.model.md"
            model_path.write_text(model_text, encoding="utf-8")
            output = self.tmp / f"round-{round_index}.jsonl"
            report = ccj.compress_jsonl(
                input_path=current,
                output_path=output,
                target_ratio=0.28,
                min_recent_records=8,
                summary_char_budget=30000,
                append_final_prompt=True,
                preserve_active_chain=True,
                model_summary_path=model_path,
                model_pack_char_budget=500000,
            )
            self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])
            self.assertEqual(report["semantic_summary_mode"], "model-assisted-v11")
            records = fx.read_jsonl(output)
            self.assertEqual(sum(1 for record in records if record.get("isCompactSummary") is True), 1)
            self.assertEqual(
                sum(1 for record in records if record.get("type") == "system" and record.get("subtype") == "compact_boundary"),
                1,
            )
            if round_index < 3:
                pointer = records.pop()
                builder = fx.TranscriptBuilder(session_id)
                builder.records = records
                builder.prev_uuid = pointer["leafUuid"]
                builder._clock = 1000 + round_index * 100
                for turn in range(28):
                    builder.user(f"round {round_index} new research prompt {turn} current constraint")
                    builder.assistant_text(f"round {round_index} decision {turn} because verified evidence")
                builder.last_prompt()
                current = fx.write_jsonl(self.tmp / f"round-{round_index}.extended.jsonl", builder.records)
            else:
                current = output


class TestEdgeCases(CompressBase):
    def _expect_error(self, records_or_text, **kwargs):
        if isinstance(records_or_text, str):
            src = self.tmp / "edge.jsonl"
            src.write_text(records_or_text, encoding="utf-8")
        else:
            src = fx.write_jsonl(self.tmp / "edge.jsonl", records_or_text)
        out = self.tmp / "edge_out.jsonl"
        with self.assertRaises(Exception):
            ccj.compress_jsonl(
                input_path=src, output_path=out,
                target_ratio=0.3, min_recent_records=5, summary_char_budget=4000,
                append_final_prompt=True, preserve_active_chain=True,
            )

    def test_empty_file_errors(self):
        self._expect_error("")

    def test_malformed_json_line_errors(self):
        self._expect_error('{"type":"user","uuid":"a"}\nNOT JSON\n')

    def test_non_object_line_errors(self):
        self._expect_error("[1,2,3]\n")

    def test_same_input_output_path_refused(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=10)
        src = fx.write_jsonl(self.tmp / "same.jsonl", tb.records)
        with self.assertRaises(ValueError):
            ccj.compress_jsonl(
                input_path=src, output_path=src,
                target_ratio=0.3, min_recent_records=5, summary_char_budget=4000,
                append_final_prompt=True, preserve_active_chain=True,
            )

    def test_api_rejects_nonpositive_and_impractically_small_summary_budgets_early(self):
        missing_source = self.tmp / "budget-source-must-not-be-read.jsonl"
        for budget in (0, -1, 64):
            with self.subTest(budget=budget):
                with self.assertRaisesRegex(ValueError, "summary.*budget"):
                    ccj.compress_jsonl(
                        input_path=missing_source,
                        output_path=self.tmp / f"api-budget-{budget}.jsonl",
                        target_ratio=0.30,
                        min_recent_records=8,
                        summary_char_budget=budget,
                        append_final_prompt=True,
                        preserve_active_chain=True,
                        deterministic_summary=True,
                    )

    def test_cli_rejects_nonpositive_and_impractically_small_summary_budgets_early(self):
        missing_source = self.tmp / "cli-budget-source-must-not-be-read.jsonl"
        for budget in (0, -1, 64):
            with self.subTest(budget=budget):
                output = self.tmp / f"cli-budget-{budget}.jsonl"
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    code = ccj.main([
                        "--input", str(missing_source),
                        "--output", str(output),
                        "--summary-char-budget", str(budget),
                        "--deterministic-summary",
                    ])
                self.assertEqual(code, 1)
                self.assertRegex(stderr.getvalue(), r"summary(?:-char-budget| character budget)")
                self.assertFalse(output.exists())

    def test_api_refuses_candidate_output_directly_under_claude_projects(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        src = fx.write_jsonl(self.tmp / "source.jsonl", tb.records)
        live_output = self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl"
        with self.assertRaisesRegex(ValueError, "outside the entire \\.claude directory"):
            ccj.compress_jsonl(
                input_path=src,
                output_path=live_output,
                target_ratio=0.3,
                min_recent_records=5,
                summary_char_budget=4000,
                append_final_prompt=True,
                preserve_active_chain=True,
                deterministic_summary=True,
            )
        self.assertFalse(live_output.exists())

    def test_replace_original_mode_backs_up_and_replaces_single_target(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=80, with_tools_every=8)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        before = target.read_bytes()
        work_dir = self.tmp / "work"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(work_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 0)
        backup = target.with_suffix(target.suffix + ".backup")
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(), before)
        self.assertNotEqual(target.read_bytes(), before)
        candidate = work_dir / f"{session_id}.compressed-candidate.jsonl"
        self.assertTrue(candidate.exists())
        self.assertTrue(candidate.with_suffix(candidate.suffix + ".report.md").exists())
        self.assertTrue(candidate.with_suffix(candidate.suffix + ".validation.json").exists())
        validation = ccj.validate_jsonl(target)
        self.assertTrue(validation["ok"], validation["errors"])
        recs = fx.read_jsonl(target)
        sessions = {r.get("sessionId") for r in recs if isinstance(r.get("sessionId"), str)}
        self.assertEqual(sessions, {session_id})

    def test_replace_original_mode_can_store_backup_in_external_dir(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=80, with_tools_every=8)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        before = target.read_bytes()
        work_dir = self.tmp / "work"
        backup_dir = self.tmp / "external-backups"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(work_dir),
                "--backup-dir", str(backup_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 0)
        external_backup = backup_dir / f"{target.name}.backup"
        self.assertTrue(external_backup.exists())
        self.assertEqual(external_backup.read_bytes(), before)
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())
        self.assertNotEqual(target.read_bytes(), before)
        validation = ccj.validate_jsonl(target)
        self.assertTrue(validation["ok"], validation["errors"])

    def test_replace_original_external_backup_dir_increments_suffix(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=80, with_tools_every=8)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        before = target.read_bytes()
        work_dir = self.tmp / "work"
        backup_dir = self.tmp / "external-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        first_backup = backup_dir / f"{target.name}.backup"
        first_backup.write_text("existing external backup", encoding="utf-8")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(work_dir),
                "--backup-dir", str(backup_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 0)
        second_backup = backup_dir / f"{target.name}.backup1"
        self.assertEqual(first_backup.read_text(encoding="utf-8"), "existing external backup")
        self.assertTrue(second_backup.exists())
        self.assertEqual(second_backup.read_bytes(), before)
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())

    def test_backup_dir_requires_replace_original(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        src = fx.write_jsonl(self.tmp / "source.jsonl", tb.records)
        out = self.tmp / "out.jsonl"
        backup_dir = self.tmp / "external-backups"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ccj.main([
                "--input", str(src),
                "--output", str(out),
                "--backup-dir", str(backup_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 1)
        self.assertIn("--backup-dir requires --replace-original", stderr.getvalue())
        self.assertFalse(out.exists())
        self.assertFalse(backup_dir.exists())

    def test_replace_original_mode_increments_existing_backup_suffix(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=80, with_tools_every=8)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        before = target.read_bytes()
        first_backup = target.with_suffix(target.suffix + ".backup")
        first_backup.write_text("existing backup", encoding="utf-8")
        work_dir = self.tmp / "work"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(work_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 0)
        second_backup = target.with_suffix(target.suffix + ".backup1")
        self.assertEqual(first_backup.read_text(encoding="utf-8"), "existing backup")
        self.assertTrue(second_backup.exists())
        self.assertEqual(second_backup.read_bytes(), before)

    def test_replace_original_refuses_work_dir_inside_claude_project_dir(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        before = target.read_bytes()
        work_dir = target.parent / "compression-work"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(work_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 1)
        self.assertIn("outside the entire .claude directory", stderr.getvalue())
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())
        self.assertFalse(work_dir.exists())

    def test_replace_original_refuses_work_dir_inside_claude_root(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        before = target.read_bytes()
        work_dir = self.tmp / ".claude" / "compression-work"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(work_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 1)
        self.assertIn("outside the entire .claude directory", stderr.getvalue())
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())
        self.assertFalse(work_dir.exists())

    def test_replace_original_refuses_backup_dir_inside_claude_root(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        before = target.read_bytes()
        backup_dir = self.tmp / ".claude" / "compression-backups"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(self.tmp / "work"),
                "--backup-dir", str(backup_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 1)
        self.assertIn("--backup-dir process files must be outside the entire .claude directory", stderr.getvalue())
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())
        self.assertFalse(backup_dir.exists())

    def test_replace_original_refuses_model_summary_inside_claude_root(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        model_summary = self.tmp / ".claude" / "model-summary.md"
        model_summary.parent.mkdir(parents=True, exist_ok=True)
        model_summary.write_text("placeholder", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(self.tmp / "work"),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--model-summary", str(model_summary),
            ])
        self.assertEqual(code, 1)
        self.assertIn("--model-summary process files must be outside the entire .claude directory", stderr.getvalue())
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())

    def test_replace_original_refuses_handoff_summary_inside_claude_root(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        handoff_summary = self.tmp / ".claude" / "handoff.md"
        handoff_summary.parent.mkdir(parents=True, exist_ok=True)
        handoff_summary.write_text("placeholder", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(self.tmp / "work"),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
                "--handoff-summary", str(handoff_summary),
            ])
        self.assertEqual(code, 1)
        self.assertIn("--handoff-summary process files must be outside the entire .claude directory", stderr.getvalue())
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())

    def test_cli_refuses_candidate_output_directly_under_claude_projects(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        src = fx.write_jsonl(self.tmp / "source.jsonl", tb.records)
        live_output = self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ccj.main([
                "--input", str(src),
                "--output", str(live_output),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 1)
        self.assertIn("--output process files must be outside the entire .claude directory", stderr.getvalue())
        self.assertFalse(live_output.exists())

    def test_replace_original_refuses_non_claude_projects_input(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=30)
        target = fx.write_jsonl(self.tmp / "ordinary.jsonl", tb.records)
        work_dir = self.tmp / "work"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = ccj.main([
                "--input", str(target),
                "--replace-original",
                "--confirm-session-closed",
                "--work-dir", str(work_dir),
                "--target-ratio", "0.25",
                "--min-recent-records", "8",
                "--summary-char-budget", "12000",
                "--deterministic-summary",
            ])
        self.assertEqual(code, 1)
        self.assertIn("only for one .claude/projects session JSONL", stderr.getvalue())
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())
        self.assertFalse(work_dir.exists())

    def test_replace_original_refuses_if_source_changed_after_candidate_generation(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        tb = fx.build_linear(session_id, turns=80, with_tools_every=8)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", tb.records)
        before = target.read_bytes()
        work_dir = self.tmp / "work"
        real_compress = ccj.compress_jsonl

        def mutate_after_compress(*args, **kwargs):
            report = real_compress(*args, **kwargs)
            target.write_bytes(before + b"\n")
            return report

        stderr = io.StringIO()
        with mock.patch.object(ccj, "compress_jsonl", side_effect=mutate_after_compress):
            with contextlib.redirect_stderr(stderr):
                code = ccj.main([
                    "--input", str(target),
                    "--replace-original",
                    "--confirm-session-closed",
                    "--work-dir", str(work_dir),
                    "--target-ratio", "0.25",
                    "--min-recent-records", "8",
                    "--summary-char-budget", "12000",
                    "--deterministic-summary",
                ])
        self.assertEqual(code, 1)
        self.assertIn("changed after candidate generation", stderr.getvalue())
        self.assertEqual(target.read_bytes(), before + b"\n")
        self.assertFalse(target.with_suffix(target.suffix + ".backup").exists())

    def test_stale_legacy_tmp_file_does_not_block_unique_staged_replacement(self):
        session_id = "55555555-5555-5555-5555-555555555555"
        target_tb = fx.build_linear(session_id, turns=20)
        candidate_tb = fx.build_linear(session_id, turns=22)
        target = fx.write_jsonl(self.tmp / ".claude" / "projects" / "proj" / f"{session_id}.jsonl", target_tb.records)
        candidate = fx.write_jsonl(self.tmp / "candidate.jsonl", candidate_tb.records)
        tmp_replace = target.with_name(target.name + ".replace-tmp")
        tmp_replace.write_text("stale temporary file", encoding="utf-8")
        before = target.read_bytes()
        result = ccj._replace_file_after_validation(candidate, target)
        self.assertNotEqual(target.read_bytes(), before)
        self.assertEqual(result["backup_path"].read_bytes(), before)
        self.assertTrue(tmp_replace.exists())
        self.assertEqual(tmp_replace.read_text(encoding="utf-8"), "stale temporary file")
        self.assertEqual(list(target.parent.glob(f".{target.name}.replace-*.tmp")), [])
        self.assertEqual(list(target.parent.glob(f".{target.name}.old-*.tmp")), [])

    def test_bom_and_crlf_input(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=30)
        src = self.tmp / "bom.jsonl"
        with src.open("wb") as f:
            f.write(b"\xef\xbb\xbf")  # UTF-8 BOM
            for r in tb.records:
                f.write((json.dumps(r, ensure_ascii=False) + "\r\n").encode("utf-8"))
        out = self.tmp / "bom_out.jsonl"
        report = ccj.compress_jsonl(
            input_path=src, output_path=out,
            target_ratio=0.3, min_recent_records=4, summary_char_budget=4000,
            append_final_prompt=True, preserve_active_chain=True,
            deterministic_summary=True,
        )
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])

    def test_records_without_uuid(self):
        records = [{"type": "user", "message": {"role": "user", "content": f"hello {i} 必须保留"}} for i in range(30)]
        report, _out = self.compress(
            records, summary_char_budget=4000, min_recent_records=4, target_ratio=0.3,
            preserve_active_chain=False,
        )
        self.assertTrue(report["validation"]["ok"], report["validation"]["errors"])

    def test_cjk_preserved_in_summary(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=40)
        _report, out = self.compress(tb.records, summary_char_budget=6000, min_recent_records=6, target_ratio=0.3)
        recs = fx.read_jsonl(out)
        summary = next(r for r in recs if r.get("isCompactSummary"))
        import re
        self.assertTrue(re.search(r"[一-鿿]", summary["message"]["content"]))


class TestValidator(CompressBase):
    def test_validator_flags_broken_chain(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=40, with_tools_every=5)
        _report, out = self.compress(tb.records, summary_char_budget=6000, min_recent_records=6, target_ratio=0.3)
        recs = fx.read_jsonl(out)
        for r in recs:
            if r.get("type") == "assistant":
                r["parentUuid"] = "broken-nonexistent-uuid"
                break
        broken = fx.write_jsonl(self.tmp / "broken.jsonl", recs)
        result = ccj.validate_jsonl(broken)
        self.assertFalse(result["ok"])
        self.assertGreater(result["missing_parent_count"], 0)

    def test_validator_reports_non_string_parent_without_crashing(self):
        tb = fx.build_linear("12121212-1212-1212-1212-121212121212", turns=30)
        tb.records[30]["parentUuid"] = {"not": "a uuid"}
        result = ccj.validate_records(tb.records)
        self.assertFalse(result["ok"])
        self.assertGreater(result["malformed_parent_count"], 0)
        self.assertEqual(result["malformed_parent_samples"][0]["parentUuidType"], "dict")

    def test_validator_accepts_one_way_session_lineage_as_compatibility(self):
        old_session = "17171717-1717-1717-1717-171717171717"
        current_session = "18181818-1818-1818-1818-181818181818"
        tb = fx.build_linear(old_session, turns=35)
        for record in tb.records[40:-1]:
            record["sessionId"] = current_session
        tb.records[-1]["sessionId"] = current_session
        result = ccj.validate_records(tb.records)
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(result["active_chain_session_lineage_compatibility"])
        self.assertEqual(result["active_chain_session_lineage_transition_count"], 1)
        self.assertGreater(result["active_cross_session_parent_count"], 0)

    def test_validator_accepts_attachment_only_physical_inversion(self):
        session = "19191919-1919-1919-1919-191919191919"
        root_uuid = "20202020-2020-2020-2020-202020202020"
        first_uuid = "21212121-2121-2121-2121-212121212121"
        second_uuid = "22222222-2222-2222-2222-222222222222"
        leaf_uuid = "23232323-2323-2323-2323-232323232323"
        records = [
            {"type": "user", "uuid": root_uuid, "parentUuid": None, "sessionId": session,
             "message": {"role": "user", "content": "synthetic"}},
            {"type": "attachment", "uuid": second_uuid, "parentUuid": first_uuid, "sessionId": session,
             "attachment": {"type": "synthetic"}},
            {"type": "attachment", "uuid": first_uuid, "parentUuid": root_uuid, "sessionId": session,
             "attachment": {"type": "synthetic"}},
            {"type": "assistant", "uuid": leaf_uuid, "parentUuid": second_uuid, "sessionId": session,
             "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
            {"type": "last-prompt", "leafUuid": leaf_uuid, "sessionId": session},
        ]
        result = ccj.validate_records(records)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["active_chain_attachment_compatibility_edge_count"], 1)

    def test_validate_only_on_raw_file_passes_with_warnings(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=20)
        src = fx.write_jsonl(self.tmp / "raw.jsonl", tb.records)
        result = ccj.validate_jsonl(src)
        self.assertTrue(result["ok"], result["errors"])
        self.assertIn("no compact_boundary records", result["warnings"])

    def test_validator_does_not_skip_malformed_physical_last_pointer(self):
        tb = fx.build_linear("13131313-1313-1313-1313-131313131313", turns=30)
        tb.add_raw({"type": "last-prompt", "leafUuid": 19, "sessionId": tb.session_id})
        result = ccj.validate_records(tb.records)
        self.assertFalse(result["ok"])
        self.assertEqual(result["latest_last_prompt_line"], len(tb.records))
        self.assertGreater(result["last_prompt_malformed_count"], 0)
        self.assertIsNone(result["latest_last_prompt_leaf_uuid"])

    def test_validator_requires_every_compact_summary_to_be_direct_boundary_child(self):
        tb = fx.TranscriptBuilder("14141414-1414-1414-1414-141414141414")
        summary_uuid = tb.compact_pair("official prior summary", codex=False)
        tb.records[-1]["parentUuid"] = None
        for i in range(5):
            tb.user(f"turn {i}")
            tb.assistant_text(f"answer {i}")
        tb.last_prompt()
        result = ccj.validate_records(tb.records)
        self.assertFalse(result["ok"])
        self.assertGreater(result["compact_pair_error_count"], 0)
        self.assertIn(summary_uuid, str(result["compact_pair_error_samples"]))

    def test_validation_report_uses_public_basename_not_absolute_path(self):
        tb = fx.build_linear("15151515-1515-1515-1515-151515151515", turns=20)
        src = fx.write_jsonl(self.tmp / "public-label.jsonl", tb.records)
        result = ccj.validate_jsonl(src)
        self.assertEqual(result["path"], "public-label.jsonl")

    def test_validator_rejects_blank_compact_summary_content(self):
        tb = fx.TranscriptBuilder("16161616-1616-1616-1616-161616161616")
        summary_uuid = tb.compact_pair("synthetic compact summary", codex=True)
        summary = next(record for record in tb.records if record.get("uuid") == summary_uuid)
        summary["message"]["content"] = " \n\t "
        tb.last_prompt(summary_uuid)
        result = ccj.validate_records(tb.records)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("compact" in error.lower() and ("blank" in error.lower() or "empty" in error.lower()) for error in result["errors"]),
            result["errors"],
        )


class TestTransactionalWrites(CompressBase):
    def test_atomic_write_failure_preserves_existing_destination_and_cleans_temp(self):
        destination = self.tmp / "atomic.json"
        destination.write_bytes(b"old-bytes")
        with mock.patch.object(ccj.os, "fsync", side_effect=OSError("synthetic fsync failure")):
            with self.assertRaisesRegex(OSError, "synthetic fsync failure"):
                ccj.atomic_write_bytes(destination, b"new-bytes")
        self.assertEqual(destination.read_bytes(), b"old-bytes")
        self.assertEqual(list(self.tmp.glob(".atomic.json.tmp-*")), [])

    def test_invalid_candidate_never_replaces_existing_output(self):
        destination = self.tmp / "candidate.jsonl"
        destination.write_bytes(b"known-good-existing-output")
        duplicate = "11111111-1111-1111-1111-111111111111"
        invalid_records = [
            {"type": "user", "uuid": duplicate, "parentUuid": None, "message": {"role": "user", "content": "a"}},
            {"type": "assistant", "uuid": duplicate, "parentUuid": duplicate, "message": {"role": "assistant", "content": []}},
        ]
        with self.assertRaisesRegex(ValueError, "validation failed before publication"):
            ccj.publish_validated_jsonl(destination, invalid_records)
        self.assertEqual(destination.read_bytes(), b"known-good-existing-output")
        self.assertEqual(list(self.tmp.glob(".candidate.jsonl.candidate-*")), [])

    def test_full_byte_sha256_distinguishes_bom_and_line_endings(self):
        payload = b'{"type":"x"}\n'
        variants = [payload, payload.replace(b"\n", b"\r\n"), b"\xef\xbb\xbf" + payload]
        self.assertEqual(len({ccj.sha256_hex(item) for item in variants}), 3)

    def test_token_ceiling_rejection_preserves_destination_and_writes_no_sidecars(self):
        tb = fx.build_linear("aeaeaeae-aeae-aeae-aeae-aeaeaeaeaeae", turns=120)
        src = fx.write_jsonl(self.tmp / "token-source.jsonl", tb.records)
        destination = self.tmp / "token-candidate.jsonl"
        destination.write_bytes(b"existing-destination")
        with self.assertRaisesRegex(ValueError, "above requested target"):
            ccj.compress_jsonl(
                input_path=src,
                output_path=destination,
                target_ratio=0.30,
                min_recent_records=8,
                summary_char_budget=6000,
                append_final_prompt=True,
                preserve_active_chain=True,
                deterministic_summary=True,
                target_estimated_tokens=100,
            )
        self.assertEqual(destination.read_bytes(), b"existing-destination")
        self.assertFalse(destination.with_suffix(destination.suffix + ".report.md").exists())
        self.assertFalse(destination.with_suffix(destination.suffix + ".validation.json").exists())

    def test_full_retained_structured_payload_counts_toward_token_ceiling_before_publication(self):
        tb = fx.build_linear("afafafaf-afaf-afaf-afaf-afafafafafaf", turns=140)
        tb.records.pop()
        tb.tool_call_pair()
        assistant, result = tb.records[-2:]
        thinking_payload = "theta " * 4000
        input_payload = "iota " * 4000
        result_payload = "kappa " * 4000
        assistant["message"]["content"].insert(
            0,
            {"type": "thinking", "thinking": thinking_payload, "signature": "synthetic-signature"},
        )
        assistant["message"]["content"][-1]["input"]["opaque_payload"] = input_payload
        result["message"]["content"][0]["content"] = result_payload
        result["toolUseResult"]["content"] = result_payload
        tb.last_prompt()
        src = fx.write_jsonl(self.tmp / "structured-token-source.jsonl", tb.records)
        destination = self.tmp / "structured-token-candidate.jsonl"
        target_tokens = 9000
        full_payload_estimate = sum(
            ccj.estimate_tokens(json.dumps(record, ensure_ascii=False, separators=(",", ":"))) + 12
            for record in (assistant, result)
        )
        self.assertGreater(full_payload_estimate, target_tokens)

        with self.assertRaisesRegex(ValueError, "above requested target"):
            ccj.compress_jsonl(
                input_path=src,
                output_path=destination,
                target_ratio=0.30,
                min_recent_records=6,
                summary_char_budget=4000,
                append_final_prompt=True,
                preserve_active_chain=True,
                deterministic_summary=True,
                target_estimated_tokens=target_tokens,
            )
        self.assertFalse(destination.exists())
        self.assertFalse(destination.with_suffix(destination.suffix + ".report.md").exists())
        self.assertFalse(destination.with_suffix(destination.suffix + ".validation.json").exists())

    def test_source_change_after_backup_stops_before_replace_and_retains_audit_backup(self):
        session_id = "abababab-abab-abab-abab-abababababab"
        target_tb = fx.build_linear(session_id, turns=25)
        candidate_tb = fx.build_linear(session_id, turns=30)
        target = fx.write_jsonl(self.tmp / f"{session_id}.jsonl", target_tb.records)
        candidate = fx.write_jsonl(self.tmp / "candidate.jsonl", candidate_tb.records)
        original = target.read_bytes()
        real_backup = ccj._exclusive_backup_from_bytes

        def backup_then_mutate(*args, **kwargs):
            backup = real_backup(*args, **kwargs)
            target.write_bytes(original + b"\n")
            return backup

        with mock.patch.object(ccj, "_exclusive_backup_from_bytes", side_effect=backup_then_mutate):
            with self.assertRaisesRegex(RuntimeError, "changed before replacement"):
                ccj._replace_file_after_validation(
                    candidate,
                    target,
                    expected_source_sha256=ccj.sha256_hex(original),
                )
        self.assertEqual(target.read_bytes(), original + b"\n")
        self.assertEqual(target.with_suffix(target.suffix + ".backup").read_bytes(), original)
        self.assertFalse(target.with_name(target.name + ".replace-tmp").exists())

    def test_failed_post_replace_validation_restores_original_bytes(self):
        session_id = "acacacac-acac-acac-acac-acacacacacac"
        target_tb = fx.build_linear(session_id, turns=25)
        candidate_tb = fx.build_linear(session_id, turns=30)
        target = fx.write_jsonl(self.tmp / f"{session_id}.jsonl", target_tb.records)
        candidate = fx.write_jsonl(self.tmp / "candidate.jsonl", candidate_tb.records)
        original = target.read_bytes()
        validation_sequence = [
            {"ok": True, "errors": []},
            {"ok": False, "errors": ["synthetic post-replace failure"]},
            {"ok": True, "errors": []},
        ]
        with mock.patch.object(ccj, "validate_jsonl_bytes", side_effect=validation_sequence):
            with self.assertRaisesRegex(RuntimeError, "original bytes were restored"):
                ccj._replace_file_after_validation(
                    candidate,
                    target,
                    expected_source_sha256=ccj.sha256_hex(original),
                )
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.with_suffix(target.suffix + ".backup").read_bytes(), original)

    def test_post_replace_validation_exception_restores_original_bytes(self):
        session_id = "adadadad-adad-adad-adad-adadadadadad"
        target = fx.write_jsonl(
            self.tmp / f"{session_id}.jsonl",
            fx.build_linear(session_id, turns=25).records,
        )
        candidate = fx.write_jsonl(
            self.tmp / "candidate-exception.jsonl",
            fx.build_linear(session_id, turns=30).records,
        )
        original = target.read_bytes()
        validation_sequence = [
            {"ok": True, "errors": []},
            RuntimeError("synthetic validator exception"),
            {"ok": True, "errors": []},
        ]
        with mock.patch.object(ccj, "validate_jsonl_bytes", side_effect=validation_sequence):
            with self.assertRaisesRegex(RuntimeError, "original bytes were restored"):
                ccj._replace_file_after_validation(
                    candidate,
                    target,
                    expected_source_sha256=ccj.sha256_hex(original),
                )
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.with_suffix(target.suffix + ".backup").read_bytes(), original)

    def test_capture_replace_failure_preserves_target_and_retains_audit_backup(self):
        session_id = "b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1"
        target = fx.write_jsonl(self.tmp / f"{session_id}.jsonl", fx.build_linear(session_id, turns=25).records)
        candidate = fx.write_jsonl(self.tmp / "capture-failure.jsonl", fx.build_linear(session_id, turns=30).records)
        original = target.read_bytes()
        real_replace = ccj.os.replace

        def fail_capture(source, destination):
            if pathlib.Path(source) == target and ".old-" in pathlib.Path(destination).name:
                raise OSError("synthetic capture replace failure")
            return real_replace(source, destination)

        with mock.patch.object(ccj.os, "replace", side_effect=fail_capture):
            with self.assertRaisesRegex(OSError, "capture replace failure"):
                ccj._replace_file_after_validation(candidate, target)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.with_suffix(target.suffix + ".backup").read_bytes(), original)
        self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_candidate_install_failure_restores_source_and_retains_audit_backup(self):
        session_id = "b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2"
        target = fx.write_jsonl(self.tmp / f"{session_id}.jsonl", fx.build_linear(session_id, turns=25).records)
        candidate = fx.write_jsonl(self.tmp / "install-failure.jsonl", fx.build_linear(session_id, turns=30).records)
        original = target.read_bytes()
        real_publish = ccj._publish_no_clobber

        def fail_install(source, destination):
            source_path = pathlib.Path(source)
            if ".replace-" in source_path.name and pathlib.Path(destination) == target:
                raise OSError("synthetic candidate install failure")
            return real_publish(source, destination)

        with mock.patch.object(ccj, "_publish_no_clobber", side_effect=fail_install):
            with self.assertRaisesRegex(RuntimeError, "original bytes were restored"):
                ccj._replace_file_after_validation(candidate, target)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.with_suffix(target.suffix + ".backup").read_bytes(), original)
        self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_backup_failure_cleans_stage_and_preserves_target(self):
        session_id = "b3b3b3b3-b3b3-b3b3-b3b3-b3b3b3b3b3b3"
        target = fx.write_jsonl(self.tmp / f"{session_id}.jsonl", fx.build_linear(session_id, turns=25).records)
        candidate = fx.write_jsonl(self.tmp / "backup-failure.jsonl", fx.build_linear(session_id, turns=30).records)
        original = target.read_bytes()
        with mock.patch.object(ccj, "_exclusive_backup_from_bytes", side_effect=OSError("synthetic backup failure")):
            with self.assertRaisesRegex(OSError, "synthetic backup failure"):
                ccj._replace_file_after_validation(candidate, target)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_rollback_failure_retains_numbered_backup_and_reports_both_errors(self):
        session_id = "b4b4b4b4-b4b4-b4b4-b4b4-b4b4b4b4b4b4"
        target = fx.write_jsonl(self.tmp / f"{session_id}.jsonl", fx.build_linear(session_id, turns=25).records)
        candidate = fx.write_jsonl(self.tmp / "rollback-failure.jsonl", fx.build_linear(session_id, turns=30).records)
        original = target.read_bytes()
        real_replace = ccj.os.replace

        def fail_rollback(source, destination):
            if ".old-" in pathlib.Path(source).name and pathlib.Path(destination) == target:
                raise OSError("synthetic rollback replace failure")
            return real_replace(source, destination)

        validations = [
            {"ok": True, "errors": []},
            {"ok": False, "errors": ["synthetic published validation failure"]},
        ]
        with mock.patch.object(ccj, "validate_jsonl_bytes", side_effect=validations):
            with mock.patch.object(ccj.os, "replace", side_effect=fail_rollback):
                with self.assertRaisesRegex(RuntimeError, "rollback also failed; retain backup"):
                    ccj._replace_file_after_validation(candidate, target)
        backup = target.with_suffix(target.suffix + ".backup")
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(), original)

    def test_no_internal_fields_leak_to_output(self):
        tb = fx.build_linear("11111111-1111-1111-1111-111111111111", turns=40, with_tools_every=4)
        _report, out = self.compress(tb.records, summary_char_budget=6000, min_recent_records=6, target_ratio=0.3)
        recs = fx.read_jsonl(out)
        for r in recs:
            self.assertNotIn("_line", r)
            self.assertNotIn("_mergedLines", r)


class TestSessionTools(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cjc_sess_")
        self.tmp = pathlib.Path(self._tmp.name)
        self.root = self.tmp / "projects" / "proj1"
        self.root.mkdir(parents=True)
        tb = fx.build_linear("22222222-2222-2222-2222-222222222222", turns=10)
        self.session_file = fx.write_jsonl(
            self.root / "22222222-2222-2222-2222-222222222222.jsonl", tb.records
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_find_by_filename(self):
        found = cst.find_unique_session(
            self.tmp / "projects",
            "22222222-2222-2222-2222-222222222222",
        )
        self.assertEqual(found.resolve(), self.session_file.resolve())

    def test_find_by_title_hint(self):
        with self.assertRaises(FileNotFoundError):
            cst.find_unique_session(self.tmp / "projects", "feasibility")
        found = cst.find_unique_session(self.tmp / "projects", "feasibility", scan_titles=True)
        self.assertEqual(found.resolve(), self.session_file.resolve())

    def test_numbered_backups_increment(self):
        b0 = cst.create_backup(self.session_file)
        self.assertTrue(str(b0).endswith(".jsonl.backup"))
        self.assertTrue(b0.exists())
        b1 = cst.create_backup(self.session_file)
        self.assertTrue(str(b1).endswith(".jsonl.backup1"))
        b2 = cst.create_backup(self.session_file)
        self.assertTrue(str(b2).endswith(".jsonl.backup2"))
        # Backup content matches the original byte-for-byte.
        self.assertEqual(b0.read_bytes(), self.session_file.read_bytes())

    def test_no_match_raises(self):
        with self.assertRaises(FileNotFoundError):
            cst.find_unique_session(self.tmp / "projects", "zzz-no-such-session")

    def test_main_no_match_returns_clean_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cst.main(["--root", str(self.tmp / "projects"), "--query", "zzz-no-such-session"])
        self.assertEqual(code, 1)
        self.assertIn("ERROR:", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_multi_match_raises_with_candidates(self):
        tb = fx.build_linear("33333333-3333-3333-3333-333333333333", turns=10)
        fx.write_jsonl(self.root / "33333333-3333-3333-3333-333333333333.jsonl", tb.records)
        with self.assertRaises(RuntimeError) as ctx:
            cst.find_unique_session(self.tmp / "projects", "feasibility", scan_titles=True)
        self.assertIn("multiple sessions", str(ctx.exception))

    def test_main_multi_match_returns_clean_error(self):
        tb = fx.build_linear("44444444-4444-4444-4444-444444444444", turns=10)
        fx.write_jsonl(self.root / "44444444-4444-4444-4444-444444444444.jsonl", tb.records)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cst.main(["--root", str(self.tmp / "projects"), "--query", "feasibility", "--scan-titles"])
        self.assertEqual(code, 1)
        self.assertIn("multiple sessions", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)

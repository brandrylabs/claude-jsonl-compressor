#!/usr/bin/env python3
"""Synthetic contracts for complete semantic evidence."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
import uuid

import _fixtures as fx


ccj = fx.ccj


class TestSemanticEvidenceContracts(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cjc_semantic_evidence_")
        self.tmp = pathlib.Path(self._tmp.name)
        ccj._SUMMARY_RESOURCES_CONFIGURED = False

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _build_pack(
        self,
        records,
        *,
        name: str,
        handoff_text: str | None = None,
        **overrides,
    ):
        source = fx.write_jsonl(self.tmp / f"{name}.jsonl", records)
        handoff_path = None
        if handoff_text is not None:
            handoff_path = self.tmp / f"{name}.handoff.md"
            handoff_path.write_text(handoff_text, encoding="utf-8")
        options = {
            "target_ratio": 0.12,
            "min_recent_records": 4,
            "summary_char_budget": 12000,
            "model_pack_char_budget": 50000,
        }
        options.update(overrides)
        if options.get("model_pack_char_budget") is None:
            options.pop("model_pack_char_budget")
        pack = ccj.build_model_summary_pack_for_input(
            input_path=source,
            handoff_summary_path=handoff_path,
            **options,
        )
        return pack

    def _model_summary(self, pack, *, standalone_line: str | None = None) -> str:
        anchors = []
        for group_lines in pack["required_anchor_groups"].values():
            for line in group_lines:
                if line not in anchors:
                    anchors.append(line)
        for line in pack["evidence_anchor_lines"]:
            if line not in anchors:
                anchors.append(line)
            if len(anchors) >= 16:
                break
        self.assertTrue(anchors, "synthetic pack must expose model evidence")
        refs = ", ".join(f"L{line}" for line in anchors)
        sections = [
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
        body = [
            f"<!-- {ccj.MODEL_SUMMARY_MARKER}",
            f"source_sha256: {pack['source_sha256']}",
            f"summary_source_sha256: {pack['summary_source_sha256']}",
            f"evidence_anchor_lines_digest: {pack['evidence_anchor_lines_digest']}",
            f"required_anchor_groups_digest: {pack['required_anchor_groups_digest']}",
            f"handoff_summary_digest: {pack.get('handoff_summary_sha256_prefix') or 'none'}",
            f"pack_request_digest: {pack['pack_request_digest']}",
            f"required_claim_sources_digest: {pack['required_claim_sources_digest']}",
            "-->",
            "# Model-Assisted Semantic Compression Summary",
        ]
        for index, heading in enumerate(sections):
            body.extend(
                [
                    "",
                    f"## {heading}",
                    (
                        f"Synthetic semantic statement {index} is grounded only in the displayed "
                        f"model evidence and preserves chronology, decisions, reasons, constraints, "
                        f"and uncertainty without adding fixture facts. Evidence: {refs}."
                    ),
                ]
            )
            if standalone_line is not None and heading == "Risks, Unknowns, and Follow-Ups":
                body.append(standalone_line)
            if heading == "Evidence and Source Anchors":
                body.extend(["", "### Mandatory Evidence Coverage"])
                for raw_line, source in sorted(
                    (pack.get("required_claim_sources") or {}).items(),
                    key=lambda item: int(item[0]),
                ):
                    excerpt = str(source).strip()[:160]
                    body.append(
                        f"- L{int(raw_line)} support_text_json={json.dumps(excerpt, ensure_ascii=False)} disposition=covered"
                    )
        return "\n".join(body) + "\n"

    def _validate_summary(self, pack, text: str, total_records: int):
        return ccj.validate_model_summary_text(
            text=text,
            source_digest=pack["source_sha256"],
            omitted_digest=pack["summary_source_sha256"],
            total_records=total_records,
            omitted_indexes=[line - 1 for line in pack["summary_source_lines"]],
            allowed_anchor_lines=pack["evidence_anchor_lines"],
            expected_evidence_anchor_lines_digest=pack["evidence_anchor_lines_digest"],
            required_anchor_groups=pack["required_anchor_groups"],
            expected_required_anchor_groups_digest=pack["required_anchor_groups_digest"],
            expected_handoff_summary_digest=pack.get("handoff_summary_sha256_prefix"),
            allowed_handoff_anchor_count=max(
                ccj.model_pack_handoff_anchor_lines(pack["text"]),
                default=0,
            ),
            expected_pack_request_digest=pack["pack_request_digest"],
            required_claim_sources=pack["required_claim_sources"],
            expected_required_claim_sources_digest=pack["required_claim_sources_digest"],
        )

    @staticmethod
    def _append_noisy_tail(builder: fx.TranscriptBuilder, count: int = 72) -> None:
        for index in range(count):
            builder.assistant_text(f"\ufffd synthetic transport-noise record {index}")

    @staticmethod
    def _ledger_failures(pack, expected):
        failures = []
        required_groups = pack["required_anchor_groups"]
        for line, text in expected:
            if line not in pack["summary_source_lines"]:
                failures.append(f"L{line} was not selected for summarization")
                continue
            if line not in pack["evidence_anchor_lines"]:
                failures.append(f"L{line} is absent from model evidence")
            if text not in pack["text"]:
                failures.append(f"L{line} is not present completely in the model pack")
            if not any(list(group_lines) == [line] for group_lines in required_groups.values()):
                failures.append(f"L{line} has no individual required anchor group")
        return failures

    def test_nonempty_handoff_requires_temporal_h_anchor_coverage(self):
        tb = fx.build_linear("10101010-1010-1010-1010-101010101010", turns=48)
        handoff = "\n".join(
            [
                "Initial synthetic handoff state.",
                "Middle synthetic handoff decision.",
                "Later synthetic handoff supersession.",
                "Final synthetic handoff instruction.",
            ]
        )
        pack = self._build_pack(tb.records, name="handoff-required", handoff_text=handoff)
        summary_without_h_anchors = self._model_summary(pack)
        result = self._validate_summary(pack, summary_without_h_anchors, len(tb.records))

        self.assertFalse(
            result["ok"],
            "a nonempty handoff was accepted even though the summary cited no required temporal H anchors",
        )

    def test_long_human_tail_instruction_is_complete_and_individually_required(self):
        tb = fx.TranscriptBuilder("20202020-2020-2020-2020-202020202020")
        tail_instruction = (
            "TAIL_HARD_INSTRUCTION: Preserve this exact final instruction without clipping, "
            "and require its source anchor in the model summary."
        )
        message = ("Synthetic lead-in context remains intentionally repetitive. " * 90) + tail_instruction
        self.assertGreater(len(message), 4000)
        tb.user(message)
        source_line = len(tb.records)
        self._append_noisy_tail(tb)
        tb.last_prompt()

        pack = self._build_pack(tb.records, name="long-human-tail")
        failures = self._ledger_failures(pack, [(source_line, message)])
        self.assertEqual([], failures, "; ".join(failures))

    def test_each_semantic_message_is_complete_and_individually_required(self):
        tb = fx.TranscriptBuilder("30303030-3030-3030-3030-303030303030")
        expected = []

        human_text = "USER_LEDGER_ALPHA requires the complete synthetic chronology and exact constraint wording."
        tb.user(human_text)
        expected.append((len(tb.records), human_text))

        long_assistant_text = (
            "ASSISTANT_LEDGER_BETA concludes that the amber route supersedes the earlier route "
            "because the checked synthetic evidence resolves the conflict. "
            + ("The rationale and rejected option remain semantic evidence. " * 24)
            + "ASSISTANT_LEDGER_BETA_FINAL_CLAUSE"
        )
        tb.assistant_text(long_assistant_text)
        expected.append((len(tb.records), long_assistant_text))

        greek_supersession = "Η νεότερη διαδρομή αντικαθιστά την παλιά επιλογή."
        tb.assistant_text(greek_supersession)
        expected.append((len(tb.records), greek_supersession))

        final_assistant_text = (
            "ASSISTANT_LEDGER_GAMMA records the final synthetic decision because its evidence was checked."
        )
        tb.assistant_text(final_assistant_text)
        expected.append((len(tb.records), final_assistant_text))

        self._append_noisy_tail(tb)
        tb.last_prompt()
        pack = self._build_pack(tb.records, name="complete-semantic-ledger")

        failures = self._ledger_failures(pack, expected)
        self.assertEqual([], failures, "; ".join(failures))

    def test_assistant_thinking_blocks_in_multiple_languages_are_required_evidence(self):
        tb = fx.TranscriptBuilder("40404040-4040-4040-4040-404040404040")
        expected = []
        thinking_texts = [
            "THINKING_EN: The synthetic evidence changes the final decision and supersedes the old route.",
            "思考_CN：综合虚构证据后，最终决定取代旧方案。",
            "ΣΚΕΨΗ_EL: Τα συνθετικά στοιχεία αλλάζουν την τελική απόφαση.",
        ]
        for thinking_text in thinking_texts:
            tb.assistant_text("temporary synthetic text")
            tb.records[-1]["message"]["content"] = [
                {"type": "thinking", "thinking": thinking_text},
            ]
            expected.append((len(tb.records), thinking_text))
        tb.assistant_text("Final visible synthetic decision because checked evidence supersedes the old route.")
        self._append_noisy_tail(tb)
        tb.last_prompt()

        pack = self._build_pack(tb.records, name="multilingual-thinking")
        failures = self._ledger_failures(pack, expected)
        self.assertEqual([], failures, "; ".join(failures))

    def test_unknown_exemption_requires_exact_whole_line_case_and_punctuation(self):
        tb = fx.build_linear("50505050-5050-5050-5050-505050505050", turns=48)
        pack = self._build_pack(tb.records, name="unknown-exemption")

        exact = self._model_summary(pack, standalone_line="Unknown from provided anchors.")
        exact_result = self._validate_summary(pack, exact, len(tb.records))
        self.assertTrue(exact_result["ok"], exact_result["errors"])

        variants = {
            "bullet": "- Unknown from provided anchors.",
            "case": "unknown from provided anchors.",
            "punctuation": "Unknown from provided anchors",
        }
        for label, variant in variants.items():
            with self.subTest(label=label):
                candidate = self._model_summary(pack, standalone_line=variant)
                result = self._validate_summary(pack, candidate, len(tb.records))
                self.assertFalse(result["ok"], f"variant was incorrectly exempt: {variant!r}")

    def test_model_pack_schema_marker_is_v11(self):
        tb = fx.build_linear("60606060-6060-6060-6060-606060606060", turns=24)
        pack = self._build_pack(tb.records, name="schema-v11")
        failures = []
        if ccj.MODEL_PACK_SCHEMA_VERSION != 11:
            failures.append(f"schema constant is {ccj.MODEL_PACK_SCHEMA_VERSION}, expected 11")
        if not pack["text"].startswith("# v11 Model-Assisted Summary Pack"):
            failures.append("model-pack heading is not v11")
        if "claude-jsonl-compressor:model-summary v11" not in pack["text"]:
            failures.append("model-summary metadata marker is not v11")
        self.assertEqual([], failures, "; ".join(failures))

    def test_default_model_pack_budget_contains_complete_required_ledger(self):
        tb = fx.TranscriptBuilder("70707070-7070-7070-7070-707070707070")
        for index in range(240):
            marker = f"LEDGER_ENTRY_{index:03d}"
            payload = (
                f"{marker}: synthetic semantic decision {index} must remain complete because its checked "
                f"evidence supersedes the previous option. " + (f"detail-{index} " * 48)
            )
            if index % 2:
                tb.assistant_text(payload)
            else:
                tb.user(payload)
        tb.last_prompt()

        pack = self._build_pack(
            tb.records,
            name="default-budget-ledger",
            summary_char_budget=4000,
            model_pack_char_budget=None,
        )
        summarized = set(pack["summary_source_lines"])
        visible = set(pack["evidence_anchor_lines"])
        individually_required = {
            line
            for group_lines in pack["required_anchor_groups"].values()
            if len(group_lines) == 1
            for line in group_lines
        }
        failures = []
        if visible != summarized:
            failures.append(
                f"default pack omitted {len(summarized - visible)} of {len(summarized)} summarized ledger records"
            )
        if not summarized.issubset(individually_required):
            failures.append(
                f"default pack left {len(summarized - individually_required)} summarized ledger records optional"
            )
        if pack["model_pack_estimated_token_budget"] != ccj.DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET:
            failures.append("default model-pack token budget was not reported exactly")
        if pack["pack_estimated_tokens"] > ccj.DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET:
            failures.append(
                f"default pack estimate {pack['pack_estimated_tokens']} exceeds "
                f"{ccj.DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET}"
            )
        self.assertEqual([], failures, "; ".join(failures))

    def test_default_token_budget_trims_only_optional_dense_evidence(self):
        tb = fx.TranscriptBuilder("80808080-8080-8080-8080-808080808080")
        mandatory_lines = []
        for index in range(8):
            human_text = f"HUMAN_REQUIRED_{index}: preserve this complete synthetic constraint and chronology."
            tb.user(human_text)
            mandatory_lines.append((len(tb.records), human_text))
            assistant_text = (
                f"ASSISTANT_REQUIRED_{index}: the synthetic decision follows because checked evidence "
                "supersedes the previous option."
            )
            tb.assistant_text(assistant_text)
            mandatory_lines.append((len(tb.records), assistant_text))

        optional_lines = []
        dense_payload = "证据密集但属于可选系统错误记录" * 70
        for index in range(320):
            rec = tb._base(
                "system",
                uuid=str(uuid.uuid4()),
                subtype="api_error",
                error=f"OPTIONAL_DENSE_{index:03d} {dense_payload}",
            )
            tb.add_raw(rec)
            optional_lines.append(len(tb.records))
        tb.last_prompt()

        pack = self._build_pack(
            tb.records,
            name="default-token-budget-optional-trim",
            summary_char_budget=4000,
            model_pack_char_budget=None,
        )
        failures = self._ledger_failures(pack, mandatory_lines)
        summarized_optional = set(optional_lines).intersection(pack["summary_source_lines"])
        visible_optional = summarized_optional.intersection(pack["evidence_anchor_lines"])
        if not pack["evidence_truncated"]:
            failures.append("dense optional evidence did not report truncation")
        if not summarized_optional:
            failures.append("fixture did not place optional system records in the summarized segment")
        if len(visible_optional) >= len(summarized_optional):
            failures.append("token budget did not trim any optional dense evidence")
        if pack["pack_estimated_tokens"] > ccj.DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET:
            failures.append(
                f"pack estimate {pack['pack_estimated_tokens']} exceeds the default token ceiling"
            )
        if pack["pack_chars"] > 500000:
            failures.append(f"pack chars {pack['pack_chars']} exceed the independent character ceiling")
        self.assertEqual([], failures, "; ".join(failures))

    def test_required_semantic_ledger_over_token_budget_stops(self):
        tb = fx.TranscriptBuilder("90909090-9090-9090-9090-909090909090")
        for index in range(36):
            tb.user(
                f"REQUIRED_DENSE_{index:03d}: "
                + ("这是一条必须完整保留且不得抽样截断的合成用户研究约束。" * 42)
            )
        tb.last_prompt()

        with self.assertRaisesRegex(
            ValueError,
            r"model evidence token budget|model-pack-estimated-token-budget",
        ):
            self._build_pack(
                tb.records,
                name="required-ledger-token-overflow",
                summary_char_budget=4000,
                model_pack_char_budget=None,
                model_pack_estimated_token_budget=10000,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

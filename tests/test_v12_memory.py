"""Synthetic migration and model-to-text protocol tests."""
import hashlib
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import compress_claude_jsonl as legacy
from v12_memory import END, prepare_prior, validate_draft, reassemble_prior


def frame(*texts, current="Current note"):
    items = [dict(sourceLine=n, uuid="sample", chars=len(t), sha256Prefix=legacy.stable_digest(t), text=t)
             for n, t in enumerate(texts, 1)]
    return legacy.format_verbatim_prior_summary_block(items) + "\n\n# Current Compression Layer\n\n" + current


def old_layer():
    meta = [f"{key}: " + "a" * (16 if key in {"evidence_anchor_lines_digest", "required_anchor_groups_digest"} else 64) for key in (
        "source_sha256", "summary_source_sha256", "evidence_anchor_lines_digest", "required_anchor_groups_digest",
        "pack_request_digest", "required_claim_sources_digest")]
    sections = ["Current State", "Timeline and Supersessions", "Decisions and Reasons",
                "Assistant Research Decisions and Rationales", "Rejected or Superseded Alternatives",
                "Evidence and Source Anchors", "User Wording and Constraints", "Risks, Unknowns, and Follow-Ups",
                "Recent Raw Context Boundary"]
    body = "<!-- claude-jsonl-compressor:model-summary v11\n" + "\n".join(meta + ["handoff_summary_digest: none", "-->"])
    body += "\n# Model-Assisted Semantic Compression Summary"
    for heading in sections:
        body += "\n\n## " + heading + "\n\n"
        body += "The trial stays local. [@L8]"
        if heading == sections[5]:
            body += '\n### Mandatory Evidence Coverage\n- L8 support_text_json="Appendix B remains unread." disposition=covered'
    return legacy.compose_model_assisted_summary(body, "- L7: Retain the blue seal.\n- L8: Retain the blue seal.", 4000)


def draft(items, heading="Current State"):
    return "## " + heading + "\n" + "\n".join(items) + "\n" + END


class Migration(unittest.TestCase):
    def test_early_writer_stripped_block_before_adding_its_separator(self):
        marker = "\n\n# Current Compression Layer\n\n"
        for ending in ("\n", "\n\n"):
            old = "first generation" + ending
            head, current = frame(old).rsplit(marker, 1)
            source = head.strip() + marker + current
            result = prepare_prior(source, "resynthesize")
            self.assertIn(old, result["evidence"])
            self.assertEqual(reassemble_prior(result["audit"]), source)
            with self.assertRaises(ValueError):
                prepare_prior(source.replace("first generation", "worse generation"), "resynthesize")

    def test_nested_round_trip_and_whitespace(self):
        odd = " \r\n## Prior Compact Summary 9\n# Current Compression Layer\n好きです  \n "
        raw = frame(frame(" \n\t", odd, current=old_layer()), "消息🥭\r\n", current="尾")
        result = prepare_prior(raw, "clean-and-merge")
        self.assertEqual(reassemble_prior(result["audit"]), raw)
        self.assertEqual(result["audit"]["roundTripSha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertIn(odd, result["residuals"].values())
        self.assertNotIn(odd, result["evidence"])
        self.assertNotIn("sha256_prefix:", result["evidence"])
        self.assertIn("Appendix B remains unread.", result["residuals"].values())
        self.assertEqual(list(result["residuals"].values()).count("Retain the blue seal."), 1)
        self.assertNotIn("Mandatory Evidence Coverage", result["evidence"])

    def test_hash_and_boundaries_fail_in_all_policies(self):
        raw = frame("twelve", "second")
        for broken in (raw.replace("twelve", "twolve"), raw.replace("chars: 6", "chars: 5"),
                       raw.replace("Summary 2\n", "Summary 3\n"), raw.replace("# Current Compression Layer", "# Broken")):
            for policy in ("verbatim-locked", "clean-and-merge", "resynthesize"):
                with self.subTest(policy=policy), self.assertRaises(ValueError):
                    prepare_prior(broken, policy)

    def test_restore_part_digest(self):
        audit = prepare_prior(frame("red fox"), "clean-and-merge")["audit"]
        audit["spans"][0]["text"] += "!"
        with self.assertRaises(ValueError):
            reassemble_prior(audit)

    def test_lock_and_unknown(self):
        for text in ("\r\n \t", "未知记忆\n## Prior Compact Summary 1\n  ", "## Current State\n\n- A pending review."):
            p = prepare_prior(text, "verbatim-locked")
            self.assertEqual(p["locked"], text)
            self.assertEqual(p["evidence"], "")
            self.assertEqual(reassemble_prior(p["audit"]), text)
        source = "notes\n### Mandatory Evidence Coverage\n- arbitrary input\r\n"
        self.assertEqual(prepare_prior(source, "resynthesize")["evidence"], source)

    def test_group_residual_range_checks_every_member(self):
        residuals = {"P1R1":"Amber wax.", "P1R2":"Amber wax."}
        item = draft(["- Amber wax. [P1R1-P1R2]", "> P1R1-P1R2 duplicate | Amber wax."])
        checked = validate_draft(item, {}, residuals)
        self.assertEqual(set(checked["audit"]["residuals"]), set(residuals))
        for data, bad in ((dict(residuals, P1R2="Indigo wax."), item),
                          (residuals, item.replace("P1R1-P1R2", "P1R1-P2R2")),
                          (residuals, item.replace("P1R1-P1R2", "P1R1-P1R9000000000"))):
            with self.assertRaises(ValueError):
                validate_draft(bad, {}, data)

    def test_three_unframed_rounds_preserve_correction_and_no_new_shell(self):
        text = "The sample gate uses 8 ms."
        for changed in ("The sample gate uses 7 ms now.", "The sample gate uses 5 ms now.", "The sample gate uses 3 ms now."):
            old = prepare_prior(text, "resynthesize")
            line = text.splitlines()[-1].removeprefix("- ")
            out = validate_draft(draft([f"- {changed} [E2]", f"- Previously: {line} [E1]", f"> E1 | {line}"]),
                                 {"E1": old["evidence"], "E2": changed}, {})
            text = out["body"]
            self.assertIn(changed, text)
            self.assertNotIn("<!--", text)
            self.assertNotIn("[E", text)


class Draft(unittest.TestCase):
    def test_grouped_repeated_sources_and_real_residual_map(self):
        t = draft(["- The test uses a blue seal. [E7.1-E7.3,P2R1]",
                   "> E7.1-E7.3 | blue seal", "> P2R1 merged | blue seal"])
        result = validate_draft(t, {f"E7.{i}": "Check the blue seal" for i in range(1, 4)}, {"P2R1": "Keep the blue seal"})
        self.assertEqual(result["body"], "## Current State\n\n- The test uses a blue seal.")
        self.assertEqual(result["audit"]["residuals"]["P2R1"]["disposition"], "merged")
        self.assertEqual(result["audit"]["residuals"]["P2R1"]["claim"], "The test uses a blue seal.")

    def test_map_language_and_status(self):
        for heading in ("当前状态", "現在の状態"):
            self.assertIn("校验", validate_draft(draft(["- 校验成功。 [E1]"], heading), {"E1": "校验成功。"}, {})["body"])
        t = draft(["- Appendix B remains unread. [E1]"], "Source Registry")
        self.assertTrue(validate_draft(t, {"E1": "Appendix B remains unread."}, {}, final=False)["audit"]["verify"])
        with self.assertRaises(ValueError):
            validate_draft(t, {"E1": "Appendix B remains unread."}, {})

    def test_fail_closed_protocol(self):
        s = {"E1": "Keep the seal intact.", "E2": "Appendix B remains unread."}
        for lines, residuals in [
            (["- Keep the seal intact. [E1]"], {}),
            (["- Keep the seal intact. [E1-E3]"], {}),
            (["- Keep the seal intact. [E1-E2]"], {}),
            (["- Keep the seal intact. [E1]", "- Appendix B remains unread. [E2]", "> E2 | missing quote"], {}),
            (["- Keep the seal intact. [E1]", "- Appendix B remains unread. [E2]"], {"R1": "Blue seal still needed."}),
            (["- Keep the seal intact. [E1]", "- Covered. [R1,E2]", "> R1 merged | blue seal", "> E2 | Appendix B"], {"R1":"blue seal"}),
            (["- Keep the seal intact. [E1]", "- Engines use fuel. [E2]", "> E2 | Appendix B remains unread."], {}),
        ]:
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                validate_draft(draft(lines), s, residuals)
        for mark in ("", END + "\nextra", END + "\n" + END):
            with self.assertRaises(ValueError):
                validate_draft(draft(["- Keep the seal intact. [E1]"]).replace(END, mark), {"E1": s["E1"]}, {})

    def test_numeric_units_read_boundary_and_polarity(self):
        for claim, support in [("The gate allows 9 ms.", "The gate allows 8 ms."),
                               ("The gate allows 8 s.", "The gate allows 8 ms."),
                               ("Access is permitted.", "Access is not permitted."),
                               ("Appendix B was read.", "Appendix B remains unread."),
                               ("已读附件。", "附件尚未读取。"),
                               ("公開できます。", "公開できない。")]:
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                validate_draft(draft([f"- {claim} [E1]", f"> E1 | {support}"]), {"E1":support}, {})

    def test_negative_prefix_cannot_be_cropped_off(self):
        with self.assertRaises(ValueError):
            validate_draft(draft(["- Release is authorized. [E1]", "> E1 | authorized."]),
                           {"E1":"The release is not authorized."}, {})

    def test_authorization_and_document_read_extent_can_be_quoted(self):
        s = "用户仅授权翻阅甲卷，乙卷尚未读取。"
        out = validate_draft(draft([f"- {s} [E1]"], "当前状态"), {"E1": s}, {})
        self.assertIn(s, out["body"])

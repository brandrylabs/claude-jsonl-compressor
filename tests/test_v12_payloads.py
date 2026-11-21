"""Regression checks for literal evidence and opaque media in both compression entries."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _fixtures as fx
import test_compressor as legacy
from test_v12_workflow import command
import v12_evidence as evidence


class PayloadProjection(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.tr = fx.TranscriptBuilder("d39950a4-f47e-4f00-bd36-f7c8d5f72d91")
        self.tr.user("Compare the sample register.")
        self.tr.tool_call_pair("SurveyBook", "register")
        self.call, self.result = self.tr.records[-2:]
        self.block = self.result["message"]["content"][0]
        self.result["toolUseResult"] = {"finding": "The companion finding survives."}
        self.tr.assistant_text("Register lookup complete.")
        for i in range(16):
            self.tr.user(f"Check sample tray {i}.")
            self.tr.assistant_text(f"Sample tray {i} is ready.")
        self.tr.last_prompt()
        self.source = self.root / "sample.jsonl"
        self.run = self.root / "run"

    def prepare(self, *args):
        fx.write_jsonl(self.source, self.tr.records)
        return command("prepare", "--input", self.source, "--run", self.run,
                       "--target-ratio", ".05", "--min-recent-records", 2, *args)

    def request(self):
        return "\n".join(path.read_bytes().decode("utf-8") for path in sorted(self.run.glob("map-*.md")))

    def test_business_metadata_and_legacy_both_passes(self):
        catalog = {"type": "document", "data": "Routing clause is active."}
        self.call["message"]["content"][1]["input"]["entry"] = catalog
        self.result["toolUseResult"]["catalog"] = {"mimeType": "image/png", "note": "Caption still under review."}
        self.block["content"] = [{"type": "document", "source": {"type": "text", "media_type": "text/plain",
                                                                  "data": "Draft line in the register."}}]
        self.prepare()
        self.assertIn(catalog["data"], self.request())
        options = dict(target_ratio=.05, min_recent_records=2, tool_evidence="full", summary_char_budget=30000)
        pack = fx.ccj.build_model_summary_pack_for_input(self.source, **options)
        for term in (catalog["data"], "Caption still under review.", "Draft line in the register."):
            self.assertIn(term, pack["text"])
        summary = self.root / "summary.md"
        summary.write_text(legacy.TestModelAssistedSummary()._model_summary_from_pack(pack), encoding="utf-8")
        out = self.root / "candidate.jsonl"
        fx.ccj.compress_jsonl(self.source, out, model_summary_path=summary, **options)
        self.assertTrue(fx.ccj.validate_jsonl(out, contract="fresh-candidate")["ok"])

    def test_nested_media_redacts_bytes_but_keeps_siblings(self):
        marker = "VEVTVF9PVkVSTEFZX0ZPUl9WSVNJQkxFX0NPUElFUw=="
        image = {"type": "image", "source": {"type": "base64", "data": marker, "caption": "Printed edge."}}
        self.block["content"] = [{"type": "text", "text": "The left edge is straight."}, image,
                                 {"type":"file", "file_id":"REMOTE-UNREAD", "title":"Reverse view."}]
        self.result["toolUseResult"].update(type="document", preview={"encoded": {"encoding":"base64", "data":marker}},
                                           credit="Written in pencil.")
        with self.assertRaisesRegex(ValueError, "unread image"):
            self.prepare()
        self.assertFalse(self.run.exists())
        self.prepare("--media", "archive")
        request = self.request()
        support = json.loads((self.run / "map-001.sources.json").read_bytes())
        for text in (request, json.dumps(support, ensure_ascii=False)):
            for keep in ("Printed edge.", "The left edge is straight.", "Reverse view.",
                         "The companion finding survives.", "Written in pencil."):
                self.assertIn(keep, text)
            self.assertNotIn(marker, text)
            self.assertNotIn("REMOTE-UNREAD", text)
            self.assertIn("unread", text)
        audit = json.loads((self.run / "source-audit.json").read_bytes())["ledger"]
        self.assertEqual({i["field"] for i in audit if i["status"] == "unsupported_blocked"}, {
            "message.content[0].content[1].source.data", "message.content[0].content[2].file_id",
            "toolUseResult.preview.encoded.data"})

    def test_direct_media_references_in_auxiliary_and_attachment_fields(self):
        self.result["toolUseResult"]["carrier"] = {"type": "file", "file_id": "outside-sheet",
                                                 "text": "The receipt needs a second signature."}
        self.result["toolUseResult"]["preview"] = {"type": "image", "url": "https://example.invalid/plate",
                                                 "caption": "Copper plate."}
        self.result["attachment"] = {"type": "document", "uri": "scheme:leaf-file",
                                     "title": "Terms", "text": "Translation is permitted."}
        self.result["toolUseResult"]["catalog"] = {"type": "entry", "url": "scheme:catalogue",
                                                  "text": "See the catalogue."}
        with self.assertRaisesRegex(ValueError, "unread"):
            self.prepare()
        with self.assertRaisesRegex(ValueError, "unsupported media"):
            fx.ccj.build_model_summary_pack_for_input(self.source, target_ratio=.05, min_recent_records=2,
                                                     tool_evidence="full", summary_char_budget=30000)
        self.prepare("--media", "archive")
        request = self.request()
        for text in ("The receipt needs a second signature.", "Copper plate.", "Translation is permitted.",
                     "scheme:catalogue", "The companion finding survives."):
            self.assertIn(text, request)
        for target in ("outside-sheet", "https://example.invalid/plate", "scheme:leaf-file"):
            self.assertNotIn(target, request)
        ledger = json.loads((self.run / "source-audit.json").read_bytes())["ledger"]
        self.assertEqual({entry["field"] for entry in ledger if entry["status"] == "unsupported_blocked"},
                         {"toolUseResult.carrier.file_id", "toolUseResult.preview.url", "attachment.uri"})

    def test_explicit_encoding_stops_both_legacy_passes(self):
        self.result["toolUseResult"]["carrier"] = {"encoding":"base64", "data":"VEVTVF9PVkVSTEFZ"}
        fx.write_jsonl(self.source, self.tr.records)
        settings = dict(target_ratio=.05, min_recent_records=2, summary_char_budget=30000, tool_evidence="full")
        with self.assertRaisesRegex(ValueError, "unsupported media"):
            fx.ccj.build_model_summary_pack_for_input(self.source, **settings)
        out = self.root / "candidate.jsonl"
        with self.assertRaisesRegex(ValueError, "unsupported media"):
            fx.ccj.compress_jsonl(self.source, out, deterministic_summary=True, **settings)
        self.assertFalse(out.exists())

    def test_literal_short_reuse_is_local_and_bound_to_each_occurrence(self):
        repeated = ('Keep the "leaf" at Q\\sample.\nThe measured edge remains stable. ' * 3).strip()
        different = repeated[:-1] + "!"
        self.block["content"] = repeated
        self.result["toolUseResult"].update({"a/b":repeated, "near":different})
        self.call["message"]["content"][1]["input"]["firstValue"] = repeated
        self.prepare("--excerpts", "0")
        request = self.request()
        self.assertEqual(request.count(repeated), 2)  # one display in each of two source records
        self.assertEqual(request.count(different), 1)
        self.assertIn("sameRecordField: /fields/content/0/content", request)
        support = json.loads((self.run / "map-001.sources.json").read_bytes())["sources"]
        self.assertTrue(any(s.count(repeated) == 3 and different in s for s in support.values()))
        audit = json.loads((self.run / "source-audit.json").read_bytes())["ledger"]
        alias = next(item for item in audit if item["status"] == "dedup_aliased")
        self.assertEqual((alias["field"], alias["sourceField"]), ("/fields/toolUseResult/a~1b", "/fields/content/0/content"))

    def test_long_dictionary_digest_conflicts_fail_closed(self):
        with mock.patch.object(evidence, "digest", return_value="fixed"):
            with self.assertRaisesRegex(ValueError, "same evidence digest"):
                evidence.render_field(["x" * 503, "y" * 503], {}, [], {}, [])

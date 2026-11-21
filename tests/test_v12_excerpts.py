"""Synthetic tests for private excerpt catalogs, writer choices and hard budgets."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v12_excerpts as ex


class SourceExcerpts(unittest.TestCase):
    def setUp(self):
        self.sources = {"E1": "line: 7\r\nrole: user\r\norigin: tool_result\r\n"
                        "time: 2025-03-01\r\nfields: content: type: tool_result\r\n"
                        "content:     41→## Workshop instruction\r\n"
                        "    42→  Heat the sample.  \r\n    43→Wait until clear.\r\n"
                        "    44→Escalate cloudy samples.\r\ntoolUseResult: exitCode: 0\r\n",
                        "E2": "Use the glass tray until the lab signs off."}
        self.catalog = ex.catalog_request(self.sources, 8)
        self.key = next(iter(self.catalog))

    def test_literal_source_numbers_whitespace_and_narrow_selection(self):
        rec = self.catalog[self.key]
        self.assertEqual((rec["firstLine"], rec["lastLine"], rec["title"]), (42, 44, "Workshop instruction"))
        self.assertIn("#42-44", ex.catalog_index(self.catalog))
        clean, choice = ex.parse_selections(f"Memo\r\n@keep {self.key} #42-43 | current | "
                                            "Manual v3, sample checks\r\n<!-- end-memory -->", self.catalog)
        self.assertEqual(clean, "Memo\r\n<!-- end-memory -->")
        ex.verify_selected(choice, self.sources)
        text = ex.render_selected(choice, 1000)
        self.assertIn("  Heat the sample.  \r\nWait until clear.", text)
        self.assertIn("lines 42–43", text)
        self.assertNotIn("Escalate", text)
        self.assertNotIn("exitCode", text)
        self.assertNotIn("→", text)
        self.assertNotIn(self.key, text)
        self.assertEqual(text, ex.render_selected(choice, len(text)))
        with self.assertRaisesRegex(ValueError, "Reselect"):
            ex.render_selected(choice, len(text) - 1)

    def test_multilevel_disposition_and_budget(self):
        first = f"@keep {self.key} | current | Workshop manual v1, March."
        _, picked = ex.parse_selections(first, self.catalog)
        frozen = json.loads(json.dumps(picked))
        catalog = ex.carry_catalog(frozen)
        _, no_picks = ex.parse_selections("Memo", catalog)
        self.assertEqual(ex.render_selected(no_picks, 0), "")
        _, same = ex.parse_selections("@keep " + self.key, catalog)
        self.assertEqual(same, frozen)
        _, changed = ex.parse_selections(f"@keep {self.key} #44 | superseded | Manual v1, before sign-off.",
                                         ex.carry_catalog(same))
        self.assertIn("Superseded", ex.render_selected(changed, 400))
        self.assertNotIn("Current", ex.render_selected(changed, 400))
        ex.verify_selected(changed, self.sources)
        self.assertEqual(same, frozen)

    def test_shared_heading_preserves_each_range_status_and_gap(self):
        source = {"E1": "line: 8\nrole: user\ntoolUseResult: file: filePath: /lab/book.txt\n"
                        "content: ## Preparation\nCut the amber tile.\n\nDip the tile in oil.\n"
                        "Keep the spare dry.\nnumLines: 5\nstartLine: 11\ntotalLines: 80"}
        catalog = ex.catalog_request(source, 10)
        one, two = catalog
        caption = " | current | Workshop manual edition A for the amber glass exhibit"
        _, selected = ex.parse_selections(f"@keep {one}{caption}\n@keep {two}{caption}", catalog)
        text = ex.render_selected(selected, 1000)
        self.assertEqual(text.count("Workshop manual edition A"), 1)
        self.assertIn("lines 12–12", text)
        self.assertIn("lines 14–15", text)
        self.assertNotIn("lines 12–15", text)
        parts = ex.parsed_passages(text)
        self.assertEqual("".join(raw for rule, raw, value in parts), text)
        values = [value for rule, raw, value in parts if rule == "v12-excerpt"]
        self.assertTrue(all("Workshop manual edition A" in item for item in values))
        self.assertTrue(all(item.endswith(rec["text"]) for rec, item in zip(selected, values)))
        selected[1]["disposition"] = "superseded"
        self.assertEqual(ex.render_selected(selected, 1000).count("Workshop manual edition A"), 2)

    def test_bad_choice_and_tampering(self):
        valid = f"@keep {self.key} | history | First laboratory meeting."
        for draft in ("@keep X00000000000000", "@keep " + self.key, valid + "\n" + valid,
                      valid.replace("history", "okay"), valid.replace(" |", " #40-42 |", 1),
                      "<!-- end-memory -->\n" + valid, valid.replace("First laboratory meeting.", "token=secret"),
                      valid.replace("First laboratory meeting.", "E1")):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                ex.parse_selections(draft, self.catalog)
        choices = ex.parse_selections(valid, self.catalog)[1]
        for field, value in [("text", "new"), ("firstLine", 43), ("title", "revised"), ("id", "X")]:
            changed = copy.deepcopy(choices)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                ex.verify_selected(changed, self.sources)
        with self.assertRaises(ValueError):
            ex.verify_selected(choices, dict(self.sources, E1=self.sources["E1"] + " "))

    def test_filter_sensitive_machine_progress_and_reminder(self):
        source = ("line: 5\nrole: user\norigin: normal\nfields: content: Do the sampling first.\n"
                  "API_KEY=syntheticvalue\nAuthorization: Bearer syntheticvalue\n" + "A" * 280 + "\n"
                  "password: |\n  shortvalue\n<system-reminder>\nInternal flotsam\n</system-reminder>\n"
                  "100% complete\n-----BEGIN " "PRIVATE KEY-----\nshortvalue\n-----END " "PRIVATE KEY-----\n"
                  "schema\\nthis\\nthat\n" + "0" * 64 + "\nRecord the package arrival.")
        catalog = ex.catalog_request({"E1": source}, 50)
        self.assertEqual([rec["text"] for rec in catalog.values()],
                         ["Do the sampling first.", "Record the package arrival."])

    def test_distribution_does_not_merge_event_history(self):
        same = "1→## Policy\n2→Delay until inspected."
        source = ("line: 3\nrole: user\nfields: content: " + same + "\nline: 4\nrole: assistant\n"
                  "fields: content: " + same)
        catalog = ex.catalog_request({"E1": source, "E2": same}, 5)
        self.assertEqual([rec["eventLine"] for rec in catalog.values()], [3, 4, None])
        catalog = ex.catalog_request({"E1": "# One\nAlpha\n\n# Two\nBeta\n\n# Three\nGamma",
                                      "E2": "Gamma"}, 3)
        self.assertEqual([rec["text"] for rec in catalog.values()], ["Alpha", "Gamma", "Gamma"])
        self.assertEqual(ex.catalog_request(self.sources, 8), self.catalog)
        self.assertEqual(ex.catalog_request(self.sources, 0), {})
        with self.assertRaises(ValueError):
            ex.catalog_request(self.sources, -1)

    def test_structured_read_original_lines_and_document(self):
        source = {"E9": "line: 80\nrole: user\ntoolUseResult: type: text\nfile: filePath: /tmp/manual.txt\n"
                  "content: ## Stage one\ncontent: literal field name\nShip before dusk.\n\n"
                  "numLines: 3\nstartLine: 31\ntotalLines: 580"}
        catalog = ex.catalog_request(source, 10)
        rec, = catalog.values()
        self.assertEqual((rec["document"], rec["title"]), ("manual.txt", "Stage one"))
        self.assertIn("32\tcontent: literal field name", ex.catalog_index(catalog, full=True))
        _, choices = ex.parse_selections(f"@keep {rec['id']} #32 | history | Dispatch policy v1", catalog)
        ex.verify_selected(choices, source)
        self.assertEqual(choices[0]["text"], "content: literal field name")
        body = ex.render_selected(choices, 500)
        self.assertIn("manual.txt", body)
        self.assertIn("lines 32–32", body)


if __name__ == "__main__":
    unittest.main()

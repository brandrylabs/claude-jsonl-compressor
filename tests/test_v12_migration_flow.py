"""Anonymous migration through the public planning, submission and finish commands."""
import json
import re
import tempfile
import unittest
from pathlib import Path

import _fixtures as fx
from test_v12_workflow import command, core
import v12_memory as mem


class MigrationWorkflow(unittest.TestCase):
    def fixture(self, base, prior):
        tr = fx.TranscriptBuilder("eeea1234-4444-4111-baaa-999999999999")
        tr.compact_pair(prior)
        for i in range(16):
            tr.user(f"Statement request {i}.")
            tr.assistant_text(f"Statement result {i}.")
        tr.last_prompt()
        return fx.write_jsonl(base/"input.jsonl", tr.records)

    def submit(self, run, job, draft):
        path = run.parent/"draft.md"
        path.write_text("\n".join(["## Current State", *draft, mem.END]), encoding="utf-8")
        return command("submit", "--run", run, "--task", job["id"], "--draft", path)

    def test_many_independent_residuals_all_reach_finish(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            facts = [f"Rack {i} carries amber." for i in range(1001)]
            prior = mem._DETERMINISTIC_INTRO + "\n" + "\n".join(
                f"- L{i}: {fact}" for i, fact in enumerate(facts, 1))
            source = self.fixture(base, prior)
            run = base/"run"
            preview = command("prepare", "--input", source, "--run", run, "--prior", "clean-and-merge",
                              "--target-ratio", .05, "--min-recent-records", 2, "--excerpts", 0)
            self.assertGreater(preview["maps"], 1)
            seen = set()
            while True:
                state = json.loads((run/"state.json").read_bytes())
                if state.get("finalJob"):
                    break
                for job in state["jobs"]:
                    support = json.loads((run/job["support"]).read_bytes())
                    draft = []
                    for key, value in support["residuals"].items():
                        self.assertNotIn(key, seen)
                        seen.add(key)
                        draft.extend([f"- {value} [{key}]", f"> {key} merged | {value}"])
                    for key, value in support["sources"].items():
                        parts = re.findall(r"Rack \d+ carries amber\.|Statement (?:request|result) \d+\.", value)
                        self.assertTrue(parts, key)
                        draft.extend(f"- {fact} [{key}]" for fact in parts)
                    self.submit(run, job, draft)
            self.assertEqual(len(seen), len(facts))
            self.assertTrue(command("finish", "--run", run)["structure"])
            summary, = [r["message"]["content"] for r in fx.read_jsonl(run/"candidate.jsonl") if r.get("isCompactSummary")]
            self.assertTrue(all(fact in summary for fact in facts))
            self.assertTrue(all(e["outputEstimate"] <= 16000 for e in state["events"]))

    def test_old_fences_and_unknown_page_binding(self):
        old = ("## Current State\r\n\r\n- Keep the sample on ice.\r\n\r\n## Source excerpts\r\n\r\n"
               "### Historical · Manual · revision A · lines 17–20\r\n\r\n~~~~\r\n"
               "### A quotation\r\n~~~\r\nReturn the sample before dusk.\r\n~~~~")
        result = mem.prepare_prior(old, "clean-and-merge")
        self.assertEqual(mem.reassemble_prior(result["audit"]), old)
        self.assertEqual(len(result["residuals"]), 1)
        quote, = result["residuals"].values()
        self.assertIn("Historical · Manual · revision A · lines 17–20", quote)
        self.assertIn("### A quotation\r\n~~~\r\nReturn", quote)
        self.assertNotIn("before dusk", result["evidence"])
        damaged = old[:-1]
        self.assertEqual(list(mem.prepare_prior(damaged, "clean-and-merge")["residuals"].values()), [damaged])
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            raw = "Amber specimen instruction.\n" * 1900
            src = self.fixture(base, raw)
            run = base/"run"
            command("prepare", "--input", src, "--run", run, "--min-recent-records", 2, "--prior", "clean-and-merge",
                    "--input-limit", 3000, "--other-input", 0, "--target-ratio", .05, "--excerpts", 0)
            plan = json.loads((run/"run-plan.json").read_bytes())
            pages, restored = [], ""
            for job in plan["jobs"]:
                support = json.loads((run/job["support"]).read_bytes())
                for key, value in support["residuals"].items():
                    span = support["residualRanges"][key]
                    self.assertEqual(span["start"], len(restored))
                    self.assertEqual(span["sha256"], mem._sha(raw))
                    restored += value
                    self.assertEqual(span["end"], len(restored))
                    pages.append(key)
                    self.assertNotIn(value, support["sources"].values())
            self.assertGreater(len(pages), 1)
            self.assertEqual(restored, raw)

    def test_finished_excerpt_then_clean_then_locked_with_new_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            literal = "Amber samples require a signed dispatch."
            src = self.fixture(base, literal)
            previous = None
            for cycle, policy in enumerate(("resynthesize", "clean-and-merge", "verbatim-locked")):
                run = base/f"run-{cycle}"
                command("prepare", "--input", src, "--run", run, "--prior", policy,
                        "--min-recent-records", 2, "--target-ratio", .05)
                job, = json.loads((run/"run-plan.json").read_bytes())["jobs"]
                data = json.loads((run/job["support"]).read_bytes())
                claims = {}
                for key, value in {**data["sources"], **data["residuals"]}.items():
                    found = re.search(r"Amber samples require a signed dispatch\.|Statement (?:request|result) \d+\.", value)
                    self.assertIsNotNone(found)
                    claims.setdefault(found[0], []).append(key)
                draft = []
                for claim, keys in claims.items():
                    draft.append(f"- {claim} [{','.join(keys)}]")
                    for key in keys:
                        if key in data["residuals"]:
                            draft.append(f"> {key} merged | {claim}")
                if cycle < 2:
                    picks = [v for v in data["excerpts"].values() if literal in v["text"]
                             and (cycle == 0 or v["source"] in data["residuals"])]
                    self.assertTrue(picks)
                    draft.append(f"@keep {picks[0]['id']} | history | Dispatch manual edition A")
                else:
                    self.assertIn(literal, (run/job["request"]).read_text(encoding="utf-8"))
                self.submit(run, job, draft)
                command("finish", "--run", run)
                rows = fx.read_jsonl(run/"candidate.jsonl")
                body, = [row["message"]["content"] for row in rows if row.get("isCompactSummary")]
                if cycle < 2:
                    residuals = mem.prepare_prior(body, "clean-and-merge")["residuals"]
                    rec, = residuals.values()
                    self.assertIn(literal, rec)
                    self.assertIn("Dispatch manual edition A", rec)
                    self.assertIn("Historical", rec)
                else:
                    self.assertTrue(body.startswith(previous + "\n\n"))
                    decoded = mem.prepare_prior(body, "clean-and-merge")
                    residual, = decoded["residuals"].values()
                    self.assertIn(literal, residual)
                    self.assertNotIn("## Current State", residual)
                    self.assertEqual(mem.reassemble_prior(decoded["audit"]), body)
                previous = body
                tr = fx.TranscriptBuilder(rows[0]["sessionId"])
                tr.prev_uuid = next(r["leafUuid"] for r in reversed(rows) if r["type"] == "last-prompt")
                for number in range(16):
                    tr.user(f"Statement request {(cycle+1)*100+number}.")
                    tr.assistant_text(f"Statement result {(cycle+1)*100+number}.")
                tr.last_prompt()
                src = fx.write_jsonl(base/f"continued-{cycle}.jsonl", rows + tr.records)

    def test_partial_locked_context_survives_reduce(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            visible = "Amber dispatch receipt."
            hidden = "Historian only manual."
            src = self.fixture(base, visible + "\n" + hidden * 50)
            run = base/"locked"
            preview = command("prepare", "--input", src, "--run", run, "--prior", "verbatim-locked",
                              "--input-limit", 900, "--other-input", 0, "--excerpts", 0,
                              "--locked-context-chars", len(visible), "--min-recent-records", 2, "--target-ratio", .05)
            self.assertGreater(preview["maps"], 1)
            stages = []
            while True:
                state = json.loads((run/"state.json").read_bytes())
                if state.get("finalJob"):
                    break
                for job in state["jobs"]:
                    stages.append(job["stage"])
                    context = (run/job["request"]).read_text(encoding="utf-8")
                    self.assertIn(visible, context)
                    self.assertNotIn(hidden, context)
                    self.assertLessEqual(job["inputEstimate"], 900)
                    data = json.loads((run/job["support"]).read_bytes())
                    self.assertEqual(data["references"], {"L1":visible})
                    draft = []
                    for key, value in data["sources"].items():
                        fact = re.search(r"Statement (?:request|result) \d+\.", value)[0]
                        draft.append(f"- {fact} [{key}]")
                    self.submit(run, job, draft)
            self.assertIn("reduce", stages)
            self.assertTrue(command("finish", "--run", run)["structure"])

    def test_explicit_locked_range_and_shape_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            prior = " Amber glass.\r\n \tOld rule.  "
            src = self.fixture(base, prior)
            run = base/"lookup"
            options = ["--input", src, "--min-recent-records", 2, "--prior", "verbatim-locked", "--target-ratio", .05,
                       "--locked-range", "P1:1-13", "--locked-context-chars", 12]
            plan = command("prepare", *options, "--run", run)
            self.assertGreater(plan["lockedContextTokens"], 0)
            self.assertNotIn(prior[1:13], str(plan))
            for job in json.loads((run/"run-plan.json").read_bytes())["jobs"]:
                self.assertEqual(json.loads((run/job["support"]).read_bytes())["references"], {"L1":prior[1:13]})
                self.assertIn(prior[1:13], (run/job["request"]).read_bytes().decode())
            with self.assertRaisesRegex(ValueError, "exceed"):
                command("plan", *options, "--locked-context-chars", 4)
            blocks = [{"type":"text", "text":"Amber sample."}, {"type":"text", "text":"Blue order."}]
            src = self.fixture(base, blocks)
            options = ["--input",src,"--min-recent-records",2,"--target-ratio",.05]
            result = command("prepare", *options, "--prior", "resynthesize", "--run", base/"list")
            self.assertEqual(result["state"], "ready")
            records = json.loads((base/"list"/"source-audit.json").read_bytes())["priors"]
            self.assertEqual([mem.reassemble_prior(p["audit"]) for p in records], [b["text"] for b in blocks])
            with self.assertRaisesRegex(ValueError, "retain and continue"):
                command("plan", *options, "--prior", "verbatim-locked")
            self.assertFalse(core.validate_jsonl(src, contract="fresh-candidate")["ok"])
            self.fixture(base, [{"type":"image","source":{"type":"missing"}}])
            with self.assertRaisesRegex(ValueError, "retain and continue"):
                command("plan", *options)
            self.fixture(base, "  \r\n")
            self.assertTrue(command("plan", *options, "--prior", "verbatim-locked")["lockedRanges"])

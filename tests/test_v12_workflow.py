"""Exercise the v12 command line on anonymous, branching and tool-bearing histories."""
from pathlib import Path
import contextlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compress_claude_jsonl as core
import v12_evidence as ev
import v12_workflow as flow
import v12_memory as memory
import _fixtures as fx


def command(*args):
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = core.main(["v12", *map(str,args)])
    if code:
        raise ValueError(err.getvalue())
    return json.loads(out.getvalue())


def cli(*args):
    result = subprocess.run([sys.executable, "-X", "utf8", "-B", core.__file__, "v12", *map(str, args)],
                            capture_output=True, encoding="utf-8", timeout=45)
    if result.returncode:
        raise ValueError(result.stderr)
    return json.loads(result.stdout)


def draft(run, job):
    sources=json.loads((run/job["support"]).read_bytes())["sources"]
    lines=["## Current State"]
    for key, text in sources.items():
        # Fixture data: use the actual utterance in the private citation map.
        found=re.search(r"Statement (?:request|result) \d+\.",text)
        if not found:
            raise AssertionError("unexpected fixture material")
        excerpt=found.group()
        lines.append(f"- {excerpt} [{key}]")
    return "\n".join(lines+["<!-- end-memory -->"])


class TestV12Workflow(unittest.TestCase):
    def source(self, root, count=22, padding=0):
        tr=fx.TranscriptBuilder("ffff0000-1111-4222-8333-999999999999")
        for i in range(count):
            tr.user(f"Statement request {i}.")
            tr.assistant_text(f"Statement result {i}.")
            if padding:
                tr.records[-1]["message"]["content"].append({"type":"text","text":("quiet " + str(i) + " ")*padding})
        tr.last_prompt()
        return fx.write_jsonl(root/"session.jsonl",tr.records)

    def run_all(self,run):
        while True:
            state=json.loads((run/"state.json").read_bytes())
            if state.get("finalJob"):break
            for job in state["jobs"]:
                if job["id"] in state["accepted"]:continue
                path=run.parent/"writer.md"
                path.write_text(draft(run,job),encoding="utf-8")
                command("submit","--run",run,"--task",job["id"],"--draft",path)
        return command("finish","--run",run)

    def test_single_candidate_checked_audit_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); src=self.source(base); original=src.read_bytes(); run=base/"run"
            settings=["--input",src,"--run",run,"--min-recent-records",2,"--target-ratio",.05]
            a=command("plan",*settings); self.assertFalse(run.exists())
            b=command("prepare",*settings); self.assertEqual(a["fixedTokens"],b["fixedTokens"])
            self.assertEqual((base/"session.jsonl.backup").read_bytes(),original)
            j=json.loads((run/"run-plan.json").read_bytes())["jobs"][0]
            original_request=(run/j["request"]).read_bytes()
            path=base/"writer.md"; path.write_text(draft(run,j),encoding="utf-8")
            (run/j["request"]).write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError,"changed"):command("submit","--run",run,"--task",j["id"],"--draft",path)
            (run/j["request"]).write_bytes(original_request)
            with self.assertRaisesRegex(ValueError,"truncated"):command("submit","--run",run,"--task",j["id"],"--draft",path,"--stop-reason","length")
            report=self.run_all(run)
            rows,_=core.read_jsonl(run/"candidate.jsonl")
            boundary=next(r for r in rows if r.get("subtype")=="compact_boundary")
            content=next(r["message"]["content"] for r in rows if r.get("isCompactSummary"))
            self.assertEqual(boundary["compactMetadata"]["auditSha256"],core.file_sha256(run/"audit.json"))
            self.assertNotIn("end-memory",content); self.assertNotIn("[E1]",content)
            self.assertEqual(src.read_bytes(),original)
            self.assertTrue(report["structure"]); self.assertEqual(report["cost"]["requestsByStage"]["map"],2)

    def test_large_windows_reduce_and_active_projection(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); src=self.source(base,count=62,padding=6900); run=base/"run"
            b=command("prepare","--input",src,"--run",run,"--min-recent-records",2,"--target-ratio",.05,
                      "--summary-char-budget",80000,"--generation",12000)
            self.assertGreaterEqual(b["maps"],2);self.assertLess(b["peakInputEstimate"],300000)
            self.assertGreater(b["inputTracks"]["conservativeGateTokens"],900000)
            self.assertLessEqual(b["inputTracks"]["conservativeGateTokens"],960000)
            report=self.run_all(run)
            self.assertGreaterEqual(report["cost"]["requestsByStage"]["reduce"],1)
            self.assertTrue(core.validate_jsonl(run/"candidate.jsonl",contract="fresh-candidate")["ok"])

    def test_partition_takes_the_longest_fitting_prefix(self):
        shared = {"shared": "Shared source text. " * 50}
        units = []
        for i in range(110):
            text = f"Item {i}. " + "原文 and notes " * (1 + i % 6)
            units.append(dict(id=f"E{i}", text=text, support=text, lines=[i],
                              refs=["shared"] if i % 3 else [], residuals={},
                              index=f"Quoted passage {i}" if i % 5 == 0 else ""))
        for stage in ("map", "reduce"):
            def size(group):
                return core.estimate_tokens(ev.request_for(group, shared, stage)[0])

            exact = size(units[:41])
            for cap in (size(units), exact, exact - 1, size(units[:13])):
                with self.subTest(stage=stage, cap=cap):
                    windows = ev.partition(core, iter(units), shared, cap, stage)
                    self.assertEqual([unit for window in windows for unit in window], units)
                    consumed = 0
                    for window in windows:
                        self.assertLessEqual(size(window), cap)
                        consumed += len(window)
                        if consumed < len(units):
                            self.assertGreater(size(window + [units[consumed]]), cap)
                    if cap == exact:
                        self.assertEqual(windows[0], units[:41])

    def test_partition_preserves_the_migration_output_allowance(self):
        text = "Preserve this source passage."
        reserve = 40 + core.estimate_tokens(text)
        units = [dict(id=f"E{i}", text="", support="", lines=[i], refs=[],
                      residuals={f"P1R{i}": text}) for i in range(7)]
        cap = core.estimate_tokens(ev.request_for(units, {}, "map")[0])
        windows = ev.partition(core, units, {}, cap, "map", output=4 * reserve)
        self.assertEqual(windows, [units[:2], units[2:4], units[4:6], units[6:]])
        with self.assertRaisesRegex(ValueError, "atomic migration obligation"):
            ev.partition(core, units, {}, cap, "map", output=2 * reserve - 1)

    def test_budget_and_media_boundaries(self):
        with self.assertRaises(ValueError):ev.profile(372000,300000,60000,32000,32000,2000,1000,3)
        p=ev.profile(36000,32000,2000,3000,8000,1000,1000,3)
        self.assertLess(p["otherInput"]+p["packLimit"],32000)
        image={"type":"image","source":{"type":"base64","media_type":"image/png","data":"AAAA"}}
        row={"type":"user","message":{"role":"user","content":[image]}}
        with self.assertRaisesRegex(ValueError,"unread image"):ev.payload_fields(core,row,7,"block",[])
        ledger=[]; obj=ev.payload_fields(core,row,7,"archive",ledger)
        self.assertNotIn("AAAA",str(obj));self.assertIn("unsupported_blocked",{i["status"] for i in ledger})
        with tempfile.TemporaryDirectory() as d:
            src=self.source(Path(d),count=50,padding=100)
            with self.assertRaisesRegex(ValueError,"floor|target|budget"):command("plan","--input",src,"--min-recent-records",70,
                    "--target-estimated-tokens",1000)

    def test_random_atomic_intervals(self):
        for seed in range(24):
            rng=random.Random(seed)
            ids=["tool-"+str(i) for i in range(10)]
            rows=[{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":s,"name":"Read","input":{}}]}}
                  for s in ids]
            rng.shuffle(ids)
            rows += [{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":s,"content":"complete"}]}}
                     for s in ids]
            ranges=list(ev.atomic_ranges(core,rows))
            self.assertEqual(ranges,[(0,len(rows))])

    def test_run_directory_collision_and_read_only_backup_diagnostic(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = self.source(base)
            run = base / "run"
            settings = ("prepare", "--input", source, "--run", run, "--min-recent-records", 2, "--target-ratio", .05)
            with self.assertRaisesRegex(ValueError, "different files or directories"):
                command(*settings, "--backup-dir", run)
            self.assertFalse(run.exists())
            with patch.object(core, "_exclusive_backup_from_bytes", side_effect=PermissionError):
                with self.assertRaisesRegex(ValueError, "--backup-dir"):
                    command(*settings)
            self.assertFalse((run / "run-plan.json").exists())
            self.assertFalse(list(base.glob("*.backup*")))
            with flow.exclusive(run):
                with self.assertRaisesRegex(ValueError, "PID"):
                    with flow.exclusive(run):
                        self.fail("second owner acquired a live lock")
            self.assertFalse((run / ".operation.lock").exists())

    def test_live_uses_one_numbered_backup(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); project=base/"other-config"/"projects"/"demo";project.mkdir(parents=True)
            src=self.source(project); raw=src.read_bytes(); run=base/"work"
            with patch.dict(os.environ,{"CLAUDE_CONFIG_DIR":str(base/"other-config")}):
                command("prepare","--input",src,"--run",run,"--min-recent-records",2,"--target-ratio",.05,
                        "--live","--confirm-session-closed")
                self.run_all(run)
                replacement=command("finish","--run",run,"--replace-original","--confirm-session-closed")
                self.assertEqual(replacement["operation"],"committed")
                self.assertEqual(list(project.glob("*.backup*")),[project/"session.jsonl.backup"])
                self.assertEqual((project/"session.jsonl.backup").read_bytes(),raw)
                self.assertEqual(src.read_bytes(),(run/"candidate.jsonl").read_bytes())

    def submit_text(self, run, job, text):
        path = run.parent / "fixture-draft.md"
        path.write_bytes(text.encode("utf-8"))
        return command("submit", "--run", run, "--task", job["id"], "--draft", path)

    def test_signature_scope_in_frozen_author_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            tr = fx.TranscriptBuilder("ffff0000-1111-4222-8333-999999999999")
            tr.user("Check the signed agreement.")
            tr.tool_call_pair()
            call, result = tr.records[-2:]
            call["message"]["content"].append({"type": "thinking", "thinking": "Checking the draft.",
                                               "signature": "opaque-native-marker"})
            call["message"]["content"][1]["input"].update(
                signature="contract-author-signature",
                vendor={"type": "thinking", "signature": "nested-business-signature"})
            call["message"]["content"].append({"type": "vendor_attestation", "signature": "unknown-block-signature"})
            result["message"]["content"][0]["content"] = [{"type": "text", "text": "Verified.",
                                                            "signature": "result-signature"}]
            result["toolUseResult"]["signature"] = "auxiliary-signature"
            for i in range(20):
                tr.user(f"Archive request {i}.")
                tr.assistant_text(f"Archive result {i}.")
            tr.last_prompt()
            src = fx.write_jsonl(base/"source.jsonl", tr.records)
            run = base/"run"
            command("prepare", "--input", src, "--run", run, "--min-recent-records", 2, "--target-ratio", .05)
            plan = json.loads((run/"run-plan.json").read_bytes())
            requests = "".join((run/j["request"]).read_text(encoding="utf-8") for j in plan["jobs"])
            support = "".join((run/j["support"]).read_text(encoding="utf-8") for j in plan["jobs"])
            for text in (requests, support):
                for expected in ("Checking the draft.", "contract-author-signature", "nested-business-signature",
                                 "unknown-block-signature", "result-signature", "auxiliary-signature"):
                    self.assertIn(expected, text)
                self.assertNotIn("opaque-native-marker", text)
            ledger = json.loads((run/"source-audit.json").read_bytes())["ledger"]
            self.assertTrue(any(x["line"] == 2 and x.get("field") == "message.content[2].signature"
                                and x["status"] == "raw_kept" for x in ledger))
            self.assertEqual(Path(plan["backup"]).read_bytes(), src.read_bytes())

    def test_finish_checks_every_map_and_required_reduce(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            src = self.source(base, count=22, padding=100)
            run = base/"run"
            command("prepare", "--input", src, "--run", run, "--min-recent-records", 2, "--target-ratio", .05,
                    "--input-limit", 3000, "--other-input", 0, "--generation", 1000, "--thinking", 0, "--excerpts", 0)
            maps = json.loads((run/"run-plan.json").read_bytes())["jobs"]
            self.assertGreater(len(maps), 1)
            state_file = run/"state.json"
            for i, job in enumerate(maps):
                self.submit_text(run, job, draft(run, job))
                if i not in (0, len(maps) - 1):
                    continue
                original = state_file.read_bytes()
                state = json.loads(original)
                self.assertNotIn("finalJob", state)
                state["finalJob"] = maps[0]["id"]
                state_file.write_text(json.dumps(state), encoding="utf-8")
                with self.subTest(after_maps=i + 1), self.assertRaisesRegex(ValueError, "pending|ancestr|Reduce|final"):
                    command("finish", "--run", run)
                self.assertFalse((run/"candidate.jsonl").exists())
                self.assertFalse((run/"audit.json").exists())
                state_file.write_bytes(original)
            while True:
                state = json.loads(state_file.read_bytes())
                if state.get("finalJob"):
                    break
                for job in state["jobs"]:
                    self.submit_text(run, job, draft(run, job))
            original = state_file.read_bytes()
            state["level"] = 0
            state_file.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(ValueError):
                command("finish", "--run", run)
            state_file.write_bytes(original)
            for name in (maps[0]["id"] + ".accepted.json", maps[0]["support"], maps[0]["request"]):
                path = run/name
                raw = path.read_bytes()
                path.write_bytes(raw + b" ")
                with self.subTest(changed=name), self.assertRaises(ValueError):
                    command("finish", "--run", run)
                path.write_bytes(raw)
            self.assertFalse((run/"candidate.jsonl").exists())
            self.assertTrue(command("finish", "--run", run)["structure"])

    def test_prepare_keeps_tool_and_message_fragments_atomic(self):
        for kind in ("tool", "same-message"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                base = Path(temp)
                tr = fx.TranscriptBuilder("ffff0000-1111-4222-8333-999999999999")
                tr.user("Review the manual.")
                detail = "retained fact " * 3000 + "final condition"
                if kind == "tool":
                    tr.tool_call_pair(file_path="call-marker.txt")
                    tr.records[-1]["message"]["content"][0]["content"] = detail
                else:
                    tr.assistant_text("call-marker.txt")
                    tr.assistant_text(detail)
                    tr.records[-1]["message"]["id"] = tr.records[-2]["message"]["id"]
                for i in range(20):
                    tr.user(f"Request {i}.")
                    tr.assistant_text(f"Result {i}.")
                tr.last_prompt()
                src = fx.write_jsonl(base/"source.jsonl", tr.records)
                original = src.read_bytes()
                source_stat = src.stat()
                run = base/"run"
                flags = ["--input", src, "--run", run, "--min-recent-records", 2, "--target-ratio", .05,
                         "--other-input", 0, "--generation", 1000, "--thinking", 0, "--excerpts", 0]
                for action in ("plan", "prepare"):
                    with self.assertRaisesRegex(ValueError, r"(?i)atomic") as failure:
                        command(action, *flags, "--input-limit", 1200)
                    counts = re.search(r"requires (\d+) evidence tokens; profile permits (\d+)", str(failure.exception))
                    self.assertIsNotNone(counts)
                    self.assertGreater(int(counts[1]), int(counts[2]))
                    self.assertEqual(int(counts[2]), 1199)
                    self.assertEqual(list(base.iterdir()), [src])
                    self.assertEqual(src.read_bytes(), original)
                    self.assertEqual((src.stat().st_ino, src.stat().st_mtime_ns),
                                     (source_stat.st_ino, source_stat.st_mtime_ns))
                command("prepare", *flags, "--input-limit", 20000)
                plan = json.loads((run/"run-plan.json").read_bytes())
                requests = [(run/j["request"]).read_text(encoding="utf-8") for j in plan["jobs"]]
                matching = [r for r in requests if "call-marker.txt" in r or "final condition" in r]
                self.assertEqual(len(matching), 1)
                self.assertIn("call-marker.txt", matching[0])
                self.assertIn(detail, matching[0])

    def test_postcommit_receipt_directory_preserves_backup_and_exit_three(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = base/"config"/"projects"/"demo"
            project.mkdir(parents=True)
            src = self.source(project)
            original = src.read_bytes()
            run = base/"run"
            with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(base/"config")}):
                command("prepare", "--input", src, "--run", run, "--min-recent-records", 2,
                        "--target-ratio", .05, "--live", "--confirm-session-closed")
                self.run_all(run)
                candidate = (run/"candidate.jsonl").read_bytes()
                self.assertNotEqual(candidate, original)
                replace_file = core._replace_file_after_validation

                def occupy_receipt_after_commit(*args, **kwargs):
                    txn = replace_file(*args, **kwargs)
                    self.assertEqual(src.read_bytes(), candidate)
                    (run/"replacement.json").mkdir()
                    return txn

                out = io.StringIO()
                with patch.object(core, "_replace_file_after_validation", occupy_receipt_after_commit), \
                     contextlib.redirect_stdout(out):
                    code = core.main(["v12", "finish", "--run", str(run),
                                      "--replace-original", "--confirm-session-closed"])
                self.assertEqual(code, 3)
                receipt = json.loads(out.getvalue())
                self.assertEqual(receipt["operation"], "committed-report-failed")
                self.assertEqual(src.read_bytes(), candidate)
                backup = Path(receipt["backup"])
                self.assertEqual(list(project.resolve(strict=True).glob("*.backup*")), [backup])
                self.assertEqual(backup.read_bytes(), original)
                self.assertEqual(receipt["candidateSha256"], core.file_sha256(src))
                self.assertEqual(receipt["sourceSha256"], core.file_sha256(backup))

    def test_literal_excerpts_map_reduce_budget_and_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            src = self.source(base, count=48, padding=180)
            rows = fx.read_jsonl(src)
            first_line = "  Keep the leading and trailing spaces.  "
            second_line = "Wait until the batch clears."
            first_extra = "Long appendix describing the earlier rule. " * 58
            second_extra = "Long appendix describing the fallback plan. " * 58
            rows[0]["message"]["content"] += (
                "\r\n41→## Workshop procedure\r\n42→" + first_line + "\r\n43→" + second_line +
                "\r\n44→" + first_extra + "\r\n50→## Fallback procedure\r\n51→" + second_extra)
            fx.write_jsonl(src, rows)
            initial = src.read_bytes()
            run = base/"run"
            prepared = command("prepare", "--input", src, "--run", run, "--min-recent-records", 2,
                               "--target-ratio", .05, "--other-input", 0, "--input-limit", 8000,
                               "--summary-char-budget", 4000, "--target-estimated-tokens", 1100)
            self.assertGreater(prepared["maps"], 1)
            maps = json.loads((run/"run-plan.json").read_bytes())["jobs"]
            chosen = {}
            for job in maps:
                support = json.loads((run/job["support"]).read_bytes())
                directives = []
                for key, entry in support["excerpts"].items():
                    if entry["title"] not in {"Workshop procedure", "Fallback procedure"}:
                        continue
                    self.assertIn(key, (run/job["request"]).read_text(encoding="utf-8"))
                    chosen[entry["title"]] = key
                    directives.append(f"@keep {key} | current | Workshop manual, initial issue")
                text = draft(run, job).replace("<!-- end-memory -->", "\n".join([*directives, "<!-- end-memory -->"]))
                self.submit_text(run, job, text)
            self.assertEqual(set(chosen), {"Workshop procedure", "Fallback procedure"})
            state = json.loads((run/"state.json").read_bytes())
            reducer, = state["jobs"]
            self.assertEqual(reducer["stage"], "reduce")
            lookup = json.loads((run/reducer["support"]).read_bytes())["excerpts"]
            first, second = chosen["Workshop procedure"], chosen["Fallback procedure"]
            self.assertEqual(lookup[first]["text"], "\r\n".join([first_line, second_line, first_extra]))
            self.assertEqual(lookup[second]["text"], second_extra)
            text = draft(run, reducer)
            too_long = text.replace("<!-- end-memory -->", f"@keep {first}\n@keep {second}\n<!-- end-memory -->")
            with self.assertRaisesRegex(ValueError, "character|allowance|budget"):
                self.submit_text(run, reducer, too_long)
            self.assertFalse((run/(reducer["id"] + ".accepted.json")).exists())
            self.assertFalse((run/"candidate.jsonl").exists())
            self.assertIn(reducer["id"], command("status", "--run", run)["pending"])
            full_first = text.replace("<!-- end-memory -->", f"@keep {first}\n<!-- end-memory -->")
            with self.assertRaisesRegex(ValueError, "structured tokens|token.*ceiling"):
                self.submit_text(run, reducer, full_first)
            self.assertFalse((run/(reducer["id"] + ".accepted.json")).exists())
            self.assertIn(reducer["id"], command("status", "--run", run)["pending"])
            selected = f"@keep {first} #42-43 | superseded | Workshop manual before sign-off"
            self.submit_text(run, reducer, text.replace("<!-- end-memory -->", selected + "\n<!-- end-memory -->"))
            report = command("finish", "--run", run)
            self.assertTrue(report["structure"])
            candidate = fx.read_jsonl(run/"candidate.jsonl")
            summary, = [r["message"]["content"] for r in candidate if r.get("isCompactSummary")]
            self.assertIn(first_line + "\r\n" + second_line, summary)
            self.assertIn("Superseded", summary)
            self.assertIn("Workshop manual before sign-off", summary)
            self.assertIn("lines 42–43", summary)
            for private in (first, second, "end-memory", first_extra, second_extra):
                self.assertNotIn(private, summary)
            self.assertLessEqual(len(summary), 4000)
            self.assertLessEqual(core.estimate_records_tokens(candidate), 1100)
            final = json.loads((run/(reducer["id"] + ".accepted.json")).read_bytes())
            excerpt, = final["excerpts"]
            self.assertEqual(excerpt["text"], first_line + "\r\n" + second_line)
            self.assertEqual(final["body"], summary)
            self.assertEqual(src.read_bytes(), initial)

    def test_reduce_request_budgets_complete_inherited_excerpt(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            src = self.source(base, count=48, padding=180)
            rows = fx.read_jsonl(src)
            exception = "Exception: frozen batches require the board's written approval."
            passage = "The reviewer signs the batch register before dispatch. " * 12 + exception
            self.assertGreater(passage.index(exception), 96)
            rows[0]["message"]["content"] += "\n41→## Batch procedure\n42→" + passage
            fx.write_jsonl(src, rows)
            run = base / "run"
            command("prepare", "--input", src, "--run", run, "--min-recent-records", 2,
                    "--target-ratio", .05, "--input-limit", 8000, "--other-input", 220)
            plan = json.loads((run / "run-plan.json").read_bytes())
            self.assertGreater(len(plan["jobs"]), 1)
            selected = []
            for job in plan["jobs"]:
                text = draft(run, job)
                catalog = json.loads((run / job["support"]).read_bytes())["excerpts"]
                for key, entry in catalog.items():
                    if entry["title"] == "Batch procedure":
                        self.assertEqual(entry["text"], passage)
                        selected.append(key)
                        text = text.replace(memory.END, f"@keep {key} | history | Batch register\n{memory.END}")
                self.submit_text(run, job, text)
            key, = selected
            reducer, = json.loads((run / "state.json").read_bytes())["jobs"]
            self.assertEqual(reducer["stage"], "reduce")
            request = (run / reducer["request"]).read_bytes().decode("utf-8")
            self.assertIn(key, request)
            self.assertIn(passage, request)
            measured = core.estimate_tokens(request)
            self.assertEqual(reducer["requestTokens"], measured)
            self.assertEqual(reducer["inputEstimate"], measured + plan["profile"]["otherInput"])
            self.assertLessEqual(measured, plan["profile"]["packLimit"])
            text = draft(run, reducer).replace(memory.END, f"@keep {key} | current | Batch register\n{memory.END}")
            self.submit_text(run, reducer, text)
            self.assertTrue(command("finish", "--run", run)["structure"])
            summary, = [row["message"]["content"] for row in fx.read_jsonl(run / "candidate.jsonl")
                        if row.get("isCompactSummary")]
            self.assertIn(passage, summary)

    def test_cli_oversized_parent_can_be_shortened_before_two_reduce_levels(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            src = self.source(base, count=60, padding=100)
            run = base / "run"
            writer = base / "writer.md"
            cli("prepare", "--input", src, "--run", run, "--min-recent-records", 2, "--target-ratio", .05,
                "--input-limit", 3000, "--other-input", 0, "--generation", 9000, "--output-limit", 10000,
                "--thinking", 0, "--excerpts", 0)
            plan = json.loads((run / "run-plan.json").read_bytes())
            maps = plan["jobs"]
            self.assertGreater(len(maps), 2)

            def expanded(job, copies):
                # Expand a single supported claim while preserving its explicit literal citation.
                lines = draft(run, job).splitlines()
                claim, key = re.fullmatch(r"- (.+) \[(.+)\]", lines[1]).groups()
                lines[1:2] = [f"- {' '.join([claim] * copies)} [{key}]", f"> {key} | {claim}"]
                return "\n".join(lines)

            def send(job, text):
                writer.write_bytes(text.encode("utf-8"))
                return cli("submit", "--run", run, "--task", job["id"], "--draft", writer)

            first = maps[0]
            oversized = expanded(first, 800)
            self.assertGreater(core.estimate_tokens(oversized), plan["profile"]["packLimit"])
            self.assertLess(core.estimate_tokens(oversized), plan["profile"]["output"])
            with self.assertRaises(ValueError) as rejection:
                send(first, oversized)
            self.assertRegex(str(rejection.exception), r"(?i)reduce")
            self.assertRegex(str(rejection.exception), r"(?i)shorten|smaller|more compact")
            self.assertIn(first["id"], cli("status", "--run", run)["pending"])
            self.assertNotIn(first["id"], json.loads((run / "state.json").read_bytes())["accepted"])
            self.assertFalse((run / (first["id"] + ".accepted.json")).exists())

            for job in maps:
                send(job, expanded(job, 120))
            parents = [job["id"] for job in maps]
            for level in (1, 2):
                state = json.loads((run / "state.json").read_bytes())
                self.assertEqual(state["level"], level)
                jobs = state["jobs"]
                if level == 1:
                    self.assertGreater(len(jobs), 1)
                else:
                    self.assertEqual(len(jobs), 1)
                self.assertEqual([group for job in jobs for group in job["lines"]], [[p] for p in parents])
                for job in jobs:
                    send(job, draft(run, job))
                parents = [job["id"] for job in jobs]

            layer = run / "reduce-1.json"
            original = layer.read_bytes()
            for change in ("missing", "duplicate"):
                with self.subTest(change=change):
                    frozen = json.loads(original)
                    groups = frozen["jobs"][0]["lines"]
                    if change == "missing":
                        groups.pop()
                    else:
                        groups.append(groups[-1])
                    layer.write_bytes(json.dumps(frozen).encode("utf-8"))
                    with self.assertRaises(ValueError):
                        cli("finish", "--run", run)
                    self.assertFalse((run / "candidate.jsonl").exists())
            layer.write_bytes(original)
            self.assertTrue(cli("finish", "--run", run)["structure"])

    def test_three_cli_rounds_with_appended_corrections_and_locked_prior(self):

        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            tr = fx.TranscriptBuilder("ffff0000-1111-4222-8333-999999999999")
            historical = "  Signed test instruction.\r\n\tPreserve these spaces.  \r\n"
            prior = historical
            tr.compact_pair(historical)
            src = base/"source.jsonl"
            previous_candidate = None
            for cycle, color in enumerate(("amber", "indigo", "ivory"), 1):
                correction = f"Current label is {color} after review {cycle}."
                tr.user(correction)
                tr.assistant_text(f"Statement result {cycle * 100}.")
                for i in range(1, 17):
                    tr.user(f"Statement request {cycle * 100 + i}.")
                    tr.assistant_text(f"Statement result {cycle * 100 + i}.")
                tr.last_prompt()
                if previous_candidate is None:
                    fx.write_jsonl(src, tr.records)
                else:
                    # Continue from the exact preceding candidate bytes and its declared leaf.
                    new_rows = fx.write_jsonl(base/"appended.jsonl", tr.records)
                    src.write_bytes(previous_candidate + new_rows.read_bytes())
                beginning = src.read_bytes()
                run = base/f"run-{cycle}"
                result = cli("prepare", "--input", src, "--run", run, "--min-recent-records", 2,
                             "--target-ratio", .05, "--prior", "verbatim-locked")
                self.assertEqual(result["maps"], 1)
                job, = json.loads((run/"run-plan.json").read_bytes())["jobs"]
                sources = json.loads((run/job["support"]).read_bytes())["sources"]
                claims = []
                for key, support in sources.items():
                    match = re.search(r"(?:Current label is [a-z]+ after review \d+|Statement (?:request|result) \d+)\.",
                                      support)
                    self.assertIsNotNone(match, support)
                    claims.append(f"- {match.group()} [{key}]")
                writer = base/"writer.md"
                writer.write_bytes("\n".join(["## Current State", *claims, "<!-- end-memory -->"]).encode())
                cli("submit", "--run", run, "--task", job["id"], "--draft", writer)
                self.assertTrue(cli("finish", "--run", run)["structure"])
                rows = fx.read_jsonl(run/"candidate.jsonl")
                current, = [r["message"]["content"] for r in rows if r.get("isCompactSummary")]
                self.assertTrue(current.startswith(prior + "\n\n"))
                self.assertEqual(current.count(historical), 1)
                self.assertIn(correction, current[len(prior):])
                self.assertNotIn("end-memory", current)
                old, = json.loads((run/"source-audit.json").read_bytes())["priors"]
                self.assertEqual(memory.reassemble_prior(old["audit"]), prior)
                self.assertEqual(Path(json.loads((run/"run-plan.json").read_bytes())["backup"]).read_bytes(), beginning)
                self.assertEqual(src.read_bytes(), beginning)
                prior = current
                previous_candidate = (run/"candidate.jsonl").read_bytes()
                tr.records.clear()
                tr.prev_uuid = next(r["leafUuid"] for r in reversed(rows) if r["type"] == "last-prompt")

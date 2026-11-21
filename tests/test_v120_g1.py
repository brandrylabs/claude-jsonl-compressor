"""Synthetic regression probes for the 1.2 structural contracts."""
import contextlib
import io
import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock

import _fixtures as fx
from _fixtures import ccj, cst


class StructuralRegression(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        self.tb = fx.build_linear("structural-example", turns=30)
        self.source = fx.write_jsonl(self.root / "source.jsonl", self.tb.records)

    def test_pack_alias_rejected_before_read_and_write(self):
        alias = self.root / "alias.md"
        os.link(self.source, alias)
        original = self.source.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(ccj, "build_model_summary_pack_for_input", side_effect=AssertionError) as build:
                result = ccj.main(["--input", str(self.source), "--write-model-pack", str(alias)])
            build.assert_not_called()
        self.assertNotEqual(result, 0)
        self.assertEqual(alias.read_bytes(), original)

    def test_floor_blocks_semantic_work(self):
        result = ccj.preflight_jsonl(self.source, .05, 2, 8000, min_recent_turns=500)
        self.assertFalse(result["ok"])
        with self.assertRaisesRegex(ValueError, "recent"):
            ccj.build_model_summary_pack_for_input(self.source, .05, 2, 8000, min_recent_turns=500)

    def test_budget_and_media_before_pack(self):
        self.tb.records.pop()
        self.tb.user("界" * 5000)
        self.tb.last_prompt()
        fx.write_jsonl(self.source, self.tb.records)
        result = ccj.preflight_jsonl(self.source, .05, 2, 8000, target_estimated_tokens=1000)
        self.assertFalse(result["ok"])
        self.tb.records[1]["message"]["content"] = [{"type":"image","source":{"type":"base64","data":"ABCD"}}]
        fx.write_jsonl(self.source, self.tb.records)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            ccj.build_model_summary_pack_for_input(self.source, .05, 2, 8000)

    def test_custom_root_and_locator(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root)}):
            self.assertTrue(ccj.is_under_claude_projects(self.root / "projects" / "p" / "s.jsonl"))
        sub = self.root / "subagents" / "agent-example.jsonl"
        fx.write_jsonl(sub, self.tb.records)
        self.assertNotIn(sub, cst.list_session_files(self.root))
        self.tb.custom_title("Review")
        fx.write_jsonl(self.source, self.tb.records)
        self.tb.custom_title("Review next")
        fx.write_jsonl(self.root / "another.jsonl", self.tb.records)
        self.assertEqual(cst.find_unique_session(self.root, "Review", True), self.source)
        (self.root / "broken.jsonl").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "scan"):
            cst.find_unique_session(self.root, "Review", True)

    def test_v11_budget_includes_final_projection_before_pack_is_written(self):
        tb = fx.TranscriptBuilder("budget")
        for i in range(30):
            tb.user(f"Question {i}")
            tb.assistant_text(f"Answer {i}")
        tb.last_prompt()
        fx.write_jsonl(self.source, tb.records)
        for active in (True, False):
            options = dict(target_ratio=.05, min_recent_records=2, summary_char_budget=4000,
                           target_estimated_tokens=1000, preserve_active_chain=active)
            with self.subTest(active=active):
                pre = ccj.preflight_jsonl(self.source, **options)
                self.assertFalse(pre["ok"], pre)
                self.assertGreater(pre["estimates"]["fixedLowerBoundTokens"], 1000)
                self.assertLess(pre["estimates"]["rawStructuredTokens"], 1000)
                with self.assertRaisesRegex(ValueError, "fixed.*above requested target"):
                    ccj.build_model_summary_pack_for_input(self.source, **options)
        pack_path = self.root / "pack.md"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = ccj.main(["--input", str(self.source), "--write-model-pack", str(pack_path),
                             "--min-recent-records", "2", "--target-ratio", ".05",
                             "--summary-char-budget", "4000", "--target-estimated-tokens", "1000"])
        self.assertNotEqual(code, 0)
        self.assertFalse(pack_path.exists())


    def test_historical_and_fresh_have_distinct_contracts(self):
        output = self.root / "candidate.jsonl"
        ccj.compress_jsonl(self.source, output, .05, 2, 12000, deterministic_summary=True)
        rows = fx.read_jsonl(output)
        rows.append(dict(rows[-1]))
        fx.write_jsonl(output, rows)
        self.assertTrue(ccj.validate_jsonl(output, contract="historical-source")["ok"])
        self.assertFalse(ccj.validate_jsonl(output, contract="fresh-candidate")["ok"])

    def test_v11_floor_is_below_accepted_candidate_and_pack_is_built_once(self):
        from test_protocol_contracts import ProtocolBase
        tb = fx.TranscriptBuilder("budget")
        tb.compact_pair("Locked original  \n" * 5)
        for i in range(24):
            tb.user(f"Question {i}")
            tb.assistant_text(f"Answer {i}")
        tb.last_prompt()
        fx.write_jsonl(self.source, tb.records)
        for active, overflow in ((True, "error"), (False, "fold")):
            options = dict(target_ratio=.05, min_recent_records=2, summary_char_budget=16000,
                           target_estimated_tokens=15000, preserve_active_chain=active,
                           preserve_prior_summaries_verbatim=True, prior_summary_overflow=overflow,
                           append_final_prompt=True, target_session_id="normalized", single_resume_chain=True)
            with self.subTest(active=active):
                with mock.patch.object(ccj, "build_model_summary_pack_payload",
                                       wraps=ccj.build_model_summary_pack_payload) as build:
                    pre = ccj.preflight_jsonl(self.source, **options)
                    self.assertEqual(build.call_count, 1)
                self.assertEqual(pre["state"], "budget-pending-draft", pre)
                pack = ccj.build_model_summary_pack_for_input(self.source, **options)
                model = self.root / "model.md"
                model.write_text(ProtocolBase().model_summary(pack), encoding="utf-8")
                output = self.root / "candidate.jsonl"
                report = ccj.compress_jsonl(self.source, output, model_summary_path=model, **options)
                bound = pack["fixed_candidate_lower_bound_tokens"]
                self.assertEqual(pre["estimates"]["fixedLowerBoundTokens"], bound)
                self.assertLessEqual(bound, report["output_estimated_message_tokens"])
                self.assertEqual(report["output_estimated_message_tokens"],
                                 ccj.estimate_records_tokens(fx.read_jsonl(output)))
                # Rebind both passes to the exact accepted size. With this input the
                # ratio, selected suffix, and character lengths of digest fields are stable.
                options["target_estimated_tokens"] = report["output_estimated_message_tokens"]
                exact = ccj.build_model_summary_pack_for_input(self.source, **options)
                model.write_text(ProtocolBase().model_summary(exact), encoding="utf-8")
                repeat = ccj.compress_jsonl(self.source, output, model_summary_path=model, **options)
                self.assertEqual(repeat["output_estimated_message_tokens"], options["target_estimated_tokens"])

    def test_nothing_to_summarize_skips_candidate_and_pack_floor(self):
        tb = fx.TranscriptBuilder("unchanged")
        tb.user("Single request.")
        tb.assistant_text("A reply.")
        tb.last_prompt()
        fx.write_jsonl(self.source, tb.records)
        with mock.patch.object(ccj, "build_model_summary_pack_payload", side_effect=AssertionError):
            pre = ccj.preflight_jsonl(self.source, target_estimated_tokens=1000)
        self.assertEqual(pre["state"], "nothing-to-summarize", pre)
        self.assertIsNone(pre["pack"])

    def test_multiple_active_compacts_and_rewound_compact(self):
        self.tb.records.pop()
        ancestor = self.tb.prev_uuid
        self.tb.compact_pair("A generated summary.", codex=True)
        self.tb.compact_pair("A subsequent native summary.")
        self.tb.user("Continue.")
        self.tb.assistant_text("Current reply.")
        self.tb.last_prompt()
        fx.write_jsonl(self.source, self.tb.records)
        self.assertTrue(ccj.validate_jsonl(self.source)["ok"])
        self.assertTrue(ccj.preflight_jsonl(self.source, .05, 2, 8000)["activeChain"]["ok"])
        self.tb.prev_uuid = ancestor
        self.tb.user("Rewound here.")
        self.tb.assistant_text("Rewound reply.")
        self.tb.last_prompt()
        fx.write_jsonl(self.source, self.tb.records)
        self.assertTrue(ccj.validate_jsonl(self.source)["ok"])
        self.tb.records[-2]["parentUuid"] = "missing-node"
        fx.write_jsonl(self.source, self.tb.records)
        self.assertFalse(ccj.validate_jsonl(self.source)["ok"])

    def test_locked_text_adds_to_recent_token_floor(self):
        tb = fx.TranscriptBuilder("example")
        tb.compact_pair("字" * 3500)
        for i in range(12):
            tb.user(f"Question {i}")
            tb.assistant_text(f"Answer {i}")
        tb.last_prompt()
        fx.write_jsonl(self.source, tb.records)
        options = dict(target_ratio=.05, min_recent_records=2, summary_char_budget=10000,
                       preserve_prior_summaries_verbatim=True, prior_summary_overflow="error",
                       target_estimated_tokens=2000)
        self.assertFalse(ccj.preflight_jsonl(self.source, **options)["ok"])
        for operation in (
            lambda: ccj.build_model_summary_pack_for_input(self.source, **options),
            lambda: ccj.compress_jsonl(self.source, self.root / "budget.jsonl",
                                       deterministic_summary=True, **options),
        ):
            with self.assertRaisesRegex(ValueError, "fixed recent raw and locked"):
                operation()

    def test_case_alias_and_symlink_roles(self):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            if os.name == "nt":
                path = self.source.with_name(self.source.name.upper())
                with self.assertRaisesRegex(ValueError, "different files"):
                    ccj.guard_artifact_roles(self.source, pack=path)
        link = self.root / "symlink.md"
        try:
            link.symlink_to(self.source)
        except OSError:
            if os.name != "nt":
                raise
            # Windows allows unprivileged directory junctions when file symlinks require a privilege.
            import _winapi
            target_dir = self.root / "target-dir"
            target_dir.mkdir()
            target = target_dir / "source.jsonl"
            os.link(self.source, target)
            junction = self.root / "junction"
            _winapi.CreateJunction(str(target_dir), str(junction))
            link = junction / target.name
            self.assertEqual(link.resolve(), target.resolve())
        with self.assertRaisesRegex(ValueError, "different files"):
            ccj.guard_artifact_roles(self.source, pack=link)

    def test_truncate_and_mixed_reminder(self):
        text = "a " * 500
        result = ccj.truncate(text, 500)
        prefix, marker = result.split("\n...")
        self.assertEqual(int(re.search(r"\d+", marker).group()), len(text) - len(prefix))
        self.assertLessEqual(len(result), 500)
        obj = {"type":"user","message":{"role":"user","content":"<system-reminder>hint</system-reminder> Retain this."}}
        self.assertEqual(ccj.user_record_origin(obj), "mixed")
        self.assertTrue(ccj.is_human_user_record(obj))

    def test_closed_descendants_require_unique_authorization(self):
        tb = fx.TranscriptBuilder("example")
        tb.user("Inspect the note.")
        tb.tool_call_pair()
        result = tb.records.pop()
        leaf = tb.records[-1]["uuid"]
        tb.last_prompt(leaf)
        tb.add_raw(result)
        closed = tb.assistant_text("Finished.")
        tb.records[-1]["message"]["stop_reason"] = "end_turn"
        path = fx.write_jsonl(self.root / "lag.jsonl", tb.records)
        pre = ccj.preflight_jsonl(path)
        self.assertEqual(pre["topology"]["selectedLeafUuid"], leaf)
        self.assertFalse(pre["activeChain"]["ok"])
        self.assertEqual(pre["closedTurnCandidates"], [
            {"leafUuid": closed, "additionalRecords": 2, "isSelectedChainPrefix": True,
             "roles": {"user": 1, "assistant": 1}, "replyPreview": "Finished."}])
        self.assertTrue(ccj.choose_resume_leaf_info(tb.records, resume_leaf_override=closed)["ok"])
        self.assertEqual(ccj.choose_resume_leaf_info(tb.records, 2)["selectedLeafUuid"], closed)
        tb.prev_uuid = result["uuid"]
        second = tb.assistant_text("Another result.")
        tb.records[-1]["message"]["stop_reason"] = "end_turn"
        self.assertEqual(len(ccj.closed_turn_candidates(tb.records, tb.records[2])), 2)
        self.assertFalse(ccj.choose_resume_leaf_info(tb.records, resume_leaf_override=second)["ok"])
        tb.records.pop()
        tb.prev_uuid = closed
        tb.user("A new task.")
        self.assertFalse(ccj.choose_resume_leaf_info(tb.records, resume_leaf_override=closed)["ok"])

    def test_closed_api_reply_with_owned_trailing_metadata(self):
        tb = fx.TranscriptBuilder("museum-session")
        tb.user("Check the catalogue.")
        tb.tool_call_pair()
        result = tb.records.pop()
        pointer_leaf = tb.records[-1]["uuid"]
        tb.last_prompt(pointer_leaf)
        tb.add_raw(result)
        answer = tb.assistant_text("Catalogue checked.")
        tb.records[-1]["message"]["stop_reason"] = "end_turn"
        metadata = [
            {"uuid": "note-end", "type": "attachment", "attachment": {"type": "info"},
             "parentUuid": answer, "sessionId": tb.session_id},
            {"uuid": "clock-end", "type": "system", "subtype": "turn_duration",
             "parentUuid": "note-end", "sessionId": tb.session_id},
        ]
        rows = [*tb.records, *metadata]
        source = fx.write_jsonl(self.root / "catalogue.jsonl", rows)
        pre = ccj.preflight_jsonl(source)
        self.assertEqual(pre["topology"]["selectedLeafUuid"], pointer_leaf)
        choice, = pre["closedTurnCandidates"]
        self.assertEqual(choice["leafUuid"], answer)
        self.assertEqual(choice["trailingMetadata"], {"count": 2, "firstRecord": len(rows)-1,
                         "lastRecord": len(rows), "types": {"attachment": 1, "system": 1}})
        explicit = ccj.choose_resume_leaf_info(rows, resume_leaf_override=answer)
        self.assertTrue(explicit["ok"], explicit["errors"])
        self.assertEqual(explicit["activeChainUuids"][-1], answer)
        misplaced = [*tb.records[:-1], metadata[0], tb.records[-1]]
        self.assertFalse(ccj.choose_resume_leaf_info(misplaced, resume_leaf_override=answer)["ok"])
        for tail in (
            dict(metadata[-1], subtype="unknown-hook"), dict(metadata[-1], sessionId="another-session"),
            dict(metadata[-1], isSidechain=True), dict(metadata[-1], type="user", message={"role":"user","content":"New work"}),
            dict(metadata[-1], uuid=answer),
        ):
            with self.subTest(tail=tail):
                self.assertFalse(ccj.choose_resume_leaf_info([*rows[:-1], tail], resume_leaf_override=answer)["ok"])

    def test_snapshot_ownership_and_controls(self):
        controls = [{"type": "permission-mode", "permissionMode": "default"},
                    {"type": "permission-mode", "permissionMode": "default"},
                    {"type": "agent-name", "agentName": "Example"}]
        self.tb.records.insert(0, controls[0])
        self.tb.records.extend(controls[1:])
        leaf = self.tb.prev_uuid
        self.tb.user("Other branch.", parent=None)
        side = self.tb.prev_uuid
        self.tb.add_raw({"type": "file-history-snapshot", "messageId": leaf, "snapshot": {
            "trackedFileBackups": {"note": {"backupFileName": "missing-file"}}}})
        self.tb.add_raw({"type": "file-history-snapshot", "messageId": leaf, "snapshot":{"messageId": side}})
        fx.write_jsonl(self.source, self.tb.records)
        output = self.root / "snapshot-out.jsonl"
        report = ccj.compress_jsonl(self.source, output, .05, 2, 10000, deterministic_summary=True)
        self.assertEqual(report["file_history_snapshots_preserved"], 1)
        self.assertEqual(report["snapshot_diagnostics"]["uncertainSourceRecords"], [len(self.tb.records)])
        self.assertEqual(report["snapshot_diagnostics"]["externalBackupContents"], "unverified")
        self.assertEqual([r for r in fx.read_jsonl(output) if r["type"] in ("agent-name", "permission-mode")], controls)

    def test_derived_reports_cannot_alias_source_or_summary(self):
        output = self.root / "candidate.jsonl"
        for suffix in (".validation.json", ".report.md", ".repair.json"):
            alias = output.with_name(output.name + suffix)
            os.link(self.source, alias)
            with self.subTest(suffix=suffix), contextlib.redirect_stderr(io.StringIO()):
                original = self.source.read_bytes()
                args = ["--input", str(self.source), "--output", str(output)]
                if suffix == ".repair.json":
                    result = fx.rcj.main(args)
                else:
                    result = ccj.main(args + ["--deterministic-summary"])
                self.assertNotEqual(result, 0)
                self.assertFalse(output.exists())
                self.assertEqual(self.source.read_bytes(), original)
            alias.unlink()

    def test_resumed_history_can_be_repaired(self):
        candidate = self.root / "base.jsonl"
        ccj.compress_jsonl(self.source, candidate, .05, 2, 9000, deterministic_summary=True)
        rows = fx.read_jsonl(candidate)
        self.tb.records = rows
        self.tb.prev_uuid = rows[-1]["leafUuid"]
        self.tb.user("Read again.")
        self.tb.tool_call_pair()
        self.tb.records[-2]["message"]["content"][-1]["input"]["pages"] = ""
        self.tb.last_prompt()
        fx.write_jsonl(self.source, self.tb.records)
        repaired = self.root / "repair.jsonl"
        with contextlib.redirect_stdout(io.StringIO()):
            status = fx.rcj.main(["--input", str(self.source), "--output", str(repaired), "--expect-matches", "1"])
        self.assertEqual(status, 0)
        self.assertTrue(ccj.validate_jsonl(repaired)["ok"])
        self.assertFalse(ccj.validate_jsonl(repaired, contract="fresh-candidate")["ok"])

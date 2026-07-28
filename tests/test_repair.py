#!/usr/bin/env python3
"""Strict tests for the byte-preserving Read.pages compatibility repair."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _fixtures as fx


ccj = fx.ccj
rcj = fx.rcj


def add_pages_to_latest_read(records, value="1-2"):
    for record in reversed(records):
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in reversed(content):
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Read":
                block["input"]["pages"] = value
                return block["id"]
    raise AssertionError("fixture contains no Read tool_use")


class RepairBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="cjc_repair_")
        self.tmp = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def build_source(self, page_values=("1-2",), bom=False, crlf=False):
        tb = fx.TranscriptBuilder("91919191-9191-9191-9191-919191919191")
        for i, value in enumerate(page_values):
            tb.user(f"read source {i}")
            tb.tool_call_pair(file_path=f"C:\\synthetic\\source{i}.pdf")
            add_pages_to_latest_read(tb.records, value)
        for i in range(25):
            tb.user(f"continue {i}")
            tb.assistant_text(f"result {i}")
        tb.last_prompt()
        newline = b"\r\n" if crlf else b"\n"
        body = newline.join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            for record in tb.records
        ) + newline
        if bom:
            body = b"\xef\xbb\xbf" + body
        return tb, body

    def build_read_pair(
        self,
        *,
        tool_session="a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1",
        result_session=None,
        source_uuid="__tool__",
    ):
        result_session = result_session if result_session is not None else tool_session
        root_uuid = "11111111-aaaa-4111-8111-111111111111"
        tool_uuid = "22222222-bbbb-4222-8222-222222222222"
        result_uuid = "33333333-cccc-4333-8333-333333333333"
        tool_id = "toolu_anonymous_read"
        if source_uuid == "__tool__":
            source_uuid = tool_uuid
        records = [
            {
                "type": "user", "uuid": root_uuid, "parentUuid": None,
                "sessionId": tool_session,
                "message": {"role": "user", "content": "synthetic read"},
            },
            {
                "type": "assistant", "uuid": tool_uuid, "parentUuid": root_uuid,
                "sessionId": tool_session,
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use", "id": tool_id, "name": "Read",
                        "input": {"file_path": "C:\\synthetic\\anonymous.pdf", "pages": "1-2"},
                    }],
                },
            },
            {
                "type": "user", "uuid": result_uuid, "parentUuid": tool_uuid,
                "sessionId": result_session, "sourceToolAssistantUUID": source_uuid,
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}],
                },
            },
            {"type": "last-prompt", "leafUuid": result_uuid, "sessionId": result_session},
        ]
        return records

    def assert_read_pair_is_not_patchable(self, source, *, scope="active-chain"):
        try:
            plan = rcj.plan_read_pages_repairs(source, scope=scope)
        except ValueError:
            return
        self.assertEqual(plan["patchableMatchCount"], 0, plan["matches"])
        self.assertEqual(rcj.apply_patch_plan(source, plan), source)


class TestReadPagesPlanning(RepairBase):
    def test_value_matrix_is_removed_without_reserializing_other_bytes(self):
        values = ["", "1-2", 7, [1, 2], {"from": 1}, True, None]
        _tb, source = self.build_source(values, bom=True, crlf=True)
        plan = rcj.plan_read_pages_repairs(source)
        self.assertEqual(plan["patchableMatchCount"], len(values))
        output = rcj.apply_patch_plan(source, plan)
        validation = rcj.validate_repair(source, output, plan)
        self.assertTrue(validation["ok"], validation["errors"])
        self.assertTrue(output.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(output.count(b"\r\n"), source.count(b"\r\n"))
        repaired, _ = ccj.parse_jsonl_bytes(output)
        for record in repaired:
            message = record.get("message")
            for block in message.get("content", []) if isinstance(message, dict) else []:
                if isinstance(block, dict) and block.get("name") == "Read":
                    self.assertNotIn("pages", block.get("input", {}))
                    self.assertIn("file_path", block.get("input", {}))

    def test_unicode_escaped_pages_key_is_found(self):
        _tb, source = self.build_source(["3-4"])
        source = source.replace(b'"pages":"3-4"', b'"p\\u0061ges":"3-4"', 1)
        plan = rcj.plan_read_pages_repairs(source)
        self.assertEqual(plan["patchableMatchCount"], 1)
        output = rcj.apply_patch_plan(source, plan)
        self.assertNotIn(b"p\\u0061ges", output)
        self.assertTrue(rcj.validate_repair(source, output, plan)["ok"])

    def test_pending_call_is_reported_but_not_modified(self):
        tb = fx.TranscriptBuilder("92929292-9292-9292-9292-929292929292")
        tb.user("pending read")
        tool_id = "toolu_pending"
        assistant_uuid = tb.assistant_text("placeholder")
        record = tb.records[-1]
        record["message"]["content"] = [{
            "type": "tool_use", "id": tool_id, "name": "Read",
            "input": {"file_path": "C:\\synthetic\\pending.pdf", "pages": "1"},
        }]
        tb.last_prompt(assistant_uuid)
        source = ccj.jsonl_bytes(tb.records)
        plan = rcj.plan_read_pages_repairs(source)
        self.assertEqual(plan["targetMatchCount"], 1)
        self.assertEqual(plan["patchableMatchCount"], 0)
        self.assertEqual(plan["pendingMatchCount"], 1)
        self.assertEqual(rcj.apply_patch_plan(source, plan), source)

    def test_similar_tools_and_plain_text_are_untouched(self):
        tb = fx.TranscriptBuilder("93939393-9393-9393-9393-939393939393")
        tb.user("similar tools")
        tb.tool_call_pair(tool_name="ReadX", file_path="C:\\synthetic\\a.pdf")
        tb.records[-2]["message"]["content"][-1]["input"]["pages"] = "1"
        tb.assistant_text('plain text with {"name":"Read","pages":"2"}')
        tb.last_prompt()
        source = ccj.jsonl_bytes(tb.records)
        plan = rcj.plan_read_pages_repairs(source)
        self.assertEqual(plan["targetMatchCount"], 0)
        self.assertEqual(rcj.apply_patch_plan(source, plan), source)

    def test_duplicate_key_stops_before_edit(self):
        _tb, source = self.build_source(["1"])
        source = source.replace(b'"pages":"1"', b'"pages":"0","pages":"1"', 1)
        with self.assertRaisesRegex(ValueError, "duplicate JSON keys"):
            rcj.plan_read_pages_repairs(source)

    def test_second_pass_is_byte_identical(self):
        _tb, source = self.build_source(["1", "2"])
        plan = rcj.plan_read_pages_repairs(source)
        once = rcj.apply_patch_plan(source, plan)
        second_plan = rcj.plan_read_pages_repairs(once)
        self.assertEqual(second_plan["patchableMatchCount"], 0)
        self.assertEqual(rcj.apply_patch_plan(once, second_plan), once)

    def test_unicode_line_separators_inside_json_string_are_not_record_boundaries(self):
        _tb, source = self.build_source(["1"])
        replacement = '"content":"alpha\u2028beta\u2029gamma\u0085delta"'.encode("utf-8")
        source = source.replace(b'"content":"ok"', replacement, 1)
        records, _ = ccj.parse_jsonl_bytes(source)
        spans = rcj.jsonl_record_spans(source)
        self.assertEqual(len(spans), len(records))
        plan = rcj.plan_read_pages_repairs(source)
        self.assertEqual(plan["patchableMatchCount"], 1)
        output = rcj.apply_patch_plan(source, plan)
        self.assertTrue(rcj.validate_repair(source, output, plan)["ok"])

    def test_duplicate_keys_anywhere_in_physical_file_block_repair(self):
        _tb, source = self.build_source(["1"])
        source += b'{"type":"custom-title","title":"first","title":"second"}\n'
        with self.assertRaisesRegex(ValueError, "duplicate JSON keys"):
            rcj.plan_read_pages_repairs(source)

    def test_earlier_tool_result_does_not_pair_with_later_read_call(self):
        tb = fx.TranscriptBuilder("96969696-9696-9696-9696-969696969696")
        tb.user("setup")
        stale_id = "toolu_stale_before_use"
        tb.user("placeholder")
        tb.records[-1]["message"]["content"] = [{
            "type": "tool_result", "tool_use_id": stale_id, "content": "stale",
        }]
        read_uuid = tb.assistant_text("placeholder")
        tb.records[-1]["message"]["content"] = [{
            "type": "tool_use", "id": stale_id, "name": "Read",
            "input": {"file_path": "C:\\synthetic\\later.pdf", "pages": "1"},
        }]
        tb.last_prompt(read_uuid)
        source = ccj.jsonl_bytes(tb.records)
        plan = rcj.plan_read_pages_repairs(source)
        self.assertEqual(plan["patchableMatchCount"], 0)
        self.assertEqual(plan["pendingMatchCount"], 1)
        self.assertEqual(rcj.apply_patch_plan(source, plan), source)

    def test_read_pair_does_not_cross_one_way_session_lineage(self):
        records = self.build_read_pair(
            result_session="b2b2b2b2-b2b2-b2b2-b2b2-b2b2b2b2b2b2",
        )
        source = ccj.jsonl_bytes(records)
        topology = ccj.choose_resume_leaf_info(records)
        self.assertTrue(topology["ok"], topology["errors"])
        self.assertTrue(topology["sessionLineageCompatibility"])
        self.assert_read_pair_is_not_patchable(source)

    def test_read_pair_requires_matching_session_ids_even_in_all_scope(self):
        source = ccj.jsonl_bytes(self.build_read_pair(result_session="different-session"))
        self.assert_read_pair_is_not_patchable(source, scope="all")

    def test_read_pair_requires_matching_source_tool_assistant_link(self):
        records = self.build_read_pair(source_uuid="44444444-dddd-4444-8444-444444444444")
        source = ccj.jsonl_bytes(records)
        self.assert_read_pair_is_not_patchable(source)

    def test_candidate_publication_revalidates_the_actual_published_bytes(self):
        _tb, source = self.build_source(["1"])
        src = self.tmp / "source.jsonl"
        out = self.tmp / "candidate.jsonl"
        src.write_bytes(source)
        real_atomic_write = ccj.atomic_write_bytes

        def publish_then_mutate(path, data):
            real_atomic_write(path, data)
            if pathlib.Path(path) == out:
                out.write_bytes(source)

        with mock.patch.object(ccj, "atomic_write_bytes", side_effect=publish_then_mutate):
            with mock.patch.object(rcj, "validate_repair", wraps=rcj.validate_repair) as validate_repair:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = rcj.main([
                        "--input", str(src), "--output", str(out), "--expect-matches", "1",
                    ])
        self.assertEqual(code, 1, "structurally valid unrepaired published bytes were reported as success")
        self.assertTrue(validate_repair.called)
        self.assertFalse(out.exists(), "failed repair candidate should be removed when no prior destination existed")


class TestStructuralClosureBlockers(RepairBase):
    def build_post_prompt_tool_closure(self, closure_session="__same__", gap=None):
        session_id = "c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3"
        root_uuid = "55555555-eeee-4555-8555-555555555555"
        tool_uuid = "66666666-ffff-4666-8666-666666666666"
        result_uuid = "77777777-aaaa-4777-8777-777777777777"
        tool_id = "toolu_post_prompt"
        records = [
            {
                "type": "user", "uuid": root_uuid, "parentUuid": None,
                "sessionId": session_id, "message": {"role": "user", "content": "synthetic"},
            },
            {
                "type": "assistant", "uuid": tool_uuid, "parentUuid": root_uuid,
                "sessionId": session_id,
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use", "id": tool_id, "name": "Read",
                        "input": {"file_path": "C:\\synthetic\\closure.pdf"},
                    }],
                },
            },
            {"type": "last-prompt", "leafUuid": tool_uuid, "sessionId": session_id},
        ]
        if gap is not None:
            records.append(gap)
        closure = {
            "type": "user", "uuid": result_uuid, "parentUuid": tool_uuid,
            "sourceToolAssistantUUID": tool_uuid,
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}],
            },
        }
        if closure_session == "__same__":
            closure["sessionId"] = session_id
        elif closure_session != "__missing__":
            closure["sessionId"] = closure_session
        records.append(closure)
        return records

    def test_post_prompt_extension_requires_nonempty_string_session_id(self):
        invalid_session_ids = ["__missing__", "", [], 7]
        for invalid_session_id in invalid_session_ids:
            with self.subTest(sessionId=repr(invalid_session_id)):
                records = self.build_post_prompt_tool_closure(invalid_session_id)
                info = ccj.choose_resume_leaf_info(records, max_post_prompt_extension=4)
                self.assertFalse(info["ok"], info)

    def test_post_prompt_extension_rejects_uuidless_record_before_closure(self):
        records = self.build_post_prompt_tool_closure(
            gap={
                "type": "attachment", "sessionId": "c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3",
                "attachment": {"type": "synthetic", "content": "anonymous"},
            },
        )
        info = ccj.choose_resume_leaf_info(records, max_post_prompt_extension=4)
        self.assertFalse(info["ok"], info)

    def test_orphan_tool_result_after_attachment_terminates_and_fails_closed(self):
        script = f"""
import sys
sys.path.insert(0, {str(fx.SCRIPTS_DIR)!r})
import compress_claude_jsonl as ccj
records = [
    {{
        "type": "assistant", "uuid": "88888888-bbbb-4888-8888-888888888888",
        "parentUuid": None, "sessionId": "synthetic-session",
        "message": {{"role": "assistant", "content": [{{"type": "text", "text": "before"}}]}},
    }},
    {{
        "type": "attachment", "sessionId": "synthetic-session",
        "attachment": {{"type": "synthetic", "content": "separator"}},
    }},
    {{
        "type": "user", "uuid": "99999999-cccc-4999-8999-999999999999",
        "parentUuid": "88888888-bbbb-4888-8888-888888888888", "sessionId": "synthetic-session",
        "message": {{
            "role": "user",
            "content": [{{"type": "tool_result", "tool_use_id": "toolu_orphan", "content": "orphan"}}],
        }},
    }},
]
try:
    ccj.adjust_recent_start_for_tool_pairs(records, 1)
except ValueError:
    raise SystemExit(0)
raise SystemExit(7)
"""
        try:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=fx.SKILL_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(f"adjust_recent_start_for_tool_pairs did not terminate within 5 seconds: {exc}")
        self.assertEqual(
            completed.returncode,
            0,
            f"orphan tool_result did not fail closed; stdout={completed.stdout!r} stderr={completed.stderr!r}",
        )


class TestReadPagesScope(RepairBase):
    def test_default_active_scope_excludes_rewound_branch(self):
        tb, _source = self.build_source(["1"])
        active_leaf = tb.records[-2]["uuid"]
        tb.records[-1]["leafUuid"] = active_leaf
        tb.prev_uuid = tb.records[2]["uuid"]
        tb.user("dead branch")
        tb.tool_call_pair(file_path="C:\\synthetic\\dead.pdf")
        add_pages_to_latest_read(tb.records, "9")
        source = ccj.jsonl_bytes(tb.records)
        active_plan = rcj.plan_read_pages_repairs(source, scope="active-chain")
        all_plan = rcj.plan_read_pages_repairs(source, scope="all")
        self.assertEqual(active_plan["patchableMatchCount"], 1)
        self.assertEqual(all_plan["patchableMatchCount"], 2)
        active_output = rcj.apply_patch_plan(source, active_plan)
        self.assertIn(b'"pages":"9"', active_output)


class TestReadPagesCli(RepairBase):
    def test_scan_only_has_no_filesystem_side_effect(self):
        _tb, source = self.build_source(["1"])
        src = self.tmp / "scan.jsonl"
        src.write_bytes(source)
        before = src.read_bytes()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = rcj.main(["--input", str(src), "--scan-only", "--expect-matches", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(src.read_bytes(), before)
        self.assertEqual(list(self.tmp.iterdir()), [src])
        self.assertEqual(json.loads(stdout.getvalue())["patchableMatchCount"], 1)

    def test_candidate_mode_and_expectation_guard(self):
        _tb, source = self.build_source(["1"])
        src = self.tmp / "source.jsonl"
        out = self.tmp / "candidate.jsonl"
        src.write_bytes(source)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = rcj.main([
                "--input", str(src), "--output", str(out), "--expect-matches", "2",
            ])
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())
        self.assertIn("expected 2", err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            code = rcj.main(["--input", str(src), "--output", str(out), "--expect-matches", "1"])
        self.assertEqual(code, 0)
        self.assertTrue(out.exists())
        report_path = out.with_suffix(out.suffix + ".repair.json")
        self.assertTrue(report_path.exists())
        repair_report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(repair_report["reportSchemaVersion"], 1)
        self.assertEqual(src.read_bytes(), source)

    def test_replace_original_creates_numbered_backup(self):
        session_id = "94949494-9494-9494-9494-949494949494"
        tb, source = self.build_source(["1"])
        for record in tb.records:
            if isinstance(record.get("sessionId"), str):
                record["sessionId"] = session_id
        tb.records[-1]["sessionId"] = session_id
        source = ccj.jsonl_bytes(tb.records)
        live = self.tmp / ".claude" / "projects" / "project" / f"{session_id}.jsonl"
        live.parent.mkdir(parents=True)
        live.write_bytes(source)
        live.with_suffix(live.suffix + ".backup").write_bytes(b"existing")
        work = self.tmp / "work"
        with contextlib.redirect_stdout(io.StringIO()):
            code = rcj.main([
                "--input", str(live), "--replace-original", "--confirm-session-closed",
                "--work-dir", str(work),
                "--expect-matches", "1",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(live.with_suffix(live.suffix + ".backup1").read_bytes(), source)
        self.assertNotIn(b'"pages"', live.read_bytes())
        self.assertTrue(ccj.validate_jsonl(live)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

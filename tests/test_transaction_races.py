#!/usr/bin/env python3
"""Synthetic regressions for transaction race recovery."""
from __future__ import annotations

import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest import mock

import _fixtures as fx
from test_repair import RepairBase


ccj = fx.ccj
rcj = fx.rcj


class TestTransactionalRaceSafety(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="cjc_transaction_race_")
        self.tmp = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_concurrent_target_recreation_preserves_external_and_recovery_assets(self):
        session_id = "d4d4d4d4-d4d4-d4d4-d4d4-d4d4d4d4d4d4"
        original = ccj.jsonl_bytes(fx.build_linear(session_id, turns=12).records)
        candidate_bytes = ccj.jsonl_bytes(fx.build_linear(session_id, turns=14).records)
        external_bytes = ccj.jsonl_bytes(fx.build_linear(session_id, turns=16).records)
        target = self.tmp / f"{session_id}.jsonl"
        candidate = self.tmp / "candidate.jsonl"
        target.write_bytes(original)
        candidate.write_bytes(candidate_bytes)
        target.with_suffix(target.suffix + ".backup").write_bytes(b"preexisting-backup-slot")
        real_replace = ccj.os.replace

        def replace_then_recreate(source, destination):
            source_path = pathlib.Path(source)
            destination_path = pathlib.Path(destination)
            if source_path == target and ".old-" in destination_path.name:
                real_replace(source, destination)
                target.write_bytes(external_bytes)
                return
            real_replace(source, destination)

        with mock.patch.object(ccj.os, "replace", side_effect=replace_then_recreate):
            with self.assertRaisesRegex(RuntimeError, "recreated concurrently"):
                ccj._replace_file_after_validation(candidate, target)

        self.assertEqual(target.read_bytes(), external_bytes)
        recovery = target.with_suffix(target.suffix + ".backup1")
        self.assertTrue(recovery.exists(), "verified original recovery asset was discarded")
        self.assertEqual(recovery.read_bytes(), original)
        self.assertTrue(ccj.validate_jsonl_bytes(recovery.read_bytes())["ok"])

    def test_live_repair_rejects_structurally_valid_unrepaired_stage(self):
        fixture = RepairBase(methodName="runTest")
        fixture.setUp()
        try:
            _tb, source = fixture.build_source(["1"])
        finally:
            fixture.tearDown()
        live = self.tmp / "synthetic-live.jsonl"
        work = self.tmp / "work"
        live.write_bytes(source)
        real_atomic_write = ccj.atomic_write_bytes

        def publish_then_mutate(path, data):
            real_atomic_write(path, data)
            path = pathlib.Path(path)
            if path.name.endswith(".read-pages-repaired.jsonl"):
                path.write_bytes(source)

        with mock.patch.object(ccj, "is_under_claude_projects", return_value=True):
            with mock.patch.object(ccj, "claude_root_ancestor", return_value=None):
                with mock.patch.object(ccj, "atomic_write_bytes", side_effect=publish_then_mutate):
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        code = rcj.main([
                            "--input", str(live), "--replace-original", "--work-dir", str(work),
                            "--expect-matches", "1",
                        ])

        self.assertEqual(code, 1, "live repair reported success after publishing unrepaired bytes")
        self.assertEqual(live.read_bytes(), source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Synthetic contracts for structural and live-operation safety."""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import _fixtures as fx


ccj = fx.ccj
cst = fx.cst
rcj = fx.rcj


class TestStructuralSafetyContracts(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cjc_structural_safety_")
        self.tmp = pathlib.Path(self._tmp.name)
        ccj._SUMMARY_RESOURCES_CONFIGURED = False

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _transaction_files(self, label: str):
        session_id = "51515151-5151-5151-5151-515151515151"
        target = self.tmp / f"{label}-{session_id}.jsonl"
        candidate = self.tmp / f"{label}-candidate.jsonl"
        original = ccj.jsonl_bytes(fx.build_linear(session_id, turns=12).records)
        candidate_bytes = ccj.jsonl_bytes(fx.build_linear(session_id, turns=14).records)
        external = ccj.jsonl_bytes(fx.build_linear(session_id, turns=16).records)
        target.write_bytes(original)
        candidate.write_bytes(candidate_bytes)
        return target, candidate, original, candidate_bytes, external

    def _write_compressor_source(self, name: str = "source.jsonl") -> pathlib.Path:
        session_id = "61616161-6161-6161-6161-616161616161"
        return fx.write_jsonl(self.tmp / name, fx.build_linear(session_id, turns=40).records)

    def _write_repair_source(self, path: pathlib.Path) -> pathlib.Path:
        session_id = "71717171-7171-7171-7171-717171717171"
        transcript = fx.TranscriptBuilder(session_id)
        transcript.user("synthetic read request")
        transcript.tool_call_pair(file_path="C:\\synthetic\\anonymous.txt")
        for record in reversed(transcript.records):
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            read_call = next(
                (
                    block
                    for block in content
                    if isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Read"
                ),
                None,
            )
            if read_call is not None:
                read_call["input"]["pages"] = "1"
                break
        else:
            raise AssertionError("synthetic fixture contains no Read call")
        transcript.last_prompt()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ccj.jsonl_bytes(transcript.records))
        return path

    def _escaped_session_candidate(self, root: pathlib.Path):
        root.mkdir(parents=True, exist_ok=True)
        outside = self.tmp / "outside" / "outside-session.jsonl"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text(
            json.dumps({"type": "custom-title", "title": "synthetic outside title"}) + "\n",
            encoding="utf-8",
        )
        link = root / "linked-session.jsonl"
        try:
            link.symlink_to(outside)
        except (NotImplementedError, OSError):
            self.assertFalse(cst.is_same_or_inside(outside, root))
            enumeration = mock.patch.object(pathlib.Path, "rglob", return_value=[outside])
            return outside, enumeration
        return link, contextlib.nullcontext()

    def test_live_install_does_not_clobber_target_claimed_after_absence_check(self):
        target, candidate, original, _candidate_bytes, external = self._transaction_files("install-race")
        real_exists = pathlib.Path.exists
        race_injected = False

        def exists_then_claim(path):
            nonlocal race_injected
            exists = real_exists(path)
            if path == target and not exists and not race_injected:
                target.write_bytes(external)
                race_injected = True
                return False
            return exists

        error = None
        with mock.patch.object(pathlib.Path, "exists", new=exists_then_claim):
            try:
                ccj._replace_file_after_validation(candidate, target)
            except Exception as exc:  # Expected once publication is no-clobber.
                error = exc

        self.assertTrue(race_injected)
        self.assertIsNotNone(error, "live install accepted a target claimed in the publish interval")
        self.assertEqual(target.read_bytes(), external)
        self.assertEqual(target.with_suffix(target.suffix + ".backup").read_bytes(), original)

    def test_rollback_does_not_clobber_target_claimed_after_identity_check(self):
        target, candidate, original, candidate_bytes, external = self._transaction_files("rollback-race")
        real_read_bytes = pathlib.Path.read_bytes
        candidate_observations = 0

        def read_then_claim(path):
            nonlocal candidate_observations
            data = real_read_bytes(path)
            if path == target and data == candidate_bytes:
                candidate_observations += 1
                if candidate_observations == 2:
                    target.unlink()
                    target.write_bytes(external)
            return data

        real_validate = ccj.validate_jsonl_bytes
        validation_calls = 0

        def fail_published_validation(*args, **kwargs):
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 2:
                return {"ok": False, "errors": ["synthetic published validation failure"]}
            return real_validate(*args, **kwargs)

        error = None
        with mock.patch.object(pathlib.Path, "read_bytes", new=read_then_claim):
            with mock.patch.object(ccj, "validate_jsonl_bytes", side_effect=fail_published_validation):
                try:
                    ccj._replace_file_after_validation(candidate, target)
                except Exception as exc:
                    error = exc

        self.assertEqual(candidate_observations, 2, "rollback race was not injected")
        self.assertIsNotNone(error)
        self.assertEqual(target.read_bytes(), external, "rollback clobbered the concurrent target")
        self.assertEqual(target.with_suffix(target.suffix + ".backup").read_bytes(), original)

    def test_failure_cleanup_preserves_externally_recreated_backup_path(self):
        target, candidate, original, _candidate_bytes, external = self._transaction_files("backup-recreate")
        backup_path = target.with_suffix(target.suffix + ".backup")
        real_backup = ccj._exclusive_backup_from_bytes

        def backup_then_recreate(*args, **kwargs):
            backup = real_backup(*args, **kwargs)
            backup.unlink()
            backup.write_bytes(external)
            target.write_bytes(original + b"\n")
            return backup

        with mock.patch.object(ccj, "_exclusive_backup_from_bytes", side_effect=backup_then_recreate):
            with self.assertRaisesRegex(RuntimeError, "changed before replacement"):
                ccj._replace_file_after_validation(candidate, target)

        self.assertTrue(backup_path.exists(), "failure cleanup deleted an externally recreated pathname")
        self.assertEqual(backup_path.read_bytes(), external)

    def test_created_backup_remains_an_audit_asset_after_install_failure(self):
        target, candidate, original, _candidate_bytes, _external = self._transaction_files("backup-audit")
        backup_path = target.with_suffix(target.suffix + ".backup")
        real_publish = ccj._publish_no_clobber

        def fail_install(source, destination):
            source_path = pathlib.Path(source)
            if ".replace-" in source_path.name and pathlib.Path(destination) == target:
                raise OSError("synthetic candidate install failure")
            return real_publish(source, destination)

        with mock.patch.object(ccj, "_publish_no_clobber", side_effect=fail_install):
            with self.assertRaisesRegex(RuntimeError, "original bytes were restored"):
                ccj._replace_file_after_validation(candidate, target)

        self.assertTrue(backup_path.exists(), "a successfully created backup was discarded")
        self.assertEqual(backup_path.read_bytes(), original)

    def test_active_correlated_snapshots_require_null_uuid_and_parent_uuid(self):
        active_uuid = "81818181-8181-8181-8181-818181818181"
        session_id = "82828282-8282-8282-8282-828282828282"
        records = [
            {
                "type": "user",
                "uuid": active_uuid,
                "parentUuid": None,
                "sessionId": session_id,
                "message": {"role": "user", "content": "synthetic active record"},
            },
            {
                "type": "file-history-snapshot",
                "uuid": None,
                "parentUuid": None,
                "sourceUuid": active_uuid,
                "sessionId": session_id,
            },
            {
                "type": "file-history-snapshot",
                "uuid": 7,
                "parentUuid": None,
                "sourceUuid": active_uuid,
                "sessionId": session_id,
            },
            {
                "type": "file-history-snapshot",
                "uuid": None,
                "parentUuid": active_uuid,
                "sourceUuid": active_uuid,
                "sessionId": session_id,
            },
            {
                "type": "file-history-snapshot",
                "uuid": None,
                "parentUuid": {"synthetic": "invalid"},
                "sourceUuid": active_uuid,
                "sessionId": session_id,
            },
        ]

        selected = ccj.select_active_correlated_snapshot_indexes(
            records,
            active_indexes=[0],
            max_snapshots=10,
            authority_index=len(records),
        )

        self.assertEqual(selected, [1])

    def test_compressor_candidate_under_claude_root_is_rejected_before_writes(self):
        source = self._write_compressor_source()
        output = self.tmp / ".claude" / "artifacts" / "candidate.jsonl"
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            code = ccj.main(
                [
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--target-ratio",
                    "0.30",
                    "--min-recent-records",
                    "5",
                    "--summary-char-budget",
                    "4000",
                    "--deterministic-summary",
                ]
            )

        artifacts = [
            output,
            output.with_suffix(output.suffix + ".report.md"),
            output.with_suffix(output.suffix + ".validation.json"),
        ]
        self.assertEqual((code, [path.exists() for path in artifacts]), (1, [False, False, False]), stderr.getvalue())

    def test_compressor_model_pack_under_claude_root_is_rejected_before_writes(self):
        source = self._write_compressor_source("pack-source.jsonl")
        pack = self.tmp / ".claude" / "artifacts" / "candidate.model-pack.md"
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            code = ccj.main(
                [
                    "--input",
                    str(source),
                    "--write-model-pack",
                    str(pack),
                    "--target-ratio",
                    "0.30",
                    "--min-recent-records",
                    "5",
                    "--summary-char-budget",
                    "4000",
                    "--model-pack-char-budget",
                    "50000",
                ]
            )

        self.assertEqual((code, pack.exists()), (1, False), stderr.getvalue())

    def test_repair_candidate_and_report_under_claude_root_are_rejected_before_writes(self):
        source = self._write_repair_source(self.tmp / "repair-source.jsonl")
        output = self.tmp / ".claude" / "artifacts" / "repair-candidate.jsonl"
        report = output.with_suffix(output.suffix + ".repair.json")
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            code = rcj.main(["--input", str(source), "--output", str(output), "--expect-matches", "1"])

        self.assertEqual((code, output.exists(), report.exists()), (1, False, False), stderr.getvalue())

    def test_session_tools_backup_is_exclusive_during_concurrent_name_claim(self):
        source = self._write_compressor_source("backup-source.jsonl")
        original = source.read_bytes()
        claimed_path = source.with_suffix(source.suffix + ".backup")
        external = b"synthetic concurrent backup claim"
        real_numbered_path = cst.numbered_backup_path
        race_injected = False

        def numbered_path_then_claim(path):
            nonlocal race_injected
            candidate = real_numbered_path(path)
            if not race_injected:
                candidate.write_bytes(external)
                race_injected = True
            return candidate

        result = None
        error = None
        with mock.patch.object(cst, "numbered_backup_path", side_effect=numbered_path_then_claim):
            try:
                result = cst.create_backup(source)
            except Exception as exc:
                error = exc

        self.assertTrue(race_injected)
        self.assertEqual(claimed_path.read_bytes(), external, "create_backup overwrote a concurrent name claim")
        if result is not None:
            self.assertNotEqual(result, claimed_path)
            self.assertEqual(result.read_bytes(), original)
        else:
            self.assertIsNotNone(error)

    def test_session_listing_ignores_candidate_resolving_outside_root(self):
        root = self.tmp / "declared-root"
        candidate, enumeration = self._escaped_session_candidate(root)

        with enumeration:
            listed = cst.list_session_files(root)

        self.assertFalse(cst.is_same_or_inside(candidate, root))
        self.assertEqual(listed, [], "session listing exposed a file outside the declared root")

    def test_session_title_scan_ignores_candidate_resolving_outside_root(self):
        root = self.tmp / "declared-title-root"
        _candidate, enumeration = self._escaped_session_candidate(root)

        found = None
        with enumeration:
            try:
                found = cst.find_unique_session(root, "synthetic outside title", scan_titles=True)
            except FileNotFoundError:
                pass

        self.assertIsNone(found, f"title scan read an escaped session candidate: {found}")

    def test_live_compressor_requires_session_closed_ack_before_writes(self):
        session_id = "91919191-9191-9191-9191-919191919191"
        live = fx.write_jsonl(
            self.tmp / ".claude" / "projects" / "synthetic" / f"{session_id}.jsonl",
            fx.build_linear(session_id, turns=12).records,
        )
        work = self.tmp / "compressor-work"
        stderr = io.StringIO()
        with mock.patch.object(ccj, "compress_jsonl", side_effect=RuntimeError("live operation reached")) as operation:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = ccj.main(
                    [
                        "--input",
                        str(live),
                        "--replace-original",
                        "--work-dir",
                        str(work),
                        "--summary-char-budget",
                        "4000",
                        "--deterministic-summary",
                    ]
                )

        observed = (code, operation.called, work.exists(), "--confirm-session-closed" in stderr.getvalue())
        self.assertEqual(observed, (1, False, False, True), stderr.getvalue())

    def test_live_repair_requires_session_closed_ack_before_writes(self):
        session_id = "a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1"
        live = self._write_repair_source(
            self.tmp / ".claude" / "projects" / "synthetic" / f"{session_id}.jsonl"
        )
        work = self.tmp / "repair-work"
        stderr = io.StringIO()
        with mock.patch.object(
            rcj,
            "publish_repair_candidate",
            side_effect=RuntimeError("live operation reached"),
        ) as operation:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = rcj.main(
                    [
                        "--input",
                        str(live),
                        "--replace-original",
                        "--work-dir",
                        str(work),
                        "--expect-matches",
                        "1",
                    ]
                )

        observed = (code, operation.called, work.exists(), "--confirm-session-closed" in stderr.getvalue())
        self.assertEqual(observed, (1, False, False, True), stderr.getvalue())

    def test_live_compressor_rejects_non_jsonl_target_before_writes(self):
        session_id = "b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1"
        live = fx.write_jsonl(
            self.tmp / ".claude" / "projects" / "synthetic" / "not-a-session.txt",
            fx.build_linear(session_id, turns=12).records,
        )
        work = self.tmp / "compressor-non-jsonl-work"
        stderr = io.StringIO()
        with mock.patch.object(ccj, "compress_jsonl", side_effect=RuntimeError("live operation reached")) as operation:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = ccj.main(
                    [
                        "--input", str(live), "--replace-original", "--confirm-session-closed",
                        "--work-dir", str(work), "--summary-char-budget", "4000",
                        "--deterministic-summary",
                    ]
                )

        self.assertEqual((code, operation.called, work.exists()), (1, False, False), stderr.getvalue())
        self.assertIn(".jsonl session file", stderr.getvalue())
        self.assertFalse(live.with_suffix(live.suffix + ".backup").exists())

    def test_live_repair_rejects_non_jsonl_target_before_writes(self):
        live = self._write_repair_source(
            self.tmp / ".claude" / "projects" / "synthetic" / "not-a-session.txt"
        )
        work = self.tmp / "repair-non-jsonl-work"
        stderr = io.StringIO()
        with mock.patch.object(
            rcj,
            "plan_read_pages_repairs",
            side_effect=RuntimeError("live operation reached"),
        ) as operation:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = rcj.main(
                    [
                        "--input", str(live), "--replace-original", "--confirm-session-closed",
                        "--work-dir", str(work), "--expect-matches", "1",
                    ]
                )

        self.assertEqual((code, operation.called, work.exists()), (1, False, False), stderr.getvalue())
        self.assertIn(".jsonl session file", stderr.getvalue())
        self.assertFalse(live.with_suffix(live.suffix + ".backup").exists())

    def test_live_cli_parsers_accept_explicit_session_closed_acknowledgement(self):
        def parsed_ack(parse_args):
            try:
                args = parse_args(["--confirm-session-closed"])
            except SystemExit:
                return None
            return getattr(args, "confirm_session_closed", None)

        with contextlib.redirect_stderr(io.StringIO()):
            observed = (parsed_ack(ccj.parse_args), parsed_ack(rcj.parse_args))

        self.assertEqual(observed, (True, True))

    def test_session_listing_survives_a_short_name_root_on_windows(self):
        """A root written with 8.3 short components must still enumerate.

        The escape guard compares a child against its resolved form. Comparing
        resolve() with os.path.abspath() rejected every entry when any root
        component was a short name, because resolve() expands short names and
        abspath() does not, so the locator found nothing at all.
        """
        if sys.platform != "win32":
            self.skipTest("8.3 short names are a Windows-only path form")
        import ctypes

        with tempfile.TemporaryDirectory() as raw_dir:
            long_root = pathlib.Path(raw_dir) / "projects"
            long_root.mkdir(parents=True)
            session = long_root / "session-shortname.jsonl"
            session.write_text(
                json.dumps({"type": "custom-title", "title": "short name probe"}) + "\n",
                encoding="utf-8",
            )

            buffer = ctypes.create_unicode_buffer(1024)
            written = ctypes.windll.kernel32.GetShortPathNameW(str(long_root), buffer, 1024)
            if not written:
                self.skipTest("the filesystem did not provide a short path form")
            short_root = pathlib.Path(buffer.value)
            if short_root == long_root:
                self.skipTest("8.3 short names are disabled on this volume")

            listed = cst.list_session_files(short_root)
            self.assertEqual(len(listed), 1, f"short-name root enumerated nothing: {short_root}")
            self.assertEqual(listed[0].resolve(), session.resolve())
            self.assertEqual(
                cst.find_unique_session(short_root, "session-shortname").resolve(),
                session.resolve(),
            )

    def test_hardlink_preflight_stops_before_touching_the_live_target(self):
        """os.link is required by both publication and rollback.

        Without a preflight the failure would surface only after the original
        had been moved aside, and the rollback would then fail for the same
        reason, leaving the target absent.
        """
        record = {
            "type": "user",
            "uuid": "11111111-1111-1111-1111-111111111111",
            "parentUuid": None,
            "sessionId": "22222222-2222-2222-2222-222222222222",
            "message": {"role": "user", "content": "hello"},
        }
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as raw_dir:
            work = pathlib.Path(raw_dir)
            target = work / "session.jsonl"
            candidate = work / "candidate.jsonl"
            target.write_bytes(line)
            candidate.write_bytes(line)
            before = target.read_bytes()
            entries_before = sorted(path.name for path in work.iterdir())

            def refuse_link(_source, _destination):
                raise OSError(1, "operation not permitted")

            reached_backup = []
            real_backup = ccj._exclusive_backup_from_bytes

            def spy_backup(*args, **kwargs):
                reached_backup.append(True)
                return real_backup(*args, **kwargs)

            with mock.patch.object(ccj.os, "link", refuse_link):
                with mock.patch.object(ccj, "_exclusive_backup_from_bytes", spy_backup):
                    with self.assertRaises(RuntimeError) as caught:
                        ccj._replace_file_after_validation(candidate, target)

            message = str(caught.exception)
            # The preflight must reject before backup creation is attempted.
            # Without it the run still fails safely, but only once it reaches
            # backup publication, and the message is the low-level one that
            # does not tell the caller what to do about it.
            self.assertEqual(reached_backup, [], "preflight must run before backup creation")
            self.assertIn("hard-link support on the volume", message)
            self.assertIn("still untouched", message)
            self.assertTrue(target.exists(), "live target must survive the refusal")
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(sorted(path.name for path in work.iterdir()), entries_before)

    def test_hardlink_probe_cleans_up_and_passes_on_a_supported_volume(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            work = pathlib.Path(raw_dir)
            ccj.verify_hardlink_support(work)
            self.assertEqual(list(work.iterdir()), [])

    def test_old_python_is_warned_about_but_never_blocked(self):
        for module in (ccj, cst):
            with self.subTest(module=module.__name__):
                stderr = io.StringIO()
                with mock.patch.object(module, "MIN_SUPPORTED_PYTHON", (99, 0)):
                    with contextlib.redirect_stderr(stderr):
                        returned = module.warn_if_python_too_old()
                self.assertIsNotNone(returned, "an unsupported interpreter must be reported")
                self.assertIn("WARNING", stderr.getvalue())
                self.assertIn("Continuing anyway", stderr.getvalue())

    def test_supported_python_produces_no_warning(self):
        for module in (ccj, cst):
            with self.subTest(module=module.__name__):
                stderr = io.StringIO()
                with mock.patch.object(module, "MIN_SUPPORTED_PYTHON", (3, 0)):
                    with contextlib.redirect_stderr(stderr):
                        returned = module.warn_if_python_too_old()
                self.assertIsNone(returned)
                self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

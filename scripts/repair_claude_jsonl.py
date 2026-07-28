#!/usr/bin/env python3
"""Byte-preserving, explicit compatibility repairs for one Claude JSONL."""
from __future__ import annotations

import argparse
import collections
import copy
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import compress_claude_jsonl as ccj


JsonObj = Dict[str, Any]
RULE_NAME = "remove-unsupported-read-pages"


@dataclass
class Member:
    key: str
    start: int
    end: int
    value: "Node"


@dataclass
class Node:
    kind: str
    start: int
    end: int
    members: List[Member] = field(default_factory=list)
    items: List["Node"] = field(default_factory=list)


class SpanJsonParser:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def parse(self) -> Node:
        self._ws()
        node = self._value()
        self._ws()
        if self.pos != len(self.data):
            raise ValueError(f"unexpected trailing JSON bytes at offset {self.pos}")
        return node

    def _ws(self) -> None:
        while self.pos < len(self.data) and self.data[self.pos] in b" \t\r\n":
            self.pos += 1

    def _string(self) -> Tuple[str, int, int]:
        start = self.pos
        if self.pos >= len(self.data) or self.data[self.pos] != 0x22:
            raise ValueError(f"expected JSON string at offset {self.pos}")
        self.pos += 1
        while self.pos < len(self.data):
            byte = self.data[self.pos]
            if byte == 0x5C:
                self.pos += 2
                continue
            self.pos += 1
            if byte == 0x22:
                raw = self.data[start:self.pos].decode("utf-8", errors="strict")
                value = json.loads(raw)
                if not isinstance(value, str):
                    raise ValueError("parsed JSON key is not a string")
                return value, start, self.pos
        raise ValueError(f"unterminated JSON string at offset {start}")

    def _value(self) -> Node:
        self._ws()
        if self.pos >= len(self.data):
            raise ValueError("unexpected end of JSON")
        byte = self.data[self.pos]
        if byte == 0x7B:
            return self._object()
        if byte == 0x5B:
            return self._array()
        if byte == 0x22:
            _value, start, end = self._string()
            return Node("string", start, end)
        start = self.pos
        while self.pos < len(self.data) and self.data[self.pos] not in b",]} \t\r\n":
            self.pos += 1
        if self.pos == start:
            raise ValueError(f"invalid JSON value at offset {start}")
        json.loads(self.data[start:self.pos].decode("ascii", errors="strict"))
        return Node("scalar", start, self.pos)

    def _object(self) -> Node:
        start = self.pos
        self.pos += 1
        members: List[Member] = []
        self._ws()
        if self.pos < len(self.data) and self.data[self.pos] == 0x7D:
            self.pos += 1
            return Node("object", start, self.pos, members=members)
        while True:
            self._ws()
            key, key_start, _key_end = self._string()
            self._ws()
            if self.pos >= len(self.data) or self.data[self.pos] != 0x3A:
                raise ValueError(f"expected ':' after object key at offset {self.pos}")
            self.pos += 1
            value = self._value()
            members.append(Member(key, key_start, value.end, value))
            self._ws()
            if self.pos >= len(self.data):
                raise ValueError("unterminated JSON object")
            if self.data[self.pos] == 0x7D:
                self.pos += 1
                return Node("object", start, self.pos, members=members)
            if self.data[self.pos] != 0x2C:
                raise ValueError(f"expected ',' in object at offset {self.pos}")
            self.pos += 1

    def _array(self) -> Node:
        start = self.pos
        self.pos += 1
        items: List[Node] = []
        self._ws()
        if self.pos < len(self.data) and self.data[self.pos] == 0x5D:
            self.pos += 1
            return Node("array", start, self.pos, items=items)
        while True:
            items.append(self._value())
            self._ws()
            if self.pos >= len(self.data):
                raise ValueError("unterminated JSON array")
            if self.data[self.pos] == 0x5D:
                self.pos += 1
                return Node("array", start, self.pos, items=items)
            if self.data[self.pos] != 0x2C:
                raise ValueError(f"expected ',' in array at offset {self.pos}")
            self.pos += 1


def unique_member(node: Node, key: str) -> Optional[Member]:
    matches = [member for member in node.members if member.key == key]
    if len(matches) > 1:
        raise ValueError(f"duplicate JSON key in repair control path: {key}")
    return matches[0] if matches else None


def assert_no_duplicate_keys(node: Node) -> None:
    if node.kind == "object":
        counts = collections.Counter(member.key for member in node.members)
        duplicates = sorted(key for key, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate JSON keys make byte repair ambiguous: {duplicates[:20]}")
        for member in node.members:
            assert_no_duplicate_keys(member.value)
    elif node.kind == "array":
        for item in node.items:
            assert_no_duplicate_keys(item)


def member_deletion_span(object_node: Node, target: Member) -> Tuple[int, int]:
    index = object_node.members.index(target)
    if len(object_node.members) == 1:
        return target.start, target.end
    if index < len(object_node.members) - 1:
        return target.start, object_node.members[index + 1].start
    return object_node.members[index - 1].end, target.end


def jsonl_record_spans(data: bytes) -> List[Tuple[int, int, bytes]]:
    spans: List[Tuple[int, int, bytes]] = []
    offset = 0
    while offset < len(data):
        lf_index = data.find(b"\n", offset)
        physical_end = len(data) if lf_index < 0 else lf_index
        content_end = physical_end - 1 if physical_end > offset and data[physical_end - 1] == 0x0D else physical_end
        start = offset
        if start == 0 and data.startswith(b"\xef\xbb\xbf"):
            start = 3
        content = data[start:content_end]
        if content.strip():
            spans.append((start, content_end, content))
        if lf_index < 0:
            break
        offset = lf_index + 1
    return spans


def _node_at_tool_input(root: Node, block_index: int) -> Tuple[Node, Member]:
    message = unique_member(root, "message")
    if message is None or message.value.kind != "object":
        raise ValueError("matched assistant record has no object message node")
    content = unique_member(message.value, "content")
    if content is None or content.value.kind != "array" or block_index >= len(content.value.items):
        raise ValueError("matched tool_use block has no content-array node")
    block = content.value.items[block_index]
    if block.kind != "object":
        raise ValueError("matched tool_use block is not an object node")
    input_member = unique_member(block, "input")
    if input_member is None or input_member.value.kind != "object":
        raise ValueError("matched Read tool_use has no object input node")
    pages = unique_member(input_member.value, "pages")
    if pages is None:
        raise ValueError("matched Read tool_use pages key has no byte span")
    return input_member.value, pages


def plan_read_pages_repairs(
    source_bytes: bytes,
    scope: str = "active-chain",
    resume_leaf_override: Optional[str] = None,
) -> Dict[str, Any]:
    records, _raw_lines = ccj.parse_jsonl_bytes(source_bytes, source_label="SOURCE_JSONL")
    line_spans = jsonl_record_spans(source_bytes)
    if len(line_spans) != len(records):
        raise ValueError("record/span count mismatch while planning byte repair")
    parsed_roots: List[Node] = []
    for _line_start, _line_end, line_bytes in line_spans:
        root = SpanJsonParser(line_bytes).parse()
        assert_no_duplicate_keys(root)
        parsed_roots.append(root)
    topology: Optional[Dict[str, Any]] = None
    if scope == "active-chain":
        topology = ccj.require_resume_leaf_info(records, resume_leaf_override=resume_leaf_override)
        scope_indexes = set(topology.get("activeChainIndexes") or [])
    elif scope == "all":
        scope_indexes = set(range(len(records)))
    else:
        raise ValueError(f"unknown repair scope: {scope}")

    tool_use_occurrences: Dict[str, List[int]] = collections.defaultdict(list)
    tool_result_occurrences: Dict[str, List[int]] = collections.defaultdict(list)
    for record_index in sorted(scope_indexes):
        for tool_id in ccj.tool_use_ids(records[record_index]):
            tool_use_occurrences[tool_id].append(record_index)
        for tool_id in ccj.tool_result_ids(records[record_index]):
            tool_result_occurrences[tool_id].append(record_index)
    patches: List[Dict[str, Any]] = []
    matches: List[Dict[str, Any]] = []
    seen_target_ids: set = set()
    for record_index in sorted(scope_indexes):
        obj = records[record_index]
        if obj.get("type") != "assistant" or ccj.api_role(obj) != "assistant":
            continue
        message = obj.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        line_start, _line_end, line_bytes = line_spans[record_index]
        root_node = parsed_roots[record_index]
        for block_index, block in enumerate(content):
            if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("name") != "Read":
                continue
            tool_input = block.get("input")
            if not isinstance(tool_input, dict) or "pages" not in tool_input:
                continue
            tool_id = block.get("id")
            file_path = tool_input.get("file_path")
            if isinstance(tool_id, str) and len(tool_use_occurrences.get(tool_id, [])) > 1:
                raise ValueError(f"duplicate target tool_use id makes repair ambiguous: {tool_id}")
            if isinstance(tool_id, str) and len(tool_result_occurrences.get(tool_id, [])) > 1:
                raise ValueError(f"duplicate tool_result id makes repair ambiguous: {tool_id}")
            later_results = [
                result_index
                for result_index in tool_result_occurrences.get(tool_id, [])
                if result_index > record_index
            ] if isinstance(tool_id, str) else []
            result_index = later_results[0] if len(later_results) == 1 else None
            result_record = records[result_index] if isinstance(result_index, int) else None
            use_session = obj.get("sessionId")
            result_session = result_record.get("sessionId") if isinstance(result_record, dict) else None
            same_session = (
                isinstance(use_session, str)
                and bool(use_session)
                and isinstance(result_session, str)
                and bool(result_session)
                and use_session == result_session
            )
            assistant_uuid = obj.get("uuid")
            source_uuid = ccj.source_tool_assistant_uuid(result_record) if isinstance(result_record, dict) else None
            source_matches = (
                isinstance(assistant_uuid, str)
                and bool(assistant_uuid)
                and source_uuid == assistant_uuid
            )
            paired = len(later_results) == 1 and same_session and source_matches
            eligible = paired and isinstance(file_path, str) and bool(file_path)
            if eligible:
                reason = "eligible"
            elif len(later_results) != 1:
                reason = "pending-tool-result"
            elif not same_session:
                reason = "cross-session-tool-result"
            elif not source_matches:
                reason = "source-assistant-mismatch"
            else:
                reason = "missing-file-path"
            match = {
                "recordLine": record_index + 1,
                "blockIndex": block_index,
                "toolUseId": tool_id,
                "pairedToolResult": paired,
                "sameSession": same_session,
                "sourceAssistantMatches": source_matches,
                "eligible": eligible,
                "reason": reason,
            }
            matches.append(match)
            if not eligible:
                continue
            if tool_id in seen_target_ids:
                raise ValueError(f"duplicate target tool_use id makes repair ambiguous: {tool_id}")
            seen_target_ids.add(tool_id)
            input_node, pages_member = _node_at_tool_input(root_node, block_index)
            rel_start, rel_end = member_deletion_span(input_node, pages_member)
            patches.append(
                {
                    "start": line_start + rel_start,
                    "end": line_start + rel_end,
                    "recordLine": record_index + 1,
                    "blockIndex": block_index,
                    "toolUseId": tool_id,
                }
            )
    ordered = sorted(patches, key=lambda item: (item["start"], item["end"]))
    for left, right in zip(ordered, ordered[1:]):
        if left["end"] > right["start"]:
            raise ValueError("planned repair byte spans overlap")
    return {
        "rule": RULE_NAME,
        "scope": scope,
        "sourceSha256": ccj.sha256_hex(source_bytes),
        "sourceBytes": len(source_bytes),
        "recordCount": len(records),
        "targetMatchCount": len(matches),
        "patchableMatchCount": len(patches),
        "pendingMatchCount": sum(1 for item in matches if item["reason"] == "pending-tool-result"),
        "ineligibleMatchCount": sum(1 for item in matches if not item["eligible"]),
        "matches": matches,
        "patches": ordered,
        "resumeTopology": ccj.public_resume_leaf_info(topology),
    }


def apply_patch_plan(source_bytes: bytes, plan: Dict[str, Any]) -> bytes:
    output = source_bytes
    for item in reversed(plan.get("patches") or []):
        start = int(item["start"])
        end = int(item["end"])
        if not (0 <= start < end <= len(output)):
            raise ValueError(f"invalid repair span: {start}:{end}")
        output = output[:start] + output[end:]
    return output


def _uuid_parent_signature(records: Sequence[JsonObj]) -> List[Tuple[Any, Any, Any]]:
    return [(obj.get("type"), obj.get("uuid"), obj.get("parentUuid")) for obj in records]


def validate_repair(source_bytes: bytes, output_bytes: bytes, plan: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    expected = apply_patch_plan(source_bytes, plan)
    if output_bytes != expected:
        errors.append("output bytes differ outside the planned deletion spans")
    source_records, _ = ccj.parse_jsonl_bytes(source_bytes, source_label="SOURCE_JSONL")
    output_records, _ = ccj.parse_jsonl_bytes(output_bytes, source_label="REPAIRED_JSONL")
    if len(source_records) != len(output_records):
        errors.append("record count changed")
    if _uuid_parent_signature(source_records) != _uuid_parent_signature(output_records):
        errors.append("type/uuid/parentUuid signature changed")
    source_tool_ids = [
        (ccj.tool_use_ids(obj), ccj.tool_result_ids(obj)) for obj in source_records
    ]
    output_tool_ids = [
        (ccj.tool_use_ids(obj), ccj.tool_result_ids(obj)) for obj in output_records
    ]
    if source_tool_ids != output_tool_ids:
        errors.append("tool_use/tool_result identifier sequence changed")
    second_plan = plan_read_pages_repairs(
        output_bytes,
        scope=str(plan.get("scope") or "active-chain"),
        resume_leaf_override=(plan.get("resumeTopology") or {}).get("selectedLeafUuid")
        if (plan.get("resumeTopology") or {}).get("manualOverride") else None,
    )
    if second_plan.get("patchableMatchCount") != 0:
        errors.append("repair is not idempotent; a second pass still finds patchable matches")
    return {
        "ok": not errors,
        "errors": errors,
        "sourceSha256": ccj.sha256_hex(source_bytes),
        "outputSha256": ccj.sha256_hex(output_bytes),
        "sourceBytes": len(source_bytes),
        "outputBytes": len(output_bytes),
        "removedBytes": len(source_bytes) - len(output_bytes),
        "recordCount": len(output_records),
        "secondPassPatchableMatchCount": second_plan.get("patchableMatchCount"),
    }


def public_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(plan)
    result.pop("patches", None)
    return result


def publish_repair_candidate(
    path: pathlib.Path,
    source_bytes: bytes,
    output_bytes: bytes,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    if ccj.is_under_claude_root(path):
        raise ValueError("repair candidates and reports must be outside the entire .claude directory")
    expected_sha256 = ccj.sha256_hex(output_bytes)
    previous_bytes = path.read_bytes() if path.exists() else None
    try:
        ccj.atomic_write_bytes(path, output_bytes)
        published_bytes = path.read_bytes()
        if published_bytes != output_bytes or ccj.sha256_hex(published_bytes) != expected_sha256:
            raise RuntimeError("published repair candidate bytes differ from the validated repair snapshot")
        validation = validate_repair(source_bytes, published_bytes, plan)
        if not validation.get("ok"):
            raise ValueError(f"published repair candidate validation failed: {validation.get('errors')}")
        full_validation = ccj.validate_jsonl_bytes(published_bytes, source_label=path.name)
        validation["fullTranscriptValidation"] = full_validation
        if not full_validation.get("ok"):
            raise ValueError(
                "published repair candidate full transcript validation failed: "
                f"{full_validation.get('errors')}"
            )
        return validation
    except Exception:
        if previous_bytes is None:
            try:
                path.unlink()
                ccj.fsync_parent_directory(path)
            except FileNotFoundError:
                pass
        else:
            ccj.atomic_write_bytes(path, previous_bytes)
        raise


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="claude-jsonl-repair-read-pages",
        description="Scan or byte-preservingly remove historical Read.input.pages members from one Claude Code JSONL.",
    )
    parser.add_argument("--version", action="store_true", help="Print package, engine, and report versions")
    parser.add_argument("--input", type=pathlib.Path, help="One source Claude Code session JSONL")
    parser.add_argument("--output", type=pathlib.Path, help="Distinct repaired candidate path")
    parser.add_argument("--scan-only", action="store_true", help="Report matches without writing files")
    parser.add_argument("--replace-original", action="store_true", help="Transactionally replace one closed live .claude/projects session")
    parser.add_argument(
        "--confirm-session-closed",
        action="store_true",
        help="Required caller acknowledgement for --replace-original; this does not detect processes or locks.",
    )
    parser.add_argument("--work-dir", type=pathlib.Path, help="Required external candidate/report directory for --replace-original")
    parser.add_argument("--backup-dir", type=pathlib.Path, help="Optional external numbered-backup directory for --replace-original")
    parser.add_argument("--rule", choices=(RULE_NAME,), default=RULE_NAME, help=f"Repair rule; currently only {RULE_NAME}")
    parser.add_argument("--scope", choices=("active-chain", "all"), default="active-chain", help="Strict active chain by default; all scans every physical branch")
    parser.add_argument("--expect-matches", type=int, help="Require exactly N patchable matches before writing")
    parser.add_argument("--resume-leaf", help="Explicit active-chain recovery leaf override")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.version:
            print(
                json.dumps(
                    {
                        "packageVersion": ccj.PACKAGE_VERSION,
                        "engineVersion": ccj.CODEX_OFFLINE_COMPRESSION_VERSION,
                        "reportSchemaVersion": ccj.REPORT_SCHEMA_VERSION,
                    },
                    indent=2,
                )
            )
            return 0
        if not args.input:
            raise ValueError("--input is required")
        mode_count = int(args.scan_only) + int(bool(args.output)) + int(args.replace_original)
        if mode_count != 1:
            raise ValueError("choose exactly one mode: --scan-only, --output, or --replace-original")
        if args.replace_original and not args.work_dir:
            raise ValueError("--replace-original requires --work-dir")
        if args.replace_original and not args.confirm_session_closed:
            raise ValueError("--replace-original requires --confirm-session-closed before any live-session writes")
        if args.replace_original:
            if not ccj.is_under_claude_projects(args.input):
                raise ValueError("--replace-original is only for one .claude/projects session JSONL")
            ccj.require_live_session_jsonl(args.input)
        if args.confirm_session_closed and not args.replace_original:
            raise ValueError("--confirm-session-closed is only meaningful with --replace-original")
        if args.backup_dir and not args.replace_original:
            raise ValueError("--backup-dir requires --replace-original")
        if args.expect_matches is not None and args.expect_matches < 0:
            raise ValueError("--expect-matches must be non-negative")
        if args.output and args.output.resolve() == args.input.resolve():
            raise ValueError("--input and --output must be different files")
        for label, process_path in (
            ("--output", args.output),
            ("--work-dir", args.work_dir),
            ("--backup-dir", args.backup_dir),
        ):
            if process_path is not None and ccj.is_under_claude_root(process_path):
                raise ValueError(f"{label} process files must be outside the entire .claude directory")
        source_bytes = args.input.read_bytes()
        plan = plan_read_pages_repairs(source_bytes, scope=args.scope, resume_leaf_override=args.resume_leaf)
        if args.expect_matches is not None and plan["patchableMatchCount"] != args.expect_matches:
            raise ValueError(
                f"--expect-matches expected {args.expect_matches}, found {plan['patchableMatchCount']} patchable matches"
            )
        if args.scan_only:
            print(json.dumps(public_plan(plan), ensure_ascii=False, indent=2))
            return 0
        output_bytes = apply_patch_plan(source_bytes, plan)
        validation = validate_repair(source_bytes, output_bytes, plan)
        if not validation.get("ok"):
            raise ValueError(f"repair validation failed: {validation.get('errors')}")
        full_validation = ccj.validate_jsonl_bytes(output_bytes, source_label=args.input.name)
        validation["fullTranscriptValidation"] = full_validation
        if not full_validation.get("ok"):
            raise ValueError(
                "repair candidate full transcript validation failed: "
                f"{full_validation.get('errors')}"
            )
        replacing = False
        if args.replace_original:
            replacing = True
            claude_root = ccj.claude_root_ancestor(args.input)
            if claude_root and ccj.is_same_or_inside(args.work_dir, claude_root):
                raise ValueError("--work-dir must be outside the .claude directory")
            if claude_root and args.backup_dir and ccj.is_same_or_inside(args.backup_dir, claude_root):
                raise ValueError("--backup-dir must be outside the .claude directory")
            args.work_dir.mkdir(parents=True, exist_ok=True)
            output_path = args.work_dir / f"{args.input.stem}.read-pages-repaired.jsonl"
        else:
            output_path = args.output
        validation = publish_repair_candidate(output_path, source_bytes, output_bytes, plan)
        report = {
            "packageVersion": ccj.PACKAGE_VERSION,
            "engineVersion": ccj.CODEX_OFFLINE_COMPRESSION_VERSION,
            "reportSchemaVersion": ccj.REPORT_SCHEMA_VERSION,
            "input": ccj.public_path_label(args.input),
            "output": ccj.public_path_label(output_path),
            "plan": public_plan(plan),
            "validation": validation,
            "replaceOriginal": replacing,
        }
        if replacing:
            replacement = ccj._replace_file_after_validation(
                output_path,
                args.input,
                backup_dir=args.backup_dir,
                expected_source_sha256=plan["sourceSha256"],
                expected_candidate_sha256=validation["outputSha256"],
            )
            backup = replacement["backup_path"]
            report["replacementTarget"] = ccj.public_path_label(args.input)
            report["replacementBackup"] = ccj.public_path_label(backup)
            report["replacementValidation"] = replacement["validation"]
            report["replacementCandidateSha256"] = replacement["candidate_sha256"]
            report["replacementPublishedSha256"] = replacement["published_sha256"]
            report["replacementParentDirectoryFsync"] = replacement["parent_directory_fsync"]
        report_path = output_path.with_suffix(output_path.suffix + ".repair.json")
        try:
            ccj.atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        except Exception as report_exc:
            if replacing:
                receipt = {
                    "operationState": "committed-report-failed",
                    "replacementTarget": ccj.public_path_label(args.input),
                    "replacementBackup": report.get("replacementBackup"),
                    "replacementCandidate": ccj.public_path_label(output_path),
                    "sourceSha256": plan.get("sourceSha256"),
                    "candidateSha256": report.get("replacementCandidateSha256"),
                    "publishedSha256": report.get("replacementPublishedSha256"),
                    "replacementValidationOk": bool((report.get("replacementValidation") or {}).get("ok")),
                    "reportError": f"{type(report_exc).__name__}: {report_exc}",
                }
                print(json.dumps(receipt, ensure_ascii=False, indent=2))
                ccj.eprint(
                    "ERROR: live repair committed, but final report publication failed: "
                    f"{report_exc}"
                )
                return 3
            raise
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        ccj.eprint(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

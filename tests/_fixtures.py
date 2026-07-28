#!/usr/bin/env python3
"""Shared test fixtures and helpers for the claude-jsonl-compressor test suite.

No third-party dependencies. The skill scripts are imported as modules so tests
can drive them in-process (fast) and also assert on validator output directly.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys
import uuid
from typing import Any, Dict, List, Optional

# Make scripts/ importable regardless of where pytest/unittest is launched from.
SKILL_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import compress_claude_jsonl as ccj  # noqa: E402
import claude_session_tools as cst  # noqa: E402
import repair_claude_jsonl as rcj  # noqa: E402

JsonObj = Dict[str, Any]


def _ts(minute: int) -> str:
    base = datetime.datetime(2026, 6, 1, 9, 0, 0, tzinfo=datetime.timezone.utc)
    return (
        (base + datetime.timedelta(minutes=minute))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def write_jsonl(path: pathlib.Path, records: List[JsonObj]) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def read_jsonl(path: pathlib.Path) -> List[JsonObj]:
    out: List[JsonObj] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


class TranscriptBuilder:
    """Builds a linear-by-default Claude-style transcript with explicit control
    over parent links so tests can model branches, tool pairs, and snapshots."""

    def __init__(self, session_id: str, cwd: str = "C:\\work\\case", version: str = "1.0.0"):
        self.session_id = session_id
        self.cwd = cwd
        self.version = version
        self.records: List[JsonObj] = []
        self.prev_uuid: Optional[str] = None
        self._clock = 0

    def _base(self, rtype: str, **kw: Any) -> JsonObj:
        rec: JsonObj = {
            "parentUuid": self.prev_uuid,
            "isSidechain": False,
            "userType": "external",
            "cwd": self.cwd,
            "sessionId": self.session_id,
            "version": self.version,
            "gitBranch": "main",
            "type": rtype,
        }
        rec.update(kw)
        return rec

    def _add(self, rec: JsonObj) -> JsonObj:
        self.records.append(rec)
        uid = rec.get("uuid")
        if isinstance(uid, str):
            self.prev_uuid = uid
        return rec

    def add_raw(self, rec: JsonObj) -> JsonObj:
        """Append an arbitrary record verbatim (no parent rewrite)."""
        return self._add(rec)

    def user(self, text: str, parent: Optional[str] = "__chain__") -> str:
        uid = str(uuid.uuid4())
        rec = self._base("user", message={"role": "user", "content": text}, uuid=uid, timestamp=_ts(self._clock))
        if parent != "__chain__":
            rec["parentUuid"] = parent
        self._clock += 1
        self._add(rec)
        return uid

    def assistant_text(self, text: str) -> str:
        uid = str(uuid.uuid4())
        rec = self._base(
            "assistant",
            message={"id": f"msg_{self._clock}", "role": "assistant", "content": [{"type": "text", "text": text}]},
            uuid=uid,
            timestamp=_ts(self._clock),
        )
        self._clock += 1
        self._add(rec)
        return uid

    def tool_call_pair(self, tool_name: str = "Read", file_path: str = "C:\\work\\case\\doc.md") -> str:
        """Append an assistant tool_use + the matching user tool_result. Returns
        the uuid of the tool_result record (the new active leaf)."""
        tool_id = f"toolu_{self._clock}_{uuid.uuid4().hex[:6]}"
        a_uid = str(uuid.uuid4())
        self._add(
            self._base(
                "assistant",
                message={
                    "id": f"msg_{self._clock}",
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": f"reading {file_path}"},
                        {"type": "tool_use", "id": tool_id, "name": tool_name, "input": {"file_path": file_path}},
                    ],
                },
                uuid=a_uid,
                timestamp=_ts(self._clock),
            )
        )
        self._clock += 1
        r_uid = str(uuid.uuid4())
        self._add(
            self._base(
                "user",
                message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]},
                toolUseResult={"type": "text", "filePath": file_path, "content": "evidence"},
                sourceToolAssistantUUID=a_uid,
                uuid=r_uid,
                timestamp=_ts(self._clock),
            )
        )
        self._clock += 1
        return r_uid

    def split_tool_result_pair(
        self,
        tool_name: str = "Read",
        file_paths: Optional[List[str]] = None,
        assistant_fragments: bool = False,
        bad_second_result: bool = False,
    ) -> str:
        """Append one assistant turn with multiple tool_use blocks followed by
        multiple user records, each carrying one tool_result.

        Claude Code can serialize this shape in real transcripts. The validator
        should treat the split user records as one API user message while still
        rejecting wrong or out-of-order result IDs.
        """
        paths = file_paths or ["C:\\work\\case\\a.md", "C:\\work\\case\\b.md"]
        tool_ids = [f"toolu_{self._clock}_{i}_{uuid.uuid4().hex[:6]}" for i, _ in enumerate(paths)]
        msg_id = f"msg_{self._clock}"
        assistant_uuids: List[str] = []
        if assistant_fragments:
            for idx, (tool_id, file_path) in enumerate(zip(tool_ids, paths)):
                a_uid = str(uuid.uuid4())
                assistant_uuids.append(a_uid)
                self._add(
                    self._base(
                        "assistant",
                        message={
                            "id": msg_id,
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": f"fragment {idx} reading {file_path}"},
                                {"type": "tool_use", "id": tool_id, "name": tool_name, "input": {"file_path": file_path}},
                            ],
                        },
                        uuid=a_uid,
                        timestamp=_ts(self._clock),
                    )
                )
                self._clock += 1
        else:
            a_uid = str(uuid.uuid4())
            assistant_uuids.append(a_uid)
            content: List[JsonObj] = [{"type": "text", "text": "reading multiple files"}]
            for tool_id, file_path in zip(tool_ids, paths):
                content.append({"type": "tool_use", "id": tool_id, "name": tool_name, "input": {"file_path": file_path}})
            self._add(
                self._base(
                    "assistant",
                    message={"id": msg_id, "role": "assistant", "content": content},
                    uuid=a_uid,
                    timestamp=_ts(self._clock),
                )
            )
            self._clock += 1

        source_uuid = assistant_uuids[-1]
        leaf = source_uuid
        for idx, (tool_id, file_path) in enumerate(zip(tool_ids, paths)):
            result_id = "toolu_wrong_id" if bad_second_result and idx == 1 else tool_id
            r_uid = str(uuid.uuid4())
            self._add(
                self._base(
                    "user",
                    message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": result_id, "content": "ok"}]},
                    toolUseResult={"type": "text", "filePath": file_path, "content": f"evidence {idx}"},
                    sourceToolAssistantUUID=source_uuid,
                    uuid=r_uid,
                    timestamp=_ts(self._clock),
                )
            )
            self._clock += 1
            leaf = r_uid
        return leaf

    def file_history_snapshot(
        self,
        file_name: str,
        message_id: Optional[str] = None,
        source_uuid: Optional[str] = None,
    ) -> JsonObj:
        """Append a file-history-snapshot. These typically have NO uuid/parentUuid."""
        rec = {
            "type": "file-history-snapshot",
            "messageId": message_id or f"msg_{self._clock}",
            "snapshot": {"trackedFileBackups": {file_name: {"version": 1}}},
        }
        if source_uuid:
            rec["sourceUuid"] = source_uuid
        return self._add(rec)

    def compact_pair(self, summary_text: str, codex: bool = False) -> str:
        """Append a compact_boundary + isCompactSummary pair. Returns summary uuid."""
        b_uid = str(uuid.uuid4())
        meta: JsonObj = {"trigger": "auto"}
        if codex:
            meta["codexOfflineCompression"] = True
        self._add(
            self._base("system", subtype="compact_boundary", uuid=b_uid, isMeta=True, level="info",
                       content="compacted", compactMetadata=meta, timestamp=_ts(self._clock))
        )
        self._clock += 1
        s_uid = str(uuid.uuid4())
        self._add(
            self._base("user", uuid=s_uid, isCompactSummary=True, isVisibleInTranscriptOnly=True,
                       message={"role": "user", "content": summary_text}, timestamp=_ts(self._clock))
        )
        self._clock += 1
        return s_uid

    def last_prompt(self, leaf: Optional[str] = None) -> JsonObj:
        leaf = leaf if leaf is not None else self.prev_uuid
        rec = {"type": "last-prompt", "leafUuid": leaf, "sessionId": self.session_id}
        return self._add(rec)

    def custom_title(self, title: str) -> JsonObj:
        return self._add({"type": "custom-title", "title": title})


def build_linear(session_id: str, turns: int = 40, with_tools_every: int = 0) -> TranscriptBuilder:
    """A simple linear conversation; optionally inject tool pairs periodically."""
    tb = TranscriptBuilder(session_id)
    tb.custom_title("Legal feasibility research")
    for i in range(turns):
        tb.user(f"用户消息 {i}: 关于法律可行性的决定，必须保留来源与证据。constraint goal {i}")
        if with_tools_every and i % with_tools_every == 0:
            tb.tool_call_pair(file_path=f"C:\\work\\case\\doc{i}.md")
        else:
            tb.assistant_text(f"回应 {i}: 决定如下，理由是 because evidence。最终结论 {i}.")
    tb.last_prompt()
    return tb

#!/usr/bin/env python3
"""Utilities for locating and backing up Claude Code session JSONL files.

This helper is intentionally generic. It can:
- list session files under a .claude/projects tree
- match a session by exact path, file name, or session id without reading files
- optionally scan titles when --scan-titles is explicitly provided
- create numbered .backup copies before modification

It does not compress JSONL itself; it only prepares a single target file safely.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any, Dict, List, Optional, Sequence


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def eprint(*parts: object) -> None:
    print(*parts, file=sys.stderr)


configure_stdio()

MIN_SUPPORTED_PYTHON = (3, 10)


def warn_if_python_too_old() -> Optional[str]:
    """Warn on an unsupported interpreter without blocking the run."""
    if sys.version_info >= MIN_SUPPORTED_PYTHON:
        return None
    running = ".".join(str(part) for part in sys.version_info[:3])
    required = ".".join(str(part) for part in MIN_SUPPORTED_PYTHON)
    message = (
        f"WARNING: running on Python {running}; this project documents Python {required} or newer. "
        "Continuing anyway. Unexpected errors may be caused by the interpreter version."
    )
    eprint(message)
    return message


warn_if_python_too_old()


def read_jsonl_records(path: pathlib.Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                records.append(obj)
    return records


def list_session_files(root: pathlib.Path) -> List[pathlib.Path]:
    if not root.exists():
        return []
    root_resolved = root.resolve()
    found: List[pathlib.Path] = []
    for dir_path, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        directory = pathlib.Path(dir_path)
        # Resolve the containing directory once and compare each child against
        # `resolved_directory / name`. Comparing child.resolve() against
        # os.path.abspath(child) instead would reject every entry whenever any
        # component of the root is a Windows 8.3 short name, because resolve()
        # expands short names to their long form and abspath() leaves them as
        # written. A symlink or junction that leaves the directory still
        # resolves somewhere other than resolved_directory / name, so the
        # escape guard is unchanged.
        try:
            resolved_directory = directory.resolve()
        except OSError:
            dir_names[:] = []
            continue
        safe_dirs: List[str] = []
        for name in dir_names:
            child = directory / name
            try:
                resolved = child.resolve()
                if resolved != resolved_directory / name or not is_same_or_inside(resolved, root_resolved):
                    continue
            except OSError:
                continue
            safe_dirs.append(name)
        dir_names[:] = safe_dirs
        for name in file_names:
            if not name.lower().endswith(".jsonl"):
                continue
            candidate = directory / name
            try:
                resolved = candidate.resolve()
                if resolved != resolved_directory / name or not is_same_or_inside(resolved, root_resolved):
                    continue
                if not candidate.is_file():
                    continue
            except OSError:
                continue
            found.append(candidate)
    return sorted(found)


def extract_hint(path: pathlib.Path) -> str:
    try:
        records = read_jsonl_records(path)
    except Exception:
        return ""
    for obj in records:
        for key in ("custom-title", "ai-title"):
            if obj.get("type") == key:
                if isinstance(obj.get("title"), str) and obj["title"].strip():
                    return obj["title"].strip()
                msg = obj.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip().splitlines()[0][:120]
    return ""


def numbered_backup_path(path: pathlib.Path) -> pathlib.Path:
    base = path.with_suffix(path.suffix + ".backup")
    if not base.exists():
        return base
    for i in range(1, 1000):
        candidate = path.with_suffix(path.suffix + f".backup{i}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find free backup name for {path}")


def create_backup(path: pathlib.Path) -> pathlib.Path:
    source_bytes = path.read_bytes()
    for _attempt in range(1000):
        backup = numbered_backup_path(path)
        backup.parent.mkdir(parents=True, exist_ok=True)
        try:
            with backup.open("xb") as stream:
                stream.write(source_bytes)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            continue
        if backup.read_bytes() == source_bytes:
            return backup
        # Keep a concurrently replaced path untouched and try the next number.
    raise RuntimeError(f"could not create and verify a numbered backup for {path}")


def is_same_or_inside(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _candidate_label(root: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name


def _path_query_match(root: pathlib.Path, path: pathlib.Path, query: str) -> bool:
    q = query.lower()
    name = path.name.lower()
    stem = path.stem.lower()
    if q == name or q == stem:
        return True
    if any(sep in query for sep in ("\\", "/")):
        query_path = pathlib.Path(query)
        if query_path.is_absolute():
            try:
                return path.resolve() == query_path.resolve()
            except OSError:
                return False
        normalized_query = query.replace("\\", "/").lower()
        relative = _candidate_label(root, path).replace("\\", "/").lower()
        return normalized_query == relative
    return False


def find_unique_session(root: pathlib.Path, query: str, scan_titles: bool = False) -> pathlib.Path:
    candidates: List[pathlib.Path] = []
    for path in list_session_files(root):
        if _path_query_match(root, path, query):
            candidates.append(path)
            continue
        if scan_titles:
            hint = extract_hint(path).lower()
            if hint and query.lower() in hint:
                candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"no session matches {query!r} under {root}")
    if len(candidates) > 1:
        lines = [f"- {_candidate_label(root, p)}" for p in candidates[:20]]
        raise RuntimeError("query matched multiple sessions:\n" + "\n".join(lines))
    return candidates[0]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claude-session-tools",
        description="Locate exactly one Claude Code session JSONL and optionally create a verified numbered backup.",
    )
    parser.add_argument("--root", type=pathlib.Path, required=True, help="Root .claude/projects directory")
    parser.add_argument("--query", required=True, help="Exact session id, filename, relative/absolute path, or title substring when --scan-titles is set")
    parser.add_argument(
        "--scan-titles",
        action="store_true",
        help="Read candidate JSONL files to match custom-title/ai-title. Omit this for privacy-sensitive exact path/id/filename lookup.",
    )
    parser.add_argument("--backup", action="store_true", help="Create a numbered .backup copy of the matched file")
    args = parser.parse_args(argv)

    try:
        target = find_unique_session(args.root, args.query, scan_titles=args.scan_titles)
        print(str(target))
        if args.backup:
            print(str(create_backup(target)))
        return 0
    except Exception as exc:
        eprint(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

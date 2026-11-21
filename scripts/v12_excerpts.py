"""Source-bound literal excerpt choices for v12 Map and Reduce writers."""
from __future__ import annotations

import hashlib
import json
import re


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_FILE_LINE = re.compile(r"^ *(\d{1,9})(?:\t|→| ?│ ?| +\| )")
_HEAD = re.compile(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_FIELD = re.compile(r"^(?:fields|toolUseResult|input|file|content|text|stdout|output): ?")
_MACHINE = re.compile(
    r"^(?:line|role|time|origin|id|name|type|stop|tool_use_id|toolUseId|sourceToolAssistantUUID|"
    r"startLine|numLines|totalLines|offset|limit|uuid|parentUuid|sessionId|cwd|timestamp|"
    r"filePath|file_path|command|description|thinking|signature|exactText|stderr|exitCode|"
    r"duration_ms|is_error|isSidechain|stop_reason|usage|data|encoding|mime_type|"
    r"support_text_json|sha256|digest|pack_request_digest)\s*:", re.I)
_MATERIAL = re.compile(
    r"-----[A-Z ]*PRIVATE KEY-----|(?:authorization|proxy-authorization)\s*[:=]|"
    r"\b(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]{6,}|\b[a-z][a-z0-9+.-]*://[^/\s]+:[^/\s]+@|"
    r"\b(?:sk-(?:ant-|proj-)?|github_pat_|gh[pousr]_|xox[baprs]-)[A-Za-z0-9_-]{8,}|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|"
    r"(?:password|passwd|secret|pwd|api[_ -]?key|access[_ -]?key|"
    r"private[_ -]?key|(?:access[_ -]?|refresh[_ -]?)?token|cookie|credentials?)"
    r"\s*['\"]?\s*[:=]|(?:密码|密钥|權杖|口令)\s*[:：=]|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|data:[^, ]*;base64,", re.I)
_OPAQUE = re.compile(r"[A-Za-z0-9+/_=-]{60,}|^[A-Za-z0-9+/]{16,}={1,2}$|\b[0-9a-fA-F]{32,}\b|"
                     r"\\(?:n|r|t|u[0-9a-fA-F]{4}).*\\(?:n|r|t|u[0-9a-fA-F]{4})")
_RECEIPT = re.compile(r"(?:\[(?:[ .=>#-]+)\]\s*)?(?:\d{1,3}%|\d+\s*/\s*\d+)"
                      r"(?:\s*(?:complete[d]?|done|processed|完成))?[.!… ]*|"
                      r"(?:ok|done|working|loading|processing|running|pending|success|"
                      r"处理中|进行中|完成|收到|继续)[.!… ]*", re.I)
_AUDIT = re.compile(r"<!--|-->|\bsupport_text_json=|\b(?:[a-z_]+digest|sha256)\s*[:=]|"
                    r"\[@[LH]\d+\]|^@@\s|^@keep\s")
_STATE = {"current": ("Current", "现行"), "history": ("Historical", "历史记录"),
          "superseded": ("Superseded", "已被取代"), "unresolved": ("Unresolved", "待定")}


def contains_credential(text):
    return bool(_MATERIAL.search(text))


def _unsafe(line):
    return bool(len(line) > 12000 or _OPAQUE.search(line) or _MATERIAL.search(line) or _AUDIT.search(line)
                or any(ord(ch) < 32 and ch != "\t" for ch in line))


def _caption(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 240 or not any(c.isalnum() for c in text):
        raise ValueError("excerpt needs a readable attribution of at most 240 characters")
    if _unsafe(text) or any(c in text for c in "\n\r|<>") or re.fullmatch(r"[EX][a-fA-F0-9.]+", text):
        raise ValueError("unsafe or mechanical excerpt attribution")
    return text


def _literal(source, spans):
    # Numbered Read prefixes lie between spans. Preserve internal terminators.
    parts = [source[a:b] for a, b in spans]
    parts[-1] = parts[-1].rstrip("\r\n")
    return "".join(parts)


_BOUND = ("source", "sourceSha256", "spans", "firstLine", "lastLine", "lineKind",
          "document", "title", "eventLine", "role", "time", "textSha256")


def _identify(record):
    encoded = json.dumps([record[k] for k in _BOUND], ensure_ascii=False, separators=(",", ":"))
    record["binding"] = _sha(encoded)
    record["id"] = "X" + record["binding"][:14]
    return record


def _file_sections(lines):
    """Recognize the readable projection of Read.file with verified length."""
    result = {}
    for i, raw in enumerate(lines):
        count_match = re.fullmatch(r"numLines: (\d{1,9})", raw.rstrip("\r\n"))
        if not count_match or i + 1 >= len(lines):
            continue
        origin = re.fullmatch(r"startLine: (\d{1,9})", lines[i + 1].rstrip("\r\n"))
        if not origin:
            continue
        count = int(count_match[1])
        first = i - count
        path_field = r"^(?:(?:file|toolUseResult): )*filePath: "
        if (i and lines[i-1].rstrip("\r\n") == "" and first >= 2
                and re.match(path_field, lines[first-2]) and lines[first-1].startswith("content: ")):
            first -= 1
        if (not count or first < 1 or not lines[first].startswith("content: ")
                or not re.match(path_field, lines[first-1])):
            continue
        for j in range(count):
            result[first + j] = int(origin[1]) + j, len("content: ") if j == 0 else 0
    return result


def _groups(key, source):
    digest = _sha(source)
    title = filename = role = time = ""
    event = None
    kind = None
    spans = []
    first = last = size = offset = 0
    pem = False
    reminder = False
    ignored_indent = None
    envelope = bool(re.search(r"(?m)^line: [0-9]+\r?\nrole: ", source))
    lines = source.splitlines(keepends=True)
    file_sections = _file_sections(lines) if envelope else {}

    def finish():
        if not spans:
            return None
        text = _literal(source, spans)
        rec = dict(source=key, sourceSha256=digest, spans=list(spans),
                   firstLine=first, lastLine=last, lineKind=kind, document=filename, title=title or filename,
                   eventLine=event, role=role, time=time, text=text, textSha256=_sha(text))
        spans.clear()
        return _identify(rec)

    for index, raw in enumerate(lines, 1):
        start = offset
        offset += len(raw)
        line = raw.rstrip("\r\n")
        section = file_sections.get(index - 1)
        if envelope and section is None:
            while match := _FIELD.match(line):
                start += match.end()
                line = line[match.end():]
        number = _FILE_LINE.match(line)
        if section is not None:
            n, prefix_len = section
            start += prefix_len
            line = line[prefix_len:]
            current_kind = "file"
        elif number:
            start += number.end()
            current_kind, n = "file", int(number[1])
            line = line[number.end():]
        else:
            current_kind, n = "source", index
        clean = line.strip()
        field = _MACHINE.match(line) if envelope and current_kind != "file" else None
        heading = _HEAD.fullmatch(line)
        if ignored_indent is not None and clean and len(line) - len(line.lstrip()) <= ignored_indent:
            ignored_indent = None
        unsafe = _unsafe(line)
        if clean.endswith((":", "|", ">")) and len(line) <= 12000 and _MATERIAL.search(line):
            ignored_indent = len(line) - len(line.lstrip())
        if "-----BEGIN " in line and "PRIVATE KEY-----" in line:
            pem = True
        if "<system-reminder" in line:
            reminder = True
        skip = (unsafe or field or pem or reminder or ignored_indent is not None or not clean
                or _RECEIPT.fullmatch(clean)
                or clean.startswith(("{\"", "[{", "</", "<system-reminder", chr(96)*3, "~~~"))
                or not any(ch.isalnum() for ch in clean))
        if "-----END " in line and "PRIVATE KEY-----" in line:
            pem = False
        if "</system-reminder>" in line:
            reminder = False
        if heading or skip or n != last + 1 or current_kind != kind or size + len(raw) > 4096:
            if rec := finish():
                yield rec
            size = 0
        if field:
            field_key, _, value = line.partition(":")
            value = value.strip()
            if field_key == "line" and value.isdecimal():
                event = int(value)
                title = filename = role = time = ""
            elif field_key == "role" and value in ("user", "assistant", "system"):
                role = value
            elif field_key == "time" and re.fullmatch(r"[0-9TtZz:.+ -]{10,40}", value):
                time = value
            elif field_key in ("filePath", "file_path"):
                leaf = re.split(r"[/\\]", value)[-1].strip()
                filename = leaf if 0 < len(leaf) <= 160 and not _unsafe(leaf) else ""
                title = ""
        if heading:
            title = heading[1] if not skip and len(heading[1]) <= 180 else ""
        if skip or heading:
            continue
        if not spans:
            first, kind = n, current_kind
        last = n
        spans.append([start, offset])
        size += len(raw)
    if rec := finish():
        yield rec


def _spread(values, count):
    if count >= len(values):
        return values
    if count == 1:
        return values[:1]
    return [values[i * (len(values) - 1) // (count - 1)] for i in range(count)]


def catalog_request(sources: dict[str, str], limit: int) -> dict:
    """Offer up to limit candidate passages across source occurrences, in order."""
    if type(limit) is not int or limit < 0:
        raise ValueError("excerpt catalog limit must be a non-negative count")
    if not limit:
        return {}
    groups = []
    for key, source in sources.items():
        unique = []
        seen = set()
        for rec in _groups(key, source):
            # Deduplicate only identical numbered reads in one event and section.
            if rec["eventLine"] is not None and rec["lineKind"] == "file":
                marker = (rec["eventLine"], rec["document"], rec["title"], rec["firstLine"], rec["lastLine"], rec["text"])
                if marker in seen:
                    continue
                seen.add(marker)
            unique.append(rec)
        if unique:
            groups.append(unique)
    groups = _spread(groups, limit)
    counts = [0] * len(groups)
    remaining = limit
    while remaining:
        active = [i for i, group in enumerate(groups) if counts[i] < len(group)]
        if not active:
            break
        for i in _spread(active, remaining):
            counts[i] += 1
            remaining -= 1
    catalog = {}
    for group, count in zip(groups, counts):
        for rec in _spread(group, count):
            if rec["id"] in catalog:
                raise ValueError("excerpt identifier collision")
            catalog[rec["id"]] = rec
    return catalog


def catalog_index(catalog, *, full=False):
    """Compact writer lookup; the literal passage remains in the private catalog."""
    lines = []
    for key, rec in catalog.items():
        preview = " ".join(rec["text"].split())[:96]
        label = rec.get("attribution") or rec["title"]
        status = rec.get("disposition", "")
        lines.append(f"{key} {rec['source']} {rec['lineKind']} #{rec['firstLine']}-{rec['lastLine']} "
                     f"({len(rec['text'])} chars) {status} {label} | {preview}")
        if full:
            lines.extend(f"{n}\t{line}" for n, line in enumerate(rec["text"].splitlines(), rec["firstLine"]))
    return "\n".join(lines)


def _check(rec):
    n, m, spans = rec["firstLine"], rec["lastLine"], rec["spans"]
    if (type(n) is not int or type(m) is not int or n < 0 or len(spans) != m - n + 1
            or not spans or rec["lineKind"] not in ("source", "file")
            or any(len(s) != 2 or any(type(i) is not int for i in s) or not 0 <= s[0] < s[1] for s in spans)
            or any(r[0] < l[1] for l, r in zip(spans, spans[1:]))):
        raise ValueError("invalid excerpt range")
    identity = _identify(dict(rec))
    if (identity["id"] != rec["id"] or identity["binding"] != rec["binding"]
            or _sha(rec["text"]) != rec["textSha256"]):
        raise ValueError("excerpt binding mismatch")


def _slice(rec, start, stop):
    first = rec["firstLine"]
    if not first <= start <= stop <= rec["lastLine"]:
        raise ValueError("excerpt choice lies outside its frozen line range")
    left, right = start - first, stop - first + 1
    spans = rec["spans"][left:right]
    lines = rec["text"].splitlines(keepends=True)[left:right]
    text = "".join(lines).rstrip("\r\n")
    return _identify(dict(rec, spans=spans, firstLine=start, lastLine=stop, text=text, textSha256=_sha(text)))


_CHOICE = re.compile(r"@keep (X[0-9a-f]{14})(?: #(\d{1,9})(?:-(\d{1,9}))?)?"
                     r"(?: \| (current|history|superseded|unresolved) \| (.+))?")


def parse_selections(draft, catalog):
    """Remove explicit choices from the writer's draft before memory validation."""
    body, choices = [], []
    ended = False
    for line in draft.splitlines(keepends=True):
        raw = line.strip()
        if not raw.startswith("@keep"):
            ended |= raw == "<!-- end-memory -->"
            body.append(line)
            continue
        if ended:
            raise ValueError("excerpt choice follows the draft completion marker")
        match = _CHOICE.fullmatch(raw)
        if not match or match[1] not in catalog:
            raise ValueError("invalid or unavailable excerpt choice")
        rec = dict(catalog[match[1]])
        _check(rec)
        if rec["id"] != match[1]:
            raise ValueError("excerpt catalog key mismatch")
        if match[2]:
            rec = _slice(rec, int(match[2]), int(match[3] or match[2]))
        if match[4]:
            rec.update(disposition=match[4], attribution=_caption(match[5]))
        if rec.get("disposition") not in _STATE:
            raise ValueError("first selection needs disposition and attribution")
        _caption(rec["attribution"])
        choices.append(rec)
    carry_catalog(choices)
    return "".join(body), choices


def carry_catalog(selections):
    """Only writer-selected passages can be offered to the next reducer."""
    catalog = {}
    previous = {}
    for rec in selections:
        _check(rec)
        if rec.get("disposition") not in _STATE:
            raise ValueError("unknown excerpt disposition")
        _caption(rec["attribution"])
        origin = rec["source"], rec["sourceSha256"]
        intervals = previous.setdefault(origin, [])
        a, b = rec["spans"][0][0], rec["spans"][-1][1]
        if rec["id"] in catalog or any(a < stop and b > start for start, stop in intervals):
            raise ValueError("repeated or overlapping excerpt choice")
        intervals.append((a, b))
        catalog[rec["id"]] = dict(rec)
    return catalog


def verify_selected(selections, sources):
    """Check frozen source digests, offsets and literal contents before reuse."""
    digests = {}
    for rec in carry_catalog(selections).values():
        key = rec["source"]
        if key not in sources:
            raise ValueError("excerpt source missing")
        source = sources[key]
        if key not in digests:
            digests[key] = _sha(source)
        if (digests[key] != rec["sourceSha256"] or rec["spans"][-1][1] > len(source)
                or _literal(source, rec["spans"]) != rec["text"]):
            raise ValueError("excerpt source, range or content changed")


EXCERPT_HEADINGS = ("## Source excerpts", "## 来源摘录")
_CAPTION = re.compile(r"### (?:" + "|".join(re.escape(label) for pair in _STATE.values() for label in pair)
                      + r") · [^\r\n]+")
_RANGE = re.compile(r"(?:lines \d+–\d+|第 \d+–\d+ 行|source lines \d+–\d+|来源行 \d+–\d+)")


def parsed_passages(section, *, next_modules=()):
    """Consume either renderer exactly, including independently fenced, range-labelled selections."""
    lines = section.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") not in EXCERPT_HEADINGS:
        return None
    parts = [("v12-excerpt-heading", lines[0], "")]
    index = 1
    caption = ""
    while index < len(lines):
        start = index
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index == len(lines):
            parts.append(("whitespace", "".join(lines[start:]), ""))
            break
        label = lines[index].rstrip("\r\n")
        if caption and label.startswith("## ") and label[3:].casefold() in next_modules:
            # A locked v12 writer may append a new memory after a complete old excerpt section.
            parts.append(("whitespace", "".join(lines[start:index]), ""))
            parts.append(("inspect", "".join(lines[index:]), ""))
            break
        if _CAPTION.fullmatch(label):
            caption = label
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
        elif not caption:
            return None
        scope = ""
        if index < len(lines) and _RANGE.fullmatch(lines[index].rstrip("\r\n")):
            scope = lines[index].rstrip("\r\n")
            index += 1
        elif label != caption:
            return None
        if index >= len(lines):
            return None
        fence = lines[index].rstrip("\r\n")
        if not re.fullmatch(r"~{3,}", fence):
            return None
        index += 1
        first = index
        while index < len(lines) and lines[index].rstrip("\r\n") != fence:
            index += 1
        if index == len(lines) or first == index:
            return None
        quote = "".join(lines[first:index])
        quote = quote.removesuffix("\n").removesuffix("\r")
        if any(fence in line for line in lines[first:index]):
            return None
        index += 1
        evidence = caption + ("\n" + scope if scope else "") + "\n" + quote
        parts.append(("v12-excerpt", "".join(lines[start:index]), evidence))
    return parts if any(rule == "v12-excerpt" for rule, _, _ in parts) else None


def _shared_origin(rec):
    return tuple(rec[k] for k in ("source", "sourceSha256", "document", "eventLine", "role", "time",
                                  "title", "lineKind", "disposition", "attribution"))


def render_selected(selections, limit):
    """Render complete attributed excerpts or reject the character budget."""
    if type(limit) is not int or limit < 0:
        raise ValueError("excerpt character limit must be non-negative")
    records = list(carry_catalog(selections).values())
    if not records:
        return ""
    chinese = bool(re.search(r"[\u3400-\u9fff]", records[0]["attribution"]))
    output = [EXCERPT_HEADINGS[int(chinese)]]
    previous = None
    for index, rec in enumerate(records):
        state = _STATE[rec["disposition"]][int(chinese)]
        text = rec["text"]
        title = rec["title"]
        details = [rec["attribution"]]
        for label in (rec["document"], title):
            if label and not any(label in existing for existing in details):
                details.append(label)
        if rec["time"]:
            details.append(rec["time"])
        a, b = rec["firstLine"], rec["lastLine"]
        # Separate fences preserve each selected range, including any gap.
        origin = _shared_origin(rec)
        follows = previous is not None and previous[0] == origin and previous[1] < a
        has_next = (index + 1 < len(records) and _shared_origin(records[index+1]) == origin
                    and b < records[index+1]["firstLine"])
        shared = follows or has_next
        scope = f"第 {a}–{b} 行" if chinese else f"lines {a}–{b}"
        if shared and rec["lineKind"] == "source":
            scope = f"来源行 {a}–{b}" if chinese else f"source lines {a}–{b}"
        if not shared and rec["lineKind"] == "file":
            details.append(scope)
        previous = origin, b
        # A longer fence keeps headings inside the quotation.
        fence = "~" * max(3, 1 + max((len(m[0]) for m in re.finditer(r"~+", text)), default=0))
        header = "" if follows else f"### {state} · " + " · ".join(details) + "\n\n"
        output.append(header + (scope + "\n" if shared else "") + f"{fence}\n{text}\n{fence}")
    rendered = "\n\n".join(output)
    if len(rendered) > limit:
        raise ValueError(f"selected excerpts need {len(rendered)} characters, allowance {limit}. "
                         "Reselect passages or narrower complete line ranges.")
    return rendered

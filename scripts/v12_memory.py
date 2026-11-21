"""Local v12 draft verification and reversible prior-memory migration."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from v12_excerpts import contains_credential

import v12_excerpts

END = "<!-- end-memory -->"
HEADINGS = {
    "state": ("Current State", "Resume Cockpit", "当前状态", "目前狀態", "現在の状態"),
    "sources": ("Source Registry", "来源登记", "來源登記", "資料一覧"),
    "decisions": ("Decisions and Rejected Alternatives", "Decisions & Rejected", "决策与否决方案", "決策與否決方案", "決定と却下案"),
    "unresolved": ("Unresolved", "未决事项", "未決事項", "未解決事項"),
    "boundary": ("Handoff Boundary", "交接边界", "交接邊界", "引き継ぎ境界"),
}
SLOTS = {name.casefold(): slot for slot, names in HEADINGS.items() for name in names}

PRESERVED = "# Preserved Prior Compact Summaries"
INTRO = (PRESERVED + "\n\nThe following prior \x60isCompactSummary\x60 message contents are copied verbatim because "
         "the user explicitly requested preservation across repeated compression. They are embedded inside "
         "this new single compact summary; the old compact records are not kept as additional live compact pairs.")
FRAME = re.compile(r"\n\n## Prior Compact Summary ([1-9][0-9]*)\n<!-- source_line: ([1-9][0-9]*) "
                   r"uuid: ([^\r\n ]+) sha256_prefix: ([0-9a-f]{16}) chars: ([0-9]+) -->\n\n")
CURRENT = "\n\n# Current Compression Layer\n\n"
MODEL_PREFIX = ("# Codex Offline Compression Summary\n\nThis candidate uses model-assisted semantic compression. "
                "The model-authored section below was accepted only after source-digest, summary-source, "
                "evidence-group, and line-anchor validation. The deterministic safety appendix remains a "
                "bounded structural backstop.\n\n## Model-Assisted Semantic Summary\n\n")
APPENDIX = "\n\n## Deterministic Safety Appendix\n\n"
OLD_SECTIONS = ("Current State", "Timeline and Supersessions", "Decisions and Reasons",
                "Assistant Research Decisions and Rationales", "Rejected or Superseded Alternatives",
                "Evidence and Source Anchors", "User Wording and Constraints", "Risks, Unknowns, and Follow-Ups",
                "Recent Raw Context Boundary")
OLD_TITLE = "# Model-Assisted Semantic Compression Summary"
COVERAGE = "### Mandatory Evidence Coverage"
META = re.compile(r"\A<!-- claude-jsonl-compressor:model-summary v11\r?\n((?:[a-z_0-9]+: (?:[a-f0-9]{16}|[a-f0-9]{64}|none)\r?\n)+)-->\r?\n")
META_KEYS = {"source_sha256", "summary_source_sha256", "evidence_anchor_lines_digest", "required_anchor_groups_digest",
             "pack_request_digest", "required_claim_sources_digest", "handoff_summary_digest"}
OLD_ANCHOR = re.compile(r"\[@[LH][0-9]{1,9}\]")
_DETERMINISTIC_DESCRIPTION = (
    "This is a candidate Claude Code JSONL compact summary generated outside Claude. It summarizes only older "
    "records from the selected active chain. Rewound, inactive, and unattributed records are excluded.")
_DETERMINISTIC_INTRO = "# Codex Offline Compression Summary\n\n" + _DETERMINISTIC_DESCRIPTION + "\n\n## 1. Scope"
_FIXED_APPENDIX = {
    "# Codex Offline Compression Summary", _DETERMINISTIC_DESCRIPTION, "## 1. Scope", "## 2. Structural Overview",
    "## 3. Long-Term Memory Ledger", "## 4. Early / Middle Summary", "### 4.1 Early", "### 4.2 Middle",
    "## 5. Assistant Behavior and Evidence", "### 5.1 Assistant research decisions and rationales",
    "### 5.2 Key assistant outputs", "### 5.3 Key paths and filenames", "### 5.4 Errors and anomalies",
    "## 6. Existing Compact Records", "### 6.1 compact_boundary layer", "### 6.2 isCompactSummary layer",
    "### 6.3 Repeated compression policy", "## 7. Recent Raw Preservation", "## 8. Important Reminders",
    "### Extracted human-user prompts from summarized records", "### Topic evidence index",
    "### Assistant research decisions and rationales from summarized records", "No direct hit in the summarized range.",
    "- Exact wording lives in the source JSONL or external archives.", "- Source file label: SOURCE_JSONL",
    "- Treat previous compact layers as prior memory, not as live stacked context.",
    "- Fold still-relevant facts into the current compact summary.",
    "- Keep provenance, hashes, file labels, and line ranges in metadata or sidecars.",
    "- If prior layers themselves are too large, switch to a long-term memory ledger.",
    "- This file is a candidate transcript rewrite, not a proof of Claude runtime behavior.",
    "- This ledger is extracted from the summarized range by generic rules. It contains no project facts built into the skill.",
    "- Recent raw records remain in this candidate JSONL for rewind. Exact early/middle wording requires the original JSONL or archive.",
    "- If the same topic changed over time, later work should judge by event order instead of treating early states as final.",
    "- Project-specific facts must come from the JSONL or an explicit handoff summary, not from hardcoded skill memory.",
}
_COUNT_LINE = re.compile(
    r"- (?:(?:Original record count|Recent raw active-chain records preserved|File history snapshots|"
    r"Existing compact summaries summarized into this layer|Human user prompts|Tool-result user records): \d+|"
    r"Active-chain records selected for summary: \d+ records before the preserved active-chain window|"
    r"Physical line window of preserved records: \d+ to \d+|\d+ additional similar items were counted but not expanded\.)")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reassemble_prior(audit: dict) -> str:
    """Check each contiguous classification span against both lengths and digests."""
    pieces = []
    position = 0
    for span in audit["spans"]:
        value = span["text"]
        if (span["start"] != position or span["end"] != position + len(value)
                or _sha(value) != span["sha256"]):
            raise ValueError("prior migration span failed reassembly")
        pieces.append(value)
        position = span["end"]
    restored = "".join(pieces)
    if position != audit["chars"] or _sha(restored) != audit["sourceSha256"]:
        raise ValueError("prior migration fingerprint changed during reassembly")
    return restored


def _model_parts(text):
    """Recognize the full v11 grammar. Ambiguous or extended models stay opaque."""
    if not text.startswith(MODEL_PREFIX) or text.count(APPENDIX) != 1:
        return None
    model, appendix = text[len(MODEL_PREFIX):].split(APPENDIX)
    metadata = META.match(model)
    if not metadata:
        return None
    fields = [line.split(": ", 1) for line in metadata[1].splitlines()]
    keys = [key for key, _ in fields]
    if set(keys) != META_KEYS or len(keys) != len(set(keys)):
        return None
    for key, value in fields:
        if key in {"evidence_anchor_lines_digest", "required_anchor_groups_digest"} and len(value) == 16:
            continue
        if key == "handoff_summary_digest" and value == "none":
            continue
        if len(value) != 64:
            return None
    lines = model[metadata.end():].splitlines(keepends=True)
    headings = [s.strip() for s in lines if s.strip().startswith("#")]
    expected = [OLD_TITLE, *("## " + h for h in OLD_SECTIONS)]
    expected.insert(expected.index("## User Wording and Constraints"), COVERAGE)
    if headings != expected:
        return None
    parts = [("v11-composition", MODEL_PREFIX, ""), ("v11-metadata", metadata[0], "")]
    coverage = False
    for raw in lines:
        line = raw.strip()
        if line in expected:
            coverage = line == COVERAGE
            # A sentence under "Rejected" or "User Wording" changes meaning
            # if the label is removed before the next model sees it.
            label = line if line.startswith("## ") else ""
            if line == "## Recent Raw Context Boundary":
                label = "## Raw-context boundary recorded by the previous compression"
            parts.append(("v11-heading", raw, label))
        elif not line:
            parts.append(("whitespace", raw, ""))
        elif coverage:
            match = re.fullmatch(r'- L[0-9]{1,9} support_text_json=(.+) disposition=covered', line)
            if not match:
                return None
            try:
                excerpt = json.loads(match[1])
            except ValueError:
                return None
            if not isinstance(excerpt, str) or not excerpt.strip():
                return None
            parts.append(("coverage-quote", raw, excerpt))
        else:
            parts.append(("v11-knowledge", raw, OLD_ANCHOR.sub("", raw).rstrip()))
    parts.append(("v11-composition", APPENDIX, ""))
    parts.extend(_appendix_parts(appendix))
    return parts


def _appendix_parts(appendix):
    known_template = appendix.startswith(_DETERMINISTIC_INTRO)
    for raw in appendix.splitlines(keepends=True):
        # Generated appendix includes arbitrary handoffs and user text. Only the
        # exact line-evidence envelope is decoded; unknown lines remain intact.
        match = re.fullmatch(r"- L[0-9]+: (.+)", raw.rstrip("\r\n"))
        bare = raw.rstrip("\r\n")
        if known_template and (bare in _FIXED_APPENDIX or _COUNT_LINE.fullmatch(bare)):
            yield "v11-appendix-scaffold", raw, ""
        elif match:
            yield "appendix-quote", raw, match[1]
        elif raw.strip():
            yield "appendix-opaque", raw, raw.rstrip("\r\n")
        else:
            yield "whitespace", raw, ""


def _frame_parts(text):
    if not text.startswith(INTRO):
        raise ValueError("prior frame introduction is malformed")
    yield "frame-intro", INTRO, ""
    position = len(INTRO)
    number = 1
    while True:
        match = FRAME.match(text, position)
        if not match or int(match[1]) != number:
            raise ValueError("prior frame sequence or boundary is malformed")
        end = match.end() + int(match[5])
        payload = text[match.end():end]
        if end > len(text) or _sha(payload)[:16] != match[4]:
            raise ValueError("prior frame length or fingerprint mismatch")
        yield "frame-header", match[0], "Earlier preserved memory"
        yield "inspect", payload, ""
        position = end
        number += 1
        if text.startswith(CURRENT, position):
            separator = CURRENT
            break
        # The 1.0 writer stripped the built frame before joining CURRENT. Its
        # separator can supply the final LF(s) of a hash-verified payload.
        # Inspect only the declared end. Never shift the authenticated span.
        removed = payload[len(payload.rstrip()):]
        if removed in ("\n", "\n\n") and text.startswith(CURRENT[len(removed):], position):
            separator = CURRENT[len(removed):]
            break
    yield "frame-current-boundary", separator, "Current compression layer"
    yield "inspect", text[position + len(separator):], ""


def _prior_parts(text):
    # Descend only at a verified v11 content boundary, never by heading search.
    stack = [("inspect", text, "")]
    while stack:
        kind, raw, value = stack.pop()
        if kind != "inspect":
            yield kind, raw, value
        elif raw.startswith(INTRO) or (
            raw.partition("\n")[0].rstrip("\r") == PRESERVED and
            ("\n## Prior Compact Summary 1" in raw[:700] or "sha256_prefix:" in raw[:700])
        ):
            stack.extend(reversed(list(_frame_parts(raw))))
        else:
            stack.extend(reversed(list(_unframed_parts(raw))))


def _unframed_parts(text):
    model = _model_parts(text)
    if model is not None:
        yield from model
        return
    if text.startswith(_DETERMINISTIC_INTRO):
        yield from _appendix_parts(text)
        return
    marker = re.search(r"(?m)^## (?:Source excerpts|来源摘录)\r?$", text)
    prose = text[:marker.start()] if marker else text
    headings = [line[3:].casefold() for line in prose.splitlines() if line.startswith("## ")]
    is_memory = (bool(headings) and all(h in SLOTS for h in headings)
                 and all(line.startswith(("## ", "### ", "- ")) for line in prose.splitlines() if line.strip()))
    passages = v12_excerpts.parsed_passages(text[marker.start():], next_modules=SLOTS) if marker and is_memory else []
    if is_memory and passages is not None:
        yield "v12-prose", prose, prose
        yield from passages
    else:
        yield "opaque", text, text


def prepare_prior(text: str, policy: str) -> dict:
    if not isinstance(text, str) or policy not in {"resynthesize", "clean-and-merge", "verbatim-locked"}:
        raise ValueError("expected prior text and a supported migration policy")
    spans, evidence, candidates = [], [], []
    pos = 0
    for kind, raw, value in _prior_parts(text):
        span = dict(rule=kind, start=pos, end=pos + len(raw), sha256=_sha(raw), text=raw)
        spans.append(span)
        pos = span["end"]
        if kind in {"coverage-quote", "appendix-quote", "appendix-opaque", "v12-excerpt"}:
            candidates.append((value, span))
        elif kind == "opaque" and value.strip() and policy == "clean-and-merge":
            candidates.append((value, span))
        elif value:
            evidence.append(value)

    audit = dict(policy=policy, chars=len(text), sourceSha256=_sha(text), spans=spans)
    restored = reassemble_prior(audit)
    if restored != text:
        raise ValueError("prior migration altered original text")
    audit["roundTripSha256"] = _sha(restored)
    audit["roundTripVerified"] = True
    if policy == "verbatim-locked":
        return dict(evidence="", locked=text, residuals={}, audit=audit)
    # The same wording may be superseded, then reinstated in a later layer.
    prose = "\n".join(evidence)
    residuals = {}
    reverse = {}
    additions = []
    for value, span in candidates:
        if span["rule"] not in {"opaque", "v12-excerpt"} and value in prose:
            span["disposition"] = "verbatim-in-evidence"
            continue
        identity = (span["start"], value) if span["rule"] == "v12-excerpt" else value
        if identity not in reverse:
            key = f"R{len(reverse) + 1}"
            reverse[identity] = key
            if policy == "clean-and-merge":
                residuals[key] = value
            elif span["rule"] == "v12-excerpt" or value not in prose:
                additions.append(value)
        span["residualId" if policy == "clean-and-merge" else "evidenceExcerpt"] = (
            reverse[identity] if policy == "clean-and-merge" else value)
    return dict(evidence="\n".join([prose, *additions]) if additions else prose,
                locked="", residuals=residuals, audit=audit)


def locked_references(priors, allowance, choices):
    """Bind optional views to exact character ranges of the locked originals."""
    if allowance < 0:
        raise ValueError("locked context character allowance must be non-negative")
    locked = {f"P{i}": p for i, p in enumerate(priors, 1) if p["locked"]}
    ranges = []
    if choices:
        for choice in choices:
            match = re.fullmatch(r"(P[1-9]\d{0,8}):(\d{1,12})-(\d{1,12})", choice)
            if not match or match[1] not in locked:
                raise ValueError("expected --locked-range P1:START-END for a locked prior")
            key, start, stop = match[1], int(match[2]), int(match[3])
            if not 0 <= start < stop <= len(locked[key]["locked"]):
                raise ValueError("locked range exceeds its source")
            if any(k == key and a < stop and start < b for k, a, b in ranges):
                raise ValueError("overlapping locked ranges")
            ranges.append((key, start, stop))
        if sum(b-a for _, a, b in ranges) > allowance:
            raise ValueError("explicit locked ranges exceed --locked-context-chars")
    elif allowance:
        remaining = allowance
        for i, (key, prior) in enumerate(locked.items()):
            text = prior["locked"]
            size = min(len(text), remaining // (len(locked) - i))
            if not size:
                continue
            if size == len(text):
                ranges.append((key, 0, size))
            else:
                # Prefer the latest current-state section over a legacy frame preamble.
                starts = [span["start"] + match.start()
                          for span in prior["audit"]["spans"] if span["rule"] == "v12-prose"
                          for match in re.finditer(r"(?m)^## ([^\r\n]+)", span["text"])
                          if SLOTS.get(match[1].casefold()) == "state"]
                start = starts[-1] if starts else 0
                stop = min(len(text), start + size)
                ranges.append((key, start, stop))
            remaining -= ranges[-1][2] - ranges[-1][1]
    result = {}
    for i, (key, start, stop) in enumerate(ranges, 1):
        prior = locked[key]
        result[f"L{i}"] = dict(prior=key, line=prior["line"], start=start, end=stop,
                               total=len(prior["locked"]), sourceSha256=prior["audit"]["sourceSha256"],
                               text=prior["locked"][start:stop])
    return result


def _references(field, available):
    ids = []
    for raw in field.split(","):
        ref = raw.strip()
        if ref in available:
            ids.append(ref)
            continue
        # Never allocate a range larger than the evidence dictionary.
        pair = re.fullmatch(r"(E(?:\d+\.)?|P[1-9]\d*R)([1-9]\d*)-(E(?:\d+\.)?|P[1-9]\d*R)([1-9]\d*)", ref)
        if not pair or pair[1] != pair[3]:
            raise ValueError(f"unknown citation or malformed range {ref[:80]}")
        first, last = int(pair[2]), int(pair[4])
        if last < first or last - first >= len(available):
            raise ValueError("invalid citation range")
        for index in range(first, last + 1):
            key = pair[1] + str(index)
            if key not in available:
                raise ValueError(f"range contains unseen source {key}")
            ids.append(key)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate citation on an item")
    return ids


# Compare literal quantities with the units that change their interpretation.
# Keep quantity matching separate from identifiers such as path names and UUIDs.
UNIT_ALIASES = {
    "milliseconds": "ms", "millisecond": "ms", "毫秒": "ms", "ミリ秒": "ms",
    "seconds": "s", "second": "s", "秒": "s", "sec": "s",
    "minutes": "min", "minute": "min", "分钟": "min", "分鐘": "min", "分間": "min",
    "hours": "h", "hour": "h", "小时": "h", "小時": "h", "時間": "h",
    "days": "d", "day": "d", "天": "d", "日間": "d", "％": "%",
    "kilograms": "kg", "公斤": "kg", "grams": "g", "克": "g",
    "weeks": "week", "周": "week", "週": "week", "months": "month", "个月": "month", "個月": "month",
    "years": "year", "年": "year", "美元": "USD", "欧元": "EUR", "歐元": "EUR", "人民币": "CNY",
    "人民幣": "CNY", "英镑": "GBP", "英鎊": "GBP", "日元": "JPY", "萬": "万", "億": "亿",
    "萬元": "万元", "億元": "亿元", "頁": "页", "條": "条", "項": "项",
}
for scale, normalized in (("百", "百"), ("千", "千"), ("万", "万"), ("萬", "万"), ("亿", "亿"), ("億", "亿")):
    for currency in ("元", "美元", "欧元", "歐元", "英镑", "英鎊", "日元"):
        UNIT_ALIASES[scale + currency] = normalized + UNIT_ALIASES.get(currency, currency)
UNITS = set(UNIT_ALIASES) | set(UNIT_ALIASES.values()) | {
    "ns", "µs", "μs", "mm", "cm", "km", "m", "ml", "mg", "KB", "MB", "GB", "KiB", "MiB", "GiB", "B",
    "Hz", "kHz", "MHz", "GHz", "V", "mV", "A", "mA", "W", "kW", "°C", "°F",
    "元", "月", "天", "人", "份", "页", "行", "条", "款", "项", "倍", "折", "件", "个", "個",
    "thousand", "million", "billion",
}
UNIT_PATTERN = "|".join(re.escape(x) for x in sorted(UNITS, key=lambda s: (-len(s), s)))
NUMBER = re.compile(r"(?<![A-Za-z0-9_])(?:(?P<currency>USD|EUR|CNY|GBP|JPY|人民币|人民幣|[$€£¥￥])\s*)?"
                    r"(?P<value>[+-]?\d+(?:[.,]\d+)*)(?:[ \t]*(?P<unit>" + UNIT_PATTERN + r")(?![A-Za-z]))?")
NEGATIVE = re.compile(r"\b(?:not|no|never|cannot|denied|forbidden|prohibited|unauthorized|unavailable|unread|"
                      r"failed|excluded|pending|rejected|without)\b|n['’]t\b|尚未|并未|並未|未(?=[获獲予经經批核同授开開启啟"
                      r"完读讀阅閱取交支选選能确认確認通生到付封])|禁止|不得|不许|不允|不允許|不准|"
                      r"不能|不会|不會|不(?=公开|公開|开放|開放|批准|同意|支持|授权|授權)|并非|並非|"
                      r"没有|沒有|否决|否決|失败|失敗|却下|できない|できず|されていない|しない|不可",
                      re.I)
UNREAD = re.compile(r"\bunread\b|(?:not|never|yet to be)\s+(?:been\s+)?(?:read|opened|reviewed)|"
                    r"(?:尚?未|没有|沒有|まだ)[^\s，。；]{0,4}(?:读|讀|阅|閱|読|確認)|未読", re.I)
CLAUSE_BREAK = re.compile(r"[!?。！？；;\n]|(?<=\.)\s+|(?<!\d),|,(?!\d)|，|"
                          r"\b(?:but|however|whereas|while)\b|但是|不过|不過|一方", re.I)
CONDITION = re.compile(r"\b(?:if|unless|provided that|only when)\b|若|如果|除非|只有|仅当|僅當", re.I)
CONDITION_TAIL = re.compile(r"\s*(?:if\b|unless\b|provided that\b|若|如果|除非|仅当|僅當|方可|才可|否则|否則)", re.I)
APPROX = re.compile(r"(?:约|約|大概|大约|大約|\babout|\broughly|\bapproximately|[~≈])\s*$", re.I)
LIMITED = re.compile(r"\bonly\b|仅供|僅供|仅限|僅限|只限|仅授权|僅授權|只允许|只允許", re.I)
PERMISSION = re.compile(r"(?:授权|授權|获准|獲准|允许|允許)")
STATUS_PREDICATE = re.compile(r"\b(?:permitted|approved|authorized|allowed|granted|read|unread)\b|"
                              r"获批|獲批|核准|通过|通過|批准|授权|授權|获准|獲准|开放|開放|已读|已讀", re.I)
OLD_ROLE = r"\b(?:previously|initially|formerly|originally|estimated)\b|原定|此前|先前|初估|预估|預估|先估|原估"
NEW_ROLE = r"\b(?:now|currently|revised|corrected|actual)\b|目前|现定|現定|现行|現行|改为|改為|实测|實測|更正为|更正為"
ROLE = re.compile(f"(?P<old>{OLD_ROLE})|(?P<new>{NEW_ROLE})", re.I)
STRUCTURAL_ONLY = re.compile(
    r"(?:(?:role|origin|type|line|stop):\s*)?(?:user|assistant|system|human|tool|injected|unknown|"
    r"text|tool_use|tool_result|end_turn|stop_sequence)|(?:role|origin|type|fields|content|text|line):?", re.I)
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
STOP = set("the a an as is are be was were will by and or of to in for from with this that it has have "
           "still remains remain now previously its only no not yet use uses".split())
RECEIPT = re.compile(r"(?:all\s+)?(?:covered|done|processed|acknowledged|same|duplicate|merged|noted|"
                     r"已[覆盖覆蓋处理處理完成合并合併记录記錄]+|重复|重複|対応済み|処理済み|なし|暂无|無|none|n/?a)[.!。！ ]*", re.I)


def _words(text):
    text = unicodedata.normalize("NFC", text).casefold()
    words = {w for w in re.findall(r"[^\W\d_]+", CJK.sub(" ", text)) if len(w) >= 2 and w not in STOP}
    for run in re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+", text):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def _quantity(match):
    value, unit = match["value"], match["unit"]
    if re.fullmatch(r"[+-]?[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?", value):
        value = value.replace(",", "")
    if unit in {"A", "B", "W", "V"} and re.match(r"\s*(?:组|組|班|类|類|组别|組別)", match.string[match.end():]):
        unit = None
    currency = match["currency"]
    unit = UNIT_ALIASES.get(unit, unit)
    if currency:
        currency = UNIT_ALIASES.get(currency, currency)
        unit = currency if not unit else currency + " " + unit
    return value, unit


def _quantities(text):
    return {_quantity(m) for m in NUMBER.finditer(text)}


def _clause_spans(text):
    start = 0
    for match in CLAUSE_BREAK.finditer(text):
        if match[0] in {",", "，"} and (CONDITION.search(text, start, match.start()) or
                                      CONDITION_TAIL.match(text, match.end())):
            continue
        yield start, match.end()
        start = match.end()
    if start < len(text):
        yield start, len(text)


def _quote_context(source, quote):
    """Include local clause boundaries so selecting a noun cannot hide a negated predicate."""
    start = source.find(quote)
    if start < 0:
        raise ValueError("support excerpt is absent from its cited source")
    # Offsets keep independent clauses apart even when the quotation itself
    # ends with punctuation. Repeated short fragments can have opposite scopes.
    seen = None
    while start >= 0:
        left = max(0, start - 256)
        window = source[left:start + len(quote) + 256]
        begin, end = start - left, start - left + len(quote)
        spans = [(a, b) for a, b in _clause_spans(window) if b > begin and a < end]
        context = window[spans[0][0]:spans[-1][1]].strip().removeprefix("- ").strip()
        if seen is not None and seen != context:
            raise ValueError("ambiguous repeated support; quote a longer passage")
        seen = context
        start = source.find(quote, start + len(quote))
    return seen


def _dominant_script(text):
    counts = {}
    for char in text:
        if char.isalpha():
            script = ("CJK" if CJK.match(char) else unicodedata.name(char, "UNKNOWN").split()[0])
            counts[script] = counts.get(script, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _role_quantities(clause):
    roles = list(ROLE.finditer(clause))
    pairs = set()
    for i, role in enumerate(roles):
        end = roles[i + 1].start() if i + 1 < len(roles) else len(clause)
        pairs.update((role.lastgroup, quantity) for quantity in _quantities(clause[role.end():end]))
    return pairs


def _scope_terms(clause):
    # Keep subjects and predicates for alignment; the values being checked
    # must not decide which of two subjects supplies their own evidence.
    text = NUMBER.sub(" ", clause)
    text = NEGATIVE.sub(" ", text)
    text = re.sub(r"已经|已經|已|尚|并|並|\b(?:already|still)\b", " ", text, flags=re.I)
    return _words(text)


def _subject_action(clause):
    match = PERMISSION.search(clause)
    if match:
        return (clause[:match.start()].strip(" -，,。"), clause[match.end():].strip(" -，,。"))
    return None


def _restriction(clause):
    match = LIMITED.search(clause)
    return clause[match.end():].strip(" ,，.。!?！？;；").casefold() if match else ""


def _condition_text(clause):
    match = CONDITION.search(clause)
    if not match:
        return ""
    return re.split(r"[,，]", clause[match.end():], maxsplit=1)[0].strip(" ,，.。!?！？;；").casefold()


def _approximate_quantities(clause):
    return {_quantity(m) for m in NUMBER.finditer(clause) if APPROX.search(clause, max(0, m.start() - 20), m.start())}


def _verify_claim(claim, excerpts, contexts):
    quantities = _quantities(claim)
    known = _quantities("\n".join(excerpts))
    missing = quantities - known
    if missing:
        raise ValueError(f"unsupported quantity or unit in claim: {sorted(str(n) + (u or '') for n, u in missing)[:8]}")
    patterns = (("negation", NEGATIVE), ("unread", UNREAD), ("condition", CONDITION), ("restricted permission", LIMITED))
    literal = all(claim in excerpt for excerpt in excerpts)
    receipt = dict(quantities=[{"value": n, "unit": u} for n, u in sorted(quantities, key=lambda x: (x[0], x[1] or ""))],
                   wording="source-literal" if literal else "lexical-overlap",
                   semanticEntailment="not-mechanically-verified")
    if literal and all(context == claim for context in contexts):
        receipt["boundaryChecks"] = sorted(label for label, pattern in patterns if pattern.search(claim))
        return receipt
    clauses = [context[a:b] for context in dict.fromkeys(contexts) for a, b in _clause_spans(context)
               if any(c.isalnum() for c in context[a:b])]
    aligned = [(_scope_terms(clause), clause) for clause in clauses]
    role_values = {pair for clause in clauses for pair in _role_quantities(clause)}
    permissions = {pair for clause in clauses if (pair := _subject_action(clause))}
    checks = set()
    terms = _words(claim)
    source_terms = set().union(*(_words(excerpt) for excerpt in excerpts))
    unmatched_scripts = {_dominant_script(term) for term in terms} - {
        _dominant_script(term) for term in terms & source_terms}
    if unmatched_scripts and not literal:
        raise ValueError("mixed-language wording lacks a shared term in each script; retain the original clause")
    for excerpt in excerpts:
        if claim in excerpt or excerpt in claim:
            continue
        if not terms.intersection(_words(excerpt)):
            raise ValueError("support lacks a concrete shared term; write the source-language clause in the claim")
    for a, b in _clause_spans(claim):
        clause = claim[a:b].strip(" \t\n-!?.。！？；;，,")
        if not any(c.isalnum() for c in clause):
            continue
        if not any(clause in excerpt or (_dominant_script(clause) == _dominant_script(excerpt)
                   and _words(clause) & _words(excerpt)) for excerpt in excerpts):
            raise ValueError("no language-aligned support; retain the source-language clause")
        permission = _subject_action(clause)
        if permission and permission not in permissions:
            subject, action = permission
            if any(p[0] == subject for p in permissions) and any(p[1] == action for p in permissions):
                raise ValueError("permission belongs to a different subject in the cited clauses")
        for role, quantity in _role_quantities(clause):
            if any(other == quantity for _, other in role_values) and (role, quantity) not in role_values:
                raise ValueError("quantity conflicts with the cited earlier/current value")
        anchors = _scope_terms(clause)
        scores = [len(anchors & other) for other, _ in aligned]
        best = max(scores, default=0)
        candidates = [source for score, (_, source) in zip(scores, aligned) if score == best]
        for label, pattern in patterns:
            actual = bool(pattern.search(clause))
            candidates = [source for source in candidates if bool(pattern.search(source)) == actual]
            if not candidates:
                raise ValueError(f"claim and selected supporting clauses differ on {label}")
            if actual:
                checks.add(label)
        numbers = _quantities(clause)
        restriction = _restriction(clause)
        if restriction and not any(restriction == _restriction(source) for source in candidates):
            raise ValueError("retain the supported permission or use restriction in its original wording")
        condition = _condition_text(clause)
        if condition and not any(condition == _condition_text(source) for source in candidates):
            raise ValueError("retain the cited condition in its original wording")
        if numbers and len(clauses) > 1 and best and not any(numbers <= _quantities(source) for source in candidates):
            raise ValueError("quantity differs for the selected subject; cite each clause separately")
        if numbers:
            approximate = _approximate_quantities(clause)
            if not any(approximate == numbers & _approximate_quantities(source) for source in candidates):
                raise ValueError("quantity differs in certainty; preserve the estimate or measured value")
    receipt["boundaryChecks"] = sorted(checks)
    return receipt


def validate_draft(text: str, sources: dict[str, str], residuals: dict[str, str], *, final: bool = True,
                   references: dict[str, str] | None = None) -> dict:
    """Validate one completed Markdown draft against the actual frozen task input."""
    references = references or {}
    required = sources.keys() | residuals.keys()
    if sources.keys() & residuals.keys() or required & references.keys():
        raise ValueError("source and residual IDs collide")
    available = {**sources, **residuals, **references}
    lines = text.rstrip().splitlines()
    if not lines or lines[-1] != END or lines.count(END) != 1:
        raise ValueError("draft is truncated or has a misplaced completion marker; retry this task")
    items, sections, used_slots = [], [], set()
    slot = None
    current = None
    topics, supported_topics = [], set()
    topic = None
    for line_no, raw in enumerate(lines[:-1], 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("## "):
            slot = SLOTS.get(line[3:].casefold())
            if slot is None or slot in used_slots:
                raise ValueError(f"unknown or duplicate module on draft line {line_no}")
            used_slots.add(slot)
            sections.append((slot, line))
            current = None
            topic = None
            continue
        if line.startswith("### "):
            title = line[4:].strip()
            if contains_credential(title):
                raise ValueError("replace credential-like material in the topic with a safe description")
            if slot is None or not re.fullmatch(r"[\w][\w \-/·]{0,63}", title) or not any(c.isalpha() for c in title):
                raise ValueError(f"expected a short topic name inside a module on draft line {line_no}")
            topic = len(topics)
            topics.append(title)
            current = None
            continue
        if line.startswith("> ") and current is not None:
            field, bar, quote = line[2:].partition(" | ")
            if not bar or not quote.strip():
                raise ValueError(f"expected a literal support excerpt on draft line {line_no}")
            refs, _, disposition = field.strip().partition(" ")
            for key in _references(refs, available):
                if key not in current["refs"] or key in current["support"]:
                    raise ValueError(f"unattached or duplicate support for {key}")
                if key in residuals and disposition not in {"merged", "duplicate"}:
                    raise ValueError(f"residual {key} needs merged or duplicate")
                if key not in residuals and disposition:
                    raise ValueError(f"unsupported disposition for {key}")
                current["support"][key] = dict(quote=quote, disposition=disposition)
            continue
        match = re.fullmatch(r"- (.+?) +\[([^\[\]\r\n]+)\]", line)
        if not match or slot is None:
            raise ValueError(f"expected a heading or sourced knowledge item on draft line {line_no}")
        claim, field = match[1].strip(), match[2]
        if contains_credential(claim):
            raise ValueError("replace credential-like material in the claim with a safe description")
        if not claim or RECEIPT.fullmatch(claim) or not any(c.isalnum() for c in claim):
            raise ValueError(f"generic receipt or empty claim on draft line {line_no}")
        if re.search(r"<!--|-->|\[@[LH]\d+\]|\[(?:E\d|[A-Z0-9]*R\d)[.,\dA-Z-]*\]|support_text_json=", claim):
            raise ValueError(f"mechanical markup in knowledge text on draft line {line_no}")
        refs = _references(field, available)
        if required.isdisjoint(refs):
            raise ValueError("locked references must accompany current evidence")
        current = dict(slot=slot, topic=topic, claim=claim, refs=refs, support={})
        items.append(current)
    if not items or (final and "state" not in used_slots):
        raise ValueError("final draft needs an explicit current state" if final else "map needs a sourced item")
    if used_slots != {item["slot"] for item in items}:
        raise ValueError("omit empty modules")
    claims, outcomes, used, seen_claims = [], {}, set(), set()
    for item in items:
        claim = item["claim"]
        if claim in seen_claims:
            raise ValueError("repeated knowledge item; group its sources on a single item")
        seen_claims.add(claim)
        excerpts, contexts, links = [], [], {}
        for key in item["refs"]:
            source = available[key]
            explicit = item["support"].get(key)
            if not explicit and key in residuals:
                raise ValueError(f"residual {key} lacks a specific disposition and support")
            quote = explicit["quote"] if explicit else claim
            # Very short sources may themselves be meaningful, e.g. “OK”.
            minimum = 2 if CJK.search(quote) else 6
            if len(quote.strip()) < min(minimum, len(source.strip())) or not any(c.isalnum() for c in quote):
                raise ValueError(f"support for {key} is too short")
            if source.strip() != quote and STRUCTURAL_ONLY.fullmatch(quote.strip()):
                raise ValueError(f"support for {key} contains only a structural label")
            try:
                contexts.append(_quote_context(source, quote))
            except ValueError as exc:
                raise ValueError(f"{key}: {exc}") from exc
            excerpts.append(quote)
            links[key] = quote
            if key in residuals:
                if key in outcomes:
                    raise ValueError(f"residual {key} has multiple dispositions")
                outcomes[key] = dict(disposition=explicit["disposition"], claim=claim, support=quote)
        checks = _verify_claim(claim, excerpts, contexts)
        if item["topic"] is not None:
            title = topics[item["topic"]]
            for quote, context in zip(excerpts, contexts):
                if title in claim and title in quote:
                    if STATUS_PREDICATE.search(title):
                        _verify_claim(title, [title], [_quote_context(context, title)])
                    supported_topics.add(item["topic"])
                    break
        claims.append(dict(module=item["slot"], claim=claim, sources=links, checks=checks))
        used.update(item["refs"])
    missing = sorted(required - used)
    if missing:
        raise ValueError(f"draft misses {len(missing)} source or residual IDs: {missing[:12]}")
    if len(supported_topics) != len(topics):
        raise ValueError("each topic needs an item and a literal topic name in its claim and quoted evidence")
    modules = []
    for key, heading in sections:
        lines = [heading, ""]
        last_topic = None
        for item in items:
            if item["slot"] != key:
                continue
            if item["topic"] != last_topic:
                lines.extend(["### " + topics[item["topic"]], ""])
                last_topic = item["topic"]
            lines.append("- " + item["claim"])
        modules.append("\n".join(lines))
    body = "\n\n".join(modules)
    return dict(body=body, audit=dict(claims=claims, residuals=outcomes, bodySha256=_sha(body),
                                      verify=dict(status="passed", completed=True, sourceCount=len(sources),
                                                  residualCount=len(residuals), itemCount=len(claims))))

"""Offline prepare → independent Map/Reduce submissions → verified JSONL candidate."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import uuid

import v12_evidence as evidence
import v12_memory as memory
import v12_excerpts as excerpts


VERSION = "v12.2"
PRICES = {"writerInput": .1, "writerOutput": .1, "consumerInput": 1., "cacheRead": .1, "cacheWrite": 1.25}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def writable(core, file):
    if core.is_under_claude_root(file):
        raise ValueError("run artifacts must be outside Claude configuration directories")
    if file.is_symlink():
        raise ValueError("run artifacts require a direct path")
    if file.exists() and (not file.is_file() or file.stat().st_nlink != 1):
        raise ValueError("run artifact path is not an independent regular file")


def store(core, path, data, replace=False):
    writable(core, path)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=".stage-", delete=False) as f:
        stage = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            stage.unlink(missing_ok=True)
            raise
    try:
        if replace:
            os.replace(stage, path)
        else:
            core._publish_no_clobber(stage, path)
        core.fsync_parent_directory(path)
    finally:
        stage.unlink(missing_ok=True)


def read_artifact(run, name, expected=None):
    if Path(name).name != name:
        raise ValueError("invalid artifact name")
    p = run / name
    if p.is_symlink() or not p.is_file() or p.stat().st_nlink != 1:
        raise ValueError(f"missing or linked run artifact: {name}")
    data = p.read_bytes()
    if expected is not None and sha(data) != expected:
        raise ValueError(f"run artifact changed: {name}")
    return data


def run_root():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        configured = Path(os.environ.get("XDG_STATE_HOME", ""))
        base = configured if configured.is_absolute() else Path.home() / ".local" / "state"
    return base / "claude-jsonl-compressor" / "runs"


@contextlib.contextmanager
def exclusive(run):
    lock = run / ".operation.lock"
    try:
        handle = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("run is busy; inspect the PID in .operation.lock and remove the lock only "
                         "after confirming that its owner has stopped") from exc
    try:
        os.write(handle, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(handle)
        lock.unlink()


def identity(path):
    s = path.stat()
    return [s.st_dev, s.st_ino]


def verify_snapshot(core, plan):
    src = Path(plan["source"])
    if identity(src) != plan["sourceIdentity"] or core.file_sha256(src) != plan["sourceSha256"]:
        raise ValueError("source changed since preparation; start a new run")
    backup = Path(plan["backup"])
    if backup.is_symlink() or identity(backup) != plan["backupIdentity"] or os.path.samefile(src, backup) or core.file_sha256(backup) != plan["sourceSha256"]:
        raise ValueError("frozen backup identity or bytes changed")
    return src


def implementation(core):
    files = [Path(core.__file__), Path(__file__), Path(evidence.__file__), Path(memory.__file__),
             Path(core._session_tools.__file__), Path(excerpts.__file__)]
    return sha(b"".join(bytes.fromhex(core.file_sha256(p)) for p in files))


def load_run(core, path):
    run = path.resolve(strict=True)
    if core.is_under_claude_root(run) or path.is_symlink():
        raise ValueError("invalid run directory")
    raw = read_artifact(run, "run-plan.json")
    plan = json.loads(raw)
    state = json.loads(read_artifact(run, "state.json"))
    if state["planSha256"] != sha(raw) or plan["schema"] != VERSION or plan["implementation"] != implementation(core):
        raise ValueError("plan or implementation changed; prepare a fresh run")
    # First-level request bytes are independently bound by the frozen plan.
    if state["level"] == 0 and state["jobs"] != plan["jobs"]:
        raise ValueError("Map tasks differ from the frozen plan")
    if state["level"] > 0:
        sealed = json.loads(read_artifact(run, f"reduce-{state['level']}.json",
                                         state["reductionSha256"]))
        if sealed["jobs"] != state["jobs"] or sealed["planSha256"] != state["planSha256"]:
            raise ValueError("Reduce tasks differ from their frozen parents")
        for parent, expected in sealed["parents"].items():
            if state["accepted"].get(parent) != expected:
                raise ValueError("Reduce parent changed")
            read_artifact(run, parent+".accepted.json", expected)
    return run, plan, state


def locked_display(views):
    if not views:
        return ""
    lines = ["Optional locked context. Cite L with a new source when reconciling a change. "
             "Only the following ranges were shown; do not repeat the locked text in the new layer."]
    for key, view in views.items():
        lines.append(f"{key} {view['prior']} at source line {view['line']}, "
                     f"characters [{view['start']},{view['end']}) of {view['total']}:\n{view['text']}")
    return "\n".join(lines) + "\n"


def job_files(core, run, name, group, pool, stage, profile, store_files):
    request, sources, residuals = evidence.request_for(group, pool, stage)
    references = profile.get("lockedViews", {})
    request += locked_display(references)
    text = request.encode("utf-8")
    catalog = {k:v for u in group for k,v in u.get("catalog", {}).items()}
    spans = {k:v for u in group for k,v in u.get("residualRanges", {}).items()}
    support = encode({"sources": sources, "residuals": residuals, "excerpts": catalog,
                      "residualRanges": spans, "references": {k:v["text"] for k,v in references.items()}})
    size = core.estimate_tokens(request)
    if size > profile["packLimit"]:
        raise ValueError("rendered job exceeds input limit")
    job = dict(id=name, stage=stage, request=name + ".md", requestSha256=sha(text),
               support=name + ".sources.json", supportSha256=sha(support), requestTokens=size,
               inputEstimate=size + profile["otherInput"],
               lines=[u.get("lines", []) for u in group], sources=list(sources))
    if store_files:
        for k, data in ((job["request"], text), (job["support"], support)):
            dst = run/k
            if dst.exists():
                read_artifact(run, k, sha(data))
            else:
                store(core, dst, data)
    return job


def settings(args):
    if not (.05 <= args.target_ratio <= .95) or args.min_recent_records < 0 or args.min_recent_turns < 0:
        raise ValueError("invalid target ratio or recent window")
    if args.target_estimated_tokens is not None and args.target_estimated_tokens < 1000:
        raise ValueError("final target must be at least 1000")
    if args.summary_char_budget < 4000:
        raise ValueError("summary character budget must be at least 4000")
    return dict(target_ratio=args.target_ratio, min_recent_records=args.min_recent_records,
                summary_char_budget=args.summary_char_budget, target_estimated_tokens=args.target_estimated_tokens,
                min_recent_turns=args.min_recent_turns, checkpoint_policy=args.checkpoint_policy,
                resume_leaf_override=args.resume_leaf, max_file_history_snapshots=args.max_file_history_snapshots)


def prepare(core, args):
    source = args.input.resolve(strict=True)
    if not source.is_file():
        raise ValueError("expected one JSONL file")
    cfg = settings(args)
    profile = evidence.profile(args.window, args.input_limit, args.other_input, args.generation,
                               args.output_limit, args.thinking, args.margin, args.max_attempts)
    prices = dict(PRICES)
    if args.prices:
        override = json.loads(args.prices.read_text(encoding="utf-8-sig"))
        if not isinstance(override, dict) or set(override) - prices.keys():
            raise ValueError("unknown relative price parameter")
        prices.update(override)
    if any(not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in prices.values()):
        raise ValueError("prices must be finite non-negative numbers")
    data = source.read_bytes()
    source_hash = sha(data)
    rows, raw, physical = core.parse_jsonl_bytes_with_lines(data)
    if args.max_file_history_snapshots < 0:
        raise ValueError("snapshot limit must be non-negative")
    pointer = core.latest_last_prompt_entry(rows)
    closures = core.closed_turn_candidates(rows, pointer[1]) if pointer else []
    ratio, _ = core.effective_target_ratio_for_tokens(rows, args.target_ratio, args.target_estimated_tokens)
    part = core.select_preservation_plan(rows, raw, len(data), ratio, args.min_recent_records, args.summary_char_budget,
              True, 0, args.max_file_history_snapshots, args.checkpoint_policy, args.resume_leaf, args.min_recent_turns)
    try:
        core.validate_source_active_chain_for_plan(rows, part, physical_lines=physical, v12_migration=True)
    except ValueError as exc:
        if closures:
            raise ValueError(f"{exc}; inspect the eligible end points with --preflight: "
                             + ", ".join(c["leafUuid"] for c in closures)) from exc
        raise
    info = part["preserve_info"]
    if info.get("retainedRecentTurns", 0) < args.min_recent_turns:
        raise ValueError("selected chain cannot satisfy the requested recent human turns")
    groups, pool, ledger, prior = evidence.units(core, part, physical, args.prior, args.media, memory)
    if not groups:
        raise ValueError("no semantic evidence for a new compression layer")
    if args.excerpts < 0:
        raise ValueError("excerpt count must be non-negative")
    views = memory.locked_references(prior, args.locked_context_chars, args.locked_range)
    reference_tokens = core.estimate_tokens(locked_display(views))
    evidence_limit = profile["packLimit"] - reference_tokens - (2 if views else 0)
    if evidence_limit <= 0:
        raise ValueError("locked context exceeds input profile; narrow --locked-range or --locked-context-chars")
    profile.update(evidenceLimit=evidence_limit, lockedViews=views)
    groups = evidence.migration_units(core, groups, evidence_limit)
    windows = evidence.partition(core, groups, pool, evidence_limit, "map", profile["output"])
    if args.excerpts:
        indexed = []
        for window in windows:
            sources = {u["id"]:u["support"] for u in window if u["support"]}
            for unit in window:
                sources.update(unit["residuals"])
            offered = excerpts.catalog_request(sources, args.excerpts)
            for unit in window:
                available = set(unit["residuals"])
                if unit["support"]:
                    available.add(unit["id"])
                choices = {k:v for k,v in offered.items() if v["source"] in available}
                # The complete payload takes priority when an index would
                # push an otherwise indivisible source beyond the window.
                enriched = with_index(unit, choices)
                if core.estimate_tokens(evidence.request_for([enriched], pool, "map")[0]) > evidence_limit:
                    enriched = unit
                indexed.append(enriched)
        windows = evidence.partition(core, indexed, pool, evidence_limit, "map", profile["output"])
    locked = "\n\n".join(p["locked"] for p in prior if p["locked"])
    leaf = part["selected_leaf_uuid"]
    active = [rows[i] for i in info["resumeLeafInfo"]["activeChainIndexes"]]
    tracks = evidence.token_panel(core, active)
    # Dry construction includes the native boundary, title, pointer and checkpoint
    # metadata. Keep the smallest legal new layer when estimating the fixed floor.
    bound_record = binding(source_hash, leaf, part["omitted_indexes"], combine(locked, "X"), "0"*64)
    options = dict(cfg, target_session_id=args.target_session_id or (source.stem if args.live else None))
    dry = core.compress_jsonl(source, None, **dict(options, target_estimated_tokens=cfg["target_estimated_tokens"]),
                              v12_memory=bound_record, v12_measure_only=True, write_sidecar_files=False)
    budget = args.target_estimated_tokens
    room = budget - dry["fixedTokens"] if budget is not None else None
    if room is not None and room < 1:
        raise ValueError(f"target-budget-infeasible: fixed floor {dry['fixedTokens']}, target {budget}")
    if len(locked) >= args.summary_char_budget:
        raise ValueError("locked prior text alone reaches the requested final character budget")
    planned = [job_files(core, None, f"map-{i:03d}", w, pool, "map", profile, False) for i,w in enumerate(windows,1)]
    preview_profile = {k:v for k,v in profile.items() if k != "lockedViews"}
    preview = dict(state="ready", sourceSha256=source_hash, selectedLeaf=leaf, profile=preview_profile,
                   lockedContextTokens=reference_tokens, lockedRanges=[
                       {k:v for k,v in view.items() if k != "text"} for view in views.values()],
                   maps=len(windows), reduceRequired=len(windows)>1,
                   peakInputEstimate=max(j["inputEstimate"] for j in planned),
                   sumMapInputEstimate=sum(j["inputEstimate"] for j in planned), fixedTokens=dry["fixedTokens"],
                   finalNewTextRoomEstimate=room, finalCharacters=args.summary_char_budget,
                   intermediateAllowance=len(planned)*profile["output"], inputTracks=tracks,
                   payloadCounts=dict(evidence.Counter(i["status"] for i in ledger)),
                   retainedHumanTurns=info.get("retainedRecentTurns",0))
    preview["closedTurnCandidates"] = closures
    if args.action == "plan":
        return preview
    run = args.run.resolve() if args.run else (run_root() / uuid.uuid4().hex).resolve()
    core.guard_artifact_roles(source, run=run, backup_dir=args.backup_dir)
    if core.is_under_claude_root(run) or (args.backup_dir and core.is_under_claude_root(args.backup_dir)):
        raise ValueError("choose a run and external backup directory outside Claude configuration")
    if args.live:
        if not core.is_under_claude_projects(source) or not args.confirm_session_closed:
            raise ValueError("live preparation requires a closed, named Claude project session")
        core.require_live_session_jsonl(source)
    if run == source or run.exists():
        raise ValueError("choose a new run directory; use status to resume an existing run")
    run.mkdir(parents=True, mode=0o700)
    if core.file_sha256(source) != source_hash:
        raise ValueError("source changed during planning")
    try:
        backup = core._exclusive_backup_from_bytes(source, data, args.backup_dir)
    except PermissionError as exc:
        raise ValueError("backup directory is not writable; choose a writable --backup-dir "
                         "and prepare a new run") from exc
    if core.file_sha256(source) != source_hash:
        raise ValueError("source changed during backup")
    jobs = [job_files(core, run, j["id"], w, pool, "map", profile, True) for j,w in zip(planned,windows)]
    audit = encode({"ledger": ledger, "priors": prior})
    store(core, run/"source-audit.json", audit)
    # Recovery previews can contain text outside the selected branch. Keep them
    # in the operator's diagnosis, never in the author's run plan or evidence.
    saved_preview = {k:v for k,v in preview.items() if k != "closedTurnCandidates"}
    plan = dict(saved_preview, schema=VERSION, implementation=implementation(core), source=str(source),
                sourceIdentity=identity(source), backup=str(backup), backupIdentity=identity(backup),
                backupDir=str(args.backup_dir.resolve()) if args.backup_dir else None, policy=args.prior,
                media=args.media, options=options, live=args.live, leaf=leaf,
                omitted=part["omitted_indexes"], raw=part["raw_keep_indexes"],
                sourceAuditSha256=sha(audit), jobs=jobs, prices=prices, excerptLimit=args.excerpts)
    plan["profile"] = profile
    frozen = encode(plan)
    store(core, run/"run-plan.json", frozen)
    state = {"planSha256": sha(frozen), "jobs": jobs, "accepted": {}, "events": [], "level": 0}
    store(core, run/"state.json", encode(state))
    return dict(preview, run=str(run), next="submit one Markdown draft per map job",
                requests=[j["request"] for j in jobs])


def binding(source_hash, leaf, omitted, body, audit_hash):
    return dict(source=source_hash, leaf=leaf, omitted=omitted, body=body, auditSha256=audit_hash)


def combine(locked, new):
    return locked + "\n\n" + new if locked else new


def with_index(unit, catalog, inherited=None):
    inherited = inherited or {}
    catalog = {key: rec for key, rec in catalog.items() if key not in inherited}
    if not (catalog or inherited):
        return unit
    lookup = ("Optional literal passages. For each useful passage write "
              "@keep ID | current/history/superseded/unresolved | source, version and scope. "
              "Put choices before the completion marker.")
    sections = [lookup]
    if inherited:
        sections.append(excerpts.catalog_index(inherited, full=True))
    if catalog:
        sections.append(excerpts.catalog_index(catalog))
    return dict(unit, catalog={**inherited, **catalog}, index="\n".join(sections))


def reduce_unit(number, parent, body, selected, limit):
    tag = f"E{number}"
    unit = dict(id=tag, text=body, support=body, residuals={}, refs=[], lines=[parent])
    # Local passages are visible in the body. Earlier literal selections live
    # only in the parent receipt, so the reducer must receive their complete text.
    local = excerpts.catalog_request({tag: body}, limit) if limit else {}
    return with_index(unit, local, excerpts.carry_catalog(selected))


def save_state(core, run, state):
    store(core, run/"state.json", encode(state), replace=True)


def find_job(state, task):
    for job in state["jobs"]:
        if job["id"] == task:
            return job
    raise ValueError("unknown task; see status for pending jobs")


def verified_final(core, run, plan, state):
    """Reconstruct the path to the final task from the frozen Map set."""
    jobs = plan["jobs"]
    known = set()
    for level in range(len(plan["jobs"])):
        parents = {}
        for job in jobs:
            name = job["id"]
            expected = state["accepted"].get(name)
            if not expected:
                raise ValueError(f"pending source task: {name}")
            read_artifact(run, job["request"], job["requestSha256"])
            read_artifact(run, job["support"], job["supportSha256"])
            accepted = json.loads(read_artifact(run, name+".accepted.json", expected))
            if (accepted["request"] != job["requestSha256"] or accepted["support"] != job["supportSha256"]
                    or accepted["parents"] != job["lines"] or
                    sha(accepted["body"].encode("utf-8")) != accepted["bodySha256"]):
                raise ValueError("accepted draft differs from its assigned source task")
            parents[name] = expected
        known.update(parents)
        if len(jobs) == 1:
            last = jobs[0]["id"]
            if (last != state.get("finalJob") or level != state["level"] or jobs != state["jobs"]
                    or known != set(state["accepted"])):
                raise ValueError("final state does not match the complete Map/Reduce ancestry")
            return last
        sealed = json.loads(read_artifact(run, f"reduce-{level+1}.json"))
        if sealed["parents"] != parents or sealed["planSha256"] != state["planSha256"]:
            raise ValueError("Reduce is missing its exact parent tasks")
        nxt = sealed["jobs"]
        if not 0 < len(nxt) < len(jobs):
            raise ValueError("invalid Reduce fan-in")
        # A Reduce layer must account for every prior note, in order, once.
        covered = [parent for job in nxt for group in job["lines"] for parent in group]
        if covered != list(parents):
            raise ValueError("Reduce does not cover every previous task in order")
        jobs = nxt
    raise ValueError("final Reduce is missing")


def advance(core, run, plan, state):
    current = state["jobs"]
    completed = state["accepted"]
    if not all(j["id"] in completed for j in current):
        return
    if len(current) == 1:
        last = current[0]["id"]
        latest = json.loads(read_artifact(run, last+".accepted.json", completed[last]))
        prior = json.loads(read_artifact(run, "source-audit.json", plan["sourceAuditSha256"]))
        locked = "\n\n".join(p["locked"] for p in prior["priors"] if p["locked"])
        complete = combine(locked, latest["body"])
        if len(complete) > plan["finalCharacters"]:
            raise ValueError("final draft exceeds the frozen character budget; shorten this final draft")
        ceiling = plan["options"]["target_estimated_tokens"]
        if ceiling is not None:
            test = binding(plan["sourceSha256"], plan["leaf"], plan["omitted"], complete, "0"*64)
            actual = core.compress_jsonl(Path(plan["source"]), None, **plan["options"], v12_memory=test,
                                         v12_measure_only=True, write_sidecar_files=False)["fixedTokens"]
            if actual > ceiling:
                raise ValueError(f"final draft needs {actual} structured tokens, ceiling {ceiling}; shorten this final draft")
        state["finalJob"] = last
        return
    # Hierarchical reductions carry source coverage transitively through accepted task hashes.
    entries = []
    for i, j in enumerate(current, 1):
        note = json.loads(read_artifact(run, j["id"]+".accepted.json", completed[j["id"]]))
        entries.append(reduce_unit(i, j["id"], note["body"], note["excerpts"], plan["excerptLimit"]))
    windows = evidence.partition(core, entries, {}, plan["profile"]["evidenceLimit"], "reduce")
    if len(windows) >= len(current):
        raise ValueError("reduce notes exceed profile; use more compact intermediate drafts or a larger input allowance")
    level = state["level"]+1
    jobs = [job_files(core, run, f"reduce-{level}-{i:03d}", w, {}, "reduce", plan["profile"], True)
            for i,w in enumerate(windows, 1)]
    sealed = encode({"jobs": jobs, "planSha256": state["planSha256"],
                     "parents": {j["id"]:completed[j["id"]] for j in current}})
    name = f"reduce-{level}.json"
    if (run/name).exists():
        read_artifact(run, name, sha(sealed))
    else:
        store(core, run/name, sealed)
    state.update(level=level, jobs=jobs, reductionSha256=sha(sealed))


def submit(core, run, plan, state, args):
    verify_snapshot(core, plan)
    if state.get("finalJob"):
        raise ValueError("final draft already accepted")
    job = find_job(state, args.task)
    if job["id"] in state["accepted"]:
        raise ValueError("task already accepted")
    read_artifact(run, job["request"], job["requestSha256"])
    support = json.loads(read_artifact(run, job["support"], job["supportSha256"]))
    name = job["id"]
    attempts = sum(e.get("task")==name for e in state["events"])
    if attempts >= plan["profile"]["maxAttempts"]:
        raise ValueError("frozen retry allowance exhausted")
    src_path = args.draft.resolve(strict=True)
    if core.is_under_claude_root(src_path) or os.path.samefile(src_path, plan["source"]):
        raise ValueError("draft must be a distinct work file")
    raw = src_path.read_bytes()
    text = raw.decode("utf-8-sig")
    output_est = core.estimate_tokens(text)
    profile = plan["profile"]
    event = dict(kind="submit", stage=job["stage"], task=name, inputEstimate=job["inputEstimate"],
                 outputEstimate=output_est, observedInput=args.observed_input, observedOutput=args.observed_output,
                 draftSha256=sha(raw))
    state["events"].append(event)
    try:
        if args.observed_input is not None and args.observed_input < 0 or args.observed_output is not None and args.observed_output < 0:
            raise ValueError("observed counts must be non-negative")
        inp = max(job["inputEstimate"], args.observed_input or 0)
        gen = max(output_est + profile["thinking"], args.observed_output or 0)
        if output_est > profile["output"] or gen > profile["outputLimit"] or inp >= min(profile["inputLimit"],300000) or inp+gen+profile["margin"]>min(profile["window"],372000):
            raise ValueError("input or generated draft exceeds this task's frozen profile")
        if args.stop_reason in ("length", "max_tokens", "interrupted"):
            raise ValueError("truncated generation; retry this task")
        clean, selected = excerpts.parse_selections(text, support["excerpts"])
        literal_sources = {**support["sources"], **support["residuals"]}
        local = [s for s in selected if s["source"] in literal_sources and
                 s["sourceSha256"] == sha(literal_sources[s["source"]].encode())]
        if job["stage"] == "map" and len(local) != len(selected):
            raise ValueError("selected excerpt is not bound to this Map source")
        excerpts.verify_selected(local, literal_sources)
        final = len(state["jobs"])==1
        validated = memory.validate_draft(clean, support["sources"], support["residuals"], final=final,
                                          references=support.get("references"))
        extra = excerpts.render_selected(selected, plan["finalCharacters"]) if final else ""
        body = combine(validated["body"], extra) if extra else validated["body"]
        if not final:
            number = state["jobs"].index(job) + 1
            unit = reduce_unit(number, name, body, selected, plan["excerptLimit"])
            evidence.check_reduce_size(core, unit, profile["evidenceLimit"])
        accepted = encode({"body":body, "bodySha256":sha(body.encode()), "audit":validated["audit"], "excerpts":selected,
                           "request": job["requestSha256"], "support": job["supportSha256"],
                           "parents": job["lines"], "draftSha256": sha(raw)})
        dest = name+".accepted.json"
        prior_accepted = dict(state["accepted"])
        state["accepted"][name] = sha(accepted)
        file = run/dest
        if file.exists():
            # Recover the prepared artifact of an interrupted local submit.
            read_artifact(run, dest, sha(accepted))
        else:
            store(core, file, accepted)
        try:
            advance(core, run, plan, state)
        except Exception:
            state["accepted"] = prior_accepted
            if read_artifact(run, dest, sha(accepted)) == accepted:
                file.unlink()
            raise
        event["status"] = "accepted"
    except (ValueError, OSError) as exc:
        event.update(status="failed", reason=str(exc))
        save_state(core, run, state)
        raise
    save_state(core, run, state)
    return status(state)


def status(state):
    return {"pending": [j["id"] for j in state["jobs"] if j["id"] not in state["accepted"]],
            "finalJob": state.get("finalJob"), "attempts": len(state["events"]), "level": state["level"]}


def finalize(core, run, plan, state, args):
    if args.replace_original and (not plan["live"] or not args.confirm_session_closed):
        raise ValueError("live installation requires live preparation and a closed session")
    src = verify_snapshot(core, plan)
    if not state.get("finalJob"):
        raise ValueError("complete pending Map/Reduce tasks before finalization")
    final = verified_final(core, run, plan, state)
    if state.get("replacement"):
        raise ValueError("this run already installed a candidate; inspect the receipt")
    source_audit = json.loads(read_artifact(run, "source-audit.json", plan["sourceAuditSha256"]))
    docs = {name:json.loads(read_artifact(run, name+".accepted.json", h)) for name,h in state["accepted"].items()}
    locked = "\n\n".join(p["locked"] for p in source_audit["priors"] if p["locked"])
    body = combine(locked, docs[final]["body"])
    if len(body)>plan["options"]["summary_char_budget"]:
        raise ValueError("final memory exceeds the frozen character budget")
    audit = {"schema": VERSION, "planSha256": state["planSha256"], "sourceSha256": plan["sourceSha256"],
             "bodySha256": sha(body.encode()), "sourceAuditSha256": plan["sourceAuditSha256"],
             "tasks": state["accepted"], "finalTask": final,
             "verification": {k:v["audit"].get("verify") for k,v in docs.items()}}
    raw_audit = encode(audit)
    v12 = binding(plan["sourceSha256"], plan["leaf"], plan["omitted"], body, sha(raw_audit))
    path = run/"candidate.jsonl"
    audit_path = run/"audit.json"
    if not audit_path.exists():
        store(core, audit_path, raw_audit)
    else:
        read_artifact(run, "audit.json", sha(raw_audit))
    if path.exists():
        previous = state.get("candidateSha256")
        if not previous or core.file_sha256(path)!=previous:
            raise ValueError("candidate already exists without matching receipt; preserve it and use a new run")
        report = json.loads(read_artifact(run, "result.json", state["resultSha256"]))
    else:
        # Stage in an owned directory so publication can use an exclusive link.
        with tempfile.TemporaryDirectory(dir=run, prefix=".candidate-") as stage:
            staged = Path(stage)/"candidate.jsonl"
            report = core.compress_jsonl(src, staged, **plan["options"], v12_memory=v12, write_sidecar_files=False)
            verify_snapshot(core, plan)
            core._publish_no_clobber(staged, path)
        core.fsync_parent_directory(run)
        result = core.validate_jsonl(path, contract="fresh-candidate")
        if not result["ok"]:
            raise ValueError("published candidate failed independent structural verification")
        rows, _ = core.read_jsonl(path)
        out = evidence.token_panel(core, rows)
        report = dict(candidateSha256=core.file_sha256(path), auditSha256=sha(raw_audit), outputTracks=out,
                      inputTracks=plan["inputTracks"], structure=result["ok"], operation="candidate-verified",
                      cost=evidence.cost_report(plan["inputTracks"]["estimatedApiMessageTokens"],
                          out["estimatedApiMessageTokens"], state["events"], plan["prices"]))
        packed = encode(report)
        store(core, run/"result.json", packed)
        state.update(candidateSha256=report["candidateSha256"], resultSha256=sha(packed))
        save_state(core, run, state)
    if args.replace_original:
        back = Path(plan["backup"])
        txn = core._replace_file_after_validation(path, src, backup_dir=Path(plan["backupDir"]) if plan["backupDir"] else None,
              expected_source_sha256=plan["sourceSha256"], expected_candidate_sha256=state["candidateSha256"],
              frozen_backup=(back,*plan["backupIdentity"]), validation_contract="fresh-candidate")
        receipt = {"operation":txn["operation_state"],"backup":str(txn["backup_path"]),
                   "sourceSha256":txn["source_sha256"],"candidateSha256":txn["published_sha256"],
                   "cleanup":txn["cleanup_errors"]}
        try:
            store(core, run/"replacement.json", encode(receipt))
            state["replacement"] = receipt
            save_state(core, run, state)
        except Exception as exc:
            return dict(receipt, operation="committed-report-failed", error=str(exc), exitCode=3)
        return dict(receipt, exitCode=3 if txn["cleanup_errors"] else 0)
    return report


def parser():
    p = argparse.ArgumentParser(prog="claude-jsonl-compressor v12")
    subs = p.add_subparsers(dest="action", required=True)
    for action in ("plan","prepare"):
        s = subs.add_parser(action, help="inspect a source" if action=="plan" else "freeze a run and prepare evidence")
        s.add_argument("--input",type=Path,required=True)
        s.add_argument("--run",type=Path)
        s.add_argument("--backup-dir",type=Path)
        s.add_argument("--resume-leaf")
        s.add_argument("--target-session-id")
        s.add_argument("--live",action="store_true")
        s.add_argument("--confirm-session-closed",action="store_true")
        s.add_argument("--prior",choices=("verbatim-locked","clean-and-merge","resynthesize"),default="resynthesize")
        s.add_argument("--locked-context-chars",type=int,default=1600,
                       help="Total characters of locked prior text shown per task (default 1600)")
        s.add_argument("--locked-range",action="append",default=[],metavar="P1:START-END",
                       help="Show an exact zero-based, half-open range of a locked prior; repeatable")
        s.add_argument("--media",choices=("block","archive"),default="block")
        s.add_argument("--target-ratio",type=float,default=.3)
        s.add_argument("--target-estimated-tokens",type=int)
        s.add_argument("--summary-char-budget",type=int,default=60000)
        s.add_argument("--min-recent-records",type=int,default=120)
        s.add_argument("--min-recent-turns",type=int,default=0)
        s.add_argument("--checkpoint-policy",choices=("active-correlated","none"),default="active-correlated")
        s.add_argument("--max-file-history-snapshots",type=int,default=80)
        s.add_argument("--window",type=int,default=372000)
        s.add_argument("--input-limit",type=int,default=300000)
        s.add_argument("--other-input",type=int,default=60000)
        s.add_argument("--generation",type=int,default=16000)
        s.add_argument("--output-limit",type=int,default=32000)
        s.add_argument("--thinking",type=int,default=4000)
        s.add_argument("--margin",type=int,default=8000)
        s.add_argument("--max-attempts",type=int,default=3)
        s.add_argument("--excerpts",type=int,default=96,help="Maximum optional source passages to offer per evidence window")
        s.add_argument("--prices",type=Path)
    s=subs.add_parser("status")
    s.add_argument("--run",type=Path,required=True)
    s=subs.add_parser("submit")
    s.add_argument("--run",type=Path,required=True)
    s.add_argument("--task",required=True)
    s.add_argument("--draft",type=Path,required=True)
    s.add_argument("--stop-reason",default="complete",choices=("complete","length","max_tokens","interrupted"))
    s.add_argument("--observed-input",type=int)
    s.add_argument("--observed-output",type=int)
    s=subs.add_parser("finish")
    s.add_argument("--run",type=Path,required=True)
    s.add_argument("--replace-original",action="store_true")
    s.add_argument("--confirm-session-closed",action="store_true")
    return p


def main(argv, core):
    args = parser().parse_args(argv)
    try:
        if args.action in ("plan","prepare"):
            result=prepare(core,args)
        else:
            run,plan,state=load_run(core,args.run)
            if args.action == "status":
                result=status(state)
            else:
                with exclusive(run):
                    run,plan,state=load_run(core,args.run)
                    result=submit(core,run,plan,state,args) if args.action=="submit" else finalize(core,run,plan,state,args)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return result.get("exitCode",0)
    except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
        core.eprint(f"ERROR: {exc}")
        return 1

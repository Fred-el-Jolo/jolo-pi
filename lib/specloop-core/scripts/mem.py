#!/usr/bin/env python3
"""specloop memory CLI — the bridge between the engine and the agent.

Minimal two-touch model (see ../references/loop.md):
  - START (read) : ``mem start "<prompt>"`` → recall similar past recaps
  - END   (write): ``echo '<digest>' | mem recap --initial-prompt "<p>"``
                   → one chat call → one recap node

There is NO mid-session recall, NO per-error capture, NO per-turn write. The
pi extension drives both touches from session hooks (recall on the first
prompt, recap on session shutdown).

Env:
  SPECLOOP_DB        sqlite path (default ~/.specloop/memory.db)
  SPECLOOP_PROVIDER  embedding provider: mistral|zai|openai|hash (default mistral)
  SPECLOOP_PROJECT   project scope key (default: git toplevel basename)
  SPECLOOP_CHAT_PROVIDER  recap chatter: mistral|openai|zai (default mistral)
  SPECLOOP_CHAT_MODEL     chat model override (default: provider default)
  MISTRAL_API_KEY    (or ZAI_API_KEY / OPENAI_API_KEY) — required for remote
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from engine import HashEmbedder, Memory, PROVIDERS, make_embedder  # noqa: E402
from semantic import CHATTERS, make_chatter, extract_lessons  # noqa: E402
from lesson import LessonPolicy, render_body  # noqa: E402
from redact import redact  # noqa: E402
import status  # noqa: E402
from audit import log as audit_log, read as audit_read  # noqa: E402
from usage import read as usage_read, rollup_by_day, rollup_by_session  # noqa: E402


def detect_project() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.basename(r.stdout.strip())
    except Exception:
        pass
    return os.path.basename(os.getcwd())


def build_embedder(name: str):
    if name == "hash":
        return HashEmbedder()
    if name not in PROVIDERS:
        raise SystemExit(f"unknown embedder '{name}'. known: hash, {', '.join(PROVIDERS)}")
    return make_embedder(name)  # raises RuntimeError if the provider key is missing


def chatter_from_args(args) -> "Chatter":
    provider = getattr(args, "chat_provider", None) or os.environ.get("SPECLOOP_CHAT_PROVIDER", "mistral")
    if provider not in CHATTERS:
        raise SystemExit(f"unknown chat provider '{provider}'. known: {', '.join(CHATTERS)}")
    model = getattr(args, "chat_model", None) or os.environ.get("SPECLOOP_CHAT_MODEL")
    return make_chatter(provider, **({"model": model} if model else {}))


SESSION = os.environ.get("SPECLOOP_SESSION")


def _default_scope() -> str:
    """Recall scope. Defaults to GLOBAL; SPECLOOP_SCOPE=local forces per-project
    isolation for users who don't want cross-project recall even with redaction."""
    return "local" if os.environ.get("SPECLOOP_SCOPE", "").strip().lower() == "local" else "global"


def _stamp(meta: dict) -> dict:
    """Tag a node's meta with the current pi session id (when set) so memory
    nodes can be joined to pi sessions via the audit log too."""
    if SESSION:
        meta = dict(meta)
        meta.setdefault("session", SESSION)
    return meta


# small meta fields worth keeping in the (terse) audit line
_AUDIT_META_KEYS = ("status",)


def _log_write(ntype: str, nid: str | None, outcome: str = "new",
                meta: dict | None = None) -> None:
    audit_log({"event": "write", "type": ntype, "id": nid, "outcome": outcome,
              "status": (meta or {}).get("status")})


def open_memory(args) -> Memory:
    db = args.db or os.environ.get("SPECLOOP_DB") or os.path.expanduser("~/.specloop/memory.db")
    os.makedirs(os.path.dirname(db) or ".", exist_ok=True)
    project = args.project or os.environ.get("SPECLOOP_PROJECT") or detect_project()
    emb = build_embedder(args.embedder or os.environ.get("SPECLOOP_PROVIDER", "mistral"))
    return Memory(db, embedder=emb, current_project=project)


def body_for(ntype: str, text: str, meta: dict) -> str:
    if ntype == "prompt":
        cats = meta.get("categories")
        return " ".join(filter(None, [text, " ".join(cats) if cats else ""]))
    return text


def emit(rows, args):
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    for r in rows:
        score = r.get("_score")
        sc = f"{score:.3f}  " if score is not None else "        "
        print(f"{sc}{r['id']:<20} {r['type']:<8} {r.get('project') or '-':<14} | {r['body'][:80]}")


def cmd_recall(m, args):
    emit(m.recall(args.query, k=args.k, scope=args.scope, node_type=args.type), args)


def cmd_remember(m, args):
    meta = {}
    if args.categories:
        meta["categories"] = [c.strip() for c in args.categories.split(",")]
    if args.meta:
        meta.update(json.loads(args.meta))
    meta = _stamp(meta)
    body = body_for(args.type, args.body, meta)
    before = m.count()
    nid = m.index({"type": args.type, "body": body, "meta": meta})
    outcome = "merged" if m.count() == before else "new"
    _log_write(args.type, nid, outcome=outcome, meta=meta)
    print(json.dumps({"id": nid, "outcome": outcome}) if args.json
          else f"{nid}{'  (merged — dedup)' if outcome == 'merged' else ''}")


def cmd_stats(m, args):
    rows = m.conn.execute("SELECT type, COUNT(*) c FROM nodes GROUP BY type ORDER BY type").fetchall()
    data = {r["type"]: r["c"] for r in rows}
    if args.json:
        print(json.dumps(data))
    else:
        for t, c in data.items():
            print(f"{c:>5}  {t}")
        print(f"{sum(data.values()):>5}  total")


def cmd_export(m, args):
    import os
    os.makedirs(args.out_dir, exist_ok=True)
    rows = m.conn.execute(
        "SELECT id,type,project,body,meta FROM nodes ORDER BY created").fetchall()
    mem_path = os.path.join(args.out_dir, "memory.jsonl")
    with open(mem_path, "w") as f:
        for r in rows:
            f.write(json.dumps({
                "id": r["id"], "type": r["type"], "project": r["project"],
                "body": r["body"], "meta": json.loads(r["meta"] or "{}"),
            }) + "\n")
    print(f"wrote {len(rows)} nodes → {mem_path}")
    if args.scaffold_queries:
        qpath = os.path.join(args.out_dir, "queries.jsonl")
        n = 0
        with open(qpath, "w") as f:
            for r in rows:
                f.write(json.dumps({"query": r["body"], "expected_ids": [r["id"]],
                                    "type": r["type"]}) + "\n")
                n += 1
        print(f"wrote {n} self-match scaffold queries → {qpath}")
        print("  ⚠ self-match (query==body) → expect R@1≈1.0; REPLACE with realistic")
        print("    labeled queries for a real quality number.")
    print(f"\nbenchmark:  python3 scripts/bench.py --corpus {os.path.abspath(args.out_dir)}")


def cmd_start(m, args):
    """START (read): recall similar past recaps for this prompt. Read-only —
    nothing is indexed here; the recap node is written at session end."""
    recalls = m.recall(args.prompt, k=args.k, scope=_default_scope())
    out = {"recalls": recalls}
    print(json.dumps(out, indent=2, default=str) if args.json
          else f"{len(recalls)} recall(s)")


def run_recap(m: Memory, chatter, initial_prompt: str, digest: str,
             session: str | None) -> dict:
    """Core recap flow (unit 05): extract lessons → index each (dedup/merge) →
    audit. Returns the JSON-able summary dict.

    Memory never breaks the run: an extraction failure ⇒ ``error`` (no nodes,
    audit); a per-lesson index/merge failure ⇒ skip that lesson and continue;
    ``void`` ⇒ no nodes, audit only. This owns NONE of the logic — extraction is
    semantic.extract_lessons, dedup/merge is the LessonPolicy, status is the
    status module. It only sequences them and writes the audit."""
    policy = LessonPolicy(m.embedder, chatter)
    m.register_policy("lesson", policy)
    warnings: list[str] = []

    # 1. EXTRACT — one chat call for the whole session
    try:
        res = extract_lessons(chatter, initial_prompt, digest)
    except Exception as e:  # technical failure ⇒ error, write nothing
        audit_log({"event": "write", "type": "lesson", "outcome": "error",
                   "status": "error", "session": session, "error": str(e)})
        return {"session_status": "error", "lessons": [],
                "warnings": [f"extract: {e}"]}

    session_status = res.get("status", "partial")
    lessons = res.get("lessons", []) or []

    # void (or nothing emitted) ⇒ write nothing, audit void
    if session_status == "void" or not lessons:
        audit_log({"event": "write", "type": "lesson", "outcome": "void",
                   "status": session_status, "session": session})
        return {"session_status": session_status, "lessons": [], "warnings": warnings}

    initial = status.initial_lesson_status(session_status)
    results = []
    for l in lessons:
        when = (l.get("when") or "").strip()
        then_items = l.get("then") or []  # extract_lessons already coerced this to list[str]
        if not when or not then_items:
            continue
        body = render_body(when, then_items)
        meta = _stamp({
            "when": when, "then": then_items,
            "status": initial,
            "confirmed_by": [session] if session else [],
            "learned_days": [time.strftime("%Y-%m-%d")],
            "merge_count": 0,
        })
        try:
            nid = m.index({"type": "lesson", "body": body, "meta": meta})
            outcome = getattr(m, "last_outcome", "new")
            stored = m.get_node(nid) or {}
            final_status = stored.get("meta", {}).get("status", initial)
            results.append({"id": nid, "status": final_status, "outcome": outcome,
                            "when": when})
            audit_log({"event": "write", "type": "lesson", "id": nid,
                       "outcome": outcome, "status": final_status, "session": session})
            if outcome in ("merged:fast", "merged:llm") and policy.last_merge:
                d = policy.last_merge
                audit_log({"event": "merge", "id": nid, "mode": d.get("mode"),
                           "same_trigger": d.get("same_trigger"),
                           "dropped": d.get("dropped", []),
                           "provenance_count": d.get("provenance_count", 0),
                           "session": session})
        except Exception as e:  # one bad lesson doesn't lose the others
            warnings.append(f"lesson '{when[:40]}': {e}")
            audit_log({"event": "write", "type": "lesson", "outcome": "skip",
                       "status": initial, "session": session,
                       "error": str(e), "when": when[:80]})

    return {"session_status": session_status, "lessons": results, "warnings": warnings}


def cmd_recap(m, args):
    """END (write): extract lessons from the session and index each (dedup/merge).
    Reads the session digest as JSON from stdin (or --digest):
    {prompts:[...], errors:[...]}.

    With --spool-file: unlink it on ANY exit path (the extension writes the
    spool before spawning this; completion ⇒ deletion is the crash-recovery
    contract — a lingering file would be retried every session forever)."""
    digest = args.digest if args.digest is not None else (
        sys.stdin.read() if not sys.stdin.isatty() else "{}")
    initial_prompt = args.initial_prompt or "(none)"
    try:
        try:
            chatter = chatter_from_args(args)
        except Exception as e:  # bad provider/key — audit it, don't crash silently
            audit_log({"event": "write", "type": "lesson", "outcome": "error",
                       "status": "error", "session": SESSION, "error": str(e)})
            out = {"session_status": "error", "lessons": [],
                   "warnings": [f"chatter: {e}"]}
        else:
            out = run_recap(m, chatter, initial_prompt, digest, SESSION)
    finally:
        if getattr(args, "spool_file", None):
            try:
                os.unlink(args.spool_file)
            except OSError:
                pass
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        n = len(out["lessons"])
        print(f"recap: {n} lesson(s)  status={out['session_status']}"
              + (f"  warnings={out['warnings']}" if out["warnings"] else ""))


def _audit_detail(d: dict) -> str:
    e = d.get("event")
    if e == "recall":
        return (f"{d.get('phase')} injected={d.get('injected')} "
                f"hits={len(d.get('hits', []))} chars={d.get('chars')}")
    if e == "write":
        return (f"type={d.get('type')} id={(d.get('id') or '')[:8]} "
                f"outcome={d.get('outcome')} status={d.get('status')}")
    if e == "merge":
        detail = (f"id={(d.get('id') or '')[:8]} mode={d.get('mode')} "
                  f"same={d.get('same_trigger')} prov={d.get('provenance_count')}")
        if d.get("confirmed_by_count") is not None:
            detail += f" confirmed={d.get('confirmed_by_count')}"
        if d.get("learned_days_count") is not None:
            detail += f" days={d.get('learned_days_count')}"
        return detail
    if e == "dedup":
        return (f"{(d.get('merged') or '')[:8]} into {(d.get('into') or '')[:8]} "
                f"mode={d.get('mode')} cos={d.get('cos')}")
    if e == "lifecycle":
        return f"state={d.get('state')} {d.get('reason', '')}".rstrip()
    return json.dumps({k: v for k, v in d.items()
                       if k not in ("ts", "event", "session", "project")}, default=str)


def cmd_dedup(m, args):
    """Maintenance: re-run dedup/merge over EXISTING lesson nodes.

    Repairs fragmentation left by older thresholds (e.g. the exact-text-edit
    family that 0.92/0.82 let accumulate). Dry-run by default — reports
    candidate pairs (cosine ≥ --threshold, scoped per-node project like
    write-time dedup). --apply merges each source onto its best candidate via
    the LessonPolicy (fast path, else the LLM arbiter when a chatter key is
    available) and DELETES the losing node; arbiter refusals (not-a-dup) and
    chatter-less arbiter cases are skipped, never force-merged. --apply re-scans
    in ROUNDS (a merge can free another node's best candidate — the cascade
    case: A~B merges and deletes B, so C~B must re-find C~A)."""
    rows = m.conn.execute(
        "SELECT id, project FROM nodes WHERE type='lesson' ORDER BY created").fetchall()
    threshold = args.threshold if args.threshold is not None else _lesson_threshold()

    def scan_pairs():
        pairs, seen = [], set()
        for r in m.conn.execute(
                "SELECT id, project FROM nodes WHERE type='lesson' ORDER BY created").fetchall():
            node = m.get_node(r["id"])
            when = (node or {}).get("meta", {}).get("when")
            if not when:
                continue
            vec = m.embedder.embed(redact(when), purpose="dedup")
            hits = m.nearest(vec, type="lesson", project=r["project"] or None,
                             k=3, threshold=threshold)
            cand = next(((nid, s) for nid, s in hits if nid != node["id"]), None)
            if cand:
                key = tuple(sorted((node["id"], cand[0])))  # A~B == B~A — once
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((node["id"], cand[0], round(cand[1], 3)))
        return pairs

    pairs = scan_pairs()
    if not args.apply:
        for src, dst, s in pairs:
            print(f"{src[:8]} ~ {dst[:8]}  cos={s}")
        print(f"dedup: {len(pairs)} candidate pair(s) [dry-run — pass --apply to merge]")
        if args.json:
            print(json.dumps({"pairs": pairs, "applied": False}))
        return
    try:
        chatter = chatter_from_args(args)
    except Exception:
        chatter = None  # fast-path merges still work; arbiter cases are skipped
    policy = LessonPolicy(m.embedder, chatter)
    m.register_policy("lesson", policy)
    merged = skipped = 0
    rounds = 0
    while pairs and rounds < 5:
        rounds += 1
        for src, dst, s in pairs:
            src_node, dst_node = m.get_node(src), m.get_node(dst)
            if src_node is None or dst_node is None:
                skipped += 1  # consumed by an earlier merge this run
                continue
            try:
                outcome = policy.merge(m, dst, src_node)
                ov = getattr(outcome, "value", outcome)
            except Exception as e:
                print(f"dedup: skip {src[:8]}~{dst[:8]}: {e}", file=sys.stderr)
                skipped += 1
                continue
            if ov in ("merged:fast", "merged:llm"):
                m.delete_node(src)
                merged += 1
                audit_log({"event": "dedup", "merged": src, "into": dst,
                           "mode": ov, "cos": s, "session": SESSION})
            else:
                skipped += 1  # arbiter says different trigger — keep both
        pairs = scan_pairs()  # cascade: deleted nodes free new candidates
    remaining = m.count(type="lesson")
    print(f"dedup: {merged} merged, {skipped} skipped ({rounds} round(s)) "
          f"→ {remaining} lesson(s) remain")
    if args.json:
        print(json.dumps({"applied": True, "merged": merged,
                          "skipped": skipped, "rounds": rounds}))


def _lesson_threshold() -> float:
    import lesson
    return lesson.LESSON_DEDUP_THRESHOLD


def cmd_audit(m, args):
    """Read the audit log (memory USE: recalls, writes, lifecycle).
    Does not need the DB or an embedder."""
    p = args.path or os.environ.get("SPECLOOP_AUDIT") or os.path.expanduser("~/.specloop/audit.jsonl")
    rows = audit_read(p, event=args.event, session=args.session, since=args.since, tail=args.tail)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return
    for d in rows:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(d.get("ts", 0)))
        sess = (d.get("session") or "-")[:8]
        print(f"{ts} {sess:<8} {d.get('event', '?'):<10} {_audit_detail(d)}")


def _parse_since(s):
    """'7d' / '12h' / epoch-secs → epoch cutoff (float)."""
    s = str(s).strip().lower()
    if s.endswith("d"):
        mult, n = 86400.0, s[:-1]
    elif s.endswith("h"):
        mult, n = 3600.0, s[:-1]
    else:
        mult, n = None, s
    try:
        val = float(n)
    except ValueError:
        raise SystemExit(f"--since: bad value {s!r} (use '7d', '12h', or epoch seconds)")
    return time.time() - val * mult if mult else val


def _usage_default() -> str:
    v = os.environ.get("SPECLOOP_USAGE")
    if v and v.strip().lower() not in ("0", "off", "false", "no"):
        return v
    return os.path.expanduser("~/.specloop/usage.jsonl")


def cmd_tokens(m, args):
    """API token-usage rollups: per-day totals (default) or per-learning-saved
    (--by-lesson). Reads the usage log; --by-lesson also reads the audit log to
    count lessons saved per session. No DB / embedder needed."""
    up = args.path or _usage_default()
    since = _parse_since(args.since) if args.since else None
    rows = usage_read(up, since=since, tail=args.tail)
    if args.by_lesson:
        _print_tokens_by_lesson(rows, args)
    else:
        _print_tokens_by_day(rows, args)


def _print_tokens_by_day(rows, args):
    days = rollup_by_day(rows)
    if args.json:
        print(json.dumps(days, indent=2))
        return
    if not days:
        print("(no usage recorded)")
        return
    print(f"{'day':<12} {'chat':>9} {'embed':>9} {'total':>9} {'calls':>6}")
    tc = te = cc = 0
    for d in days:
        tot = d["chat"] + d["embed"]
        print(f"{d['day']:<12} {d['chat']:>9} {d['embed']:>9} {tot:>9} {d['calls']:>6}")
        tc += d["chat"]; te += d["embed"]; cc += d["calls"]
    print(f"{'TOTAL':<12} {tc:>9} {te:>9} {tc + te:>9} {cc:>6}")


def _print_tokens_by_lesson(rows, args):
    sess = rollup_by_session(rows)
    # lesson counts per session come from the audit log's write events (the
    # outcomes that produced or refined a node). Joined on the shared session id.
    ap = (args.audit_path or os.environ.get("SPECLOOP_AUDIT")
          or os.path.expanduser("~/.specloop/audit.jsonl"))
    saved = {"new", "not-a-dup", "merged:fast", "merged:llm"}
    counts: dict[str, int] = {}
    if os.path.exists(ap):
        for w in audit_read(ap, event="write"):
            if w.get("outcome") in saved:
                s = w.get("session") or "(none)"
                counts[s] = counts.get(s, 0) + 1
    out = []
    for s in sess:
        n = counts.get(s["session"], 0)
        total = s["extract"] + s["write"]
        out.append({"session": s["session"], "lessons": n,
                    "extract": s["extract"], "write": s["write"], "total": total,
                    "per_lesson": round(total / n, 1) if n else None})
    if args.json:
        print(json.dumps(out, indent=2))
        return
    if not out:
        print("(no write-side usage recorded)")
        return
    print(f"{'session':<14} {'lessons':>7} {'extract':>8} {'write':>8} "
          f"{'total':>8} {'per_lesson':>10}")
    for o in out:
        pl = f"{o['per_lesson']}" if o["per_lesson"] is not None else "-"
        print(f"{o['session'][:14]:<14} {o['lessons']:>7} {o['extract']:>8} "
              f"{o['write']:>8} {o['total']:>8} {pl:>10}")


def main():
    ap = argparse.ArgumentParser(prog="mem", description="specloop memory CLI")
    ap.add_argument("--db", help="sqlite path (default $SPECLOOP_DB or ~/.specloop/memory.db)")
    ap.add_argument("--embedder", help="hash|mistral|zai|openai (default $SPECLOOP_PROVIDER or mistral)")
    ap.add_argument("--project", help="project scope key (default: git toplevel basename)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("recall", help="top-k similar nodes")
    p.add_argument("query")
    p.add_argument("-k", "--k", type=int, default=5)
    p.add_argument("--scope", choices=["global", "local"], default=_default_scope())
    p.add_argument("--type")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_recall)

    p = sub.add_parser("remember", help="index a node manually (default type=prompt)")
    p.add_argument("body")
    p.add_argument("--type", default="prompt")
    p.add_argument("--categories")
    p.add_argument("--meta")
    p.add_argument("--root")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_remember)

    p = sub.add_parser("stats", help="node counts by type")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("export", help="dump the live DB to bench corpus format")
    p.add_argument("out_dir")
    p.add_argument("--scaffold-queries", action="store_true",
                   help="also emit self-match queries (plumbing check; replace for real labels)")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("start", help="START (read): recall similar past recaps for a prompt")
    p.add_argument("prompt")
    p.add_argument("-k", "--k", type=int, default=5)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("recap", help="END (write): extract lessons from a session and index each")
    p.add_argument("--initial-prompt", required=True,
                   help="the session's first user prompt")
    p.add_argument("--digest", help="session digest JSON (default: stdin)")
    p.add_argument("--spool-file", dest="spool_file", default=None,
                   help="crash-recovery spool: unlink when the recap completes")
    p.add_argument("--chat-provider", default=None)
    p.add_argument("--chat-model", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_recap)

    p = sub.add_parser("dedup", help="maintenance: re-run dedup/merge over existing lessons")
    p.add_argument("--threshold", type=float, default=None,
                   help="candidate cosine (default: the live LESSON_DEDUP_THRESHOLD)")
    p.add_argument("--apply", action="store_true",
                   help="actually merge + delete losers (default: dry-run report)")
    p.add_argument("--chat-provider", default=None,
                   help="arbiter chatter for non-fast-path merges (default: env)")
    p.add_argument("--chat-model", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_dedup)

    p = sub.add_parser("audit", help="read the memory audit log (recalls/writes/lifecycle)")
    p.add_argument("--event", help="filter: recall|write|lifecycle")
    p.add_argument("--session", help="filter by pi session id")
    p.add_argument("--since", type=float, help="epoch seconds")
    p.add_argument("--tail", type=int, help="last N lines")
    p.add_argument("--path", help="audit log path (default $SPECLOOP_AUDIT)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser("tokens", help="API token-usage rollups (per-day / per-learning-saved)")
    p.add_argument("--by-lesson", action="store_true",
                   help="per-session write-side cost (reads the audit log for lesson counts)")
    p.add_argument("--since", help="only since: '7d', '12h', or epoch seconds")
    p.add_argument("--tail", type=int, help="only the last N usage lines")
    p.add_argument("--path", help="usage log path (default $SPECLOOP_USAGE or ~/.specloop/usage.jsonl)")
    p.add_argument("--audit-path", help="audit log path for --by-lesson lesson counts")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_tokens)

    args = ap.parse_args()
    if args.cmd in ("audit", "tokens"):  # no DB / embedder needed
        args.fn(None, args)
        return
    try:
        m = open_memory(args)
    except RuntimeError as e:
        print(f"mem: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        args.fn(m, args)
    finally:
        m.close()


if __name__ == "__main__":
    main()

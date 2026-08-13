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
from semantic import CHATTERS, make_chatter, summarize_session  # noqa: E402
from audit import log as audit_log, read as audit_read  # noqa: E402


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


def _log_write(ntype: str, nid: str, root: str | None = None,
                merged: bool = False, meta: dict | None = None) -> None:
    audit_log({"event": "write", "type": ntype, "id": nid, "root": root,
              "merged": merged,
              "meta": {k: v for k, v in (meta or {}).items() if k in _AUDIT_META_KEYS}})


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
    nid = m.index({"type": args.type, "body": body, "meta": meta, "root_prompt_id": args.root})
    merged = m.count() == before
    _log_write(args.type, nid, root=args.root, merged=merged, meta=meta)
    print(json.dumps({"id": nid, "merged": merged}) if args.json
          else f"{nid}{'  (merged — dedup)' if merged else ''}")


def cmd_history(m, args):
    emit(m.history(args.root_id), args)


def cmd_link(m, args):
    m.link(args.child_id, args.root_id)
    print("ok")


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


def _digest_to_text(initial_prompt: str, digest_json: str) -> str:
    """Offline fallback: render a terse recap body from the digest (no model)."""
    try:
        d = json.loads(digest_json) if digest_json else {}
    except json.JSONDecodeError:
        d = {}
    prompts = d.get("prompts") or []
    errors = d.get("errors") or []
    parts = [initial_prompt]
    if prompts:
        parts.append("prompts: " + " | ".join(str(p) for p in prompts))
    if errors:
        parts.append("errors: " + " | ".join(str(e) for e in errors))
    return " ".join(parts)[:1000]


def cmd_recap(m, args):
    """END (write): summarize the session into one recap node. Reads the session
    digest as JSON from stdin (or --digest): {prompts:[...], errors:[...]}.
    The summarizer folds subject-drift into the prose (no separate field).
    --no-summary skips the model and indexes a body rendered from the digest."""
    digest = args.digest if args.digest is not None else (
        sys.stdin.read() if not sys.stdin.isatty() else "{}")
    initial_prompt = args.initial_prompt or "(none)"
    status = "partial"
    summary = ""
    warnings = []
    if args.no_summary:
        body = _digest_to_text(initial_prompt, digest)
    else:
        try:
            res = summarize_session(chatter_from_args(args), initial_prompt, digest)
            summary = (res.get("summary") or "").strip()
            status = res.get("status", "partial")
            body = summary or status
        except Exception as e:  # technical failure — flag, don't conflate with semantic partial
            status = "error"
            warnings.append(f"summary: {e}")
            body = initial_prompt
    meta = _stamp({"status": status, "summary": summary, "initial_prompt": initial_prompt})

    # void = nothing worth remembering: don't pollute the graph. Audit only.
    if status == "void":
        _log_write("recap", None, root=None, merged=False, meta=meta)
        print(json.dumps({"recap_id": None, "status": "void", "merged": False,
                          "warnings": warnings}, indent=2, default=str) if args.json
              else "recap=void (not stored)")
        return

    before = m.count()
    recap_id = m.index({"type": "recap", "body": body, "meta": meta})
    merged = m.count() == before
    _log_write("recap", recap_id, root=recap_id, merged=merged, meta=meta)
    out = {"recap_id": recap_id, "status": status, "merged": merged, "warnings": warnings}
    print(json.dumps(out, indent=2, default=str) if args.json
          else f"recap={recap_id}  status={status}"
               + (f"  warnings={warnings}" if warnings else ""))


def _audit_detail(d: dict) -> str:
    e = d.get("event")
    if e == "recall":
        return (f"{d.get('phase')} injected={d.get('injected')} "
                f"hits={len(d.get('hits', []))} chars={d.get('chars')}")
    if e == "write":
        return f"type={d.get('type')} id={(d.get('id') or '')[:8]} merged={d.get('merged')}"
    if e == "lifecycle":
        return f"state={d.get('state')} {d.get('reason', '')}".rstrip()
    return json.dumps({k: v for k, v in d.items()
                       if k not in ("ts", "event", "session", "project")}, default=str)


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

    p = sub.add_parser("history", help="a node + everything linked to it")
    p.add_argument("root_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_history)

    p = sub.add_parser("link", help="attach provenance: child -> root")
    p.add_argument("child_id")
    p.add_argument("root_id")
    p.set_defaults(fn=cmd_link)

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

    p = sub.add_parser("recap", help="END (write): summarize a session into one recap node")
    p.add_argument("--initial-prompt", required=True,
                   help="the session's first user prompt (subject anchor)")
    p.add_argument("--digest", help="session digest JSON (default: stdin)")
    p.add_argument("--chat-provider", default=None)
    p.add_argument("--chat-model", default=None)
    p.add_argument("--no-summary", action="store_true",
                   help="skip the model call (index a recap node from --digest text only)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_recap)

    p = sub.add_parser("audit", help="read the memory audit log (recalls/writes/lifecycle)")
    p.add_argument("--event", help="filter: recall|write|lifecycle")
    p.add_argument("--session", help="filter by pi session id")
    p.add_argument("--since", type=float, help="epoch seconds")
    p.add_argument("--tail", type=int, help="last N lines")
    p.add_argument("--path", help="audit log path (default $SPECLOOP_AUDIT)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_audit)

    args = ap.parse_args()
    if args.cmd == "audit":  # no DB / embedder needed
        cmd_audit(None, args)
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

#!/usr/bin/env python3
"""specloop API token-usage log — append-only JSONL of every real model call.

The companion to :mod:`audit`: ``audit`` logs memory *use* (recalls/writes);
this logs API *cost* (chat + embedding tokens). One line per ACTUAL API call —
cache hits cost nothing and are not logged. Rolled up by ``mem tokens`` into
per-day totals and per-learning-saved cost.

Only two places hit the network, and both call :func:`log` with the ``usage``
block the OpenAI-compatible API already returns:

- :meth:`semantic.Chatter.complete`  → ``kind="chat"``  (extract / merge)
- :meth:`engine.EmbedderAPI._call`   → ``kind="embed"`` (recall / index / dedup / merge)

Every line is stamped with ``ts``, ``session`` (``SPECLOOP_SESSION``) and
``project`` so usage can be joined to pi sessions and to the audit log's
``write`` events (the per-learning-saved rollup counts lessons per session).
Disable with ``SPECLOOP_USAGE=0`` (or off/false/no).

Stdlib only (runs on a bare Pi, like the rest of the engine).
"""
from __future__ import annotations

import json
import os
import time

_OFF = {"0", "off", "false", "no"}

# Purposes attributed to the WRITE side (producing/refining lessons). Used by the
# per-learning-saved rollup; ``recall`` is read-side and excluded from per-lesson
# cost (it is still counted in the per-day total).
WRITE_PURPOSES = {"extract", "merge", "index", "dedup"}


def path() -> str | None:
    """Resolve the usage-log path, or None if disabled."""
    v = os.environ.get("SPECLOOP_USAGE")
    if v is not None and v.strip().lower() in _OFF:
        return None
    return v or os.path.expanduser("~/.specloop/usage.jsonl")


def log(entry: dict) -> None:
    """Append one usage line. No-op when disabled or when the path is unset."""
    p = path()
    if p is None:
        return
    line = dict(entry)
    line.setdefault("ts", time.time())
    line.setdefault("session", os.environ.get("SPECLOOP_SESSION"))
    line.setdefault("project", os.environ.get("SPECLOOP_PROJECT"))
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, default=str) + "\n")


def read(p: str, *, kind: str | None = None, purpose: str | None = None,
         session: str | None = None, since: float | None = None,
         until: float | None = None, tail: int | None = None) -> list[dict]:
    """Read + filter the usage log. Tolerant of malformed lines."""
    out: list[dict] = []
    if not p or not os.path.exists(p):
        return out
    with open(p, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if kind and d.get("kind") != kind:
                continue
            if purpose and d.get("purpose") != purpose:
                continue
            if session and d.get("session") != session:
                continue
            if since and d.get("ts", 0) < since:
                continue
            if until and d.get("ts", 0) > until:
                continue
            out.append(d)
    if tail:
        out = out[-tail:]
    return out


def day_key(ts: float) -> str:
    """Local calendar day as ``YYYY-MM-DD``."""
    return time.strftime("%Y-%m-%d", time.localtime(ts or 0))


def rollup_by_day(rows: list[dict]) -> list[dict]:
    """Per-calendar-day token totals, split chat vs embed. Pure — pass read() rows."""
    days: dict[str, dict] = {}
    for r in rows:
        d = day_key(r.get("ts", 0))
        agg = days.setdefault(d, {"day": d, "chat": 0, "embed": 0, "calls": 0})
        tok = r.get("total_tokens", 0) or 0
        if r.get("kind") == "chat":
            agg["chat"] += tok
        elif r.get("kind") == "embed":
            agg["embed"] += tok
        agg["calls"] += 1
    return sorted(days.values(), key=lambda x: x["day"])


def rollup_by_session(rows: list[dict]) -> list[dict]:
    """Per-session WRITE-side tokens: ``extract`` (the session-level chat call)
    vs ``write`` (merge chat + index/dedup embeds). Recall is excluded — it is
    read-side cost, shown in the per-day total instead. Pure."""
    sess: dict[str, dict] = {}
    for r in rows:
        if r.get("purpose") not in WRITE_PURPOSES:
            continue
        s = r.get("session") or "(none)"
        agg = sess.setdefault(s, {"session": s, "extract": 0, "write": 0, "calls": 0})
        if r.get("purpose") == "extract":
            agg["extract"] += r.get("total_tokens", 0) or 0
        else:
            agg["write"] += r.get("total_tokens", 0) or 0
        agg["calls"] += 1
    return sorted(sess.values(), key=lambda x: x["session"])

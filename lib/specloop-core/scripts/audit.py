#!/usr/bin/env python3
"""specloop audit log — append-only JSONL of memory *use*.

Two writers append to the same file (both small lines, O_APPEND → atomic on
Linux), so "use" is replayable independently of the memory DB ("state"):

  - the pi extension (TS)  → ``recall`` + ``lifecycle`` events
  - this module (mem.py)   → ``write`` events

Every line is stamped with ``ts``, ``session`` (``SPECLOOP_SESSION``) and
``project`` so memory nodes ↔ pi sessions can be joined. Disable with
``SPECLOOP_AUDIT=0`` (or ``off``/``false``/``no``).
"""
from __future__ import annotations

import json
import os
import time

_OFF = {"0", "off", "false", "no"}


def path() -> str | None:
    """Resolve the audit log path, or None if disabled."""
    v = os.environ.get("SPECLOOP_AUDIT")
    if v is not None and v.strip().lower() in _OFF:
        return None
    return v or os.path.expanduser("~/.specloop/audit.jsonl")


def log(event: dict) -> None:
    """Append one audit line. No-op when disabled or when the path is unset."""
    p = path()
    if p is None:
        return
    line = dict(event)
    line.setdefault("ts", time.time())
    line.setdefault("session", os.environ.get("SPECLOOP_SESSION"))
    line.setdefault("project", os.environ.get("SPECLOOP_PROJECT"))
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, default=str) + "\n")


def read(p: str, *, event: str | None = None, session: str | None = None,
         since: float | None = None, tail: int | None = None) -> list[dict]:
    """Read + filter the audit log. Tolerant of malformed lines."""
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
            if event and d.get("event") != event:
                continue
            if session and d.get("session") != session:
                continue
            if since and d.get("ts", 0) < since:
                continue
            out.append(d)
    if tail:
        out = out[-tail:]
    return out

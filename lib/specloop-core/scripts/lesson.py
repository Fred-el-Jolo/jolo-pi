#!/usr/bin/env python3
"""specloop lesson dedup + merge policy (units 03 + 04).

The lesson-specific intelligence that the Store dispatches to. The Store (unit
01) is lesson-agnostic: it calls ``embedding_text`` / ``find_candidate`` /
``merge`` polymorphically. Everything lesson-specific lives here:

- **Dedup key** = the WHEN clause (``embedding_text`` returns ``meta.when``).
- **Candidate** = best existing lesson with ``cosine(when_vec, cand.when_vec) ≥
  LESSON_DEDUP_THRESHOLD`` (the Store's ``nearest`` does the scan).
- **Fast path** — THENs already near-identical (``THEN_IDENTICAL_THRESHOLD``):
  bump ``confirmed_by`` + ``merge_count``, trend status, no LLM.
- **Arbiter + reconcile** — ``merge_thens`` (LLM): ``same_trigger=False`` ⇒
  ``NOT_A_DUP`` (insert separately); else UPDATE the existing node in place with
  the merged THEN, unioned confirmations, and appended provenance.

Stable ids: a merge updates the *existing* node in place; ids don't churn across
merges. The WHEN/embedding are deliberately not refined in v1 (see unit 07).

Constants are env-overridable via the ``SPECLOOP_`` prefix where useful.
"""
from __future__ import annotations

import os
import time
from enum import Enum

from redact import redact
from semantic import merge_thens
import status


class MergeOutcome(Enum):
    """Result of :meth:`LessonPolicy.merge`. The ``.value`` is the stable outcome
    string the Store reads (``getattr(outcome, 'value')``) for audit + dispatch:
    ``NOT_A_DUP`` tells the Store to insert a fresh node instead of merging."""
    FAST_PATH = "merged:fast"
    MERGED = "merged:llm"
    NOT_A_DUP = "not-a-dup"


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    try:
        return float(v) if v is not None and v.strip() else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v is not None and v.strip() else default
    except ValueError:
        return default


# WHEN-vector cosine to flag a merge candidate. The arbiter makes this forgiving
# — a false candidate is rejected, so the value can be a little loose.
LESSON_DEDUP_THRESHOLD = _env_float("SPECLOOP_LESSON_DEDUP_THRESHOLD", 0.92)
# THEN-vector cosine for the fast path (confirm-count bump, no LLM).
THEN_IDENTICAL_THRESHOLD = _env_float("SPECLOOP_THEN_IDENTICAL_THRESHOLD", 0.95)
# hard cap items in a merged THEN (the merger is told this; enforced as a safety net).
MAX_THEN_ITEMS = _env_int("SPECLOOP_MAX_THEN_ITEMS", 6)


def _cosine(a, b):
    """Local cosine (mirrors engine.cosine) so this policy is unit-testable in
    isolation without importing the Store module. Same loud dim-mismatch guard."""
    if len(a) != len(b):
        raise ValueError(f"embedding dim mismatch: {len(a)} != {len(b)}")
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / (na * nb) ** 0.5 if na and nb else 0.0


def _union_sessions(*lists) -> list:
    """Union session-id lists, preserving order, deduping distinct ids."""
    out = []
    for lst in lists:
        for s in lst or []:
            if s not in out:
                out.append(s)
    return out


class LessonPolicy:
    """Per-lesson dedup + merge policy (registered for type ``"lesson"``)."""

    def __init__(self, embedder, chatter):
        self.embedder = embedder
        self.chatter = chatter
        # detail of the most recent merge(), read by the write path for audit:
        # {mode: fast|llm, same_trigger, dropped, provenance_count}; None if none.
        self.last_merge = None

    # -- protocol (called by the Store) ------------------------------------
    def embedding_text(self, node) -> str:
        """The MATCH KEY: the WHEN clause alone (key/payload separation)."""
        return node["meta"]["when"]

    def find_candidate(self, store, node, project):
        """Best existing lesson with a near-identical WHEN vector, or None.

        The WHEN vector is redacted+embedded here (the Store redacts the same
        text when it inserts); the API embedder caches it, HashEmbedder is cheap."""
        when = node["meta"]["when"]
        vec = self.embedder.embed(redact(when), purpose="dedup")
        hits = store.nearest(vec, type="lesson", project=project,
                             k=1, threshold=LESSON_DEDUP_THRESHOLD)
        return hits[0][0] if hits else None

    def merge(self, store, existing_id, new_node) -> MergeOutcome:
        """Reconcile ``new_node`` onto the existing lesson ``existing_id``.

        Fast path (THENs near-identical) → confirm-count bump, no LLM.
        Arbiter (``merge_thens``): ``same_trigger=False`` → ``NOT_A_DUP``;
        else reconcile the THENs in place. Sets :attr:`last_merge` for audit."""
        self.last_merge = None
        existing = store.get_node(existing_id)
        emeta = existing["meta"]
        cand_then = emeta.get("then", "")
        new_then = new_node["meta"].get("then", "")

        # 2. FAST PATH — re-learned the same lesson (THENs already agree)
        if self._thens_near_identical(cand_then, new_then):
            meta = self._fast_path(emeta, new_node)
            store.update_node(existing_id,
                              body=self._render(emeta["when"], emeta["then"]), meta=meta)
            self.last_merge = {
                "mode": "fast", "same_trigger": None, "dropped": [],
                "provenance_count": len(emeta.get("provenance", []) or []),
            }
            return MergeOutcome.FAST_PATH

        # 3. ARBITER — are these truly the same trigger situation?
        res = merge_thens(self.chatter, emeta["when"],
                          self._then_input(existing, cand_then),
                          self._then_input(new_node, new_then))
        if not res.get("same_trigger"):
            # different trigger ⇒ NOT a dup; Store inserts the new lesson separately
            return MergeOutcome.NOT_A_DUP

        # 4. RECONCILE — same trigger, THENs differ → update existing in place
        meta, dropped = self._reconcile(emeta, new_node, res)
        store.update_node(existing_id,
                          body=self._render(emeta["when"], res["then"]), meta=meta)
        self.last_merge = {
            "mode": "llm", "same_trigger": True, "dropped": dropped,
            "provenance_count": len(meta.get("provenance", []) or []),
        }
        return MergeOutcome.MERGED

    # -- helpers -----------------------------------------------------------
    def _thens_near_identical(self, a: str, b: str) -> bool:
        va = self.embedder.embed(redact(a), purpose="merge")
        vb = self.embedder.embed(redact(b), purpose="merge")
        return _cosine(va, vb) >= THEN_IDENTICAL_THRESHOLD

    @staticmethod
    def _render(when: str, then: str) -> str:
        return f"WHEN {when} THEN {then}"

    @staticmethod
    def _then_input(node_or_existing, then_text) -> dict:
        meta = node_or_existing["meta"]
        return {
            "then": then_text,
            "status": meta.get("status"),
            "confirmed_by": meta.get("confirmed_by", []) or [],
            "date": node_or_existing.get("created", time.time()),
        }

    def _fast_path(self, emeta: dict, new_node: dict) -> dict:
        """THENs agree ⇒ keep the existing THEN, accumulate confirmation, promote."""
        meta = dict(emeta)
        confirmed_by = _union_sessions(emeta.get("confirmed_by", []),
                                       new_node["meta"].get("confirmed_by", []))
        meta["confirmed_by"] = confirmed_by
        meta["merge_count"] = emeta.get("merge_count", 0) + 1
        meta["status"] = status.promote(emeta.get("status", "tentative"), len(confirmed_by))
        # then unchanged (near-identical); body + embedding unchanged by the Store
        return meta

    def _reconcile(self, emeta: dict, new_node: dict, res: dict):
        """Same trigger, THENs differ ⇒ merged THEN + lossless provenance."""
        meta = dict(emeta)
        then = res["then"]
        # safety-net cap: the merger is told MAX_THEN_ITEMS, but trust-but-verify
        dropped = list(res.get("dropped", []) or [])
        meta["then"] = then
        meta["status"] = res.get("status") or status.merged_status(
            [emeta.get("status"), new_node["meta"].get("status")])
        meta["confirmed_by"] = _union_sessions(emeta.get("confirmed_by", []),
                                               new_node["meta"].get("confirmed_by", []))
        meta["merge_count"] = emeta.get("merge_count", 0) + 1
        provenance = list(emeta.get("provenance", []) or [])
        provenance.append({
            "then": new_node["meta"].get("then"),
            "status": new_node["meta"].get("status"),
            "session": new_node["meta"].get("session"),
            "date": new_node.get("created", time.time()),
        })
        meta["provenance"] = provenance
        return meta, dropped

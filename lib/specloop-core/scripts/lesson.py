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

THEN is a ``list[str]`` of atomic items, not one prose blob — that's what makes
MAX_THEN_ITEMS (semantic.py) an actual enforceable cap instead of a prompt hint.

Stable ids: a merge updates the *existing* node in place; ids don't churn across
merges. The WHEN/embedding are deliberately not refined in v1 (see unit 07).

Constants are env-overridable via the ``SPECLOOP_`` prefix where useful.
"""
from __future__ import annotations

import time
from enum import Enum

from engine import cosine
from redact import redact
from semantic import coerce_then, env_float, merge_thens
import status


class MergeOutcome(Enum):
    """Result of :meth:`LessonPolicy.merge`. The ``.value`` is the stable outcome
    string the Store reads (``getattr(outcome, 'value')``) for audit + dispatch:
    ``NOT_A_DUP`` tells the Store to insert a fresh node instead of merging."""
    FAST_PATH = "merged:fast"
    MERGED = "merged:llm"
    NOT_A_DUP = "not-a-dup"


# WHEN-vector cosine to flag a merge candidate. The arbiter makes this forgiving
# — a false candidate is rejected, so the value can be a little loose.
LESSON_DEDUP_THRESHOLD = env_float("SPECLOOP_LESSON_DEDUP_THRESHOLD", 0.92)
# THEN-vector cosine for the fast path (confirm-count bump, no LLM).
THEN_IDENTICAL_THRESHOLD = env_float("SPECLOOP_THEN_IDENTICAL_THRESHOLD", 0.95)


def _union_sessions(*lists) -> list:
    """Union session-id lists, preserving order, deduping distinct ids."""
    out = []
    for lst in lists:
        for s in lst or []:
            if s not in out:
                out.append(s)
    return out


def _then_text(items: list[str]) -> str:
    """Join THEN items into one string — cosine needs a single vector per side,
    so the fast-path comparison and the stored body both go through this."""
    return "; ".join(items)


def render_body(when: str, then_items: list[str]) -> str:
    """The stored body's canonical WHEN/THEN text. Public (not LessonPolicy-
    private) because mem.py needs the identical format for a lesson's first
    insert — one render function, so the two call sites can't drift apart."""
    return f"WHEN {when} THEN {_then_text(then_items)}"


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
        emeta = dict(existing["meta"])
        # legacy-data guard: a node written before THEN became list[str] still
        # has a bare string here. coerce_then wraps it to a 1-item list so every
        # read below (fast-path join, reconcile, provenance, render) sees a real
        # list instead of _then_text silently iterating it character by character.
        emeta["then"] = coerce_then(emeta.get("then"))
        cand_then = emeta["then"]                      # already redacted (stored via the Store)
        # new_node hasn't touched the Store yet (merge() runs before any insert/update),
        # so its THEN is raw — redact now, before it reaches the embedder or the arbiter LLM.
        new_then = [redact(t) for t in coerce_then(new_node["meta"].get("then"))]

        # 1. FAST PATH — re-learned the same lesson (THENs already agree)
        if self._thens_near_identical(cand_then, new_then):
            meta = self._fast_path(emeta, new_node)
            store.update_node(existing_id,
                              body=render_body(emeta["when"], emeta["then"]), meta=meta)
            self.last_merge = {
                "mode": "fast", "same_trigger": None, "dropped": [],
                "provenance_count": len(emeta.get("provenance", []) or []),
            }
            return MergeOutcome.FAST_PATH

        # 2. ARBITER — are these truly the same trigger situation?
        res = merge_thens(self.chatter, emeta["when"],
                          self._then_input(existing, cand_then),
                          self._then_input(new_node, new_then))
        if not res.get("same_trigger"):
            # different trigger ⇒ NOT a dup; Store inserts the new lesson separately
            return MergeOutcome.NOT_A_DUP

        # 3. RECONCILE — same trigger, THENs differ → update existing in place
        meta, dropped = self._reconcile(emeta, new_node, res, new_then)
        store.update_node(existing_id,
                          body=render_body(emeta["when"], res["then"]), meta=meta)
        self.last_merge = {
            "mode": "llm", "same_trigger": True, "dropped": dropped,
            "provenance_count": len(meta.get("provenance", []) or []),
        }
        return MergeOutcome.MERGED

    # -- helpers -----------------------------------------------------------
    def _thens_near_identical(self, a: list[str], b: list[str]) -> bool:
        # callers pass already-redacted items (see merge()) — no re-redact here
        va = self.embedder.embed(_then_text(a), purpose="merge")
        vb = self.embedder.embed(_then_text(b), purpose="merge")
        return cosine(va, vb) >= THEN_IDENTICAL_THRESHOLD

    @staticmethod
    def _then_input(node_or_existing, then_items: list[str]) -> dict:
        meta = node_or_existing["meta"]
        return {
            "then": then_items,
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

    def _reconcile(self, emeta: dict, new_node: dict, res: dict, new_then: list[str]):
        """Same trigger, THENs differ ⇒ merged THEN + lossless provenance.

        ``new_then`` is the already-redacted THEN items (see merge()) — used here
        instead of ``new_node["meta"]["then"]`` because the raw value already went
        out to the arbiter LLM call before this method runs; redacting once, at
        the source, keeps every downstream use (embed, LLM call, provenance)
        consistent, on top of whatever Memory._redact_meta re-checks at persist
        time."""
        meta = dict(emeta)
        # res["then"] is already capped at MAX_THEN_ITEMS (semantic.merge_thens
        # enforces it, overflow items land in res["dropped"] — real enforcement,
        # not just a number in the prompt).
        then = res["then"]
        dropped = list(res.get("dropped", []) or [])
        meta["then"] = then
        meta["status"] = res.get("status") or status.merged_status(
            [emeta.get("status"), new_node["meta"].get("status")])
        meta["confirmed_by"] = _union_sessions(emeta.get("confirmed_by", []),
                                               new_node["meta"].get("confirmed_by", []))
        meta["merge_count"] = emeta.get("merge_count", 0) + 1
        provenance = list(emeta.get("provenance", []) or [])
        provenance.append({
            "then": new_then,
            "status": new_node["meta"].get("status"),
            "session": new_node["meta"].get("session"),
            "date": new_node.get("created", time.time()),
        })
        meta["provenance"] = provenance
        return meta, dropped

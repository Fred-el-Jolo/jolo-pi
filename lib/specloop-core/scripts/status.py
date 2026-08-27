#!/usr/bin/env python3
"""specloop status taxonomy + conflict-resolution authority (unit 04).

A *pure* module — no I/O, no imports of engine/semantic. It holds the canonical
status vocabulary so the three consumers (extractor 02, dedup+merge 03, write
path 05) cannot diverge on what "confirmed" means. The consumers apply these
rules; this module only states them.

Two layers:

- **Session-level** (emitted by the extractor, describes the session that
  produced the lessons): ``done | partial | failed | void``. ``error`` is
  engine-only — never emitted by the model; set by the write path when the
  extraction call fails (⇒ no nodes, audit only).
- **Lesson-level** (stored on the node, evolves via re-learning/merging):
  ``confirmed | tentative | contested``.

See spec ``units/04-status.md``.
"""
from __future__ import annotations

# Session-level verdicts (model output). `void` ⇒ no lessons emitted.
SESSION_STATUS = ("done", "partial", "failed", "void")

# Lesson-level statuses (stored on the node). `error` is deliberately absent —
# it is engine-only and never persisted on a node.
LESSON_STATUS = ("confirmed", "tentative", "contested")

# Higher rank = higher authority on a contradiction (confirmed > tentative > contested).
STATUS_RANK = {"confirmed": 3, "tentative": 2, "contested": 1}

# Distinct sessions that must re-learn a tentative lesson before it promotes.
CONFIRM_TO_CONFIRMED = 2
# …OR distinct calendar days the lesson was (re-)learned on — the escape hatch
# for heavily-RESUMED sessions: one pi session spanning several days re-learns
# under the same session id, so session-count alone never promotes (observed
# 2026-08-18→08-27: lessons merged 3× by one resumed session stayed prov=1).
# Re-learning on 3 separate days is independent-enough evidence to confirm.
CONFIRM_DAYS = 3


def initial_lesson_status(session_status: str) -> str:
    """Translate a session outcome into a new lesson's initial status.

    ALWAYS ``tentative``. Confirmation is evidence-based only: a lesson promotes
    to ``confirmed`` when ≥2 distinct sessions re-learn it (see :func:`promote`).
    The extractor's ``done`` verdict alone used to grant ``confirmed`` with a
    single provenance — but that verdict proved unstable (the same session
    re-recapped after a restart flipped it), so it no longer grants trust.
    Anything not in SESSION_STATUS also defaults to ``tentative``."""
    return "tentative"


def promote(status: str, confirmed_by_count: int, learned_days_count: int | None = None) -> str:
    """Trend a lesson's status as it gets re-confirmed.

    ``tentative`` ⇒ ``confirmed`` once EITHER evidence bar is met:
    ``confirmed_by_count >= CONFIRM_TO_CONFIRMED`` (2 distinct sessions) or
    ``learned_days_count >= CONFIRM_DAYS`` (3 distinct calendar days — see
    CONFIRM_DAYS above for why session-count alone is not enough).
    ``confirmed`` stays ``confirmed``; ``contested`` is untouched here (a merge
    left it contested — re-confirmation does not silently clear that)."""
    if status == "tentative" and (
        confirmed_by_count >= CONFIRM_TO_CONFIRMED
        or (learned_days_count or 0) >= CONFIRM_DAYS
    ):
        return "confirmed"
    return status


def merged_status(source_statuses: list[str]) -> str:
    """Pure merged-status rule for two-or-more contributing lessons.

    all ``confirmed`` ⇒ ``confirmed``; otherwise ``tentative``. ``contested`` is
    *not* produced here — it is set by the merger (``merge_thens``) when a
    contradiction could not be resolved. This function is the canonical statement
    of the non-contradiction cases (used as a reference + in tests)."""
    if source_statuses and all(s == "confirmed" for s in source_statuses):
        return "confirmed"
    return "tentative"


def authority_rank(status: str, confirmed_by_count: int, created: float) -> tuple:
    """Sortable authority key for conflict resolution during merge.

    Returns ``(rank, confirmed_by_count, created)`` — **larger tuple = higher
    authority**; use ``max(items, key=authority_rank)`` to pick the winner. On a
    contradiction the precedence is: status rank → confirm-count → recency
    (newer wins ⇒ larger ``created`` ranks higher). See spec 04 §Authority."""
    return (STATUS_RANK.get(status, 0), confirmed_by_count, created)

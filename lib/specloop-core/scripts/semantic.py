#!/usr/bin/env python3
"""specloop semantic layer — lesson extraction + THEN-merge (units 02, 03).

OpenAI-compatible ``/chat/completions`` (default: mistral ``mistral-small-latest``).
Deliberately separate from the embedding providers in :mod:`engine` but reusing
the same key env by default (``MISTRAL_API_KEY``), so embeddings + chat share one
dedicated model config.

This module owns the two LLM calls on the WRITE side:

- :func:`extract_lessons` — session → 0–5 ``{when, then}`` lessons + a session
  status (unit 02). It is the *only* producer of lesson content.
- :func:`merge_thens` — reconcile two THEN takeaways for the same trigger into
  one (unit 03). Used by the dedup+merge policy's LLM path.

The READ side (recall) never calls a model — it is pure cosine lookup in
:mod:`engine`. This module does NOT import :mod:`status` — it emits raw session
statuses per its prompt; the write path applies the session→lesson mapping.

All functions are pure apart from :meth:`Chatter.complete`, so prompt-building
and JSON parsing are unit-testable without network (see test_semantic.py).
"""
from __future__ import annotations

import json
import os
import re

from httputil import post_json
from usage import log as usage_log

# Add a row here to support a new chat provider; nothing else changes.
# Switching in code is a one-liner:  make_chatter("mistral")
CHATTERS = {
    "mistral": dict(
        name="mistral", key_env="MISTRAL_API_KEY",
        url="https://api.mistral.ai/v1/chat/completions", model="mistral-small-latest"),
    "openai": dict(
        name="openai", key_env="OPENAI_API_KEY",
        url="https://api.openai.com/v1/chat/completions", model="gpt-4o-mini"),
    "zai": dict(
        name="zai", key_env="ZAI_API_KEY",
        url="https://api.z.ai/api/paas/v4/chat/completions", model="glm-4-flash"),
}


class Chatter:
    """Remote chat via any OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(self, name, key_env, url, model, api_key=None):
        self.name = name
        self.key_env = key_env
        self.url = url
        self.model = model
        self.api_key = api_key or os.environ.get(key_env)
        if not self.api_key:
            raise RuntimeError(
                f"{key_env} not set (export it to use the '{name}' chatter)")

    def complete(self, system: str, user: str, *, json_mode: bool = True,
                 timeout: int = 40, purpose: str = "chat") -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        payload = post_json(self.url, {"Authorization": f"Bearer {self.api_key}"},
                            body, timeout=timeout)
        # log the token cost the API already reports (OpenAI-compatible `usage`)
        u = payload.get("usage") or {}
        usage_log({"kind": "chat", "provider": self.name, "model": self.model,
                   "purpose": purpose,
                   "prompt_tokens": u.get("prompt_tokens", 0) or 0,
                   "completion_tokens": u.get("completion_tokens", 0) or 0,
                   "total_tokens": u.get("total_tokens", 0) or 0})
        return payload["choices"][0]["message"]["content"]


def make_chatter(provider: str, **overrides):
    """Build a Chatter from the CHATTERS registry. One-liner switch."""
    p = dict(CHATTERS[provider])
    p.update(overrides)
    return Chatter(name=p["name"], key_env=p["key_env"], url=p["url"],
                   model=p["model"], api_key=p.get("api_key"))


# --------------------------------------------------------------- pure helpers
def parse_json(raw: str, default: dict) -> dict:
    """Best-effort JSON object parse. Models in json_mode are reliable; this
    still defends against markdown fences / trailing prose."""
    if not raw:
        return dict(default)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return dict(default)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]"


# --------------------------------------------------------------- write-outs
# Hard cap lessons per session (unit 02): a ceiling, not a target. The prompt
# biases toward curation (soft target 3) to suppress padding.
MAX_LESSONS = 5

_LESSON_SYSTEM = (
    "You extract durable, reusable lessons from a completed coding-agent session.\n"
    "Inputs: the session's INITIAL prompt, the later prompts, and the tool errors.\n"
    "Answer: what was LEARNT that is worth remembering for future similar "
    "situations? Return STRICT JSON only:\n"
    '{"status": "done"|"partial"|"failed"|"void", '
    '"lessons": [{"when": str, "then": str}]}.\n'
    "\n"
    "- status — done=goal accomplished; partial=partly done or drifted; "
    "failed=the work failed; void=nothing durably reusable was learnt.\n"
    "- lessons — 0 to 5 rules.\n"
    "  - when = the situation/trigger that should make future-you recall this. "
    "Be specific (the situation, not the fix).\n"
    "  - then = the takeaway — an action to take, a fact that holds, or a "
    "verdict reached.\n"
    "- Ground every rule in the session's actual work/errors. Do not invent "
    "plausible-sounding generalities. If a rule isn't evidenced by the "
    "transcript, don't emit it.\n"
    "- Fewer sharp rules beats more mediocre ones. Soft target 3, hard cap 5. "
    'If nothing is genuinely reusable, return {"status":"void","lessons":[]}.'
)


def extract_lessons(chatter: Chatter, initial_prompt: str, digest_json: str) -> dict:
    """Session → 0–5 lessons + a session status (unit 02).

    Returns ``{'status': str, 'lessons': [{'when': str, 'then': str}, ...]}``.
    ``status`` ∈ ``{done, partial, failed, void}``; ``void`` ⇒ ``lessons == []``.

    RAISES ``ValueError`` on an unparseable / contract-violating reply (the write
    path maps that to the engine-only ``error`` status and writes nothing). A
    well-formed ``{status, lessons:[]}`` is *not* an error — that is the model's
    own void/partial verdict. ``{error}`` is never returned by this function."""
    user = (f"Initial prompt:\n{initial_prompt}\n\n"
            f"Session digest (JSON):\n{truncate(digest_json, 6000)}")
    raw = chatter.complete(_LESSON_SYSTEM, user, purpose="extract")
    data = parse_json(raw, default={})  # {} signals "could not parse"
    if not isinstance(data, dict) or "status" not in data:
        raise ValueError(f"extract_lessons: unparseable model reply: {raw!r}")
    lessons = data.get("lessons") or []
    if not isinstance(lessons, list):
        raise ValueError(f"extract_lessons: 'lessons' is not a list: {raw!r}")
    # enforce the hard cap (the prompt asks for ≤5, but trust-but-verify)
    lessons = [l for l in lessons if isinstance(l, dict)][:MAX_LESSONS]
    return {"status": data.get("status"), "lessons": lessons}


_MERGE_SYSTEM = (
    "You reconcile two lessons that may describe the SAME trigger situation.\n"
    "Inputs: the shared WHEN, and two THEN takeaways — each with an authority "
    "(status) and an age. Return STRICT JSON:\n"
    '{"same_trigger": bool, "then": str, "status": str, '
    '"dropped": [{"item": str, "reason": str}]}.\n'
    "\n"
    "- same_trigger = false if the two THENs are actually about different "
    "situations — then this is not a merge; the caller keeps them separate and "
    "the other fields are ignored.\n"
    "- If same trigger, produce ONE merged then that:\n"
    "  1. unions all distinct actionable items from both sides (lossless),\n"
    "  2. removes near-duplicates,\n"
    "  3. resolves contradictions by authority — never keep both sides of a "
    "contradiction silently (authority ordering: status rank "
    "confirmed>tentative>contested, then confirm-count, then recency),\n"
    "  4. orders by required dependency first, then efficiency; treat ordered "
    "steps (causal) differently from unordered conditions (a set),\n"
    "  5. caps at 6 items, dropping only duplicates or the lowest-value item — "
    "each drop recorded in 'dropped' with a reason; never drop a unique item "
    "silently.\n"
    "- status: confirmed if all sources confirmed; tentative if mixed but "
    "uncontradicted; contested if a contradiction could not be resolved."
)


def merge_thens(chatter: Chatter, when: str, a: dict, b: dict) -> dict:
    """Reconcile two THEN takeaways for the same WHEN trigger (unit 03).

    ``a``/``b`` carry ``{then, status, confirmed_by, date}``. Returns
    ``{same_trigger: bool, then: str, status: str, dropped: [{item, reason}]}``.
    If ``same_trigger`` is False, the caller ignores the other fields and keeps
    the lessons as separate nodes.

    RAISES ``ValueError`` on an unparseable reply (propagates to the write path's
    per-lesson handler, which skips + audits the lesson — graceful degradation)."""
    user = json.dumps({"when": when, "a": a, "b": b})
    raw = chatter.complete(_MERGE_SYSTEM, user, purpose="merge")
    data = parse_json(raw, default={})
    if not isinstance(data, dict) or "same_trigger" not in data:
        raise ValueError(f"merge_thens: unparseable model reply: {raw!r}")
    dropped = data.get("dropped") or []
    if not isinstance(dropped, list):
        dropped = []
    return {
        "same_trigger": bool(data.get("same_trigger")),
        "then": data.get("then", ""),
        "status": data.get("status", "tentative"),
        "dropped": dropped,
    }

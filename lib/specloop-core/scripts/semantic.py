#!/usr/bin/env python3
"""specloop semantic layer — cheap model calls for the WRITE side (S5).

OpenAI-compatible ``/chat/completions`` (default: mistral ``mistral-small-latest``).
Deliberately separate from the embedding providers in :mod:`engine` but reusing
the same key env by default (``MISTRAL_API_KEY``), so embeddings + semantic
write-outs share one dedicated model config.

This module owns the *semantic write-outs* (outcome summary + fix extraction).
The READ side (recall) never calls a model — it is pure cosine lookup in
:mod:`engine`. The :mod:`mem` CLI ``finish`` command calls the helpers here.

All functions are pure apart from :meth:`Chatter.complete`, so prompt-building
and JSON parsing are unit-testable without network (see test_semantic.py).
"""
from __future__ import annotations

import json
import os
import re

from httputil import post_json

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
                 timeout: int = 40) -> str:
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
_SESSION_SYSTEM = (
    "You write a memory 'recap' for a completed coding-agent session. "
    "Inputs: the session's INITIAL user prompt, the later user prompts, and "
    "the tool errors that occurred. Return STRICT JSON only: "
    '{"summary": string (<=3 plain sentences: what was actually accomplished '
    "and the final state. If the subject drifted or evolved away from the "
    "initial prompt over the session, fold that into the summary so future "
    "recall reflects the REAL outcome, not just the original ask), "
    '"status": "done" | "partial" | "failed" | "void"}. '
    "done=goal accomplished; partial=partly done or drifted; failed=the work failed; VOID=accomplished nothing worth remembering (trivial/abandoned/chat). Be terse and factual. If the session did nothing meaningful, return "
    '{"status":"void","summary":""}.'
)


def summarize_session(chatter: Chatter, initial_prompt: str, digest_json: str) -> dict:
    """Session recap content. Returns {'summary','status'}.

    The summary prose accounts for subject evolution: if the work drifted from
    ``initial_prompt``, that is folded into the summary (no separate field)."""
    user = (f"Initial prompt:\n{initial_prompt}\n\n"
            f"Session digest (JSON):\n{truncate(digest_json, 6000)}")
    return parse_json(chatter.complete(_SESSION_SYSTEM, user),
                      default={"summary": "", "status": "partial"})

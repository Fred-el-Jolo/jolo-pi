#!/usr/bin/env python3
"""Shared OpenAI-compatible HTTP helper for embeddings + chat.

One retry with jitter on transient failures (timeout / URLError, 429, 5xx) so a
single flaky gateway response doesn't disable recall for a whole pi session on
the first miss (the extension disables the memory layer on the first hard
error). Both the embedding endpoint (``engine.EmbedderAPI``) and the chat
endpoint (``semantic.Chatter``) go through ``post_json``.

Stdlib only (runs on a bare Pi). Non-transient errors (4xx except 429 — bad key,
unknown model) raise ``RuntimeError`` immediately with the upstream detail.
"""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request

# Retried: rate-limit + gateway/timeout status codes. Other 4xx is the caller's
# fault (bad key/model) → fail immediately, no point retrying.
_TRANSIENT_HTTP = {429, 500, 502, 503, 504}


def post_json(url, headers, body, *, timeout=30, retries=1, sleep=time.sleep):
    """POST ``body`` (dict) as JSON to ``url``; return the parsed JSON response.

    On a transient failure, retry up to ``retries`` times after a full-jitter
    backoff (~0.5–1.5s). Any failure that isn't transient (or that persists
    after retries) raises ``RuntimeError`` carrying the upstream status + a
    short detail snippet. ``sleep`` is injectable for tests.
    """
    payload = json.dumps(body).encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url, data=payload,
            headers={**headers, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode(errors="replace")[:500]
            except Exception:
                pass
            transient = e.code in _TRANSIENT_HTTP
            if transient and attempt < retries:
                sleep(0.5 + random.random())
                continue
            raise RuntimeError(f"{url} HTTP {e.code}: {detail}".rstrip()) from None
        except urllib.error.URLError as e:
            # network/timeout/DNS — always worth one retry
            if attempt < retries:
                sleep(0.5 + random.random())
                continue
            raise RuntimeError(f"{url} URLError: {e.reason}") from None
    raise RuntimeError(f"{url}: retries exhausted")  # pragma: no cover

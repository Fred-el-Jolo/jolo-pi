#!/usr/bin/env python3
"""Secret redaction for the specloop memory WRITE boundary.

Global-scope recall (engine §4) means a secret leaked into a prompt/error in
project A can be durably stored and later recalled into project B's context.
``redact()`` scrubs high-confidence structured secrets → ``[REDACTED:<kind>]``
placeholders BEFORE the text is embedded or persisted (called from
``engine.index``), so stored bodies are clean and recall
injects already-scrubbed text. For air-tight per-project isolation, set
``SPECLOOP_SCOPE=local``.

**This is best-effort, NOT a guarantee.** Regex redaction catches the common
structured tokens (cloud keys, API keys, JWTs, URL credentials, key=value
assignments, PEM blocks); it cannot catch arbitrary high-entropy secrets.
Design choice: favor FALSE NEGATIVES over false positives — a miss is defended
by scope choice, but a false positive mangles legitimate text/code in memory.

Gated by ``SPECLOOP_REDACT`` (default ON; ``0``/``off``/``false``/``no``
disables). Stdlib only.
"""
from __future__ import annotations

import os
import re

_ON_FALSE = {"0", "off", "false", "no"}

# High-precision secret patterns. Order matters only for the url-creds
# substitution (handled specially); the rest are plain substring replacements.
# Add a (kind, compiled) row to extend. Values are matched verbatim, not
# across arbitrary boundaries, to keep precision high.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # PEM private key block (multi-line) — capture first so the body inside
    # isn't separately matched by later patterns.
    ("private-key",
     re.compile(r"-----BEGIN (?:[A-Z0-9 ]+) PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+) PRIVATE KEY-----",
                re.DOTALL)),
    # Cloud / service tokens with distinctive prefixes
    ("aws-access-key",  re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token",    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,251}\b")),
    ("stripe-key",      re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}\b")),
    ("openai-key",      re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}\b")),
    # Structured self-describing tokens
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_\-]{6,}\.eyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.=]{20,}\b")),
    # credentials embedded in a URL: scheme://user:pass@host[:port]  -> scrub pass
    ("url-creds",
     re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)([^\s:/@]+):([^\s/@]+)(@[^\s/]+)")),
    # key=value / key: "..." assignments for common secret-bearing names.
    # requires a >=16-char value to avoid mangling ordinary short config.
    ("key-assign", re.compile(
        r"\b(?:api[_-]?key|apikey|secret|passwd|password|access[_-]?key|token)"
        r"\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?",
        re.IGNORECASE)),
]


def _enabled() -> bool:
    """Redaction is ON by default; disabled only by an explicit falsey value."""
    v = os.environ.get("SPECLOOP_REDACT")
    if v is None:
        return True
    return v.strip().lower() not in _ON_FALSE


def redact(text, enabled=None):
    """Scrub high-confidence secrets → ``[REDACTED:<kind>]``.

    ``enabled`` overrides the env-derived default (useful in tests and where a
    caller already resolved the flag). Returns the text unchanged when disabled
    or when the input is falsy. See module docstring for the precision/guarantee
    trade-off and the ``SPECLOOP_SCOPE=local`` escape hatch.
    """
    if enabled is None:
        enabled = _enabled()
    if not enabled or not text:
        return text
    out = text
    for kind, rx in _PATTERNS:
        if kind == "url-creds":
            out = rx.sub(
                lambda m: f"{m.group(1)}{m.group(2)}:[REDACTED:url-creds]{m.group(4)}",
                out)
        else:
            out = rx.sub(f"[REDACTED:{kind}]", out)
    return out

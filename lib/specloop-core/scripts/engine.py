#!/usr/bin/env python3
"""specloop-core memory engine.

Stdlib-only — runs on a bare Pi (Python 3.13 + sqlite3, no pip/numpy).

  Storage    : sqlite3 (one file; `cp` to back up)
  Similarity : cosine, linear scan (stdlib math)
  Embeddings : supplied by an Embedder; HashEmbedder (lexical, zero-dep) ships
               so the engine + bench run with no model deps.

Drop-in upgrades (interface unchanged):
  - sqlite-vec : replace the linear scan with sqlite-vec KNN once the corpus
                 hits ~10k+ vectors (needs `pip install sqlite-vec`).
  - real embedder : replace HashEmbedder with ONNX MiniLM / an API embedder for
                    semantic recall — this is what the bench decides
                    (references/testing.md §2).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from typing import Optional, Sequence

from httputil import post_json
from redact import redact

DEDUP_THRESHOLD = 0.92  # recap dedup on the initial-PROMPT vector (§8)


# --------------------------------------------------------------- Embedders
class Embedder:
    name = "base"
    dim = 0

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class HashEmbedder(Embedder):
    """Zero-dep LEXICAL baseline (signed feature hashing of word tokens).

    Cosine here approximates lexical overlap — NOT semantic similarity. It
    exists so the engine + bench run with no model deps and gives a meaningful
    lower bound a real embedder must beat. Replace it for real benchmarks.
    """

    name = "hash"

    def __init__(self, dim: int = 512):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokens(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if ((h >> 1) & 1) else -1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm > 0 else vec


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


# Remote embedding providers — all OpenAI-compatible `/embeddings` endpoints.
# Add a row here to support a new provider; nothing else in the codebase changes.
# Switching in code is then a one-liner:  make_embedder("mistral")
PROVIDERS = {
    "mistral": dict(                       # DOCUMENTED & confirmed (recommended)
        name="mistral", key_env="MISTRAL_API_KEY",
        url="https://api.mistral.ai/v1/embeddings", model="mistral-embed", dim=1024),
    "zai": dict(                           # endpoint undocumented; returns 401 (exists)
        name="zai", key_env="ZAI_API_KEY",
        url="https://api.z.ai/api/paas/v4/embeddings", model="embedding-3", dim=None),
    "openai": dict(
        name="openai", key_env="OPENAI_API_KEY",
        url="https://api.openai.com/v1/embeddings", model="text-embedding-3-small", dim=1536),
}


class EmbedderAPI(Embedder):
    """Remote embeddings via any OpenAI-compatible `/embeddings` endpoint.

    For the Pi (too weak for local embedding): key from the environment, no
    pip/model deps (plain Bearer HTTP via stdlib urllib). Prefer
    `make_embedder(provider)`; construct directly only for custom endpoints.
    """

    def __init__(self, name, key_env, url, model, api_key=None):
        import os
        self.name = name
        self.key_env = key_env
        self.api_key = api_key or os.environ.get(key_env)
        self.url = url
        self.model = model
        self._cache = {}
        self.dim = 0
        if not self.api_key:
            raise RuntimeError(
                f"{key_env} not set (export it to use the '{name}' embedder)")

    def embed(self, text):
        if text in self._cache:
            return self._cache[text]
        vec = self._call([text])[0]
        if not self.dim:
            self.dim = len(vec)
        self._cache[text] = vec
        return vec

    def _call(self, inputs):
        payload = post_json(self.url,
                            {"Authorization": f"Bearer {self.api_key}"},
                            {"model": self.model, "input": inputs},
                            timeout=30)
        # OpenAI-style: {"data":[{"embedding":[...], "index":0}, ...]}
        data = sorted(payload["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]


def make_embedder(provider, **overrides):
    """Build an EmbedderAPI from the PROVIDERS registry. Switching providers in
    code is a one-liner:  make_embedder("mistral")."""
    p = dict(PROVIDERS[provider])
    p.update(overrides)
    p.pop("dim", None)  # metadata only; dim is learned on first embed
    return EmbedderAPI(**p)


# --------------------------------------------------------------- Storage
_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id             TEXT PRIMARY KEY,
    type           TEXT NOT NULL,
    root_prompt_id TEXT,
    project        TEXT,
    created        REAL NOT NULL,
    body           TEXT NOT NULL,
    meta           TEXT NOT NULL DEFAULT '{}',
    embedding      TEXT NOT NULL,
    embedding_prompt TEXT
);
CREATE INDEX IF NOT EXISTS idx_type    ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_root    ON nodes(root_prompt_id);
CREATE INDEX IF NOT EXISTS idx_project ON nodes(project);
"""


class Memory:
    """The memory graph: one sqlite file, embeddings as JSON (→ vec BLOB later)."""

    def __init__(self, path: str = ":memory:", embedder: Optional[Embedder] = None,
                 current_project: Optional[str] = None):
        self.embedder = embedder or HashEmbedder()
        self.current_project = current_project
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        self._migrate()
        self._backfill_prompt_vectors()

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
        if len(a) != len(b):
            # Fail loud, not silent: ``zip`` would truncate to the shorter vec
            # and return plausible-looking garbage scores. The usual cause is
            # switching SPECLOOP_PROVIDER after data exists (e.g. mistral→hash,
            # 1024→512). Better to disable recall (the extension catches this)
            # than to corrupt ranking silently.
            raise ValueError(
                f"embedding dim mismatch: {len(a)} != {len(b)} "
                "(switching SPECLOOP_PROVIDER after data exists corrupts recall)")
        dot = na = nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        return dot / (math.sqrt(na) * math.sqrt(nb)) if na and nb else 0.0

    def _find_dup(self, ntype: str, prompt: str, project: Optional[str]) -> Optional[str]:
        """§8: merge a recap whose initial-PROMPT vector is near-identical.
        Dedup is on the user's ASK (prompt), not the summary body — so a failed
        attempt and a later partial on the same task merge regardless of how
        differently their summaries read. Status is ignored at match time; the
        higher-status summary survives via _maybe_promote."""
        q = self.embedder.embed(prompt)
        rows = self.conn.execute(
            "SELECT id, embedding_prompt FROM nodes WHERE type=? AND project IS ?",
            (ntype, project)).fetchall()
        best, best_id = 0.0, None
        for r in rows:
            ep = r["embedding_prompt"]
            if ep is None:
                continue  # legacy row pre-prompt-dedup — skip until backfilled
            s = self._cosine(q, json.loads(ep))
            if s > best:
                best, best_id = s, r["id"]
        return best_id if best >= DEDUP_THRESHOLD else None

    # status precedence for dedup survivor selection: the node with the
    # higher-rank summary wins the merge. ``void`` is never stored (skipped at
    # cmd_recap), so it's absent; ``error`` ranks lowest so a real summary
    # always supersedes a crashed attempt.
    _STATUS_RANK = {"done": 4, "partial": 3, "failed": 2, "error": 1}

    def _maybe_promote(self, dup_id: str, new_meta: dict, new_body: str) -> None:
        """On prompt-vector merge: if the new recap outranks the existing node's
        status, overwrite its body+meta with the better summary. Equal or lower
        rank → keep the existing node unchanged (stable; no churn)."""
        row = self.conn.execute("SELECT meta FROM nodes WHERE id=?", (dup_id,)).fetchone()
        if row is None:
            return
        old_rank = self._STATUS_RANK.get(
            (json.loads(row["meta"] or "{}")).get("status"), 0)
        new_rank = self._STATUS_RANK.get(new_meta.get("status"), 0)
        if new_rank > old_rank:
            # body changed → re-embed so recall ranking tracks the NEW summary,
            # not the stale pre-merge one
            self.conn.execute(
                "UPDATE nodes SET body=?, meta=?, embedding=? WHERE id=?",
                (new_body, json.dumps(new_meta),
                 json.dumps(self.embedder.embed(new_body)), dup_id))
            self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the initial schema to existing DBs.
        CREATE TABLE IF NOT EXISTS won't alter an existing table, so patch
        here. Idempotent: checks PRAGMA table_info before altering."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(nodes)")}
        if "embedding_prompt" not in cols:
            self.conn.execute("ALTER TABLE nodes ADD COLUMN embedding_prompt TEXT")
            self.conn.commit()

    def _backfill_prompt_vectors(self) -> None:
        """Populate embedding_prompt for recap rows that predate the column
        (prompt-vector dedup needs them). Best-effort: an embed failure leaves
        the row unfilled and _find_dup skips it until the next successful pass.
        A no-op once all recap rows carry a prompt vector."""
        rows = self.conn.execute(
            "SELECT id, meta FROM nodes WHERE type='recap' AND embedding_prompt IS NULL"
        ).fetchall()
        for r in rows:
            try:
                prompt = (json.loads(r["meta"] or "{}")).get("initial_prompt")
                if not prompt:
                    continue
                vec = self.embedder.embed(prompt)
                self.conn.execute(
                    "UPDATE nodes SET embedding_prompt=? WHERE id=?",
                    (json.dumps(vec), r["id"]))
            except Exception:
                continue  # leave for the next pass; never block recall/recap
        if rows:
            self.conn.commit()

    # -- public API (the contract facades rely on) -------------------------
    # Types that dedup-on-write (open-questions §8): one node per distinct
    # recap — repeating an identical session merges instead of stacking.
    _DEDUP_TYPES = ("recap",)

    # meta string fields that may carry free text (and thus secrets) — scrubbed
    # at index time alongside the body. See redact.py.
    _META_REDACT_KEYS = ("summary", "result", "initial_prompt")

    @staticmethod
    def _redact_meta(meta: dict) -> dict:
        out = dict(meta)
        for k in Memory._META_REDACT_KEYS:
            v = out.get(k)
            if isinstance(v, str):
                out[k] = redact(v)
        return out

    def index(self, node: dict) -> str:
        """Insert a node (+ embeddings). recap nodes dedup-on-write on the
        initial-PROMPT vector; the higher-status summary survives a merge.
        Returns the id used (may be an existing id if merged)."""
        ntype = node["type"]
        project = node.get("project", self.current_project)
        body = redact(node["body"])            # write-boundary scrub (redact.py)
        meta = self._redact_meta(node.get("meta", {}))

        if ntype in self._DEDUP_TYPES:
            # dedup on the prompt vector; fall back to body when meta has no
            # initial_prompt (manual/test nodes). Status is ignored at match
            # time — _maybe_promote keeps the higher-ranked summary.
            prompt = meta.get("initial_prompt") or body
            dup = self._find_dup(ntype, prompt, project)
            if dup is not None:
                self._maybe_promote(dup, meta, body)
                return dup

        nid = node.get("id") or str(uuid.uuid4())
        embedding = self.embedder.embed(body)
        embedding_prompt = None
        if ntype in self._DEDUP_TYPES:
            embedding_prompt = self.embedder.embed(meta.get("initial_prompt") or body)
        self.conn.execute(
            "INSERT INTO nodes(id,type,root_prompt_id,project,created,body,meta,embedding,embedding_prompt) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (nid, ntype, node.get("root_prompt_id"), project,
             node.get("created", time.time()), body,
             json.dumps(meta), json.dumps(embedding),
             json.dumps(embedding_prompt) if embedding_prompt is not None else None),
        )
        self.conn.commit()
        return nid

    def link(self, child_id: str, root_prompt_id: str) -> None:
        self.conn.execute("UPDATE nodes SET root_prompt_id=? WHERE id=?",
                          (root_prompt_id, child_id))
        self.conn.commit()

    def recall(self, query: str, k: int = 5, scope: str = "global",
               node_type: Optional[str] = None) -> list[dict]:
        """Top-k nodes by cosine. scope='global' (default, §4) | 'local'
        (current_project only). node_type filters a type (e.g. 'error'). The
        query is redacted first so it compares in the same scrubbed space as
        stored bodies (redact.py)."""
        q = self.embedder.embed(redact(query))
        clauses, params = [], []
        if node_type:
            clauses.append("type=?")
            params.append(node_type)
        if scope == "local" and self.current_project:
            clauses.append("project=?")
            params.append(self.current_project)
        sql = "SELECT * FROM nodes"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(sql, params).fetchall()

        scored = sorted(
            ((self._cosine(q, json.loads(r["embedding"])), r) for r in rows),
            key=lambda t: t[0], reverse=True,
        )
        out = []
        for score, r in scored[:k]:
            d = dict(r)
            d["meta"] = json.loads(r["meta"] or "{}")
            d.pop("embedding", None)
            d["_score"] = score
            out.append(d)
        return out

    def history(self, root_id: str) -> list[dict]:
        """A node + everything linked to it (``root_prompt_id == root_id``)."""
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE id=? OR root_prompt_id=? ORDER BY created",
            (root_id, root_id)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta"] = json.loads(r["meta"] or "{}")
            d.pop("embedding", None)
            out.append(d)
        return out

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def close(self) -> None:
        self.conn.close()

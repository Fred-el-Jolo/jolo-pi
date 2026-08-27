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
import os
import re
import sqlite3
import time
import uuid
from typing import Optional, Sequence

from httputil import post_json
from redact import redact
from usage import log as usage_log


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    try:
        return float(v) if v is not None and v.strip() else default
    except ValueError:
        return default


# MMR diversification weight for recall: score = λ·cos(query,d) − (1−λ)·max cos(d,picked).
# 1.0 = pure relevance (off); 0.7 trades a little relevance so near-duplicate
# lessons (e.g. the same situation re-learned) don't monopolize the top-k.
MMR_LAMBDA = _env_float("SPECLOOP_MMR_LAMBDA", 0.7)


# --------------------------------------------------------------- similarity
def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity with a loud dim-mismatch guard.

    ``zip`` would truncate to the shorter vector and return plausible-looking
    garbage scores; the usual cause of a mismatch is switching
    ``SPECLOOP_PROVIDER`` after data exists (e.g. mistral→hash, 1024→512). Better
    to fail (the extension catches it and disables recall) than corrupt rank."""
    if len(a) != len(b):
        raise ValueError(
            f"embedding dim mismatch: {len(a)} != {len(b)} "
            "(switching SPECLOOP_PROVIDER after data exists corrupts recall)")
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / (math.sqrt(na) * math.sqrt(nb)) if na and nb else 0.0


# --------------------------------------------------------------- Embedders
class Embedder:
    name = "base"
    dim = 0

    def embed(self, text: str, purpose: str = "embed") -> list[float]:
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

    def embed(self, text: str, purpose: str = "embed") -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokens(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if ((h >> 1) & 1) else -1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm > 0 else vec


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


# cosine is defined above (module-level) so the dedup/merge policy in lesson.py
# can reuse it without engine importing lesson (decomposition: the Store owns
# vector search, the policy owns semantics).


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

    def embed(self, text, purpose="embed"):
        if text in self._cache:
            return self._cache[text]
        vec = self._call([text], purpose=purpose)[0]
        if not self.dim:
            self.dim = len(vec)
        self._cache[text] = vec
        return vec

    def _call(self, inputs, purpose="embed"):
        payload = post_json(self.url,
                            {"Authorization": f"Bearer {self.api_key}"},
                            {"model": self.model, "input": inputs},
                            timeout=30)
        # log the token cost the API already reports; cache hits never reach here
        u = payload.get("usage") or {}
        usage_log({"kind": "embed", "provider": self.name, "model": self.model,
                   "purpose": purpose,
                   "prompt_tokens": u.get("prompt_tokens", 0) or 0,
                   "completion_tokens": 0,
                   "total_tokens": u.get("total_tokens", 0) or 0})
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
# Type-agnostic node table; see the Memory class docstring below for the
# policy-dispatch design this schema backs.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id        TEXT PRIMARY KEY,
    type      TEXT NOT NULL,
    project   TEXT,
    created   REAL NOT NULL,
    body      TEXT NOT NULL,
    meta      TEXT NOT NULL DEFAULT '{}',
    embedding TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_type    ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_project ON nodes(project);
"""


class Memory:
    """Flat sqlite node store + linear-scan cosine index (unit 01).

    Knows nothing about lessons, recaps, prompts, or models — only nodes,
    vectors, and types. ``index()`` dispatches to a per-type policy (registered
    via :meth:`register_policy`); if no policy is registered for a type, the node
    is inserted unconditionally. The match key vector is supplied per-type by the
    policy's ``embedding_text`` (key/payload separation): for a lesson that is the
    WHEN clause alone.

    Construction takes an **Embedder** (dependency injection):
    ``Memory(path, embedder, current_project)``. ``HashEmbedder`` (lexical,
    zero-dep) ships for tests/offline; ``make_embedder("mistral")`` for prod.
    """

    def __init__(self, path: str = ":memory:", embedder: Optional[Embedder] = None,
                 current_project: Optional[str] = None):
        self.embedder = embedder or HashEmbedder()
        self.current_project = current_project
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        self._policies: dict[str, object] = {}
        # outcome of the most recent index() call, as a stable string the write
        # path reads for audit: "new" | "merged:fast" | "merged:llm" | "not-a-dup".
        self.last_outcome = "new"

    # -- policy registry ---------------------------------------------------
    def register_policy(self, node_type: str, policy) -> None:
        """Register a dedup/merge policy for a node type.

        Policy protocol (duck-typed; the Store does NOT import it):
          ``embedding_text(node) -> str``
              the MATCH KEY text (redacted+embedded by the Store).
          ``find_candidate(store, node, project) -> str | None``
              an existing node id to merge onto, or None to insert fresh.
          ``merge(store, existing_id, new_node) -> MergeOutcome``
              reconcile in place; returns an enum whose ``.value`` is the outcome
              string (``merged:fast`` | ``merged:llm`` | ``not-a-dup``). A value of
              ``not-a-dup`` tells the Store to insert the new node instead."""
        self._policies[node_type] = policy

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _redact_meta(meta: dict) -> dict:
        """Redact every string value in meta, recursing into nested dicts/lists
        (e.g. lesson.py's ``provenance`` entries). A per-key allowlist would drift
        every time a policy adds a new free-text field — recursing over every
        string leaf doesn't need updating when that happens. Safe to apply
        broadly: redact() is high-precision by design (see redact.py)."""
        def scrub(v):
            if isinstance(v, str):
                return redact(v)
            if isinstance(v, dict):
                return {k: scrub(x) for k, x in v.items()}
            if isinstance(v, list):
                return [scrub(x) for x in v]
            return v
        return scrub(meta)

    def _insert(self, node: dict, project: Optional[str]) -> str:
        """Persist a fresh node. Redacts body + listed meta fields, then embeds
        the policy's key text (or the body when no policy) for the match vector."""
        ntype = node["type"]
        policy = self._policies.get(ntype)
        body = redact(node["body"])            # write-boundary scrub (redact.py)
        meta = self._redact_meta(node.get("meta", {}))
        if policy is not None:
            key = redact(policy.embedding_text(node))   # WHEN-only for lessons
        else:
            key = body                                   # fallback: embed the body
        embedding = self.embedder.embed(key, purpose="index")
        nid = node.get("id") or str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO nodes(id,type,project,created,body,meta,embedding) "
            "VALUES(?,?,?,?,?,?,?)",
            (nid, ntype, project, node.get("created", time.time()),
             body, json.dumps(meta), json.dumps(embedding)),
        )
        self.conn.commit()
        return nid

    # -- public API --------------------------------------------------------
    def index(self, node: dict) -> str:
        """Insert a node, or merge onto an existing id via the type's policy.

        Flow (unit 01 → 03): redact → policy.embedding_text → (find_candidate →
        policy.merge | insert). Returns the id USED — callers must not assume a
        new node was created (a merge returns the existing id). Sets
        :attr:`last_outcome` to the stable outcome string for audit."""
        self.last_outcome = "new"
        ntype = node["type"]
        project = node.get("project", self.current_project)
        policy = self._policies.get(ntype)
        if policy is None:
            return self._insert(node, project)          # no policy → unconditional insert
        cand = policy.find_candidate(self, node, project)
        if cand is None:
            return self._insert(node, project)          # no match → fresh node
        outcome = policy.merge(self, cand, node)        # MergeOutcome (enum)
        self.last_outcome = getattr(outcome, "value", "new")
        if self.last_outcome == "not-a-dup":
            return self._insert(node, project)          # vector false-positive
        return cand                                       # merged in place onto existing

    def _scan(self, vec, type: Optional[str] = None, project: Optional[str] = None,
              threshold: float = 0.0) -> list[tuple[str, float, list]]:
        """Full cosine scan → ``[(id, score, embedding)]`` sorted by score desc.

        Shared by :meth:`nearest` (top-k) and :meth:`recall` (MMR needs the
        candidate embeddings, not just ids+scores)."""
        clauses, params = [], []
        if type is not None:
            clauses.append("type=?")
            params.append(type)
        if project is not None:
            clauses.append("project=?")
            params.append(project)
        sql = "SELECT id, embedding FROM nodes"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(sql, params).fetchall()
        scored = []
        for r in rows:
            emb = json.loads(r["embedding"])
            s = cosine(vec, emb)
            if s >= threshold:
                scored.append((r["id"], s, emb))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored

    def nearest(self, vec, type: Optional[str] = None, project: Optional[str] = None,
                k: int = 1, threshold: float = 0.0) -> list[tuple[str, float]]:
        """Top-k node ids by cosine to ``vec``, each with score ≥ ``threshold``.

        Factored out of :meth:`recall` so the dedup policy can reuse the same
        cosine scan (no duplicated search, and the policy never touches SQL).
        ``project=None`` means global (no project filter); a value filters to it."""
        return [(i, s) for i, s, _ in
                self._scan(vec, type=type, project=project, threshold=threshold)[:k]]

    def recall(self, query: str, k: int = 5, scope: str = "global",
               node_type: Optional[str] = None) -> list[dict]:
        """Top-k nodes by cosine, MMR-diversified. scope='global' (default) |
        'local' (current_project only). node_type filters a type. The query is
        redacted first so it compares in the same scrubbed space as stored keys.

        Candidates are ranked by ``MMR_LAMBDA·cos(query,d) − (1−MMR_LAMBDA)·max
        cos(d, picked)`` so a cluster of near-duplicate lessons can't crowd out
        a distinct-but-slightly-less-relevant one. ``_score`` stays the raw
        query cosine (honest relevance for thresholds/audit); only the ORDER is
        diversified. ``SPECLOOP_MMR_LAMBDA=1`` restores pure relevance."""
        q = self.embedder.embed(redact(query), purpose="recall")
        project = self.current_project if scope == "local" else None
        pool = self._scan(q, type=node_type, project=project, threshold=0.0)
        picked: list[tuple[str, float, list]] = []
        while pool and len(picked) < k:
            if not picked or MMR_LAMBDA >= 1.0:
                best_i = 0
            else:
                best_i, best_v = 0, float("-inf")
                for i, (_nid, s, emb) in enumerate(pool):
                    penalty = max(cosine(emb, p[2]) for p in picked)
                    v = MMR_LAMBDA * s - (1.0 - MMR_LAMBDA) * penalty
                    if v > best_v:
                        best_i, best_v = i, v
            picked.append(pool.pop(best_i))
        out = []
        for nid, score, _emb in picked:
            node = self.get_node(nid)
            if node is None:
                continue
            node["_score"] = score
            out.append(node)
        return out

    def get_node(self, id: str) -> Optional[dict]:
        """Fetch one node (meta parsed, embedding dropped), or None."""
        r = self.conn.execute("SELECT * FROM nodes WHERE id=?", (id,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["meta"] = json.loads(r["meta"] or "{}")
        d.pop("embedding", None)
        return d

    def update_node(self, id: str, body: Optional[str] = None,
                    meta: Optional[dict] = None) -> None:
        """Update an existing node's body and/or meta IN PLACE (stable id).

        Used by a policy's merge path. ``body`` and listed meta fields are
        redacted on write; the embedding is deliberately NOT changed here (a
        merge evolves the payload, not the match key — see unit 03 §stable id)."""
        if body is not None:
            self.conn.execute("UPDATE nodes SET body=? WHERE id=?",
                              (redact(body), id))
        if meta is not None:
            self.conn.execute("UPDATE nodes SET meta=? WHERE id=?",
                              (json.dumps(self._redact_meta(meta)), id))
        self.conn.commit()

    def count(self, type: Optional[str] = None) -> int:
        """Node count, optionally filtered by type."""
        if type is not None:
            return self.conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE type=?", (type,)).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def close(self) -> None:
        self.conn.close()

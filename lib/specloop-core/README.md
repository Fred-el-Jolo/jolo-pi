# specloop-core  *(internal library — not a skill)*

> **Not a skill.** No `SKILL.md`, so pi's scanner ignores it. This is the shared memory engine the [`specloop-pi`](../../extensions/specloop-pi) extension shells out to. It exists **exactly once**.

## What it does

A flat memory of **one node type — `recap`** — one per session, embedded and dedup-on-write. Two operations, full stop:

- **recall** — top-k similar recaps by cosine (used on the session's first prompt).
- **recap** — a dedicated cheap model summarizes the session (initial prompt + how the subject evolved + errors) into one recap node (used on session quit).

No error nodes, no spec/plan nodes, no per-turn writes. Subject-drift is folded into the recap summary prose, not a separate field.

## What's in here

| File | Purpose |
|---|---|
| `references/loop.md` | The two-touch loop: **recall** (start) → **recap** (end). |
| `references/memory-model.md` | The single `recap` node schema + recall queries. |
| `references/open-questions.md` | Engine-level decisions. |
| `references/testing.md` | How to bench recall quality + pick the embedding model. |
| `scripts/` | `engine.py` (index/recall/link — stdlib sqlite3+cosine, dedup-on-write) · `semantic.py` (chat + recap summarizer — default mistral) · `mem.py` (CLI: recall/remember/recap/start/history/link/stats/export/audit) · `bench.py` (Recall@k / MRR) · `smoke.py` (provider check) · `redact.py` (write-boundary secret scrubber) · `audit.py` (use-log) · `httputil.py` (retry+jitter POST). sqlite-vec = drop-in at scale; providers = drop-in for semantics. |
| `tests/` | `test_engine.py` + `test_semantic.py` + `test_audit.py` + `test_redact.py` + `test_http.py` + `corpus/` (labeled recall pairs; **seed is synthetic — replace with real data**). |

## The contract the extension relies on

```
index(node)                # write a recap node + its embedding; dedup-on-write (§8)
recall(query, k, filter?)  # top-k by similarity; scope defaults to GLOBAL, 'local' opt-in (§4)
link(child_id, root_id)    # attach provenance (manual primitive; recaps are roots)
```

Storage: **SQLite** (stdlib sqlite3 + cosine via linear scan; sqlite-vec drops in at scale). Embeddings are a separate, provider-agnostic concern (`PROVIDERS` + `make_embedder` in `engine.py`).

## How the extension uses it

The pi extension ([`../../extensions/specloop-pi`](../../extensions/specloop-pi)) owns both touches by calling `mem.py` from lifecycle hooks — it does **not** import this code; it shells out:

- `before_agent_start` (first prompt) → `mem start` (recall-only).
- `session_shutdown{quit}` → `mem recap` (one chat call → one recap node).

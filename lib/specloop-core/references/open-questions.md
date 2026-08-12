# Open Questions / Decisions

## 1. RAG backend — ✅ RESOLVED
**SQLite** (stdlib sqlite3 + cosine via linear scan; zero daemon, one file, runs on a bare Pi). sqlite-vec drops in at scale (~10k+ vectors) behind an unchanged interface.
- **Embeddings = remote OpenAI-compatible API** (Pi CPU too weak for local). Provider-agnostic via `PROVIDERS` + `make_embedder`. Registered: **mistral** (`mistral-embed`, 1024-dim — recommended & verified on-Pi), `zai`, `openai`, `hash` (lexical, offline/tests). Switching is a one-liner.
- **Local-only.** Privacy-first. Sync across machines = future opt-in.

## 2. Memory scope — ✅ RESOLVED (global default)
**GLOBAL by default; `scope='local'` (current repo) as opt-in** (`SPECLOOP_SCOPE=local`). Memory's value compounds across projects; per-repo cold-starts every new repo. Recall returns top-K by *similarity*, which already filters relevance hard; scope is a redundant second filter. The real risks under global are staleness + volume — mitigated by dedup-on-write (§4) + token caps (§3).

## 3. Recall token budget — ✅ RESOLVED
Hard caps (tune with data). Recalled recaps render as **compact one-liners**, never full bodies.
- **recall (start):** top-3 similar recaps × 1-line summary. Hard cap **≤ 800 tokens** (target ~600). Env-tunable via `SPECLOOP_MAX_CHARS_M0`.

## 4. Hygiene — dedup-on-write NOW; decay/compaction DEFERRED
- **Dedup-on-write:** before indexing a new recap, check similarity to existing recaps in scope; if ≥ ~0.98, merge instead of duplicating. Prevents repeated-identical-session pollution.
- **Decay / archival: DEFER** (no data yet).
- **Compaction: DEFER.**
- **Embedding dim-mismatch guard:** `_cosine` raises `ValueError` on `len(a) != len(b)` instead of silently truncating (the failure mode when switching `SPECLOOP_PROVIDER` after data exists).

## 5. Secret redaction at the WRITE boundary — ✅ DONE
`scripts/redact.py` scrubs high-precision structured secrets (cloud tokens, API keys, JWTs, URL credentials, key=value assignments, PEM blocks) → `[REDACTED:<kind>]` *before* embedding/persisting, in `engine.index` (body + free-text meta fields) and `engine.recall` (query — so query↔body compare in the same scrubbed space). Gated by `SPECLOOP_REDACT` (default **ON**). **Best-effort, NOT a guarantee** — favours false negatives over false positives (a miss is defended by `SPECLOOP_SCOPE=local`; a false positive mangles stored text). Entropy-based detection + a `mem scrub` migration remain deferred.

## 6. Why an extension (hooks), not a skill — ✅ RESOLVED
The core promise is *"on the first prompt, recall; on quit, recap"* — both must be **guaranteed**, which an event-hook extension is and a model-driven skill is not (compliance = instruction-following). So memory lives in the **pi extension** (`specloop-pi`) as lifecycle hooks. The *recap content* is semantic, so it's produced by a **dedicated cheap model** (`semantic.py`) at session end, not by hooks. There are **no skills** driving memory — the earlier execution-discipline skills (`specloop-dev`, `specloop`) were removed as out-of-scope bloat; `process-extractor` stays (standalone, no memory tie).

## 7. Two touches, not a continuous loop — ✅ RESOLVED (design choice, with eyes open)
The memory layer fires exactly twice per session: **recall on the first prompt**, **recap on quit**. This deliberately drops the earlier continuous machinery:
- **on-error mid-run recall** (inject a known fix when the same error recurs) — **removed**. This was the single highest-leverage feature for coding, but it was also most of the engine's complexity and the main source of mid-session noise/cost. Traded away for fewer interruptions and a simpler system. Re-introducing it would mean re-adding error embeddings + a `tool_result` hook.
- **per-turn outcome writes** — **removed** (replaced by one session recap).

Accepted trade-off: a session that drifts to a brand-new topic mid-way gets no fresh recall for that topic — by design. The end-of-session recap captures the drift so the *next* session recalls it.

---

**Status:** all resolved/deferred. **Built & running:** `engine.py` (index/recall/link, dedup-on-write for recaps, global/local, write-boundary redaction) · `redact.py` · `httputil.py` (retry+jitter) · `semantic.py` (chat + `summarize_session` recap summarizer, default mistral) · `audit.py` · `mem.py` (recall/remember/recap/start/history/link/stats/export/audit) · tests green (engine 9, semantic 8, audit 5, redact 16, http 5) · **`specloop-pi` extension** (session_start probe, gated first-prompt recall, quit-only recap; tsc-clean + mock-pi verified). **Next:** run it for real to accumulate the corpus the [bench](testing.md) validates for recall quality.

# Migration, compatibility & constants

## Supersession — what happens to the live system

| Artefact | Disposition |
|---|---|
| `recap` node type (prose, 1/session) | **Retired — purged.** No recap type remains; the DB is reset (see below). |
| `lesson` node type | **New — the only type.** WHEN/THEN, `embedding = embed(WHEN)`. |
| `_maybe_promote` (highest-status overwrite) | **Removed.** Replaced by the two-stage + LLM merge policy ([03](03-dedup-merge.md)). |
| `embedding_prompt` column + its `_migrate` / `_backfill_prompt_vectors` code | **Removed.** They existed only for recap prompt-dedup; lessons use `embedding` for both recall and dedup — no separate column. |
| `void` / `error` status semantics | **Carried over**, with one change: M2 writes **no error-flagged nodes** (extraction failure ⇒ audit-only). |
| `recall` / `formatContext` | **Carried over**, renders WHEN/THEN rules. |
| Audit log (mechanism) | **Carried over** + `merge` events + per-lesson `write` outcomes; the old *file* is purged. |
| M0 link graph (`root_prompt_id` column, `history()`, `link()`) | **Removed.** Lessons carry provenance in `meta` ([03](03-dedup-merge.md)); no node-link traversal. |

## Existing data — purged, not migrated

**Decision: the DB is reset to empty. No existing memories are carried over.**

The current 6 `recap` nodes are prose session summaries. They can't be re-derived
into lessons (the original session digests weren't retained), and M2 recall is
situation↔WHEN — prose recaps would only dilute it. A clean restart is simpler
than a coexist shim and loses nothing of substance: the **audit log already holds
the full session history**, and forward-going memory is what compounds.

**How:** delete the DB file — `rm ~/.specloop/memory.db`. The schema is recreated
fresh on next open from `_SCHEMA` (now lesson-only, no `embedding_prompt`). The
`recap` type is retired outright: not written, not read, not special-cased —
only `lesson` exists.

**Audit log — also purged.** Old entries reference the retired recap schema
(stale node ids, the pre-M2 `void` / `error` / merge semantics), so they'd be
misleading against the fresh DB. Delete `~/.specloop/audit.jsonl` with the DB; it
is recreated empty on the next `session_start` (the extension appends, and
`open_memory` re-creates the dir).

## Constants & tunables

All env-overridable where it makes operational sense (prefix `SPECLOOP_`).

| constant | default | unit | meaning |
|---|---|---|---|
| `LESSON_DEDUP_THRESHOLD` | **0.92** | [03](03-dedup-merge.md) | WHEN-vector cosine to flag a merge candidate. The arbiter makes this forgiving — a false candidate is rejected, so the value can be a little loose. |
| `THEN_IDENTICAL_THRESHOLD` | **0.95** | [03](03-dedup-merge.md) | THEN-vector cosine for the fast path (confirm-count, no LLM). |
| `MAX_LESSONS` | **5** | [02](02-extraction.md) | hard cap lessons per session |
| `SOFT_LESSON_TARGET` | **3** | [02](02-extraction.md) | prompt-side soft target (anti-padding) |
| `MAX_THEN_ITEMS` | **6** | [03](03-dedup-merge.md) | hard cap items in a merged THEN |
| `CONFIRM_TO_CONFIRMED` | **2** | [04](04-status.md) | distinct sessions to promote tentative→confirmed |
| `SPECLOOP_MIN_SCORE` | **0.40** | [06](06-read-path.md) | recall inject threshold (existing) |
| `SPECLOOP_K` | **5** | [06](06-read-path.md) | recall top-k (existing) |
| `SPECLOOP_MAX_CHARS_M0` | **2400** | [06](06-read-path.md) | injected-block char budget (existing) |

> **On `SPECLOOP_MIN_SCORE`:** design review found `mistral-embed`'s unrelated-text
> cosine floor sits at ~0.55–0.65, so 0.40 admits weak/false matches *regardless
> of format*. Tightening it (~0.68) would cut false positives more than any format
> change — but that's an **independent tuning decision**, out of scope for this
> spec. Flagged here so it isn't forgotten.

## Implementation order (build sequence)

Each step is independently testable; do not advance on red.

0. **Purge** — `rm ~/.specloop/memory.db` (recreated lesson-only on next open) **and** `rm ~/.specloop/audit.jsonl` (recreated empty on next `session_start`).
1. **Status unit** ([04](04-status.md)) — pure; lands first as the shared vocab.
2. **Extractor** ([02](02-extraction.md)) — `extract_lessons` + prompt; mock-chatter tests.
3. **Store changes** ([01](01-storage.md)) — register the `lesson` type + dedup/merge dispatch; `embedding` from `meta.when`. **Drop `embedding_prompt` from `_SCHEMA` and delete `_migrate` / `_backfill_prompt_vectors`** (they served only recap prompt-dedup).
4. **Dedup+Merge** ([03](03-dedup-merge.md)) — candidate → fast path → `merge_thens`; mock-chatter tests for every branch.
5. **Write path** ([05](05-write-path.md)) — rewire `cmd_recap` to the new flow; void/error handling; audit additions.
6. **Read path** ([06](06-read-path.md)) — render WHEN/THEN (`lesson` is the only type; no type-defaulting needed).
7. **Wire-in / smoke** — run against the fresh DB with a real mistral key; confirm a synthetic session yields lessons that recall against a matching query.

## Test plan

**Per-unit (mocked, no network):**
- 02 — schema conformance, `void`⇒[], cap, garbage-JSON⇒raises (→ write-path `error`).
- 03 — candidate found/none; fast-path bumps `confirmed_by` + trends status;
  `same_trigger=false`⇒new node; LLM⇒in-place update (id stable, body changed,
  provenance appended, `dropped` honoured); authority picks higher-status side;
  length cap drops lowest-value-with-reason.
- 04 — translations + merged-status table.
- 05 — node count = `len(lessons)`−merges; `void`/error⇒0 nodes+audit; per-lesson skip⇒partial.

**Integration (in-memory, `HashEmbedder`):** a multi-session sequence where the
same trigger recurs — assert the second session fast-path-merges, a third with a
*different* THEN triggers an LLM-merge, and a different-trigger lesson stays a
separate node.

**Recall bench (existing `references/testing.md`):** rebuild the labelled corpus
as `(situation-query → correct lesson)` pairs (the old recap corpus is the wrong
shape). Re-run Recall@k / MRR; the lesson model should beat the recap model on
situation queries by a clear margin — that's the proof the design pays off.

## Out of scope (deferred / v2)

- WHEN refinement on merge (keys stay stable in v1).
- Confirm-count/status boost in recall ranking.
- `contested` surfacing in the TUI / recall deprioritisation.
- Dual-vector indexing (WHEN + symptom) for symptom-based discovery.
- Decay/compaction of old lessons (M0 deferred this too).

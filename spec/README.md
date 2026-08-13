# specloop memory — lesson-based model (M2)  *(spec)*

> **Status: design spec — not yet implemented.** This describes the target
> architecture agreed in design review. The live system today is the **M0**
> recap-per-session model (`lib/specloop-core/references/`). This spec supersedes
> it; see [Migration & compatibility](units/07-migration.md).

## The change in one paragraph

Today, memory writes **one prose-summary node per session** and matches a future
query (a *situation*) against that *narrative* — a semantic mismatch, and the
retrieved knowledge is descriptive, not actionable. M2 rewrites the write path to
extract **0–5 reusable lessons per session**, each a `WHEN <situation> THEN
<takeaway>` rule stored as its **own node**, with the embedding computed on the
**WHEN clause alone**. Recall then matches situation↔situation at full strength,
and dedup/merge operates at the **lesson** level — so recurring situations
compound into refined, confirmed rules instead of stacking duplicate recaps.

## Why (the three findings that drove it)

1. **Precision** — a solo-fact vector recalls at ~0.85 vs ~0.72 for a 5-bullet
   centroid and ~0.66 for a prose summary (measured on the live `mistral-embed`).
   One node per learning is the precision-optimal storage.
2. **Cue alignment** — the query is a *situation*; the WHEN clause is a
   *situation*. Embedding WHEN-only aligns the stored key with the retrieval cue
   (key/payload separation: WHEN is the key, the full rule is the payload).
3. **Actionability + compounding** — rules are prescriptive, and per-lesson
   dedup lets a recurring trigger accumulate confirmations and refinements.

## Unit map

The system is decomposed into units with one purpose each, communicating through
the interfaces below. Each unit doc answers: **what it does, how to use it, what
it depends on** — readable without its internals.

| Unit | Doc | Purpose | Key interface |
|---|---|---|---|
| **Store** | [01-storage](units/01-storage.md) | persist nodes; cosine search; dispatch index→dedup/merge by type | `index(node)→id`, `recall(q,k,scope,type?)→[hit]` |
| **Extractor** | [02-extraction](units/02-extraction.md) | session → 0–5 lessons + status | `extract_lessons(chatter, ip, digest)→{status, lessons}` |
| **Dedup+Merge** | [03-dedup-merge](units/03-dedup-merge.md) | same-trigger? → fast-path confirm or LLM-merge THENs | `merge_thens(chatter, when, a, b)→{same_trigger, then, status, dropped}` |
| **Status** | [04-status](units/04-status.md) | status taxonomy + conflict-resolution authority | (pure taxonomy; consumed by 02/03/06) |
| **Write path** | [05-write-path](units/05-write-path.md) | orchestrate session-end: digest→extract→index→audit | `mem recap` CLI |
| **Read path** | [06-read-path](units/06-read-path.md) | session-start: recall lessons → format → inject | `recall()` + `formatContext()` |
| **Migration** | [07-migration](units/07-migration.md) | supersession, existing data, constants, test plan | — |

## End-to-end data flow

```
SESSION QUIT (reason=quit)
  build digest {initial_prompt, prompts[], errors[]}            [extension]
  └─► mem recap  (background, fire-and-forget)                   [write-path 05]
        ├─ extract_lessons(chatter, ip, digest) ──► {status, lessons[]}   [02]
        │     status==void  ─► audit VOID, write nothing        (graceful: nothing learned)
        │     extraction err ─► audit ERROR, write nothing        (graceful: never break the run)
        │     else            ─► for each lesson:
        └─ store.index(lesson_node)                                      [01]
              ├─ redact(when), redact(body)
              ├─ dedup: WHEN-vector cosine ≥ 0.92?  ──► candidate id     [03]
              │     no candidate ─► INSERT new lesson (embed=embed(when))
              │     candidate    ─► merge policy:
              │         THENs near-identical? ─► FAST-PATH: confirm-count bump, no LLM
              │         else                 ─► merge_thens (LLM)              [03]
              │            same_trigger=false ─► NOT a dup → INSERT new lesson
              │            same_trigger=true  ─► UPDATE existing (merged THEN, provenance, status)
              └─ audit WRITE/MERGE

SESSION START (first prompt only)
  recall(prompt) ──► top-k lessons by cosine(embed(prompt), embed(when))   [01/06]
  formatContext(hits) ──► inject rules ≥ minScore into system prompt
```

## Glossary

- **Lesson** — one reusable rule; the M2 node unit. `WHEN <trigger> THEN <takeaway>`.
- **WHEN / trigger** — the situation that should recall this lesson. It is the
  **index key** (embedded alone) and the **dedup key**.
- **THEN / takeaway** — the payload: an *action* to take, a *fact* that holds, or
  a *verdict* reached. Flexible by design (one shape, broad coverage).
- **Confirm-count** — how many distinct sessions re-learned the same lesson
  (fast-path). Trends a lesson's status toward `confirmed`.
- **Provenance** — the raw input THENs (with status/session/date) preserved in
  meta when an LLM-merge occurs, so a bad merge is recoverable.
- **Authority** — the precedence used to resolve contradictions between two
  THENs during merge: status rank → confirm-count → recency.
- **Arbiter** — the LLM call that confirms a vector-candidate pair is truly the
  *same trigger* before merging (two-stage dedup).
- **Void** — model verdict: nothing durably reusable was learned → write nothing.
- **Error** — engine-only status: the extraction/merge call failed technically
  → write nothing, audit the failure (memory must never break the run).

## Design principles (apply to every unit)

1. **Isolation.** Each unit has one purpose and a narrow interface. Internals
   may change without breaking consumers as long as the interface holds.
2. **Key/payload separation.** The match key (WHEN) is embedded; the payload
   (full rule) is stored and injected. Never embed the payload into the key.
3. **Graceful degradation.** Every model/embed call is best-effort: a failure
   disables that touch for the session (audit + notify), never raises into the
   agent run. Memory is a convenience, not a dependency.
4. **Grounding.** Lessons must be evidenced by the session transcript; the
   extractor is explicitly told not to invent plausible generalities.
5. **Stable ids, evolving content.** A merge updates the *existing* node in
   place (WHEN/embedding unchanged in v1); ids don't churn across merges.

## Supersession at a glance

| From M0 (today) | In M2 | Note |
|---|---|---|
| `recap` node type (prose, 1/session) | **frozen** — no new writes | existing nodes read-only; see [07-migration](units/07-migration.md) |
| `lesson` node type | **new** — the only active write type | WHEN/THEN, embed(WHEN) |
| dedup on `initial_prompt` vector | **replaced** — dedup on WHEN vector | [03](units/03-dedup-merge.md) |
| highest-status overwrite (`_maybe_promote`) | **replaced** — two-stage + LLM merge | [03](units/03-dedup-merge.md) |
| `embedding_prompt` column | **vestigial** for lessons | `embedding` *is* the WHEN vector; column kept for legacy recaps |
| `void` / `error` status | **carried over** | void→no nodes; error→no nodes, audit only |
| `recall` + `formatContext` | **carried over**, renders rules | [06](units/06-read-path.md) |
| audit log | **carried over**, + `merge` events | [05](units/05-write-path.md) |

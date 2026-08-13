# specloop Lesson-Based Memory (M2) Implementation Plan

**Goal:** Replace specloop's one-recap-per-session memory with per-learning `WHEN…THEN` lesson nodes — embedded on the trigger clause, deduped and merged at the lesson level — so future sessions recall situation-matched, actionable rules instead of session narratives.

**Architecture:** Memory becomes a flat store of `lesson` nodes — one per reusable `WHEN…THEN` rule, embedded on the trigger clause alone (key/payload separation) so recall matches situation↔situation. A generic `Memory` store dispatches `index()` through a per-type policy registry to a `LessonPolicy`, which dedups on the WHEN vector (two-stage: cosine candidate → LLM same-trigger arbiter) and merges THENs losslessly (fast-path confirm-count, else LLM reconcile by authority), with a pure `status.py` taxonomy shared by the write path and the merge. The read path and the pi extension stay untouched — `recall`/`formatContext` are already generic and `lesson` becomes the only node type.

**Tech Stack:** Python 3.13 (stdlib only — `sqlite3`, `urllib`, `math`; zero pip deps), SQLite storage; remote embeddings via `mistral-embed` (OpenAI-compatible `/embeddings` over stdlib HTTP; `zai`/`openai`/`hash` alternates); recap + merge chat via Mistral (OpenAI-compatible). The pi extension is TypeScript loaded via `jiti` (untouched in M2); tests use stdlib `unittest`.

**Spec:** [`README.md`](README.md) + [`units/01`–`07`](units/). The plan argues from the spec, so the spec travels with it — executors read both; every task cites its unit, and a deviation requires a spec edit first.

> **Status:** plan — not started. **Scope:** the lesson-based model (M2) as specified — one
> implementation plan, sequenced so each task is self-contained and independently
> testable.

**Build order** mirrors [`units/07-migration.md §Implementation order`](units/07-migration.md#implementation-order-build-sequence).
**Invariant for every task:** land green (unit test passes) before advancing.

---

## Global Constraints

Exact project-wide requirements — each line is a hard, checkable constraint.
Behavioral invariants (graceful degradation, key/payload separation, stable ids,
grounding) live in the spec's [Design principles](README.md#design-principles-apply-to-every-unit).

**Version & dependencies**
- **Python:** 3.13 (target; `from __future__ import annotations`).
- **Dependencies:** zero pip packages — stdlib only (`sqlite3`, `urllib`, `math`, `hashlib`, `re`, `json`, `uuid`, `argparse`, `subprocess`). No numpy, no pytest, no `sqlite-vec` (deferred to ≥10k vectors).
- **Tests:** stdlib `unittest`, each file standalone (`python3 tests/test_<unit>.py`).

**Naming (exact strings)**
- **Node type:** `"lesson"` — the only type.
- **Rule body:** `WHEN <when> THEN <then>` (literal prefixes).
- **Status vocab:** session `{done, partial, failed, void}`; lesson `{confirmed, tentative, contested}`; `error` is engine-only, never stored on a node.
- **Symbols:** `extract_lessons`, `merge_thens`, `LessonPolicy`, `Memory.{index,recall,nearest,get_node,update_node,register_policy,count}`.
- **Files:** snake_case — `status.py`, `lesson.py`, `engine.py`, `semantic.py`, `mem.py`.
- **Env vars:** `SPECLOOP_` prefix (`SPECLOOP_DB`, `SPECLOOP_PROVIDER`, `SPECLOOP_CHAT_PROVIDER`, `SPECLOOP_REDACT`, `SPECLOOP_MIN_SCORE`, `SPECLOOP_K`, `SPECLOOP_NOTIFY`, …); provider keys `MISTRAL_API_KEY` / `ZAI_API_KEY` / `OPENAI_API_KEY`.

**Copy (verbatim user-facing strings — do not reword)**
- **Recall block header:** `## related past work (auto-recalled — consider but verify)`.
- **Notify prefix:** `specloop:` (e.g. `specloop: recalled N related`).
- **Manual command:** `/specloop` → `recall <q> | stats | off`.

**Platform**
- **Target:** a bare Raspberry Pi (the constraint that forces stdlib-only + remote models).
- **Storage:** one local SQLite file (`$SPECLOOP_DB` or `~/.specloop/memory.db`); linear cosine scan.
- **Network:** embeddings + chat are remote (OpenAI-compatible API); a provider key is required in production. The pi extension never does HTTP — only the Python engine does.

Every task below implicitly inherits these constraints — they are not restated per task.

---

## 1. File map — decomposition locked here

| Path | Action | Responsibility | Spec unit |
|---|---|---|---|
| `scripts/status.py` | **CREATE** | Pure status taxonomy + authority: vocab, rank, initial/promote/merged mappings | [04](units/04-status.md) |
| `scripts/lesson.py` | **CREATE** | The `LessonPolicy`: WHEN-vector dedup + fast-path/arbiter/LLM merge | [03](units/03-dedup-merge.md) |
| `scripts/engine.py` | **MODIFY** | Generic store: schema, policy registry, `nearest()`, node helpers; **remove all M0/M0+ dedup code** | [01](units/01-storage.md) |
| `scripts/semantic.py` | **MODIFY** | `extract_lessons` + `merge_thens` (+ chat infra); **remove `summarize_session`** | [02](units/02-extraction.md) · [03](units/03-dedup-merge.md) |
| `scripts/mem.py` | **MODIFY** | Rewrite `cmd_recap`; register `LessonPolicy`; **remove `cmd_history`/`cmd_link`/`--no-summary`** | [05](units/05-write-path.md) |
| `tests/test_status.py` | **CREATE** | status.py translations + merged-status table | [04](units/04-status.md) |
| `tests/test_lesson.py` | **CREATE** | LessonPolicy every branch (mock chatter) | [03](units/03-dedup-merge.md) |
| `tests/test_engine.py` | **MODIFY** | Drop history/link + M0 dedup tests; add registry/`nearest`/helpers | [01](units/01-storage.md) |
| `tests/test_semantic.py` | **MODIFY** | `extract_lessons`/`merge_thens`; drop `summarize_session` | [02](units/02-extraction.md) · [03](units/03-dedup-merge.md) |
| `tests/test_mem.py` | **CREATE** | `cmd_recap` end-to-end: void/error paths, per-lesson index/merge, JSON shape | [05](units/05-write-path.md) |
| `extensions/specloop-pi/extension/{extension,mem}.ts` | **NONE** | Read path is generic + `lesson` is the only type → verified, not edited | [06](units/06-read-path.md) |
| `scripts/{redact,audit,httputil,bench,smoke}.py` | **NONE** | Untouched | — |
| `~/.specloop/{memory.db,audit.jsonl}` | **PURGE** | Manual, task 0 | [07](units/07-migration.md) |

### Decomposition decisions (why these boundaries)

1. **`status.py` is its own file, not folded into `lesson.py`.** Spec [04](units/04-status.md) is a *pure* taxonomy consumed by two units (write-path mapping in `mem.py`, merge authority in `lesson.py`). A dedicated file keeps the vocabulary canonical so the consumers can't diverge, and it's trivially unit-testable with no DB/model.
2. **`lesson.py` is its own file, and `engine.py` imports nothing from it.** The Store stays lesson-agnostic: it exposes a **policy registry** and calls `embedding_text` / `find_candidate` / `merge` polymorphically. All lesson-specific intelligence (WHEN-key embedding, thresholds, arbiter, reconciliation) lives in `LessonPolicy`. This is what lets `engine.py`'s internals change without breaking the policy, and vice versa.
3. **The Store owns vector search; the policy owns semantics.** `engine.nearest()` is factored out of `recall()` and reused by `LessonPolicy.find_candidate()` — no duplicated cosine scan, and the policy never touches SQL.
4. **The extension is intentionally untouched.** `recall`/`formatContext`/hooks are generic over node bodies; with `lesson` as the only type they render rules as-is. This is a verification task (§3 task 6), not a code task — calling it out so no one edits TS speculatively.
5. **`semantic.py` keeps only LLM concerns.** `extract_lessons` + `merge_thens` + chat infra. It does *not* import `status.py` — it emits raw session statuses per its prompt; the write path applies the session→lesson mapping. Keeps the LLM boundary clean.

---

## 2. Interface contracts to land first (the seams)

These signatures are committed early (task 1–3) so every later unit can be built and tested against them in isolation. **Internal implementations may change; these shapes should not.**

### `status.py`
```python
SESSION_STATUS = ("done", "partial", "failed", "void")   # model verdicts (02)
LESSON_STATUS  = ("confirmed", "tentative", "contested")  # stored on node
STATUS_RANK    = {"confirmed": 3, "tentative": 2, "contested": 1}
CONFIRM_TO_CONFIRMED = 2

def initial_lesson_status(session_status: str) -> str           # done→confirmed; partial/failed→tentative
def promote(status: str, confirmed_by_count: int) -> str        # tentative→confirmed at ≥ CONFIRM_TO_CONFIRMED
def merged_status(source_statuses: list[str]) -> str            # all confirmed→confirmed; else tentative (contested set by merger)
def authority_rank(status: str, confirmed_by_count: int, created: float) -> tuple  # sortable: (rank, count, -created)
```

### `semantic.py`
```python
def extract_lessons(chatter, initial_prompt: str, digest_json: str) -> dict:
    # → {"status": <SESSION_STATUS>, "lessons": [{"when": str, "then": str}, ...]}
    # void ⇒ lessons == [].  RAISES on unparseable JSON (write path maps to error).

def merge_thens(chatter, when: str, a: dict, b: dict) -> dict:
    # a,b = {"then","status","confirmed_by","date"}
    # → {"same_trigger": bool, "then": str, "status": str, "dropped": [{"item","reason"}]}
```

### `engine.py` — `Memory` additions / shape
```python
def register_policy(self, node_type: str, policy) -> None
def nearest(self, vec, type=None, project=None, k=1, threshold=0.0) -> list[tuple[str, float]]  # factored from recall()
def get_node(self, id: str) -> dict | None
def update_node(self, id: str, body=None, meta=None) -> None
# index(): redact → policy.embedding_text(node) → embed → policy.find_candidate → policy.merge | insert
# policy protocol (registered per type):
#   embedding_text(node) -> str ; find_candidate(store, node, project) -> str|None ; merge(store, existing_id, new_node) -> MergeOutcome
```

### `lesson.py`
```python
class MergeOutcome(Enum): FAST_PATH, MERGED, NOT_A_DUP
class LessonPolicy:
    def __init__(self, embedder, chatter): ...
    def embedding_text(self, node) -> str               # node["meta"]["when"]
    def find_candidate(self, store, node, project) -> str | None
    def merge(self, store, existing_id, new_node) -> MergeOutcome
LESSON_DEDUP_THRESHOLD = 0.92 ; THEN_IDENTICAL_THRESHOLD = 0.95 ; MAX_THEN_ITEMS = 6
```

---

## Task Structure

Each task is a component-named heading — `### Task N: [Component]` — that delivers one file/unit. Its work is broken into `- [ ]` checkbox **steps** (the executor's tracking tokens), followed by **Spec** (the unit it implements) and **Gate** (a runnable acceptance check that must pass before the next task).

Design units with clear boundaries and well-defined interfaces; each file has one clear responsibility. Prefer smaller, focused files over large ones that do too much — you reason best about code you can hold in context at once, and your edits are more reliable when files are focused. Files that change together live together — split by responsibility, not by technical layer. Tasks are ordered by dependency; each builds on the prior unit's landed interface and is self-contained (no task requires reading another's diff to understand its own scope).

In existing code, follow established patterns — don't unilaterally restructure large files. If a file you're already modifying has grown unwieldy, planning a split is reasonable (call it out as its own task).

## 3. Tasks

### Task 0: Data purge  *(manual, no code)*

- [ ] `rm ~/.specloop/memory.db ~/.specloop/audit.jsonl` (recreated fresh: schema lesson-only on next open; audit empty on next `session_start`).
- **Spec:** [07 §Existing data](units/07-migration.md#existing-data--purged-not-migrated).
- **Gate:** both files gone; `mem stats` (after task 5) recreates an empty lesson-only DB without error.

### Task 1: `scripts/status.py`  *(CREATE)*

- [ ] Create `scripts/status.py` — pure taxonomy + functions per §2 (no I/O, no imports of engine/semantic).
- [ ] Create `tests/test_status.py` — covers `initial_lesson_status`, `promote` (incl. the `≥2` threshold + `void` never reaching it), `merged_status` table, `authority_rank` ordering.
- **Spec:** [04](units/04-status.md).
- **Gate:** `python3 tests/test_status.py` green.

### Task 2: `scripts/semantic.py`  *(MODIFY)*

- [ ] Add `extract_lessons` (system prompt per [02 §Prompt contract](units/02-extraction.md#prompt-contract-system)); **raises** on unparseable JSON (the write path maps to `error`).
- [ ] Add `merge_thens` (prompt per [03 §merge_thens prompt contract](units/03-dedup-merge.md#the-merge_thens-prompt-contract)).
- [ ] **Delete** `summarize_session` + `_SESSION_SYSTEM`; reuse existing `Chatter`/`parse_json`/`truncate`.
- [ ] Update `tests/test_semantic.py` — extract schema, `void⇒[]`, cap ≤5, garbage-JSON⇒raises; merge `same_trigger` true/false, union/dedupe, authority pick, `dropped` populated.
- **Spec:** [02](units/02-extraction.md), [03](units/03-dedup-merge.md).
- **Gate:** `python3 tests/test_semantic.py` green.

### Task 3: `scripts/engine.py`  *(MODIFY)*

- [ ] Add `register_policy`, `nearest` (factor the cosine scan out of `recall` — `recall` becomes `nearest` + decorate), `get_node`, `update_node`; rewrite `index()` to the §2 dispatch flow; add `"when","then"` to `_META_REDACT_KEYS`.
- [ ] **Remove** M0/M0+ dead code: `_find_dup`, `_maybe_promote`, `_STATUS_RANK`, `_migrate`, `_backfill_prompt_vectors`, `_DEDUP_TYPES`, `link()`, `history()`, `DEDUP_THRESHOLD`; drop `embedding_prompt` **and** `root_prompt_id` from `_SCHEMA`.
- [ ] Update `tests/test_engine.py` — drop history/link + M0 dedup tests; add registry/`nearest`/helpers with a stub policy.
- **Spec:** [01](units/01-storage.md), [07 supersession](units/07-migration.md#supersession--what-happens-to-the-live-system).
- **Gate:** `Memory(":memory:", HashEmbedder())`; stub-policy asserts `index` calls `embedding_text`→embed→`find_candidate`→`merge`/insert and `NOT_A_DUP` inserts; `nearest` ranking correct; `recall` unchanged; `get_node`/`update_node` round-trip. `python3 tests/test_engine.py` green.

### Task 4: `scripts/lesson.py`  *(CREATE)*

- [ ] Create `scripts/lesson.py` — `LessonPolicy` per §2 + [03 §Algorithm](units/03-dedup-merge.md#algorithm-the-full-flow-per-new-lesson): `find_candidate` via `store.nearest(..., threshold=LESSON_DEDUP_THRESHOLD)`; **fast path** (THEN-vector cosine ≥ `THEN_IDENTICAL_THRESHOLD` → bump `confirmed_by`/`merge_count`, `promote`, no LLM); **arbiter** (`merge_thens`, `same_trigger=False` → `NOT_A_DUP`); **reconcile** (update existing in place: body, `meta.then/status/confirmed_by/merge_count/provenance`; `MAX_THEN_ITEMS` cap via `dropped`). Uses `status.py`; stable id.
- [ ] Create `tests/test_lesson.py` — no-candidate→insert; fast-path bumps+promotes; `same_trigger=False`→new node; reconcile→id stable, body changed, `provenance` appended, `dropped` honoured; authority keeps higher-status side; cap drops lowest-value-with-reason.
- [ ] Add a multi-session integration case to `tests/test_lesson.py` (in-memory, `HashEmbedder`, per [07 §Test plan](units/07-migration.md#test-plan)): same trigger recurs → 2nd write fast-path-merges; 3rd with a *different* THEN → LLM-merge; a different-trigger lesson → stays a separate node.
- **Spec:** [03](units/03-dedup-merge.md), [04](units/04-status.md).
- **Gate:** mock chatter; in-memory store + `HashEmbedder`. `python3 tests/test_lesson.py` green.

### Task 5: `scripts/mem.py`  *(MODIFY)*

- [ ] Rewrite `cmd_recap`: build chatter, `m.register_policy("lesson", LessonPolicy(m.embedder, chatter))`; call `extract_lessons`; `void`→audit `WRITE{void}`, exit; per lesson build node (`body` = `WHEN {when} THEN {then}`, `meta` per [01](units/01-storage.md) with `status=status.initial_lesson_status(session_status)`, `confirmed_by=[session]`, `merge_count=0`) and `m.index(node)`; per-lesson try/except → skip+audit; audit `write`/`merge` per [05 §Audit events](units/05-write-path.md#audit-events-additions); print the new JSON summary.
- [ ] **Remove** `cmd_history`, `cmd_link` (+ subparsers), the `recap --no-summary` flag, the `summarize_session` import, `body_for` if unused.
- [ ] Add `tests/test_mem.py` (mock `extract_lessons`+`merge_thens`): node count = `len(lessons)`−merges; `void`/extractor-raise⇒0 nodes+audit; per-lesson skip⇒partial; JSON output shape.
- **Spec:** [05](units/05-write-path.md).
- **Gate:** `python3 tests/test_mem.py` green (or subprocess vs an in-memory DB).

### Task 6: Read-path verification  *(NO code change)*

- [ ] Confirm `recall` returns lesson nodes (only type) ranked by `cosine(embed(query), embed(when))`; `formatContext` renders `WHEN…THEN…` bodies; the extension's `before_agent_start`/`session_shutdown` hooks need no edits.
- **Spec:** [06](units/06-read-path.md).
- **Gate:** a scripted recall against hand-seeded lesson nodes returns them ranked; the formatted block matches the [06 example](units/06-read-path.md#formatcontext--rendering-rules). `git diff extensions/` still empty.

### Task 7: Smoke test  *(real model, fresh DB)*

- [ ] With `MISTRAL_API_KEY` set + the post-task-0 empty DB: run a synthetic `mem recap` (canned digest) → confirm N lesson nodes written with correct meta/embedding.
- [ ] `mem recall "<a situation>"` → confirm the matching lesson surfaces at high score.
- [ ] A second recap on the *same* trigger → confirm fast-path/merge (count stable, `confirmed_by`/`merge_count` advanced).
- **Spec:** end-to-end [README §Data flow](README.md#end-to-end-data-flow).
- **Gate:** lessons persisted; situation recall hits; a repeat trigger merges rather than duplicates; audit log shows `write`/`merge` events.

---

## 4. Done criteria

- All five test files green (`test_status`, `test_semantic`, `test_engine`, `test_lesson`, `test_mem`): `python3 tests/test_*.py`.
- Task-7 smoke passes against the real model.
- DB is lesson-only (one node type); no `embedding_prompt`/`root_prompt_id` columns; no `recap` nodes.
- Audit log shows the new `write`/`merge` event shapes; old file purged.
- Extension source byte-identical to pre-M2 (read path untouched) — `git diff extensions/` empty.
- **Validation (non-blocking):** recall bench per [07 §Test plan](units/07-migration.md#test-plan) — rebuild the corpus as `(situation → correct lesson)` pairs and re-run Recall@k/MRR; the lesson model should beat the recap baseline on situation queries (the proof the design pays off).
- Open items from [`units/07 §Out of scope`](units/07-migration.md#out-of-scope-deferred--v2) remain unimplemented (v2).

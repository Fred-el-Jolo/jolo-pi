# Unit: Write path  *(session-end orchestration)*

> Files: `mem.py` (`cmd_recap`) + `extensions/specloop-pi/extension/mem.ts`
> (`recapAsync`).

## What it does

Glue. On session quit it builds a digest, calls the Extractor once, then indexes
each emitted lesson — letting the Store's dedup/merge policy do its per-lesson
work. It owns **none** of the logic: extraction is [02](02-extraction.md),
dedup/merge is [03](03-dedup-merge.md), status is [04](04-status.md). It only
sequences them, handles failure, and writes the audit.

## End-to-end flow

```
session_shutdown{reason:"quit"}                       [extension: builds digest]
  └─ recapAsync(initial_prompt, digest)               [fire-and-forget, detached]
       └─ mem recap --initial-prompt <ip>             [digest on stdin]
            1. extract_lessons(chatter, ip, digest) → {status, lessons}     [02]
                 status == "void"   → audit WRITE{void}, exit (no nodes)
                 raises (tech err) → audit WRITE{error}, exit (no nodes)
            2. for each lesson in lessons:
                 node = {type:"lesson", body: render(when,then),
                         meta:{when,then,status:initial(lesson,session),
                               session, confirmed_by:[session], merge_count:0},
                         /* embedding computed by Store from meta.when */}
                 id = store.index(node)                                     [01→03]
                       (index may INSERT, fast-path-merge, or LLM-merge in place)
                 record outcome per lesson (new | merged:fast | merged:llm | not-a-dup)
            3. audit WRITE per lesson + MERGE where applicable
            4. print JSON summary; exit 0
```

## Failure handling (graceful degradation — the core invariant)

Memory must **never** break the agent's run. Every model/embed call is
best-effort:

| failure | behaviour |
|---|---|
| Extractor raises (API/timeout/parse) | `status=error`, **write no nodes**, audit `WRITE{error}`. The session simply isn't memorised. |
| A per-lesson index/merge raises | skip that lesson, continue the rest; audit the skip. One bad lesson doesn't lose the others. |
| `void` (model verdict) | not a failure — write nothing, audit `WRITE{void}`. |

Note the deliberate difference from M0: M2 writes **no error-flagged nodes**. An
extraction failure means there are no lessons to store; an error node would be
noise. (M0 wrote `error`-flagged recap nodes to avoid losing the session; M2
loses nothing because the audit log already records that the session ran.)

## Why fire-and-forget

`recapAsync` spawns a **detached**, `unref()`'d process so it survives pi exiting
mid-write and doesn't keep the event loop alive. Consequence: a crash during
recap is invisible to the user beyond an audit line — acceptable, by design.

## Interface (CLI)

```
echo '<digest-json>' | mem recap --initial-prompt "<first prompt>" [--json]
```
`--json` output (new shape):
```json
{"session_status": "done",
 "lessons": [{"id": "…", "status": "confirmed", "outcome": "merged:llm|merged:fast|new|not-a-dup"}]}
```
`--no-summary` (the offline/index-from-digest escape hatch) is **removed** — it
was an M0 testing affordance with no lesson analogue.

## Audit events (additions)

| event | fields | when |
|---|---|---|
| `write` | `type=lesson, id, outcome, status, session` | every lesson indexed |
| `merge` | `id, mode=fast\|llm, same_trigger (llm only), dropped[], provenance_count` | a dedup merged |
| `write{void}` / `write{error}` | — | nothing learned / tech failure |

(The existing `recall`/`lifecycle` events are unchanged.)

## What it depends on

Extractor ([02](02-extraction.md)), Store ([01](01-storage.md), which itself
delegates to [03](03-dedup-merge.md)), Status ([04](04-status.md)), Audit
(`audit.py`, existing). The extension half depends only on shelling out to `mem`.

## Testability

Mock the Extractor (canned `{status, lessons}`) and the Merger (canned
`merge_thens`), drive `cmd_recap` against an in-memory store, assert: node count
matches `len(lessons)` minus merges, `void`⇒0 nodes + audit line, extractor-raise⇒
`error` + 0 nodes, per-lesson-skip⇒partial write + audit, JSON output shape.

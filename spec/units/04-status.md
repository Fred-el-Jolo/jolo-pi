# Unit: Status taxonomy + authority  *(pure — no I/O)*

> Consumed by: [02-extraction](02-extraction.md), [03-dedup-merge](03-dedup-merge.md),
> and (optionally, v2) [06-read-path](06-read-path.md) ranking.

## What it is

A small, fixed vocabulary of statuses plus the rules that (a) translate a session
outcome into a lesson's initial status, (b) resolve contradictions during merge,
and (c) promote a lesson as it gets re-confirmed. It is a **pure taxonomy** — no
functions with side effects; the consuming units apply it.

## Two layers

**Session-level** (emitted by the Extractor, describes the *session* that produced
the lessons):

| status | meaning | effect on lessons |
|---|---|---|
| `done` | goal accomplished | each lesson starts `confirmed` |
| `partial` | partly done / drifted | each lesson starts `tentative` |
| `failed` | the work failed | each lesson starts `tentative` |
| `void` | nothing durably reusable | **no lessons emitted** (write nothing) |

`error` is **engine-only** — never emitted by the model; set by the write path
when the extraction call fails. ⇒ no nodes, audit only (graceful degradation).

**Lesson-level** (stored on the node, *evolves* via re-learning/merging):

| status | rank | meaning |
|---|---|---|
| `confirmed` | 3 | validated (from a `done` session, or promoted by confirm-count) |
| `tentative` | 2 | observed but not yet validated (from `partial`/`failed`) |
| `contested` | 1 | a merge left an unresolved contradiction |

## Initial status (write time)

`lesson.status = confirmed if session.status == done else tentative`. `void`
never reaches here. Stored on every new lesson node.

## Confirm-count → promotion

Each time the **fast path** ([03](03-dedup-merge.md) §2) re-learns an identical
lesson from a new session, `confirmed_by` grows. Promotion rule:

```
if status == tentative and len(confirmed_by) >= CONFIRM_TO_CONFIRMED (default 2):
    status = confirmed
```

So a lesson seen once from a failed session, then re-learned from a later
session, trends to `confirmed`. `confirmed_by` holds **distinct session ids**
(dedup), so re-running the same session doesn't inflate it.

## Authority ordering  *(conflict resolution during merge)*

When two THENs contradict, the Merger keeps the higher-authority side (and the
merged `status` reflects the outcome):

1. **status rank** — confirmed > tentative > contested
2. **confirm-count** — more distinct sessions wins
3. **recency** — newer wins (an old rule may be stale)

### Merged-status rules

| sources | merged status |
|---|---|
| all `confirmed` | `confirmed` |
| mixed, but **no contradiction** resolved | `tentative` |
| a contradiction was **kept unresolved** | `contested` |

`contested` is intentionally rare and surfaces a real signal: the memory is
unsure, so recall can deprioritise or flag it (v2).

## What it depends on

Nothing. It is data + rules. Kept in one place so the three consumers can't
diverge on what "confirmed" means.

## Testability

Pure functions / a small table — unit-test the translations and the merged-status
table directly. No DB, no model.

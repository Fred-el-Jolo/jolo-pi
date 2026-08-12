# Memory Model  *(core schema)*

A flat store of **one node type**. No ontology, no provenance graph, no error/spec/plan/step nodes — those were the elaborate model; this is the minimal one. Just one recap per session.

## The `recap` node  *(the only type)*

One per session. Created on session quit. This is both the memory's root and its content.

```
id            : uuid
type          : "recap"
created       : iso8601
project       : <repo/path scope>          # see open-questions §4
body          : the recap summary (what happened; folds in subject-drift)
embedding     : vector(body)               # the recall key
meta
  status      : done | partial | failed
  summary     : the raw summary text (== body)
  initial_prompt : the session's first user prompt (subject anchor)
  session     : <pi session id>            # when SPECLOOP_SESSION is set
```

## Recall

| When | Query | Returns |
|---|---|---|
| session start (first prompt) | `recall(prompt)` | top-k recaps by summary similarity |

Token budget for injected recall is bounded (see [open-questions.md](open-questions.md) §6) — recall stays cheap.

## Dedup-on-write

Before indexing a new recap, check similarity to existing recaps in scope; if ≥ ~0.98 to an existing one, merge instead of duplicating. Prevents repeated-identical-session pollution. (open-questions §8.)

## Persistence

- **Auto-written by the extension** (`specloop-pi`): `recap` (on session quit, via `mem recap` → `engine.index`).
- When `SPECLOOP_SESSION` is set (by the extension), the recap's `meta.session` records the pi session that produced it — the join key for the audit log (`audit.py`).

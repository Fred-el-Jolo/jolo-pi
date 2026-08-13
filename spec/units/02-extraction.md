# Unit: Extractor  *(session → 0–5 lessons)*

> File: `lib/specloop-core/scripts/semantic.py` — `extract_lessons()` (+ chat infra).

## What it does

The single LLM call at session end. Given the session's initial prompt and a
compact digest (later prompts + tool errors), it returns **0–5 reusable lessons**
as structured `{when, then}` objects, plus a **session status**. It is the only
producer of lesson content. It never touches the store, the embeddings, or the
network embedder — only a chat model.

## How to use it (interface)

```python
def extract_lessons(chatter: Chatter, initial_prompt: str, digest_json: str) -> dict:
    """Returns {'status': str, 'lessons': [{'when': str, 'then': str}, ...]}."""
```

- `status` ∈ `{done, partial, failed, void}` — a **session-level** outcome that
  becomes each emitted lesson's *initial* status (see [04-status](04-status.md)).
  `void` ⇒ `lessons == []` (write nothing).
- `lessons[i].when` — the **trigger/situation**; must be specific enough to
  recognise the situation (it is the retrieval key).
- `lessons[i].then` — the **takeaway**: an action to take, a fact that holds, or
  a verdict reached. One shape, intentionally flexible.
- **Structured output is mandatory** — the split into `when`/`then` fields is
  *required* by key/payload separation: the Store embeds `when` alone, and the
  Merger needs `when`/`then` isolated to do its job. Flat `"WHEN x THEN y"`
  strings are not accepted.

`{error}` is **not** a value this function returns; it is set by the **write
path** when the call raises (technical failure) — see [05-write-path](05-write-path.md).

## Prompt contract (system)

> You extract durable, reusable lessons from a completed coding-agent session.
> Inputs: the session's INITIAL prompt, the later prompts, and the tool errors.
> Answer: **what was LEARNT that is worth remembering for future similar
> situations?** Return STRICT JSON only:
> `{"status": "done"|"partial"|"failed"|"void", "lessons": [{"when": str, "then": str}]}`.
>
> - **status** — `done`=goal accomplished; `partial`=partly done or drifted;
>   `failed`=the work failed; `void`=nothing durably reusable was learnt.
> - **lessons** — 0 to 5 rules.
>   - `when` = the situation/trigger that should make future-you recall this. Be
>     specific (the situation, not the fix).
>   - `then` = the takeaway — an *action* to take, a *fact* that holds, or a
>     *verdict* reached.
> - **Ground every rule in the session's actual work/errors.** Do not invent
>   plausible-sounding generalities. If a rule isn't evidenced by the transcript,
>   don't emit it.
> - **Fewer sharp rules beats more mediocre ones.** Soft target 3, hard cap 5.
>   If nothing is genuinely reusable, return `{"status":"void","lessons":[]}`.

The user message is `Initial prompt:\n{ip}\n\nSession digest (JSON):\n{digest}`
(digest truncated to ~6000 chars, as today). Parsing uses the existing
`parse_json`; an **unparseable** reply (the model broke the JSON contract) is a
hard failure — the Extractor **raises**, and the write path records `error` and
writes nothing ([05](05-write-path.md)). A well-formed `{status, lessons:[]}` is
*not* an error — that's the model's own `void`/`partial` verdict.

## The cap: 0–5 (soft target 3)

- **0 allowed** — many sessions (chat, exploration, one-off debugging) yield
  nothing reusable; that's `void`, and the cost of a quota-driven fake rule is
  higher than the cost of an empty write.
- **Hard cap 5, soft target 3** — the cost of a dropped good lesson is high
  (it's gone from memory); the cost of an extra node is ~nil. So the *cap* is
  generous (5) but the *prompt* biases toward curation (target 3) to suppress
  padding. The cap is a **ceiling, not a target.**

## Anti-hallucination

The dominant risk of free-form extraction is rules that *sound* right but weren't
earned by the session. Two controls: (1) the prompt's grounding clause above;
(2) the write path can later cross-check a lesson against the digest if precision
demands it (deferred — not in v1).

## What it depends on

- A **Chatter** (`chatter.complete(system, user)→str`): `make_chatter("mistral")`
  by default; `openai`/`zai` registered. Model is the cheap recap model, not the
  agent's. Overridable via `SPECLOOP_CHAT_PROVIDER` / `SPECLOOP_CHAT_MODEL`.
- `parse_json` (existing, in this file).

## Testability

Inject a fake `Chatter` whose `.complete()` returns canned JSON; assert: schema
conformance, `void`⇒empty list, cap enforced, garbage-JSON⇒raises (signals
`error` to the write path).
No network. (See existing `test_semantic.py` pattern.)

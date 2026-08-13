# Unit: Read path  *(recall + context formatting)*

> Files: `engine.py` (`recall`) + `extensions/specloop-pi/extension/mem.ts`
> (`start`, `formatContext`) + `extension.ts` (`before_agent_start`).

## What it does

On the session's **first prompt only**, embed it, find the top-k similar lessons,
and inject the relevant ones into the system prompt as compact rules. Read-only —
**nothing is indexed here.** Mechanically this is almost unchanged from M0; the
only differences are what the hits *contain* (WHEN/THEN rules, not prose) and how
they're rendered.

## How to use it (interface)

```python
# engine.py — unchanged signature
recall(query, k=5, scope="global", type=None) -> list[hit]   # hit has _score, body, meta
```
```ts
// mem.ts — unchanged signature
start(cfg, prompt, session) -> { recalls: RecallHit[] }
formatContext(cfg, recalls) -> string     // the injected block, "" if nothing relevant
```

The extension's `before_agent_start` hook:
1. calls `start(prompt)` (gated to fire once per session — `recalledThisSession`),
2. filters `recalls` to `_score >= minScore`, top 3,
3. renders via `formatContext`, appends to the system prompt,
4. notifies if hits were injected (when `SPECLOOP_NOTIFY`).

## Recall semantics (unchanged, restated for clarity)

`recall` redacts the query, embeds it, ranks all (optionally type-filtered)
nodes by `cosine(embed(query), node.embedding)`, returns top-k with `_score`.
Because lesson `embedding` holds the **WHEN vector**, ranking is
**situation↔situation** — exactly the alignment M2 exists to provide.

> **Type:** `lesson` is the only node type, so recall returns lessons by
> default. The `type` filter stays as a general feature (future types) but needs
> no special defaulting.

## `formatContext` — rendering rules

```md
## related past work (auto-recalled — consider but verify)
- (0.81) WHEN deploying a Jekyll site to GitHub Pages THEN resolve dist/CNAME + dist/robots.txt before the action runs
- (0.74) WHEN booting a Pi from USB THEN program_usb_boot_timeout=1 must be set in bootconfig
```

Rules: top-3 hits with `_score >= minScore`; each clipped to a char budget
(`SPECLOOP_MAX_CHARS_M0`, default 2400); the block is `""` (nothing injected) if
no hit clears the threshold — quiet sessions stay quiet.

## Carried over from M0

- **Once-per-session gate** (`recalledThisSession`), reset on every
  `session_start` (startup/new/resume/fork/reload).
- **Health probe** on `session_start` (python3 + `mem.py` + db); first hard
  failure disables recall for the session (audit + notify).
- **Token cap**, **manual `/specloop recall <query>`** command.

## Deferred (v2)

- **Ranking boost from confirm-count/status** — confirmed/often-re-learned rules
  could rank above tentative ones at equal cosine. Not in v1 (keep ranking pure
  cosine; let the injected block's `(score)` + the rule's own grounding carry it).
- **Type-filtered recall UI** in the TUI.

## What it depends on

Store ([01](01-storage.md)) + an Embedder (via the CLI). The extension depends
only on shelling out to `mem start`.

## Testability

Feed `recall` canned nodes (in-memory store + `HashEmbedder`); assert ordering +
`_score`. Feed `formatContext` canned hits; assert the rendered block, the
`minScore`/top-3 filtering, and the empty-when-nothing-relevant case.

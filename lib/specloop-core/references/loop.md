# The loop  *(two touches — recall at start, recap at end)*

```
START  recall    on the session's FIRST prompt: search memory for similar past recaps,
                 inject the hits into the system prompt. Read-only — nothing indexed.
… session runs … (no memory ops in between)
END    recap     on session QUIT: a cheap model summarizes the session — initial prompt,
                 how the subject evolved, the errors hit — and writes one recap node.
```

That's it. No mid-session recall, no per-error capture, no per-turn writes. Two model-class operations per session: one embedding (start) + one chat (end).

## START — recall (first prompt only)

`recall(prompt)` → surface the top-k most similar past recaps as compact one-liners. *"Last time you worked on something like this, here's what happened."* Token budget: see [open-questions.md](open-questions.md) §6. Driven automatically by the extension's `before_agent_start` hook, gated to fire exactly once per session.

## END — recap (on quit)

On `session_shutdown{reason:"quit"}`, the extension builds a digest from the session transcript (initial prompt + later user prompts + tool errors) and runs **one** chat call that returns `{summary, status}`. The summary prose accounts for subject-drift — if the work wandered from the initial prompt, that's folded into the recap so future recall reflects the real outcome, not the original ask. Written as a single `recap` node (dedup-on-write). Driven automatically by the extension's `session_shutdown` hook.

## Memory CLI — `scripts/mem.py`

The extension drives both touches through the CLI (disk-backed; one sqlite file at `$SPECLOOP_DB` or `~/.specloop/memory.db`; mistral embeddings by default).

| Touch | Command |
|---|---|
| **START** (recall) | `mem start "<prompt>" -k 5 --json` → `{recalls: [...]}` (read-only) |
| **END** (recap) | `echo '<digest>' \| mem recap --initial-prompt "<p>" --json` → `{recap_id, status, merged}` |
| manual recall | `mem recall "<query>" --json` → top-k similar recaps |
| manual index | `mem remember "<text>" --type recap` |
| expand | `mem history <id> --json` → a node + everything linked to it |
| audit (use) | `mem audit [--event recall\|write\|lifecycle] [--session …] [--tail N]` |
| bench real data | `mem export <dir> --scaffold-queries` → live DB to corpus format; then `bench.py --corpus <dir>` (replace scaffold queries with real labels) |

Env: `SPECLOOP_PROVIDER` (default `mistral`), `MISTRAL_API_KEY` (or `ZAI_API_KEY` / `OPENAI_API_KEY`), `SPECLOOP_CHAT_PROVIDER`/`SPECLOOP_CHAT_MODEL` (for the recap), `SPECLOOP_DB`, `SPECLOOP_PROJECT` (auto-detected from git). `--embedder hash` for offline/tests. **Memory is user-wide:** one DB at `~/.specloop/memory.db`; `recall` defaults to **global** (searches everything you've stored, across all repos/projects). `project` is auto-detected from git and is *only* used by the opt-in `--scope local` ("just this repo"). (`mem` is shorthand for `python3 specloop-core/scripts/mem.py`.)

# specloop-pi  *(pi extension — minimal wired-in memory)*

> **Not a skill.** This is a [pi extension](https://github.com/earendil-works/pi-coding-agent) (TypeScript, loaded via `jiti`) that wires the [`specloop-core`](../../lib/specloop-core) memory engine into two pi lifecycle hooks. **Two touches per session, nothing in between** — recall on the first prompt, recap when the session quits. All automatic; the agent never has to remember to ask.

## What it does

| Hook | Fires | What happens |
|---|---|---|
| `session_start` | every session | cheap health probe (python3 + `mem.py` + db); resets per-session recall state. No memory op. |
| `before_agent_start` | **first prompt only** (gated) | recall similar past recaps → inject into the **system prompt** for the run (transient, not stored). **Read-only — nothing is indexed here.** |
| `session_shutdown` | `reason === "quit"` only | build a digest from the session transcript (initial prompt, later prompts, tool errors) → one background model call → write **one recap node**. |

That's the entire surface. No mid-session recall, no per-error capture, no per-turn writes.

## The two sides

- **Read side (recall) — fully automatic, once.** On the session's first prompt, embed it, find the top-k similar past recaps, inject the hits above threshold into the system prompt. Pure cosine lookup; no model call on the read side (embeddings live in the engine).
- **Write side (recap) — one model call, at quit.** The recap is produced by a **dedicated cheap model** (default mistral) that sees the initial prompt + the session digest (how the subject evolved + the errors hit). It writes a single recap node whose summary folds subject-drift into the prose — no separate label. If the session did nothing meaningful, it writes nothing useful and dedup-on-write keeps the store clean.

**The extension never does HTTP.** Embeddings AND chat both live in the python engine (`engine.py` + `semantic.py`), behind the `mem.py` CLI, sharing one model config (default: mistral). This module only shells out, formats the recall block, builds the digest, and injects/flushes.

## Install / load

From this repo (dev), load it directly:

```bash
pi -e /home/jolo/dev/skills/specloop-pi/extension/extension.ts
```

Or drop a symlink in `~/.pi/agent/extensions/`, or install as a pi package (see `package.json`). It auto-locates `mem.py` at `../../lib/specloop-core/scripts/mem.py` relative to itself; override with `SPECLOOP_MEM` when installed elsewhere.

**Graceful degradation:** the first hard failure (bad path, missing key, timeout) disables recall for the session — memory must never break your run. `/specloop off` disables manually.

## Configuration (env)

| Var | Default | Purpose |
|---|---|---|
| `SPECLOOP_ENABLED` | `1` | master switch |
| `SPECLOOP_MEM` | `../../lib/specloop-core/scripts/mem.py` | path to the engine CLI |
| `SPECLOOP_PYTHON` | `python3` | python binary |
| `SPECLOOP_PROVIDER` | `mistral` | **embedding** provider (`mistral\|zai\|openai\|hash`) |
| `SPECLOOP_CHAT_PROVIDER` | `mistral` | **chat** provider for the recap summary |
| `SPECLOOP_CHAT_MODEL` | provider default (`mistral-small-latest`) | chat model override |
| `MISTRAL_API_KEY` | — | required for mistral embeddings + chat (same key) |
| `SPECLOOP_K` | `5` | recall top-k |
| `SPECLOOP_MIN_SCORE` | `0.4` | min cosine to inject a recall |
| `SPECLOOP_MAX_CHARS_M0` | `2400` | recall injection budget (chars) |
| `SPECLOOP_NOTIFY` | `0` | surface recalls/notices via `notify` |
| `SPECLOOP_AUDIT` | `~/.specloop/audit.jsonl` | audit-log path (`0`/`off`/`false` disables) |
| `SPECLOOP_SESSION` | *(set by the extension)* | pi session id, stamped on every node + audit line (the memory↔session join key) |
| `SPECLOOP_REDACT` | `1` | scrub high-precision secrets at the storage boundary, *before* embedding/persisting. Best-effort. |
| `SPECLOOP_SCOPE` | `global` | recall scope. `local` = current repo only. |

`SPECLOOP_PROVIDER=hash` runs fully offline (lexical embeddings — lower recall quality, useful for tests/air-gapped). With no chat key set, the recap degrades to storing the initial prompt as the body (best-effort) rather than failing.

## Commands

- `/specloop` — status (on/off, k, thresholds, mem path).
- `/specloop stats` — node counts by type.
- `/specloop recall <query>` — manual similarity search.
- `/specloop off` — disable for this session.

## Auditing

Memory **state** lives in the sqlite DB (`mem history`, `mem export`). Memory **use** — what was recalled/injected, what was written, enable/disable, recap queued — is logged to `~/.specloop/audit.jsonl` by two writers:

- the **extension** logs `recall` (query, hits, scores, whether injected, chars) and `lifecycle` (enabled/disabled/recap_queued + reason);
- **`mem.py`** logs `write` (every node indexed, incl. merged/dedup).

Every line is stamped with `ts`, `session` (the pi session id), and `project`. Inspect:

```bash
mem audit                          # human-readable tail
mem audit --event recall           # only recalls/injections
mem audit --session <pi-session>   # one pi session's memory activity
mem audit --tail 50 --json         # machine-readable
```

## File map

```
specloop-pi/
├── README.md                 # this file
├── package.json              # pi-package manifest (extension only)
└── extension/
    ├── extension.ts          # entry: 3 hooks (session_start / before_agent_start / session_shutdown) + /specloop
    └── mem.ts                # config + mem.py bridge + recall formatting + digest builder (pure)
```

Engine + recap summarizer live in [`../../lib/specloop-core/scripts/`](../../lib/specloop-core/scripts) (`engine.py`, `semantic.py`, `mem.py`).

## Verification done

- `python3 specloop-core/tests/test_engine.py` (9) + `test_semantic.py` (8) + `test_audit.py` (5) + `test_redact.py` (16) + `test_http.py` (5) — green.
- CLI end-to-end (`start` recall → `recap` write → dedup-on-write) offline with the `hash` embedder — green.
- `tsc --strict` against pi's type definitions — clean.
- Extension logic driven through a mock pi: first-prompt recall injects, second prompt is a no-op (once-per-session gate), `session_shutdown{quit}` writes a recap, `session_shutdown{reload}` does not (reason-gated), and `buildDigest` extracts the initial prompt + drift prompts + tool errors correctly — all green.

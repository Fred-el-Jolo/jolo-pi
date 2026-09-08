# specloop-pi  *(pi extension — minimal wired-in memory)*

> **Not a skill.** This is a [pi extension](https://github.com/earendil-works/pi-coding-agent) (TypeScript, loaded via `jiti`) that wires the [`specloop-core`](../../lib/specloop-core) memory engine into two pi lifecycle hooks. **Two touches per session, nothing in between** — recall on the first prompt, recap when the session quits. All automatic; the agent never has to remember to ask.

## What it does

| Hook | Fires | What happens |
|---|---|---|
| `session_start` | every session | cheap health probe (python3 + `mem.py` + db); resets per-session recall state. No memory op. |
| `before_agent_start` | **first prompt only** (gated) | recall similar past recaps → **show the candidates as a checkbox list — nothing is in LLM context yet** → insert ONLY the checked ones as a persistent session message (visible once in the transcript, in context for the whole session). **Read-only — nothing is indexed here.** |
| `session_shutdown` | `reason === "quit"` only | build a digest from the session transcript (initial prompt, later prompts, tool errors) → one background model call → write **one recap node**. |

That's the entire surface. No mid-session recall, no per-error capture, no per-turn writes.

## The validation gate ("no magic")

Memory systems that silently insert stuff you can't control are annoying. specloop's read side is **gated**: on the first prompt, the candidate recalls are shown as a **checkbox list** (`↑↓` move · `space` toggle · `e` compact · `a` all/none · `enter` insert checked · `esc` insert none) and **only the checked entries are inserted**. Bodies render **fully, word-wrapped, at any terminal width** — on a phone-sized terminal you still see every word of what you're approving, never a 3-word ellipsis stub (via a proper reusable TUI component, `ExpandableText` — pi-tui's closest builtin, `TruncatedText`, is truncate-only: no expand, no wrap). `e` compacts the item under the cursor to a one-line preview, and back. The list is rendered in the terminal only — nothing enters LLM context before you confirm, by construction (injection happens solely through the handler's return value, built from the checked subset).

The insert is a **persistent session message** (`customType: "specloop-recall"`), not a system-prompt tweak:

- displayed **once**, compactly, at its position in the transcript (expand to see the exact text the LLM gets) — it never re-renders on later messages;
- sent to the model on **every turn** for the rest of the session (unlike the old systemPrompt override, which silently vanished after the first run); it sits early in the history so provider prompt-caching covers it, and compaction folds it away like any old message;
- survives `/resume`.

Fail-safes: `esc` inserts nothing (no re-asking this session); the recall spawn is hard-capped (`SPECLOOP_RECALL_TIMEOUT_MS`); the picker can auto-skip after a deadline for unattended runs (`SPECLOOP_PICK_TIMEOUT_MS`, default off); any picker/UI error fails **open** (auto-include, audited as `picker_error`); modes without a UI degrade sensibly — RPC gets a single confirm dialog, `print`/`json` auto-include.

## The two sides

- **Read side (recall) — validated, once.** On the session's first prompt, embed it, find the top-k similar past recaps, show the hits above threshold as a checkable list, and insert the checked ones as a persistent session message (see [the validation gate](#the-validation-gate-no-magic)). Pure cosine lookup; no model call on the read side (embeddings live in the engine).
- **Write side (recap) — one model call, at quit.** The recap is produced by a **dedicated cheap model** (default mistral) that sees the initial prompt + the session digest (how the subject evolved + the errors hit). It extracts **lessons** (`WHEN <situation> THEN <action>`); each is indexed with dedup-on-write. Confirmation is **evidence-based**: every lesson starts `tentative` and promotes to `confirmed` only via ≥2 *distinct sessions* re-learning it **or** ≥3 distinct calendar days (`meta.learned_days`) — the day-bar exists because heavily-resumed pi sessions re-learn under one session id. Neither the extractor's `done` verdict nor the merge arbiter's status suggestion can confirm anything. If the session did nothing meaningful, it writes nothing useful and dedup-on-write keeps the store clean.

**The extension never does HTTP.** Embeddings AND chat both live in the python engine (`engine.py` + `semantic.py`), behind the `mem.py` CLI, sharing one model config (default: mistral). This module only shells out, formats the recall block, builds the digest, and injects/flushes.

## Install / load

From this repo (dev), load it directly:

```bash
pi -e /home/jolo/dev/jolo-pi/extensions/specloop-pi/extension/extension.ts
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
| `SPECLOOP_CONFIRM` | `ask` | recall validation: `ask` = show the checkbox picker, insert only checked entries; `auto` = old behavior (insert all hits, no prompt) |
| `SPECLOOP_RECALL_TIMEOUT_MS` | `6000` | hard cap on the recall spawn (it runs inside `before_agent_start`; a hang must never stall the run) |
| `SPECLOOP_PICK_TIMEOUT_MS` | `0` (off) | auto-skip the validation picker after this long (countdown shown); 0 = wait for the user |
| `SPECLOOP_MAX_CHARS_M0` | `2400` | recall injection budget (chars) — the ONLY size cap: bodies are never per-line clipped; if the first body alone exceeds it, that body is clipped to the budget |
| `SPECLOOP_NOTIFY` | `0` | surface recalls/notices via `notify` |
| `SPECLOOP_AUDIT` | `~/.specloop/audit.jsonl` | audit-log path (`0`/`off`/`false` disables) |
| `SPECLOOP_SESSION` | *(set by the extension)* | pi session id, stamped on every node + audit line (the memory↔session join key) |
| `SPECLOOP_PROJECT` | *(auto-detected)* | project scope key for audit lines + writes (git toplevel basename; set by the extension at `session_start`) |
| `SPECLOOP_LESSON_DEDUP_THRESHOLD` | `0.75` | WHEN-cosine to flag a merge candidate for the LLM arbiter. Measured on the live store: true paraphrases ≥0.729, unrelated pairs ≤0.728 (0.92 and 0.82 both left paraphrases stranded → duplicates accumulated) |
| `SPECLOOP_MMR_LAMBDA` | `0.7` | recall diversification (1 = pure relevance). Stops near-duplicate lessons monopolizing the top-k |
| `SPECLOOP_REDACT` | `1` | scrub high-precision secrets at the storage boundary, *before* embedding/persisting. Best-effort. |
| `SPECLOOP_SCOPE` | `global` | recall scope. `local` = current repo only. |

`SPECLOOP_PROVIDER=hash` runs fully offline (lexical embeddings — lower recall quality, useful for tests/air-gapped). With no chat key set, the recap degrades to storing the initial prompt as the body (best-effort) rather than failing.

## Commands

- `/specloop` — status (on/off, k, thresholds, mem path).
- `/specloop stats` — node counts by type.
- `/specloop recall <query>` — manual similarity search (read-only preview).
- `/specloop pick [query]` — manual recall **through the validation gate**: pick memories mid-session and insert them as a `specloop-recall` message without triggering a model turn (query defaults to the session's first prompt).
- `/specloop off` — disable for this session.

## Auditing

Memory **state** lives in the sqlite DB (`mem export`). Memory **use** — what was recalled/injected, what was written, enable/disable, recap lifecycle — is logged to `~/.specloop/audit.jsonl` by two writers:

- the **extension** logs `recall` (query, `above` = hits ≥ minScore pre-slice, `mode` = `picker|rpc_confirm|auto|auto_no_ui|picker_error`, `cancelled`, per-hit `accepted` flags, injected chars, `vehicle` = `message`) and `lifecycle` (`enabled`, `disabled`, `recap_queued` + `total_prompts`/drift/errors, `recap_spawned` + spool name, `shutdown_skipped` + reason for reload/new/resume/fork, `recap_recovered`);
- **`mem.py`** logs `write` (every node indexed, incl. merged/dedup/void/error) and `merge` (arbiter decisions).

Every line is stamped with `ts`, `session` (the pi session id), and `project`. Inspect:

```bash
mem audit                          # human-readable tail
mem audit --event recall           # only recalls/injections
mem audit --session <pi-session>   # one pi session's memory activity
mem audit --tail 50 --json         # machine-readable
```

### Store maintenance

```bash
mem dedup                # dry-run: report duplicate-candidate pairs (cos ≥ threshold)
mem dedup --apply        # merge via fast-path/arbiter, delete losers, re-scan in rounds
```

Repairs fragmentation left by older thresholds; every merge is audited (`dedup`
events) and losers' THENs survive in the winner's `provenance`. The audit trail
of bugs found & fixes applied lives in
[`notes/specloop-audit-log.md`](../../notes/specloop-audit-log.md).

## Crash recovery (lost recaps)

`recap` runs in a detached child, so a killed pi or a reboot used to lose the
session's recap **silently** (queued + spawned, then nothing). Now the exact
recap payload is **spooled** to `~/.specloop/spool/<session>-<ts>.json` before
the spawn, and `mem.py recap --spool-file` unlinks it on *every* exit path
(void, error, success). A leftover file therefore means the process died — the
next `session_start` re-runs it (`lifecycle: recap_recovered`). The child's
stderr is appended to `~/.specloop/recap-errors.log` (previously discarded).

## File map

```
specloop-pi/
├── README.md                 # this file
├── package.json              # pi-package manifest (extension only)
└── extension/
    ├── extension.ts          # entry: 3 hooks + renderer + /specloop (incl. pick)
    ├── picker.ts             # validation gate: checkbox picker component + mode-aware confirmGate
    ├── expandable.ts         # ExpandableText — reusable TUI component (clipped one-liner ↔ full text word-wrapped)
    └── mem.ts                # config + mem.py bridge + recall formatting + digest builder (pure)
```

Engine + recap summarizer live in [`../../lib/specloop-core/scripts/`](../../lib/specloop-core/scripts) (`engine.py`, `semantic.py`, `mem.py`).

## Verification done

- `python3` test suite: `test_engine.py` (12) + `test_semantic.py` + `test_audit.py` + `test_redact.py` + `test_http.py` + `test_lesson.py` + `test_status.py` + `test_mem.py` + `test_usage.py` — green.
- CLI end-to-end (`start` recall → `recap` write → dedup-on-write; `--spool-file` unlinked on both the error and success paths) offline with the `hash` embedder — green.
- `tsc --strict` against pi's type definitions — clean.
- Extension logic driven through a mock pi: first-prompt recall injects (audit carries `above` + `project`), second prompt is a no-op (once-per-session gate), `session_shutdown{reload}` logs `shutdown_skipped` (no recap), `session_shutdown{quit}` logs `recap_queued` (with `total_prompts`) + `recap_spawned` + writes the spool, the child unlinks the spool on completion and logs its write outcome, and a backdated spool file is picked up by `recoverSpooledRecaps` (`recap_recovered`) — all green.
- Validation-gate suite (97 checks, mock pi + stub mem.py + the **real** picker component): checkbox subset selection → message contains only checked entries; esc → nothing inserted (`cancelled` audit); `auto` mode → no picker; picker crash → fail-open (`picker_error`); rpc confirm fallback both ways; print/json auto; `/specloop pick` inserts via `sendMessage` with no turn; render width discipline in **both** states (default fully-wrapped and `e`-compacted — every line obeys the width contract down to width 1); mobile default (width 34: every word of every body visible, no ellipsis); `ExpandableText` unit battery (collapsed ellipsis ↔ wrapped full text, every word survives wrapping, toggle/handleInput); uncapped `formatContext` (budget is the only cap; later hits dropped at the budget; a first body larger than the whole budget is clipped to it, not skipped); message-renderer width safety with long + unbreakable bodies (the width-40 crash class) in both collapsed and expanded states; recap spool unlink — all green.

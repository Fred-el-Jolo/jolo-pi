# jolo-pi — customizations for the pi coding agent

This repo holds **all my personal customizations of [pi](https://github.com/earendil-works/pi)** (the `@earendil-works/pi-coding-agent` CLI/TUI) — skills, extensions, themes, the specloop memory engine, and notes — organized by kind. It is a pi-package (root `package.json` registers the extensions + skills), but in practice everything is loaded by absolute path from `~/.pi/agent/settings.json`.

## Repo layout (organized by kind)

| Path | Kind | Contents |
|---|---|---|
| `skills/` | pi skills (`SKILL.md`) | `process-extractor`, `isa` (+ `README.md` skill-format reference) |
| `extensions/` | pi extensions (TS) | `specloop-pi/` (wired-in memory extension), `zai-footer.ts` |
| `lib/` | supporting libraries | `specloop-core/` (python memory engine the `specloop-pi` extension shells out to) |
| `themes/` | pi themes (JSON) | `dark-bright.json` |
| `notes/` | design notes / research | `lifeos-skills-review.md` |
| `LEARNING.md` | walkthrough for `extensions/zai-footer.ts` | |

> Consolidation note: the former `skills/` repo was folded in here by kind; `skills/` now holds **only** `SKILL.md` folders.

## What pi is

pi is a coding agent harness with a TUI. It is extended through a few distinct surfaces. Knowing *which surface* a request belongs to is half the work — pick the right one:

| Surface | What it's for | Where it lives |
|---|---|---|
| **Context files** (`AGENTS.md` / `CLAUDE.md`) | Instructions & conventions loaded at startup | global `~/.pi/agent/AGENTS.md`, this file, parent dirs |
| **Themes** (`*.json`) | Colors only | global `~/.pi/agent/themes/`, project `.pi/themes/`, `--theme` |
| **Extensions** (TypeScript/JS) | Real logic: hooks, TUI components, custom tools, providers, event handlers | global `~/.pi/agent/extensions/`, project `.pi/extensions/`, `--extension`/`-e` |
| **TUI components** | Rendered UI blocks (rendered inside extensions/custom tools) | implemented within extensions; built on `@earendil-works/pi-tui` |
| **Skills** (`SKILL.md` + scripts) | Reusable task playbooks loaded on demand | global `~/.pi/agent/skills/` |
| **Settings** (`settings.json`) | Theme selection, enabled extensions, etc. | `~/.pi/agent/settings.json`, `/settings` in the TUI |
| **Prompt templates** | Reusable prompts | `~/.pi/agent/prompts/` |

## Canonical references

Pi's installed docs (read these before implementing anything pi-specific):

- Main: `README.md` under `$(npm root -g)/@earendil-works/pi-coding-agent/`
- Docs dir: `…/pi-coding-agent/docs/` — notably `extensions.md`, `tui.md`, `themes.md`, `custom-provider.md`, `rpc.md`, `environment-variables.md`, `settings.md`
- Examples dir: `…/pi-coding-agent/examples/` — `extensions/`, `sdk/`, `rpc-extension-ui.ts`

Resolve any `docs/...` or `examples/...` path the user mentions against that install root, **not** against this repo.

## How to work in this repo

- **The global IRON LAW still applies** — propose, don't impose. Don't start implementing a customization until I explicitly say so in the session. Research and explain first.
- Prefer the **least-invasive surface** that solves the problem: themes for colors, extensions for behavior/logic, a TUI component only when custom rendering is needed.
- **Extension source lives in the visible `extensions/` dir** (version-controlled, not auto-loaded). Test with `pi -e extensions/<name>.ts`; promote to global `~/.pi/agent/extensions/` (or `settings.json` `extensions`) only once it's stable. Avoid leaving copies in project `.pi/extensions/` — that auto-loads and defeats the test-first workflow.
- Keep TypeScript/JS extension code aligned with the interfaces in `docs/extensions.md` and `docs/tui.md`.

## Planned / in-progress customizations

### 1. z.ai quota footer segment *(implemented — tier B, pending review)*
- **Code:** `extensions/zai-footer.ts` · **walkthrough:** `LEARNING.md`
- **Mechanism:** `ctx.ui.setStatus("zai", segment)` — **augments** the default footer (built-in cwd/session/↑↓tokens/cache/cost/context-%/model stays intact). Refreshed on `session_start` + `turn_end` + a 60s background poll.
- **Data source:** **LIVE account quota** via `GET https://api.z.ai/api/monitor/usage/quota/limit` (Bearer key from `~/.pi/agent/auth.json` → `zai.key`). Returns real `remaining`/`currentValue`/`percentage`/`nextResetTime` for the 5h + weekly windows and the plan `level`. This **superseded** the per-turn session-credit estimate (tier A, removed) — the API is the source of truth for "how much do I have left?".
- **Display:** `⚡5h <remaining> (<%used> · ↻<countdown>) · wk <remaining> (<%used>) · peak|off-peak`. 5h number → `warning` ≥90% used, `error` at 100%.
- **Design notes:** fetches are async + never block render (we `setStatus` the cached result); the poll interval is `unref`'d and dedup'd across `/reload` via `globalThis`; `turn_end` fetch is delayed ~1.5s so z.ai's counter catches up.
- **Testing/applying:** `pi -e extensions/zai-footer.ts` to test; symlink into `~/.pi/agent/extensions/` or add to `settings.json` `extensions` to apply permanently.
- **Decisions to review (constants at top of file):** `POLL_MS` (60s), `TURN_END_DELAY_MS` (1.5s), `WARN_AT_PCT`/`ERROR_AT_PCT` (90/100). Plan `level` + caps come from the API (no hardcoded plan).
- **Color note:** the segment's detail text uses the `dim` token, so its readability depends on the `dark-bright` theme below (in plain `dark`, `dim` is `#666666` and hard to read).

### 2. `dark-bright` theme *(applied)*
- **Code:** `themes/dark-bright.json` · full copy of the built-in `dark` theme with one change: `vars.dimGray` `#666666` → `#909090` (recommended readability level). All 53 color tokens otherwise identical.
- **Why:** the built-in footer (`footer.js`) renders nearly all its text with the `dim` token (6×), which is nearly invisible at `#666666`. Bumping `dimGray` makes the **standard footer readable** — and since the z.ai segment (item 1) also uses `dim`, both footers share the same bright grey.
- **Applied via** `~/.pi/agent/settings.json`: `"theme": "dark-bright"` + `"themes": ["/home/jolo/dev/jolo-pi/themes/dark-bright.json"]` (source stays in the visible repo; settings references it by absolute path).
### 3. specloop — wired-in memory extension *(active)*
- **Code:** `extensions/specloop-pi/` (extension) + `lib/specloop-core/` (python engine) · **docs:** `extensions/specloop-pi/README.md`
- **What:** minimal two-touch memory — recall similar past recaps on the session's first prompt, write one recap node when the session quits. No mid-session recall, no per-error capture.
- **Applied via** `~/.pi/agent/settings.json` `extensions` (absolute path to `extensions/specloop-pi/extension/extension.ts`). The extension auto-locates `lib/specloop-core/scripts/mem.py` relatively; override with `SPECLOOP_MEM`.
- **Audit-driven fixes (2026-08-17):** dedup gate 0.92→0.82 (the LLM arbiter now sees paraphrases instead of near-verbatim only); evidence-only confirmation (`done` no longer grants `confirmed`, arbiter status suggestions ignored — ≥2 distinct sessions required); MMR recall diversification (`SPECLOOP_MMR_LAMBDA=0.7`); crash-safe recaps (payload spooled to `~/.specloop/spool/`, `mem.py recap --spool-file` unlinks on every exit, next `session_start` recovers leftovers, child stderr → `~/.specloop/recap-errors.log`); richer audit (`project` stamped on every line, recall `above` pre-slice count, `recap_queued` `total_prompts`, `shutdown_skipped`/`recap_spawned`/`recap_recovered` lifecycle events).

### 4. skills — `process-extractor`, `isa` *(process-extractor active; isa = scaffold)*
- **Code:** `skills/process-extractor/` (capture an existing process as a doc), `skills/isa/` (spec/completeness discipline — scaffold pending a source port; see `skills/isa/references/design-decision.md`).
- **Applied via** `~/.pi/agent/settings.json` `skills` (absolute paths). Skill-format reference: `skills/README.md`.

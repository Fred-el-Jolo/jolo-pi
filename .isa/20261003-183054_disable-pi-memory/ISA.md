---
task: "Disable specloop memory extension in pi config"
slug: 20261003-183054_disable-pi-memory
effort: E2
phase: complete
progress: 5/5
started: 2026-10-03T18:30:54
updated: 2026-10-05T21:35:00
root: .
stated_goal: "enc:v1:0ddf368a:K--cKrdbnipxqr2jptvPH3qJE7Zj-E5JfYU0zhf44jA72xpCcDmMBG1eo-P6L22-Wv5V360iIOr4tc_uy4i3nRii9UGhIMrVTLRRfoGqUrU8Rcqy-oPH2Di7lfeRiZWeveEPCaLzwGLnBZgPT2rZw0PQ97FU9ZkHgLtZJdY7DuQ9fHWUPBXVfRSiZHKOHzwLaiISjtrsGDM5GTPf"
stated_goal_source: prompt
asks:
  - "enc:v1:0ddf368a:go6SBw1uHZUOULVh1kRXumuBr0YGoVj5f9mI1MmI5Mfd3S_0lDm25wOp1qro0fWWi-ZZYrj2uqtVhdl7s_nZ3oH1yHOjEaacUnwKnw5PgvkwajSceZY0Qx2wbANQqaCMpmE"
  - "enc:v1:0ddf368a:ydDRA08IwORjGHrms6QXgv9qDjgkULoauTGLx7UQg2D1CutVdY15L1qWszUhP29lg87GqlspXaCMXhU_NqUAtHHYD7vl7RBXFEAgUEMVFMAYraO5ZxFM-m8T9A"
context_sufficient: true
frozen: true
---

## Problem

The pi agent loads the **specloop-pi** extension ("the wired-in memory layer for pi") from the `extensions` array in `~/.pi/agent/settings.json`. Every session it runs a health probe, offers a recall picker on the first prompt, and writes a recap node (background model call) when the session quits — the audit log shows it firing in this very session (project `jev-kit`). The user wants the memory behaviour gone from pi now and in every future session, but the plugin's files (and its data) must stay on disk untouched.

## Constraints

- The only load point is the `extensions` array in `~/.pi/agent/settings.json` (verified: no entry in `~/.pi/agent/extensions/`, no project `.pi/` in use for this, no other settings file active post-migration).
- Disable at the pi-config level using pi's own disable form: the `-` override pattern in the `extensions` array (what `pi config`'s space-toggle writes; `package-manager.js` force-excludes `-`-prefixed paths). No env-var tricks in shell profiles — `SPECLOOP_ENABLED` is not used because the extension would still load and probe.
- No edits to any file under `/home/jolo/dev/jolo-pi/extensions/specloop-pi/` and nothing deleted from `~/.specloop/`.

## Goal

"enc:v1:0ddf368a:3i3WP04zl_x0iX9gFHMoGdfj7VIA4ghICa7AtwQuLqsl0KnKEsu0J6u_r8QIjDhqwzv4nOsiYoxNaLrSm-Lp9A8y500w2ZgusHwzr4pcdtp5TbYYp2omK_0cLI8FP_GyQTpoHsBm9uiUwxitqkxG3GYyw3otOeVNq2pwcDSGrc_EVtvi-Xw4LNTjJ8oDFRulXxy49Oa0Q8UTfg"

Done = pi's configuration no longer references the specloop-pi extension anywhere (so no new or reloaded pi session loads it — proven by a fresh `pi config` read-back), while every file under `extensions/specloop-pi/` and the `~/.specloop` store remain exactly as they are.

## Criteria

- [x] ISC-1: settings.json extensions array enables no specloop entry
- [x] ISC-2: fresh pi session writes no specloop audit activity
- [x] ISC-3: Anti: no specloop-pi plugin file added, removed, or modified
- [x] ISC-4: Anti: `~/.specloop` memory store not deleted
- [x] ISC-5: Anti: settings.json stays valid JSON with other entries intact

## Test Strategy

```yaml
- isc: ISC-1
  anchors_to: "enc:v1:0ddf368a:go6SBw1uHZUOULVh1kRXumuBr0YGoVj5f9mI1MmI5Mfd3S_0lDm25wOp1qro0fWWi-ZZYrj2uqtVhdl7s_nZ3oH1yHOjEaacUnwKnw5PgvkwajSceZY0Qx2wbANQqaCMpmE"
  type: bash
  kind: config
  tool: jq -e '[.extensions[]? | select(test("specloop")) | select(startswith("-") | not)] | length == 0' ~/.pi/agent/settings.json
  check: no specloop-matching entry in the extensions array lacks the `-` disable prefix
  threshold: jq -e exit 0
  fails-when: "jq finds a specloop path in the extensions array without the leading `-`"
- isc: ISC-2
  anchors_to: "enc:v1:0ddf368a:go6SBw1uHZUOULVh1kRXumuBr0YGoVj5f9mI1MmI5Mfd3S_0lDm25wOp1qro0fWWi-ZZYrj2uqtVhdl7s_nZ3oH1yHOjEaacUnwKnw5PgvkwajSceZY0Qx2wbANQqaCMpmE"
  type: bash
  kind: config
  tool: bash -c 'b=$(wc -l < ~/.specloop/audit.jsonl); env -u SPECLOOP_PROJECT pi -p --no-session --offline "Reply with the single word ok" >/dev/null 2>&1; a=$(wc -l < ~/.specloop/audit.jsonl); test "$b" -eq "$a"'
  check: a one-shot print-mode pi session (fresh process, real settings) appends nothing to specloop's audit log — no health probe, no recall, no recap
  threshold: audit.jsonl line count unchanged across the run
  fails-when: "the fresh pi session appends any audit line (specloop loaded and ran its session_start probe)"
- isc: ISC-3
  anchors_to: "enc:v1:0ddf368a:ydDRA08IwORjGHrms6QXgv9qDjgkULoauTGLx7UQg2D1CutVdY15L1qWszUhP29lg87GqlspXaCMXhU_NqUAtHHYD7vl7RBXFEAgUEMVFMAYraO5ZxFM-m8T9A"
  type: bash
  kind: file
  tool: test -z "$(git -C /home/jolo/dev/jolo-pi status --porcelain extensions/specloop-pi)"
  check: the plugin's git tree shows no add/modify/delete under extensions/specloop-pi
  threshold: git status prints nothing for the path (test -z exits 0)
  fails-when: "git status prints any line for extensions/specloop-pi (a file added, deleted or modified there)"
- isc: ISC-4
  anchors_to: "enc:v1:0ddf368a:ydDRA08IwORjGHrms6QXgv9qDjgkULoauTGLx7UQg2D1CutVdY15L1qWszUhP29lg87GqlspXaCMXhU_NqUAtHHYD7vl7RBXFEAgUEMVFMAYraO5ZxFM-m8T9A"
  type: bash
  kind: file
  tool: test -f ~/.specloop/memory.db -a -d ~/.specloop/spool
  check: the memory store's database and spool directory still exist
  threshold: test exits 0
  fails-when: "memory.db or the spool directory no longer exists under ~/.specloop"
- isc: ISC-5
  anchors_to: "enc:v1:0ddf368a:ydDRA08IwORjGHrms6QXgv9qDjgkULoauTGLx7UQg2D1CutVdY15L1qWszUhP29lg87GqlspXaCMXhU_NqUAtHHYD7vl7RBXFEAgUEMVFMAYraO5ZxFM-m8T9A"
  type: bash
  kind: config
  tool: jq -e '(.extensions | index("/home/jolo/dev/jolo-pi/extensions/zai-footer.ts")) != null and .defaultModel == "glm-5.3" and (.skills | length) == 3' ~/.pi/agent/settings.json
  check: neighbouring settings survive the edit — zai-footer extension entry, defaultModel, all three skills
  threshold: jq -e exit 0
  fails-when: "settings.json fails to parse or a neighbouring entry (zai-footer extension, defaultModel, skills) was lost in the edit"
```

## Decisions

- 2026-10-03 refined: tier E3 → E2 — single bounded config edit in one domain (pi settings), mechanical but must be proven.
- 2026-10-03 Disable by prefixing the specloop entry in the `extensions` array with `-` (`-<path>` is pi's force-exclude override — exactly what the `pi config` TUI writes on space-toggle-off; verified in `config-selector.js` `toggleTopLevelResource` and `package-manager.js` `isEnabledByOverrides`). Files stay on disk; the entry stays visible and self-documenting; re-enabling later = strip the `-` (or toggle in `pi config`). Chosen over deleting the line: same effect, more reviewable.
- 2026-10-03 End-to-end witness is specloop's own audit log (`~/.specloop/audit.jsonl`): every loaded specloop instance appends lifecycle lines. A one-shot `pi -p --no-session` run whose audit line count is unchanged proves a fresh session did no memory activity. `pi config`/`pi list` were rejected as probes (TUI only / packages only).
- 2026-10-03 Probe-tool lesson: the engine executes the `tool:` field verbatim in bash — the first red run used bare command names in `tool:` (probe text since replaced), producing meaningless baselines; ledger rows from that run are void.
- 2026-10-03 Rejected `SPECLOOP_ENABLED=0` env route: needs shell-profile changes, the extension still loads and runs its session_start probe, and it would not cover pi launched outside that profile.
- 2026-10-03 Current session caveat: the already-running pi process keeps its loaded extension until reload/restart; the user can run `/specloop off` (session-scoped off switch) or `/reload`/restart to pick up the settings change immediately. Recorded, not fixable from inside the session.

## Verification

- ISC-1: verified 2026-10-03T18:36:02 — exit 0 in 0.0s — `jq -e '[.extensions[]? | select(test("specloop")) | select(startswith("-") | not)] | length == 0' ~/.pi/agent/settings.json` (ledger: bf231b937d)
- ISC-2: verified 2026-10-03T18:36:02 — exit 0 in 4.05s — `bash -c 'b=$(wc -l < ~/.specloop/audit.jsonl); env -u SPECLOOP_PROJECT pi -p --no-session --offline "Reply with the single word ok" >/dev/null 2>&1; a=$(wc -l < ~/.specloop/audit.jsonl); test "$b" -eq "$a"'` (ledger: f564dc88ca)
- ISC-3: verified 2026-10-03T18:36:02 — exit 0 in 0.0s — `test -z "$(git -C /home/jolo/dev/jolo-pi status --porcelain extensions/specloop-pi)"` (ledger: 5877797795)
- ISC-4: verified 2026-10-03T18:36:02 — exit 0 in 0.0s — `test -f ~/.specloop/memory.db -a -d ~/.specloop/spool` (ledger: 69209bfd32)
- ISC-5: verified 2026-10-03T18:36:02 — exit 0 in 0.0s — `jq -e '(.extensions | index("/home/jolo/dev/jolo-pi/extensions/zai-footer.ts")) != null and .defaultModel == "glm-5.3" and (.skills | length) == 3' ~/.pi/agent/settings.json` (ledger: a409748fa1)
- Ask 1: met — pi no longer loads specloop anywhere: settings disable via `-` force-exclude (ISC-1), and a fresh one-shot `pi -p` session performs zero specloop audit activity (ISC-2) — no probe, recall, or recap. "Now" needs the running process to reload: `/reload` or restart picks up the setting (or `/specloop off` as a session-scoped off switch); the already-loaded instance is the one thing an in-session edit cannot unload.
- Ask 2: met — no plugin file touched (ISC-3: git-clean tree under `extensions/specloop-pi`), memory store intact (ISC-4), and the disable lives in pi's own config — the exact form `pi config`'s toggle writes (ISC-1/ISC-5).
- Goal: yes — the memory layer is disabled both now and for future sessions: a brand-new pi process runs with zero memory activity (ISC-2), the setting is live for every new/reloaded pi process (one-command /reload hand-off noted to the user), and the plugin files and data are untouched as demanded.

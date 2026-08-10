# z.ai quota footer — review reference

How `extensions/zai-footer.ts` works (tier B: live account quota). For later review.

Doc paths are relative to the pi install root:
`$(npm root -g)/@earendil-works/pi-coding-agent/`.

---

## 0. Run / iterate

```bash
# from /home/jolo/dev/jolo-pi — load for this session only:
pi -e extensions/zai-footer.ts
/zai        # toggle the segment on/off
```

Apply permanently: symlink/copy into `~/.pi/agent/extensions/` (global,
auto-discovered, `/reload`-able) or add the path to `settings.json` `extensions`.

Extensions run via [jiti](https://github.com/unjs/jiti) — TS with no build step.
`import type` from `@earendil-works/*` resolves through the global `node_modules`.

---

## 1. Mechanism: `setStatus` augments the default footer

```ts
ctx.ui.setStatus("zai", "⚡5h 1891 (5% · ↻4h53m) …");  // persistent segment
ctx.ui.setStatus("zai", undefined);                     // clear
```

We use `setStatus` (append a segment) **not** `setFooter` (replace the whole
line), so the built-in footer — cwd, session, `↑`/`↓`/`R`/`W`/`CH`, cost,
context-%, model (`README.md` line 156) — stays 100% intact. Reference examples:
`status-line.ts`, `model-status.ts` (`docs/extensions.md` ~line 2555).

---

## 2. The API

```
GET https://api.z.ai/api/monitor/usage/quota/limit
Authorization: Bearer <zai key>      (from ~/.pi/agent/auth.json → zai.key)
```

```jsonc
{ "code":200, "success":true, "data":{
    "level":"lite",
    "limits":[
      { "type":"CREDIT_LIMIT","unit":3,"number":5,        // 5-hour window
        "usage":2000,        // ← the CAP (Lite 5h)
        "currentValue":1916, // used
        "remaining":83,
        "percentage":95,     // % USED
        "nextResetTime":1786373456756 },                  // epoch ms (UTC)
      { "type":"CREDIT_LIMIT","unit":6,"number":1,        // weekly window
        "usage":10000,"currentValue":2398,"remaining":7601,
        "percentage":23,"nextResetTime":1786539767998 } ] } }
```

Field notes:
- `level` ∈ `lite`|`pro`|`max`; `usage` is the **cap** for that window
  (2000/10000 = Lite 5h/weekly, 12000/60000 = Pro, 28000/140000 = Max).
- `percentage` is **% used**, not remaining.
- We tell the two windows apart by `nextResetTime`: **nearest = 5h, farthest =
  weekly** (robust; doesn't depend on what `unit`/`number` mean).
- `nextResetTime` is UTC epoch ms. z.ai displays it in **UTC+8** (verified: a
  1786373456756 reset = 22:50 UTC+8 = 16:50 CEST).

---

## 3. Refresh strategy

| Trigger | Why |
|---|---|
| `session_start` | first paint when a session opens |
| `turn_end` (+ ~1.5s delay) | a turn just consumed credits; the delay lets z.ai's counter update |
| `setInterval(60s)` | keeps the countdown/reset correct while idle (the 5h window rolls on its own) |

Rules:
- **Never block render.** Fetches are async; we `setStatus` the *cached* result.
  Footers can't do network on the render path.
- `inFlight` guard prevents overlapping requests.
- The interval is `unref()`'d (won't keep pi alive) and stored on `globalThis`
  so a `/reload` clears the previous module's timer (no leak/double-poll).
- On fetch error we **keep the previous status** (don't blank it) and `console.warn`.

`/zai` toggles visibility; toggling back on triggers an immediate refresh.

---

## 4. `buildStatus` + thresholds

```ts
⚡5h 1891 (5% · ↻4h53m) · wk 7466 (25%) · off-peak
```

- 5h `remaining` is `accent`, but `warning` at ≥90% used and `error` at 100%
  (`WARN_AT_PCT` / `ERROR_AT_PCT`) so a near-exhausted window pops.
- Detail text (`(% · ↻…)`, weekly) uses the **`dim`** token — readable only with
  the **`dark-bright`** theme (`dimGray #909090`, see `AGENTS.md` item 2). In
  plain `dark`, `dim` is `#666666` and nearly invisible.
- countdown via `fmtDur` → `4h53m` / `5m` / `12s`.
- peak/off-peak badge from `isOffPeakSGT()` (UTC+8) — independent of the API,
  but useful: it tells you whether you're being charged 50% right now.

---

## 5. Caveats

- **One account/key.** Reads `zai.key` from `auth.json`; if you use multiple z.ai
  accounts, that's the one it shows.
- **Network dependency.** If z.ai's API is unreachable, the segment goes stale
  (or absent on first load) until the next successful poll — by design, no error
  spam in the footer.
- **`auth.json` coupling.** pi doesn't expose the provider key to extensions via
  `ctx`, so we read the file directly (path respects `PI_CODING_AGENT_DIR`).
  Format breakage on a pi upgrade is the main risk → surfaced as a fetch failure.

---

## 6. What was removed (tier A)

Earlier the segment estimated spend by converting per-turn token `Usage` to
credits via z.ai's per-model multipliers + off-peak discount
(`computeCredits`, `MODEL_MULTIPLIERS`, `PLAN_ALLOWANCE`, `isOffPeakSGT` for
billing). All gone — the API gives the real account-wide number, which is what
matters. The only `isOffPeakSGT` kept is for the informational badge (§4).

---

## 7. Stretch ideas

- **Per-session spend** as a secondary number (resurrect `computeCredits`) —
  useful attribution the API can't give ("this session cost X").
- **Near-limit notify** — `ctx.ui.notify` when 5h crosses 90%.
- **Weekly prominence** — promote weekly when 5h is healthy but weekly is the
  binding constraint.
- **Quota history** — log `currentValue` over time to a file (this is where a
  standalone Bun/Node daemon would actually earn its place; see chat).

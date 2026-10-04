---
task: "Fix zai-footer NaN rendering; confirm % is server-side"
slug: 20261004-175255_fix-zai-footer-nan
effort: E2
phase: complete
progress: 5/5
started: 2026-10-04T17:52:55
updated: 2026-10-04T17:59:30
root: .
stated_goal: "enc:v1:0ddf368a:DyWOdwaD78YXYfR_qgaK7Lu5toZuzXIHmAj43WBkw7Q4OTbaan4MTghOeU6HP_FVxohepdnbHwYNpAnI3c92vORtoXsaFwX3VY5EhY5xWV2B_RB5SNf6fAbYZwqQdogVwu2_LzNIhbfXfVXcCJKfmDnGzeoq1mBhLTrKjC5t47_YP5At6mJU2uCMjluCNOqrnmWQZkEL9L6S74cCBNbvfknPFp1z3ArNvIS35Df26ZnH8UMRS4r_VtipxYKfuVXc__MotteF_BeZ89hAXhzjHzFLkbjnCPkdm9d5WrlTK4RI_eM9TvinhhOT_fIfzOaBTWWPIPdiN4V2ZNPqnc7bXgrRgO4sJpAPpCwn3e32"
stated_goal_source: prompt
asks:
  - "enc:v1:0ddf368a:DA_uj8vaBKcb_-svfvnkAuhFIiHGm_k3CxukitrLe4aYW_3hqZ-ZVbo4E8q6DW5wcPTRi2zT_8Izd5WWJMWPhTLzQtMxQnfaouoZhMjkNnG2ZsvqgW3MlWaUTtM2hOCx9WBKsDYYl23Yi7OaQ524FqFqzR7t3Og"
  - "enc:v1:0ddf368a:pD7BgRPNT8PFk3ED2erVQiYHOnMoVAdAKRHqTHWRF3e8kSseT3VwgHJspw2gMQ2vlam-prxaN-tdT2O8arlxpnQjkwiQtC7OQ5vv1mIdMKfl6OAUgoZ86G-_6whue0K5CyGncoOFXJv8Rw-EO-oco5Tx10B-w8i6J_RtpYl2rkOmekoY33mx1MlTUjweCTZ0Xs6O5du5ZnEpEj57iJ3oZyHbM6pVqlAcJtg8OCMhVfmc3ep1wdYpNb4"
context_sufficient: true
---

## Problem

`extensions/zai-footer.ts` renders `nextResetTime` straight into the countdown
(`fmtDur`/`fmtDurWk`) with no validation. When no usage window has started yet,
z.ai returns that field absent/null, and `(undefined - now)` → `NaN`, which
`Math.max(0, …)` propagates — the footer shows `NaNh…` for the remaining time.
The same unchecked-render class covers `percentage` on both the 5h and weekly
limits. Separately, the user wants assurance that the displayed % stays correct
for new z.ai models — i.e. that nothing in the extension computes credits or %
from per-model token pricing that could silently go stale.

## Goal

"enc:v1:0ddf368a:65ERRDDezz41lwW8ZhHZsC4cIpiu96d-2HKezz8BA7Uup4wGLeM9qCo_OswHCcALnXpQXghcJpOoN6u1zfI7mEwJ0YwhIbVdLahrcL5zwrYAQ50H-LgxOQ_1ZMKX_55_0asV7U5AOrAGK58RFOt3F5XO6ZueVs1ujSyMt2UOl_KMwiNGPnAir8cazdLRhYYzv_BMAd8YYqJpigd0XpcAZ7TaA1vi7KuEb18dFtaJjdOxv1GVXIxi2URs_A9pepo-B-tmQCSIfw6wxAKTAplLKgMDA6jQnGCtzKYpwPtDAqQjo6_gJfhxyaENqRn9OnarGgkG3oZkz4Yc0UIFTyi6waa6hKdACC1g_oHfBg"
The footer renders only finite data — an absent field degrades per-field (a
missing reset time never hides a renderable percentage), never as NaN — and the
% shown is confirmed to be z.ai's own server-side figure, with no local
token→credit arithmetic in the extension to actualize per model.

## Criteria

- [x] ISC-1: buildStatus output contains no NaN for absent numeric fields
- [x] ISC-2: Anti: absent reset time never hides renderable percentage segment
- [x] ISC-3: valid quota still renders pct and countdown both windows
- [x] ISC-4: live API percentage matches used-over-cap ratio both limits
- [x] ISC-5: Anti: extension contains no local token-credit estimation code

## Test Strategy

```yaml
- isc: ISC-1
  anchors_to: literal
  type: unit-test
  kind: behaviour
  class: unvalidated-numeric-render
  check: buildStatus on limits with null/undefined nextResetTime and percentage renders no "NaN"
  threshold: node exits 0 (assertions hold)
  tool: node extensions/zai-footer.test.mjs

- isc: ISC-2
  anchors_to: literal
  type: unit-test
  kind: behaviour
  check: 5h segment still shows its percentage when only its nextResetTime is undefined
  threshold: node exits 0
  tool: node extensions/zai-footer.test.mjs
  fails-when: "the ⚡5h segment disappears entirely or shows no % while only its reset time is absent"

- isc: ISC-3
  anchors_to: literal
  type: unit-test
  kind: regression
  check: fully valid quota renders ⚡5h %, ↻ countdown, wk %, peak dot
  threshold: node exits 0
  tool: node extensions/zai-footer.test.mjs
  fails-when: "a valid payload loses the % or the ↻ countdown in the rendered segment"

- isc: ISC-4
  anchors_to: literal
  type: bash
  kind: http
  check: live quota API's own percentage equals 100·currentValue/usage (±1) per limit; null percentage only when nothing used
  threshold: exit 0 (python asserts hold)
  tool: |-
    KEY=$(python3 -c "import json;print(json.load(open('$HOME/.pi/agent/auth.json'))['zai']['key'])") && curl -sS -m 15 -H "Authorization: Bearer $KEY" -H "Accept: application/json" https://api.z.ai/api/monitor/usage/quota/limit | python3 -c "
    import json,sys
    j=json.load(sys.stdin)
    assert j.get('success') and j.get('data',{}).get('limits'), j.get('msg')
    for L in j['data']['limits']:
        p,u,c=L.get('percentage'),L.get('usage'),L.get('currentValue')
        if isinstance(p,(int,float)):
            assert abs(p-100*c/u)<=1, L
        else:
            assert not c, L
    print('OK')"
  red: exempt — audits z.ai's live server-side figure; no build change can turn this probe red
  fails-when: "a limit's percentage deviates from 100·currentValue/usage by more than 1 point (or null % while credits are used)"
  risk: low — GET only, with the stored key read from auth.json; the key never appears in output

- isc: ISC-5
  anchors_to: literal
  type: unit-test
  kind: regression
  check: no local token→credit/% estimation remains in the extension; % is relayed byte-for-byte
  threshold: node exits 0 AND zero matches (negated rg exits 0)
  tool: node extensions/zai-footer.test.mjs && ! rg -q 'computeCredits|MODEL_MULTIPLIERS|PLAN_ALLOWANCE' extensions/zai-footer.ts
  risk: low — grep-only static check; no secrets, tokens or credentials touched
  fails-when: "a per-model multiplier table or credits formula reappears, or a non-integer % input stops rendering byte-for-byte, making the % stale for new models"
```

## Decisions

- 2026-10-04 17:55: refined: tier E3 → E2 — single bounded fix in one extension file plus a live-API audit; no multi-subsystem surface
- 2026-10-04 17:56: The suspect file was read in an earlier turn (repo recap request) before a reproducing test existed; the red unit test below is still written and run before any fix lands
- 2026-10-04 18:05: Node v24 type stripping runs the .ts import directly (`node extensions/zai-footer.test.mjs`) — no extra toolchain needed; `buildStatus` gets an `export` keyword purely to make the real code probeable
- 2026-10-04 18:12: Red run shows the exact defect: `⚡5h 42% · ↻NaNs │ wk null% · ↻0m` — undefined reset → NaN countdown, null pct → `null%`, null reset clamps to bogus `↻0m`
- 2026-10-04 18:15: ISC-1/2/3 share one probe command (one node process, three assertion blocks) — a failure in any block fails all three recordings; accepted coupling for a 40-line test
- 2026-10-04 18:20: Sort-by-resetTime mislabels windows when one reset is absent (null sorts as farthest → weekly would land in the 5h slot); when any reset time is absent, fall back to z.ai's own array order and degrade per-field
- 2026-10-04 18:25: Jev advisory (0.42) on ISC-5 accepted — grep alone can't catch a freshly-named estimator; tightened the probe to also assert byte-for-byte % pass-through in the unit test
- 2026-10-04 18:30: Live audit (active session): 5h 114/2000 → API % 5 (5.7 floored), wk 688/10000 → API % 6 (6.88 floored) — percentage is z.ai's own server-side figure, floors used/cap; nothing local to go stale per model
- 2026-10-04 18:35: class-sweep: unvalidated-numeric-render — 4 render sites (5h pct, 5h reset, wk pct, wk reset) via rg 'parts.push' in buildStatus; 4 guarded (pctUsed/resetAt), 0 tombstoned

## Verification

- ISC-1: verified 2026-10-04T17:59:30 — exit 0 in 0.08s — `node extensions/zai-footer.test.mjs` (ledger: 052b62e9fa)
- ISC-2: verified 2026-10-04T17:59:30 — exit 0 in 0.08s — `node extensions/zai-footer.test.mjs` (ledger: ae9b176bea)
- ISC-3: verified 2026-10-04T17:59:30 — exit 0 in 0.08s — `node extensions/zai-footer.test.mjs` (ledger: e7a0fdefbe)
- ISC-5: verified 2026-10-04T17:59:30 — exit 0 in 0.13s — `node extensions/zai-footer.test.mjs && ! rg -q 'computeCredits|MODEL_MULTIPLIERS|PLAN_ALLOWANCE' extensions/zai-footer.ts` (ledger: 58b8d587ac)
- ISC-4: verified 2026-10-04T17:59:30 — exit 0 in 0.3s — `KEY=$(python3 -c "import json;print(json.load(open('$HOME/.pi/agent/auth.json'))['zai']['key'])") && curl -sS -m 15 -H "Authorization: Bearer $KEY" -H "Accept: application/json" https://api.z.ai/api/monitor/usage/quota/limit | python3 -c "
import json,sys
j=json.load(sys.stdin)
assert j.get('success') and j.get('data',{}).get('limits'), j.get('msg')
for L in j['data']['limits']:
    p,u,c=L.get('percentage'),L.get('usage'),L.get('currentValue')
    if isinstance(p,(int,float)):
        assert abs(p-100*c/u)<=1, L
    else:
        assert not c, L
print('OK')"` (ledger: 384b92efd2)
import json,sys
j=json.load(sys.stdin)
assert j.get('success') and j.get('data',{}).get('limits'), j.get('msg')
for L in j['data']['limits']:
    p,u,c=L.get('percentage'),L.get('usage'),L.get('currentValue')
    if isinstance(p,(int,float)):
        assert abs(p-100*c/u)<=1, L
    else:
        assert not c, L
print('OK')"` (ledger: 39bbedadc3)
- Ask 1: met — red→green on the real buildStatus: absent reset/pct fields now degrade per-field (`⚡5h 42% │ ○`), NaN/null/undefined render impossible (ISC-1, ISC-2, ISC-3)
- Ask 2: met — % is z.ai's server-side figure, verified live today (5h 5% = ⌊5.7⌋, wk 6% = ⌊6.88⌋) and relayed byte-for-byte; the tier-A token→credit tables are gone, so new models are actualized automatically by z.ai, not by us (ISC-4, ISC-5)
- Goal: yes — the footer never renders NaN for absent quota fields (red baseline `↻NaNs │ wk null%` → clean per-field render), and the % computation is confirmed server-side with no local token-cost math (live probe + static probe)

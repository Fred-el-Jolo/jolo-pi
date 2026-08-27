# specloop audit log — bugs encountered & fixes applied

Running record of memory-system audits: what was observed, root cause, fix,
verification, and store surgery. One section per audit round. Store **state**
lives in `~/.specloop/memory.db`; memory **use** in `~/.specloop/audit.jsonl`
(`mem audit`). Engine: `lib/specloop-core/`, extension:
`extensions/specloop-pi/`.

Legend: ✅ fixed & verified · 📋 observed, decision pending / accepted risk

---

## Round 1 — 2026-08-17 (initial audit, post-`36dff93`)

Store state at audit: 25 lessons, 4 `confirmed` with prov=1, ~7 duplicate
clusters. Audit log: 70 events over 4 days. **Store was purged afterwards and
rebuilt from zero** (backup: `memory.db.bak-20260817`).

| ID | Symptom (evidence) | Root cause | Fix | Status |
|---|---|---|---|---|
| R1-1 | Same lesson stored 3× (`1ff81a91`/`989e8ccd`/`50a9d07d` exact-text family) | `LESSON_DEDUP_THRESHOLD=0.92`: paraphrases (cos 0.73–0.88) never reached the LLM arbiter — it only ran above the gate | default → 0.82 (later 0.75, see R2-4) | ✅ `f05d820` |
| R1-2 | `confirmed` with prov=1 (4 nodes); same session recapped twice flipped tentative→confirmed | `initial_lesson_status("done")⇒confirmed` + `_reconcile` trusted the arbiter's status suggestion | status always starts `tentative`; merge status computed from evidence (`merged_status`+`promote`), arbiter status ignored | ✅ `f05d820` |
| R1-3 | Generic "hub" lessons in every recall top-3 (`2039a015` in 4/11 recalls) | pure-cosine ranking over a small store | MMR diversification (`SPECLOOP_MMR_LAMBDA=0.7`), `_score` kept raw | ✅ `f05d820` |
| R1-4 | Recap queued then nothing (`01a009b6` — user rebooted the rpi); lost silently | detached recap child killed with the machine; stderr discarded; non-quit shutdowns unlogged | payload spooled to `~/.specloop/spool/`, `mem recap --spool-file` unlinks on every exit, next `session_start` recovers (`recap_recovered`), stderr → `recap-errors.log`, `shutdown_skipped`/`recap_spawned` lifecycle events | ✅ `f05d820` |
| R1-5 | `project: null` on every audit line | extension never set `SPECLOOP_PROJECT` | `detectProject()` (git toplevel basename) at `session_start`, stamped on all lines | ✅ `f05d820` |
| R1-6 | `recap_queued prompts=0` looked like digest failure | field logged only *drift* prompts (`slice(1,21)`) | `total_prompts` added to the audit line | ✅ `f05d820` |
| R1-7 | Recall re-armed on restart/resume → double recall per logical session | deliberate (`session_start` resets the gate); restarts re-inject | accepted: re-injection is bounded (once per process) | 📋 accepted |

Verified: 9 test suites, `tsc --strict`, mock-pi e2e (spool write→unlink,
recovery, gated recall). Production follow-up (08-18→08-27): 7 recaps, 0 lost,
all statuses honest, project stamped.

---

## Round 2 — 2026-08-27 (after ~10 days of real use)

Store state at audit: 18 lessons, all `tentative`, spool empty, no lost
recaps, `recap-errors.log` clean. New issues:

| ID | Symptom (evidence) | Root cause | Fix | Status |
|---|---|---|---|---|
| R2-1 | 🔴 Two pi sessions `disabled` at 12:25 with `SyntaxError` — engine files were being rewritten on disk 12:24–12:27 (read mid-write). One is the session that requested this audit → no recall injected, no recap at quit | transient: probe caught a half-written file. **Aggravator:** `session_start` early-returned on `!memOk` *before* the probe → the disable latched for the whole process lifetime; even `/reload` never re-probed | probe runs on EVERY `session_start`; a pass after a previous failure re-enables (`lifecycle enabled recovered:true`). Restart pi to un-poison currently-running instances | ✅ (this commit) |
| R2-2 | 18/18 lessons `tentative` after 10 days — confirmation unreachable. `dff16dbe` merged 3× but prov=1 | heavy session **resuming**: re-learnings carry the same session id, so `confirmed_by` never grows | promotion now has a second evidence bar: `≥ CONFIRM_DAYS (3)` distinct calendar days (`meta.learned_days`, unioned on every merge) ⇒ `confirmed` even for one resumed session. Session-count bar (2) unchanged | ✅ (this commit) |
| R2-3 | audit `merge provenance_count=2` while DB truth was prov=1 — misleading during analysis | `provenance_count` counted provenance entries (≈ merges), not confirmations | kept `provenance_count` (now accurate as merge count) + added `confirmed_by_count`, `learned_days_count` to merge audit lines | ✅ (this commit) |
| R2-4 | Exact-text family re-fragmentating: `5a0ad549`/`49b63424`/`73942c42`/`e8285777` = same meta-lesson, 4 nodes (0.82 gate still misses: measured family cosines 0.64–0.84) | threshold above the paraphrase band | measured on live store: family pairs ≥0.729, unrelated pairs ≤0.728 → **default 0.75** (clean separation in the measured data); plus `mem dedup` repair command (below) | ✅ (this commit) |
| R2-5 | no repair path for already-fragmented nodes | dedup only ran at write time | new `mem dedup` — dry-run report of candidate pairs; `--apply` merges via the policy (fast path/arbiter), deletes losers, audits `dedup` events, re-scans in **rounds** (cascade: a merge frees another node's candidate). `Memory.delete_node()` added | ✅ (this commit) |
| R2-6 | **Incident (introduced then fixed same session):** first `dedup --apply` over-merged — the arbiter approved 5/5 pairs including cross-family ones (cos 0.755/0.794), producing a grab-bag node `0c3b246c` ("module import fails" absorbing "read SPECS.md first" + "Promise type-check" THENs). Also the cascade bug: pair 6 (`73942c42~59698de2`) silently vanished when its target was consumed mid-run | (a) arbiter is permissive at low cosines — it never says not-a-dup near the threshold; (b) single-pass apply didn't re-scan | cascade → rounds loop in `cmd_dedup` (R2-5); grab-bag → **store surgery**: split `0c3b246c` using its preserved provenance, resurrected the two lessons as `80b20aae` (SPECS.md) + `8631359a` (Promise type), WHENs are prefixes of the originals (full text died with the merge; `meta.reconstructed: true` marks them), audited as `repair` events. Recall verified: right node at 0.89–0.95 per query | ✅ surgery done; 📋 arbiter permissiveness = accepted risk (below) |
| R2-7 | `0c0c74fc` ("proposing multiple creative projects") hit 5/7 recalls | generic WHEN on a real lesson | accepted — MMR rotates the rest; revisit if a hub survives store growth | 📋 accepted |
| R2-8 | embedding drift: fresh-vs-stored cosine differed enough to change nearest (`5a0ad549~59698de2` measured 0.844 fresh, <0.772 against stored) | API embeddings not perfectly stable call-to-call | observed only; `dedup` re-embeds queries but compares against stored vectors. If it recurs: re-embed store in one pass (`mem export`+rebuild) | 📋 watch |

**Open follow-ups** (no action taken):
- Arbiter prompt tuning (semantic.py `merge_thens`) — make it *willing* to say
  `same_trigger: false` near the threshold; consider passing the cosine to the
  prompt. Upstream-owned file — coordinate before touching.
- Consider a periodic `mem dedup` (e.g. weekly manual) now that it's safe.
- `mem audit` printer doesn't know `repair` events (falls back to JSON dump) —
  cosmetic.

Verified this round: 9 suites green (new tests: days-promotion, cascade dedup,
delete_node, promote-by-days), `tsc --strict` clean, recall precision check
post-surgery (3 queries → correct node first at 0.89–0.95).

**Store surgery history**: 2026-08-17 purge (25 damaged nodes → 0, backup
kept) · 2026-08-27 dedup repair (18→13, then split +2 → 15) · both audited in
`audit.jsonl`.

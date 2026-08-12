# Design decision — isa: always-on rule vs on-demand skill

**Decision: on-demand skill + (later) a one-line AGENTS.md nudge.** Not always-on.

## What isa is
A pre-execution **spec/completeness discipline** (LifeOS "ideal-state artifact"): describe the ideal end state → interview to surface gaps → score the spec's completeness → reconcile until it clears a threshold → only then execute. A "slow down to speed up" gate that front-loads thinking to avoid building the wrong thing.

Not installed anywhere on the system (LifeOS-coupled; previously rejected for import whole). "Re-using" it = **porting its discipline into this clean local skill** — deliberately lighter than the deleted `specloop` (no memory plumbing).

## The trade-off

| | Always-on (AGENTS.md rule) | On-demand (skill) |
|---|---|---|
| Mechanism | baked into the system prompt every turn | SKILL.md; loaded only when its description matches |
| Cost on simple prompts | pays every time (tokens + latency) | **zero** |
| Over-application risk | **high** — forces a completeness-interview on "fix the typo" (the over-engineering this repo keeps rejecting) | none — trivial tasks skip it |
| Skip risk (model doesn't apply when it should) | low (always in context; compliance still not guaranteed) | moderate — routing gap |
| Aligns with the cleanup just done | ❌ reverses it (re-adds continuous overhead) | ✅ extends it |

## The crux
isa's value is **sharply conditional** — gold on ambiguous, open-ended, "done-state unclear" work; **negative value** on well-specified/trivial work. So the real question isn't "does enabling it improve quality" but "does applying it to *the right tasks* improve quality." Always-on applies to *all* tasks; on-demand applies to *matching* tasks.

## Why this differs from memory (which became a hook)
Memory was pushed into a hook because its value is **destroyed if skipped** (no recall = the feature is invisible) — guarantee-critical. isa is a **quality enhancer**: a miss means a slightly worse outcome on one task, fully recoverable with "run isa on this." Low-cost misses are exactly what on-demand is built for. **The same logic that made memory a hook is the logic that makes isa a skill.**

## Recommendation chosen: (b) on-demand + a one-line nudge

The spectrum considered:
- **(a) pure on-demand skill** — zero base cost.
- **(b) on-demand + one-line AGENTS.md nudge** ← **chosen**.
- **(c) always-on *lite*** (just "state the done-state before acting") + full isa on demand.
- **(d) full isa always-on** — rejected; reverses the minimalism thrust.

(b) keeps the heavy discipline out of base context, preserves minimalism, but counters the routing-compliance gap with a cheap reminder.

## The nudge (TO BE WIRED — not yet active)
Once the skill content is ported (the ⟪…⟫ sections of [../SKILL.md](../SKILL.md) are filled), add this one line to the relevant `AGENTS.md`:

> For non-trivial or goal-ambiguous work, invoke the `isa` skill before executing.

**Not wired yet** because a nudge to an empty/scaffold skill would degrade sessions (the model would load an incomplete skill). Activation is a separate step, pending:
1. The source isa content being ported.
2. A scope decision: repo-only (this repo's `AGENT.md`) vs global (`~/.pi/agent/AGENTS.md`) — i.e. should isa be suggested everywhere or only when working in this repo.

## Open questions (for when the source skill arrives)
- **Scope of the discipline:** full isa (interview + score + reconcile) or just the trimmed completeness gate?
- **Threshold:** is ~0.7 the right completeness gate cut-off, or did the source skill use a different bar?
- **Interview style:** does the source isa do an interactive Q&A with the user, or a self-checklist? (Affects how intrusive it is mid-session.)

---
name: isa
description: "Spec-driven execution discipline for NON-TRIVIAL or goal-ambiguous work. Before executing: articulate the ideal end state (done-state), interview to surface gaps, score the spec's completeness, reconcile until it clears a threshold — only then build. Use when the task is open-ended, the done-state is unclear, or the work is multi-step and underspecified. Do NOT use for trivial, well-specified, or one-off tasks (typos, single commands, explanations, lookups)."
license: MIT
---

# isa  *(ideal-state artifact — spec/completeness discipline)*

> **Status: SCAFFOLD.** The architecture, routing, and scope below are **decided**. The actual prompts / interview / completeness checklist are **pending** — to be ported from the source LifeOS `isa` skill (LifeOS-coupled; not imported whole — only its discipline is ported into this clean local skill). Sections marked ⟪…⟫ are placeholders for that port.

## Design decision (always-on vs on-demand)
This skill is **on-demand by design**, not an always-on rule. The reasoning is in [references/design-decision.md](references/design-decision.md). Short version: isa's value is *sharply conditional* — gold on ambiguous work, negative value on trivial work — so it must route by task, not apply to everything. The description above IS the router.

## When to use
- Open-ended or goal-ambiguous work ("improve the auth flow", "make this faster").
- Multi-step builds/refactors where "done" is not self-evident.
- Anything where success criteria are fuzzy or contested.

## When NOT to use
- Trivial / well-specified fixes (typos, off-by-one with a clear cause).
- Single commands, lookups, explanations, "what does X do".
- One-off, non-repeating tasks with an obvious answer.
*(Applying isa to these is the over-engineering this skill exists to avoid.)*

## The flow  *(decided architecture — lighter than the deleted `specloop`)*

```
1. ideal-state   articulate the done-state (ideal end state) in concrete terms
2. interview     surface gaps: what's missing/ambiguous in the spec? (ask the user)
3. gate          score the spec's completeness 0–1 against the checklist
4. reconcile     fill gaps until completeness clears the threshold (~0.7), with the user
5. execute       only now build — against the reconciled spec
```

### 1. Ideal state
⟪port the ideal-state prompt from the source skill⟫

### 2. Interview
⟪port the gap-surfacing interview from the source skill⟫

### 3. Completeness gate
⟪port the completeness checklist (the old `spec-gate.md`, lifted from isa)⟫ — see [references/completeness-gate.md](references/completeness-gate.md) *(TODO: port)*. Score 0–1; do not execute below ~0.7.

### 4. Reconcile
Iterate with the user to close gaps until the gate clears.

### 5. Execute
Build against the reconciled spec.

## What this skill does NOT do (deliberately)
- **No memory plumbing.** Unlike the deleted `specloop`/`specloop-dev`, isa does not index/recall/capture nodes, drive `mem.py`, or persist spec/plan artifacts. The [`specloop-pi`](../specloop-pi) memory extension handles memory automatically; isa is pure execution discipline. Keeping them separate is the point.
- **No per-step nodes, no on-error recall, no outcome writes.** Those were the heavy machinery that got cut.
- **No always-on behavior.** It loads only when its description matches.

## Status
Scaffold. Pending: the source `isa` skill content to port into the ⟪…⟫ sections + [references/completeness-gate.md](references/completeness-gate.md).

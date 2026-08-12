# Process Extractor — Branching Question Bank

This is the core of the skill. Answer top to bottom, but **follow the branches** — most sections are conditional. Tag legend:

- `[P]` = only if capturing a **process** (a repeating workflow with steps)
- `[M]` = only if capturing a **methodology** (a set of principles / rules / gates that guide how work is done)
- `[SD]` = software-development add-on (merge from [software-dev.md](software-dev.md))

Ask a few questions at a time. Capture answers verbatim, then clean up.

---

## Phase 0 — Triage (always run; selects the branches)

▸ **Q0.1** Are you capturing a **process** (a repeating workflow: "we do these steps to get X done") or a **methodology** (a governing approach: "these are our principles/rules for how we decide and do work")?
- → **Process**: run `[P]` sections; skip `[M]` sections.
- → **Methodology**: run `[M]` sections; skip `[P]` sections.
- → **Both / hybrid** (e.g. a team's dev *process* that embeds a Scrum *methodology*): run both, but keep them in separate parts of the doc.

▸ **Q0.2** Is this documenting what happens **today** (as-is) or what **should** happen (to-be)?
- → **As-is** (default): proceed. Record reality, including the messy parts and workarounds. Mark any known-bad steps with ⚠️.
- → **To-be**: stop — this skill is for extraction, not design. Note it and point the user to process-design resources.

▸ **Q0.3** Is this a **software-development** context (code, releases, CI/CD, tickets, incidents)?
- → **Yes**: set the `[SD]` flag and merge the add-on questions from [software-dev.md](software-dev.md) into Phases 1–3.
- → **No**: skip `[SD]`.

▸ **Q0.4** Who is this doc **for**, and who is the **owner** (the one person accountable for keeping it correct)?
- Audience drives depth & jargon level. Owner is required (no owner = doc goes stale).

▸ **Q0.5** Roughly how long does one run of this take, and how often does it happen?
- Sets the expected granularity. A 5-minute daily task needs fewer words than a quarterly release.

**Branch summary after Phase 0:** record `{process|methodology|both}`, `{as-is}`, `{SD?}`, owner, audience, cadence.

---

## Phase 1 — Frame the boundaries (always run)

▸ **Q1.1 Trigger.** What event or signal **starts** this? (A ticket created? A calendar date? A customer request? A merge to main? A question asked 3×?)
▸ **Q1.2 End-state.** What observable thing marks it **done**? (An artifact produced? A status changed? A customer told? A release live?)
▸ **Q1.3 In scope / out of scope.** Name 1–3 things this process does **not** cover (prevents scope creep and "where does it end?" confusion).
▸ **Q1.4 SIPOC-lite.** Fill the five columns in one line each (see [frameworks.md](frameworks.md)):

| Suppliers | Inputs | Process | Outputs | Customers |
|---|---|---|---|---|
| who/what feeds it | what's consumed | (high-level, ≤7 steps) | what's produced | who uses the output |

- → If you **cannot** name a customer or an output, the boundary is wrong — go back to Q1.1/Q1.2.

`[SD]` ▸ **Q1.5** Which SDLC stage(s) does this cover? (requirements / design / build / test / review / release / operate / incident). Note cross-stage handoffs.

---

## Phase 2 — Capture the substance

### 2A. If PROCESS `[P]`

▸ **Q2P.1 Brain-dump.** List every step **as you actually do them**, in order. Don't edit yet. (Tip from Bergren: if the blank page blocks you, talk through it out loud and transcribe, or screen-record yourself doing it once.)
▸ **Q2P.2 Voice.** Rewrite each step in the **second person** ("You open…", "You send…"), not first person. Use **role titles**, never personal names.
▸ **Q2P.3 Granularity check.** Can someone who has never done it follow each step? If a step hides sub-steps an outsider wouldn't know, split it.
▸ **Q2P.4 Per step, capture:**
- **Trigger of this step** (what makes you start it)
- **Who** does it (role)
- **Tools / systems / links** used
- **Inputs** needed and **output/artifact** produced
- **Time** it typically takes (rough)

▸ **Q2P.5 Decision points → exceptions (critical).** For every step that can go more than one way, ask:
- "What if \<edge case\>?" → record the branch.
- "When do we **skip** this step?" → record the skip condition.
- "When does this need **approval**, and from whom?"
- Collect these into a **branches/exceptions** table or sub-flowchart. *This is usually the most valuable part of the doc.*

`[SD]` ▸ **Q2P.6** Per the SDLC stage, add the relevant blocks from [software-dev.md](software-dev.md) §"Per-stage capture".

### 2B. If METHODOLOGY `[M]`

▸ **Q2M.1 Core principles.** What are the 3–7 guiding beliefs/rules that shape how decisions get made here? (e.g. "trunk-based, small PRs", "ship behind a flag", "docs live next to code".)
▸ **Q2M.2 Decision gates / criteria.** At each major decision point, what must be true to proceed? (Definition of Ready, Definition of Done, release criteria, go/no-go checklist.)
▸ **Q2M.3 Roles & decision rights.** Who decides what? (Use a RACI-lite — see [frameworks.md](frameworks.md).) Who is accountable vs. consulted vs. informed?
▸ **Q2M.4 Cadence & rituals.** What recurring events enact this methodology? (standup, planning, retro, design review, on-call rotation.) One line each: purpose, frequency, owner.
▸ **Q2M.5 Tooling conventions.** Which tools are mandatory, and the conventions for using them (where tickets live, how branches are named, where decisions are recorded).
▸ **Q2M.6 Anti-patterns.** Name 2–4 things that violate this methodology, so readers recognize what "wrong" looks like.

---

## Phase 3 — Controls & maintenance (always run)

▸ **Q3.1 Definition of Done.** What must be true for the whole thing to count as correctly finished? (Checklist.)
▸ **Q3.2 Checkpoints / controls.** Where are the quality or safety gates? (reviews, approvals, automated tests, sign-offs.) What happens if a gate fails?
▸ **Q3.3 Known failure modes & fixes.** What commonly goes wrong, and what do you do when it does? (One line each.)
▸ **Q3.4 Metrics (optional).** Is anything measured? (lead time, error rate, time-to-restore.) Only if already tracked — don't invent.
▸ **Q3.5 Owner & review cadence.**
- Single **owner** (role title).
- **Last-reviewed date** + **next review** (or the **trigger** that means "review this now": e.g. tool change, reorg, repeated incidents).

---

## Phase 4 — Validate (always run)

▸ **Q4.1 Self-walk-through.** Next time you do the work, follow your own doc live. Note every place you deviated — that's a gap (either the doc is wrong, or you do a hidden step).
▸ **Q4.2 Outsider read (optional).** If you can grab one person unfamiliar with the work, have them read it and list every step they couldn't do from the doc alone, then patch those. Skip if you're truly solo — the self-walk-through in Q4.1 is the core check.
▸ **Q4.3 Trim.** Cut anything that's aspiration rather than current reality. Move rare-edge-case detail into an appendix so the main path stays scannable.

Then write the final doc with [assets/process-doc-template.md](../assets/process-doc-template.md).

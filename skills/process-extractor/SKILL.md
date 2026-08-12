---
name: process-extractor
description: Extract and document an EXISTING process or methodology by running a fast, solo, branching questionnaire. Captures as-is reality (what actually happens, not the ideal) and turns it into a clean, repeatable process doc. Tuned for software-development workflows (SDLC, branching strategy, code review, CI/CD, release, incidents) but works for any business process. Use when you need to write down how something is really done today so others can repeat it, or before improving/handing off a workflow.
license: MIT
---

# Process Extractor

This skill helps a single person quickly write down an **existing** process or methodology so it is clear, repeatable, and not trapped in one person's head. It captures **as-is reality** (what really happens), not to-be ideals.

## When to use

Use this skill when you (the person doing the work) want to:

- Write down a recurring piece of work so others can repeat it without asking you.
- Stop answering the same "how do we…" onboarding questions.
- Hand off a workflow, or audit/standardize a methodology *before* trying to improve it.

Do **not** use this for:

- Designing a brand-new process from scratch — that is process *design*, not extraction.
- One-off, non-repeating tasks.

## Recommended format: a branching questionnaire

The core of this skill is a **branching questionnaire** — see [references/question-bank.md](references/question-bank.md). For fast *solo* extraction this format beats the alternatives:

| Format | Problem for solo use |
|--------|----------------------|
| Blank template / SOP skeleton | Intimidating; hides what you don't yet know; you stare at empty headings. |
| Flat checklist of questions | Asks everything regardless of context — slow, noisy, lots of N/A. |
| **Branching questionnaire** ✅ | Drives discovery systematically **and skips irrelevant sections** based on early answers (e.g. a manual process skips CI/CD; a methodology skips step-by-step capture). |

So: **interview yourself with the branching bank, then pour the answers into the output template.**

## The flow

1. **Phase 0 — Triage.** A handful of questions decide whether you are capturing a *process* or a *methodology*, whether it is software-dev, and its scope. These answers select which later branches run.
2. **Phase 1 — Frame boundaries.** Trigger (what starts it), end-state (what marks done), in/out of scope, and a SIPOC-lite (Suppliers → Inputs → Process → Outputs → Customers).
3. **Phase 2 — Capture substance.** Numbered steps (for a process) or principles/rules/gates (for a methodology), each with roles, tools, and **decision branches / exceptions** ("if X then Y else Z").
4. **Phase 3 — Controls & maintenance.** Definition of Done, checkpoints, single owner, last-reviewed date, review cadence, change triggers.
5. **Phase 4 — Validate.** Self-walk-through the draft against reality while doing the work once; fix gaps; then finalize using [assets/process-doc-template.md](assets/process-doc-template.md).

If the context is software development, **merge** the add-on questions in [references/software-dev.md](references/software-dev.md) into Phases 1–3.

## How the agent should run this skill

When invoked, the agent:

1. Reads [references/question-bank.md](references/question-bank.md). (Inline links there point to [references/frameworks.md](references/frameworks.md) for SIPOC/RACI explanations — follow them if the user is unfamiliar with a framework.)
2. Runs **Phase 0 (Triage)** with the user first and records the branch choices.
3. If triage says software-dev, also reads [references/software-dev.md](references/software-dev.md).
4. Asks the remaining questions **a few at a time**, following only the branches the triage selected. Never dumps the whole bank at once.
5. At every decision point, explicitly asks the **"what if…?"** exception questions so the doc captures branches, not just the happy path.
6. Writes the result to `process-doc.md` (or a path the user chooses) using [assets/process-doc-template.md](assets/process-doc-template.md) as the structure.
7. Offers to render a Mermaid flowchart of the main path plus exception branches.

Target: ~20–40 minutes of questions for a typical process. This is built for one person capturing their own work — no committee interviews required.

## Reference index

- [Question bank (branching)](references/question-bank.md) — the core
- [Software-development add-ons](references/software-dev.md) — SDLC branches merged into phases
- [Frameworks](references/frameworks.md) — SIPOC, as-is analysis, RACI, BPMN notes
- [Sources](references/sources.md) — every source this skill draws on, with what each contributed
- [Output template](assets/process-doc-template.md) — the final doc structure

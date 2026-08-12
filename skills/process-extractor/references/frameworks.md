# Frameworks Used by This Skill

Short, practical notes on the frameworks the question bank leans on. These are the source of the structure — you don't need to master them, just recognize where each shows up.

## SIPOC (high-level boundary map)

From Six Sigma. Maps a process on five columns so you can pin down its edges fast — used in Phase 1 (Q1.4).

| Letter | Means | Ask |
|---|---|---|
| **S** | Suppliers | Who/what provides the inputs? |
| **I** | Inputs | What is consumed to produce the output? |
| **P** | Process | The high-level steps (keep to ~4–7) |
| **O** | Outputs | What tangible outcome comes out? |
| **C** | Customers | Who uses that output? |

Rule of thumb: if you can't fill **Outputs** or **Customers**, your boundary is wrong — widen or narrow the process until you can.

## As-Is process analysis (current-state capture)

From Lucid's current-state methodology. The reason this skill insists on **as-is**: you can't improve a process you haven't accurately described, and people routinely document what they *wish* happened instead of what does. Three phases:

1. **Research** — gather how it really runs (here: self-interview + one live walk-through, not a committee).
2. **Document** — write it down in a map/steps (here: the output template + optional flowchart).
3. **Analyze** — find gaps, bottlenecks, exceptions (here: Phase 4 validation surfaces these).

Future-state (to-be) mapping is explicitly **out of scope** for this skill.

## RACI-lite (decision rights)

For methodology docs (Phase 2B) and any step needing approval. One role per cell:

- **R**esponsible — does the work.
- **A**ccountable — owns the outcome, final say (exactly one).
- **C**onsulted — asked before; two-way.
- **I**nformed — told after; one-way.

For solo/fast docs you usually only need **A** (who decides) and **R** (who does); add C/I where handoffs exist.

## 10-step process documentation (IT Glue) — what we kept

The full IT Glue model has 10 steps. This skill folds the useful ones into the branching bank rather than running them linearly:

| IT Glue step | Where it lives here |
|---|---|
| 1 Identify the process | Phase 0 triage |
| 2 Determine scope | Phase 1 (Q1.3) |
| 3 Determine boundaries | Phase 1 (Q1.1, Q1.2, Q1.4 SIPOC) |
| 4 Identify inputs/outputs | Phase 1 SIPOC + Phase 2 per-step |
| 5 Organize steps | Phase 2A |
| 6 Define roles | Phase 2 per-step + RACI-lite |
| 7 Visualize | Phase 4 (optional Mermaid) |
| 8 Document exceptions | Phase 2 Q2P.5 (the branching heart) |
| 9 Set controls | Phase 3 (Q3.2) |
| 10 Publish & test | Phase 4 validation |

## BPMN (optional, for flowcharts)

Business Process Model & Notation — the standard for drawing processes. For solo docs a simple **Mermaid flowchart** with the main path plus diamonds for decision/exception branches is enough and renders anywhere markdown does. Only reach for full BPMN if the process is complex and shared with process/analytics teams.

## Bergren writing rules (voice & clarity)

Applied in Phase 2A (Q2P.2–Q2P.3) and the output template:

- Second person ("You…"), never first person.
- Role titles, never personal names (people change).
- No unexplained jargon/abbreviations.
- Small, atomic steps — "could a smart newcomer follow this?"
- Think of it as a **recipe**: do this, then this, then this.
- Living document: first draft won't be perfect; refine by doing the work with the doc open.

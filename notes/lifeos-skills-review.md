# LifeOS Skills Review

**Date:** 2025-08-08
**Source:** https://ourlifeos.ai/skills/ (47 skills)
**Goal:** Evaluate LifeOS skills against this repo's philosophy — *perimeter-delimited, fast, very efficient, minimal overlap, no brain-mimicry, bare-minimum context loading.*

---

## Methodology

Each skill was scored on four criteria derived from the repo's purpose:

1. **Crisp perimeter** — one clear job, no scope creep.
2. **Low overlap** — doesn't duplicate an existing/planned skill.
3. **Not brain-mimicry** — no "digital brain / life-OS" substrate (the explicit rejection).
4. **Minimal context load** — cheap to load and run; not a multi-agent monster.

A skill must pass all four to land in **Tier 1**.

---

## Tier 1 — Strong fit (recommend keeping / porting)

| Skill | Perimeter | Why it fits |
|---|---|---|
| **bitterpillengineering** | Audit/trim over-prompting in instruction files (CUT/RESOLVE/MERGE/SHARPEN + token savings) | Directly serves "no extra fluff." Self-cleaning meta-skill. |
| **evals** | Score agent transcripts — 3 grader types, pass@k / pass^k | Core for validating a skill system. Low overlap. Minor LifeOS coupling, portable. |
| **hardening** | Property + mutation testing (fast-check, stryker, jscpd) | Sharp dev-testing skill. Strongly aligned with quality/efficiency. |
| **prompting** | Meta-prompting stdlib (generate/optimize/compose prompts as output) | Distinct perimeter: prompt-as-output. Supports the memory/meta layer. |
| **rootcauseanalysis** | Post-failure diagnosis (5-why, fishbone, FMEA, fault tree) | Distinct from process-extractor (captures *how*) — this finds *why it broke*. |
| **redteam** | Pre-failure adversarial attack (decompose→attack→steelman→counter) | Distinct from RCA (post-mortem). Crisp perimeter. |
| **arxiv** | Academic paper search + alphaxiv overviews | Concrete data-retrieval skill, zero fluff. |
| **audioeditor** | whisper → claude classify → ffmpeg cut (audio/podcast cleanup) | Concrete, technical, non-brain pipeline. Good minimal-skill template. |

## Tier 2 — Borderline (your call)

| Skill | Concern |
|---|---|
| **research** | Useful (verified multi-agent web research) but **heavy** — fights the "minimal context" rule. |
| **extractwisdom** | Real capability (media → insights) but **fluffy branding** ("wisdom domains", 5 depth levels). Needs de-fluffing. |
| **delegation** | Efficiency-aligned (parallel agents/worktrees) but **6 patterns = heavy**; references "The Algorithm" (LifeOS). |
| **biascheck** | Solid + low overlap, just niche-ish. Fine to keep. |
| **createcli** | Clean codegen but **TS-specific** and orthogonal to the "skill & memory" goal. |

---

## Rejected (34) — reason in ≤10 words

**Brain-mimicry / LifeOS substrate (explicitly unwanted):**
- `telos` — core brain-mimicking goals/beliefs/narratives store.
- `daemon` — LifeOS public-profile vanity manager.
- `lifeos` — LifeOS install/bootstrap, foreign system.
- `isa` — LifeOS ideal-state artifact, stack-coupled. *(see Field Notes — architecture worth stealing)*
- `interview` — LifeOS-brain check-in, telos-file dependent.
- `upgrade` — LifeOS self-upgrade meta, stack-tied.
- `migrate` — LifeOS taxonomy importer, stack-tied.
- `contextsearch` — LifeOS internal memory-search, registry-tied.
- `knowledge` — LifeOS-tied knowledge-graph archive.

**Cognitive-fluff frameworks (overlap each other + brain-flavor):**
- `apertureoscillation` — cognitive scope-framing exercise, brain-fluff.
- `becreative` — meta-cognitive divergent-ideation theatre.
- `ideate` — multi-cycle ideation engine, overlaps becreative.
- `iterativedepth` — multi-lens exploration theatre, overlaps council.
- `council` — meta multi-agent debate theatre, overlaps redteam.
- `firstprinciples` — cognitive reasoning framework, brain-fluff.
- `science` — meta problem-solving framework, overlaps RCA.
- `systemsthinking` — cognitive systems-analysis framework, overlaps RCA.
- `loop` — meta iterative-refinement loop, overlaps optimize.
- `optimize` — meta hill-climb loop, overlaps evals.
- `worldthreatmodel` — heavy long-horizon scenario engine, overlaps redteam.

**Heavy / niche / external-dep:**
- `art` — heavy multi-model media-generation pipeline.
- `webdesign` — heavy web-design pipeline, broad overlap.
- `remotion` — niche React video-rendering pipeline.
- `writestory` — creative-fiction scaffolding, content-gen niche.
- `sales` — marketing pipeline, overlaps art + writing.
- `interceptor` — macOS GUI automation, tight stack coupling.
- `fabric` — 240-pattern grab-bag, maximal overlap by design.
- `apify` — requires paid Apify account.
- `brightdata` — requires paid Bright Data account.

**Just niche / low-value:**
- `localintelligence` — US civic-data aggregator, niche external APIs.
- `usmetrics` — US-only government indicators, niche APIs.
- `aphorisms` — niche quote-database CRUD.
- `privateinvestigator` — niche OSINT people-finding, limited utility.
- `createskill` — LifeOS-internal skill scaffolding orchestrator.

---

## Worth stealing as *design reference* (not as a skill)

- **`isa`** + its memory graph — the closest thing to the "spec-driven + memory" loop we want. Don't port as-is (LifeOS-coupled); **mine the architecture**: spec → interview → score completeness → reconcile → persist with provenance.
- **`knowledge`** / **`contextsearch`** — typed graph + topic/date recall. Good schema reference for a memory layer, but wired to LifeOS's brain model.

---

## Field notes — actual usage feedback

Skills I (the user) ran for a while, with real-world takeaways:

- **`telos`** — Interesting as a *self / personal-dev* tool. **Low value for AI sessions** — at most, useful to sanity-check a decision against personal values. Not worth a permanent slot.
- **`isa`** — Genuinely interesting and works well in practice. Effectively **"spec-driven development with memory."** This is the seed of the new skill (see `specloop/`).
- **`superpowers`** — Used heavily, liked it. **Open question: does it embed any memory?** Needs verification before deciding whether to keep or fold its good parts into the new spec-driven skill.

---

## Next step

Build a **spec-driven development skill backed by persistent memory** — prompt → index (RAG) → spec → optional plan → execute → per-step review, with all errors/outcomes captured and recalled on the next prompt and on any failure.

Draft lives in `specloop/SKILL.md`.

# Software-Development Add-On Questions

Merge these into Phases 1–3 whenever triage (Q0.3) sets the `[SD]` flag. They are what turn a generic process doc into one that actually reflects how a software team works.

## Methodology flavor (run once, early — affects everything else; applies whether capturing a `[P]` process or `[M]` methodology)

▸ Which methodology does this team actually follow? (Scrum / Kanban / Shape Up / SAFe / something custom / "none, we just ship".) Record the *real* one, not the aspirational one.
▸ What is the planning cadence and unit of work? (sprint length, story/issue unit, estimate method if any.)
▸ Where is the single source of truth for "what are we working on"? (Jira, Linear, GitHub Issues, a board.)

## Per-stage capture `[P]`

Pick the block(s) matching the SDLC stage(s) from Q1.5.

### Requirements / design
▸ Where do requests/specs live, and what makes one "ready to build" (Definition of Ready)?
▸ Is there a design/RFC step? Where are design decisions recorded and for how long?

### Build / version control
▸ Branching strategy? (trunk-based / feature branches / GitFlow / PR-per-task.) Branch naming convention?
▸ What must be true before code is committed/pushed? (local tests, formatting, signed commits, conventional commits.)

### Code review
▸ What makes a PR mergeable? (Definition of Done for a PR: reviewers count, approvals, CI green, tests added, docs updated.)
▸ Typical review SLA and who can approve what (code-owners, required reviewers)?
▸ How are large/risky changes handled differently? (stacked PRs, feature flags, design review first.)

### Test
▸ What tests are mandatory and at which level? (unit / integration / e2e / contract.)
▸ Where do tests run (local, pre-merge CI, nightly)? What blocks a merge?

### Release / deploy
▸ What is the path from merge to production? (auto-deploy on merge / scheduled release / manual promotion / canary.)
▸ Environments (dev/staging/prod) and what each is for; how data/secrets are handled.
▸ Feature flags / dark launch? Rollback procedure — who can do it and how fast?
▸ Release notes / changelog: who writes them, where, format.

### Operate / on-call
▸ Who is on-call and how is it rotated? Severity levels and response targets?
▸ Where do alerts go, and what runbook/playbook accompanies a major alert?

### Incident / change
▸ When something breaks: declare, communicate, mitigate, resolve, postmortem — one line each, with **who** does it.
▸ Postmortem format (blameless?) and where they live; what triggers a process/doc update afterward?

## Controls `[SD]` (merge into Phase 3)

▸ Definition of Done for a work item (distinct from PR DoD): tests pass, reviewed, deployed, docs updated, ticket closed with outcome noted.
▸ Security/compliance gates: SAST/SCA, secret scanning, dependency policy, required approvals for prod.
▸ Observability minimum: what must a service ship with to count as done? (metrics, logs, traces, dashboards, alerting.)

## Anti-patterns to name explicitly `[M]`

Common ones worth calling out so the doc says what "wrong" looks like:
- Long-lived feature branches / infrequent merges.
- Direct pushes to main / deploys without CI green.
- "Works on my machine" — no reproducible build.
- Secrets in code or logs; prod access without review.
- Shipping without metrics/alerts; no rollback plan.
- Decisions made in DMs, not recorded.

## Tip

Software processes drift fast because tooling changes. Make the **change triggers** (Q3.5) concrete for dev docs: e.g. "review this when CI provider, branching model, or deploy target changes, or after any SEV incident."

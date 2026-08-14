# Skill Usage Report

Generated: 2026-08-07

**Sources scanned:** `~/.claude/projects/`, `~/.claude-backup-20260528/projects/`, `~/.claude-backup-20260724/projects/` (845 unique session transcripts after deduping sessions that exist in both the live directory and a backup).

**Method:** counted every `Skill` tool call (`{"skill": "<name>"}`) in the transcripts, plus slash-command invocations (`<command-name>`) that map to a skill of the same name (e.g. `/Interview` → the Interview skill, `/init` → the init skill). Aliases were merged (`ContextSearch` = `context-search`, `pai:algorithm` = `Algorithm`, `Upgrade`/`PAIUpgrade` = `/upgrade`).

## Skills used, by frequency

| # | Skill | Times used |
|---|-------|------------|
| 1 | Interview | 37 |
| 2 | ISA | 19 |
| 3 | init | 10 |
| 4 | Interceptor | 8 |
| 5 | IterativeDepth | 7 |
| 6 | Telos | 7 |
| 7 | Upgrade / PAIUpgrade | 7 |
| 8 | FirstPrinciples | 5 |
| 9 | ApertureOscillation | 5 |
| 10 | ContextSearch | 3 |
| 11 | CreateSkill | 3 |
| 12 | SystemsThinking | 3 |
| 13 | update-config | 2 |
| 14 | RootCauseAnalysis | 2 |
| 15 | BlogPost | 2 |
| 16 | Algorithm | 1 |
| 17 | Migrate | 1 |
| 18 | BeCreative | 1 |
| 19 | Art | 1 |
| 20 | BlogSlides | 1 |

**Total tracked invocations: 125**

## Not counted above (Claude Code / MCP built-ins, not LifeOS skills)

These slash commands showed up in the same scan but aren't LifeOS skills — listed for transparency, not merged into the table:

| Command | Times used |
|---------|------------|
| /compact | 28 |
| /login | 15 |
| /reload-skills | 13 |
| /chrome-devtools-mcp:chrome-devtools | 10 |
| /plan | 7 |
| /extra-usage | 7 |
| /doctor | 4 |
| /mcp | 3 |
| /skills | 2 |
| /remote-control | 1 |
| /plugin | 1 |

## Caveats

- Only counts what's preserved in stored session transcripts — deleted/rotated sessions or work done outside Claude Code (e.g. Pulse, cron/Arbol runs without a saved transcript) aren't reflected.
- Skills invoked implicitly by subagents inside a `Task`/`Agent` call, without a direct `Skill` tool call in the parent transcript, aren't counted separately.
- `/plan` was excluded from the skill table because it's ambiguous whether it's plan-mode toggling (built-in) or the `Plan` agent — worth a manual check if you care about that number specifically.

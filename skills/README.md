# AGENT.md

This repository is a collection of skills for the [pi](https://github.com/badlogic/pi-coding-agent) agent. Each skill lives in its own subfolder.

## Repository Layout

```
skills/
├── AGENT.md          # This file
├── LICENSE
└── <skill-name>/     # One folder per skill
    └── SKILL.md      # Required entry point
```

To add a new skill, create a subfolder and put a `SKILL.md` inside it. Folders without a `SKILL.md` are **not** skills — e.g. `specloop-core/` is a shared python library and `specloop-pi/` is a pi *extension* (loaded via `pi -e .../extension.ts`).

## Skill Structure

A skill is a directory containing a `SKILL.md` file. Everything else is freeform.

```
my-skill/
├── SKILL.md          # Required: frontmatter + instructions
├── scripts/          # Optional helper scripts
├── references/       # Optional detailed docs loaded on-demand
└── assets/           # Optional static assets
```

### SKILL.md Format

```markdown
---
name: my-skill
description: What this skill does and when to use it. Be specific.
---

# My Skill

## Setup

Run once before first use:
\`\`\`bash
npm install
\`\`\`

## Usage

\`\`\`bash
./scripts/process.sh <input>
\`\`\`
```

Reference scripts and assets with **relative paths** from the skill directory:

```markdown
See [the reference guide](references/REFERENCE.md) for details.
```

## Frontmatter

Per the [Agent Skills specification](https://agentskills.io/specification):

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | 1-64 chars. Lowercase a-z, 0-9, hyphens. No leading/trailing or consecutive hyphens. |
| `description` | Yes | Max 1024 chars. What the skill does and **when** to use it. Determines when the agent loads the skill. |
| `license` | No | License name or reference to a bundled file. |
| `compatibility` | No | Max 500 chars. Environment requirements. |
| `metadata` | No | Arbitrary key-value mapping. |
| `allowed-tools` | No | Space-delimited list of pre-approved tools (experimental). |
| `disable-model-invocation` | No | When `true`, skill is hidden from system prompt; users must invoke via `/skill:name`. |

> **Note:** Pi does **not** require `name` to match the parent directory (unlike the strict standard), which is convenient for shared skill directories like this one. Other unknown frontmatter fields are ignored.
> **Important:** A skill with a missing `description` is not loaded.

## How Skills Are Loaded

1. At startup pi scans skill locations and extracts each skill's name and description.
2. Available skills are listed in the system prompt (progressive disclosure).
3. When a task matches, the agent reads the full `SKILL.md` on demand.
4. The agent follows the instructions, using relative paths to reference scripts/assets.

Skills can also be invoked directly as commands: `/skill:<name>`.

## References

- [Pi Skills documentation](https://github.com/badlogic/pi-coding-agent/blob/main/docs/skills.md)
- [Agent Skills specification](https://agentskills.io/specification)

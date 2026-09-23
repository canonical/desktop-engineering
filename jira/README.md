# Jira Agent Tooling

This directory is the working root for AI-assisted Jira workflows on the
Dektop team. Open it as your project folder in OpenCode to get full
agent context, skills, and practices automatically loaded.

## Prerequisites

- [OpenCode](https://opencode.ai) installed
- Jira MCP configured for `warthogs.atlassian.net`
  - Cloud ID: `220bceb6-6b32-4813-90eb-68d67c9445db`
  - The MCP server must be listed in your OpenCode config
    (`~/.config/opencode/config.json`)

## Quick Start

```bash
git clone https://github.com/canonical/desktop-engineering
cd desktop-engineering/jira
opencode
```

On first run, tell the agent your role so it loads the right persona:

> "I am a squad lead" — loads `personas/squad-lead.md`
> "I am the director" — loads `personas/director.md`
> "I am a developer" — loads `personas/developer.md`

The agent will automatically read `AGENT.md` for team context (Atlassian
config, custom fields, issue hierarchy, metrics targets).

## Available Skills

Skills are loaded automatically from `.opencode/skills/`. Each skill provides
the agent with a focused workflow for a specific task.

| Skill        | Trigger phrases | What it does                                        |
|--------------|-----------------|-----------------------------------------------------|
| *(none yet)* | —               | Skills are being developed — see Contributing below |

## Practices

Detailed lifecycle rules, grooming checklists, and interrupt workflows:

| Document                  | Covers                                                                                                 |
|---------------------------|--------------------------------------------------------------------------------------------------------|
| `practices/objectives.md` | Objective creation, grooming → Triaged, state transitions, carry-over, interrupts                      |
| `practices/epics.md`      | Epic creation, grooming → Triaged, child items, state transitions, carry-over, interrupts              |
| `practices/pulse.md`      | Story / Task / Spike creation, sizing, sprint assignment, pulse planning, velocity                     |

## Personas

| File                       | For                                                                                        |
| -------------------------- | ------------------------------------------------------------------------------------------ |
| `personas/director.md`     | Director / Product Owner — LTS Objectives, cross-squad prioritisation, interrupt triage    |
| `personas/squad-lead.md`   | Squad Leads — Release backlog, Epic ownership, pulse health per squad                      |
| `personas/developer.md`    | Individual Contributors — pulse delivery, Epic ownership, velocity, blockers               |

## Contributing

- Practice changes (grooming rules, checklists): edit `practices/*.md` and open a PR
- New skills: add a directory under `.opencode/skills/` with a `SKILL.md` and any supporting scripts
- Persona updates: edit `personas/*.md` — keep role-specific context current after each cycle
- Discuss on [`#dekstop-team-eng`](https://chat.canonical.com/canonical/channels/desktop-team-eng)

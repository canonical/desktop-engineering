# Persona: Squad Lead

Squad leads own the release backlog and pulse health for their squad. This
persona is pre-populated for all current Foundations squad leads.

---

## Squad Leads — Current Cycle

| Squad | Lead | Scope |
| ----- | ---- | ----- |
| GNOME | Daniel Van Vugt | GNOME Shell ecosystem |
| Integration | Jean-Baptiste Lallement | Lower level desktop components such as multimedia, webbrowsers, printing, accessibility |
| Apps | Didier Roche Tolomelli | In-house applications such as installer, app center, security center, TPMFDE, permission prompting |
| Enterprise | Adrian Dombeck | Enterprise application such as GPO client (adsys),  cloud authentication (authd) |
| WSL | Carlos Nihelton Santana De Oliveira | Everything WSL and container based |
| Design | Ana Sereijo | UX and Design for the Desktop |

> Update this table at the start of each cycle. See `AGENT.md` for the full
> squad roster and Jira team names.

---

## Primary Responsibilities

- **Release backlog grooming**: ensure all Epics in your squad are triaged
  before or during the SRR review process for the upcoming cycle
- **Epic quality**: verify all active Epics have Why/Who/What/Community/
  Innovation/How, t-shirt size, parent Objective, team field, and a docs
  Story child
- **Pulse health**: monitor pulse velocity for your squad members; target
  ≥ 80%
- **Child item grooming**: ensure Stories, Tasks, and Spikes have story
  points, sprint assignment, and parent set before each Pulse
- **Blocker escalation**: surface blocked items to the Director immediately;
  do not let blocked Epics sit

## Decision Authority

| Decision | Authority |
| -------- | --------- |
| Triage an Epic for the upcoming Release Cycle | Squad lead |
| Set t-shirt size on an Epic | Squad lead (with Epic owner) |
| Add/remove child Stories/Tasks/Spikes | Squad lead or Epic owner |
| Commit a new Epic to the current cycle | Squad lead + Director sign-off |
| De-commit / carry over an Epic | Squad lead + Director sign-off |
| Escalate a new Objective request | Squad lead → Director |

---

## Typical Agent Prompts

### Triage debt review for your squad

```
Show all untriaged Epics for the Apps team in the 26.10 cycle,
ordered by creation date
```

### Epic grooming quality check

```
Assess grooming quality for all active Epics in the GNOME team —
flag missing fields
```

### Pulse health overview

```
Show all active pulse items (Stories, Tasks, Spikes) for the WSL team
in the current sprint — flag those missing story points or sprint assignment
```

### Blocker check

```
List all blocked items in the Enterprise team and how long they
have been blocked
```

### Sprint planning prep

```
What Stories and Tasks in the Design team are Triaged but not yet
assigned to a sprint?
```

### Carry-over risk

```
Which Roadmap Item Epics in the Integration team are still Untriaged with
less than 3 months to cycle end?
```

---

## Pre-baked JQL Queries

### Untriaged Epics for your squad (replace team name)

```
project in (UDENG) AND issuetype = Epic AND status = Untriaged
AND "Team[Team]" = "Desktop | Integration" AND fixVersion = "26.10"
ORDER BY created ASC
```

### Active pulse items for your squad

```
project in (UDENG) AND issuetype in (Story, Task, Spike)
AND "Team[Team]" = "Desktop | GNOME" AND statusCategory != Done
AND sprint in openSprints() ORDER BY assignee ASC
```

### Epics missing t-shirt size in your squad

```
project in (UDENG) AND issuetype = Epic AND cf[10040] is EMPTY
AND "Team[Team]" = "Desktop | Enterprise" AND statusCategory != Done
```

### Items without story points in your squad

```
project in (UDENG) AND issuetype in (Story, Task, Spike)
AND cf[10016] is EMPTY
AND "Team[Team]" = "Desktop | WSL"
AND statusCategory != Done
```

### Blocked items in your squad

```
project in (UDENG) AND status = Blocked
AND "Team[Team]" = "Desktop | GNOME"
AND statusCategory != Done
```

---

## Practice References

- Epic lifecycle: `practices/epics.md`
- Pulse item lifecycle: `practices/pulse.md`
- Objective lifecycle (read-only for leads): `practices/objectives.md`
- Team context, custom fields, timeboxes: `AGENT.md`

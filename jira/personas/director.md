# Persona: Director / Product Owner

**Role:** Director, Desktop Engineering — product owner for Themes and
Objectives grooming

---

## Primary Responsibilities

- **LTS Objectives backlog**: own the full product backlog of Objectives
  across all squads for the current and next LTS cycle
- **Interrupt triage**: receive and assess ad-hoc requests; decide whether
  they become new Objectives, absorb into existing ones, or are deferred
- **Cross-squad re-prioritisation**: when new commitments arrive, assess
  impact on existing Objectives and communicate trade-offs to leads
- **Velocity oversight**: monitor team-wide pulse velocity (target ≥ 80%)
  and squad-level triage debt
- **Grooming quality**: ensure all Objectives and Epics meet creation and
  grooming criteria before commitment

## Decision Authority

| Decision | Authority |
| -------- | --------- |
| Commit / de-commit an Objective to an LTS cycle | Director |
| Commit / de-commit an Epic to a Release Cycle | Squad lead + Director sign-off |
| Re-prioritise Objectives within an LTS cycle | Director (communicate to leads) |
| Assign Objective owner | Director |
| Escalate staffing or structural concerns | Director → Engineering Manager |

---

## Typical Agent Prompts

### Objectives backlog review

```
Review all untriaged Objectives in the FR project for the 26.04 LTS cycle
```

### Interrupt assessment

```
A new request has come in: [description]. Should this be a new Objective,
absorbed into an existing one, or deferred? Check for duplicates first.
```

### Roadmap snapshot

```
Give me a roadmap snapshot for the 26.10 cycle — total Epics by squad,
status breakdown, and top triage concerns
```

### Triage debt overview

```
What is the untriaged Epic count per squad for the 26.10 cycle? Flag any
squad above 30% untriaged.
```

### Grooming quality check

```
Assess all active Objectives in the FR project against grooming criteria —
flag any missing Why, Who, What, or Docs sections
```

### Carry-over assessment

```
Which 26.10 Epics are at risk of not completing this cycle? List Roadmap
Items that are still Untriaged or have no In Progress children.
```

---

## Pre-baked JQL Queries

### All untriaged Objectives (current LTS)

```
project = UDENG AND issuetype = Objective AND status = Untriaged
AND fixVersion = "26.04 LTS" ORDER BY created ASC
```

### All Roadmap Item Epics for 26.10

```
project in (UDENG) AND issuetype = Epic AND labels = "26.10"
AND cf[10615] = "Roadmap Item" ORDER BY project ASC, status ASC
```

### Untriaged Epics by squad (replace team name as needed)

```
project in (UDENG) AND issuetype = Epic AND status = Untriaged
AND "Team[Team]" = "Desktop" ORDER BY created ASC
```

### Blocked items

```
project in (UDENG) AND status = Blocked AND statusCategory != Done
ORDER BY updated ASC
```

### Epics missing t-shirt size

```
project in (UDENG) AND issuetype = Epic AND cf[10040] is EMPTY
AND statusCategory != Done
```

### Epics missing parent Objective

```
project in (UDENG) AND issuetype = Epic
AND issueFunction in subtasksOf("issuetype = Objective") is EMPTY
AND statusCategory != Done
```

### Issues without team field

```
project in (UDENG) AND cf[10001] is EMPTY AND statusCategory != Done
AND issuetype != Objective
```

---

## Practice References

- Objective lifecycle: `practices/objectives.md`
- Epic lifecycle: `practices/epics.md`
- Pulse items: `practices/pulse.md`
- Team context, custom fields, timeboxes: `AGENT.md`

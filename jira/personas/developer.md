# Persona: Developer / Individual Contributor

Individual contributors own the delivery of pulse items and the quality of
their assigned Epics. This persona is for any Foundations team member who is
not acting as a squad lead or director.

---

## Primary Responsibilities

- **Pulse delivery**: complete assigned Stories, Tasks, and Spikes within the
  Pulse; target ≥ 80% of your committed story points done each sprint
- **Own your Epic quality**: for any Epic you own, ensure it meets grooming
  criteria before and during the cycle — description, t-shirt size, parent
  Objective, team field, and a docs Story child
- **Proactive blocking**: flag blockers to your squad lead the moment they
  appear — do not wait until the Pulse review
- **WIP discipline**: finish in-progress items before picking up new ones;
  keep your active item count low
- **Triage hygiene**: keep your assigned items free of dangling Untriaged
  work — everything in an active Pulse should be Triaged or beyond

## Decision Authority

| Decision | Authority |
| -------- | --------- |
| Create a Story / Task / Spike under your Epic | You |
| Estimate story points on your items | You (with squad lead input) |
| Move an item to In Progress / In Review / Done | You |
| Flag an item as Blocked | You — notify squad lead immediately |
| Carry over an item to the next Pulse | You + squad lead awareness |
| Create a new Epic | You + squad lead sign-off to triage it |

---

## Typical Agent Prompts

### My current pulse

```
Show all my active pulse items in the current sprint — flag any missing
story points, assignee, or parent
```

### My Epic health

```
Assess grooming quality for all Epics assigned to me — flag missing fields
or child items
```

### What should I pick up next?

```
Show all Triaged Stories and Tasks assigned to me that are not yet in a
sprint, ordered by parent Epic priority
```

### Carry-over check

```
Which of my items from the previous Pulse are still open? Should any be
re-estimated or closed?
```

### Create a new pulse item

```
I need to create a Story under Epic FR-XXXX to [description]. Help me write
a well-formed description with Why, Who, What, and How.
```

### Check my velocity

```
What is my pulse velocity for the last 3 sprints? How does it compare to
the 80% target?
```

### Blocker

```
UDENG-XXXX is blocked — [describe blocker]. Help me write a clear blocker
comment and identify who can unblock it.
```

---

## Pre-baked JQL Queries

### My active pulse items

```
assignee = currentUser() AND issuetype in (Story, Task, Spike)
AND sprint in openSprints() AND statusCategory != Done
ORDER BY status ASC
```

### My untriaged items

```
assignee = currentUser() AND status = Untriaged
AND statusCategory != Done ORDER BY created ASC
```

### My Epics (owned)
```
project in (UDENG) AND issuetype = Epic AND assignee = currentUser()
AND statusCategory != Done ORDER BY status ASC
```

### My Epics missing grooming fields

```
project in (UDENG) AND issuetype = Epic AND assignee = currentUser()
AND statusCategory != Done
AND (cf[10040] is EMPTY OR cf[10001] is EMPTY)
```

### Items I own that are blocked

```
assignee = currentUser() AND status = Blocked ORDER BY updated ASC
```

### Items assigned to me not yet in a sprint

```
assignee = currentUser() AND issuetype in (Story, Task, Spike)
AND sprint is EMPTY AND statusCategory != Done ORDER BY created ASC
```

---

## Practice References

- Pulse items (your day-to-day): `practices/pulse.md`
- Epic lifecycle (if you own Epics): `practices/epics.md`
- Objective lifecycle (read-only): `practices/objectives.md`
- Team context, custom fields, timeboxes: `AGENT.md`

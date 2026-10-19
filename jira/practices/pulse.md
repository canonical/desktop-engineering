# Pulse Items — Full Lifecycle & Best Practices

Pulse items are Stories, Tasks, and Spikes — the atomic units of work
assigned to a 2-week sprint (Pulse). Use this document when **creating,
sizing, assigning, or grooming** pulse-level work.

---

## What is a Pulse?

A Pulse is a 2-week sprint. All Canonical teams share the same sprint
numbering: `Pulse YYYY#nn` (e.g. `Pulse 2026#22`). Pulses are the primary
delivery cadence for the Foundations team.

Pulse velocity target: **≥ 80%** of committed story points completed per
Pulse. The team currently averages ~60%.

---

## Issue Types

| Type | When to use | Parent required? |
| ----- | ----------- | --------------- |
| Story | Delivers incremental user/product value; fits in one Pulse | Yes — must have a parent Epic |
| Task | Background, overhead, tech debt, or maintenance work that does not deliver direct user value | No — Tasks may be parentless if they are cross-cutting or team overhead |
| Spike | Time-boxed investigation or ideation to clarify How for a parent Epic or Story | Yes — must have a parent Epic or Story |

**If work spans more than one Pulse, it is an Epic — not a Story.**
Break it down.

---

## Creation Criteria

### Story

All of the following must be clear before creating a Story:

- **Why**: why does this story matter to the user/product? (derived from
  parent Epic)
- **Who**: who benefits from this story being done?
- **What**: what is the specific deliverable or behaviour change? Include a
  definition of done.
- **How**: how will this be implemented? The parent Epic's specification must
  be approved before the Story is triaged.

### Task

- **What**: clearly articulate what needs to be done and why it is necessary
  overhead.
- Tasks do not need a formal Why/Who/What structure, but must not be vague
  (e.g. "misc work" is not acceptable).

### Spike

- **Purpose**: clearly state what question the spike will answer or what
  decision it will enable.
- **Time-box**: spikes must have a story point estimate that fits within one
  Pulse. If the investigation cannot be completed in one Pulse, break it into
  multiple spikes.
- **Output**: define the expected output (e.g. "a decision on approach X vs
  Y", "a draft specification", "a prototype").

---

## Sizing — Story Points

Story points estimate effort relative to complexity, not time. Use the
following as a rough guide:

| Points | Effort |
| ------ | ------ |
| 1 | Trivial — a few hours |
| 2 | Small — half a day to one day |
| 3 | Medium — two to three days |
| 5 | Large — most of a Pulse for one person |
| 8 | Very large — consider breaking down; may span multiple people |
| 13+ | Too large for a pulse item — must be broken down into smaller Stories/Tasks |

A single person should carry at most **~15 story points per Pulse** across
all assigned items. Plan capacity accordingly.

---

## Pulse Planning Checklist (Grooming → Triaged)

Before a pulse item can be committed to a Pulse:

- [ ] Story points estimated (`customfield_10016`)
- [ ] Assigned to a specific Pulse / sprint
- [ ] Assignee set (a real person — not unassigned)
- [ ] Parent set (mandatory for Stories and Spikes; optional for Tasks)
- [ ] Team field (`customfield_10001`) set to the correct squad
- [ ] For Stories: parent Epic specification approved
- [ ] Detailed How specified (in the item description or parent Epic spec)
- [ ] Workload balanced across the Pulse for the assignee
- [ ] State set to `Triaged`

---

## During a Pulse

- Move item to `In Progress` when work actually starts — not at Pulse
  kickoff.
- If a blocker is encountered: set status to `Blocked`, add a comment
  describing the blocker and who can unblock it, and notify the squad lead
  immediately.
- Keep WIP low — completing in-progress items is higher priority than
  starting new ones.
- If an item will not complete this Pulse: flag it to the squad lead
  **before** the Pulse ends, not in the retro.

---

## Pulse Review & Carry-Over

At the end of each Pulse:

- Items `Done` count toward velocity. Target: ≥ 80% of committed story
  points done.
- Items not completed:
  - If still valid: carry to next Pulse (reassign sprint); re-estimate if
    scope changed.
  - If no longer needed: close as `Rejected` with a comment.
  - Do not silently leave items dangling across multiple Pulses without
    comment.

**Velocity formula:**

`velocity % = (done story points) / (committed story points) × 100`

If velocity is consistently below 80%, common causes:

- Over-commitment at planning (reduce points planned next Pulse)
- Too many parallel items per person (reduce WIP)
- Unresolved blockers accumulating (escalate earlier)
- Items too large to complete in one Pulse (break down further)

---

## State Transitions

| State | Trigger |
| ----------- | ------- |
| Untriaged | Newly created; not yet groomed |
| Triaged | Grooming checklist complete; assigned to a Pulse |
| In Progress | Work actually starts |
| In Review | Owner's work done; reviewer working on it |
| Blocked | External factor prevents progress |
| Done | Work complete and accepted |
| Rejected | No longer needed; explicitly closed |

**Rules:**

- Parent Epic must be `Triaged` before a child can be `Triaged`.
- Parent Epic moves to `In Progress` when any child starts.
- A child Story/Task/Spike moves to `In Review` when the owner is done —
  do not skip In Review for non-trivial items.

---

## Grooming Quality Checks (for Agent Assessment)

| Check | Field / Rule |
| ----- | ----------- |
| `has_story_points` | `customfield_10016` is set and > 0 |
| `has_sprint` | Sprint (Pulse) is assigned |
| `has_parent` | Parent is set (mandatory for Stories and Spikes) |
| `has_team` | `customfield_10001` is not null/empty |
| `has_assignee` | `assignee` is set |
| `status_valid` | Not `Untriaged` if sprint is active |
| `not_oversized` | Story points ≤ 8 (flag if 13+) |

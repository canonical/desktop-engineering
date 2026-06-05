# Epics — Full Lifecycle & Best Practices

Epics are the primary unit of Release Cycle planning and roadmap commitment.
They define a chunk of work deliverable within a single release cycle
(~6 months). Use this document when **creating, assessing, or grooming** an
Epic.

---

## Description Structure (Creation Criteria)

All three of Why, Who, and What must be **clearly articulated at creation
time** — stricter than Objectives. A vague Epic must not be created; write
it up properly first or create a Spike to investigate.

**Why** — motivation
: Based on the parent Objective. Must be clear and specific before creating
  the Epic.

**Who** — beneficiary / stakeholder
: Clearly identified — not just broad at this stage. Name the personas or
  teams who benefit.

**What** — value / deliverable
: Clearly articulated scope and definition of done for this Epic. Specific
  enough to know when the Epic is finished.

**Community**
: Is this Epic suitable for community engagement (mailing list, Discourse,
  blog post)? State yes/no and what kind.

**Innovation**
: Does it give Ubuntu any unique advantages? What competitive or technical
  differentiation does this create?

**How** (broad ideas)
: Propose at a high level how the work will be done, preferably referencing
  a draft specification.

---

## Ownership & Parenting

- Must have a **parent Objective**.
- Assign to a **team lead or team member** who understands the full scope or will primarily work on it.
- Created in `Untriaged` state.
- One person can carry at most **one XL Epic** per release cycle. Plan capacity accordingly.

---

## Grooming → Triaged (Release Backlog Grooming)

Performed during Release Backlog grooming (SRR review process for the
upcoming cycle).

**Grooming checklist:**

- [ ] Why, Who, and What are clear and confirmed
- [ ] Community and Innovation sections present
- [ ] Specification draft started (high-level How)
- [ ] Priority established relative to other triaged Epics in the Release Backlog
- [ ] T-shirt size recorded in `customfield_10040` (XS / S / M / L / XL)
  - One person can carry at most one XL per cycle
  - Workload balanced against team capacity
- [ ] Parent Objective is set and is `Triaged`
- [ ] Team field (`customfield_10001`) set to the correct squad
- [ ] FixVersion set to target Release Cycle (e.g. `26.10`)
- [ ] If roadmap committed: release label added (e.g. `26.10`) and `customfield_10615` set to `"Roadmap Item"`
- [ ] Broken down into child Spikes, Stories, and Tasks (initially Untriaged)
- [ ] A **docs Story** created as a child issue
- [ ] State set to `Triaged`

---

## Child Work Items

Every Epic must have at least one child issue. A **docs Story** is mandatory
for every Epic.

| Type | Purpose | Creation Criteria | Sized by |
| ----- | ------- | ----------------- | -------- |
| Spike | Investigation / ideation to clarify How | Purpose clearly articulates what will be learned | Story points |
| Story | Incremental value; ideally fits in one Pulse | Why/Who/What clear, How specified, parent Epic spec approved | Story points |
| Task | Non-value work (tech debt, background, overhead) | What clearly articulated | Story points |
| Docs | Documentation Story — mandatory for every Epic | What / scope of docs clearly stated | Story points |

---

## Child Item Grooming → Triaged (Pulse Backlog Grooming)

Before a Story, Task, or Spike can be assigned to a Pulse:

- [ ] Story points estimated (`customfield_10016`)
- [ ] Assigned to a specific Pulse (sprint)
- [ ] Detailed How specified (in the item or parent Epic spec)
- [ ] Parent Epic spec is approved (critical for Stories)
- [ ] Workload balanced across the Pulse
- [ ] Team field (`customfield_10001`) set
- [ ] State set to `Triaged`

See `practices/pulse.md` for full pulse-level grooming rules.

---

## Ongoing State Transitions

| State       | Trigger                                                     |
|-------------|-------------------------------------------------------------|
| Triaged     | Grooming checklist complete; added to Release Backlog       |
| In Progress | Work actually starts; parent Objective also set In Progress |
| In Review   | Owner's work done; reviewer identified early                |
| Blocked     | External factor halts all progress                          |
| Done        | All child items Done; delivery to product complete          |
| Rejected    | Work is no longer needed; explicitly closed                 |

**State rules:**

- Parent Objective must be `Triaged` before the Epic can be `Triaged`.
- An Epic moves to `In Progress` when any child starts; do not wait until
  all children are active.
- An Epic is `Done` only when **all** child items are `Done`.
- Identify a reviewer early — do not wait until the Epic is done to start
  In Review.

---

## Missing Commitments (Carry-Over)

If a Roadmap Item Epic is not completed by end of its Release Cycle:

1. Add new release label (e.g. `27.04`)
2. Update `FixVersion` to the next cycle
3. Communicate carry-over to the Objective lead and Director
4. Re-assess t-shirt size — scope may have changed

---

## Interrupts — Ad-hoc Epic or Child Item Requests

| Urgency | Issue Type | Action |
| ------- | ---------- | ------ |
| NOW / ASAP | Story/Task/Bug | Add to current Pulse; communicate to leads — something may need dropping |
| NOW / ASAP | Epic | Create Epic; communicate to leads — this impacts the Release Backlog |
| Next Pulse | Story/Task/Spike | Treat as regular new work; apply pulse grooming criteria |
| Next Cycle | Epic | Treat as regular new work; apply release grooming criteria |

**Steps:**

1. **Check scope** — does an existing Epic already cover this? If so, add a
   child item rather than a new Epic.
2. **Identify timebox** — NOW/ASAP requires immediate lead communication;
   future timeboxes follow normal grooming.
3. **Choose issue type** — Epic (>1 pulse, <1 cycle), Story (incremental
   value, 1 pulse), Task (non-value), Bug (defect).
4. **Assign owner** — Epic: objective lead + Epic owner; Story/Task/Spike:
   team member.
5. **Apply grooming criteria** for the appropriate level.

---

## Grooming Quality Checks (for Agent Assessment)

| Check | Field / Rule |
| ----- | ------------ |
| `has_why` | Description contains a clear "Why" section |
| `has_who` | Description contains a clear "Who" section |
| `has_what` | Description contains a clear "What" section |
| `has_community` | Description contains a "Community" section |
| `has_innovation` | Description contains an "Innovation" section |
| `has_how` | Description contains a "How" section |
| `has_tshirt_size` | `customfield_10040` is not null |
| `has_fix_version` | `fixVersions` is not empty |
| `has_parent_objective` | Parent is set and is an Objective |
| `is_roadmap_item` | `customfield_10615 == "Roadmap Item"` (if committed) |
| `has_team` | `customfield_10001` is not null/empty |
| `has_owner` | `assignee` is set |

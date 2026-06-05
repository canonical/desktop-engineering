# Objectives — Full Lifecycle & Best Practices

Objectives are the primary unit of LTS-level planning. They define what the
Desktop team commits to deliver within an LTS cycle (~2 years). Use this
document when **creating, assessing, or grooming** an Objective.

---

## Description Structure (Creation Criteria)

Every Objective description must contain the following four sections. **Why
must be clear at creation time.** Who and What may be broad or imprecise
initially.

**Why** — motivation
: Clearly articulate why this work is needed and how it aligns with
  Desktop team's value propositions. This is the minimum requirement to create
  an Objective. Without a clear Why, do not create the Objective.

**Who** — beneficiary / stakeholder
: Identify who benefits. Can be broad (e.g. "Enterprise developers", "OEM
  partners", "all users") at creation time.

**What** — value / deliverable
: Describe the value or outcome at a high level. More specific than a Theme,
  but does not need to be precise at creation time.

**Docs** — documentation planning
: Every Objective must include a Docs section covering documentation planning
  and scoping. Mandatory — even if the initial entry is "TBD, scoped with
  Objective owner before triaging".

---

## Ownership & Parenting

- Assign to a **senior team member, architect, or SME** who will lead the
  Objective.
- If a parent Theme exists, parent the Objective to it (Themes not currently
  active but may be used in future).
- Created in `Untriaged` state in the Full Backlog.
- FixVersion set to target LTS cycle at creation (e.g. `26.04 LTS`).

---

## Grooming → Triaged (Product Backlog / LTS Grooming)

Performed before the first Product roadmap sprint of the upcoming LTS cycle,
or whenever a new Objective is committed to the current cycle.

> Before committing a new Objective to the **current** LTS cycle,
> re-prioritisation of already committed Objectives must be considered and
> communicated to leads.

**Grooming checklist:**

- [ ] Why is clearly articulated and confirmed with relevant stakeholders
- [ ] Standard spec draft started to detail the What (may start as a
      braindump)
- [ ] Creation criteria verified: Why clear, Who and What recorded
- [ ] Docs section present (at minimum a placeholder with scoping intent)
- [ ] Priority established relative to other triaged Objectives in the
      Product Backlog
- [ ] FixVersion set to target LTS cycle (e.g. `26.04 LTS`)
- [ ] Broken down into child Epics (initially Untriaged) — or at least one
      child Spike if investigation is needed first
- [ ] Child Spikes created if investigation is needed before Epics can be
      defined
- [ ] State set to `Triaged`

---

## Ongoing State Transitions

| State       | Trigger                                              |
|-------------|------------------------------------------------------|
| Triaged     | Grooming checklist complete; priority established    |
| In Progress | First child Epic moves to In Progress                |
| In Review   | Child Epics are in review (if applicable)            |
| Blocked     | External factor halts progress on all child Epics    |
| Done        | All child Epics are Done                             |
| Rejected    | Work is no longer needed; explicitly closed          |

**State rules:**

- Parent chain (Objective) must be `Triaged` before a child Epic can be `Triaged`.
- Parent chain should move to `In Progress` when a child moves to`In Progress`.
- An Objective is `Done` only when **all** child Epics are `Done`.

---

## Missing Commitments (Carry-Over)

If an Objective is not completed by the end of its LTS cycle:

1. Update `FixVersion` to the next LTS cycle
   (e.g. `26.04 LTS` → `28.04 LTS`)
2. Re-prioritise against new and existing Objectives for the incoming cycle
3. Communicate carry-over to leads and document reason

Do not silently carry over without re-prioritisation — carried Objectives
compete with new commitments.

---

## Interrupts — Ad-hoc Objective Requests

When a new urgent request arrives that may become an Objective:

1. **Check for duplicates** — if an existing Objective already covers it,
   update that one instead of creating a new one.
2. **Identify timebox** — typically the next LTS cycle. If the current cycle
   is requested, re-prioritisation of committed Objectives is required;
   communicate with Director and leads.
3. **Apply creation criteria** — Why (clear), Who, What, Docs section
   (placeholder).
4. **Assign owner** — escalate to Director / seniors / architects for
   grooming.
5. **Apply LTS grooming criteria** — prioritise against existing backlog;
   communicate with leads if re-prioritisation is needed.

---

## Grooming Quality Checks (for Agent Assessment)

| Check | Field / Rule |
| --- | --- |
| `has_why` | Description contains a "Why" section with non-trivial content |
| `has_who` | Description contains a "Who" section |
| `has_what` | Description contains a "What" section |
| `has_docs` | Description contains a "Docs" section |
| `has_fix_version` | `fixVersions` is not empty |
| `has_owner` | `assignee` is set |
| `state_valid` | If children exist and are In Progress, Objective should be In Progress |

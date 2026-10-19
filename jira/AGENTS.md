# Jira Team Context

## User

Load your persona from `personas/` to tailor agent behaviour to your role:

- **Director / Product Owner** → `personas/director.md`
- **Squad Lead** → `personas/squad-lead.md`
- **Developer / Individual Contributor** → `personas/developer.md`

## Atlassian

- **Site:** [warthogs](https://warthogs.atlassian.net)
- **Cloud ID:** `220bceb6-6b32-4813-90eb-68d67c9445db`

## Projects

| Project Key | Project Name        |
|-------------|---------------------|
| UDENG       | Desktop Roadmap     |

## Team

The authoritative roster of all Desktop team members is maintained in
the GitHub team:
[IS Platform Services: Desktop](https://github.com/orgs/canonical/teams/is-platform-services-desktop)

## Squads

| Squad                    | Project | Jira Team Name (`customfield_10001`)  |
|--------------------------|---------|---------------------------------------|
| GNOME Team               | UDENG   | Desktop \| GNOME                      |
| Integration Team         | UDENG   | Desktop \| Integration                |
| Apps Team                | UDENG   | Desktop \| Apps                       |
| Enterprise Team          | UDENG   | Desktop \| Enterprise                 |
| Core Desktop Team        | UDENG   | Desktop \| Core                       |
| WSL Team                 | UDENG   | Desktop \| WSL                        |
| Design Team              | UDENG   | Desktop \| Design                     |

## Issue Hierarchy

`Objectives > Epics > Stories / Tasks / Spikes`

| Issue Type | Timebox       | Sized by     | Notes                                              |
|------------|---------------|--------------|----------------------------------------------------|
| Objective  | LTS Cycle     | -            | Owned/triaged by director or senior leads          |
| Epic       | Release Cycle | T-shirt size | Roadmap commitment; max XL per person per cycle    |
| Story      | Pulse         | Story points | Delivers incremental value; fits in one pulse      |
| Task       | Pulse         | Story points | Background/overhead work; may not have parent Epic |
| Spike      | Pulse         | Story points | Investigation/ideation to break down parent work   |

## Key Custom Fields

| Field        | Jira ID             | Notes                                            |
|--------------|---------------------|--------------------------------------------------|
| Team         | `customfield_10001` | Squad name (see Squads table)                    |
| T-shirt size | `customfield_10040` | XS, S, M, L, XL — used on Epics                  |
| Roadmap Item | `customfield_10615` | Value `"Roadmap Item"` — marks Epic as committed |
| Story Points | `customfield_10016` | Used on Stories, Tasks, Spikes — **Note:** the API returns story points in `customfield_10024` (not `customfield_10016`) in issue responses; use `customfield_10016` in JQL but read `customfield_10024` from results |

Note: in JQL, `customfield_NNNNN` is written as `cf[NNNNN]`.

> **JQL limitation — Team field filtering:** Filtering by team (`cf[10001]`
> or `"Team[Team]"`) combined with a `sprint =` clause returns no results
> due to a Jira API limitation on this instance. **Workaround:** omit the
> team filter from JQL, fetch all sprint items, then filter locally by
> `customfield_10001.name` in the returned JSON.

## Timeboxes

| Timebox       | Duration  | Jira representation                                 |
|---------------|-----------|-----------------------------------------------------|
| LTS Cycle     | ~2 years  | FixVersion e.g. `26.04 LTS`                         |
| Release Cycle | ~6 months | FixVersion e.g. `26.10`                             |
| Pulse         | 2 weeks   | Sprint, named `Pulse YYYY#nn` e.g. `Pulse 2025#01`  |

- Pulse is the internal name for a Jira sprint — all Canonical teams share
  the same sprint numbering. `#nn` is the sequential sprint number for the
  year.
- Roadmap Items are Epics with `customfield_10615 = "Roadmap Item"` plus a
  release label (e.g. `26.10`).
- Uncompleted Roadmap Items are carried over: new label added, FixVersion
  updated.

## Issue States

`Untriaged` → `Triaged` → `In Progress` → `In Review` → `Done`
(or `Blocked` / `Rejected`)

- Parent chain must be marked Triaged before a child can be Triaged.
- Parent chain should be marked In Progress when a child moves to In Progress.
- Parent is Done only when all children are Done.

## Metrics & Targets

| Metric                             | Target | Current (approx.) |
|------------------------------------|--------|-------------------|
| Pulse velocity                     | ≥ 80%  | ~60%              |
| Untriaged issues in active timebox | 0%     | significant debt  |
| Issues without team/component      | ~0     | -                 |
| Epics without t-shirt size         | 0      | -                 |
| Epics without parent Objective     | 0      | -                 |

## Backlog Grooming Owners

| Backlog         | Who grooms                          |
|-----------------|-------------------------------------|
| Full backlog    | Director + senior leads             |
| Product (LTS)   | Seniors, architects, SMEs           |
| Release (Cycle) | Assigned objective lead, Epic owner |
| Pulse           | Everyone / issue owners             |

## Practice References

For full lifecycle rules, grooming checklists, and interrupt workflows:

- Objectives → `practices/objectives.md`
- Epics → `practices/epics.md`
- Pulse items (Stories / Tasks / Spikes) → `practices/pulse.md`

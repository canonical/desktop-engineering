# AI planning board — composite actions

This directory is the **single home** of the AI planning boards' wiring. It holds
sibling composite actions; the one planning repo (`canonical/desktop-ai-planning`,
which feeds an `all` board and one board per squad) and every onboarded code repo
reference one of them instead of carrying its own copy of the code:

- [`sync/`](sync/action.yaml) — the **status-reconcile** action. For each board,
  reads every Project card's live GitHub facts and sets each card's **Status** from
  scratch.
  Called by a planning repo's `board-sync.yml`. Drives the `ai_planning` package at
  [`../../ai-planning`](../../ai-planning).
- [`archive/`](archive/action.yaml) — the **archive-Map** action. Archives (or
  restores) the Project cards of every descendant of a closed Map, on one board. Called by a
  planning repo's manually-run `archive-map.yml`. Drives `ai_planning.archive`.
- [`pr-dispatch/`](pr-dispatch/action.yaml) — the **PR-relay** action. Forwards one
  destination-repo PR event to the planning repo as a `repository_dispatch`. Called
  by the per-repo `ai-planning-pr.yml` that `setup-dest-repo.sh` installs.
- [`issue-dispatch/`](issue-dispatch/action.yaml) — the **issue-relay** action.
  Forwards one destination-repo issue lifecycle event the same way (event type
  `ai-planning-issue`), so a code-repo issue reconciles the boards too.

All are **composite actions, not reusable workflows**, on purpose: GitHub requires
reusable workflows (`uses: …/foo.yaml`) to be rooted in the repo-root
`.github/workflows` (subdirectories are not supported), but an action can be
referenced from any directory
(`uses: canonical/desktop-engineering/gh-actions/ai-planning/<name>@<ref>`). Keeping
both here means the whole wiring lives in one place; the only cost is that the
`pr-dispatch` job checks this repo out to load the action (a few seconds, on a
cosmetic non-gating PR check).

## `sync/` — reconcile the board

It runs one idempotent **full reconcile of every board**: for each one it reads every
Project card's live GitHub facts (issue / PR / dependency state, cross-repo, over a
fine-grained PAT) and sets each card's **Status** from scratch. Cards already in the
right column are left untouched, so a resync never churns a board. The `all` board
is seeded with every open planning issue, a squad board with those labelled
`squad:<slug>`; each board has its own archived-Map marker label
`wayfinder:archived:<slug>`.

### Example usage (in a planning repo)

The caller owns the triggers; the action owns everything else. This is the whole
file a planning repo needs at `.github/workflows/board-sync.yml`:

```yaml
name: AI planning board status sync

on:
  issues:
    types: [opened, closed, reopened, assigned, unassigned, labeled, unlabeled, edited]
  repository_dispatch:
    types: [ai-planning-pr, ai-planning-issue]
  schedule:
    - cron: "17 */4 * * *"
  workflow_dispatch: {}

permissions:
  contents: read

concurrency:
  group: ai-planning-sync
  cancel-in-progress: true

jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Reconcile the planning board
        uses: canonical/desktop-engineering/gh-actions/ai-planning/sync@ai_planning_board
        with:
          boards: ${{ vars.AI_PLANNING_BOARDS }}
          token: ${{ secrets.AI_PLANNING_TOKEN }}
          dispatched-pr: ${{ github.event_name == 'repository_dispatch' && github.event.action == 'ai-planning-pr' && toJSON(github.event.client_payload) || '' }}
```

`setup-ai-planning-repo.sh` (in `../../ai-planning`) stands up the repo, the org
Projects, labels, and stores the two things this action needs on the planning
repo:

- secret **`AI_PLANNING_TOKEN`** — the fine-grained PAT, passed in as `token`;
- variable **`AI_PLANNING_BOARDS`** — a JSON object of board slug to Project node id
  (`{"all": "PVT_…", "apps": "PVT_…", …}`), passed in as `boards`.

### Inputs

| name             | required | default              | description                                                                 |
| ---------------- | -------- | -------------------- | --------------------------------------------------------------------------- |
| `boards`         | yes      | —                    | JSON object mapping each board slug to its org Project (v2) node id (`PVT_...`). `all` carries every planning issue, any other slug the issues labelled `squad:<slug>`. |
| `token`          | yes      | —                    | Fine-grained PAT (Issues:read/write, PRs:read, org Projects:write).         |
| `ref`            | no       | `ai_planning_board`  | Ref of `canonical/desktop-engineering` providing the `ai_planning` package. |
| `dispatched-pr`  | no       | `""`                 | JSON `repository_dispatch` `client_payload` (ticket 35), forwarded by the caller only when it ran `on: repository_dispatch`; the immediate arm authors that one PR's link before this same sweep scores it. |

The `permissions` and `concurrency` blocks live on the **caller** job (an action
cannot set them itself).

## `pr-dispatch/` — relay a code repo's PR

It builds a `client_payload` from the PR's facts (`repository`, `number`, `body`,
`baseRefName`, `state`, `isDraft`, `merged`) and POSTs a `repository_dispatch`
(event type `ai-planning-pr`) at the planning repo. It knows nothing about tickets,
links, or Status — every decision happens once, in the planning repo, off this
payload. The per-repo caller a code repo installs is a single `uses:` step:

```yaml
jobs:
  dispatch:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: canonical/desktop-engineering/gh-actions/ai-planning/pr-dispatch@ai_planning_board
        with:
          planning-repo: <org>/<planning-repo>
          dispatch-token: ${{ secrets.AI_PLANNING_DISPATCH_TOKEN }}
```

### Inputs

| name             | required | default          | description                                                                                              |
| ---------------- | -------- | ---------------- | -------------------------------------------------------------------------------------------------------- |
| `planning-repo`  | yes      | —                | The planning repo (`owner/name`) to dispatch to. The action fails fast if it is empty or a `<...>` placeholder. |
| `dispatch-token` | yes      | —                | Fine-grained PAT scoped to the planning repo, **`Contents: Read and write`** — the permission that authorises `POST .../dispatches`. |
| `event-type`     | no       | `ai-planning-pr` | The `repository_dispatch` event type the planning repo's `board-sync.yml` listens for.                   |

The caller job sets `permissions: {}` — this action uses only the passed-in
`dispatch-token`, never the workflow's `GITHUB_TOKEN`.

## `archive/` — hide or restore one Map's tree

Called by the planning repo's manually-run `archive-map.yml`. Inputs: `boards`
(same JSON as above), `board` (the slug to act on), `token`, `map`, `mode`
(`archive` | `unarchive`) and `dry-run`.

## The immediacy path (ticket 35)

A code-repo PR event reaches the reconcile within about a minute, with no
`schedule` cron anywhere in the path:

1. The destination code repo carries a per-repo caller
   (`.github/workflows/ai-planning-pr.yml`, installed by
   `../../ai-planning/setup-dest-repo.sh` from its
   `../../ai-planning/dest-repo/.github/workflows/ai-planning-pr.yml`
   template) that `uses:` the `pr-dispatch/` action on `on: pull_request`. That job
   POSTs a `repository_dispatch` (event type `ai-planning-pr`) at the planning repo,
   carrying the PR's facts as its `client_payload`.
2. The planning repo's `board-sync.yml` caller listens `on: repository_dispatch`
   (beside `on: issues` and `workflow_dispatch`) and forwards the payload to the
   `sync/` action's `dispatched-pr` input.
3. The `sync/` action's `python -m ai_planning` invocation authors that one PR's
   deliberate link (`ai_planning.link_authoring_job.author_dispatched_pr_link`)
   before running its usual full-board sweep — so the immediate path pays for one
   targeted lookup, not the reconcile arm's full-repo PR scan.

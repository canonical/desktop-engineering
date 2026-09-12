# AI planning board — status-reconcile composite action

`action.yaml` is the **single home** of the AI planning board sync. Every squad's
planning repo references it as a step instead of carrying its own copy of the
`ai_planning` package (which lives at [`../../ai-planning`](../../ai-planning)).

It is a **composite action**, not a reusable workflow, on purpose: GitHub requires
reusable workflows (`uses: …/foo.yaml`) to be rooted in `.github/workflows`, but an
action can be referenced from any directory
(`uses: canonical/desktop-engineering/gh-actions/ai-planning@<ref>`), which is why
this tooling can live here beside its package.

It runs one idempotent **full-board reconcile**: it reads every Project card's live
GitHub facts (issue / PR / dependency state, cross-repo, over a fine-grained PAT)
and sets each card's **Status** from scratch. Cards already in the right column are
left untouched, so a resync never churns the board.

## Example usage (in a planning repo)

The caller owns the triggers; the action owns everything else. This is the whole
file a planning repo needs at `.github/workflows/board-sync.yml`:

```yaml
name: AI planning board status sync

on:
  issues:
    types: [opened, closed, reopened, assigned, unassigned, labeled, unlabeled, edited]
  workflow_dispatch: {}
  schedule:
    - cron: "*/10 * * * *"

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
        uses: canonical/desktop-engineering/gh-actions/ai-planning@ai_planning_board
        with:
          project-id: ${{ vars.AI_PLANNING_PROJECT_ID }}
          token: ${{ secrets.AI_PLANNING_TOKEN }}
```

`setup.sh` (in `../../ai-planning`) stands up the repo, org Project, labels, and
stores the two things this action needs on the planning repo:

- secret **`AI_PLANNING_TOKEN`** — the fine-grained PAT, passed in as `token`;
- variable **`AI_PLANNING_PROJECT_ID`** — the Project node id, passed in as
  `project-id`.

## Inputs

| name             | required | default              | description                                                                 |
| ---------------- | -------- | -------------------- | --------------------------------------------------------------------------- |
| `project-id`     | yes      | —                    | The org Project (v2) node id (`PVT_...`) whose board to reconcile.          |
| `token`          | yes      | —                    | Fine-grained PAT (Issues:read/write, PRs:read, org Projects:write).         |
| `ref`            | no       | `ai_planning_board`  | Ref of `canonical/desktop-engineering` providing the `ai_planning` package. |
| `dispatched-pr`  | no       | `""`                 | JSON `repository_dispatch` `client_payload` (ticket 35), forwarded by the caller only when it ran `on: repository_dispatch`; the immediate arm authors that one PR's link before this same sweep scores it. |

The `permissions` and `concurrency` blocks live on the **caller** job (an action
cannot set them itself).

## The immediacy path (ticket 35)

A code-repo PR event reaches this reconcile within about a minute, with no
`schedule` cron anywhere in the path:

1. The destination code repo carries a per-repo caller
   (`.github/workflows/ai-planning-pr.yml`, installed by
   `../../ai-planning/onboard-code-repo.sh`) that `uses:` the reusable
   workflow `../../.github/workflows/ai-planning-pr-dispatch.yaml` on
   `on: pull_request`. That job POSTs a `repository_dispatch` (event type
   `ai-planning-pr`) at the planning repo, carrying the PR's facts
   (`repository`, `number`, `body`, `baseRefName`, `state`, `isDraft`,
   `merged`) as its `client_payload`.
2. The planning repo's `board-sync.yml` caller listens `on: repository_dispatch`
   (beside `on: issues` and `workflow_dispatch`) and forwards the payload to
   this action's `dispatched-pr` input.
3. This action's `python -m ai_planning` invocation authors that one PR's
   deliberate link (`ai_planning.link_authoring_job.author_dispatched_pr_link`)
   before running its usual full-board sweep — so the immediate path pays for
   one targeted lookup, not the reconcile arm's full-repo PR scan.

The reusable dispatch workflow itself must live at the repo root's
`.github/workflows/` (GitHub's hard requirement for `uses: …/foo.yaml`), which
is why it is a sibling of, not inside, this composite action's own directory.

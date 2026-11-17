# AI planning repo board

A code repo whose planning issues live in the repo itself — maps, specs and
tickets as ordinary issues (the Wayfinder work in `canonical/warty-whisperer`)
— gets **its own board** with nothing to configure: one org Project linked to
the repo and found by its predictive title, one event-driven workflow in the
repo, one secret. Everything else is native GitHub or this folder's sweep.

```bash
DEST_REPO=canonical/<repo> ./setup-dest-board.sh
# add COMMIT=0 to print the workflow instead of committing it
# (or run it from inside a clone of the destination repo: it writes the file
# into that working tree for review)
```

## What the setup stands up

- An org Project titled **`AI planning`**, **linked to the code repo** (it
  shows in the repo's Projects tab). The API cannot create repo-owned
  projects, but `createProjectV2` takes a `repositoryId` that does the linking
  at creation time. The sync finds it among the repo's linked projects by
  that predictive title — no variables, no boards JSON. Idempotent: re-running
  finds the existing Project and only refreshes what drifted.
- The five Status columns — **Blocked · Ready · In progress · In review ·
  Done** — plus a **Board** view (grouped by Status) and an **Efforts** view
  (the maps, `label:wayfinder:map`).
- `.github/workflows/board-sync.yml` on the repo's default branch:
  **event-driven only** — `issues` and `pull_request` events plus a manual
  `workflow_dispatch`, **no timer**. Every trigger is a fact the sweep can
  reconcile; a change that raises no event (archiving a card in the UI) waits
  for the next event or a manual run. The composite action
  (`gh-actions/ai-planning/repo-board-sync`) needs one input — the PAT — and
  runs one `python3` call: the runner has already downloaded the action's own
  repo (the engine lives three folders above it) and the package is
  stdlib-only, so there is no checkout and no install step.

## The one secret

`AI_PLANNING_TOKEN` on the code repo — a fine-grained PAT scoped to that one
repo (Issues: read and write; Pull requests: read — the sweep reads PRs, its
link scan included) plus the org's **Projects: read and write**.
This cannot be avoided: the workflow's own `GITHUB_TOKEN` is repo-scoped and
cannot even *resolve* a ProjectV2 — verified live, including for a
repo-linked board — so any Projects v2 automation needs a token carrying the
org's Projects permission. This exact recipe is what the deployed planning
repos (`AI_PLANNING_TOKEN` there) already run in production. The setup script
prints it and prompts for the PAT; it is the only key involved — no dispatch
tokens, no app, no variables.

## What runs on each event

`gh-actions/ai-planning/repo-board-sync` is a composite action: a sparse
checkout of `ai-planning/src` and one `python3 -m ai_planning.repo_board` —
the package is stdlib-only, so there is no install step. The sweep:

1. **authors this repo's missing ticket links** — GitHub ignores `Closes` on
   any PR that does not target the default branch, i.e. every stack PR into a
   spec branch (`<spec-slug>/base`), so the link behind `Closes #<ticket>` in
   the PR body is authored here; this is what makes the PRs visible to the
   sweep at all;
2. **seeds** the board with the repo's open issues carrying the agent-work
   vocabulary (`ready-for-agent`, `ready-for-human`, `wayfinder:*`) plus every
   sub-issue below them, at any depth: a spec and its tickets travel together;
   a bug or an unlabelled idea never lands;
3. **scores every card** from live facts, real work beating blockers:
   claim or open draft PR → **In progress**; PR ready for review, or a child
   in review (the parent roll-up) → **In review**; merged linked PR →
   **Done**; an open blocker with nothing running → **Blocked**; otherwise
   **Ready**;
4. **self-closes** a ticket whose linked PR merged while the issue was still
   open (GitHub never closes it itself outside `main`), unblocking its
   dependents;
5. **cascades maps**: a map whose whole sub-issue tree is settled closes; a
   closed map with a reopened descendant reopens.

Finished maps are **not** archived automatically — no `wayfinder:archived`
marker in this design. Hide a finished map's card by hand (its whole tree
follows it) or set the project's native auto-archive workflow.

## Native automations (the only hand adjustments)

Projects v2 ships built-in workflows with no API to configure them — click
only. On the project: `⋯` → **Workflows** → click each → **Edit** →
*Save and turn on*:

1. **Item added to project** → Set Status: **Ready** — new cards start in
   Ready (a blocked one is corrected by the next sweep; a map card also gets
   a Ready value set, which is cosmetic only: maps carry no work-state, the
   sweep never writes them and the Board view hides them);
2. **Item closed** → Set Status: **Done**;
3. **Pull request merged** → Set Status: **Done** — fires for merges into
   *any* branch, so stack PRs into spec branches settle instantly; it does
   **not** close the issue (GitHub ignores `Closes` outside `main`), which is
   the sweep's self-close job on its next pass.

**Auto-add sub-issues to project** ships enabled: a sub-issue of anything
already carded is carded by GitHub itself.

Everything else — Blocked, claims, In review, the roll-up, the cascade — has
no native trigger (the built-in workflow list is exhaustive) and stays the
sweep's job. The two never disagree for long: the sweep recomputes every card
from live facts and is idempotent, so a native write is at most a latency win.

Also by hand, if wanted: the project's **base role** (Settings → Manage
access) to let the org read the board, and the repo's **Projects** feature
flag (Settings → General → Features) for the Projects tab.

## Layout

```
setup-dest-board.sh                  one-pass setup/refresh (linked Project + columns
                                     + views + the event-driven workflow + the PAT secret)
dest-repo/.github/workflows/
  board-sync.yml                     the workflow installed on the code repo (a thin caller)
src/ai_planning/
  repo_board.py                      the repo-board entry point: find the linked
                                     `AI planning` Project by title, then sweep
  sync_status.py                     the pure precedence ladder (unit-tested)
  job.py                             the sweep: seed -> fetch -> score -> write
  client.py / queries.py / facts_mapping.py / boards.py
  link_authoring.py / link_authoring_job.py   the missing-link authoring arm
  map_visibility.py / archive.py     map-tree archiving (unused on repo boards:
                                     no marker label; kept for the shared design)
tests/                               pytest for the ladder, the sweep and the authoring
../gh-actions/ai-planning/repo-board-sync/action.yaml   the composite action (stdlib-only run)
```

The older, shared-planning-repo design (one planning repo feeding several org
boards per squad, PR/issue dispatch relays) still lives on the
`ai_planning_board` branch and keeps serving its deployments; this folder is
the repo-board design, self-contained on its own branch.

## Develop

```bash
python3 -m pytest            # from this folder; stdlib-only, no venv needed
```

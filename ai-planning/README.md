# AI planning repo board

A code repo whose planning issues live in the repo itself — maps, specs and
tickets (the Wayfinder work) — gets **its own board** with nothing to configure:
one Project linked to the repo (an org Project for an org-owned repo, a
user Project for a user-owned repo) and found by its predictive title
(`AI planning`), one event-driven workflow in the repo, one secret. Everything
else is native GitHub or this folder's sweep.

```bash
DEST_REPO=canonical/<repo> ./setup-dest-board.sh    # add COMMIT=0 to print the workflow instead of committing it
# (or run it from inside a clone of the destination repo: it writes the file into that working tree for review)
```

## What exists where

- The setup script does ONLY: the repo's Projects feature flag, the linked org
  Project (created/found by title; it refuses an ambiguous duplicate title), the
  PAT secret, and installing `.github/workflows/board-sync.yml` (signed commit +
  PR on a protected default branch).
- The SWEEP itself shapes the board on every run — idempotent and
  identity-preserving: existing options are always rewritten WITH their ids, so
  card values never wipe.
  - Six Status columns with one-line descriptions: **Blocked · Ready · In progress · In review · Approved · Done**.
  - The `Map` and `Spec` single-select stamp fields, created lazily (only once a
    map/spec exists), one option per map/spec named `<title> #<number>`, renamed
    in place when the issue is retitled (identity pinned by the option id
    already on the card).
  - Three views ensured by name: **Maps** (board, filter `-no:map`), **Efforts**
    (table, filter `is:issue`), **Specs** (board, filter `-no:spec`) — with their
    visible fields. The slice-by is UI-only (views/fields/options are
    API-creatable, the slice is not): one hand click each — Maps → Map, Efforts
    → Parent issue, Specs → Spec — printed by the setup; the three view updates
    go one mutation per call (batching fails with a misleading type error).

## The model (what each card is; all typing is labels + tree position, zero config)

- `wayfinder:map` → a **map card**: never status-written; Map-stamped with itself.
- `wayfinder:research|grilling|prototype|task` → **phase-1 decision tickets**: the
  plain ladder, never vanished, never archived when they close (they settle
  visibly in Done).
- Any other issue under a map: a child of a map is a **spec**; a child of a spec
  is an **implementation ticket** — tree position, read from GitHub's own
  sub-issue edges, no extra labels.
- **PR cards**: a *spec PR* is one whose head branch is `<spec-slug>/base` (it
  targets `main`, is a draft, body `Closes #<spec>`); *stack PRs* are every open
  PR whose base chain bottoms out in a spec branch — one ticket's PR
  (`Closes #<ticket>`) plus the fix PRs stacked above it (no ticket needed).
  Standalone PRs into `main` are not carded.

## The stamps (computed every sweep; the vanish is a cleared stamp, never a deletion)

- **Map**: the map card (itself), phase-1 tickets, spec tickets **before** their
  spec PR opens, and the spec PR card (which REPLACES the vanished spec ticket in
  the Maps surface).
- **Spec**: spec tickets (pre-PR), implementation tickets (pre-PR), and every
  spec-family PR card (spec/stack/fix).
- While a card's own PR is open its stamps are CLEARED (a spec loses both, an
  implementation ticket loses Spec): the card vanishes from the surfaces its PR
  card now serves, stays visible in the tree views via its Parent issue, and
  everything self-heals (re-stamped) if the PR closes unmerged.

## The views' populations (no overlaps)

- **Maps**: per map, only its direct descendants + the spec PR (once it exists) —
  the per-map action surface.
- **Efforts**: the whole ticket tree by parentage (slice by Parent issue): the
  map's section holds its direct children, each spec's section its implementation
  tickets. Issues only — no PR cards.
- **Specs**: per spec, implementation tickets without open PRs + all the spec's
  PR cards. The implementation surface.

## The ladder (CI-aware)

Done (closed, or a merged linked PR) > Approved (the PR's reviewDecision is
APPROVED — a second reviewer or bot reviewer; GitHub blocks self-approval and the
agent PRs as the user, so this fires exactly when a teammate or bot approves) >
In review (the PR is ready for review AND its check rollup is green — or it runs
no checks) > In progress (claimed, a started child, a draft PR, or a ready PR
with red/pending checks) > Blocked (open blocker with nothing running) > Ready.
A parent rolls up "started child" only (In progress and beyond); the
child-in-review roll-up rung is retired — PR cards carry the review lifecycle now.

## The arms, in run order

1. **seed**: open issues carrying the agent vocabulary (`ready-for-agent`,
   `ready-for-human`, `wayfinder:*`) plus their transitive sub-issues;
2. **shape** (above);
3. **card** the spec-family PRs;
4. **type + stamp** (drift-only writes);
5. **score + write** statuses (two passes, skip-if-unchanged);
6. **self-close** a ticket whose linked PR merged while the issue was still open —
   GitHub ignores `Closes` outside `main` and authors no link there, so the sweep
   authors those links from PR bodies first (one paged PR read shared by both
   arms);
7. **cascade maps**: a settled subtree closes; a closed map with any open
   descendant reopens;
8. **archive**: every closed card of the spec family (map, spec, implementation
   ticket, PR card) is archived — hidden from every view; reopened work
   unarchives. Phase-1 tickets and standalone issues are never auto-archived.
   A hand-archived card of still-open work comes back on the next sweep —
   the sweep has no marker to tell a hand-hide from a stale archive, so it
   errs toward visibility; hide finished work by closing it. The items read
   carry `archivedStates:
   [NOT_ARCHIVED, ARCHIVED]` because `addProjectV2ItemById` on archived content
   un-archives it.

## Events

`.github/workflows/board-sync.yml` is event-driven only: `issues`, `pull_request`
(incl. `synchronize`), `pull_request_review` (submitted/dismissed),
`issue_comment` (created — the reliable trigger for stacked-PR reviews, whose
merge ref may not carry the workflow file), plus a manual `workflow_dispatch` (Actions → "AI planning board
sync" → Run workflow) which reconciles everything — that is the "manual sync".
No schedule. The three native project workflows are UI-only, printed by the
setup: Item added → Ready, Item closed → Done, Pull request merged → Done.
Auto-add sub-issues to project ships enabled.

## The agent's only board duty

One line: every stack PR body says `Closes #<ticket>` (and the spec PR
`Closes #<spec>`). Everything else on the board is automation.

## The one secret

`AI_PLANNING_TOKEN` on the code repo — a fine-grained PAT scoped to that one repo
(Issues: read and write; Pull requests: read — the sweep reads PRs, its link scan
included) plus the org's **Projects: read and write**. This cannot be avoided:
the workflow's own `GITHUB_TOKEN` cannot resolve a ProjectV2 at all — verified
live, including for a repo-linked board. The setup prints it and prompts for the
PAT; it is the only key involved.

## Files

```
setup-dest-board.sh                  one-pass setup/refresh: project + workflow + secret only
dest-repo/.github/workflows/
  board-sync.yml                     the workflow installed on the code repo (a thin caller)
src/ai_planning/
  repo_board.py                      the zero-config entry point: find the linked
                                     `AI planning` Project by title, then sweep
  sync_status.py                     the pure precedence ladder (unit-tested)
  card_model.py                      the pure card model: typing, PR classification, stamp policy
  shape.py                           board shape: columns, stamp fields, views
  job.py                             the sweep: seed -> shape -> PR cards -> type/stamp
                                     -> statuses -> self-close -> cascade -> archive
  client.py / queries.py / facts_mapping.py / boards.py
  link_authoring.py / link_authoring_job.py   the missing-link authoring arm
  map_visibility.py / archive.py     kept for the older shared-planning-repo design (unused here)
tests/                               pytest for the ladder, the card model, the sweep, the authoring
../gh-actions/ai-planning/repo-board-sync/action.yaml   the composite action (stdlib-only run)
```

Tests: `python3 -m pytest` from this folder (stdlib-only, no venv needed).

The older, shared-planning-repo design (one planning repo feeding several org
boards per squad, PR/issue dispatch relays) still lives on the
`ai_planning_board` branch; this folder is the repo-board design, self-contained
on its own branch.

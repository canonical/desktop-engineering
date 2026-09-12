# AI planning board

A **per-squad planning surface** for **agentic / AI-native development**, plus the
**status-reconcile tooling** that keeps its board honest — as **self-contained
scaffolding**.

Each board is **scoped to one squad/team**: `create-ai-planning-repo.sh` takes a
`TEAM` and stands up that team's private planning repo and org Project. The board
is where planning skills (map / spec / tickets / triage / implement) publish their
maps, specs, implementation tickets, and research/prototype artifacts, driven by
the agent.

This folder lives inside the `desktop-engineering` resources repo as a **template**.
Deploying it (`./create-ai-planning-repo.sh`) pushes a **clean copy** of the
planning **surface** out as a standalone **private planning repo** in your org:
planning issues live there and a **thin caller** workflow ships inside it
(`.github/workflows/board-sync.yml`). The reconcile **code runs in one place only** —
the composite action at
`canonical/desktop-engineering/gh-actions/ai-planning`, which the caller invokes.
Nothing is deployed to any code repo by this script — a destination code repo gets
only its own small PR-dispatch caller, installed by `./add-new-repo.sh` (see
"Onboarding a destination code repo" below). `create-ai-planning-repo.sh` never
touches this parent repo's git state.

## What the deployed repo is

- **The deployed planning repo holds the issues + a thin caller workflow**: the
  squad's planning issues (maps, specs' implementation tickets,
  research/prototype/grilling tickets) live there as GitHub **issues** (never
  committed files), alongside a one-job `.github/workflows/board-sync.yml` that
  calls the reusable reconcile workflow. The reconcile **code itself lives once**
  in `canonical/desktop-engineering` (`ai-planning/` package +
  `gh-actions/ai-planning/action.yaml`), not in each planning repo.
- **One org-level Project (v2)** is the board. Its single **Status** field has five
  columns: **Blocked · Ready · In progress · In review · Done**. No custom fields —
  hierarchy uses the native **Parent issue** field, "which repo" uses the native
  **Repository** field.
- **Only a spec crosses into a code repo** (created directly in its destination).
  Its implementation tickets stay in the planning repo, parented cross-repo.

## How the board stays in sync (no unreliable cron dependency)

The board is reconciled by **one idempotent full-board sweep** (`python -m
ai_planning`) that, each run, **cards every issue then sets its Status from
scratch** off live facts. Two phases:

- **Pass 0 — seed.** Add every OPEN planning-repo issue to the board, then take
  the transitive closure over native **sub-issues**, so a cross-repo child such
  as a spec (reachable only through its map) is carded too. `addProjectV2ItemById`
  is idempotent and the sweep diffs against the board first, so a settled board
  issues no adds. **The agent never runs `item-add`.**
- **Sync.** Read each card's facts and write its derived Status.

The sweep is reached by, in order of importance:

1. **`on: issues` events in this repo** — the prompt, reliable path. *Any* issue
   activity here fires a full sweep of the whole board (seed + sync), so even
   unrelated events card and reconcile every issue, including a brand-new one.
   (GitHub's best-effort delay applies to `schedule`, **not** to issue/dispatch
   events.)
2. **Native Project "→ Done" workflows** — closes/merges set Done with no sweep at
   all (settings-only, cross-repo, reliable).
3. **A `workflow_dispatch` at code-repo merge time** — the prompt path for a merge
   that lands in *another* repo. GitHub sends the planning repo no event for a
   merge elsewhere, so the agent/dev that merges an implementation PR runs
   `gh workflow run board-sync.yml --repo <planning-repo>`; the sweep then closes
   the ticket (see the self-close mechanism below) and dependents unblock at once.
4. **A short `schedule` (`*/10 * * * *`)** — the quiescence floor only, for when the
   board is silent (e.g. a dispatch was missed). Its lateness is harmless because
   events and the dispatch carry the fast path. It is a 10-minute floor rather than
   a daily one so a merged implementation ticket whose dispatch is missed still
   settles within minutes, not up to a day.

The agent writes **no** Status and adds **no** cards: it only creates and wires
issues (labels, assignee, `blocked-by`, sub-issues), and the sweep derives every
column — assignee or open draft linked PR → In progress, open blocker → Blocked,
non-draft linked PR → In review, closed or merged linked PR → Done, plus the
child roll-up.

### Self-close on merge (cross-repo implementation tickets)

An implementation ticket lives in the planning repo, but its PR lives in a code
repo and targets the spec's **branch, not that repo's default branch**. GitHub
honours a closing keyword (`Closes owner/repo#n`) **only** on a PR that targets the
repo's default branch, so on a spec-branch PR the keyword is inert: merging
neither closes the ticket nor unblocks its dependents through GitHub's own native
close-on-merge. (Verified against
<https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue>.)

The PR is still a **deliberate native link** on the issue, though —
`closedByPullRequestsReferences(userLinkedOnly: true)` — which the sweep reads as
its sole PR signal (never a mention or keyword-inclusive read). So the sweep
detects the merge there — keyed off the linked PR's `merged`/`state` — and, when
it has merged while the issue is still open, **closes the underlying issue**
(using the PAT's existing `Issues: write`). Closing is what clears the native
`blocked_by` edges so dependents unblock; the `closed → Done` path then sets the
card (the merged-PR fact alone already sets it too, so the column is right either
way). No allow-list or cross-repo guard is needed: the deliberate link itself,
cross-repo or same-repo, is the guard. Instant-from-the-planning-repo-only is
impossible without a hosted webhook/App receiver, so the `workflow_dispatch`-at-
merge call above is the chosen prompt path, with the 10-minute floor as backstop.

**No event is ever lost:** the sweep reconciles *current state*, so a dropped,
delayed, or `cancel-in-progress`-cancelled event just settles on the next trigger.
The one thing no planning-repo trigger can see promptly is a **human** marking a
spec's PR ready-for-review (it happens in the code repo, has no native workflow)
— it settles on the next event sweep, the merge dispatch, or the floor.

Why not webhooks / a GitHub App / a code-repo workflow? They need org-owner rights
or a hosted receiver or a footprint in the code repo — deliberately out of scope
here (the rationale is summarised above).

### Scaling lever (future): the 3× pagination de-dup

Every sweep run pages the board **three times over**: the seed closure loop, the
`_board_content_ids` de-dup read, and the main `items` read each fully paginate
independently. That is an accepted cost at today's scale (open cards board-wide,
roughly `N≈500` before it starts to bite) and is **not built now** — it is a
documented escape hatch to reach for if/when the sweep's run time or API-call
budget becomes a problem, not a change this design requires.

## Deploy

```bash
# from this folder inside desktop-engineering:
ORG=my-org TEAM="Desktop Apps" ./create-ai-planning-repo.sh   # or run it and answer the prompts
```

`create-ai-planning-repo.sh` (idempotent, re-runnable):

1. **stages a clean copy** of the planning surface (no `.git`, no dev cruft, and
   **without** the Python package/tests/packaging) and pushes it as the private
   planning repo (`<org>/<team-slug>-ai-planning`) — the parent
   `desktop-engineering` repo is never modified;
2. creates the org Project (titled `<team> AI planning`) and sets its five Status columns (private);
3. creates the label vocabulary;
4. prompts for the fine-grained **PAT** and stores it as the `AI_PLANNING_TOKEN`
   secret plus the `AI_PLANNING_PROJECT_ID` variable **on the deployed planning repo**;
5. prints the two click-only follow-ups (enable native "→ Done"; create the Board
   and Efforts views).

Board title and repo name derive from `TEAM`; override with `BOARD_TITLE` /
`PLANNING_REPO` if you want different labels.

Then confirm the workflow:

```bash
gh workflow run board-sync.yml --repo <org>/<team-slug>-ai-planning
# or open/close a test issue here and watch the card settle.
```

> The private planning repo is **exempt** from GitHub's 60-day scheduled-workflow
> auto-disable (that rule is public-repo only) — moot in any case, since this
> board carries no `schedule` trigger at all (see the immediacy path above).

### Onboarding a destination code repo

Once the planning repo exists, wire each destination code repo's PRs into it:

```bash
DEST_REPO=<org>/<code-repo> PLANNING_REPO=<org>/<team-slug>-ai-planning ./add-new-repo.sh
```

`add-new-repo.sh` (idempotent, re-runnable) installs/updates that repo's
`.github/workflows/ai-planning-pr.yml` PR-dispatch caller (a non-required,
cosmetic check) via the Contents API, and registers its
`AI_PLANNING_DISPATCH_TOKEN` secret — the fine-grained PAT (`Contents:
write` only, scoped to the planning repo) minted once and kept in Bitwarden
under the planning repo's own entry.

## The PAT (fine-grained, least privilege)

Mint at <https://github.com/settings/personal-access-tokens/new>:

- **Resource owner:** the org (so the org `Projects` permission and org approval apply).
- **Repository access → All repositories:** every repo the token owner can access.
  This is deliberately broad: the alternative — all public repos *plus* a hand-picked
  set of private ones — isn't expressible in a single fine-grained grant, and it would
  force a token edit every time a spec targets a new destination code repo. "All
  repositories" avoids that churn; the permissions below keep it least-privilege.
- **Repository permissions:** `Issues: Read and write`, `Pull requests: Read-only`.
  (Write on Issues so the job can update the planning issues it reconciles.)
- **Organization permissions:** `Projects: Read and write`.
- **No `actions` permission** — nothing calls `gh workflow run`.

Migration path: swap the PAT for a **GitHub App** installation token later (own
identity, no rotation) once an org owner can approve it — the job code is unchanged,
only how the token is minted.

## Layout

```
create-ai-planning-repo.sh            one-pass deploy (repo + project + labels + PAT)
add-new-repo.sh                       onboard one destination code repo (PR-dispatch
                                      caller + dispatch-token secret)
dest-repo/                            templates for a DESTINATION repo, laid out at
                                      their exact destination-relative paths:
  docs/agents/issue-tracker.md          Matt Pocock skills adapter (copy/stamped into
                                        a target project's docs/agents/issue-tracker.md)
  .github/workflows/ai-planning-pr.yml  per-repo PR-dispatch caller (installed by
                                        add-new-repo.sh)
.github/workflows/board-sync.yml      thin caller: triggers -> the reusable workflow
                                      (this is all a deployed planning repo carries)
src/ai_planning/                      the sweep: fetch → sync_status → write
  sync_status.py                      the pure precedence-ladder function (unit-tested)
  job.py / facts_mapping.py / queries.py / client.py / link_authoring.py / link_authoring_job.py
tests/                                pytest for the pure function + mappers

# hosted once in this same repo, called by every planning repo and every
# onboarded destination code repo:
../gh-actions/ai-planning/action.yaml                        the reconcile composite action
../.github/workflows/ai-planning-pr-dispatch.yaml            the PR-dispatch reusable workflow
```

## Wiring the Matt Pocock skills to this board

`dest-repo/docs/agents/issue-tracker.md` is the tracker-adapter profile that makes
the Matt Pocock engineering skills (`/wayfinder`, `/to-spec`, `/to-tickets`,
`/triage`, `/implement`) publish to **this** board without forking any vendored
`SKILL.md`. In a **target project**, copy it to `docs/agents/issue-tracker.md` —
the skills already consult it through that project's `AGENTS.md` →
`docs/agents/*` pointer. It keeps the `wayfinder:` label vocabulary the skills
expect (created by `create-ai-planning-repo.sh`), and defines every tracker
operation (create/read/list, blocking, frontier, claim, resolve, promotion)
against this board.

## Develop

```bash
python -m pip install -e .
python -m pytest
```

The precedence ladder lives entirely in `sync_status(facts) → Status`; the fetch and
write mappers hold no branching. See `tests/test_sync_status.py` for the full truth
table (Done > Blocked > In review > In progress > Ready, plus the child roll-up).

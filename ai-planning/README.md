# AI planning board

This is a **planning board for a squad that works with AI agents**. It gives one
team a private space to plan work — maps, specs, tickets, research notes — as
ordinary GitHub issues, shown on a single org-level Project board, and it keeps
that board's columns up to date on its own so nobody has to drag cards around.

You deploy it once per team. After that, agents and people file issues the normal
way and the board follows along.

## What you get

Running the deploy script (below) stands up three things for a team:

- **A private planning repo** (`<org>/<team-slug>-ai-planning`). Every planning
  artifact — maps, specs' implementation tickets, research/prototype/grilling
  tickets — lives here as a GitHub **issue**, not a committed file. The repo
  deliberately carries **almost nothing** on disk: just one tiny workflow
  (`.github/workflows/board-sync.yml`) that keeps the board in sync, plus a short
  README.
- **An org-level Project board.** One **Status** field with five columns —
  **Blocked · Ready · In progress · In review · Done**. There are no custom fields:
  the board reuses GitHub's native **Parent issue** field for hierarchy and the
  native **Repository** field to show which code repo a spec belongs to.
- **A shared label vocabulary** the planning skills expect (`wayfinder:*` and the
  triage labels).

Only one kind of artifact ever leaves the planning repo: a finished **spec** is
created directly in its destination code repo. Its implementation tickets stay in
the planning repo and point back up to it.

This folder lives inside the `desktop-engineering` resources repo and is the
**single home** of every script, template and line of sync code. A deployed
planning repo carries only its `board-sync.yml`; destination code repos are wired
up straight from here by `setup-dest-repo.sh`. The reconcile code runs in exactly
one place — the composite action at
`canonical/desktop-engineering/gh-actions/ai-planning/sync` — which every deployed
planning repo calls. Nothing here is ever copied into a planning repo beyond that
one workflow.

## Deploy

From this folder, inside a clone of `desktop-engineering`:

```bash
ORG=my-org TEAM="Desktop Apps" ./setup-ai-planning-repo.sh
# or just run ./setup-ai-planning-repo.sh and answer the prompts
```

The script is idempotent — safe to re-run, and re-running it against an existing
planning repo is the supported way to **refresh** it after this scaffolding
changes (it syncs only the files that changed, never touching issues). In one pass it:

1. **creates the planning repo** carrying only `.github/workflows/board-sync.yml`
   and a short README (on a refresh it syncs just those). Your local
   `desktop-engineering` checkout is never modified;
2. creates the org Project (titled `<team> AI planning`) with its five Status columns;
3. creates the label vocabulary;
4. prompts you for a fine-grained **PAT** and stores it as the `AI_PLANNING_TOKEN`
   secret, plus the `AI_PLANNING_PROJECT_ID` variable, **on the planning repo**.
   On a refresh the secret is already set, so it skips that prompt (pass
   `ROTATE_PAT=1` to replace the token);
5. re-checks the native "→ Done" workflows live (there's no API to flip them, only
   to read them) and prints the result; if they're off it also prints the
   click-only fix, but the sweep never depends on them either way (see below).
   It also prints the one remaining click-only follow-up (create the Board and
   Efforts views).

Repo name and board title come from `TEAM`; override with `PLANNING_REPO` /
`BOARD_TITLE` if you want different names.

> **Refreshing from a local clone.** If you run the script from inside a clone of
> the planning repo, it infers the org/repo from that clone's `origin` and writes
> the refreshed files into your working tree (for you to review, commit and push)
> instead of pushing them straight through the API.

Then check it works:

```bash
gh workflow run board-sync.yml --repo <org>/<team-slug>-ai-planning
# …or just open and close a test issue in the planning repo and watch the card settle.
```

> The planning repo is private, so it's exempt from GitHub's 60-day
> scheduled-workflow auto-disable (a public-repo rule). That's moot here anyway —
> this board runs no `schedule` cron at all (see "How the board stays in sync").

### Onboarding a destination code repo

The planning repo works on its own. To also have a **code repo's pull requests
move planning cards** (draft PR → In progress, ready for review → In review,
merged → Done), wire that code repo in:

```bash
DEST_REPO=<org>/<code-repo> PLANNING_REPO=<org>/<team-slug>-ai-planning ./setup-dest-repo.sh
```

Run it from this folder (the templates live only here). Again idempotent — re-run
it any time to refresh whatever drifted after a template change — it stamps the
chosen planning repo into and installs two files on the code repo's default
branch:

- **`.github/workflows/ai-planning-pr.yml`** — the PR-dispatch caller that relays
  PR events to the planning repo (a non-required, cosmetic check — the real work
  happens back in the planning repo, so it never gates a merge); and
- **`docs/agents/issue-tracker.md`** — the planning-skills adapter pointing at this
  board (pass `WITH_ADAPTER=0` to skip it for a dispatch-only repo).

It also registers the `AI_PLANNING_DISPATCH_TOKEN` secret it needs (on a refresh,
already set, it skips that prompt — `ROTATE_PAT=1` to replace it). These are the
*only* footprint the tooling leaves in a code repo.

> **Refreshing from a local clone.** Run it from inside a clone of the code repo
> and it infers `DEST_REPO` from that clone's `origin` — and `PLANNING_REPO` from
> the caller workflow the repo already carries — then writes the two files into
> your working tree (for you to review, commit and push) instead of pushing them
> through the API.

## Tokens

There are two tokens, deliberately split so a code repo never holds anything
privileged.

**`AI_PLANNING_TOKEN`** — on the planning repo. This is the one that does the work:
reads issues/PRs across repos and writes the board. Mint a fine-grained PAT at
<https://github.com/settings/personal-access-tokens/new>:

- **Resource owner:** the org (so org `Projects` permission and org approval apply).
- **Repository access → All repositories.** Deliberately broad but read-mostly: the
  alternative (all public repos *plus* a hand-picked private set) can't be expressed
  in one fine-grained grant, and would force a token edit every time a spec targets
  a new code repo. "All repositories" avoids that churn; the permissions keep it tight.
- **Repository permissions:** `Issues: Read and write`, `Pull requests: Read-only`.
  (Write on Issues so the sweep can update the planning issues it reconciles.)
- **Organization permissions:** `Projects: Read and write`.
- **No `actions` permission** — nothing calls `gh workflow run`.

**`AI_PLANNING_DISPATCH_TOKEN`** — on each onboarded code repo. A separate, much
narrower PAT: **`Contents: Read and write`** only, scoped to the planning repo. That
Contents grant authorises `POST /repos/{owner}/{repo}/dispatches`. Mint it **once**,
keep it in **Bitwarden** under the planning repo's own entry, and `setup-dest-repo.sh`
reuses that same token for every code repo it onboards.

> Migration path: both tokens can later be swapped for a **GitHub App** installation
> token (its own identity, no rotation) once an org owner can approve it — the code
> is unchanged, only how the token is minted.

## How the board stays in sync

You never set a card's Status by hand. A single idempotent **full-board sweep**
(`python -m ai_planning`) does it: on every run it adds any missing issue to the
board, then recomputes each card's Status from live GitHub facts —
assignee or open draft PR → In progress, open blocker → Blocked, open non-draft PR
→ In review, closed or merged PR → Done, plus a roll-up from child issues. Because
it recomputes from scratch, a dropped or delayed trigger simply settles on the next
one; nothing is ever permanently wrong.

The sweep is **event-driven only — there is no `schedule` cron**. It runs from:

1. **`issues` events in the planning repo** — any issue activity settles the whole
   board within about a minute (GitHub's best-effort delay applies to `schedule`,
   not to issue or dispatch events).
2. **`repository_dispatch` from an onboarded code repo** — that repo's PR events are
   relayed here and drive the same sweep, so a code-repo PR moves its planning card
   almost immediately.
3. **Native Project "→ Done" workflows**, when enabled — GitHub's own
   settings-only automation flips closed/merged items to Done ahead of the next
   sweep, for the lowest possible latency. The sweep does **not** depend on
   these being on: every card, closed or open, is an ordinary write-candidate
   in the sweep's own pass (see `run_sync`'s write loop), so a Project where
   these ship disabled — or get switched off later — still settles every
   closed card to Done on the very next sweep, not never.

A `workflow_dispatch` is also wired for manual runs.

### Self-close on merge (cross-repo tickets)

An implementation ticket lives in the planning repo, but its PR lives in a code repo
and targets the **spec's branch, not the code repo's default branch**. GitHub only
honours a closing keyword (`Closes owner/repo#n`) on a PR that targets the default
branch, so on a spec-branch PR the keyword does nothing — merging won't close the
ticket or unblock its dependents on its own.

The sweep handles this. The PR is still a **deliberate native link** on the issue,
which the sweep reads as its sole PR signal. When it sees that linked PR has merged
while the issue is still open, it **closes the issue itself**. Closing clears the
native `blocked_by` edges, so dependent tickets unblock, and the card lands on Done.

Why not webhooks, a GitHub App, or a workflow inside the code repo? Each needs
org-owner rights, a hosted receiver, or a bigger footprint in the code repo — all
deliberately out of scope here.

### A scaling lever for later

Each sweep pages the whole board **three times** (the seed closure loop, the
de-dup read, and the main items read each paginate independently). That's fine at
today's scale — roughly `N≈500` active cards before it starts to bite — and is left
as a **documented escape hatch**, not built now. Reach for the de-dup only if a
sweep's run time or API-call budget ever becomes a real problem.

## Wiring the planning skills to this board

`dest-repo/docs/agents/issue-tracker.md` is the tracker-adapter profile that makes
the Matt Pocock engineering skills (`/wayfinder`, `/to-spec`, `/to-tickets`,
`/triage`, `/implement`) publish to **this** board without forking any vendored
`SKILL.md`. You don't copy it by hand: `setup-dest-repo.sh` stamps it with the
chosen planning repo and installs it at the code repo's `docs/agents/issue-tracker.md`
(unless you pass `WITH_ADAPTER=0`). The skills already find it through that project's
`AGENTS.md` → `docs/agents/*` pointer. It keeps the `wayfinder:` labels the skills
expect and defines every tracker operation (create/read/list, blocking, frontier,
claim, resolve, promotion) against this board.

## Layout

```
setup-ai-planning-repo.sh             one-pass deploy/refresh (repo + project + labels + PAT)
setup-dest-repo.sh                    add/refresh one destination code repo (PR-dispatch
                                      caller + skills adapter + dispatch-token secret)
dest-repo/                            templates applied to a DESTINATION code repo by
                                      setup-dest-repo.sh, at their destination-relative paths
                                      (NOT shipped into the planning repo):
  docs/agents/issue-tracker.md          planning-skills adapter (installed at the code
                                        repo's docs/agents/issue-tracker.md)
  .github/workflows/ai-planning-pr.yml  per-repo PR-dispatch caller
.github/workflows/board-sync.yml      thin caller: triggers -> the sync action
                                      (the ONLY file a deployed planning repo carries)
src/ai_planning/                      the sweep: fetch -> sync_status -> write
  sync_status.py                      the pure precedence-ladder function (unit-tested)
  job.py / facts_mapping.py / queries.py / client.py / link_authoring.py / link_authoring_job.py
tests/                                pytest for the pure function + mappers

# hosted once in this same repo, called by every planning repo and every
# onboarded destination code repo:
../gh-actions/ai-planning/sync/action.yaml         the reconcile composite action
../gh-actions/ai-planning/pr-dispatch/action.yaml  the PR-relay composite action
```

## Develop

```bash
python -m pip install -e .
python -m pytest
```

The precedence ladder lives entirely in `sync_status(facts) → Status`; the fetch and
write mappers hold no branching. See `tests/test_sync_status.py` for the full truth
table (Done > Blocked > In review > In progress > Ready, plus the child roll-up).

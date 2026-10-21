# Desktop AI planning boards

This is the **planning surface for the desktop squads that work with AI agents**.
It gives every squad one shared, private space to plan work — maps, specs, tickets,
research notes — as ordinary GitHub issues, shown on **one org-level Project board
per squad plus a global `all` board**, and it keeps those boards' columns up to date
on its own so nobody has to drag cards around.

You deploy it **once**, for everybody. After that, agents and people file issues the
normal way and the boards follow along.

## What you get

Running the deploy script (below) stands up, for the whole desktop team:

- **One private planning repo**, `canonical/desktop-ai-planning`. Every planning
  artifact — maps, specs' implementation tickets, research/prototype/grilling
  tickets — lives here as a GitHub **issue**, not a committed file. The repo
  deliberately carries **almost nothing** on disk: two tiny workflows
  (`board-sync.yml` keeps the boards in sync, `archive-map.yml` hides a finished
  Map on demand) plus a short README.
- **Eight org-level Project boards**: `all`, `apps`, `gaming`, `core`, `gnome`,
  `integration`, `enterprise` and `wsl` (titled `Desktop AI planning - <Squad>`).
  Each has one **Status** field with five columns — **Blocked · Ready · In progress
  · In review · Done** — and a *Board* and an *Efforts* view. There are no custom
  fields: the boards reuse GitHub's native **Parent issue** field for hierarchy and
  the native **Repository** field to show which code repo a spec belongs to. A closed
  Map is hidden, with its whole tree, by archiving its cards, and shown again by
  restoring the Map's card (see [Hiding a finished Map](#hiding-a-finished-map)).
- **A shared label vocabulary** the planning skills expect (`wayfinder:*` and the
  triage labels), plus one `squad:<slug>` label per squad and one
  `wayfinder:archived:<board>` marker per board.

Only one kind of artifact ever leaves the planning repo: a finished **spec** is
created directly in its destination code repo. Its implementation tickets stay in
the planning repo and point back up to it.

This folder lives inside the `desktop-engineering` resources repo and is the
**single home** of every script, template and line of sync code. The deployed
planning repo carries only its two workflows; destination code repos are wired up
straight from here by `setup-dest-repo.sh`. The reconcile code runs in exactly one
place — the composite action at
`canonical/desktop-engineering/gh-actions/ai-planning/sync` — which the planning
repo calls. Nothing here is ever copied into the planning repo beyond those
workflows.

## Which board does an issue land on?

| Board | Carries |
| --- | --- |
| `all` | **every** open issue of the planning repo |
| `apps`, `gaming`, `core`, `gnome`, `integration`, `enterprise`, `wsl` | the issues labelled `squad:<slug>` |

On every board, the sync also pulls in the **sub-issues below** those issues, at any
depth and in any repo — so a spec (which lives in a code repo) follows its Map onto
the boards, whatever label it carries. An effort shared by two squads carries both
`squad:*` labels and shows on both boards.

The squad label comes from the code repo the agent works in:
`setup-dest-repo.sh` stamps its squad into the repo's skills adapter, which tells
agents to add `--label squad:<squad>` to every planning issue they create. A card
whose squad label is removed later is **not** taken off that squad's board by the
sync (it only adds); archive or delete the card by hand.

## Bootstrap checklist

### 1. One-time: the planning repo and its boards

What you need before running anything:

- a **`gh` CLI** logged in as someone who can create repos and Projects in
  `canonical` (scopes `repo`, `project`, `read:org`, `workflow`; the script runs
  `gh auth refresh -s project,read:org` for you), plus **`git`** and **`jq`**;
- a clone of `canonical/desktop-engineering` on the branch the workflows pin
  (`ai_planning_board`, see [Pinning](#pinning-the-action-ref)) — nothing is
  modified in it;
- a **fine-grained PAT** for the sync, minted by hand in the browser (it cannot be
  scripted) at <https://github.com/settings/personal-access-tokens/new>, see
  [`AI_PLANNING_TOKEN`](#tokens) below. Keep it in Bitwarden;
- and, to wire the PAT in, either a terminal (the script prompts for it) or
  `AI_PLANNING_PAT=<token>` in the environment.

Then, from this folder:

```bash
./setup-ai-planning-repo.sh                      # prompts for the PAT
AI_PLANNING_PAT=<token> ./setup-ai-planning-repo.sh   # non-interactive
```

Defaults: org `canonical`, repo `desktop-ai-planning`, squads
`apps gaming core gnome integration enterprise wsl`. Override with `ORG`,
`PLANNING_REPO` (the repo *name*) or `SQUADS` (space-separated slugs). Board titles
derive from the repo name (`desktop-ai-planning` → `Desktop AI planning - <Squad>`);
`BOARD_TITLE_BASE` overrides it.

The script is idempotent — safe to re-run, and re-running it against an existing
planning repo is the supported way to **refresh** it after this scaffolding changes
or to **add a squad** (put it in `SQUADS`). It syncs only the files that changed and
never touches issues. In one pass it:

1. creates the 8 org Projects with their five Status columns (only when the columns
   differ, as rewriting them would clear every card's Status), forces them private,
   and creates their **Board** (`-label:wayfinder:map`, grouped by Status) and
   **Efforts** (`label:wayfinder:map`) views through the Projects Views API;
2. creates the **private** planning repo carrying only
   `.github/workflows/board-sync.yml`, `.github/workflows/archive-map.yml` and a
   short README (on a refresh it syncs just those);
3. creates the label vocabulary, including `squad:<slug>` and
   `wayfinder:archived:<board>` for every board;
4. stores the board map (`slug -> Project node id`) as the **`AI_PLANNING_BOARDS`**
   repo variable, and the PAT as the **`AI_PLANNING_TOKEN`** secret (on a refresh the
   secret is already set, so it skips that prompt; `ROTATE_PAT=1` replaces it);
5. re-checks the native "→ Done" workflows live on each board (there is no API to
   flip them, only to read them) and prints the remaining click-only follow-ups.

What is left **by hand** after it ran:

- **Visibility** — the repo and boards start private. See
  [Making it visible inside canonical](#making-it-visible-inside-canonical).
- *(Optional)* each board's native **"Item closed"** and **"Pull request merged"**
  workflows (`⋯` → Workflows → Set Status → Done): lower latency, never required,
  as the sweep settles every closed card itself.
- *(Optional)* **Slice by → Parent issue** on each Board view, and deleting the
  default `View 1`.

Then check it works:

```bash
gh workflow run board-sync.yml --repo canonical/desktop-ai-planning
# …or just open and close a test issue labelled squad:apps in the planning repo and
# watch its card settle on the `all` and `apps` boards.
```

> **Refreshing from a local clone.** If you run the script from inside a clone of
> the planning repo, it infers the org/repo from that clone's `origin` and writes
> the refreshed files into your working tree (for you to review, commit and push)
> instead of pushing them straight through the API.

> The repo is private (or internal), so it is exempt from GitHub's 60-day
> scheduled-workflow auto-disable (a public-repo rule), which would otherwise
> pause the 4-hourly sweep (see "How the boards stay in sync").

### 2. Per destination code repo

The planning repo works on its own. To also have a **code repo's pull requests
move planning cards** (draft PR → In progress, ready for review → In review,
merged → Done), have its issue lifecycle events immediately reconcile Map state and
visibility, and have its agents file squad-labelled planning issues, wire that code
repo in. What you need:

- admin rights on the code repo (the script sets a secret and commits two files to
  its default branch; if that branch is protected, run it from a local clone of the
  code repo instead — see below — and open a PR);
- the **dispatch token** (`AI_PLANNING_DISPATCH_TOKEN`, see [Tokens](#tokens)),
  minted **once** for the planning repo and read back from Bitwarden for every code
  repo; and
- the code repo's **squad** slug.

```bash
SQUAD=apps DEST_REPO=canonical/<code-repo> ./setup-dest-repo.sh
```

Run it from this folder (the templates live only here). `PLANNING_REPO` defaults to
`canonical/desktop-ai-planning`. Again idempotent — re-run it any time to refresh
whatever drifted after a template change (the squad is recovered from the adapter
already installed). It refuses a squad the planning repo has no `squad:<slug>`
label for. It stamps the planning repo and the squad into, and installs, two files
on the code repo's default branch:

- **`.github/workflows/ai-planning-pr.yml`** — the event-dispatch caller that relays
  PR facts and issue opened/edited/closed/reopened events to the planning repo
  (non-required, cosmetic checks — the real work happens back in the planning
  repo, so they never gate a merge); and
- **`docs/agents/issue-tracker.md`** — the planning-skills adapter pointing at the
  boards, and telling agents to label every planning issue `squad:<squad>` (pass
  `WITH_ADAPTER=0` to skip it for a dispatch-only repo).

It also registers the `AI_PLANNING_DISPATCH_TOKEN` secret it needs (on a refresh,
already set, it skips that prompt — `ROTATE_PAT=1` to replace it). These are the
*only* footprint the tooling leaves in a code repo. The planning skills find the
adapter through the project's `AGENTS.md` → `docs/agents/*` pointer.

> **Refreshing from a local clone.** Run it from inside a clone of the code repo
> and it infers `DEST_REPO` from that clone's `origin` — and `PLANNING_REPO` and
> `SQUAD` from the files the repo already carries — then writes the two files into
> your working tree (for you to review, commit and push) instead of pushing them
> through the API.

## Making it visible inside canonical

After the script, the planning repo and the 8 boards are **private**: only the
people explicitly given access see them. To let the whole `canonical` organization
read them (and nobody on the internet):

**The repo.** Two ways, depending on what "inside Canonical" must mean:

- **Internal** (simplest): visible to *every member of the enterprise*, i.e. of every
  organization in Canonical's GitHub Enterprise account, not just `canonical`.
  ```bash
  gh repo edit canonical/desktop-ai-planning --visibility internal \
    --accept-visibility-change-consequences
  ```
  or Settings → General → Danger Zone → *Change repository visibility* → *Change
  to internal*. Needs repo admin; the org must allow internal repos (it does).
  Members get read access, so they can see and comment on issues; writing still
  needs a collaborator or team grant.
- **Only the `canonical` org**: keep the repo private and give a `canonical` team
  (or all members, through a team that contains them) access: Settings →
  Collaborators and teams → *Add teams* → pick the team → role *Read* (or *Triage*,
  to let them label and assign issues). Pick this if the enterprise spans other orgs
  that must not see it.

**Each board** (×8, no API for it): a board stays "private" in the GitHub sense (not
on the internet) but can be readable by all org members through its base role: open
the board → `⋯` → Settings → **Manage access** → *Base role* → **Read** (or *Write*
so everybody can edit it). Leave *Visibility* at private; **never** flip it to public
(that is the internet). To make it the default for all new boards of the org, an
org owner sets the *base permission for projects* in the organization's Settings →
Projects. Cards of issues from a private repo only show to people who can read that
repo, so the repo access above matters as much as the base role.

## Pinning the action ref

The workflows and code-repo callers call the composite actions of
`canonical/desktop-engineering` at the branch `ai_planning_board` (the default of
`REF` in both setup scripts, of each action's `ref` input, and of the `@…` in the
templates). The planning repo therefore runs whatever that branch holds: **push the
tooling there before relying on the boards**. Once the work is merged, repin by
replacing `ai_planning_board` with `main` in the templates, the action defaults and
the scripts' `REF`, then re-run both scripts to refresh the repos.

## Tokens

There are two tokens, deliberately split so a code repo never holds anything
privileged.

**`AI_PLANNING_TOKEN`** — on the planning repo. This is the one that does the work:
reads issues/PRs across repos and writes the boards. Mint a fine-grained PAT at
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
narrower PAT: **`Contents: Read and write`** only, with *Only select repositories*
→ `desktop-ai-planning`. That Contents grant authorises
`POST /repos/{owner}/{repo}/dispatches`. Mint it **once**, keep it in **Bitwarden**
under the planning repo's own entry, and `setup-dest-repo.sh` reuses that same token
for every code repo it onboards.

> Migration path: both tokens can later be swapped for a **GitHub App** installation
> token (its own identity, no rotation) once an org owner can approve it — the code
> is unchanged, only how the token is minted.

## How the boards stay in sync

You never set a card's Status by hand. A single idempotent **full sweep**
(`python -m ai_planning`) does it: on every run, **for each board in turn**, it
adds any missing issue to the board (see
[Which board does an issue land on?](#which-board-does-an-issue-land-on)), then
recomputes each card's Status from live GitHub facts —
assignee or open draft PR → In progress, open blocker → Blocked, open non-draft PR
→ In review, closed or merged PR → Done, plus a roll-up from child issues. Because
it recomputes from scratch, a dropped or delayed trigger simply settles on the next
one; nothing is ever permanently wrong. One board failing (a revoked Project, an
API hiccup) does not stop the others: they are all swept, then the run fails.

The sweep is **event-driven, plus a 4-hourly `schedule` safety net**. It runs from:

1. **`issues` events in the planning repo** — any issue activity settles all
   the boards within about a minute (GitHub's best-effort delay applies to `schedule`,
   not to issue or dispatch events).
2. **`repository_dispatch` from an onboarded code repo** — PR events relay the PR
   facts needed by the link/status sync; issue opened/edited/closed/reopened events
   trigger the same reconcile sweep. This keeps Map closure/reopening and the
   board settled for cross-repository issues as well.
3. **Native Project "→ Done" workflows**, when enabled — GitHub's own
   settings-only automation flips closed/merged items to Done ahead of the next
   sweep, for the lowest possible latency. The sweep does **not** depend on
   these being on: every card, closed or open, is an ordinary write-candidate
   in the sweep's own pass (see `run_sync`'s write loop), so a Project where
   these ship disabled — or get switched off later — still settles every
   closed card to Done on the very next sweep, not never.

4. **A `schedule` every 4 hours** (`17 */4 * * *`) — for changes that raise no
   event, chiefly a Map card archived or restored in the Project UI (see below).
   GitHub may delay a scheduled run by several minutes.

A `workflow_dispatch` is also wired for manual runs.

The sweep never edits a view's filter. Board's `-label:wayfinder:map` filter,
which keeps Map cards out of Board, is created by the setup script and stays as it
is.

### Hiding a finished Map

An archived Map card means "this effort is hidden", and its whole tree follows it.
Every board does this on its own: archiving a Map's tree on the `apps` board leaves
the `all` board's cards alone until the sweep reaches them. GitHub raises no event
when a Project card is archived or restored, so the sweep works it out from the
active cards it can see, plus one marker on the Map issue per board, the
**`wayfinder:archived:<board>`** label (e.g. `wayfinder:archived:apps`: "the sweep
archived this Map's tree on that board"). Each
rule applies to the next sweep, so a change takes effect on the next sweep (any
planning-repo issue event, a code-repo dispatch, the 4-hourly schedule, or
**Run workflow** on `board-sync`), not instantly.

| What the sweep sees on a Map | What it does |
| --- | --- |
| closed, no marker | just finished: archives the tree (open or closed cards, any depth, any repo), then the Map's own card, then adds the marker |
| closed, marker, tree hidden | you **restored the Map's card**: restores every archived descendant, recursively; the marker stays so it is not hidden again |
| open, marker | the Map was reopened: restores the tree and removes the marker |
| Map card archived by hand, children still visible | archives the children and their subtrees and adds the marker |

A Map with an open descendant is reopened by the cascade before anything is
archived. The sweep leaves a Map alone, and says so in the log, when the
`wayfinder:archived:<board>` label does not exist in its repo
(`setup-ai-planning-repo.sh` creates one per board). Nothing else changes on the issues, and no new token permission is
needed: archiving is covered by `AI_PLANNING_TOKEN`'s org `Projects: Read and write`
and the label by `Issues: Read and write`.

A descendant that reopens while it is archived is not seen by the sweep until its
tree is restored.

**Manual.** The planning repo's **`archive-map.yml`** workflow does the same walk
for one Map, on one board, on demand (Actions tab, or
`gh workflow run archive-map.yml -f board=apps -f map=10 -f dry-run=false`), and can
restore a tree with `mode: unarchive`, immediately and without waiting for a sweep.

- The issue must carry `wayfinder:map` and be **closed**; otherwise nothing runs.
- The Map's own card is untouched, and `dry-run` (the default) only lists the cards.
- Choose `mode: unarchive` to restore the whole tree (the Map may be open).
- Only the chosen `board` changes; the other boards still show the cards until their
  own sweep archives them (a closed Map is archived everywhere by the sweep anyway).
- Archived cards leave the Efforts view too, not just the Board.
- By hand in the Project UI: select the card (click it on Board, or click the row
  number in a table; Ctrl/Cmd-click or Shift-click for several), then its "⋯"
  (Board) or ▾ (table) menu -> **Archive**. Restore from the Project's top-right
  "⋯" -> **Archived items**, tick the items, **Restore**.

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

The destination repo keeps only a thin event relay; all project reads/writes and
the Map cascade stay in the planning repo's sync. Putting that logic in each code
repo would require broader Project permissions and duplicate the reconciliation
logic. A webhook receiver or org-wide GitHub App would need a hosted receiver or
org-owner setup, respectively.

### A scaling lever for later

Each sweep pages each whole board **three times** (the seed closure loop, the
de-dup read, and the main items read each paginate independently), and the boards
are swept one after the other (the `all` board holds every card of the others, so a
sweep costs roughly twice a single board's). That's fine at
today's scale — roughly `N≈500` active cards before it starts to bite — and is left
as a **documented escape hatch**, not built now. Reach for the de-dup only if a
sweep's run time or API-call budget ever becomes a real problem.

## Wiring the planning skills to this board

`dest-repo/docs/agents/issue-tracker.md` is the tracker-adapter profile that makes
the Matt Pocock engineering skills (`/wayfinder`, `/to-spec`, `/to-tickets`,
`/triage`, `/implement`) publish to **these** boards without forking any vendored
`SKILL.md`. You don't copy it by hand: `setup-dest-repo.sh` stamps it with the
planning repo and the code repo's squad (so agents label every planning issue
`squad:<squad>`) and installs it at the code repo's `docs/agents/issue-tracker.md`
(unless you pass `WITH_ADAPTER=0`). The skills already find it through that project's
`AGENTS.md` → `docs/agents/*` pointer. It keeps the `wayfinder:` labels the skills
expect and defines every tracker operation (create/read/list, blocking, frontier,
claim, resolve, promotion) against this board.

## Layout

```
setup-ai-planning-repo.sh             one-pass deploy/refresh (repo + 8 boards + views + labels + PAT)
setup-dest-repo.sh                    add/refresh one destination code repo for a squad
                                       (event-dispatch caller + skills adapter + dispatch-token secret)
dest-repo/                            templates applied to a DESTINATION code repo by
                                      setup-dest-repo.sh, at their destination-relative paths
                                      (NOT shipped into the planning repo):
  docs/agents/issue-tracker.md          planning-skills adapter (installed at the code
                                        repo's docs/agents/issue-tracker.md)
  .github/workflows/ai-planning-pr.yml  per-repo PR + issue-event dispatcher
.github/workflows/board-sync.yml      thin caller: triggers -> the sync action
.github/workflows/archive-map.yml     manual caller: hide/restore one Map's tree on one board
                                      (these two are the ONLY files a deployed planning
                                      repo carries, besides its README)
src/ai_planning/                      the sweep: fetch -> sync_status -> write, per board
  boards.py                           the AI_PLANNING_BOARDS map: slug -> Project, seed and marker labels
  sync_status.py                      the pure precedence-ladder function (unit-tested)
  job.py / facts_mapping.py / queries.py / client.py / link_authoring.py / link_authoring_job.py
tests/                                pytest for the pure function + mappers

# hosted once in this same repo, called by every planning repo and every
# onboarded destination code repo:
../gh-actions/ai-planning/sync/action.yaml         the reconcile composite action
../gh-actions/ai-planning/pr-dispatch/action.yaml  the PR-relay composite action
../gh-actions/ai-planning/issue-dispatch/action.yaml  the issue-event relay
```

## Develop

```bash
python -m pip install -e .
python -m pytest
```

The precedence ladder lives entirely in `sync_status(facts) → Status`; the fetch and
write mappers hold no branching. See `tests/test_sync_status.py` for the full truth
table (Done > Blocked > In review > In progress > Ready, plus the child roll-up).

# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

Two repos, referenced by symbol throughout:

- `<owner>/<repo>` = the **destination code repo** — the clone you're in; `gh` infers it from `git remote -v`.
- `<planning-repo>` = `<org>/<planning-repo>` — the **planning repo** holding every artifact (map, `research`/`prototype`/`grilling`/`task` tickets, a spec's implementation tickets) **except a spec**, which is created directly in `<owner>/<repo>`.

Pass `--repo` accordingly on every `gh` call.

**A bare `#n` — in any command, skill invocation, or user message — resolves against the planning repo by default, before any tracker read.** Look it up there first, not in the destination repo `gh` would otherwise infer. The one exception is `/to-tickets`, whose argument is always a spec, and a spec lives in the destination repo. Fully-qualify a reference (`<owner>/<repo>#n`), or name it by its `wayfinder:spec` label, to point at the destination repo instead.

## Conventions

- **Create an issue**: `gh issue create --repo <owner>/<repo> --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --repo <owner>/<repo> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --repo <owner>/<repo> --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --repo <owner>/<repo> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --repo <owner>/<repo> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --repo <owner>/<repo> --comment "..."`

Infer the code repo from `git remote -v`; `gh` does this automatically when run inside a clone. Planning-repo calls take an explicit `--repo <planning-repo>`.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a planning-repo issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`, against whichever repo the bare `#n` resolved to (see above).

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --repo <planning-repo> --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write, of **any** skill that starts work on a ticket (`/implement`, `/tdd`, `/code-review`, a bare `#n`), not only `/wayfinder`.
- **Board Status is derived, never hand-set. Agents and skills write no Status and add no cards.** The board-sync sweep computes each ticket's Status from native GitHub facts, so just take the normal action and the card follows: claiming a ticket (Claim) or opening a draft PR moves it to `In progress`, marking that PR ready for review moves it to `In review`, and merging (or closing) moves it to `Done`. Do **not** `gh project item-edit` a Status or `item-add` a card by hand — the next sweep overwrites it from facts.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

## Spec operations

Used by `/to-spec` and `/to-tickets`. A map's settled design becomes one or more **specs** — the only artifact created in the **code repo**.

- **Slice the map into multiple specs.** `/to-spec` decomposes the design into **multiple landable-unit specs**, each a vertical slice that merges alone leaving `main` green; prefer more, smaller specs. Each spec is **one issue** (labelled `wayfinder:spec` + `ready-for-agent`, in the code repo), linked as a **sub-issue of the map**, and becomes **one PR against `main`**. Order specs with native `blocked_by` edges.
- **Implementation tickets are children of their spec.** Run `/to-tickets` **against a spec** (never a map): it slices the spec into implementation tickets in the planning repo, each a cross-repo **sub-issue of the spec**. Their PRs target the **spec's branch**, not `main`.
- **Small, independent, landable work goes straight to `main`.** File a decoupled ticket (an unrelated CI fix, a stray refactor) as its own `ready-for-agent` unit whose PR targets `main` directly — never folded into a feature spec.

Branch, stacking, PR-targeting, and signing mechanics for all of the above live in the project's git-workflow doc (`.kb/git-workflow.md`, where present).

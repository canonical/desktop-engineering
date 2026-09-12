# Deploy

Deployment is two scripts plus this folder's README — there is no separate
automation repo.

**Do this:** from this folder (inside the `desktop-engineering` resources repo), run
`./create-ai-planning-repo.sh` (see the top-level [`README.md`](../README.md) →
"Deploy"). It pushes a **clean copy** of the planning surface out as the private
planning repo, creates the org Project and Status columns, creates the labels, and
stores the fine-grained PAT + Project id **on the deployed planning repo**. A
**thin caller** workflow (`.github/workflows/board-sync.yml`) ships inside that
copy and invokes the reconcile composite action hosted once at
`canonical/desktop-engineering/gh-actions/ai-planning` — the sync code is never
copied. The parent `desktop-engineering` repo is never modified.

Then, for each destination code repo whose PRs should move planning-repo cards,
run `./add-new-repo.sh` (see the top-level README → "Onboarding a destination code
repo"). It installs/updates that repo's `.github/workflows/ai-planning-pr.yml`
PR-dispatch caller (a non-required, cosmetic check) and registers its
`AI_PLANNING_DISPATCH_TOKEN` secret — the only footprint this tooling puts in a
code repo.

Key facts (full detail in the README):

- **The deployed planning repo holds the issues + a thin caller workflow**; the
  reconcile code lives once in `canonical/desktop-engineering`.
- **Triggers, event-driven only, no `schedule` cron:** `on: issues` events (this
  repo) and `on: repository_dispatch` (a PR event relayed from an onboarded
  destination code repo) each drive a full-board reconcile within about a minute;
  native Project "→ Done" workflows handle closes.
- **Secret/variable location:** `AI_PLANNING_TOKEN` + `AI_PLANNING_PROJECT_ID`
  on **this** repo (not a separate automation repo); `AI_PLANNING_DISPATCH_TOKEN`
  on each onboarded destination code repo.
- **Token scope:** the planning repo's `AI_PLANNING_TOKEN` is `Issues: read and
  write` + `Pull requests: read-only` (all repositories), org `Projects: read and
  write`, no `actions:write`. Each destination repo's `AI_PLANNING_DISPATCH_TOKEN`
  is a separate, narrower PAT: `Contents: write` only, scoped to the planning repo
  (least privilege for `POST /repos/{owner}/{repo}/dispatches`).
- The private planning repo is exempt from the 60-day scheduled-workflow
  auto-disable (a public-repo rule) — moot here, since nothing on this board is
  a `schedule` trigger.

Verify:

```bash
gh workflow run board-sync.yml --repo <org>/<team-slug>-ai-planning
# or open/close a test issue in the planning repo, or open a PR in an onboarded
# destination code repo, and watch the card settle.
```

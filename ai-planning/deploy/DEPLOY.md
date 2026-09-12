# Deploy

Deployment is a single script plus this folder's README — there is no separate
automation repo and no per-code-repo footprint.

**Do this:** from this folder (inside the `desktop-engineering` resources repo), run
`./setup.sh` (see the top-level [`README.md`](../README.md) → "Deploy"). It pushes a
**clean copy** of the planning surface out as the private planning repo, creates the org
Project and Status columns, creates the labels, and stores the fine-grained PAT +
Project id **on the deployed planning repo**. A **thin caller** workflow
(`.github/workflows/board-sync.yml`) ships inside that copy and invokes the reusable
reconcile workflow hosted once at
`canonical/desktop-engineering/gh-actions/ai-planning/board-sync.yaml` — the sync
code is never copied. The parent `desktop-engineering` repo is never modified.

Key facts (full detail in the README):

- **The deployed planning repo holds the issues + a thin caller workflow**; the
  reconcile code lives once in `canonical/desktop-engineering`, and nothing is
  deployed to any code repo.
- **Triggers:** `on: issues` events (prompt, reliable) drive a full-board reconcile;
  a daily `schedule` (`37 13 * * *`) is the quiescence floor only; native Project
  "→ Done" workflows handle closes.
- **Secret/variable location:** `AI_PLANNING_TOKEN` + `AI_PLANNING_PROJECT_ID`
  on **this** repo (not a separate automation repo).
- **Token scope:** `Issues: read and write` + `Pull requests: read-only` on the
  planning repo and destination code repos, org `Projects: read and write`. No
  `actions:write`.
- The private planning repo is exempt from the 60-day scheduled-workflow
  auto-disable (a public-repo rule).

Verify:

```bash
gh workflow run board-sync.yml --repo <org>/<team-slug>-ai-planning
# or open/close a test issue in the planning repo and watch the card settle.
```

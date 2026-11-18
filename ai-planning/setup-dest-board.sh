#!/usr/bin/env bash
#
# setup-dest-board.sh — give a code repo its own AI planning board, idempotently.
# Run from THIS folder in a clone of canonical/desktop-engineering.
#
# For a repo whose planning issues live in the repo itself (maps, specs,
# tickets — e.g. the Wayfinder work in canonical/warty-whisperer), this stands
# up the whole repo-board shape with nothing to configure afterwards:
#
#   1. an org Project (v2) titled `AI planning`, **linked to the repo** (it
#      shows in the repo's Projects tab — the API cannot create repo-owned
#      projects, but `createProjectV2` takes a `repositoryId` that does the
#      linking at creation time);
#   2. `.github/workflows/board-sync.yml` on the repo's default branch — the
#      event-driven sync caller. No schedule, no variables, no boards JSON:
#      the action finds the board by its predictive title among the repo's
#      linked projects.
#
# The board's SHAPE — the six Status columns (with descriptions), the Map and
# Spec stamp fields, the Maps/Efforts/Specs views with their filters — is NOT
# set here: the sweep itself ensures all of it on its first run (and keeps it
# converged after), so this script stays project + workflow + secret only.
# The only hand steps left anywhere: the three native project workflows
# (UI-only) and the one-time slice-by click per view.
#
# One secret, set once on the repo: `AI_PLANNING_TOKEN` — a fine-grained PAT
# scoped to that one repo (Issues: read and write; Pull requests: read — the
# sweep reads PRs, its link scan included) plus the org's Projects: read and
# write. Projects v2 is out of the GITHUB_TOKEN's reach even for a
# repo-linked board (verified live: the Actions token cannot even resolve the
# Project), so no board automation can run without it. Mint it by hand
# (https://github.com/settings/personal-access-tokens/new), keep it in
# Bitwarden under the repo's entry; the script prompts for it (or takes
# AI_PLANNING_PAT=...) and skips the prompt on a refresh (ROTATE_PAT=1
# replaces).
#
# After the script, the only hand adjustments are the project's three native
# workflows (README, "Native automations"): Item added → Ready, Item closed →
# Done, Pull request merged → Done.
#
# Default mode commits the stamped workflow via the Contents API (idempotent,
# byte-identical skips). COMMIT=0 prints it instead; running from inside a
# clone of the destination repo writes into that working tree for review. The
# project/columns/views changes are always applied — they carry no commit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVOCATION_DIR="$(pwd)"
TEMPLATE="$SCRIPT_DIR/dest-repo/.github/workflows/board-sync.yml"

die() { echo "error: $*" >&2; exit 1; }

DEST_REPO="${DEST_REPO:-}"          # owner/name of the code repo
BOARD_TITLE="${BOARD_TITLE:-AI planning}"  # the predictive title the sync finds
REF="${REF:-ai_planning_repo_board}"  # desktop-engineering ref the caller pins
COMMIT="${COMMIT:-1}"               # 0: print the workflow, don't write it
AI_PLANNING_PAT="${AI_PLANNING_PAT:-}"
ROTATE_PAT="${ROTATE_PAT:-0}"

usage() { sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; }
[ -n "${1:-}" ] && { usage; exit 0; }

command -v gh >/dev/null || die "gh (GitHub CLI) is required"
command -v jq >/dev/null || die "jq is required"
gh auth status >/dev/null 2>&1 || die "run 'gh auth login' first"
[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"

# Run from inside a clone of the destination repo? Infer DEST_REPO and write
# the workflow into that working tree instead of the API.
TOOLING_TOP="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
CWD_TOP="$(git -C "$INVOCATION_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
CWD_REPO=""
if [ -n "$CWD_TOP" ] && [ "$CWD_TOP" != "$TOOLING_TOP" ]; then
  CWD_REPO="$(git -C "$INVOCATION_DIR" remote get-url origin 2>/dev/null \
    | sed -E 's#.*[:/]([^/]+/[^/.]+)(\.git)?$#\1#' || true)"
fi
[ -n "$CWD_REPO" ] && echo "==> detected local clone: $CWD_REPO"
[ -n "$DEST_REPO" ] || DEST_REPO="$CWD_REPO"
[ -n "$DEST_REPO" ] || read -rp "Destination code repo (owner/repo): " DEST_REPO
[ -n "$DEST_REPO" ] || die "DEST_REPO is required"
OWNER="${DEST_REPO%%/*}" NAME="${DEST_REPO#*/}"
LOCAL_MODE=0
[ -n "$CWD_REPO" ] && [ "$CWD_REPO" = "$DEST_REPO" ] && LOCAL_MODE=1

DEFAULT_BRANCH="$(gh repo view "$DEST_REPO" --json defaultBranchRef --jq .defaultBranchRef.name)"
# The project owner: an org for an org-owned repo, the user themself for a
# user-owned repo (both are valid `createProjectV2` owners — the API cannot
# create repo-owned projects, but the linking via `repositoryId` works either
# way). The PAT recipe differs: an org project needs the org Projects
# permission, a user project needs the PAT's Account permissions -> Projects.
if gh api "orgs/$OWNER" --jq .node_id >/dev/null 2>&1; then
  PROJECT_OWNER_KIND=org
  OWNER_ID="$(gh api "orgs/$OWNER" --jq .node_id)"
else
  PROJECT_OWNER_KIND=user
  OWNER_ID="$(gh api "users/$OWNER" --jq .node_id)"
fi
REPO_NODE_ID="$(gh repo view "$DEST_REPO" --json id --jq .id)"

# --- 1. the repo's Projects feature + the linked org Project -------------------
# The Projects tab (and this whole shape) needs the repo's Projects feature on.
# New repos ship it on; re-enable it when someone unticked it. Org-owner scope
# is not needed for the feature flag itself, but only a repo admin can PATCH.
has_projects="$(gh repo view "$DEST_REPO" --json hasProjectsEnabled --jq .hasProjectsEnabled)"
if [ "$has_projects" != "true" ]; then
  gh repo edit "$DEST_REPO" --enable-projects >/dev/null 2>&1 \
    || echo "    warning: could not enable the repo's Projects feature (needs repo admin) — do it in Settings → General → Features" >&2
fi

number="$(gh api graphql -f query='
  query($owner:String!,$name:String!){repository(owner:$owner,name:$name){
    projectsV2(first:20){nodes{number title}}
  }}' -f owner="$OWNER" -f name="$NAME" \
  --jq ".data.repository.projectsV2.nodes[] | select(.title==\"$BOARD_TITLE\") | .number" \
  2>/dev/null | head -n1 || true)"
if [ -n "$number" ]; then
  echo "==> $DEST_REPO already has linked Project #$number '$BOARD_TITLE'"
else
  echo "==> creating org Project '$BOARD_TITLE' linked to $DEST_REPO (its Projects tab)"
  number="$(gh api graphql -f query='
    mutation($oid:ID!,$rid:ID!,$title:String!){
      createProjectV2(input:{ownerId:$oid,repositoryId:$rid,title:$title}){projectV2{number}}
    }' -f oid="$OWNER_ID" -f rid="$REPO_NODE_ID" -f title="$BOARD_TITLE" \
    --jq '.data.createProjectV2.projectV2.number')" \
    || die "could not create the linked Project; create it by hand in the UI (link it to $DEST_REPO), then re-run this script"
fi
project_id="$(gh api graphql -f query='
  query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){
    projectV2(number:$number){id}
  }}' -f owner="$OWNER" -f name="$NAME" -F number="$number" \
  --jq '.data.repository.projectV2.id')"
echo "    Project #$number  id=$project_id"
echo "    (the sweep shapes the board itself on its first run: columns, stamp"
echo "     fields, views — nothing to set here)"

# --- 2. the stamped workflow ----------------------------------------------------
stamped="$(mktemp)"
sed "s|@ai_planning_repo_board|@$REF|g" "$TEMPLATE" > "$stamped"
[ -n "$(gh api "repos/canonical/desktop-engineering/branches/$REF" --jq .name 2>/dev/null || true)" ] \
  || echo "    warning: canonical/desktop-engineering has no branch '$REF' yet — the caller pins it; push the tooling there before relying on the board" >&2

# --- 3. the sweep's PAT ---------------------------------------------------------
# Fine-grained, scoped to THIS repo + the org's Projects permission (Projects
# v2 is out of the GITHUB_TOKEN's reach). Already-stored secrets are not
# readable back, so "set" means "don't ask again" — a refresh re-prompts only
# with ROTATE_PAT=1.
mint_help="    Mint the fine-grained PAT (browser-only):
      https://github.com/settings/personal-access-tokens/new
      Resource owner:        $OWNER
      Repository access:     Only select repositories -> $DEST_REPO
      Repository perms:      Issues: Read and write; Pull requests: Read
      Projects permission:   Read and write
      (a user-owned repo: the PAT's ACCOUNT permissions -> Projects;
       an org-owned repo: Organization perms -> Projects.
       no Actions/Webhooks/Contents needed)"
secret_set="$(gh secret list --repo "$DEST_REPO" --json name --jq '.[].name' 2>/dev/null | grep -qx AI_PLANNING_TOKEN && echo 1 || echo 0)"
if [ "$secret_set" = "1" ] && [ "$ROTATE_PAT" != "1" ]; then
  echo "    secret AI_PLANNING_TOKEN already set (ROTATE_PAT=1 to replace)"
elif [ "$COMMIT" = "0" ] || [ "$LOCAL_MODE" = "1" ]; then
  printf '%s\n' "$mint_help"
  if [ "$LOCAL_MODE" = "1" ]; then
    echo "    Set it from this repo's clone once you're happy:"
    echo "      gh secret set AI_PLANNING_TOKEN --repo $DEST_REPO"
  fi
else
  if [ -z "$AI_PLANNING_PAT" ]; then
    printf '%s\n' "$mint_help"
    read -rsp "PAT (input hidden): " AI_PLANNING_PAT; echo
  fi
  [ -n "$AI_PLANNING_PAT" ] || die "no PAT given (AI_PLANNING_PAT=... to skip the prompt)"
  gh secret set AI_PLANNING_TOKEN --repo "$DEST_REPO" --body "$AI_PLANNING_PAT"
  echo "    secret AI_PLANNING_TOKEN set"
fi

# --- 4. landing the workflow ---------------------------------------------------
# A protected default branch refuses API-made commits outright (HTTP 409), and
# a PR from them would fail the verified-signatures rule anyway: Contents-API
# commits carry no signature. So on a protected branch the workflow lands as a
# SIGNED commit made locally — this machine's git config and signing key —
# inside a throwaway clone of the repo, pushed to a branch and opened as a PR;
# merging it is the only step left. AUTO_PR=1 skips the confirmation.
if [ "$LOCAL_MODE" != "1" ] && [ "$COMMIT" = "1" ]; then
  if gh api "repos/$DEST_REPO/branches/$DEFAULT_BRANCH" --jq .protected 2>/dev/null | grep -q true; then
    PR_BRANCH="ai-planning/board-sync"
    echo "==> '$DEFAULT_BRANCH' of $DEST_REPO is protected (PR + verified signatures)."
    echo "    Landing the workflow as a signed commit + PR from a throwaway clone"
    echo "    of the repo (your git config and signing key do the signing)."
    if [ "${AUTO_PR:-0}" != "1" ]; then
      read -rp "Proceed? [y/N] " answer
      case "$answer" in y|Y|yes|Yes) ;; *) die "aborted — or re-run from inside your own clone of the repo";; esac
    fi
    tmp_clone="$(mktemp -d)"
    git clone --depth 1 "https://github.com/$DEST_REPO" "$tmp_clone" >/dev/null 2>&1 \
      || die "could not clone $DEST_REPO"
    (
      cd "$tmp_clone"
      mkdir -p .github/workflows
      cp "$stamped" .github/workflows/board-sync.yml
      git checkout -b "$PR_BRANCH" >/dev/null
      git add .github/workflows/board-sync.yml
      git commit -m "ci: sync the AI planning board on issue and PR events" >/dev/null
      gh api -X DELETE "repos/$DEST_REPO/git/refs/heads/$PR_BRANCH" >/dev/null 2>&1 || true
      git push -u origin "$PR_BRANCH" >/dev/null
      cat > pr-body.md <<'BODY'
## Summary

Installs `.github/workflows/board-sync.yml`: the **event-driven** sync of the
repo's own AI planning board — the org Project titled `AI planning` linked to
this repo (no schedule, no variables; the board is found by its predictive
title).

**One secret** (already set): `AI_PLANNING_TOKEN` — a fine-grained PAT scoped
to this repo (Issues: read and write; Pull requests: read) plus the org's
Projects: read and write. `GITHUB_TOKEN` cannot resolve a ProjectV2 at all
(verified live), so a Projects-capable PAT is the price of any board
automation.

**What the sweep does on each event**
(`canonical/desktop-engineering/gh-actions/ai-planning/repo-board-sync`):
- shapes the board itself (six Status columns with descriptions, the Map and
  Spec stamp fields, the Maps/Efforts/Specs views) — idempotent and
  identity-preserving, so a live board never wipes;
- authors the missing `Closes #<ticket>` links — GitHub ignores `Closes` on
  any PR that does not target `main` (every stack PR into a spec branch);
- seeds the board with open `ready-for-agent` / `ready-for-human` /
  `wayfinder:*` issues and their sub-issue trees, and cards every open
  spec-family PR (a spec PR into `main` from a `*/base` head, plus every PR
  whose base chain bottoms out in a spec branch — ticket PRs and the fix PRs
  stacked above them);
- stamps each card's Map/Spec fields (the descent) and clears a ticket's
  stamps while its own PR is open — the PR card replaces it (the vanish,
  self-healing when a PR closes unmerged);
- scores every card CI-aware: claim or draft PR → In progress, ready PR with
  green checks → In review, approved PR → Approved, merged/closed → Done
  (+ self-close of the ticket), open blocker with nothing running → Blocked,
  else Ready;
- archives every closed card of the spec family (and unarchives on reopen),
  so a merged spec's whole family — and a settled map — leave the board;
- cascades maps (auto-close/reopen with their sub-issue trees).

**Hand adjustments after merging** (Projects v2 has no API for these): on the
project → ⋯ → Workflows → turn on *Item added to project → Ready*, *Item
closed → Done*, *Pull request merged → Done*. `Auto-add sub-issues to
project` is already on. Then set each view's slice-by once (Maps → Map,
Efforts → Parent issue, Specs → Spec) — the API creates the views but cannot
set their slice.
BODY
      gh pr create --repo "$DEST_REPO" --head "$PR_BRANCH" --base "$DEFAULT_BRANCH" \
        --title "ci: sync the AI planning board on issue and PR events" \
        --body-file pr-body.md
    )
    pr_url="$(cd "$tmp_clone" && gh pr view "$PR_BRANCH" --json url --jq .url 2>/dev/null || echo "(check Actions/PRs on $DEST_REPO)")"
    rm -rf "$tmp_clone"
    echo "==> $pr_url"
    echo
    echo "Done. Board: org Project #$number '$BOARD_TITLE' ($project_id), linked to $DEST_REPO."
    echo
    echo "Remaining hand steps:"
    echo "  1. Merge the PR above — the workflow lands on $DEFAULT_BRANCH."
    echo "  2. The THREE native project workflows (open the project -> '..' ->"
    echo "     Workflows -> Edit -> 'Save and turn on'):"
    echo "       'Item added to project' -> Set Status: Ready"
    echo "       'Item closed'           -> Set Status: Done"
    echo "       'Pull request merged'   -> Set Status: Done"
    echo "     ('Auto-add sub-issues to project' is already on.)"
    echo "  3. First sweep: Actions -> 'AI planning board sync' -> Run workflow."
    exit 0
  fi
fi


echo
if [ "$LOCAL_MODE" = "1" ]; then
  mkdir -p .github/workflows
  cp "$stamped" ".github/workflows/board-sync.yml"
  echo "==> wrote ./.github/workflows/board-sync.yml — land it as a signed commit:"
  echo "     git checkout -b ai-planning/board-sync"
  echo "     git add .github/workflows/board-sync.yml"
  echo "     git commit -m 'ci: sync the AI planning board on issue and PR events'"
  echo "     git push -u origin ai-planning/board-sync"
  echo "     gh pr create --repo $DEST_REPO --fill"
elif [ "$COMMIT" = "1" ]; then
  workflow_path=".github/workflows/board-sync.yml"
  new_b64="$(base64 -w0 < "$stamped")"
  existing="$(gh api "repos/$DEST_REPO/contents/$workflow_path" --jq '{sha,content}' 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    if [ "$(echo "$existing" | jq -r '.content' | tr -d '\n')" = "$new_b64" ]; then
      echo "==> $workflow_path already up to date"
    else
      gh api --method PUT "repos/$DEST_REPO/contents/$workflow_path" \
        -f message="ai-planning: refresh the board-sync workflow" \
        -f content="$new_b64" -f sha="$(echo "$existing" | jq -r '.sha')" \
        -f branch="$DEFAULT_BRANCH" >/dev/null
      echo "==> $workflow_path updated on $DEFAULT_BRANCH"
    fi
  else
    gh api --method PUT "repos/$DEST_REPO/contents/$workflow_path" \
      -f message="ai-planning: install the board-sync workflow" \
      -f content="$new_b64" -f branch="$DEFAULT_BRANCH" >/dev/null
    echo "==> $workflow_path installed on $DEFAULT_BRANCH"
  fi
else
  echo "==> COMMIT=0: the workflow is at $stamped — review, then re-run with COMMIT=1."
fi

echo
echo "Done. Board: org Project #$number '$BOARD_TITLE' ($project_id), linked to $DEST_REPO."
echo
echo "Hand steps (the only ones left):"
echo
echo "1. THE TOKEN (skipped above when the secret is already set) — mint it in the"
echo "   browser at https://github.com/settings/personal-access-tokens/new :"
echo "     Resource owner:      $OWNER"
echo "     Repository access:   Only select repositories -> $DEST_REPO"
echo "     Repository perms:    Issues: Read and write; Pull requests: Read"
echo "     Projects permission: Read and write"
echo "       ($([ "$PROJECT_OWNER_KIND" = user ] && echo "the PAT's ACCOUNT permissions -> Projects, for a user-owned repo" || echo "Organization perms -> Projects, for an org-owned repo"))"
echo "   Then store it on the repo (it is the ONLY secret this needs):"
echo "     gh secret set AI_PLANNING_TOKEN --repo $DEST_REPO"
echo "   Why it cannot be the workflow's own token: GITHUB_TOKEN is repo-scoped"
echo "   and cannot resolve a ProjectV2 at all (verified live, even for a"
echo "   repo-linked board) — a token carrying the org's Projects permission is"
echo "   the price of any Projects v2 automation."
echo
echo "2. THE WORKFLOW — already installed above as .github/workflows/board-sync.yml"
echo "   on $DEFAULT_BRANCH (event-driven: issues, pull_request, pull_request_review,"
echo "   check_suite + Run workflow; no schedule). First run: Actions ->"
echo "   'AI planning board sync' -> Run workflow — it shapes the whole board"
echo "   (columns, stamp fields, views) on that first run."
echo
echo "3. THE THREE NATIVE PROJECT WORKFLOWS (Projects v2 has no API for these —"
echo "   click-only). Open the project -> top-right '..' -> Workflows, then for"
echo "   each: click it -> Edit (top right) -> configure -> 'Save and turn on':"
echo "     a. 'Item added to project'   -> Set Status: Ready"
echo "        (every new card starts in Ready; the sweep corrects a blocked one)"
echo "     b. 'Item closed'             -> Set Status: Done"
echo "     c. 'Pull request merged'     -> Set Status: Done"
echo "        (fires for merges into ANY branch, so stack PRs into spec branches"
echo "         settle instantly; it does not close the issue — the sweep's"
echo "         self-close does that on its next pass)"
echo "   'Auto-add sub-issues to project' is already enabled by default."
echo
echo "4. THE THREE VIEWS' SLICE-BY (the API creates the views but cannot set their"
echo "   slice — one click each): Maps -> Map, Efforts -> Parent issue, Specs -> Spec."
echo
echo "5. AGENTS: the only board-related duty anywhere is one line — every stack PR"
echo "   body says 'Closes #<ticket>' (and the spec PR 'Closes #<spec>'). GitHub"
echo "   never creates that link outside main; the sweep authors it, cards the PR,"
echo "   stamps the fields, scores the ladder (draft -> In progress, ready+green"
echo "   -> In review, approved -> Approved, merged -> Done + ticket closed) and"
echo "   archives the family when the spec lands."

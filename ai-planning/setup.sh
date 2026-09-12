#!/usr/bin/env bash
#
# setup.sh — stand up the AI planning board from this scaffolding in one pass.
#
# This folder is the SCAFFOLDING for a planning repo: it lives inside the
# desktop-engineering resources repo. Deploying it pushes a clean COPY of the
# planning SURFACE out as a standalone private planning repo (issues live there),
# carrying only a THIN caller workflow (.github/workflows/board-sync.yml) that
# calls the reusable reconcile workflow hosted once in canonical/desktop-engineering
# (gh-actions/ai-planning/board-sync.yaml). The sync code is never copied. This
# script:
#   1. creates the org Project (v2) and its Status columns,
#   2. stamps the board pointer into the adapter and pushes a clean copy of this
#      folder as the private planning repo,
#   3. creates the label vocabulary,
#   4. prompts for the fine-grained **PAT** (`Issues: read/write`, `PRs: read`,
#      org `Projects: read/write`, `All repositories`) and stores it (+ the Project id) on the repo,
#   5. prints the two click-only follow-ups (Project views + native "-> Done").
#
# Re-runnable: every step is idempotent or asks before overwriting. It never
# touches the parent desktop-engineering repo's git state — the planning repo is a
# separate repo built from a staged copy.
#
# Prereqs: `gh` authenticated with `project` + `read:org` scopes, and git.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- config (env-overridable) ------------------------------------------------
ORG="${ORG:-}"
TEAM="${TEAM:-}"                 # squad/team this board is scoped to (e.g. desktop) — placeholder
# The board is per-squad/team: its title and planning-repo name derive from $TEAM.
BOARD_TITLE="${BOARD_TITLE:-}"
PLANNING_REPO="${PLANNING_REPO:-}"
SECRET_NAME="AI_PLANNING_TOKEN"
VARIABLE_NAME="AI_PLANNING_PROJECT_ID"

slug() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-*//; s/-*$//'; }

die() { echo "error: $*" >&2; exit 1; }

command -v gh  >/dev/null || die "gh (GitHub CLI) is required"
command -v git >/dev/null || die "git is required"
command -v jq  >/dev/null || die "jq is required"

[ -n "$ORG" ] || read -rp "GitHub org that will own the board + planning repo: " ORG
[ -n "$ORG" ] || die "ORG is required"
[ -n "$TEAM" ] || read -rp "Squad/team this board is scoped to (e.g. Desktop Apps): " TEAM
[ -n "$TEAM" ] || die "TEAM is required (the board is scoped per squad/team)"
TEAM_SLUG="$(slug "$TEAM")"
# derive the per-team names (overridable via BOARD_TITLE / PLANNING_REPO env)
#   TEAM="Desktop Apps"  ->  board "Desktop Apps AI planning"  |  repo "<org>/desktop-apps-ai-planning"
BOARD_TITLE="${BOARD_TITLE:-$TEAM AI planning}"
PLANNING_REPO="${PLANNING_REPO:-${TEAM_SLUG}-ai-planning}"
PLANNING_FULL="$ORG/$PLANNING_REPO"

echo "==> team '$TEAM' | board '$BOARD_TITLE' | planning repo '$PLANNING_FULL'"
gh auth status >/dev/null 2>&1 || die "run 'gh auth login' first"
gh auth refresh -s project,read:org >/dev/null 2>&1 || true
gh api "orgs/$ORG" --jq '.login' >/dev/null || die "cannot see org '$ORG'"

# --- 1. org Project (v2) + Status columns ------------------------------------
PROJECT_NUMBER="$(gh project list --owner "$ORG" --format json \
  --jq ".projects[] | select(.title==\"$BOARD_TITLE\") | .number" 2>/dev/null || true)"
if [ -z "$PROJECT_NUMBER" ]; then
  echo "==> creating org Project '$BOARD_TITLE'"
  gh project create --owner "$ORG" --title "$BOARD_TITLE" --format json > /tmp/wf-project.json
  PROJECT_NUMBER="$(jq -r '.number' /tmp/wf-project.json)"
fi
PROJECT_ID="$(gh project view "$PROJECT_NUMBER" --owner "$ORG" --format json --jq '.id')"
[ -n "$PROJECT_ID" ] || die "could not resolve Project id"
echo "    Project #$PROJECT_NUMBER  id=$PROJECT_ID"

# force private (new org projects default to private; changing visibility is
# org-owner-only, so only attempt it when the project is actually public and
# never let a rejected mutation abort the run).
IS_PUBLIC="$(gh api graphql -f query='query($id:ID!){node(id:$id){... on ProjectV2{public}}}' \
  -f id="$PROJECT_ID" --jq '.data.node.public')"
if [ "$IS_PUBLIC" = "true" ]; then
  gh api graphql -f query='mutation($id:ID!){updateProjectV2(input:{projectId:$id,public:false}){projectV2{public}}}' \
    -f id="$PROJECT_ID" >/dev/null \
    || echo "    warning: could not set project private (needs org owner); please flip it in the UI" >&2
fi

# Status field id, then overwrite its options to exactly the five columns
STATUS_FIELD_ID="$(gh api graphql -f query='
  query($id:ID!){node(id:$id){... on ProjectV2{field(name:"Status"){... on ProjectV2SingleSelectField{id}}}}}' \
  -f id="$PROJECT_ID" --jq '.data.node.field.id')"
gh api graphql -f query='
  mutation($fid:ID!){updateProjectV2Field(input:{fieldId:$fid,singleSelectOptions:[
    {name:"Blocked",     color:RED,    description:"At least one open blocker; dominates all but Done"},
    {name:"Ready",       color:GRAY,   description:"Unblocked and unassigned — the takeable frontier"},
    {name:"In progress", color:YELLOW, description:"Assigned (claimed); or a draft PR is open"},
    {name:"In review",   color:BLUE,   description:"A non-draft PR is open and linked"},
    {name:"Done",        color:GREEN,  description:"Issue closed"}
  ]}){projectV2Field{... on ProjectV2SingleSelectField{options{name}}}}}' \
  -f fid="$STATUS_FIELD_ID" --jq '.data.updateProjectV2Field.projectV2Field.options[].name' \
  | paste -sd' · ' -

# --- 2. push a clean copy as the planning repo (adapter stamped with the pointer) ----
if gh repo view "$PLANNING_FULL" >/dev/null 2>&1; then
  echo "==> planning repo already exists: $PLANNING_FULL"
else
  echo "==> creating private planning repo $PLANNING_FULL from a staged copy of this folder"
  STAGE="$(mktemp -d)"
  trap 'rm -rf "$STAGE"' EXIT
  cp -a "$SCRIPT_DIR"/. "$STAGE"/
  # never carry dev cruft or a nested/parent .git into the planning repo
  rm -rf "$STAGE"/.git "$STAGE"/.venv "$STAGE"/.pytest_cache
  # The sync CODE lives in ONE place (canonical/desktop-engineering); the planning
  # repo carries only the thin caller workflow (.github/workflows/board-sync.yml),
  # which calls the reusable workflow. So the package, its tests, packaging, and
  # this deploy script never ship into the planning repo.
  rm -rf "$STAGE"/src "$STAGE"/tests
  rm -f "$STAGE"/pyproject.toml "$STAGE"/setup.sh "$STAGE"/onboard-code-repo.sh
  find "$STAGE" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  find "$STAGE" -type d -name '*.egg-info' -prune -exec rm -rf {} + 2>/dev/null || true
  find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true
  # Stamp the planning-repo pointer into the adapter so a code repo that fetches
  # docs/agents/issue-tracker.md points at THIS board with no hand-editing. The
  # body references the planning repo through the `<planning-repo>` symbol
  # (defined once at the top), so only that single definition value is stamped —
  # the un-inferrable pointer — leaving every body reference symbolic. This keeps
  # a stamped copy a one-line diff from this template. The destination code repo
  # stays inferred (git remote), never stamped.
  ADAPTER="$STAGE/adapter/issue-tracker.md"
  if [ -f "$ADAPTER" ]; then
    sed -i -e "s|<org>/<planning-repo>|$PLANNING_FULL|g" "$ADAPTER"
    echo "    stamped adapter pointer: $PLANNING_FULL"
  fi
  git -C "$STAGE" init -q -b main
  git -C "$STAGE" add -A
  git -C "$STAGE" commit -q -m "AI planning board tooling + planning surface"
  gh repo create "$PLANNING_FULL" --private --source="$STAGE" --remote=origin --push \
    --description "$TEAM AI planning surface (issues) + status-reconcile tooling"
fi
DEFAULT_BRANCH="$(gh repo view "$PLANNING_FULL" --json defaultBranchRef --jq .defaultBranchRef.name)"
echo "    default branch: $DEFAULT_BRANCH (schedules + this workflow run from here)"

# --- 3. label vocabulary on the planning repo --------------------------------
echo "==> labels"
mklabel(){ gh label create "$1" -R "$PLANNING_FULL" -c "$2" -d "$3" --force >/dev/null; }
mklabel needs-triage    D4C5F9 "Awaiting triage"
mklabel needs-info      FBCA04 "Blocked on missing info"
mklabel ready-for-agent 0E8A16 "Agent can pick this up"
mklabel ready-for-human 1D76DB "Needs a human"
mklabel wontfix         FFFFFF "Will not be worked"
mklabel bug             D73A4A "Category: bug"
mklabel enhancement     A2EEEF "Category: enhancement"
# Distinct colours per wayfinder type, so each ticket reads at a glance as a
# coloured label chip on the board. This only shows if the "Labels" field is
# enabled on the view — see the Views follow-up below; do it on BOTH views.
mklabel "wayfinder:research"  0E8A16 "Planning research ticket"    # green
mklabel "wayfinder:prototype" FBCA04 "Planning prototype ticket"   # yellow
mklabel "wayfinder:grilling"  D93F0B "Planning grilling ticket"    # orange-red
mklabel "wayfinder:task"      8250DF "Planning task ticket"        # purple
mklabel "wayfinder:map"       0052CC "Planning effort map (index, no work-state)"  # blue
# wayfinder:spec is NOT created here: specs live in the destination code repo, and
# labels are per-repo, so it is created there at spec-creation time (see
# adapter/issue-tracker.md → Wayfinding).

# --- 4. PAT (mint in browser) + store secret/variable on the planning repo ----
cat <<EOF

==> Fine-grained PAT
    Mint one at https://github.com/settings/personal-access-tokens/new
      Resource owner:        $ORG
      Repository access:     All repositories (every repo the token owner can
                             access) — simpler than 'all public + a hand-picked
                             set of private', and it means new destination code
                             repos need no token edit
      Repository perms:      Issues: Read and write, Pull requests: Read-only
      Organization perms:    Projects: Read and write
    (No 'actions' permission is needed — nothing calls 'gh workflow run'.)
EOF
read -rsp "Paste the PAT (hidden): " WF_PAT; echo
[ -n "$WF_PAT" ] || die "no PAT provided"
# sanity: token can read the Project
GH_TOKEN="$WF_PAT" gh api graphql -f query='query($id:ID!){node(id:$id){... on ProjectV2{title}}}' \
  -f id="$PROJECT_ID" --jq '.data.node.title' >/dev/null \
  || die "PAT cannot read the Project — check org Projects:write + org approval"
printf '%s' "$WF_PAT" | gh secret set "$SECRET_NAME" --repo "$PLANNING_FULL"
gh variable set "$VARIABLE_NAME" --repo "$PLANNING_FULL" --body "$PROJECT_ID"
unset WF_PAT
echo "    stored secret $SECRET_NAME + variable $VARIABLE_NAME on $PLANNING_FULL"

# --- 5. click-only follow-ups ------------------------------------------------
cat <<EOF

==> Two follow-ups that have no stable API (do them once in the UI):

  Board: https://github.com/orgs/$ORG/projects/$PROJECT_NUMBER

  A. Native "-> Done" workflows (so closes/merges settle to Done without the sync job):

     1. Open the board:
          https://github.com/orgs/$ORG/projects/$PROJECT_NUMBER
     2. Top-right, click the "⋯" (kebab) menu -> "Workflows".
     3. In the left list of default workflows, confirm these TWO are enabled
        (a green "On" toggle / non-grey row). Click each to open it and check:

          • "Item closed"
              - When: an issue or pull request in this project is closed
              - Set:  Status -> Done
              - Toggle: On

          • "Pull request merged"
              - When: a pull request in this project is merged
              - Set:  Status -> Done
              - Toggle: On

     4. If a workflow shows no target value, pick "Status" as the field and
        "Done" as the value from the dropdowns, then flip the toggle to On and
        save.

     Both ship enabled by default on new Projects, so usually this is just a
     one-glance confirmation — but verify, because a disabled one silently
     leaves closed cards stuck out of Done.

  B. Views:
     Board (default):
        - Layout:       Board
        - Column field: Status
        - Filter:       -label:wayfinder:map
        - Slice by:     Parent issue   (left "Slice by" panel -> pick "Parent
                        issue"; each parent becomes a slice so you can read the
                        board one effort at a time)
        - Show labels:  "⋯" (kebab) -> "Fields" and enable "Labels" so every
                        card shows its coloured wayfinder:<type> chip — the
                        at-a-glance type colour (research=green, prototype=
                        yellow, grilling=orange-red, task=purple, map=blue).
     Efforts (table):  filter label:wayfinder:map; also enable the "Labels"
                        column (same "Fields" menu) so each map row shows its
                        chip.

     Enabling "Labels" is per-view, so do it on BOTH views — a view without it
     shows no colour.

Then verify the reconcile workflow:
  gh workflow run board-sync.yml --repo $PLANNING_FULL
  # or just open/close a test issue in $PLANNING_FULL and watch the card settle.

Done. This repo is the planning repo; file planning issues here and the workflow
reconciles the board on each event, with the daily cron as the floor.

Board: https://github.com/orgs/$ORG/projects/$PROJECT_NUMBER
EOF

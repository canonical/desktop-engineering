#!/usr/bin/env bash
#
# setup-ai-planning-repo.sh — stand up OR refresh the AI planning board from this
# scaffolding in one pass.
#
# This folder, inside the desktop-engineering resources repo, is the SINGLE HOME
# of the AI planning tooling — every script, template and line of sync code. The
# planning repo it stands up carries ALMOST NOTHING: only its board-sync workflow
# (.github/workflows/board-sync.yml, which calls the reconcile composite action at
# canonical/desktop-engineering/gh-actions/ai-planning/sync) and a short README.
# Nothing else is copied out — code repos are wired up straight from here by
# setup-dest-repo.sh. This script:
#   1. creates the org Project (v2) and its Status columns,
#   2. creates the planning repo on first run, or on later runs refreshes its
#      minimal file set (push only the files whose content changed) — never
#      touching issues or anything else in the repo. If you run it from inside a
#      local clone of the planning repo, it infers the org/repo from that clone's
#      remote and writes the refreshed files into the working tree (you commit),
#      instead of pushing them through the API,
#   3. creates the label vocabulary,
#   4. stores the fine-grained **PAT** (`Issues: read/write`, `PRs: read`, org
#      `Projects: read/write`, `All repositories`) + the Project id on the repo —
#      on a refresh the PAT is already set, so it skips the prompt (ROTATE_PAT=1
#      to replace it),
#   5. prints the two click-only follow-ups (Project views + native "-> Done").
#
# Re-runnable: every step is idempotent or asks before overwriting. Re-running it
# on an existing planning repo is the supported way to REFRESH it after this
# scaffolding changes. It never touches the parent desktop-engineering repo's git
# state — the planning repo is a separate repo built from a staged set.
#
# Once the planning repo exists, onboard each destination code repo with
# `./setup-dest-repo.sh` (installs its PR-dispatch caller, the skills adapter, and
# the dispatch-token secret).
#
# Prereqs: `gh` authenticated with `project` + `read:org` scopes, and git.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVOCATION_DIR="$PWD"   # where the user ran us from (SCRIPT_DIR is where WE live)

# --- config (env-overridable) ------------------------------------------------
ORG="${ORG:-}"
TEAM="${TEAM:-}"                 # squad/team this board is scoped to (e.g. desktop) — placeholder
# The board is per-squad/team: its title and planning-repo name derive from $TEAM.
BOARD_TITLE="${BOARD_TITLE:-}"
PLANNING_REPO="${PLANNING_REPO:-}"
REF="${REF:-ai_planning_board}"  # ref of desktop-engineering the board-sync workflow pins
SECRET_NAME="AI_PLANNING_TOKEN"
VARIABLE_NAME="AI_PLANNING_PROJECT_ID"

slug() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-*//; s/-*$//'; }

die() { echo "error: $*" >&2; exit 1; }

# owner/repo of the git clone at $1 (via its origin remote), or nothing if $1 is
# not a github.com clone. Used to detect when we're standing IN the target repo.
clone_repo() {
  local top url
  top="$(git -C "$1" rev-parse --show-toplevel 2>/dev/null)" || return 0
  url="$(git -C "$top" remote get-url origin 2>/dev/null)" || return 0
  case "$url" in
    git@github.com:*)       url="${url#git@github.com:}" ;;
    https://github.com/*)   url="${url#https://github.com/}" ;;
    ssh://git@github.com/*) url="${url#ssh://git@github.com/}" ;;
    *) return 0 ;;
  esac
  printf '%s' "${url%.git}"
}

# True when a named secret already exists on repo $1 (so refresh can skip re-prompting).
secret_exists() { gh secret list --repo "$1" 2>/dev/null | awk '{print $1}' | grep -qx "$2"; }

# Write one staged file straight into the local working tree at $CWD_TOP, only when
# it differs — leaving the commit/push to the user. Used in local mode.
write_local() {
  local path="$1" staged="$STAGE/$1" dest="$CWD_TOP/$1"
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ] && cmp -s "$staged" "$dest"; then
    echo "    = $path"
  else
    cp "$staged" "$dest"
    echo "    ~ $path (written to working tree — review + commit)"
  fi
}

# Push one staged file to the planning repo via the Contents API, but only when it
# is new or its content changed — so a refresh is a no-op on unchanged files and
# never rewrites history needlessly. Reads $STAGE, $PLANNING_FULL, $DEFAULT_BRANCH.
sync_file() {
  local path="$1" staged="$STAGE/$1"
  local new_b64 existing existing_b64 sha
  new_b64="$(base64 -w0 < "$staged")"
  existing="$(gh api "repos/$PLANNING_FULL/contents/$path" --jq '{sha,content}' 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    existing_b64="$(echo "$existing" | jq -r '.content' | tr -d '\n')"
    if [ "$existing_b64" = "$new_b64" ]; then
      echo "    = $path"
      return
    fi
    sha="$(echo "$existing" | jq -r '.sha')"
    gh api --method PUT "repos/$PLANNING_FULL/contents/$path" \
      -f message="ai-planning: refresh $path" \
      -f content="$new_b64" -f sha="$sha" -f branch="$DEFAULT_BRANCH" >/dev/null
    echo "    ~ $path (updated)"
  else
    gh api --method PUT "repos/$PLANNING_FULL/contents/$path" \
      -f message="ai-planning: add $path" \
      -f content="$new_b64" -f branch="$DEFAULT_BRANCH" >/dev/null
    echo "    + $path (added)"
  fi
}

command -v gh  >/dev/null || die "gh (GitHub CLI) is required"
command -v git >/dev/null || die "git is required"
command -v jq  >/dev/null || die "jq is required"

# Are we being run from inside a clone of the target planning repo (a DIFFERENT
# repo than desktop-engineering, where this script lives)? If so, infer ORG +
# PLANNING_REPO from its remote so you needn't retype them, and — on refresh —
# write the file changes into that working tree instead of pushing via the API.
TOOLING_TOP="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
CWD_TOP="$(git -C "$INVOCATION_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
CWD_REPO=""
if [ -n "$CWD_TOP" ] && [ "$CWD_TOP" != "$TOOLING_TOP" ]; then
  CWD_REPO="$(clone_repo "$INVOCATION_DIR")"
fi
if [ -n "$CWD_REPO" ]; then
  echo "==> detected local clone: $CWD_REPO (at $CWD_TOP)"
  [ -n "$ORG" ]           || ORG="${CWD_REPO%%/*}"
  [ -n "$PLANNING_REPO" ] || PLANNING_REPO="${CWD_REPO#*/}"
  # The repo name is `<team-slug>-ai-planning`, so recover the team from it when
  # not given: desktop-apps-ai-planning -> "Desktop Apps". Override with TEAM=...
  if [ -z "$TEAM" ]; then
    TEAM="$(printf '%s' "${PLANNING_REPO%-ai-planning}" | tr '-' ' ' | sed -E 's/(^| )([a-z])/\1\U\2/g')"
    [ -n "$TEAM" ] && echo "    inferred team: $TEAM (from repo name; override with TEAM=...)"
  fi
fi

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

# Local mode: we're standing in a clone of THIS planning repo, so a refresh writes
# the file changes into the working tree (you review + commit) instead of the API.
LOCAL_MODE=0
if [ -n "$CWD_REPO" ] && [ "$CWD_REPO" = "$PLANNING_FULL" ]; then
  LOCAL_MODE=1
fi

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

# Status field id + its current option names.
STATUS_FIELD_JSON="$(gh api graphql -f query='
  query($id:ID!){node(id:$id){... on ProjectV2{field(name:"Status"){... on ProjectV2SingleSelectField{id options{name}}}}}}' \
  -f id="$PROJECT_ID" --jq '.data.node.field')"
STATUS_FIELD_ID="$(printf '%s' "$STATUS_FIELD_JSON" | jq -r '.id')"
CURRENT_OPTIONS="$(printf '%s' "$STATUS_FIELD_JSON" | jq -r '[.options[].name] | join("·")')"
WANT_OPTIONS="Blocked·Ready·In progress·In review·Done"

# Only (re)write the options when they don't already match. Rewriting the
# single-select options RECREATES their ids, which clears the Status of every
# card that referenced the old ids — so on a refresh, re-running the mutation
# would silently wipe the whole board's Status (open cards get re-synced by the
# next sweep, but closed cards, which the sweep never writes, stay blank). Guard
# it so a settled board is never disturbed.
if [ "$CURRENT_OPTIONS" = "$WANT_OPTIONS" ]; then
  echo "    Status columns already set: $CURRENT_OPTIONS"
else
  echo "==> setting Status columns (was: ${CURRENT_OPTIONS:-<none>})"
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
fi

# --- 2. build the planning repo's minimal file set, then create OR refresh ------
# The planning repo carries ALMOST NOTHING: only its board-sync workflow and a
# short README. Every script, template and line of sync code lives once in
# canonical/desktop-engineering — code repos are wired up straight from there by
# setup-dest-repo.sh, so nothing tooling-related is copied into the planning repo.
# We construct the staged set explicitly (rather than copy-then-strip) so it is
# impossible to leak a stray file, and the SAME set feeds both paths below.
echo "==> staging the planning repo's minimal file set"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/.github/workflows"
cp "$SCRIPT_DIR/.github/workflows/board-sync.yml" "$STAGE/.github/workflows/board-sync.yml"
# board-sync.yml needs no stamping: it references the board by the PROJECT_ID
# variable and the token secret, not by the repo name.
cat > "$STAGE/README.md" <<EOF
# $BOARD_TITLE

Private planning board for the **$TEAM** squad. File planning issues here; the
board's **Status** column reconciles automatically on every issue and PR event.

This repo carries almost nothing on purpose — only its board-sync workflow. All
tooling, templates and sync code live once in
**[canonical/desktop-engineering/ai-planning](https://github.com/canonical/desktop-engineering/tree/$REF/ai-planning)**
(run \`setup-ai-planning-repo.sh\` / \`setup-dest-repo.sh\` from there).

Board: https://github.com/orgs/$ORG/projects/$PROJECT_NUMBER
EOF

if gh repo view "$PLANNING_FULL" >/dev/null 2>&1; then
  if [ "$LOCAL_MODE" = 1 ]; then
    echo "==> planning repo exists: $PLANNING_FULL — refreshing files in your local clone ($CWD_TOP)"
  else
    echo "==> planning repo exists: $PLANNING_FULL — refreshing its file set"
    DEFAULT_BRANCH="$(gh repo view "$PLANNING_FULL" --json defaultBranchRef --jq .defaultBranchRef.name)"
  fi
  # Push only the two curated files (add/update the changed, skip the identical).
  # Nothing outside the set is touched; obsolete files from older versions are
  # removed by hand once (this stays experimental — no transitional pruning code).
  while IFS= read -r rel; do
    if [ "$LOCAL_MODE" = 1 ]; then write_local "$rel"; else sync_file "$rel"; fi
  done < <(cd "$STAGE" && find . -type f | sed 's|^\./||' | sort)
else
  echo "==> creating private planning repo $PLANNING_FULL from the staged file set"
  git -C "$STAGE" init -q -b main
  git -C "$STAGE" add -A
  git -C "$STAGE" commit -q -m "AI planning board (issues + board-sync workflow)"
  gh repo create "$PLANNING_FULL" --private --source="$STAGE" --remote=origin --push \
    --description "$TEAM AI planning surface (issues) + board-sync workflow"
  DEFAULT_BRANCH="$(gh repo view "$PLANNING_FULL" --json defaultBranchRef --jq .defaultBranchRef.name)"
fi
echo "    default branch: ${DEFAULT_BRANCH:-(local clone; commit + push yourself)}"

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
# dest-repo/docs/agents/issue-tracker.md → Wayfinding).

# --- 4. PAT (mint in browser) + store secret/variable on the planning repo ----
# On a refresh the secret is usually already set — skip the prompt then (pass
# ROTATE_PAT=1 to replace it). The Project-id variable is cheap and always kept
# current in case the board was recreated.
if secret_exists "$PLANNING_FULL" "$SECRET_NAME" && [ "${ROTATE_PAT:-0}" != "1" ]; then
  echo "==> secret $SECRET_NAME already set on $PLANNING_FULL — skipping PAT prompt (ROTATE_PAT=1 to replace)"
else
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
  unset WF_PAT
  echo "    stored secret $SECRET_NAME on $PLANNING_FULL"
fi
gh variable set "$VARIABLE_NAME" --repo "$PLANNING_FULL" --body "$PROJECT_ID"
echo "    set variable $VARIABLE_NAME on $PLANNING_FULL"

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

Next, onboard each destination code repo so its PR events dispatch here too:
  DEST_REPO=<org>/<code-repo> PLANNING_REPO=$PLANNING_FULL ./setup-dest-repo.sh

Done. This repo is the planning repo; file planning issues here and the workflow
reconciles the board on every issues event and every onboarded repo's PR dispatch —
event-driven only, no schedule cron.

Board: https://github.com/orgs/$ORG/projects/$PROJECT_NUMBER
EOF

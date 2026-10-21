#!/usr/bin/env bash
#
# setup-ai-planning-repo.sh — stand up OR refresh the desktop AI planning boards
# from this scaffolding in one pass.
#
# This folder, inside the desktop-engineering resources repo, is the SINGLE HOME
# of the AI planning tooling — every script, template and line of sync code. There
# is ONE planning repo for every squad (default: canonical/desktop-ai-planning) and
# ONE org Project board per squad plus a global `all` board:
#
#   all, apps, gaming, core, gnome, integration, enterprise, wsl
#
# A planning issue lands on the `all` board always, and on a squad's board when it
# carries the label `squad:<slug>` (plus, on every board, the sub-issues below it).
#
# The planning repo carries ALMOST NOTHING: its board-sync + archive-map workflows
# (.github/workflows/, which call the composite actions at
# canonical/desktop-engineering/gh-actions/ai-planning) and a short README.
# Nothing else is copied out — code repos are wired up straight from here by
# setup-dest-repo.sh. This script:
#   1. creates the org Projects (v2) — one per board — with their Status columns,
#      and the Board/Efforts views on each (when the Views API allows it),
#   2. creates the planning repo on first run (private), or on later runs refreshes
#      its minimal file set (push only the files whose content changed) — never
#      touching issues or anything else in the repo. If you run it from inside a
#      local clone of the planning repo, it infers the org/repo from that clone's
#      remote and writes the refreshed files into the working tree (you commit),
#      instead of pushing them through the API,
#   3. creates the label vocabulary (incl. one `squad:<slug>` label per squad and one
#      `wayfinder:archived:<board>` marker per board),
#   4. stores the fine-grained **PAT** (`Issues: read/write`, `PRs: read`, org
#      `Projects: read/write`, `All repositories`) as AI_PLANNING_TOKEN and the
#      board map as the AI_PLANNING_BOARDS variable on the repo — on a refresh the
#      PAT is already set, so it skips the prompt (ROTATE_PAT=1 to replace it),
#   5. prints the remaining click-only follow-ups.
#
# Re-runnable: every step is idempotent or asks before overwriting. Re-running it
# on an existing planning repo is the supported way to REFRESH it after this
# scaffolding changes (and to add a board when SQUADS grows). It never touches the
# parent desktop-engineering repo's git state — the planning repo is a separate
# repo built from a staged set.
#
# Once the planning repo exists, onboard each destination code repo with
# `SQUAD=<slug> ./setup-dest-repo.sh` (installs its PR/issue-dispatch caller, the
# skills adapter, and the dispatch-token secret).
#
# Non-interactive: pass the PAT in AI_PLANNING_PAT (otherwise it is prompted for).
#
# Prereqs: `gh` authenticated with `project` + `read:org` scopes, git and jq.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVOCATION_DIR="$PWD"   # where the user ran us from (SCRIPT_DIR is where WE live)

# --- config (env-overridable) ------------------------------------------------
ORG="${ORG:-canonical}"
PLANNING_REPO="${PLANNING_REPO:-}"   # repo NAME inside $ORG; default desktop-ai-planning
SQUADS="${SQUADS:-apps gaming core gnome integration enterprise wsl}"   # space-separated slugs
BOARD_TITLE_BASE="${BOARD_TITLE_BASE:-}"   # derived from the repo name: "Desktop AI planning"
REF="${REF:-ai_planning_board}"  # ref of desktop-engineering the workflows pin
SECRET_NAME="AI_PLANNING_TOKEN"
VARIABLE_NAME="AI_PLANNING_BOARDS"
ALL_SLUG="all"

# Display names for the board titles; any other slug is just capitalised.
declare -A SQUAD_DISPLAY=( [all]="All" [gnome]="GNOME" [wsl]="WSL" )

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

display_name() {
  local slug="$1"
  if [ -n "${SQUAD_DISPLAY[$slug]:-}" ]; then
    printf '%s' "${SQUAD_DISPLAY[$slug]}"
  else
    printf '%s' "$(tr '[:lower:]' '[:upper:]' <<<"${slug:0:1}")${slug:1}"
  fi
}

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
  ORG="${CWD_REPO%%/*}"
  [ -n "$PLANNING_REPO" ] || PLANNING_REPO="${CWD_REPO#*/}"
fi

PLANNING_REPO="${PLANNING_REPO:-desktop-ai-planning}"
PLANNING_FULL="$ORG/$PLANNING_REPO"
# Everything else derives from the repo name: desktop-ai-planning -> "Desktop AI planning"
#   boards: "Desktop AI planning - All", "Desktop AI planning - Apps", ...
if [ -z "$BOARD_TITLE_BASE" ]; then
  BOARD_TITLE_BASE="$(printf '%s' "${PLANNING_REPO%-ai-planning}" | tr '-' ' ' | sed -E 's/(^| )([a-z])/\1\U\2/g') AI planning"
fi
BOARD_SLUGS=("$ALL_SLUG" $SQUADS)

# Local mode: we're standing in a clone of THIS planning repo, so a refresh writes
# the file changes into the working tree (you review + commit) instead of the API.
LOCAL_MODE=0
if [ -n "$CWD_REPO" ] && [ "$CWD_REPO" = "$PLANNING_FULL" ]; then
  LOCAL_MODE=1
fi

echo "==> planning repo '$PLANNING_FULL' | boards: ${BOARD_SLUGS[*]} | titles '$BOARD_TITLE_BASE - <Squad>'"
gh auth status >/dev/null 2>&1 || die "run 'gh auth login' first"
gh auth refresh -s project,read:org >/dev/null 2>&1 || true
gh api "orgs/$ORG" --jq '.login' >/dev/null || die "cannot see org '$ORG'"

# --- 1. org Projects (v2) + Status columns, one per board --------------------
WANT_OPTIONS="Blocked·Ready·In progress·In review·Done"

declare -A BOARD_NUMBER BOARD_ID BOARD_NATIVE_OK BOARD_VIEWS_NOTE

# Create (or find) the Project titled $2 for slug $1 and set up its Status columns.
# Sets BOARD_NUMBER/BOARD_ID/BOARD_NATIVE_OK for the slug.
ensure_board() {
  local slug="$1" title="$2" number id is_public status_json status_field current
  number="$(gh project list --owner "$ORG" --limit 200 --format json \
    --jq ".projects[] | select(.title==\"$title\") | .number" 2>/dev/null | head -n1 || true)"
  if [ -z "$number" ]; then
    echo "==> creating org Project '$title'"
    number="$(gh project create --owner "$ORG" --title "$title" --format json | jq -r '.number')"
  fi
  id="$(gh project view "$number" --owner "$ORG" --format json --jq '.id')"
  [ -n "$id" ] || die "could not resolve Project id for '$title'"
  BOARD_NUMBER[$slug]="$number"
  BOARD_ID[$slug]="$id"
  echo "    [$slug] Project #$number  id=$id"

  # force private (new org projects default to private; changing visibility is
  # org-owner-only, so only attempt it when the project is actually public and
  # never let a rejected mutation abort the run).
  is_public="$(gh api graphql -f query='query($id:ID!){node(id:$id){... on ProjectV2{public}}}' \
    -f id="$id" --jq '.data.node.public')"
  if [ "$is_public" = "true" ]; then
    gh api graphql -f query='mutation($id:ID!){updateProjectV2(input:{projectId:$id,public:false}){projectV2{public}}}' \
      -f id="$id" >/dev/null \
      || echo "    warning: could not set '$title' private (needs org owner); please flip it in the UI" >&2
  fi

  # Status field id + its current option names.
  status_json="$(gh api graphql -f query='
    query($id:ID!){node(id:$id){... on ProjectV2{field(name:"Status"){... on ProjectV2SingleSelectField{id options{name}}}}}}' \
    -f id="$id" --jq '.data.node.field')"
  status_field="$(printf '%s' "$status_json" | jq -r '.id')"
  current="$(printf '%s' "$status_json" | jq -r '[.options[].name] | join("·")')"

  # Only (re)write the options when they don't already match. Rewriting the
  # single-select options RECREATES their ids, which clears the Status of every
  # card that referenced the old ids — so on a refresh, re-running the mutation
  # would silently wipe the whole board's Status until the next sweep resyncs
  # every card. Guard it so a settled board is never disturbed.
  if [ "$current" = "$WANT_OPTIONS" ]; then
    echo "    [$slug] Status columns already set"
  else
    echo "    [$slug] setting Status columns (was: ${current:-<none>})"
    gh api graphql -f query='
      mutation($fid:ID!){updateProjectV2Field(input:{fieldId:$fid,singleSelectOptions:[
        {name:"Blocked",     color:RED,    description:"At least one open blocker; dominates all but Done"},
        {name:"Ready",       color:GRAY,   description:"Unblocked and unassigned — the takeable frontier"},
        {name:"In progress", color:YELLOW, description:"Assigned (claimed); or a draft PR is open"},
        {name:"In review",   color:BLUE,   description:"A non-draft PR is open and linked"},
        {name:"Done",        color:GREEN,  description:"Issue closed"}
      ]}){projectV2Field{... on ProjectV2SingleSelectField{options{name}}}}}' \
      -f fid="$status_field" >/dev/null
  fi

  # Verify the native "-> Done" workflows (read-only). GitHub's Projects v2 API can
  # *read* a project's built-in workflows but has no mutation to enable one, so this
  # is only ever a live check; the sweep never depends on the result (every closed
  # card is an ordinary write-candidate there), they are a latency win when on.
  local workflows closed_on merged_on
  workflows="$(gh api graphql -f query='
    query($id:ID!){node(id:$id){... on ProjectV2{workflows(first:20){nodes{name enabled}}}}}' \
    -f id="$id" --jq '.data.node.workflows.nodes' 2>/dev/null || echo '[]')"
  closed_on="$(printf '%s' "$workflows" | jq -r '(.[] | select(.name=="Item closed") | .enabled) // false')"
  merged_on="$(printf '%s' "$workflows" | jq -r '(.[] | select(.name=="Pull request merged") | .enabled) // false')"
  if [ "$closed_on" = "true" ] && [ "$merged_on" = "true" ]; then
    BOARD_NATIVE_OK[$slug]=1
  else
    BOARD_NATIVE_OK[$slug]=0
  fi
}

# Create the Board and Efforts views on board $1 when missing, through the Projects
# Views REST API. Best-effort: on any failure record a note so the click-only
# instructions are printed for that board. Records BOARD_VIEWS_NOTE[$1].
ensure_views() {
  local slug="$1" number="${BOARD_NUMBER[$1]}" id="${BOARD_ID[$1]}"
  local existing status_id out=""
  existing="$(gh api graphql -f query='
    query($id:ID!){node(id:$id){... on ProjectV2{views(first:50){nodes{name}}}}}' \
    -f id="$id" --jq '[.data.node.views.nodes[].name]' 2>/dev/null || echo 'null')"
  if [ "$existing" = "null" ]; then
    BOARD_VIEWS_NOTE[$slug]="could not read views"; return 0
  fi
  if jq -e 'index("Board") and index("Efforts")' <<<"$existing" >/dev/null; then
    BOARD_VIEWS_NOTE[$slug]=""; return 0
  fi
  local fields
  fields="$(gh api "orgs/$ORG/projectsV2/$number/fields" --paginate 2>/dev/null || true)"
  status_id="$(jq -rs '[.[][] | select(.name=="Status") | .id] | first // empty' <<<"$fields" 2>/dev/null || true)"
  if [ -z "$status_id" ]; then
    BOARD_VIEWS_NOTE[$slug]="could not resolve the Status field id"; return 0
  fi
  # The fields each view shows: Title and the coloured Labels chips first, then the
  # context that makes a card readable (who, which repo, which effort).
  local visible
  visible="$(jq -cs '[.[][] | select(.name | IN("Title","Labels","Assignees","Linked pull requests","Repository","Parent issue","Sub-issues progress")) | .id]' <<<"$fields" 2>/dev/null || echo '[]')"
  if ! jq -e 'index("Board")' <<<"$existing" >/dev/null; then
    jq -n --argjson status "$status_id" --argjson vis "$visible" \
      '{name:"Board",layout:"board",filter:"-label:wayfinder:map",vertical_group_by:[$status]}
       + (if ($vis|length)>0 then {visible_fields:$vis} else {} end)' \
      | gh api --method POST "orgs/$ORG/projectsV2/$number/views" --input - >/dev/null 2>&1 \
      || out="Board view creation failed"
  fi
  if ! jq -e 'index("Efforts")' <<<"$existing" >/dev/null; then
    jq -n --argjson vis "$visible" \
      '{name:"Efforts",layout:"table",filter:"label:wayfinder:map"}
       + (if ($vis|length)>0 then {visible_fields:$vis} else {} end)' \
      | gh api --method POST "orgs/$ORG/projectsV2/$number/views" --input - >/dev/null 2>&1 \
      || out="${out:+$out; }Efforts view creation failed"
  fi
  BOARD_VIEWS_NOTE[$slug]="$out"
}

for slug in "${BOARD_SLUGS[@]}"; do
  ensure_board "$slug" "$BOARD_TITLE_BASE - $(display_name "$slug")"
  ensure_views "$slug"
  [ -z "${BOARD_VIEWS_NOTE[$slug]:-}" ] || echo "    [$slug] views: ${BOARD_VIEWS_NOTE[$slug]} — see follow-up B" >&2
done

# slug -> project node id, as the compact JSON the workflows read.
BOARDS_JSON="$(for slug in "${BOARD_SLUGS[@]}"; do printf '%s\t%s\n' "$slug" "${BOARD_ID[$slug]}"; done \
  | jq -Rn '[inputs | split("\t") | {(.[0]): .[1]}] | add' | jq -c .)"

# --- 2. build the planning repo's minimal file set, then create OR refresh ------
# The planning repo carries ALMOST NOTHING: its two workflows and a short README.
# Every script, template and line of sync code lives once in
# canonical/desktop-engineering — code repos are wired up straight from there by
# setup-dest-repo.sh, so nothing tooling-related is copied into the planning repo.
# We construct the staged set explicitly (rather than copy-then-strip) so it is
# impossible to leak a stray file, and the SAME set feeds both paths below.
echo "==> staging the planning repo's minimal file set"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/.github/workflows"
cp "$SCRIPT_DIR/.github/workflows/board-sync.yml" "$STAGE/.github/workflows/board-sync.yml"
cp "$SCRIPT_DIR/.github/workflows/archive-map.yml" "$STAGE/.github/workflows/archive-map.yml"
# The workflows need no stamping: they reference the boards by the
# AI_PLANNING_BOARDS variable and the token secret, not by the repo name.
{
  cat <<EOF
# $BOARD_TITLE_BASE

Private planning repo shared by every desktop squad. File planning issues here;
each board's **Status** column reconciles on planning issue events and dispatched
PR/issue events from destination repos.

Label every issue with its squad (\`squad:<slug>\`) to put it on that squad's board.
The global **all** board carries every issue.

| Board | Carries |
| --- | --- |
EOF
  for slug in "${BOARD_SLUGS[@]}"; do
    if [ "$slug" = "$ALL_SLUG" ]; then carries="every issue"; else carries="issues labelled \`squad:$slug\`"; fi
    echo "| [$BOARD_TITLE_BASE - $(display_name "$slug")](https://github.com/orgs/$ORG/projects/${BOARD_NUMBER[$slug]}) | $carries |"
  done
  cat <<EOF

When a Map closes, the sync archives its card and every card under it on each
board, so a finished effort leaves the boards. Restore the Map's card (Project "⋯"
-> Archived items) and the next sync restores its whole tree. The **archive-map**
workflow (Actions tab) does either on demand, for one board.

This repo carries almost nothing on purpose — its board-sync and archive-map
workflows. All tooling, templates and sync code live once in
**[canonical/desktop-engineering/ai-planning](https://github.com/canonical/desktop-engineering/tree/$REF/ai-planning)**
(run \`setup-ai-planning-repo.sh\` / \`setup-dest-repo.sh\` from there).
EOF
} > "$STAGE/README.md"

if gh repo view "$PLANNING_FULL" >/dev/null 2>&1; then
  if [ "$LOCAL_MODE" = 1 ]; then
    echo "==> planning repo exists: $PLANNING_FULL — refreshing files in your local clone ($CWD_TOP)"
  else
    echo "==> planning repo exists: $PLANNING_FULL — refreshing its file set"
    DEFAULT_BRANCH="$(gh repo view "$PLANNING_FULL" --json defaultBranchRef --jq .defaultBranchRef.name)"
  fi
  # Push only the curated files (add/update the changed, skip the identical).
  # Nothing outside the set is touched.
  while IFS= read -r rel; do
    if [ "$LOCAL_MODE" = 1 ]; then write_local "$rel"; else sync_file "$rel"; fi
  done < <(cd "$STAGE" && find . -type f | sed 's|^\./||' | sort)
else
  echo "==> creating private planning repo $PLANNING_FULL from the staged file set"
  git -C "$STAGE" init -q -b main
  git -C "$STAGE" add -A
  git -C "$STAGE" commit -q -m "AI planning boards (issues + board-sync workflow)"
  gh repo create "$PLANNING_FULL" --private --source="$STAGE" --remote=origin --push \
    --description "Desktop AI planning surface (issues, one board per squad) + board-sync workflow"
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
# enabled on the view (the views this script creates do).
mklabel "wayfinder:research"  0E8A16 "Planning research ticket"    # green
mklabel "wayfinder:prototype" FBCA04 "Planning prototype ticket"   # yellow
mklabel "wayfinder:grilling"  D93F0B "Planning grilling ticket"    # orange-red
mklabel "wayfinder:task"      8250DF "Planning task ticket"        # purple
mklabel "wayfinder:map"       0052CC "Planning effort map (index, no work-state)"  # blue
# wayfinder:spec is NOT created here: specs live in the destination code repo, and
# labels are per-repo, so it is created there at spec-creation time (see
# dest-repo/docs/agents/issue-tracker.md → Wayfinding).
for slug in "${BOARD_SLUGS[@]}"; do
  # One archived-Map marker per board: archiving a Map's tree is a per-board act.
  mklabel "wayfinder:archived:$slug" BFD4F2 "Set by the sync: this map's tree is archived on the '$slug' board"
  # The squad label is what puts an issue on a squad board (the `all` board needs none).
  [ "$slug" = "$ALL_SLUG" ] || mklabel "squad:$slug" C5DEF5 "Shows on the $(display_name "$slug") board"
done

# --- 4. board map variable + PAT secret on the planning repo -----------------
# The board map is cheap and always kept current, in case a board was recreated.
gh variable set "$VARIABLE_NAME" --repo "$PLANNING_FULL" --body "$BOARDS_JSON"
echo "    set variable $VARIABLE_NAME on $PLANNING_FULL: $BOARDS_JSON"

# On a refresh the secret is usually already set — skip the prompt then (pass
# ROTATE_PAT=1 to replace it).
if secret_exists "$PLANNING_FULL" "$SECRET_NAME" && [ "${ROTATE_PAT:-0}" != "1" ]; then
  echo "==> secret $SECRET_NAME already set on $PLANNING_FULL — skipping PAT prompt (ROTATE_PAT=1 to replace)"
else
  WF_PAT="${AI_PLANNING_PAT:-}"
  if [ -z "$WF_PAT" ]; then
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
    [ -t 0 ] || die "no AI_PLANNING_PAT and no terminal to prompt on: re-run with AI_PLANNING_PAT=<token> (or from a terminal). Everything above is already in place; the re-run is idempotent."
    read -rsp "Paste the PAT (hidden): " WF_PAT; echo
  fi
  [ -n "$WF_PAT" ] || die "no PAT provided"
  # sanity: token can read every Project
  for slug in "${BOARD_SLUGS[@]}"; do
    GH_TOKEN="$WF_PAT" gh api graphql -f query='query($id:ID!){node(id:$id){... on ProjectV2{title}}}' \
      -f id="${BOARD_ID[$slug]}" --jq '.data.node.title' >/dev/null \
      || die "PAT cannot read the '$slug' Project — check org Projects:write + org approval"
  done
  printf '%s' "$WF_PAT" | gh secret set "$SECRET_NAME" --repo "$PLANNING_FULL"
  unset WF_PAT
  echo "    stored secret $SECRET_NAME on $PLANNING_FULL"
fi

# --- 5. click-only follow-ups ------------------------------------------------
BOARD_LINES=""
NATIVE_OFF=""
VIEWS_TODO=""
for slug in "${BOARD_SLUGS[@]}"; do
  url="https://github.com/orgs/$ORG/projects/${BOARD_NUMBER[$slug]}"
  BOARD_LINES+="    $(printf '%-12s' "$slug") $url"$'\n'
  [ "${BOARD_NATIVE_OK[$slug]}" = 1 ] || NATIVE_OFF+="    $(printf '%-12s' "$slug") $url/workflows"$'\n'
  [ -z "${BOARD_VIEWS_NOTE[$slug]:-}" ] || VIEWS_TODO+="    $(printf '%-12s' "$slug") $url  (${BOARD_VIEWS_NOTE[$slug]})"$'\n'
done
if [ -z "$NATIVE_OFF" ]; then
  NATIVE_STATUS="✅ ON for every board — nothing to do here."
else
  NATIVE_STATUS="OFF (optional to enable) on:"$'\n'"$NATIVE_OFF"
fi
if [ -z "$VIEWS_TODO" ]; then
  VIEWS_STATUS="✅ Board + Efforts views exist on every board."
else
  VIEWS_STATUS="❌ ACTION NEEDED (the Views API refused) on:"$'\n'"$VIEWS_TODO"
fi

cat <<EOF

==> Boards:
$BOARD_LINES
==> Click-only follow-ups (no stable API for them):

  A. Native "-> Done" workflows (optional, lower-latency: closes/merges settle to
     Done ahead of the next sweep). Live status: $NATIVE_STATUS
     On a board: top-right "⋯" -> "Workflows"; enable "Item closed" and
     "Pull request merged", each with Set: Status -> Done. Not a correctness gap
     either way — the sweep settles every closed card itself.

  B. Views. $VIEWS_STATUS

     Each board wants two views (this script creates them when it can):
       Board (layout Board, column field Status): filter -label:wayfinder:map,
         with the "Labels" field shown.
       Efforts (layout Table): filter label:wayfinder:map, "Labels" shown.
     Optional, by hand: on Board, "Slice by" -> Parent issue. Delete the default
     "View 1" if you don't want it. The sync never edits a view's filter.

  C. Who can see it. The repo and the boards are PRIVATE after this run. To open
     them to every member of the $ORG organization only (not the internet): see
     the "Making it visible inside $ORG" section of ai-planning/README.md.

Then verify the reconcile workflow:
  gh workflow run board-sync.yml --repo $PLANNING_FULL
  # or just open/close a test issue in $PLANNING_FULL and watch the cards settle.

Next, onboard each destination code repo so its PR and issue lifecycle events
dispatch here too, and its agents label issues with the right squad:
  SQUAD=<slug> DEST_REPO=<org>/<code-repo> ./setup-dest-repo.sh

Done. Planning repo: https://github.com/$PLANNING_FULL
EOF

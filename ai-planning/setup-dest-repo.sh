#!/usr/bin/env bash
#
# setup-dest-repo.sh — add OR refresh one destination code repo's AI-planning
# footprint, idempotently (ticket 35). Run from THIS folder in a clone of
# canonical/desktop-engineering — the single home of every template.
#
# It asks which planning repo the code repo should talk to, then installs (or
# refreshes) two stamped files on the code repo's default branch, plus one secret:
#
#   1. `.github/workflows/ai-planning-pr.yml` — the PR-dispatch caller: a small
#      workflow that relays this repo's PR events to the planning repo. It is a
#      **non-required, cosmetic** check; the real work runs in the planning repo.
#   2. `docs/agents/issue-tracker.md` — the **skills adapter**: the tracker profile
#      that points the planning skills (`/wayfinder`, `/to-spec`, …) at THIS board.
#      Skip it with `WITH_ADAPTER=0` for a dispatch-only repo.
#   3. secret `AI_PLANNING_DISPATCH_TOKEN` — the dispatch-token PAT.
#
# Both files are stamped with the chosen planning repo (`<org>/<planning-repo>`).
# By default they're written via the Contents API — no local clone of the code
# repo, no PR: a direct, idempotent commit per file, skipped when the destination
# already carries byte-identical content. But if you run this from inside a local
# clone of the destination repo, it infers DEST_REPO from that clone's remote and
# writes the files into the working tree instead (you review + commit + push). So
# re-running it after a template changes just REFRESHES whatever drifted; on a
# refresh the dispatch-token secret is already set, so it skips that prompt
# (ROTATE_PAT=1 to replace it). Templates live only here in desktop-engineering;
# nothing is copied into the planning repo.
#
# The PAT itself (fine-grained, scoped to the **planning** repo, Contents:write
# only — least privilege for `POST /repos/{owner}/{repo}/dispatches`) is minted
# once in the browser and kept in Bitwarden under a location named after the
# planning repo (e.g. `desktop-apps-ai-planning`); this script never mints it,
# only pastes+stores the same value on each destination repo in turn.
#
# Run once per destination code repo to add it, or again any time to refresh it,
# after the planning repo exists (see `./setup-ai-planning-repo.sh`).
#
# Prereqs: `gh` authenticated with `repo` scope on the destination repo, jq.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVOCATION_DIR="$PWD"   # where the user ran us from (SCRIPT_DIR is where WE live)
CALLER_PATH=".github/workflows/ai-planning-pr.yml"
ADAPTER_PATH="docs/agents/issue-tracker.md"
CALLER_TEMPLATE="$SCRIPT_DIR/dest-repo/$CALLER_PATH"
ADAPTER_TEMPLATE="$SCRIPT_DIR/dest-repo/$ADAPTER_PATH"
SECRET_NAME="AI_PLANNING_DISPATCH_TOKEN"

# --- config (env-overridable) ------------------------------------------------
DEST_REPO="${DEST_REPO:-}"           # the code repo to onboard, e.g. acme/some-app
PLANNING_REPO="${PLANNING_REPO:-}"   # the planning repo the caller dispatches to
REF="${REF:-ai_planning_board}"      # ref of desktop-engineering providing the pr-dispatch action
WITH_ADAPTER="${WITH_ADAPTER:-1}"    # also place docs/agents/issue-tracker.md (0 = dispatch-only)

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

# Write one stamped file straight into the local working tree at $CWD_TOP, only
# when it differs — leaving the commit/push to the user. Used in local mode.
# $1=repo-relative path, $2=stamped source, $3=human noun.
write_local() {
  local path="$1" src="$2" noun="$3" dest="$CWD_TOP/$1"
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
    echo "    = $path ($noun already up to date)"
  else
    cp "$src" "$dest"
    echo "    ~ $path ($noun written to working tree — review + commit)"
  fi
}

# Stamp a template with the chosen planning repo (and the action ref) into a temp
# file, echoing its path. The `<org>/<planning-repo>` symbol is the only stamped
# value; every other reference stays symbolic.
stamp() {
  local template="$1" out
  out="$(mktemp)"
  sed \
    -e "s|<org>/<planning-repo>|$PLANNING_REPO|g" \
    -e "s|@ai_planning_board|@$REF|g" \
    "$template" > "$out"
  printf '%s' "$out"
}

# Write one stamped file to the destination repo's default branch via the Contents
# API, but only when it is new or its content changed. $1=repo path, $2=local
# stamped file, $3=human noun. Reads $DEST_REPO, $DEFAULT_BRANCH.
push_file() {
  local path="$1" src="$2" noun="$3"
  local new_b64 existing existing_b64 sha
  new_b64="$(base64 -w0 < "$src")"
  existing="$(gh api "repos/$DEST_REPO/contents/$path" --jq '{sha,content}' 2>/dev/null || true)"
  if [ -n "$existing" ]; then
    existing_b64="$(echo "$existing" | jq -r '.content' | tr -d '\n')"
    if [ "$existing_b64" = "$new_b64" ]; then
      echo "    = $path ($noun already up to date)"
      return
    fi
    sha="$(echo "$existing" | jq -r '.sha')"
    gh api --method PUT "repos/$DEST_REPO/contents/$path" \
      -f message="ai-planning: refresh $noun" \
      -f content="$new_b64" -f sha="$sha" -f branch="$DEFAULT_BRANCH" >/dev/null
    echo "    ~ $path ($noun updated)"
  else
    gh api --method PUT "repos/$DEST_REPO/contents/$path" \
      -f message="ai-planning: install $noun" \
      -f content="$new_b64" -f branch="$DEFAULT_BRANCH" >/dev/null
    echo "    + $path ($noun installed)"
  fi
}

command -v gh >/dev/null || die "gh (GitHub CLI) is required"
command -v jq >/dev/null || die "jq is required"
[ -f "$CALLER_TEMPLATE" ] || die "template not found: $CALLER_TEMPLATE"
[ -f "$ADAPTER_TEMPLATE" ] || die "template not found: $ADAPTER_TEMPLATE"

# Are we being run from inside a clone of the destination code repo (a DIFFERENT
# repo than desktop-engineering, where this script lives)? If so, infer DEST_REPO
# from its remote so you needn't retype it, and write the file changes into that
# working tree instead of pushing them via the API.
TOOLING_TOP="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
CWD_TOP="$(git -C "$INVOCATION_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
CWD_REPO=""
if [ -n "$CWD_TOP" ] && [ "$CWD_TOP" != "$TOOLING_TOP" ]; then
  CWD_REPO="$(clone_repo "$INVOCATION_DIR")"
fi
if [ -n "$CWD_REPO" ]; then
  echo "==> detected local clone: $CWD_REPO (at $CWD_TOP)"
  [ -n "$DEST_REPO" ] || DEST_REPO="$CWD_REPO"
fi

[ -n "$DEST_REPO" ] || read -rp "Destination code repo to onboard (owner/repo): " DEST_REPO
[ -n "$DEST_REPO" ] || die "DEST_REPO is required"

# Local mode: we're standing in a clone of THIS destination repo, so write the
# file changes into the working tree (you review + commit) instead of the API.
LOCAL_MODE=0
[ -n "$CWD_REPO" ] && [ "$CWD_REPO" = "$DEST_REPO" ] && LOCAL_MODE=1

# On a refresh the code repo already carries the caller workflow with its planning
# repo stamped in — recover PLANNING_REPO from it (the local working tree if we're
# in the clone, else via the API) so you needn't retype it.
if [ -z "$PLANNING_REPO" ]; then
  caller_body=""
  if [ "$LOCAL_MODE" = 1 ] && [ -f "$CWD_TOP/$CALLER_PATH" ]; then
    caller_body="$(cat "$CWD_TOP/$CALLER_PATH")"
  else
    caller_body="$(gh api "repos/$DEST_REPO/contents/$CALLER_PATH" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || true)"
  fi
  PLANNING_REPO="$(printf '%s' "$caller_body" | sed -nE 's/^[[:space:]]*planning-repo:[[:space:]]*([^[:space:]]+).*/\1/p' | head -n1)"
  [ -n "$PLANNING_REPO" ] && echo "    inferred planning repo: $PLANNING_REPO (from existing caller; override with PLANNING_REPO=...)"
fi
[ -n "$PLANNING_REPO" ] || read -rp "Planning repo this code repo should use (owner/repo): " PLANNING_REPO
[ -n "$PLANNING_REPO" ] || die "PLANNING_REPO is required"

echo "==> onboarding $DEST_REPO -> planning repo $PLANNING_REPO (ref $REF)"
gh repo view "$DEST_REPO" >/dev/null 2>&1 || die "cannot see destination repo '$DEST_REPO'"
if [ "$LOCAL_MODE" = 1 ]; then
  echo "    writing files into your local clone ($CWD_TOP) — commit + push yourself"
else
  DEFAULT_BRANCH="$(gh repo view "$DEST_REPO" --json defaultBranchRef --jq .defaultBranchRef.name)"
fi

# --- 1. stamp + push the caller workflow (and the skills adapter) ------------
STAMPED_CALLER="$(stamp "$CALLER_TEMPLATE")"
STAMPED_ADAPTER="$(stamp "$ADAPTER_TEMPLATE")"
trap 'rm -f "$STAMPED_CALLER" "$STAMPED_ADAPTER"' EXIT

put() { if [ "$LOCAL_MODE" = 1 ]; then write_local "$@"; else push_file "$@"; fi; }
put "$CALLER_PATH" "$STAMPED_CALLER" "PR-dispatch caller"
if [ "$WITH_ADAPTER" != "0" ]; then
  put "$ADAPTER_PATH" "$STAMPED_ADAPTER" "planning-skills adapter"
else
  echo "    (skipped $ADAPTER_PATH — WITH_ADAPTER=0)"
fi

# --- 2. dispatch-token secret -------------------------------------------------
# On a refresh the secret is usually already set — skip the prompt then
# (ROTATE_PAT=1 to replace it).
if secret_exists "$DEST_REPO" "$SECRET_NAME" && [ "${ROTATE_PAT:-0}" != "1" ]; then
  echo "==> secret $SECRET_NAME already set on $DEST_REPO — skipping PAT prompt (ROTATE_PAT=1 to replace)"
else
  cat <<EOF

==> Dispatch-token PAT
    Paste the token stored in Bitwarden under the planning repo's entry
    ($PLANNING_REPO). Mint one at
    https://github.com/settings/personal-access-tokens/new if it doesn't
    exist yet:
      Resource owner:     the org that owns $PLANNING_REPO
      Repository access:  Only select repositories -> $PLANNING_REPO
      Repository perms:   Contents: Read and write
                           (the permission that authorises
                           'POST /repos/.../dispatches';
                           no Issues/PRs/Projects needed)
EOF
  read -rsp "Paste the dispatch-token PAT (hidden): " DISPATCH_PAT; echo
  [ -n "$DISPATCH_PAT" ] || die "no PAT provided"
  printf '%s' "$DISPATCH_PAT" | gh secret set "$SECRET_NAME" --repo "$DEST_REPO"
  unset DISPATCH_PAT
  echo "    stored secret $SECRET_NAME on $DEST_REPO"
fi

echo
echo "Done. $DEST_REPO now dispatches its PR events to $PLANNING_REPO,"
if [ "$WITH_ADAPTER" != "0" ]; then
  echo "and carries the planning-skills adapter pointing at that board."
fi
echo "The caller is a non-required check — no branch-protection change needed."

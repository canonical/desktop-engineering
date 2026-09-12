#!/usr/bin/env bash
#
# onboard-code-repo.sh — install/update the per-repo PR-dispatch caller in one
# destination code repo, idempotently (ticket 35).
#
# Every destination code repo whose PRs should move planning-repo cards
# needs exactly one thing installed: `.github/workflows/ai-planning-pr.yml`,
# a ~6-line caller that dispatches its PR events to the planning repo (see
# `adapter/ai-planning-pr.yml`, the template this script stamps and pushes).
# It is a **non-required, cosmetic** check — the real work (link-authoring +
# scoring) runs in the planning repo, not here.
#
# This script:
#   1. stamps the template with the planning repo (`<org>/<planning-repo>`),
#   2. writes it to the destination repo's default branch via the Contents
#      API — no local clone, no PR: a direct, idempotent commit, skipped
#      entirely when the destination already carries byte-identical content,
#   3. prompts for the dispatch-token PAT and registers it as
#      AI_PLANNING_DISPATCH_TOKEN on the destination repo.
#
# The PAT itself (fine-grained, scoped to the **planning** repo, Contents:write
# only — least privilege for `POST /repos/{owner}/{repo}/dispatches`) is minted
# once in the browser and kept in Bitwarden under a location named after the
# planning repo (e.g. `desktop-apps-ai-planning`); this script never mints it,
# only pastes+stores the same value on each destination repo in turn.
#
# Re-runnable: re-onboarding an already-onboarded repo with the same inputs is
# a no-op on the caller file (byte-identical) and a harmless overwrite on the
# secret. Extending `canonical-repo-automation` for this was considered and
# rejected — this stays its own small, single-purpose script.
#
# Prereqs: `gh` authenticated with `repo` scope on the destination repo, jq.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/adapter/ai-planning-pr.yml"
CALLER_PATH=".github/workflows/ai-planning-pr.yml"
SECRET_NAME="AI_PLANNING_DISPATCH_TOKEN"

# --- config (env-overridable) ------------------------------------------------
DEST_REPO="${DEST_REPO:-}"           # the code repo to onboard, e.g. acme/some-app
PLANNING_REPO="${PLANNING_REPO:-}"   # the planning repo the caller dispatches to
REF="${REF:-ai_planning_board}"      # ref of desktop-engineering providing the reusable workflow

die() { echo "error: $*" >&2; exit 1; }

command -v gh >/dev/null || die "gh (GitHub CLI) is required"
command -v jq >/dev/null || die "jq is required"
[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"

[ -n "$DEST_REPO" ] || read -rp "Destination code repo to onboard (owner/repo): " DEST_REPO
[ -n "$DEST_REPO" ] || die "DEST_REPO is required"
[ -n "$PLANNING_REPO" ] || read -rp "Planning repo this caller dispatches to (owner/repo): " PLANNING_REPO
[ -n "$PLANNING_REPO" ] || die "PLANNING_REPO is required"

echo "==> onboarding $DEST_REPO -> dispatches to $PLANNING_REPO (ref $REF)"
gh repo view "$DEST_REPO" >/dev/null 2>&1 || die "cannot see destination repo '$DEST_REPO'"

# --- 1 + 2. stamp the caller template and push it, idempotently -------------
STAMPED="$(mktemp)"
trap 'rm -f "$STAMPED"' EXIT
sed \
  -e "s|<org>/<planning-repo>|$PLANNING_REPO|g" \
  -e "s|@ai_planning_board|@$REF|g" \
  "$TEMPLATE" > "$STAMPED"

DEFAULT_BRANCH="$(gh repo view "$DEST_REPO" --json defaultBranchRef --jq .defaultBranchRef.name)"
NEW_CONTENT_B64="$(base64 -w0 < "$STAMPED")"

EXISTING="$(gh api "repos/$DEST_REPO/contents/$CALLER_PATH" --jq '{sha,content}' 2>/dev/null || true)"
if [ -n "$EXISTING" ]; then
  EXISTING_CONTENT_B64="$(echo "$EXISTING" | jq -r '.content' | tr -d '\n')"
  if [ "$EXISTING_CONTENT_B64" = "$NEW_CONTENT_B64" ]; then
    echo "==> $CALLER_PATH already up to date on $DEST_REPO"
  else
    SHA="$(echo "$EXISTING" | jq -r '.sha')"
    gh api --method PUT "repos/$DEST_REPO/contents/$CALLER_PATH" \
      -f message="ai-planning: update PR-dispatch caller" \
      -f content="$NEW_CONTENT_B64" \
      -f sha="$SHA" \
      -f branch="$DEFAULT_BRANCH" >/dev/null
    echo "==> updated $CALLER_PATH on $DEST_REPO"
  fi
else
  gh api --method PUT "repos/$DEST_REPO/contents/$CALLER_PATH" \
    -f message="ai-planning: install PR-dispatch caller" \
    -f content="$NEW_CONTENT_B64" \
    -f branch="$DEFAULT_BRANCH" >/dev/null
  echo "==> installed $CALLER_PATH on $DEST_REPO"
fi

# --- 3. dispatch-token secret -------------------------------------------------
cat <<EOF

==> Dispatch-token PAT
    Paste the token stored in Bitwarden under the planning repo's entry
    ($PLANNING_REPO). Mint one at
    https://github.com/settings/personal-access-tokens/new if it doesn't
    exist yet:
      Resource owner:     the org that owns $PLANNING_REPO
      Repository access:  Only select repositories -> $PLANNING_REPO
      Repository perms:   Contents: Read and write
                           (least privilege for POST /repos/.../dispatches;
                           no Issues/PRs/Projects access needed)
EOF
read -rsp "Paste the dispatch-token PAT (hidden): " DISPATCH_PAT; echo
[ -n "$DISPATCH_PAT" ] || die "no PAT provided"
printf '%s' "$DISPATCH_PAT" | gh secret set "$SECRET_NAME" --repo "$DEST_REPO"
unset DISPATCH_PAT
echo "    stored secret $SECRET_NAME on $DEST_REPO"

echo
echo "Done. $DEST_REPO now dispatches its PR events to $PLANNING_REPO."
echo "The caller is a non-required check — no branch-protection change needed."

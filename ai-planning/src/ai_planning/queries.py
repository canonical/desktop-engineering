"""The GraphQL documents the I/O shell sends. Strings only — no logic.

Kept in one place so the fetch and write shells stay declarative: every branch
that decides a Status lives in `sync_status`, never in a query.
"""

# Read the Project's Status single-select field: its node id and the id of each
# option. The writer needs option ids to set a value; the option *names* are the
# exact `Status` enum values (Ready · Blocked · In progress · In review · Done).
STATUS_FIELD_QUERY = """
query($projectId: ID!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      field(name: "Status") {
        ... on ProjectV2SingleSelectField {
          id
          options { id name }
        }
      }
    }
  }
}
"""

# How many linked-PR nodes to read per issue in the per-item embed and per page
# of the stand-alone pager. A deliberate native link
# (`closedByPullRequestsReferences(userLinkedOnly: true)`) is already a narrow
# set, so one page covers all but the most-linked tickets; anything beyond is
# paged (see `ISSUE_LINKED_PRS_QUERY`).
LINKED_PR_PAGE_SIZE = 50

# The linked-PR node selection, shared verbatim by the per-item embed (below)
# and the stand-alone pager (`ISSUE_LINKED_PRS_QUERY`) so the two paths that feed
# `has_merged_linked_pr` / `has_open_non_draft_pr` / `has_open_draft_pr` never
# drift.
_LINKED_PR_FIELDS = """
  state
  isDraft
  merged
"""

# The per-item selection, shared by the paged board read and the single-item
# read below so both always expose the exact same facts (no drift between the two
# paths that feed `item_to_facts`). `status: fieldValueByName(name: "Status")`
# reads the card's *current* Status option id so the writer can skip a card
# already in the right column (a no-op write on GitHub, skipped to save the API
# call and avoid board churn). `issueDependenciesSummary.blockedBy` gives the
# open blocker count. `subIssues` gives the native sub-issue children the job
# needs for the parent's child-In-progress roll-up (two-pass sync: leaves
# first, then parents).
#
# `closedByPullRequestsReferences(userLinkedOnly: true, includeClosedPrs: true)`
# is the **sole** PR read: it is GitHub's deliberate-link connection (a PR body
# `Closes #n`, or a manually attached link), not a mere mention, so a card only
# ever scores off a PR someone actually linked to it — cross-repo and
# same-repo alike, no repo allow-list needed. `pageInfo` lets the job page the
# rest (via `ISSUE_LINKED_PRS_QUERY`) when an issue carries more linked PRs
# than one page.
_ITEM_NODE_FIELDS = """
  id
  status: fieldValueByName(name: "Status") {
    ... on ProjectV2ItemFieldSingleSelectValue {
      optionId
    }
  }
  content {
    __typename
    ... on Issue {
      id
      number
      state
      assignees { totalCount }
      labels(first: 50) { nodes { name } }
      issueDependenciesSummary { blockedBy }
      closedByPullRequestsReferences(
        first: %d
        userLinkedOnly: true
        includeClosedPrs: true
      ) {
        pageInfo { hasNextPage endCursor }
        nodes { %s }
      }
      subIssues(first: 50) {
        nodes { id }
      }
    }
    ... on PullRequest {
      id
      number
      state
      assignees { totalCount }
      labels(first: 50) { nodes { name } }
    }
  }
""" % (LINKED_PR_PAGE_SIZE, _LINKED_PR_FIELDS)

# Enumerate Project items one page at a time, reading each item's underlying
# issue/PR facts cross-repo (see `_ITEM_NODE_FIELDS`). `$cursor` is null on the
# first page.
PROJECT_ITEMS_QUERY = """
query($projectId: ID!, $pageSize: Int!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: $pageSize, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          %s
        }
      }
    }
  }
}
""" % _ITEM_NODE_FIELDS

# Read one Project item directly by its *item* node id (the id
# `addProjectV2ItemById` returns). Used to sync a card the board's paged read
# didn't surface yet: Projects v2 list reads are eventually consistent, so a card
# added earlier in the same run can be missing from the immediate re-read, but a
# read of the returned item id is consistent. Same fields as the paged read.
PROJECT_ITEM_QUERY = """
query($itemId: ID!) {
  node(id: $itemId) {
    ... on ProjectV2Item {
      %s
    }
  }
}
""" % _ITEM_NODE_FIELDS

# Write one synced Status back onto a card as the single-select option id.
UPDATE_STATUS_MUTATION = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId: $itemId
    fieldId: $fieldId
    value: { singleSelectOptionId: $optionId }
  }) {
    projectV2Item { id }
  }
}
"""

# Pass 0 (seed the board): list the planning repo's OPEN issues so the sweep can
# add any not yet carded. Open-only by design — closed cards already on the board
# stay and go Done via the sweep; seeding the full closed history would grow the
# board unboundedly. Returns each issue's own content node id (what the board
# stores and what `addProjectV2ItemById` takes). `$cursor` is null on page one.
REPO_ISSUES_QUERY = """
query($owner: String!, $name: String!, $pageSize: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: $pageSize, after: $cursor, states: [OPEN]) {
      pageInfo { hasNextPage endCursor }
      nodes { id }
    }
  }
}
"""

# Add one issue/PR to the Project by its content node id. Idempotent: if the
# content is already an item, GitHub returns the existing item without
# duplicating, so a re-seed of an already-carded issue is harmless.
ADD_ITEM_MUTATION = """
mutation($projectId: ID!, $contentId: ID!) {
  addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
    item { id }
  }
}
"""

# Page an issue's linked-PR connection beyond the first page embedded in the
# item read, keyed by the issue's own node id (`$cursor` null on page one). Only
# reached when an issue carries more deliberately-linked PRs than one page — the
# fields match `_LINKED_PR_FIELDS` exactly so the paged tail scores identically
# to the embedded head.
ISSUE_LINKED_PRS_QUERY = """
query($issueId: ID!, $pageSize: Int!, $cursor: String) {
  node(id: $issueId) {
    ... on Issue {
      closedByPullRequestsReferences(
        first: $pageSize
        after: $cursor
        userLinkedOnly: true
        includeClosedPrs: true
      ) {
        pageInfo { hasNextPage endCursor }
        nodes { %s }
      }
    }
  }
}
""" % _LINKED_PR_FIELDS

# Close one issue by its node id, marked COMPLETED. The sweep self-closes an
# implementation ticket whose deliberately-linked PR has merged while the issue
# is still open (e.g. a spec-branch PR, whose closing keyword GitHub treats as
# inert), so the native `blocked_by` dependency clears and dependents unblock.
# Uses the PAT's existing `Issues: write`; idempotent enough in practice (only
# issued for a still-OPEN issue, and re-closing a closed issue is a harmless
# no-op on GitHub — including when GitHub's own native close already fired).
CLOSE_ISSUE_MUTATION = """
mutation($issueId: ID!) {
  closeIssue(input: { issueId: $issueId, stateReason: COMPLETED }) {
    issue { id state }
  }
}
"""

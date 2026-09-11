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

# How many CROSS_REFERENCED_EVENT timeline entries to read per issue in the
# per-item embed and per page of the stand-alone pager. Cross-references are
# already a narrow slice of an issue's timeline, so one page covers all but the
# most-referenced tickets; anything beyond is paged (see `ISSUE_TIMELINE_QUERY`).
TIMELINE_PAGE_SIZE = 50

# The CROSS_REFERENCED_EVENT selection, shared verbatim by the per-item embed
# (below) and the stand-alone timeline pager (`ISSUE_TIMELINE_QUERY`) so the two
# paths that feed `_has_merged_linked_pr` never drift. `willCloseTarget` is read
# for observability only — it is *false* on a spec-branch PR (GitHub honours a
# closing keyword only against the repo's default branch), so the fact keys off
# `source.merged`/`state`, never `willCloseTarget`. `isCrossRepository` and the
# source repo's `nameWithOwner` are the false-positive guard: only a MERGED PR in
# an allow-listed destination repo, cross-repository, completes the ticket.
_TIMELINE_XREF_FIELDS = """
  ... on CrossReferencedEvent {
    willCloseTarget
    isCrossRepository
    source {
      __typename
      ... on PullRequest {
        number
        state
        merged
        baseRefName
        repository { nameWithOwner }
      }
    }
  }
"""

# The per-item selection, shared by the paged board read and the single-item
# read below so both always expose the exact same facts (no drift between the two
# paths that feed `item_to_facts`). `status: fieldValueByName(name: "Status")`
# reads the card's *current* Status option id so the writer can skip a card
# already in the right column (a no-op write on GitHub, skipped to save the API
# call and avoid board churn). `closedByPullRequestsReferences` gives the PRs that
# would close the issue; `issueDependenciesSummary.blockedBy` gives the open
# blocker count. `subIssues` gives the native sub-issue children the job needs
# for the parent's child-In-progress roll-up (two-pass sync: leaves first,
# then parents).
#
# `timelineItems(itemTypes: [CROSS_REFERENCED_EVENT])` is the timeline fallback
# (ticket 06): `closedByPullRequestsReferences` only lists PRs that *would close*
# the issue, which GitHub populates solely for PRs targeting the repo default
# branch. An implementation PR targets a **spec branch**, so its closing keyword
# is inert and that connection stays empty — but the mention still lands a
# CROSS_REFERENCED_EVENT on this issue's timeline, which is what detects the merge.
# `pageInfo` lets the job page the rest (via `ISSUE_TIMELINE_QUERY`) when an issue
# carries more cross-references than one page.
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
      closedByPullRequestsReferences(first: 20, includeClosedPrs: true) {
        nodes { state isDraft }
      }
      timelineItems(first: %d, itemTypes: [CROSS_REFERENCED_EVENT]) {
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
""" % (TIMELINE_PAGE_SIZE, _TIMELINE_XREF_FIELDS)

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

# Page an issue's CROSS_REFERENCED_EVENT timeline beyond the first page embedded
# in the item read, keyed by the issue's own node id (`$cursor` null on page one).
# Only reached when an issue carries more cross-references than one page — the
# fields match `_TIMELINE_XREF_FIELDS` exactly so the paged tail scores identically
# to the embedded head.
ISSUE_TIMELINE_QUERY = """
query($issueId: ID!, $pageSize: Int!, $cursor: String) {
  node(id: $issueId) {
    ... on Issue {
      timelineItems(first: $pageSize, after: $cursor, itemTypes: [CROSS_REFERENCED_EVENT]) {
        pageInfo { hasNextPage endCursor }
        nodes { %s }
      }
    }
  }
}
""" % _TIMELINE_XREF_FIELDS

# Close one issue by its node id, marked COMPLETED. The sweep closes an
# implementation ticket whose spec-branch PR has merged (detected via the
# timeline fallback) but whose closing keyword was inert, so the native
# `blocked_by` dependency clears and dependents unblock. Uses the PAT's existing
# `Issues: write`; idempotent enough in practice (only issued for a still-OPEN
# issue, and re-closing a closed issue is a harmless no-op on GitHub).
CLOSE_ISSUE_MUTATION = """
mutation($issueId: ID!) {
  closeIssue(input: { issueId: $issueId, stateReason: COMPLETED }) {
    issue { id state }
  }
}
"""

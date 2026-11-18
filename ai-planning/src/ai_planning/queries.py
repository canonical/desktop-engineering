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
# of the stand-alone pager. A closing link
# (`closedByPullRequestsReferences(userLinkedOnly: false)` — a closing keyword
# or a manually attached link, never a mere mention) is already a narrow set, so
# one page covers all but the most-linked tickets; anything beyond is paged (see
# `ISSUE_LINKED_PRS_QUERY`).
LINKED_PR_PAGE_SIZE = 50

# The linked-PR node selection, shared verbatim by the per-item embed (below)
# and the stand-alone pager (`ISSUE_LINKED_PRS_QUERY`) so the two paths that feed
# the PR facts (`has_merged_linked_pr`, the folded `pr_state`/`pr_ci_ok`/
# `pr_approved`) never drift. The nodes are full PullRequest objects, so the
# review decision and the check rollup ride the same connection.
_LINKED_PR_FIELDS = """
  state
  isDraft
  merged
  reviewDecision
  statusCheckRollup { state }
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
# `closedByPullRequestsReferences(userLinkedOnly: false, includeClosedPrs: true)`
# is the **sole** PR read: it is GitHub's closing-link connection (a PR body
# `Closes #n`, whether same-repo or a manually attached link), not a mere
# mention, so a card only ever scores off a PR that actually closes it —
# cross-repo and same-repo alike, no repo allow-list needed. `userLinkedOnly:
# false` is deliberate: `true` returns ONLY manually attached links and drops a
# same-repo closing *keyword*, which is exactly the deliberate signal we want to
# count; `false` still excludes bare mentions (only closing references appear at
# all). `pageInfo` lets the job page the rest (via `ISSUE_LINKED_PRS_QUERY`)
# when an issue carries more linked PRs than one page.
_ITEM_NODE_FIELDS = """
  id
  isArchived
  status: fieldValueByName(name: "Status") {
    ... on ProjectV2ItemFieldSingleSelectValue {
      optionId
    }
  }
  map: fieldValueByName(name: "Map") {
    ... on ProjectV2ItemFieldSingleSelectValue {
      optionId
    }
  }
  spec: fieldValueByName(name: "Spec") {
    ... on ProjectV2ItemFieldSingleSelectValue {
      optionId
    }
  }
  content {
    __typename
    ... on Issue {
      id
      number
      title
      state
      repository { nameWithOwner }
      parent {
        id
        state
        repository { nameWithOwner }
        labels(first: 50) { nodes { name } }
        projectItems(first: 20) { nodes { isArchived project { id } } }
      }
      assignees { totalCount }
      labels(first: 50) { nodes { name } }
      issueDependenciesSummary { blockedBy }
      closedByPullRequestsReferences(
        first: %d
        userLinkedOnly: false
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
      title
      state
      isDraft
      merged
      baseRefName
      headRefName
      reviewDecision
      statusCheckRollup { state }
      assignees { totalCount }
      labels(first: 50) { nodes { name } }
    }
  }
""" % (LINKED_PR_PAGE_SIZE, _LINKED_PR_FIELDS)

# Enumerate Project items one page at a time, reading each item's underlying
# issue/PR facts cross-repo (see `_ITEM_NODE_FIELDS`). `$cursor` is null on the
# first page. ARCHIVED items are read too (`archivedStates` defaults to
# not-archived only): the sweep must see hidden cards to leave them hidden —
# otherwise the seed re-cards a closed issue whose card is archived, the add
# un-archives it, and the archive arm re-archives it, every run.
PROJECT_ITEMS_QUERY = """
query($projectId: ID!, $pageSize: Int!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: $pageSize, after: $cursor, archivedStates: [NOT_ARCHIVED, ARCHIVED]) {
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
# stores and what `addProjectV2ItemById` takes). `$cursor` is null on page one;
# `$labels` is null for no label filter (the `all` board) or `["squad:<slug>"]`
# to keep one squad's issues (GraphQL ANDs the labels).
REPO_ISSUES_QUERY = """
query($owner: String!, $name: String!, $pageSize: Int!, $cursor: String, $labels: [String!]) {
  repository(owner: $owner, name: $name) {
    issues(first: $pageSize, after: $cursor, states: [OPEN], labels: $labels) {
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
        userLinkedOnly: false
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
# Also used, cross-repo, by the map auto-close cascade to close a map whose
# subtree has settled. Uses the PAT's existing `Issues: write`; idempotent
# enough in practice (only issued for a still-OPEN issue, and re-closing a
# closed issue is a harmless no-op on GitHub — including when GitHub's own
# native close already fired).
CLOSE_ISSUE_MUTATION = """
mutation($issueId: ID!) {
  closeIssue(input: { issueId: $issueId, stateReason: COMPLETED }) {
    issue { id state }
  }
}
"""

# Reopen one issue by its node id. Used solely by the map auto-close cascade:
# a closed map whose subtree gains an open descendant again (any descendant
# reopens) is reopened here, cross-repo, via the same PAT `Issues: write`
# scope as `CLOSE_ISSUE_MUTATION`. A no-op on GitHub when the issue is already
# open.
REOPEN_ISSUE_MUTATION = """
mutation($issueId: ID!) {
  reopenIssue(input: { issueId: $issueId }) {
    issue { id state }
  }
}
"""

# The link-authoring reconcile arm (ticket 33), now also the carding sweep's
# one PR read: page one destination repo's PRs from the *PR side* — an
# unlinked cross-repo PR is invisible from the issue side, so the scan has to
# start here. `states: [OPEN, MERGED]` covers both a PR still awaiting review
# and one whose merge needs its link authored after the fact (the straggler
# case, e.g. a spec-branch merge). `body` and `baseRefName` feed
# `link_authoring.parse_candidate_refs`; the `authoredClosingRefs` embed is
# this PR's own already-authored deliberate links (userLinkedOnly: true), so
# the reconcile arm can skip a PR that already carries its one correct link
# without a second round-trip. The `closingRefs` embed is the *effective*
# closing-link set (userLinkedOnly: false — keyword or manual): what the
# carding sweep maps a stack PR to its ticket, and a spec PR to its spec,
# through. The rest of the fields (branch names, draft flag, review decision,
# check rollup) are the PR-card facts `job` scores and classifies with.
_LINK_AUTHORING_PAGE_SIZE = 20

_CLOSING_REFS_FIELDS = """
  number
  id
  repository { owner { login } name }
"""

REPO_PRS_QUERY = """
query($owner: String!, $name: String!, $pageSize: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(
      first: $pageSize
      after: $cursor
      states: [OPEN, MERGED]
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        number
        body
        state
        isDraft
        baseRefName
        headRefName
        reviewDecision
        statusCheckRollup { state }
        authoredClosingRefs: closingIssuesReferences(first: %d, userLinkedOnly: true) {
          nodes { %s }
        }
        closingRefs: closingIssuesReferences(first: %d, userLinkedOnly: false) {
          nodes { %s }
        }
      }
    }
  }
}
""" % (
    _LINK_AUTHORING_PAGE_SIZE,
    _CLOSING_REFS_FIELDS,
    _LINK_AUTHORING_PAGE_SIZE,
    _CLOSING_REFS_FIELDS,
)

# Resolve one candidate `TicketRef` (parsed from a PR body) to the fact
# `link_authoring.pick_link_target`'s tie-break needs: the issue's own node
# id (the write target for `ADD_CLOSE_ISSUE_REFERENCES_MUTATION`) and its
# labels (to test for `wayfinder:spec`). A ref naming an issue that doesn't
# exist, or the token can't see, resolves to a null `issue` — the caller
# drops it from the candidate set rather than raising.
ISSUE_BY_NUMBER_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id
      labels(first: 50) { nodes { name } }
    }
  }
}
"""

# The immediate arm (ticket 35): read one dispatched PR's already-authored
# deliberate links by number, shaped identically to `REPO_PRS_QUERY`'s
# `closingIssuesReferences` embed so `_already_linked_refs` scores either read
# the same way. The dispatch payload already carries `body`/`baseRefName`, so
# this query fetches only what the payload can't: the PR's node id (the write
# target) and its current links (the read-before-write guard).
PR_BY_NUMBER_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      id
      closingIssuesReferences(first: %d, userLinkedOnly: true) {
        nodes {
          number
          repository { owner { login } name }
        }
      }
    }
  }
}
""" % _LINK_AUTHORING_PAGE_SIZE

# Author one deliberate PR<->issue close-link (`link_authoring.pick_link_target`'s
# chosen target). Additive only: GitHub exposes no complementary "unlink"
# mutation this tooling uses, so authoring stays conservative (see
# `link_authoring`'s docstring) and a wrong link is recovered by hand in the
# GitHub UI. Idempotent in effect — re-adding an already-present link is a
# harmless no-op — but the reconcile arm still reads-before-writing (via
# `closingIssuesReferences` above) to avoid the redundant call.
ADD_CLOSE_ISSUE_REFERENCES_MUTATION = """
mutation($issueId: ID!, $pullRequestId: ID!) {
  addCloseIssueReferences(
    input: { issueId: $issueId, pullRequestIds: [$pullRequestId] }
  ) {
    issue { id }
  }
}
"""

# Resolve an issue by repo + number to its node id, state and labels. The
# manual archive workflow starts from a Map named by the operator, so it needs
# the id to walk down from and the state/label to refuse anything that is not a
# closed Map. A missing issue resolves to a null `issue`.
ISSUE_ROOT_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id
      number
      state
      repository { nameWithOwner }
      labels(first: 50) { nodes { name } }
    }
  }
}
"""

# One level of an issue's sub-issue tree, keyed by the issue's node id:
# its own facts, every Project item it has (so the caller can pick this
# Project's by `project.id`, with `isArchived` telling whether it is already
# hidden), and a page of its direct children. `$subCursor` is null on page one.
ISSUE_SUBTREE_QUERY = """
query($issueId: ID!, $subCursor: String) {
  node(id: $issueId) {
    ... on Issue {
      id
      number
      state
      repository { nameWithOwner }
      projectItems(first: 50) {
        nodes { id isArchived project { id } }
      }
      subIssues(first: 50, after: $subCursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id }
      }
    }
  }
}
"""

# Hide / restore one Project item. Archiving removes the card from every view
# (it stays in the Project and can be restored); it changes nothing on the
# underlying issue. Covered by the PAT's existing org `Projects: write`.
ARCHIVE_ITEM_MUTATION = """
mutation($projectId: ID!, $itemId: ID!) {
  archiveProjectV2Item(input: { projectId: $projectId, itemId: $itemId }) {
    item { id }
  }
}
"""

UNARCHIVE_ITEM_MUTATION = """
mutation($projectId: ID!, $itemId: ID!) {
  unarchiveProjectV2Item(input: { projectId: $projectId, itemId: $itemId }) {
    item { id }
  }
}
"""

# Resolve a label by name in one repo, and add/remove it on an issue. The sweep
# marks a Map whose tree it has archived on a board with that board's
# `wayfinder:archived:<board>` label, so a Map the user later restores is
# recognised and its tree restored too.
LABEL_ID_QUERY = """
query($owner: String!, $name: String!, $label: String!) {
  repository(owner: $owner, name: $name) {
    label(name: $label) { id }
  }
}
"""

ADD_LABEL_MUTATION = """
mutation($issueId: ID!, $labelId: ID!) {
  addLabelsToLabelable(input: { labelableId: $issueId, labelIds: [$labelId] }) {
    clientMutationId
  }
}
"""

REMOVE_LABEL_MUTATION = """
mutation($issueId: ID!, $labelId: ID!) {
  removeLabelsFromLabelable(input: { labelableId: $issueId, labelIds: [$labelId] }) {
    clientMutationId
  }
}
"""

# --- Board shape: the sweep ensures the board can carry the design. ---

# Read one single-select field of the Project by name: its node id and every
# option (id, name, color, description). Used for Status (the ladder's
# columns), Map and Spec (the stamps). A missing field resolves to a null
# `field`. Color and description are read because rewriting a field's options
# requires BOTH non-null on every option — an option sent without them is
# rejected — so the identity-preserving rewrite must carry what exists.
FIELD_BY_NAME_QUERY = """
query($projectId: ID!, $fieldName: String!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      field(name: $fieldName) {
        ... on ProjectV2SingleSelectField {
          id
          options { id name color description }
        }
      }
    }
  }
}
"""

# Create a single-select field carrying its initial options. Used when the
# board lacks the Map or Spec stamp field (the sweep creates them itself, so
# a board predating this design converges on first run).
CREATE_SINGLE_SELECT_FIELD_MUTATION = """
mutation($projectId: ID!, $fieldName: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  createProjectV2Field(
    input: {
      projectId: $projectId
      name: $fieldName
      dataType: SINGLE_SELECT
      singleSelectOptions: $options
    }
  ) {
    projectV2Field {
      ... on ProjectV2SingleSelectField {
        id
        options { id name }
      }
    }
  }
}
"""

# Rewrite one single-select field's options. Every option that already exists
# is passed WITH its id, which preserves the option's identity — and therefore
# every item's set value ("preventing item field values from being cleared",
# per the schema). Only genuinely new options are passed without an id, so
# this is the one safe way to add a column or a stamp option to a live board:
# never a wipe, never a re-stamp. The full ordered list is sent because the
# API replaces the whole set — there is no append-only mutation.
UPDATE_FIELD_OPTIONS_MUTATION = """
mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  updateProjectV2Field(
    input: { fieldId: $fieldId, singleSelectOptions: $options }
  ) {
    projectV2Field {
      ... on ProjectV2SingleSelectField {
        id
        options { id name }
      }
    }
  }
}
"""

# Clear one field's value on one card — the vanish. A ticket whose own PR is
# open loses the stamps that would place it beside that PR; when the PR
# closes without merging, the next sweep re-stamps and the card reappears.
CLEAR_FIELD_VALUE_MUTATION = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!) {
  clearProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId: $itemId
    fieldId: $fieldId
  }) {
    projectV2Item { id }
  }
}
"""

# The Project's fields (id + name each) — what composing a view's
# visible-field id list needs.
PROJECT_FIELDS_QUERY = """
query($projectId: ID!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      fields(first: 40) {
        nodes {
          ... on ProjectV2FieldCommon {
            id
            name
          }
        }
      }
    }
  }
}
"""

# The Project's views, for ensure-by-name: id, name, layout, filter and the
# names of the fields the view currently shows (the drift check).
PROJECT_VIEWS_QUERY = """
query($projectId: ID!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      views(first: 20) {
        nodes {
          id
          name
          layout
          filter
          fields(first: 20) {
            nodes {
              ... on ProjectV2FieldCommon {
                name
              }
            }
          }
        }
      }
    }
  }
}
"""

# Create a view (name + layout only — the API sets no slice) and then give it
# its filter and visible fields. The slice-by field stays a one-time hand
# click (UI-only), which the setup output says so.
CREATE_VIEW_MUTATION = """
mutation($projectId: ID!, $name: String!, $layout: ProjectV2ViewLayout!) {
  createProjectV2View(input: {
    projectId: $projectId
    name: $name
    layout: $layout
  }) {
    projectV2View { id name layout }
  }
}
"""

UPDATE_VIEW_MUTATION = """
mutation($viewId: ID!, $filter: String, $visibleFieldIds: [ID!]) {
  updateProjectV2View(input: {
    viewId: $viewId
    filter: $filter
    configuration: { visibleFieldIds: $visibleFieldIds }
  }) {
    projectV2View { id name filter }
  }
}
"""

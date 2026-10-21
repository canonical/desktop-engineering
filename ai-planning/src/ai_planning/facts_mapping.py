"""Map a raw GraphQL Project item onto the pure function's `Facts` input.

This is the *read* half of the I/O shell (ticket 03): it turns the native
GitHub facts GraphQL returns into the exact `Facts` tuple `sync_status` eats.
It extracts facts only — it holds **no** precedence branching. The ladder
(Done > Blocked > In review > In progress > Ready) lives solely in
`sync_status`, here we only read what GitHub reports.

A card scores off exactly one PR read: `closedByPullRequestsReferences(
userLinkedOnly: false, includeClosedPrs: true)`, GitHub's closing-link
connection (a closing keyword or a manually attached link). A mere mention
scores nothing — only closing references appear in this connection at all.

A Project item whose `content` is null (a draft item, or an issue the token
cannot see) yields `None`: there is no underlying issue/PR to score, so the job
skips it rather than inventing facts.

`item_content_id` and `item_child_content_ids` are read-only structural
helpers the job uses to correlate a parent with its native sub-issue children
across Project items. They hold no precedence branching either: the roll-up
count itself (`Facts.child_started_count`) is computed by the job from
each child's already-synced Status, then folded back into `Facts` before the
parent is synced.
"""

from __future__ import annotations

from typing import Any

from ai_planning.sync_status import Facts, make_facts

MAP_LABEL = "wayfinder:map"


def _label_names(content: dict[str, Any]) -> list[str]:
    return [node["name"] for node in (content.get("labels") or {}).get("nodes", [])]


def _linked_pr_nodes(content: dict[str, Any]) -> list[dict[str, Any]]:
    """This issue's deliberately-linked PR nodes, or an empty list."""

    refs = content.get("closedByPullRequestsReferences") or {}
    return refs.get("nodes") or []


def _open_non_draft_pr(content: dict[str, Any]) -> bool:
    """True when a linked PR is open and ready (not a draft).

    A draft PR is deliberately excluded: a draft is not a review, so it must
    not push the card into In review (spec: draft PR keeps the card In progress).
    """

    for pr in _linked_pr_nodes(content):
        if pr.get("state") == "OPEN" and not pr.get("isDraft", False):
            return True
    return False


def _open_draft_pr(content: dict[str, Any]) -> bool:
    """True when a linked PR is open and still a draft.

    Lifts the card only as far as In progress — see `sync_status`.
    """

    for pr in _linked_pr_nodes(content):
        if pr.get("state") == "OPEN" and pr.get("isDraft", False):
            return True
    return False


def _merged_pr(content: dict[str, Any]) -> bool:
    """True when a deliberately-linked PR has merged.

    Keyed off `state == "MERGED"`, equivalently the boolean `merged`: either
    is enough, so a payload carrying only one of the two still scores. This
    completes the ticket even while the issue itself is still OPEN (e.g. a
    spec-branch PR, whose closing keyword GitHub treats as inert) — the job
    self-closes the issue when it detects this.
    """

    for pr in _linked_pr_nodes(content):
        if pr.get("merged") is True or pr.get("state") == "MERGED":
            return True
    return False


def linked_prs_page_info(item: dict[str, Any]) -> tuple[bool, str | None]:
    """`(has_next_page, end_cursor)` for this item's linked-PR connection.

    Read-only structural helper: the job uses it to decide whether to page the
    rest of an issue's `closedByPullRequestsReferences` connection (via
    `ISSUE_LINKED_PRS_QUERY`) when it carries more linked PRs than one page.
    """

    content = item.get("content") or {}
    refs = content.get("closedByPullRequestsReferences") or {}
    page_info = refs.get("pageInfo") or {}
    return bool(page_info.get("hasNextPage")), page_info.get("endCursor")


def extend_item_linked_prs(item: dict[str, Any], nodes: list[dict[str, Any]]) -> None:
    """Append paged linked-PR nodes onto this item's content.

    Lets the job fold a paged linked-PR tail back into the item so the single
    `item_to_facts` read scores the full set. A no-op for a contentless item.
    """

    content = item.get("content")
    if not content:
        return
    refs = content.setdefault("closedByPullRequestsReferences", {"nodes": []})
    refs.setdefault("nodes", []).extend(nodes)


def item_current_status_option_id(item: dict[str, Any]) -> str | None:
    """The Status single-select option id already set on this card, if any.

    Read-only, like the other structural helpers here. The job compares this
    against the option id it is about to write and skips the mutation when they
    match, so a card that is already in the right column is never re-written
    (no redundant API call, no board flash).
    """

    status = item.get("status") or {}
    return status.get("optionId")


def item_content_id(item: dict[str, Any]) -> str | None:
    """The underlying issue/PR's own GraphQL node id, or `None` if contentless.

    This is distinct from the Project item's id: sub-issue children are
    reported by their *content* id, so the job needs this to correlate a
    parent's listed children with the Project items that carry them.
    """

    content = item.get("content")
    if not content:
        return None
    return content.get("id")


def item_child_content_ids(item: dict[str, Any]) -> list[str]:
    """The content ids of this item's native sub-issue children, if any.

    Read-only structural extraction, same as the rest of this module: it does
    not know or care what those children's Status is, only which content ids
    to look up.
    """

    content = item.get("content")
    if not content:
        return []
    sub_issues = content.get("subIssues") or {}
    return [
        node["id"] for node in (sub_issues.get("nodes") or []) if node.get("id")
    ]


def item_to_facts(item: dict[str, Any]) -> Facts | None:
    """Map one GraphQL Project item to `Facts`, or `None` if it has no content.

    `None` means "nothing to score" (draft item / invisible content); the job
    skips it. A non-null content of any type (Issue or PullRequest) is mapped:
    every field is read defensively so a partial payload never raises.

    Every PR-derived fact (`has_open_non_draft_pr`, `has_open_draft_pr`,
    `has_merged_linked_pr`) is sourced solely from
    `closedByPullRequestsReferences(userLinkedOnly: false)` — a closing link
    (keyword or manual), cross-repo or same-repo alike. No allow-list or
    cross-repo guard is needed: the closing link itself is the guard.
    """

    content = item.get("content")
    if not content:
        return None

    labels = _label_names(content)
    assignees = content.get("assignees") or {}
    summary = content.get("issueDependenciesSummary") or {}

    return make_facts(
        closed=content.get("state") == "CLOSED",
        open_blocker_count=summary.get("blockedBy") or 0,
        has_open_non_draft_pr=_open_non_draft_pr(content),
        has_open_draft_pr=_open_draft_pr(content),
        assigned=(assignees.get("totalCount") or 0) >= 1,
        is_map=MAP_LABEL in labels,
        has_merged_linked_pr=_merged_pr(content),
    )

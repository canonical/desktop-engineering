"""Map a raw GraphQL Project item onto the pure function's `Facts` input.

This is the *read* half of the I/O shell (ticket 03): it turns the native
GitHub facts GraphQL returns into the exact `Facts` tuple `sync_status` eats.
It extracts facts only — it holds **no** precedence branching. The ladder
(Done > Blocked > In review > In progress > Ready) lives solely in
`sync_status`; here we only read what GitHub reports.

A Project item whose `content` is null (a draft item, or an issue the token
cannot see) yields `None`: there is no underlying issue/PR to score, so the job
skips it rather than inventing facts.

`item_content_id` and `item_child_content_ids` are read-only structural
helpers the job uses to correlate a parent with its native sub-issue children
across Project items. They hold no precedence branching either: the roll-up
count itself (`Facts.child_in_progress_count`) is computed by the job from
each child's already-synced Status, then folded back into `Facts` before the
parent is synced.
"""

from __future__ import annotations

from typing import Any

from ai_planning.sync_status import Facts, make_facts

MAP_LABEL = "wayfinder:map"


def _label_names(content: dict[str, Any]) -> list[str]:
    return [node["name"] for node in (content.get("labels") or {}).get("nodes", [])]


def _open_non_draft_pr(content: dict[str, Any]) -> bool:
    """True when a linked PR that would close this issue is open and ready.

    A draft PR is deliberately excluded: a draft is not a review, so it must
    not push the card into In review (spec: draft PR keeps the card In progress).
    """

    refs = content.get("closedByPullRequestsReferences") or {}
    for pr in refs.get("nodes") or []:
        if pr.get("state") == "OPEN" and not pr.get("isDraft", False):
            return True
    return False


def _timeline_xref_nodes(content: dict[str, Any]) -> list[dict[str, Any]]:
    """The issue's CROSS_REFERENCED_EVENT timeline nodes, or an empty list."""

    timeline = content.get("timelineItems") or {}
    return timeline.get("nodes") or []


def _has_merged_linked_pr(
    content: dict[str, Any], destination_repos: set[str] | None
) -> bool:
    """True when a merged cross-repo destination PR references this issue.

    The timeline fallback (ticket 06): an implementation ticket's PR targets a
    **spec branch**, not the code repo's default branch, so GitHub treats its
    closing keyword as inert — `closedByPullRequestsReferences` stays empty,
    `willCloseTarget` is false, and merging never natively closes the ticket.
    But the mention still lands a CROSS_REFERENCED_EVENT on this issue's
    timeline, so we detect the merge here.

    Keyed off `source.merged` (equivalently `state == "MERGED"`), never
    `willCloseTarget` (always false for a spec-branch PR). Two guards stop an
    unrelated merged PR that merely name-drops the ticket from wrongly
    completing it: the reference must be `isCrossRepository`, and the source
    repo must be in the caller-supplied destination allow-list. An empty/absent
    allow-list matches nothing, so the fallback stays inert until a deployment
    opts in by naming its destination repos.
    """

    allow = destination_repos or set()
    if not allow:
        return False
    for event in _timeline_xref_nodes(content):
        source = event.get("source") or {}
        if source.get("__typename") != "PullRequest":
            continue
        merged = source.get("merged") is True or source.get("state") == "MERGED"
        if not merged:
            continue
        if not event.get("isCrossRepository"):
            continue
        repo = (source.get("repository") or {}).get("nameWithOwner")
        if repo in allow:
            return True
    return False


def item_timeline_page_info(item: dict[str, Any]) -> tuple[bool, str | None]:
    """`(has_next_page, end_cursor)` for this item's cross-reference timeline.

    Read-only structural helper: the job uses it to decide whether to page the
    rest of an issue's CROSS_REFERENCED_EVENT timeline (via `ISSUE_TIMELINE_QUERY`)
    when it carries more references than one embedded page.
    """

    content = item.get("content") or {}
    timeline = content.get("timelineItems") or {}
    page_info = timeline.get("pageInfo") or {}
    return bool(page_info.get("hasNextPage")), page_info.get("endCursor")


def extend_item_timeline(
    item: dict[str, Any], nodes: list[dict[str, Any]]
) -> None:
    """Append paged CROSS_REFERENCED_EVENT nodes onto this item's content.

    Lets the job fold a paged timeline tail back into the item so the single
    `item_to_facts` read scores the full set. A no-op for a contentless item.
    """

    content = item.get("content")
    if not content:
        return
    timeline = content.setdefault("timelineItems", {"nodes": []})
    timeline.setdefault("nodes", []).extend(nodes)


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


def item_to_facts(
    item: dict[str, Any], *, destination_repos: set[str] | None = None
) -> Facts | None:
    """Map one GraphQL Project item to `Facts`, or `None` if it has no content.

    `None` means "nothing to score" (draft item / invisible content); the job
    skips it. A non-null content of any type (Issue or PullRequest) is mapped:
    every field is read defensively so a partial payload never raises.

    `destination_repos` is the allow-list of code repos whose merged PRs may
    complete a cross-repo implementation ticket via the timeline fallback; it is
    threaded straight through to `_has_merged_linked_pr` (no precedence logic
    here). Omit it and the fallback stays inert.
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
        assigned=(assignees.get("totalCount") or 0) >= 1,
        is_map=MAP_LABEL in labels,
        has_merged_linked_pr=_has_merged_linked_pr(content, destination_repos),
    )

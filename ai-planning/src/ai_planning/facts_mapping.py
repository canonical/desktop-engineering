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
    )

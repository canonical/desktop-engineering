"""The board's single point of logic.

`sync_status(facts) -> Status | None` computes a card's Kanban column from
native GitHub facts, with no network. It encodes the locked precedence ladder so
the board can never silently diverge from reality; every I/O shell (GraphQL fetch
on one side, the Project field writer on the other) maps into and out of this
function and holds no branching of its own.

Precedence (first match wins):
    1. closed OR merged linked PR                 -> Done
    2. open blocker (>=1)                       -> Blocked
    3. open non-draft PR                         -> In review
    4. assigned OR >=1 child In progress          -> In progress
    5. otherwise                                 -> Ready

`has_merged_linked_pr` shares the top rung with `closed`: a cross-repo
implementation PR that has merged completes its ticket even though its closing
keyword was inert (it targeted a spec branch, not the repo default branch), so
`closedByPullRequestsReferences`/native closing never fired. The job detects the
merge from the issue timeline and closes the underlying issue; this function
resolves the card to Done either way, so the column is right whether the read
lands before or after that close.

The child roll-up (`child_in_progress_count`) only ever lifts a parent out of
Ready into In progress: Done, Blocked and In review still win on the parent's
own facts regardless of what its children are doing. The job (not this
function) is responsible for syncing children first and rolling their
statuses up into this fact; this function stays pure and takes no part in that
ordering.

A map is skipped unconditionally: it carries no work-Status and is never forced
into a column.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    """The five Kanban columns, as the exact Project single-select option names."""

    READY = "Ready"
    BLOCKED = "Blocked"
    IN_PROGRESS = "In progress"
    IN_REVIEW = "In review"
    DONE = "Done"


@dataclass(frozen=True)
class Facts:
    """The native-GitHub facts a card's Status is synced from.

    `has_open_non_draft_pr` is deliberately narrow: a draft PR is not a review,
    so it is False until the PR is marked ready for review.

    `child_in_progress_count` is the number of this item's sub-issue children
    whose own *synced* Status is In progress. It is computed by the job (a
    two-pass roll-up), never by this function, and it only ever lifts a parent
    out of Ready into In progress.

    `has_merged_linked_pr` is True when the issue's timeline carries a
    CROSS_REFERENCED_EVENT sourced from a MERGED pull request in an allow-listed
    destination repo (cross-repository). It exists because a spec-branch PR's
    closing keyword is inert, so a merge would otherwise never complete the
    ticket. Like `closed`, it resolves the card to Done.
    """

    closed: bool
    open_blocker_count: int
    has_open_non_draft_pr: bool
    assigned: bool
    child_in_progress_count: int = 0
    is_map: bool = False
    has_merged_linked_pr: bool = False


def make_facts(
    *,
    closed: bool,
    open_blocker_count: int,
    has_open_non_draft_pr: bool,
    assigned: bool,
    child_in_progress_count: int = 0,
    is_map: bool = False,
    has_merged_linked_pr: bool = False,
) -> Facts:
    """Build a Facts tuple. Keyword-only so call sites read as a fact table."""

    return Facts(
        closed=closed,
        open_blocker_count=open_blocker_count,
        has_open_non_draft_pr=has_open_non_draft_pr,
        assigned=assigned,
        child_in_progress_count=child_in_progress_count,
        is_map=is_map,
        has_merged_linked_pr=has_merged_linked_pr,
    )


def sync_status(facts: Facts) -> Status | None:
    """Return the Status this card should sync to, or None if it's a map.

    Maps are skipped before any other rule so they are never forced into a
    column, regardless of their underlying issue state.
    """

    if facts.is_map:
        return None
    if facts.closed or facts.has_merged_linked_pr:
        return Status.DONE
    if facts.open_blocker_count >= 1:
        return Status.BLOCKED
    if facts.has_open_non_draft_pr:
        return Status.IN_REVIEW
    if facts.assigned or facts.child_in_progress_count >= 1:
        return Status.IN_PROGRESS
    return Status.READY

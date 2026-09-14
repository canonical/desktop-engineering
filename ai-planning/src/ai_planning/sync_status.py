"""The board's single point of logic.

`sync_status(facts) -> Status | None` computes a card's Kanban column from
native GitHub facts, with no network. It encodes the locked precedence ladder so
the board can never silently diverge from reality; every I/O shell (GraphQL fetch
on one side, the Project field writer on the other) maps into and out of this
function and holds no branching of its own.

Precedence (first match wins):
    1. closed OR merged linked PR                                    -> Done
    2. open blocker (>=1)                                            -> Blocked
    3. open non-draft PR                                             -> In review
    4. assigned OR >=1 started child OR open draft PR                -> In progress
    5. otherwise                                                     -> Ready

`has_merged_linked_pr` shares the top rung with `closed`: a deliberately-linked
PR that has merged completes its ticket even when the issue is still OPEN (e.g.
a spec-branch PR, whose closing keyword GitHub treats as inert, so native
closing never fired). The job self-closes the underlying issue when it detects
this; this function resolves the card to Done either way, so the column is
right whether the read lands before or after that close.

`has_open_draft_pr` is a deliberately-linked PR that is OPEN and still a draft:
a draft is not a review, so it lifts a card only as far as In progress, never
into In review (that rung is reserved for `has_open_non_draft_pr`).

The child roll-up (`child_started_count`) only ever lifts a parent out of
Ready into In progress: Done, Blocked and In review still win on the parent's
own facts regardless of what its children are doing. A child counts as
"started" once its own synced Status is In progress, In review or Done — so a
parent whose sub-issues have begun (or already finished) is at least In
progress, even when none of them is *currently* In progress (e.g. every child
is Done but the parent spec has no PR of its own yet). The job (not this
function) is responsible for syncing children first and rolling their statuses
up into this fact; this function stays pure and takes no part in that ordering.

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

    `has_open_draft_pr` is True when a deliberately-linked PR is OPEN and still
    a draft. It lifts a card only into In progress, never In review.

    `child_started_count` is the number of this item's sub-issue children whose
    own *synced* Status is In progress, In review or Done — i.e. children that
    have begun or already finished. It is computed by the job (a two-pass
    roll-up), never by this function, and it only ever lifts a parent out of
    Ready into In progress (Blocked / In review / Done on the parent's own facts
    still win).

    `has_merged_linked_pr` is True when the issue has a closing-linked PR
    (`closedByPullRequestsReferences(userLinkedOnly: false)`) that is MERGED. It
    exists because a spec-branch PR's closing keyword is inert, so a merge
    would otherwise never complete the ticket. Like `closed`, it resolves the
    card to Done.
    """

    closed: bool
    open_blocker_count: int
    has_open_non_draft_pr: bool
    assigned: bool
    child_started_count: int = 0
    is_map: bool = False
    has_merged_linked_pr: bool = False
    has_open_draft_pr: bool = False


def make_facts(
    *,
    closed: bool,
    open_blocker_count: int,
    has_open_non_draft_pr: bool,
    assigned: bool,
    child_started_count: int = 0,
    is_map: bool = False,
    has_merged_linked_pr: bool = False,
    has_open_draft_pr: bool = False,
) -> Facts:
    """Build a Facts tuple. Keyword-only so call sites read as a fact table."""

    return Facts(
        closed=closed,
        open_blocker_count=open_blocker_count,
        has_open_non_draft_pr=has_open_non_draft_pr,
        assigned=assigned,
        child_started_count=child_started_count,
        is_map=is_map,
        has_merged_linked_pr=has_merged_linked_pr,
        has_open_draft_pr=has_open_draft_pr,
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
    if facts.assigned or facts.child_started_count >= 1 or facts.has_open_draft_pr:
        return Status.IN_PROGRESS
    return Status.READY

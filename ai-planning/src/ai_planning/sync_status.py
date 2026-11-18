"""The board's single point of logic.

`sync_status(facts) -> Status | None` computes a card's Kanban column from
native GitHub facts, with no network. It encodes the locked precedence ladder so
the board can never silently diverge from reality; every I/O shell (GraphQL fetch
on one side, the Project field writer on the other) maps into and out of this
function and holds no branching of its own.

Precedence (first match wins):
    1. closed card OR merged linked PR                               -> Done
    2. open PR approved (reviewDecision APPROVED, not a draft)       -> Approved
    3. open PR ready for review with CI green (or no checks)         -> In review
    4. assigned OR >=1 started child OR an open PR not yet reviewable
       (a draft, or ready with CI red)                               -> In progress
    5. open blocker (>=1)                                            -> Blocked
    6. otherwise                                                     -> Ready

Started work is never shown as Blocked: any claim, any started child, or any
open PR outranks the blocker ("real work beats the blocker"), so rung 5 only
fires when nothing at all is running on the card.

CI-awareness (`pr_ci_ok`) keeps the In review column honest: a PR flipped to
ready while its checks fail — or still pending — stays In progress (the agent's
job is to fix CI immediately); only green (or check-free) ready PRs read as In
review. `pr_approved` is keyed on GitHub's own `reviewDecision`: it fires when a
reviewer other than the PR author approves, which is what the human merge step
waits on (a whole stack merges in one shot once every PR in it is Approved).

The child roll-up (`child_started_count`) lifts a parent on its children's
*synced* Status: any started child (In progress, In review, Approved or Done)
lifts the parent at least into In progress. Only Done still wins on the
parent's own facts regardless of what its children are doing. A child counts as
"started" once its own synced Status is In progress, In review, Approved or
Done. The job (not this function) is responsible for syncing children first and
rolling their statuses up into this fact; this function stays pure and takes no
part in that ordering.

A map is skipped unconditionally: it carries no work-Status and is never forced
into a column.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    """The six Kanban columns, as the exact Project single-select option names."""

    READY = "Ready"
    BLOCKED = "Blocked"
    IN_PROGRESS = "In progress"
    IN_REVIEW = "In review"
    APPROVED = "Approved"
    DONE = "Done"


@dataclass(frozen=True)
class Facts:
    """The native-GitHub facts a card's Status is synced from.

    `pr_state` folds the card's own-or-linked open PR into one value:
    `None` (no open PR), `"draft"` (open, still a draft — lifts only to In
    progress) or `"ready"` (open, ready for review — In review once CI is
    green). When an issue carries several open linked PRs the most advanced
    state wins (ready over draft); PR *cards* score their own state.

    `pr_ci_ok` is the ready PR's check rollup: `True` when every check
    succeeded (or the PR runs no checks at all), `False` when any failed,
    errored or is still pending, `None` when there is no ready PR to score.
    It gates rung 3 only — a red PR is work in progress, whatever its draft
    flag says.

    `pr_approved` is True when the open PR's `reviewDecision` is APPROVED
    (and no review requests changes). GitHub blocks self-approval, so this
    fires exactly when a second reviewer — a teammate or a bot reviewer —
    has approved; it is the human-merge signal.

    `child_started_count` is the number of this item's sub-issue children
    whose own *synced* Status is In progress, In review, Approved or Done —
    children that have begun or already finished. It is computed by the job
    (a two-pass roll-up), never by this function, and it only ever lifts a
    parent out of Ready into In progress (Done on the parent's own facts
    still wins).

    `has_merged_linked_pr` is True when the issue has a closing-linked PR
    (`closedByPullRequestsReferences(userLinkedOnly: false)`) that is MERGED.
    It exists because a spec-branch PR's closing keyword is inert, so a merge
    would otherwise never complete the ticket. Like `closed`, it resolves the
    card to Done.
    """

    closed: bool
    open_blocker_count: int
    assigned: bool
    pr_state: str | None = None
    pr_ci_ok: bool | None = None
    pr_approved: bool = False
    child_started_count: int = 0
    is_map: bool = False
    has_merged_linked_pr: bool = False


def make_facts(
    *,
    closed: bool,
    open_blocker_count: int,
    assigned: bool,
    pr_state: str | None = None,
    pr_ci_ok: bool | None = None,
    pr_approved: bool = False,
    child_started_count: int = 0,
    is_map: bool = False,
    has_merged_linked_pr: bool = False,
) -> Facts:
    """Build a Facts tuple. Keyword-only so call sites read as a fact table."""

    return Facts(
        closed=closed,
        open_blocker_count=open_blocker_count,
        assigned=assigned,
        pr_state=pr_state,
        pr_ci_ok=pr_ci_ok,
        pr_approved=pr_approved,
        child_started_count=child_started_count,
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
    if facts.pr_state == "ready" and facts.pr_approved:
        return Status.APPROVED
    if facts.pr_state == "ready" and facts.pr_ci_ok is not False:
        return Status.IN_REVIEW
    if (
        facts.assigned
        or facts.child_started_count >= 1
        or facts.pr_state is not None  # a draft, or a ready PR with red CI
    ):
        return Status.IN_PROGRESS
    if facts.open_blocker_count >= 1:
        return Status.BLOCKED
    return Status.READY

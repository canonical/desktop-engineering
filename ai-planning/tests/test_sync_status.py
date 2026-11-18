"""Unit tests for the board's single point of logic: sync_status.

Every case is a fact-tuple -> Status assertion, exercising every rung of the
precedence ladder and every tie-break in the spec table. No network, no wiring.

Locked precedence (first match wins):
    closed or merged linked PR -> Done
    > open PR approved -> Approved
    > open PR ready with CI green (or no checks) -> In review
    > assigned or >=1 started child or an open PR not yet reviewable -> In progress
    > open blocker -> Blocked
    > else -> Ready

Real work beats the blocker: a claim, any open PR or a started child lifts a
card out of Blocked; Blocked keeps only unclaimed, PR-less tickets with an open
blocker. CI-awareness keeps In review honest: a ready PR with red (or pending)
checks stays In progress. Approved is GitHub's own reviewDecision — a second
reviewer's verdict, the signal the human merge step waits on. The child roll-up
lifts a parent on its children's synced Status; only Done still wins on the
parent's own facts.

A map fact is skipped entirely (no work-Status), never forced into a column.
"""

import pytest

from ai_planning.sync_status import Status, sync_status, make_facts


@pytest.mark.parametrize(
    "facts, expected",
    [
        # Done dominates everything, including blocker + PR + assigned.
        pytest.param(
            make_facts(
                closed=True,
                open_blocker_count=1,
                assigned=True,
                pr_state="ready",
                pr_ci_ok=True,
            ),
            Status.DONE,
            id="closed+assigned+pr+blocker->Done",
        ),
        # Approved: an approved PR reads Approved even with an open blocker.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                assigned=False,
                pr_state="ready",
                pr_ci_ok=False,
                pr_approved=True,
            ),
            Status.APPROVED,
            id="approved+blocker+redCI->Approved",
        ),
        # In review: ready PR, CI green, no approval yet.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                assigned=True,
                pr_state="ready",
                pr_ci_ok=True,
            ),
            Status.IN_REVIEW,
            id="ready+green->In review",
        ),
        # In review with no checks configured at all: green-or-none.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                assigned=False,
                pr_state="ready",
                pr_ci_ok=None,
            ),
            Status.IN_REVIEW,
            id="ready+noChecks->In review",
        ),
        # CI honesty: a ready PR with failing checks stays In progress — it
        # must never claim In review while red.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                assigned=False,
                pr_state="ready",
                pr_ci_ok=False,
            ),
            Status.IN_PROGRESS,
            id="ready+red->In progress",
        ),
        # Pending checks are not green either.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                assigned=True,
                pr_state="ready",
                pr_ci_ok=False,
            ),
            Status.IN_PROGRESS,
            id="ready+pending->In progress",
        ),
        # A draft PR lifts a card only into In progress, never In review.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                assigned=True,
                pr_state="draft",
            ),
            Status.IN_PROGRESS,
            id="draftPR+assigned->In progress",
        ),
        # In progress: assigned, no PR, no blocker.
        pytest.param(
            make_facts(closed=False, open_blocker_count=0, assigned=True),
            Status.IN_PROGRESS,
            id="open+assigned->In progress",
        ),
        # Ready: the takeable frontier — unblocked AND unassigned.
        pytest.param(
            make_facts(closed=False, open_blocker_count=0, assigned=False),
            Status.READY,
            id="open+unassigned->Ready",
        ),
        # Child roll-up: a started child lifts the parent out of Ready.
        pytest.param(
            make_facts(
                closed=False, open_blocker_count=0, assigned=False, child_started_count=1
            ),
            Status.IN_PROGRESS,
            id="parent+childStarted->In progress",
        ),
        # A started child beats the parent's own blocker.
        pytest.param(
            make_facts(
                closed=False, open_blocker_count=1, assigned=False, child_started_count=1
            ),
            Status.IN_PROGRESS,
            id="parent+blocker+childStarted->In progress",
        ),
        # Blocked: an open blocker with no real work anywhere.
        pytest.param(
            make_facts(closed=False, open_blocker_count=1, assigned=False),
            Status.BLOCKED,
            id="open+blocker->Blocked",
        ),
        # A claim beats an open blocker too.
        pytest.param(
            make_facts(closed=False, open_blocker_count=1, assigned=True),
            Status.IN_PROGRESS,
            id="open+blocker+assigned->In progress",
        ),
        # The parent's own ready PR outranks the child roll-up.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                assigned=False,
                pr_state="ready",
                pr_ci_ok=True,
                child_started_count=1,
            ),
            Status.IN_REVIEW,
            id="parent+pr+childStarted->In review",
        ),
        # A map is skipped entirely: no work-Status.
        pytest.param(
            make_facts(closed=False, open_blocker_count=0, assigned=False, is_map=True),
            None,
            id="map->skipped",
        ),
        # Merged linked PR completes the ticket even while the issue is still
        # OPEN (spec-branch PR: the closing keyword was inert) -> Done.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                assigned=True,
                has_merged_linked_pr=True,
            ),
            Status.DONE,
            id="merged linked PR while open->Done",
        ),
        # Merged linked PR shares the top rung with closed.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                assigned=True,
                pr_state="ready",
                pr_ci_ok=True,
                has_merged_linked_pr=True,
            ),
            Status.DONE,
            id="merged+blocker+pr+assigned->Done",
        ),
        # A draft PR beats an open blocker: real work.
        pytest.param(
            make_facts(
                closed=False, open_blocker_count=1, assigned=False, pr_state="draft"
            ),
            Status.IN_PROGRESS,
            id="draftPR+blocker->In progress",
        ),
        # Several open blockers stay Blocked when nothing runs.
        pytest.param(
            make_facts(closed=False, open_blocker_count=5, assigned=False),
            Status.BLOCKED,
            id="open+severalBlockers->Blocked",
        ),
    ],
)
def test_sync_status_table(facts, expected):
    assert sync_status(facts) == expected


def test_a_map_with_a_merged_linked_pr_is_still_skipped():
    """The map skip precedes the merged-PR rung too: a map is never forced
    into Done, whatever its timeline says."""
    facts = make_facts(
        closed=False,
        open_blocker_count=0,
        assigned=False,
        is_map=True,
        has_merged_linked_pr=True,
    )
    assert sync_status(facts) is None


def test_map_is_skipped_even_when_it_would_otherwise_be_done():
    """The map skip is unconditional: it is never forced into a column,
    even when its underlying facts would otherwise resolve to Done."""
    facts = make_facts(
        closed=True,
        open_blocker_count=3,
        assigned=True,
        is_map=True,
    )
    assert sync_status(facts) is None

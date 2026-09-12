"""Unit tests for the board's single point of logic: sync_status.

Every case is a fact-tuple -> Status assertion, exercising every rung of the
precedence ladder and every tie-break in the spec table. No network, no wiring.

Locked precedence (first match wins):
    closed -> Done > open blocker -> Blocked > open non-draft PR -> In review
    > assigned or >=1 child In progress or open draft PR -> In progress
    > else -> Ready

The child roll-up only lifts a parent out of Ready into In progress; Done,
Blocked and In review still win on the parent's own facts.

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
                has_open_non_draft_pr=True,
                assigned=True,
            ),
            Status.DONE,
            id="closed+assigned+pr+blocker->Done",
        ),
        # Blocked beats In review: an open blocker outranks an open non-draft PR.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=True,
                assigned=False,
            ),
            Status.BLOCKED,
            id="open+blocker+pr->Blocked",
        ),
        # In review: non-draft PR open, no blocker.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=True,
                assigned=True,
            ),
            Status.IN_REVIEW,
            id="open+pr+assigned->In review",
        ),
        # A draft-only PR does NOT count as In review; assigned -> In progress.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=True,
            ),
            Status.IN_PROGRESS,
            id="open+draftPR+assigned->In progress",
        ),
        # In progress: assigned, no PR, no blocker.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=True,
            ),
            Status.IN_PROGRESS,
            id="open+assigned->In progress",
        ),
        # Ready: the takeable frontier — unblocked AND unassigned.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=False,
            ),
            Status.READY,
            id="open+unassigned->Ready",
        ),
        # Child roll-up: unassigned, no PR, no blocker, but a child is In
        # progress -> lifted out of Ready into In progress.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=False,
                child_in_progress_count=1,
            ),
            Status.IN_PROGRESS,
            id="parent+childInProgress->In progress",
        ),
        # The parent's own blocker still beats the child roll-up.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=False,
                assigned=False,
                child_in_progress_count=1,
            ),
            Status.BLOCKED,
            id="parent+blocker+childInProgress->Blocked",
        ),
        # The parent's own open non-draft PR still beats the child roll-up.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=True,
                assigned=False,
                child_in_progress_count=1,
            ),
            Status.IN_REVIEW,
            id="parent+pr+childInProgress->In review",
        ),
        # A map is skipped entirely: no work-Status.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=False,
                is_map=True,
            ),
            None,
            id="map->skipped",
        ),
        # Merged linked PR completes the ticket even while the issue is still
        # OPEN (spec-branch PR: the closing keyword was inert) -> Done.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=True,
                has_merged_linked_pr=True,
            ),
            Status.DONE,
            id="merged linked PR while open->Done",
        ),
        # Merged linked PR shares the top rung with closed: it beats a blocker,
        # an open review PR and assignment, exactly as closed does.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=True,
                assigned=True,
                has_merged_linked_pr=True,
            ),
            Status.DONE,
            id="merged+blocker+pr+assigned->Done",
        ),
        # An open draft PR lifts an otherwise-Ready card into In progress,
        # the same rung as `assigned`/the child roll-up.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=False,
                has_open_draft_pr=True,
            ),
            Status.IN_PROGRESS,
            id="open+draftPR+unassigned->In progress",
        ),
        # The draft PR's own In-progress rung never wins over a blocker.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=False,
                assigned=False,
                has_open_draft_pr=True,
            ),
            Status.BLOCKED,
            id="draftPR+blocker->Blocked",
        ),
        # Nor over an open non-draft PR (In review still outranks it).
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=True,
                assigned=False,
                has_open_draft_pr=True,
            ),
            Status.IN_REVIEW,
            id="draftPR+nonDraftPR->In review",
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
        has_open_non_draft_pr=False,
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
        has_open_non_draft_pr=True,
        assigned=True,
        is_map=True,
    )
    assert sync_status(facts) is None


def test_multiple_open_blockers_still_blocked():
    facts = make_facts(
        closed=False,
        open_blocker_count=5,
        has_open_non_draft_pr=False,
        assigned=True,
    )
    assert sync_status(facts) == Status.BLOCKED

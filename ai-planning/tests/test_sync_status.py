"""Unit tests for the board's single point of logic: sync_status.

Every case is a fact-tuple -> Status assertion, exercising every rung of the
precedence ladder and every tie-break in the spec table. No network, no wiring.

Locked precedence (first match wins):
    closed -> Done
    > open non-draft PR or >=1 child in review -> In review
    > assigned or >=1 started child or open draft PR -> In progress
    > open blocker -> Blocked
    > else -> Ready

Real work beats the blocker: a claim, an open PR or a started child lifts a
card out of Blocked; Blocked keeps only unclaimed, PR-less tickets with an
open blocker. The child roll-up lifts a parent on its children's synced
Status: a child In review lifts the parent to In review, and a child counts as
"started" once its synced Status is In progress, In review or Done, lifting
the parent at least into In progress. Only Done still wins on the parent's own
facts.

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
        # Real work beats the blocker: an open non-draft PR is In review even
        # with an open blocker; Blocked keeps only unclaimed, PR-less tickets.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=True,
                assigned=False,
            ),
            Status.IN_REVIEW,
            id="open+blocker+pr->In review",
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
        # In review through the roll-up: a child in review lifts the parent all
        # the way to In review, even while the parent's own PR is still a draft
        # (a spec whose stack PRs are ready for review is itself in review).
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=False,
                child_in_review_count=1,
                has_open_draft_pr=True,
            ),
            Status.IN_REVIEW,
            id="childInReview+draftPR->In review",
        ),
        # A child in review lifts the parent to In review even with a blocker.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=False,
                assigned=False,
                child_in_review_count=1,
            ),
            Status.IN_REVIEW,
            id="blocker+childInReview->In review",
        ),
        # Done still dominates a child in review.
        pytest.param(
            make_facts(
                closed=True,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=False,
                child_in_review_count=1,
            ),
            Status.DONE,
            id="closed+childInReview->Done",
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
        # Child roll-up: unassigned, no PR, no blocker, but a child has started
        # (In progress / In review / Done) -> lifted out of Ready into In progress.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=False,
                assigned=False,
                child_started_count=1,
            ),
            Status.IN_PROGRESS,
            id="parent+childStarted->In progress",
        ),
        # A started child beats the parent's own blocker: claimed work is In
        # progress even when a blocker is still open.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=False,
                assigned=False,
                child_started_count=1,
            ),
            Status.IN_PROGRESS,
            id="parent+blocker+childStarted->In progress",
        ),
        # Blocked: an open blocker with no real work anywhere — unclaimed, no
        # PR, no started child.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=False,
                assigned=False,
            ),
            Status.BLOCKED,
            id="open+blocker->Blocked",
        ),
        # A claim beats an open blocker too.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=False,
                assigned=True,
            ),
            Status.IN_PROGRESS,
            id="open+blocker+assigned->In progress",
        ),
        # The parent's own open non-draft PR still beats the child roll-up.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=0,
                has_open_non_draft_pr=True,
                assigned=False,
                child_started_count=1,
            ),
            Status.IN_REVIEW,
            id="parent+pr+childStarted->In review",
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
        # A draft PR is real work too: it beats an open blocker.
        pytest.param(
            make_facts(
                closed=False,
                open_blocker_count=1,
                has_open_non_draft_pr=False,
                assigned=False,
                has_open_draft_pr=True,
            ),
            Status.IN_PROGRESS,
            id="draftPR+blocker->In progress",
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
    """Unclaimed, PR-less tickets with several open blockers stay Blocked —
    real work (a claim, a PR, a started child) is what lifts them out."""
    facts = make_facts(
        closed=False,
        open_blocker_count=5,
        has_open_non_draft_pr=False,
        assigned=False,
    )
    assert sync_status(facts) == Status.BLOCKED

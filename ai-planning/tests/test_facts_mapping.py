"""Unit tests for the read-side mapper: GraphQL item -> `Facts`.

These assert the mapper reads native GitHub facts faithfully and holds no
precedence logic of its own (that lives in `sync_status`). No network: every
case is a hand-built payload shaped like the GraphQL response.

Every PR-derived fact of an issue card is sourced solely from
`closedByPullRequestsReferences(userLinkedOnly: false)` — a closing link
(keyword or manual). There is no bare-mention fallback and no repo allow-list:
a mere mention scores nothing (only closing references appear in the
connection), and a linked PR counts whether it's cross-repo or same-repo. A PR
card scores its own fields instead.
"""

from ai_planning.sync_status import make_facts
from ai_planning.facts_mapping import (
    item_child_content_ids,
    item_content_id,
    item_current_stamp_option_ids,
    item_current_status_option_id,
    item_is_archived,
    item_to_facts,
    linked_prs_page_info,
)

from tests.fixtures import issue_item, linked_pr, pr_item


def _issue_item(
    *,
    state="OPEN",
    assignee_count=0,
    labels=(),
    blocked_by=0,
    prs=(),
):
    return issue_item(
        state=state,
        assignees=assignee_count,
        labels=labels,
        blocked_by=blocked_by,
        prs=prs,
    )


def test_open_unassigned_issue_maps_to_bare_facts():
    facts = item_to_facts(_issue_item())
    assert facts == make_facts(
        closed=False,
        open_blocker_count=0,
        assigned=False,
    )


def test_closed_issue_maps_closed_true():
    assert item_to_facts(_issue_item(state="CLOSED")).closed is True


def test_assignees_total_count_maps_to_assigned():
    assert item_to_facts(_issue_item(assignee_count=2)).assigned is True
    assert item_to_facts(_issue_item(assignee_count=0)).assigned is False


def test_blocked_by_count_carries_through():
    assert item_to_facts(_issue_item(blocked_by=3)).open_blocker_count == 3


def test_map_label_sets_is_map():
    assert item_to_facts(_issue_item(labels=("wayfinder:map",))).is_map is True
    assert item_to_facts(_issue_item(labels=("wayfinder:task",))).is_map is False


# --- the folded open-PR facts -------------------------------------------------


def test_open_ready_green_pr_folds_to_ready_and_green():
    prs = [linked_pr(state="OPEN", is_draft=False, rollup_state="SUCCESS")]
    facts = item_to_facts(_issue_item(prs=prs))
    assert facts.pr_state == "ready"
    assert facts.pr_ci_ok is True
    assert facts.pr_approved is False


def test_open_draft_pr_folds_to_draft():
    facts = item_to_facts(_issue_item(prs=[linked_pr(state="OPEN", is_draft=True)]))
    assert facts.pr_state == "draft"
    assert facts.pr_ci_ok is None
    assert facts.pr_approved is False


def test_no_open_pr_folds_to_none():
    facts = item_to_facts(_issue_item())
    assert facts.pr_state is None
    assert facts.pr_ci_ok is None


def test_red_rollup_keeps_the_ready_pr_but_ci_not_ok():
    prs = [linked_pr(state="OPEN", is_draft=False, rollup_state="FAILURE")]
    facts = item_to_facts(_issue_item(prs=prs))
    assert facts.pr_state == "ready"
    assert facts.pr_ci_ok is False


def test_pending_rollup_is_not_green():
    prs = [linked_pr(state="OPEN", is_draft=False, rollup_state="PENDING")]
    assert item_to_facts(_issue_item(prs=prs)).pr_ci_ok is False


def test_no_checks_configured_reads_green():
    prs = [linked_pr(state="OPEN", is_draft=False, rollup_state=None)]
    assert item_to_facts(_issue_item(prs=prs)).pr_ci_ok is True


def test_approval_comes_from_the_review_decision():
    prs = [linked_pr(state="OPEN", is_draft=False, review_decision="APPROVED")]
    facts = item_to_facts(_issue_item(prs=prs))
    assert facts.pr_approved is True
    assert facts.pr_state == "ready"


def test_changes_requested_is_not_approved():
    prs = [
        linked_pr(state="OPEN", is_draft=False, review_decision="CHANGES_REQUESTED")
    ]
    assert item_to_facts(_issue_item(prs=prs)).pr_approved is False


def test_mixed_prs_ready_beats_draft():
    prs = [
        linked_pr(state="CLOSED", is_draft=False),
        linked_pr(state="OPEN", is_draft=True),
        linked_pr(state="OPEN", is_draft=False, rollup_state="SUCCESS"),
    ]
    facts = item_to_facts(_issue_item(prs=prs))
    assert facts.pr_state == "ready"
    assert facts.pr_ci_ok is True


def test_closed_pr_does_not_fold():
    prs = [linked_pr(state="CLOSED", is_draft=False)]
    assert item_to_facts(_issue_item(prs=prs)).pr_state is None


# --- PR cards score their own fields ------------------------------------------


def test_pr_item_draft_maps_to_draft_state():
    facts = item_to_facts(pr_item(is_draft=True))
    assert facts.pr_state == "draft"
    assert facts.closed is False


def test_pr_item_ready_green_maps_to_ready_and_green():
    facts = item_to_facts(pr_item(is_draft=False, rollup_state="SUCCESS"))
    assert facts.pr_state == "ready"
    assert facts.pr_ci_ok is True


def test_pr_item_red_maps_to_ready_but_not_ok():
    facts = item_to_facts(pr_item(is_draft=False, rollup_state="FAILURE"))
    assert facts.pr_state == "ready"
    assert facts.pr_ci_ok is False


def test_pr_item_approved_maps_to_approved():
    facts = item_to_facts(
        pr_item(is_draft=False, rollup_state="SUCCESS", review_decision="APPROVED")
    )
    assert facts.pr_approved is True


def test_pr_item_merged_maps_to_done():
    facts = item_to_facts(pr_item(state="MERGED", merged=True))
    assert facts.closed is True
    assert facts.pr_state is None


def test_pr_item_closed_unmerged_maps_to_done():
    facts = item_to_facts(pr_item(state="CLOSED"))
    assert facts.closed is True


def test_pr_item_has_no_blockers_and_is_never_a_map():
    facts = item_to_facts(pr_item())
    assert facts.open_blocker_count == 0
    assert facts.is_map is False


# --- structural helpers --------------------------------------------------------


def test_item_without_content_is_skipped():
    assert item_to_facts({"id": "PVTI_draft", "content": None}) is None
    assert item_to_facts({"id": "PVTI_draft"}) is None


def test_item_content_id_reads_content_node_id():
    assert item_content_id(_issue_item()) == "I_PVTI_item"
    assert item_content_id({"id": "x", "content": None}) is None
    assert item_content_id({"id": "x"}) is None


def test_item_child_content_ids_reads_sub_issue_children():
    item = issue_item(child_content_ids=("I_child_1", "I_child_2"))
    assert item_child_content_ids(item) == ["I_child_1", "I_child_2"]
    assert item_child_content_ids(_issue_item()) == []
    assert item_child_content_ids({"id": "x", "content": None}) == []


def test_item_current_status_option_id_reads_set_value():
    item = issue_item(status_option_id="opt_in_progress")
    assert item_current_status_option_id(item) == "opt_in_progress"
    # No Status set yet, or the field absent entirely -> None.
    assert item_current_status_option_id(_issue_item()) is None
    assert item_current_status_option_id({"id": "x"}) is None
    assert item_current_status_option_id({"id": "x", "status": None}) is None


def test_item_current_stamp_option_ids_read_map_and_spec():
    item = issue_item(map_option_id="opt_map_1", spec_option_id="opt_spec_1")
    assert item_current_stamp_option_ids(item) == {
        "Map": "opt_map_1",
        "Spec": "opt_spec_1",
    }
    assert item_current_stamp_option_ids(_issue_item()) == {"Map": None, "Spec": None}
    assert item_current_stamp_option_ids({"id": "x"}) == {"Map": None, "Spec": None}


def test_item_is_archived_reads_the_flag():
    assert item_is_archived(issue_item(is_archived=True)) is True
    assert item_is_archived(issue_item()) is False
    assert item_is_archived({"id": "x"}) is False


def test_partial_payload_never_raises():
    # A content node missing the optional connections still maps cleanly.
    facts = item_to_facts({"id": "x", "content": {"state": "OPEN"}})
    assert facts == make_facts(
        closed=False,
        open_blocker_count=0,
        assigned=False,
    )


# --- the deliberately-linked-PR merge fact -----------------------------------


def test_merged_linked_pr_sets_has_merged_linked_pr():
    prs = [linked_pr(state="MERGED", merged=True)]
    assert item_to_facts(_issue_item(prs=prs)).has_merged_linked_pr is True


def test_merged_by_state_alone_still_counts():
    # `state == MERGED` is honoured even if the boolean `merged` is absent.
    pr = linked_pr(state="MERGED")
    pr.pop("merged")
    assert item_to_facts(_issue_item(prs=[pr])).has_merged_linked_pr is True


def test_merged_by_boolean_alone_still_counts():
    # The boolean `merged` is honoured even if `state` says something else.
    pr = linked_pr(state="CLOSED", merged=True)
    assert item_to_facts(_issue_item(prs=[pr])).has_merged_linked_pr is True


def test_open_linked_pr_does_not_set_has_merged_linked_pr():
    prs = [linked_pr(state="OPEN", merged=False)]
    assert item_to_facts(_issue_item(prs=prs)).has_merged_linked_pr is False


def test_no_linked_pr_is_no_merged_pr():
    assert item_to_facts(_issue_item()).has_merged_linked_pr is False


def test_one_qualifying_pr_among_several_is_enough():
    prs = [
        linked_pr(state="OPEN"),
        linked_pr(state="CLOSED"),
        linked_pr(state="MERGED", merged=True),
    ]
    assert item_to_facts(_issue_item(prs=prs)).has_merged_linked_pr is True


def test_linked_prs_page_info_reads_connection_page_info():
    item = issue_item(prs_has_next=True, prs_cursor="cur1")
    assert linked_prs_page_info(item) == (True, "cur1")
    assert linked_prs_page_info(_issue_item()) == (False, None)
    assert linked_prs_page_info({"id": "x", "content": None}) == (False, None)


def test_extend_item_linked_prs_appends_nodes():
    from ai_planning.facts_mapping import extend_item_linked_prs

    item = _issue_item(prs=[linked_pr(state="OPEN")])
    extend_item_linked_prs(item, [linked_pr(state="MERGED", merged=True)])
    assert item_to_facts(item).has_merged_linked_pr is True
    # A contentless item is a no-op, not an error.
    extend_item_linked_prs({"id": "x", "content": None}, [linked_pr()])

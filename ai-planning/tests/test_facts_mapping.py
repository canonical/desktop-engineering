"""Unit tests for the read-side mapper: GraphQL item -> `Facts`.

These assert the mapper reads native GitHub facts faithfully and holds no
precedence logic of its own (that lives in `sync_status`). No network: every
case is a hand-built payload shaped like the GraphQL response.
"""

from ai_planning.sync_status import make_facts
from ai_planning.facts_mapping import item_to_facts

from tests.fixtures import issue_item


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
        has_open_non_draft_pr=False,
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


def test_open_non_draft_pr_is_review_signal():
    prs = [{"state": "OPEN", "isDraft": False}]
    assert item_to_facts(_issue_item(prs=prs)).has_open_non_draft_pr is True


def test_draft_pr_does_not_count_as_review():
    prs = [{"state": "OPEN", "isDraft": True}]
    assert item_to_facts(_issue_item(prs=prs)).has_open_non_draft_pr is False


def test_closed_pr_does_not_count_as_review():
    prs = [{"state": "CLOSED", "isDraft": False}]
    assert item_to_facts(_issue_item(prs=prs)).has_open_non_draft_pr is False


def test_mixed_prs_one_open_non_draft_is_enough():
    prs = [
        {"state": "CLOSED", "isDraft": False},
        {"state": "OPEN", "isDraft": True},
        {"state": "OPEN", "isDraft": False},
    ]
    assert item_to_facts(_issue_item(prs=prs)).has_open_non_draft_pr is True


def test_item_without_content_is_skipped():
    assert item_to_facts({"id": "PVTI_draft", "content": None}) is None
    assert item_to_facts({"id": "PVTI_draft"}) is None


def test_item_content_id_reads_content_node_id():
    from ai_planning.facts_mapping import item_content_id

    assert item_content_id(_issue_item()) == "I_PVTI_item"
    assert item_content_id({"id": "x", "content": None}) is None
    assert item_content_id({"id": "x"}) is None


def test_item_child_content_ids_reads_sub_issue_children():
    from ai_planning.facts_mapping import item_child_content_ids

    item = issue_item(child_content_ids=("I_child_1", "I_child_2"))
    assert item_child_content_ids(item) == ["I_child_1", "I_child_2"]
    assert item_child_content_ids(_issue_item()) == []
    assert item_child_content_ids({"id": "x", "content": None}) == []


def test_item_current_status_option_id_reads_set_value():
    from ai_planning.facts_mapping import item_current_status_option_id

    item = issue_item(status_option_id="opt_in_progress")
    assert item_current_status_option_id(item) == "opt_in_progress"
    # No Status set yet, or the field absent entirely -> None.
    assert item_current_status_option_id(_issue_item()) is None
    assert item_current_status_option_id({"id": "x"}) is None
    assert item_current_status_option_id({"id": "x", "status": None}) is None


def test_partial_payload_never_raises():
    # A content node missing the optional connections still maps cleanly.
    facts = item_to_facts({"id": "x", "content": {"state": "OPEN"}})
    assert facts == make_facts(
        closed=False,
        open_blocker_count=0,
        has_open_non_draft_pr=False,
        assigned=False,
    )

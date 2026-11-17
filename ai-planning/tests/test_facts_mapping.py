"""Unit tests for the read-side mapper: GraphQL item -> `Facts`.

These assert the mapper reads native GitHub facts faithfully and holds no
precedence logic of its own (that lives in `sync_status`). No network: every
case is a hand-built payload shaped like the GraphQL response.

Every PR-derived fact is sourced solely from `closedByPullRequestsReferences(
userLinkedOnly: false)` — a closing link (keyword or manual). There is no bare-
mention fallback and no repo allow-list: a mere mention scores nothing (only
closing references appear in the connection), and a linked PR counts whether
it's cross-repo or same-repo.
"""

from ai_planning.sync_status import make_facts
from ai_planning.facts_mapping import item_to_facts

from tests.fixtures import issue_item, linked_pr


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
    prs = [linked_pr(state="OPEN", is_draft=False)]
    assert item_to_facts(_issue_item(prs=prs)).has_open_non_draft_pr is True


def test_draft_pr_does_not_count_as_review():
    prs = [linked_pr(state="OPEN", is_draft=True)]
    facts = item_to_facts(_issue_item(prs=prs))
    assert facts.has_open_non_draft_pr is False
    assert facts.has_open_draft_pr is True


def test_open_draft_pr_is_false_when_no_pr_is_linked():
    assert item_to_facts(_issue_item()).has_open_draft_pr is False


def test_closed_pr_does_not_count_as_review():
    prs = [linked_pr(state="CLOSED", is_draft=False)]
    assert item_to_facts(_issue_item(prs=prs)).has_open_non_draft_pr is False


def test_mixed_prs_one_open_non_draft_is_enough():
    prs = [
        linked_pr(state="CLOSED", is_draft=False),
        linked_pr(state="OPEN", is_draft=True),
        linked_pr(state="OPEN", is_draft=False),
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
    from ai_planning.facts_mapping import linked_prs_page_info

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

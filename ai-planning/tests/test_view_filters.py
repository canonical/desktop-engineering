import pytest

from ai_planning.view_filters import (
    board_filter_for_closed_maps,
    closed_map_parent_issue_refs,
)


def test_closed_map_parent_refs_cover_the_full_cross_repo_subissue_tree():
    refs = closed_map_parent_issue_refs(
        closed_map_item_ids={"i_map"},
        item_id_by_content_id={
            "C_spec": "i_spec",
            "C_ticket": "i_ticket",
            "C_task": "i_task",
        },
        child_content_ids_by_item_id={
            "i_map": ["C_spec", "C_task"],
            "i_spec": ["C_ticket"],
            "i_ticket": [],
            "i_task": [],
        },
        issue_ref_by_item_id={
            "i_map": "canonical/desktop-apps-ai-planning#10",
            "i_spec": "canonical/warty-whisperer#459",
            "i_ticket": "canonical/desktop-apps-ai-planning#11",
            "i_task": "canonical/desktop-apps-ai-planning#12",
        },
    )

    # `parent-issue` selects direct children, so include the Map and the Spec
    # (which is itself a parent) but not leaf tickets.
    assert refs == {
        "canonical/desktop-apps-ai-planning#10",
        "canonical/warty-whisperer#459",
    }


def test_closed_map_parent_refs_ignore_children_not_on_the_project():
    refs = closed_map_parent_issue_refs(
        closed_map_item_ids={"i_map"},
        item_id_by_content_id={},
        child_content_ids_by_item_id={"i_map": ["C_off_board"]},
        issue_ref_by_item_id={"i_map": "canonical/planning#10"},
    )

    assert refs == {"canonical/planning#10"}


def test_closed_map_parent_refs_fail_if_a_parent_has_no_issue_reference():
    with pytest.raises(ValueError, match="missing issue reference"):
        closed_map_parent_issue_refs(
            closed_map_item_ids={"i_map"},
            item_id_by_content_id={},
            child_content_ids_by_item_id={"i_map": ["C_child"]},
            issue_ref_by_item_id={},
        )


def test_board_filter_replaces_map_clauses_and_preserves_other_terms():
    current_filter = (
        '-label:wayfinder:map status:"In progress" '
        '-parent-issue:"canonical/old-map#1"'
    )

    result = board_filter_for_closed_maps(
        current_filter,
        {
            "canonical/warty-whisperer#459",
            "canonical/desktop-apps-ai-planning#10",
            "canonical/warty-whisperer#459",
        },
    )

    assert result == (
        '-label:wayfinder:map status:"In progress" '
        '-parent-issue:"canonical/desktop-apps-ai-planning#10" '
        '-parent-issue:"canonical/warty-whisperer#459"'
    )


def test_board_filter_removes_map_clauses_when_no_maps_are_closed():
    assert board_filter_for_closed_maps(
        '-label:wayfinder:map -parent-issue:"canonical/map#10"', set()
    ) == "-label:wayfinder:map"


def test_board_filter_rejects_unquotable_issue_refs():
    with pytest.raises(ValueError, match="invalid issue reference"):
        board_filter_for_closed_maps("", {"canonical/repo#1\n-malicious"})

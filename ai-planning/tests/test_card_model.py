"""Unit tests for the pure card model: typing, PR classification, stamps.

No network, no client: every rule the sweep applies to cards is pinned here as
a plain function over hand-built facts.
"""

from ai_planning.card_model import (
    CardType,
    compute_stamps,
    is_map_content,
    is_phase1_content,
    is_spec_pr,
    stack_family_pr_numbers,
    type_issue_card,
)

MAP = {"id": "I_map", "number": 1, "title": "Map: the effort", "labels": [{"name": "wayfinder:map"}]}
RESEARCH = {"id": "I_res", "number": 2, "title": "Research", "labels": [{"name": "wayfinder:research"}]}
SPEC = {"id": "I_spec", "number": 5, "title": "Spec: the slice", "labels": [{"name": "ready-for-agent"}]}
IMPL = {"id": "I_impl", "number": 7, "title": "Impl: the ticket", "labels": [{"name": "ready-for-agent"}]}


def test_map_label_recognised():
    assert is_map_content(MAP) is True
    assert is_map_content(SPEC) is False


def test_phase1_labels_recognised():
    assert is_phase1_content(RESEARCH) is True
    assert is_phase1_content(SPEC) is False


def test_a_map_child_without_wayfinder_labels_is_a_spec():
    assert type_issue_card(SPEC, MAP, None) == CardType(
        "spec", map_id="I_map", spec_id="I_spec"
    )


def test_a_map_child_with_a_wayfinder_label_is_phase1():
    assert type_issue_card(RESEARCH, MAP, None) == CardType("phase1", map_id="I_map")


def test_a_spec_child_is_an_implementation_ticket():
    parent_type = CardType("spec", map_id="I_map", spec_id="I_spec")
    assert type_issue_card(IMPL, SPEC, parent_type) == CardType(
        "impl", map_id="I_map", spec_id="I_spec"
    )


def test_a_root_issue_without_labels_is_standalone():
    assert type_issue_card(SPEC, None, None) == CardType("standalone")


def test_a_map_is_typed_map_even_with_children():
    assert type_issue_card(MAP, None, None).kind == "map"


# --- PR classification ---------------------------------------------------------


def test_a_head_base_branch_is_a_spec_pr():
    assert is_spec_pr("settings-stack/base") is True


def test_a_ticket_branch_is_not_a_spec_pr():
    assert is_spec_pr("settings-stack/7-ticket") is False


def test_main_head_is_not_a_spec_pr():
    assert is_spec_pr("main") is False
    assert is_spec_pr(None) is False


def test_the_bottom_stack_pr_and_its_fixes_are_one_family():
    prs = [
        {"number": 12, "baseRefName": "settings-stack/base", "headRefName": "settings-stack/7-a"},
        {"number": 13, "baseRefName": "settings-stack/7-a", "headRefName": "settings-stack/fix"},
        {"number": 14, "baseRefName": "main", "headRefName": "standalone"},
    ]
    assert stack_family_pr_numbers(prs) == {12, 13}


def test_a_deeper_stack_chain_is_still_one_family():
    prs = [
        {"number": 1, "baseRefName": "spec/base", "headRefName": "spec/1"},
        {"number": 2, "baseRefName": "spec/1", "headRefName": "spec/2"},
        {"number": 3, "baseRefName": "spec/2", "headRefName": "spec/3"},
    ]
    assert stack_family_pr_numbers(prs) == {1, 2, 3}


def test_a_chain_not_rooted_in_a_spec_branch_is_not_carded():
    prs = [
        {"number": 1, "baseRefName": "main", "headRefName": "feature"},
        {"number": 2, "baseRefName": "feature", "headRefName": "feature-2"},
    ]
    assert stack_family_pr_numbers(prs) == set()


# --- stamps ---------------------------------------------------------------------


def _names(maps=(), specs=()):
    """Option names by content id, as the job resolves them."""

    out: dict[str, dict[str, str]] = {}
    for content_id, map_name in maps:
        out.setdefault(content_id, {})["map"] = map_name
    for content_id, spec_name in specs:
        out.setdefault(content_id, {})["spec"] = spec_name
    return out


def test_a_map_stamps_itself():
    plans = compute_stamps(
        {"I_map": CardType("map", map_id="I_map")},
        issue_ids_with_open_pr=set(),
        pr_card_meta={},
        option_name_by_content_id=_names(maps=[("I_map", "Map: the effort #1")]),
    )
    assert plans == [
        __import__("ai_planning.card_model", fromlist=["StampPlan"]).StampPlan(
            content_id="I_map", stamps={"Map": "Map: the effort #1"}
        )
    ]


def test_a_spec_without_an_open_pr_stamps_map_and_spec():
    plans = compute_stamps(
        {"I_spec": CardType("spec", map_id="I_map", spec_id="I_spec")},
        issue_ids_with_open_pr=set(),
        pr_card_meta={},
        option_name_by_content_id=_names(
            maps=[("I_map", "Map: the effort #1")], specs=[("I_spec", "Spec: the slice #5")]
        ),
    )
    assert plans[0].stamps == {"Map": "Map: the effort #1", "Spec": "Spec: the slice #5"}


def test_a_spec_whose_pr_is_open_vanishes_from_both_surfaces():
    plans = compute_stamps(
        {"I_spec": CardType("spec", map_id="I_map", spec_id="I_spec")},
        issue_ids_with_open_pr={"I_spec"},
        pr_card_meta={
            "PR_spec": {"kind": "spec", "spec_content_id": "I_spec"},
        },
        option_name_by_content_id={
            "I_map": {"map": "Map: the effort #1"},
            "I_spec": {"spec": "Spec: the slice #5", "map": "Map: the effort #1"},
        },
    )
    by_content = {plan.content_id: plan.stamps for plan in plans}
    # The spec ticket is cleared off both surfaces...
    assert by_content["I_spec"] == {"Map": None, "Spec": None}
    # ...and its spec PR card replaces it there.
    assert by_content["PR_spec"] == {"Map": "Map: the effort #1", "Spec": "Spec: the slice #5"}


def test_an_impl_ticket_stamps_only_spec_and_clears_it_while_its_pr_is_open():
    typed = {"I_impl": CardType("impl", map_id="I_map", spec_id="I_spec")}
    open_plans = compute_stamps(
        typed,
        issue_ids_with_open_pr={"I_impl"},
        pr_card_meta={"PR_impl": {"kind": "stack", "spec_content_id": "I_spec"}},
        option_name_by_content_id=_names(specs=[("I_spec", "Spec: the slice #5")]),
    )
    by_content = {plan.content_id: plan.stamps for plan in open_plans}
    assert by_content["I_impl"] == {"Spec": None}
    assert by_content["PR_impl"] == {"Spec": "Spec: the slice #5"}

    closed_plans = compute_stamps(
        typed,
        issue_ids_with_open_pr=set(),
        pr_card_meta={},
        option_name_by_content_id=_names(specs=[("I_spec", "Spec: the slice #5")]),
    )
    assert closed_plans[0].stamps == {"Spec": "Spec: the slice #5"}


def test_a_stack_pr_without_a_resolvable_spec_is_not_stamped():
    plans = compute_stamps(
        {},
        issue_ids_with_open_pr=set(),
        pr_card_meta={"PR_x": {"kind": "stack", "spec_content_id": None}},
        option_name_by_content_id={},
    )
    assert plans == []


def test_phase1_stamps_its_map_only():
    plans = compute_stamps(
        {"I_res": CardType("phase1", map_id="I_map")},
        issue_ids_with_open_pr=set(),
        pr_card_meta={},
        option_name_by_content_id=_names(maps=[("I_map", "Map: the effort #1")]),
    )
    assert plans[0].stamps == {"Map": "Map: the effort #1"}


def test_no_option_names_yet_means_no_stamp_writes():
    plans = compute_stamps(
        {"I_spec": CardType("spec", map_id="I_map", spec_id="I_spec")},
        issue_ids_with_open_pr=set(),
        pr_card_meta={},
        option_name_by_content_id={},
    )
    assert plans == []

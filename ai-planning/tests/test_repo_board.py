"""Unit tests for the repo-board entry point: discovery and settings."""

import pytest

from ai_planning.repo_board import DEFAULT_SEED_LABELS, pick_project


def _node(number, title="AI planning"):
    return {"id": f"PVT_{number}", "number": number, "title": title}


def test_pick_project_finds_the_predictively_titled_linked_project():
    nodes = [_node(175, "AI planning"), _node(164, "Desktop AI planning")]

    assert pick_project(nodes, "AI planning") == ("PVT_175", 175)


def test_pick_project_matches_the_title_exactly():
    nodes = [_node(175, "AI planning - warty-whisperer")]

    assert pick_project(nodes, "AI planning") is None


def test_pick_project_without_a_linked_project_is_none():
    assert pick_project([], "AI planning") is None


def test_pick_project_refuses_an_ambiguous_predictive_title():
    nodes = [_node(1, "AI planning"), _node(2, "AI planning")]

    with pytest.raises(ValueError, match="several linked projects"):
        pick_project(nodes, "AI planning")


def test_default_seed_labels_are_the_agent_work_vocabulary():
    assert DEFAULT_SEED_LABELS == (
        "ready-for-agent",
        "ready-for-human",
        "wayfinder:map",
        "wayfinder:task",
        "wayfinder:research",
        "wayfinder:prototype",
        "wayfinder:grilling",
    )
"""Unit tests for the repo-board entry point: discovery and settings."""

import pytest

import ai_planning.repo_board as entry
from ai_planning.job import SyncResult
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


# --- the wiring of main(): discovery -> link scan -> sweep --------------------


class FakeClient:
    def execute(self, _query, _variables):
        return {
            "repository": {
                "projectsV2": {"nodes": [_node(175)]},
            }
        }


@pytest.fixture
def wired_env(monkeypatch):
    monkeypatch.setenv("AI_PLANNING_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", "canonical/warty-whisperer")
    monkeypatch.delenv("AI_PLANNING_PROJECT_NAME", raising=False)
    monkeypatch.delenv("AI_PLANNING_SEED_LABELS", raising=False)
    monkeypatch.setattr(entry.GraphQLClient, "with_token", staticmethod(lambda _: FakeClient()))


def test_main_scans_links_then_sweeps_the_discovered_board(wired_env, monkeypatch):
    calls = []

    def fake_scan(client, repos):
        calls.append(("scan", repos))
        return type(
            "R",
            (),
            {
                "authored": [],
                "unchanged": [],
                "ambiguous": [],
                "no_candidates": [],
                "prs": [{"id": "PR_1", "state": "OPEN", "number": 1}],
            },
        )()

    monkeypatch.setattr(entry, "author_missing_links", fake_scan)

    def fake_run_sync(client, project_id, **kwargs):
        calls.append(("sweep", project_id, kwargs))
        return SyncResult()

    monkeypatch.setattr(entry, "run_sync", fake_run_sync)

    assert entry.main() == 0
    assert calls == [
        ("scan", ["canonical/warty-whisperer"]),
        (
            "sweep",
            "PVT_175",
            dict(
                planning_repo="canonical/warty-whisperer",
                seed_labels=DEFAULT_SEED_LABELS,
                repo_prs=[{"id": "PR_1", "state": "OPEN", "number": 1}],
            ),
        ),
    ]


def test_main_survives_a_failing_link_scan_and_still_sweeps(wired_env, monkeypatch):
    monkeypatch.setattr(
        entry, "author_missing_links", lambda client, repos: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    swept = []
    monkeypatch.setattr(entry, "run_sync", lambda client, pid, **kw: swept.append(pid) or SyncResult())

    assert entry.main() == 0
    assert swept == ["PVT_175"]


def test_missing_token_or_repo_is_a_usage_error(monkeypatch):
    monkeypatch.delenv("AI_PLANNING_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "canonical/warty-whisperer")
    assert entry.main() == 2

    monkeypatch.setenv("AI_PLANNING_TOKEN", "tok")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert entry.main() == 2


def test_no_linked_project_is_a_usage_error_pointing_at_the_setup(wired_env, monkeypatch):
    class EmptyClient:
        def execute(self, _query, _variables):
            return {"repository": {"projectsV2": {"nodes": []}}}

    monkeypatch.setattr(entry.GraphQLClient, "with_token", staticmethod(lambda _: EmptyClient()))

    assert entry.main() == 2
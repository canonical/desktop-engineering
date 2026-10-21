import json

import pytest

import ai_planning.__main__ as entry
from ai_planning.job import SyncResult

BOARDS = json.dumps({"all": "PVT_all", "apps": "PVT_apps", "core": "PVT_core"})


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AI_PLANNING_TOKEN", "tok")
    monkeypatch.setenv("AI_PLANNING_REPO", "canonical/desktop-ai-planning")
    monkeypatch.setenv("AI_PLANNING_BOARDS", BOARDS)
    monkeypatch.delenv("AI_PLANNING_DISPATCHED_PR", raising=False)
    monkeypatch.delenv("AI_PLANNING_LINK_SCAN_REPOS", raising=False)
    monkeypatch.setattr(entry.GraphQLClient, "with_token", staticmethod(lambda _: object()))


def test_every_board_is_swept_with_its_own_seed_and_marker_labels(env, monkeypatch):
    calls = []

    def fake_run_sync(client, project_id, **kwargs):
        calls.append((project_id, kwargs))
        return SyncResult()

    monkeypatch.setattr(entry, "run_sync", fake_run_sync)

    assert entry.main() == 0
    assert calls == [
        ("PVT_all", dict(planning_repo="canonical/desktop-ai-planning",
                         seed_label=None, archived_label="wayfinder:archived:all")),
        ("PVT_apps", dict(planning_repo="canonical/desktop-ai-planning",
                          seed_label="squad:apps",
                          archived_label="wayfinder:archived:apps")),
        ("PVT_core", dict(planning_repo="canonical/desktop-ai-planning",
                          seed_label="squad:core",
                          archived_label="wayfinder:archived:core")),
    ]


def test_a_failing_board_does_not_starve_the_others_but_fails_the_run(env, monkeypatch):
    swept = []

    def fake_run_sync(client, project_id, **kwargs):
        if project_id == "PVT_apps":
            raise RuntimeError("boom")
        swept.append(project_id)
        return SyncResult()

    monkeypatch.setattr(entry, "run_sync", fake_run_sync)

    assert entry.main() == 1
    assert swept == ["PVT_all", "PVT_core"]


def test_missing_boards_is_a_usage_error(env, monkeypatch):
    monkeypatch.delenv("AI_PLANNING_BOARDS")

    assert entry.main() == 2

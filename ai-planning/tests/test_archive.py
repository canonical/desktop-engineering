import pytest

from ai_planning.archive import (
    ARCHIVE,
    UNARCHIVE,
    ArchiveError,
    TreeIssue,
    parse_map_ref,
    plan_archive,
    run_archive,
)

PROJECT = "PVT_1"


def issue(name, state="CLOSED", item="on", archived=False):
    return TreeIssue(
        issue_id=name,
        ref=f"o/r#{name}",
        state=state,
        item_id=f"item_{name}" if item == "on" else None,
        archived=archived,
    )


def test_parse_map_ref_accepts_number_hash_and_full_ref():
    assert parse_map_ref("53", "o/planning") == ("o", "planning", 53)
    assert parse_map_ref("#53", "o/planning") == ("o", "planning", 53)
    assert parse_map_ref("x/y#7", "o/planning") == ("x", "y", 7)
    with pytest.raises(ArchiveError):
        parse_map_ref("nope", "o/planning")


def test_archive_plan_changes_every_visible_card_open_or_closed():
    plan = plan_archive(
        [
            issue("a"),
            issue("open", state="OPEN"),
            issue("gone", item="off"),
            issue("done", archived=True),
        ],
        ARCHIVE,
    )

    assert [i.issue_id for i in plan.to_change] == ["a", "open"]
    assert [i.issue_id for i in plan.off_board] == ["gone"]
    assert [i.issue_id for i in plan.already_done] == ["done"]


def test_unarchive_plan_only_restores_archived_cards():
    plan = plan_archive([issue("a"), issue("b", archived=True)], UNARCHIVE)

    assert [i.issue_id for i in plan.to_change] == ["b"]
    assert [i.issue_id for i in plan.already_done] == ["a"]


class FakeClient:
    """Serves a canned sub-issue graph and records the mutations it receives."""

    def __init__(self, root, nodes, children):
        self.root = root
        self.nodes = nodes
        self.children = children
        self.mutations = []

    def execute(self, query, variables):
        if "issue(number" in query:
            return {"repository": {"issue": self.root}}
        if "mutation" in query:
            name = "unarchive" if "unarchiveProjectV2Item" in query else "archive"
            self.mutations.append((name + "ProjectV2Item", variables))
            return {}
        node = self.nodes[variables["issueId"]]
        return {
            "node": {
                **node,
                "subIssues": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{"id": c} for c in self.children.get(node["id"], [])],
                },
            }
        }


def node(name, state="CLOSED", archived=False, on_project=True):
    items = [{"id": f"item_{name}", "isArchived": archived, "project": {"id": PROJECT}}]
    if not on_project:
        items = [{"id": "other", "isArchived": False, "project": {"id": "PVT_other"}}]
    return {
        "id": name,
        "number": 1,
        "state": state,
        "repository": {"nameWithOwner": f"o/{name}"},
        "projectItems": {"nodes": items},
    }


def root(state="CLOSED", labels=("wayfinder:map",)):
    return {
        "id": "map",
        "number": 10,
        "state": state,
        "repository": {"nameWithOwner": "o/planning"},
        "labels": {"nodes": [{"name": n} for n in labels]},
    }


def graph():
    nodes = {
        "map": node("map"),
        "spec": node("spec"),
        "ticket": node("ticket"),
        "task": node("task"),
        "elsewhere": node("elsewhere", on_project=False),
    }
    children = {
        "map": ["spec", "task", "elsewhere"],
        "spec": ["ticket", "map"],  # a cycle must not loop forever
    }
    return nodes, children


def test_run_archive_walks_the_whole_tree_and_archives_each_closed_card():
    nodes, children = graph()
    client = FakeClient(root(), nodes, children)

    plan = run_archive(client, PROJECT, ("o", "planning", 10))

    assert sorted(i.issue_id for i in plan.to_change) == ["spec", "task", "ticket"]
    assert [i.issue_id for i in plan.off_board] == ["elsewhere"]
    assert sorted(v["itemId"] for _, v in client.mutations) == [
        "item_spec",
        "item_task",
        "item_ticket",
    ]
    assert all(v["projectId"] == PROJECT for _, v in client.mutations)


def test_run_archive_dry_run_changes_nothing():
    nodes, children = graph()
    client = FakeClient(root(), nodes, children)

    plan = run_archive(client, PROJECT, ("o", "planning", 10), dry_run=True)

    assert len(plan.to_change) == 3
    assert client.mutations == []


def test_run_archive_refuses_an_open_map():
    nodes, children = graph()
    client = FakeClient(root(state="OPEN"), nodes, children)

    with pytest.raises(ArchiveError, match="still open"):
        run_archive(client, PROJECT, ("o", "planning", 10))
    assert client.mutations == []


def test_run_archive_refuses_a_non_map_issue():
    nodes, children = graph()
    client = FakeClient(root(labels=()), nodes, children)

    with pytest.raises(ArchiveError, match="not a Map"):
        run_archive(client, PROJECT, ("o", "planning", 10))


def test_unarchive_works_on_an_open_map_and_restores_archived_cards():
    nodes, children = graph()
    nodes["ticket"] = node("ticket", archived=True)
    client = FakeClient(root(state="OPEN"), nodes, children)

    plan = run_archive(client, PROJECT, ("o", "planning", 10), mode=UNARCHIVE)

    assert [i.issue_id for i in plan.to_change] == ["ticket"]
    assert client.mutations[0][0] == "unarchiveProjectV2Item"

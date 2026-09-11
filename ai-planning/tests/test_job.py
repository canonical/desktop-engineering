"""Orchestration tests for the sync job, driven by a fake GraphQL client.

The fake records every mutation and serves canned query responses, so we assert
the job's external behaviour — which cards get which Status, which are skipped —
with no network and no dependence on GitHub's live schema.
"""

import pytest

from ai_planning.client import GraphQLClient, GraphQLError
from ai_planning.sync_status import Status
from ai_planning.job import (
    fetch_status_field,
    iter_project_items,
    run_sync,
    seed_board,
)
from ai_planning.queries import (
    ADD_ITEM_MUTATION,
    CLOSE_ISSUE_MUTATION,
    ISSUE_TIMELINE_QUERY,
    PROJECT_ITEM_QUERY,
    PROJECT_ITEMS_QUERY,
    REPO_ISSUES_QUERY,
    STATUS_FIELD_QUERY,
    UPDATE_STATUS_MUTATION,
)

from tests.fixtures import issue_item, _xref_event

PROJECT_ID = "PVT_project"
DEST_REPO = "acme/code-repo"

STATUS_FIELD_RESPONSE = {
    "node": {
        "field": {
            "id": "PVTSSF_status",
            "options": [
                {"id": "opt_ready", "name": "Ready"},
                {"id": "opt_blocked", "name": "Blocked"},
                {"id": "opt_in_progress", "name": "In progress"},
                {"id": "opt_in_review", "name": "In review"},
                {"id": "opt_done", "name": "Done"},
            ],
        }
    }
}


def _issue(item_id, *, state="OPEN", assignees=0, labels=(), blocked_by=0, prs=(),
           status_option_id=None):
    return issue_item(
        item_id,
        state=state,
        assignees=assignees,
        labels=labels,
        blocked_by=blocked_by,
        prs=prs,
        status_option_id=status_option_id,
    )


class FakeClient:
    """Serves the Status field, one or more item pages, and records mutations."""

    def __init__(self, item_pages):
        self._item_pages = list(item_pages)
        self._page_index = 0
        self.mutations = []
        self.closed = []

    def execute(self, query, variables):
        if query == STATUS_FIELD_QUERY:
            return STATUS_FIELD_RESPONSE
        if query == PROJECT_ITEMS_QUERY:
            nodes, has_next = self._item_pages[self._page_index]
            end_cursor = f"cursor{self._page_index}"
            self._page_index += 1
            return {
                "node": {
                    "items": {
                        "pageInfo": {
                            "hasNextPage": has_next,
                            "endCursor": end_cursor,
                        },
                        "nodes": nodes,
                    }
                }
            }
        if query == UPDATE_STATUS_MUTATION:
            self.mutations.append(variables)
            return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}
        if query == CLOSE_ISSUE_MUTATION:
            self.closed.append(variables["issueId"])
            return {"closeIssue": {"issue": {"id": variables["issueId"],
                                             "state": "CLOSED"}}}
        raise AssertionError(f"unexpected query: {query!r}")


def _single_page(nodes):
    return [(nodes, False)]


def test_card_already_in_the_right_column_is_not_rewritten():
    """Skip-if-unchanged guard: a card whose current Status option id already
    matches the synced Status is recorded as unchanged and never mutated, so a
    full-board resync doesn't churn cards that are already correct."""
    items = [
        # Already In progress -> no write.
        _issue("i_steady", assignees=1, status_option_id="opt_in_progress"),
        # In the wrong column -> written.
        _issue("i_moved", assignees=1, status_option_id="opt_ready"),
        # No Status set yet -> written.
        _issue("i_fresh", assignees=1),
    ]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert result.unchanged == [("i_steady", Status.IN_PROGRESS)]
    assert result.written == [
        ("i_moved", Status.IN_PROGRESS),
        ("i_fresh", Status.IN_PROGRESS),
    ]
    # Only the two out-of-sync cards produce a mutation.
    assert [m["itemId"] for m in client.mutations] == ["i_moved", "i_fresh"]


def test_fully_settled_board_writes_nothing():
    """When every card already sits in its synced column, a resync is a pure
    read: no mutation is sent at all."""
    items = [
        _issue("i_ready", status_option_id="opt_ready"),
        _issue("i_done", state="CLOSED", status_option_id="opt_done"),
    ]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert client.mutations == []
    assert [item_id for item_id, _ in result.unchanged] == ["i_ready", "i_done"]
    assert result.written == []


def test_syncs_and_writes_each_status():
    items = [
        _issue("i_ready"),
        _issue("i_blocked", blocked_by=1),
        _issue("i_review", prs=[{"state": "OPEN", "isDraft": False}]),
        _issue("i_progress", assignees=1),
        _issue("i_done", state="CLOSED"),
    ]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert result.written == [
        ("i_ready", Status.READY),
        ("i_blocked", Status.BLOCKED),
        ("i_review", Status.IN_REVIEW),
        ("i_progress", Status.IN_PROGRESS),
        ("i_done", Status.DONE),
    ]
    # Each write carries the matching option id for the synced Status.
    written_option_ids = [m["optionId"] for m in client.mutations]
    assert written_option_ids == [
        "opt_ready",
        "opt_blocked",
        "opt_in_review",
        "opt_in_progress",
        "opt_done",
    ]
    # Every mutation targets the right project, item and field.
    assert all(m["projectId"] == PROJECT_ID for m in client.mutations)
    assert all(m["fieldId"] == "PVTSSF_status" for m in client.mutations)


def test_blocked_beats_review_through_the_full_pipeline():
    item = _issue(
        "i_x", blocked_by=2, prs=[{"state": "OPEN", "isDraft": False}], assignees=1
    )
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.written == [("i_x", Status.BLOCKED)]


def test_maps_are_skipped_never_written():
    items = [
        _issue("i_map", labels=("wayfinder:map",)),
        _issue("i_task", assignees=1),
    ]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert result.skipped_maps == ["i_map"]
    assert [item_id for item_id, _ in result.written] == ["i_task"]
    assert [m["itemId"] for m in client.mutations] == ["i_task"]


def test_contentless_items_are_skipped():
    items = [{"id": "i_draft", "content": None}, _issue("i_task", assignees=1)]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert result.skipped_contentless == ["i_draft"]
    assert [item_id for item_id, _ in result.written] == ["i_task"]


def test_pagination_walks_every_page():
    page_one = ([_issue("i_1")], True)
    page_two = ([_issue("i_2", state="CLOSED")], False)
    client = FakeClient([page_one, page_two])

    items = list(iter_project_items(client, PROJECT_ID, page_size=1))

    assert [item["id"] for item in items] == ["i_1", "i_2"]


def test_fetch_status_field_builds_option_lookup():
    client = FakeClient(_single_page([]))

    status_field = fetch_status_field(client, PROJECT_ID)

    assert status_field.field_id == "PVTSSF_status"
    assert status_field.option_id_for(Status.IN_REVIEW) == "opt_in_review"


def test_graphql_errors_raise():
    def transport(_payload):
        return {"errors": [{"message": "Bad credentials"}]}

    client = GraphQLClient(transport)

    with pytest.raises(GraphQLError):
        client.execute("query {}", {})


def test_parent_syncs_in_progress_from_in_progress_child():
    """Two-pass roll-up: the child (a leaf) syncs first; its In progress
    Status is folded into the parent's facts before the parent syncs."""
    child = _issue("i_child", assignees=1)  # leaf -> In progress
    parent = _issue("i_parent")  # otherwise Ready
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.written) == {
        "i_child": Status.IN_PROGRESS,
        "i_parent": Status.IN_PROGRESS,
    }
    # Written in the Project's original item order: child, then parent.
    assert [item_id for item_id, _ in result.written] == ["i_child", "i_parent"]


def test_parent_stays_ready_when_no_child_is_in_progress():
    child = _issue("i_child")  # leaf, unassigned -> Ready
    parent = _issue("i_parent")
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.written) == {
        "i_child": Status.READY,
        "i_parent": Status.READY,
    }


def test_parents_own_blocker_beats_child_roll_up():
    child = _issue("i_child", assignees=1)  # leaf -> In progress
    parent = _issue("i_parent", blocked_by=1)
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.written)["i_parent"] == Status.BLOCKED


def test_parents_own_review_pr_beats_child_roll_up():
    child = _issue("i_child", assignees=1)  # leaf -> In progress
    parent = _issue("i_parent", prs=[{"state": "OPEN", "isDraft": False}])
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.written)["i_parent"] == Status.IN_REVIEW


def test_map_parent_is_still_skipped_regardless_of_children():
    child = _issue("i_child", assignees=1)  # leaf -> In progress
    parent = _issue("i_parent", labels=("wayfinder:map",))
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert result.skipped_maps == ["i_parent"]
    assert dict(result.written) == {"i_child": Status.IN_PROGRESS}


def test_child_not_on_board_does_not_make_an_item_a_parent():
    """A sub-issue child that isn't itself a Project item can't be synced,
    so it can't be rolled up either: the item syncs as a plain leaf."""
    item = _issue("i_solo")
    item["content"]["subIssues"] = {"nodes": [{"id": "I_off_board"}]}
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.written) == {"i_solo": Status.READY}


PLANNING_REPO = "acme/acme-ai-planning"


class SeedingFakeClient:
    """Models a *mutable* board over a fixed 'world' of issues.

    `world` maps content_id -> its facts (state, labels, blocked_by, prs,
    assignees) and `child_content_ids`. `repo_open` is what the planning repo
    reports as OPEN issues (REPO_ISSUES_QUERY). `on_board` is the content
    currently carded; ADD_ITEM grows it, and PROJECT_ITEMS reflects it — so the
    transitive sub-issue closure a real board would expose is modelled here too.
    """

    def __init__(self, world, repo_open, on_board=(), *, list_lag=False):
        self.world = world
        self.repo_open = list(repo_open)
        self.on_board = list(dict.fromkeys(on_board))
        self.added = []
        self.status_writes = []
        # When True, a content added via ADD_ITEM does NOT appear in the
        # PROJECT_ITEMS list read (models Projects v2 eventual consistency),
        # but is still readable directly by its item id via PROJECT_ITEM_QUERY.
        self.list_lag = list_lag
        self._lagged = []

    def _item(self, content_id):
        spec = self.world[content_id]
        return issue_item(
            item_id=f"PVTI_{content_id}",
            state=spec.get("state", "OPEN"),
            assignees=spec.get("assignees", 0),
            labels=spec.get("labels", ()),
            blocked_by=spec.get("blocked_by", 0),
            prs=spec.get("prs", ()),
            content_id=content_id,
            child_content_ids=spec.get("child_content_ids", ()),
            status_option_id=spec.get("status_option_id"),
        )

    def execute(self, query, variables):
        if query == STATUS_FIELD_QUERY:
            return STATUS_FIELD_RESPONSE
        if query == REPO_ISSUES_QUERY:
            return {
                "repository": {
                    "issues": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"id": cid} for cid in self.repo_open],
                    }
                }
            }
        if query == PROJECT_ITEMS_QUERY:
            visible = [cid for cid in self.on_board if cid not in self._lagged]
            return {
                "node": {
                    "items": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [self._item(cid) for cid in visible],
                    }
                }
            }
        if query == PROJECT_ITEM_QUERY:
            content_id = variables["itemId"].removeprefix("PVTI_")
            if content_id not in self.on_board:
                return {"node": None}
            return {"node": self._item(content_id)}
        if query == ADD_ITEM_MUTATION:
            content_id = variables["contentId"]
            if content_id not in self.on_board:
                self.on_board.append(content_id)
                self.added.append(content_id)
                if self.list_lag:
                    self._lagged.append(content_id)
            return {"addProjectV2ItemById": {"item": {"id": f"PVTI_{content_id}"}}}
        if query == UPDATE_STATUS_MUTATION:
            self.status_writes.append(variables)
            return {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}
        raise AssertionError(f"unexpected query: {query!r}")


def test_seed_adds_a_planning_repo_issue_not_yet_on_board():
    client = SeedingFakeClient(world={"C_task": {}}, repo_open=["C_task"])

    added = seed_board(client, PROJECT_ID, PLANNING_REPO)

    assert added == {"C_task": "PVTI_C_task"}
    assert client.added == ["C_task"]


def test_seed_is_idempotent_when_the_issue_is_already_carded():
    client = SeedingFakeClient(
        world={"C_task": {}}, repo_open=["C_task"], on_board=["C_task"]
    )

    added = seed_board(client, PROJECT_ID, PLANNING_REPO)

    assert added == {}
    assert client.added == []  # diffed against the board, no add mutation


def test_seed_transitively_adds_a_cross_repo_spec_via_the_maps_subissues():
    """The spec lives in the code repo, so it is NOT in the planning repo's
    issue list — it is reached only as a sub-issue child of the map, which is
    itself only visible once seeded. The closure loop must pull it in."""
    world = {
        "C_map": {"labels": ("wayfinder:map",), "child_content_ids": ("C_spec",)},
        "C_spec": {"child_content_ids": ("C_ticket",)},
        "C_ticket": {},
    }
    # Only the planning-repo issues (map, ticket) are reported; the spec is not.
    client = SeedingFakeClient(world=world, repo_open=["C_map", "C_ticket"])

    added = seed_board(client, PROJECT_ID, PLANNING_REPO)

    assert "C_spec" in added  # reached transitively, not from the repo list
    assert set(client.on_board) == {"C_map", "C_spec", "C_ticket"}


def test_run_sync_seeds_then_syncs_the_newly_carded_issue():
    """End to end: an open planning-repo task that starts off-board is carded by
    pass 0 and then given its Status by the sweep in the same run."""
    client = SeedingFakeClient(
        world={"C_task": {"assignees": 1}}, repo_open=["C_task"]
    )

    result = run_sync(client, PROJECT_ID, planning_repo=PLANNING_REPO)

    assert result.seeded == ["C_task"]
    assert dict(result.written) == {"PVTI_C_task": Status.IN_PROGRESS}


def test_run_sync_syncs_a_seeded_card_missing_from_the_lagging_list_read():
    """Regression: Projects v2 list reads are eventually consistent, so a card
    added in pass 0 can be absent from the immediate re-read. It must still be
    synced this run (read back by its item id), not left with no Status."""
    client = SeedingFakeClient(
        world={"C_task": {"assignees": 1}},
        repo_open=["C_task"],
        list_lag=True,  # ADD_ITEM won't show up in the PROJECT_ITEMS read
    )

    result = run_sync(client, PROJECT_ID, planning_repo=PLANNING_REPO)

    assert result.seeded == ["C_task"]
    # Synced despite never appearing in the board list read.
    assert dict(result.written) == {"PVTI_C_task": Status.IN_PROGRESS}
    assert [w["itemId"] for w in client.status_writes] == ["PVTI_C_task"]


def test_run_sync_without_planning_repo_does_not_seed():
    """Backward-compatible: omit the repo and pass 0 is skipped entirely — no
    REPO_ISSUES_QUERY, no add mutation."""
    items = [_issue("i_task", assignees=1)]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert result.seeded == []
    assert [item_id for item_id, _ in result.written] == ["i_task"]


# --- the merged-PR timeline fallback (ticket 06) -----------------------------


def _issue_with_timeline(item_id, *events, state="OPEN", **kwargs):
    return issue_item(item_id, state=state, timeline=events, **kwargs)


def test_merged_cross_repo_pr_closes_issue_and_sets_done():
    """A still-OPEN ticket whose spec-branch PR merged is detected via the
    timeline, its issue is closed (so dependents unblock), and its card -> Done."""
    item = _issue_with_timeline(
        "i_ticket", _xref_event(merged=True, state="MERGED", repo=DEST_REPO)
    )
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID, destination_repos={DEST_REPO})

    assert result.written == [("i_ticket", Status.DONE)]
    # The underlying issue node id (content id) was closed exactly once.
    assert client.closed == ["I_i_ticket"]
    assert result.closed_issues == ["I_i_ticket"]


def test_open_pr_still_maps_to_in_review_and_does_not_close():
    """Unchanged behaviour: an open non-draft linked PR is In review, and the
    timeline fallback closes nothing."""
    item = _issue_with_timeline(
        "i_review",
        _xref_event(merged=False, state="OPEN", repo=DEST_REPO),
        prs=[{"state": "OPEN", "isDraft": False}],
    )
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID, destination_repos={DEST_REPO})

    assert result.written == [("i_review", Status.IN_REVIEW)]
    assert client.closed == []


def test_unrelated_repo_merged_mention_does_not_complete_the_ticket():
    """Guard: a merged PR in a repo outside the allow-list must not close or
    Done the ticket — it stays on its own facts (here Ready)."""
    item = _issue_with_timeline(
        "i_ticket", _xref_event(merged=True, state="MERGED", repo="acme/unrelated")
    )
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID, destination_repos={DEST_REPO})

    assert result.written == [("i_ticket", Status.READY)]
    assert client.closed == []
    assert result.closed_issues == []


def test_already_closed_issue_with_merged_pr_is_not_closed_again():
    """A ticket already CLOSED is Done via `closed`; the fallback does not
    re-issue a close for it."""
    item = _issue_with_timeline(
        "i_done",
        _xref_event(merged=True, state="MERGED", repo=DEST_REPO),
        state="CLOSED",
    )
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID, destination_repos={DEST_REPO})

    assert result.written == [("i_done", Status.DONE)]
    assert client.closed == []


def test_fallback_inert_without_destination_repos():
    """No allow-list -> a merged cross-repo mention is ignored: the card stays on
    its own facts and nothing is closed."""
    item = _issue_with_timeline(
        "i_ticket", _xref_event(merged=True, state="MERGED", repo=DEST_REPO)
    )
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.written == [("i_ticket", Status.READY)]
    assert client.closed == []


class TimelinePagingFakeClient(FakeClient):
    """A FakeClient that also serves a paged CROSS_REFERENCED_EVENT tail.

    `tail_pages` maps an issue node id -> a list of (nodes, has_next) pages the
    ISSUE_TIMELINE_QUERY returns in order, modelling an issue whose timeline
    exceeds the single embedded page.
    """

    def __init__(self, item_pages, tail_pages):
        super().__init__(item_pages)
        self._tail_pages = {k: list(v) for k, v in tail_pages.items()}
        self._tail_index = {k: 0 for k in tail_pages}

    def execute(self, query, variables):
        if query == ISSUE_TIMELINE_QUERY:
            issue_id = variables["issueId"]
            idx = self._tail_index[issue_id]
            nodes, has_next = self._tail_pages[issue_id][idx]
            self._tail_index[issue_id] = idx + 1
            return {
                "node": {
                    "timelineItems": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": "t_cur"},
                        "nodes": nodes,
                    }
                }
            }
        return super().execute(query, variables)


def test_merged_pr_found_only_on_a_paged_timeline_tail():
    """The qualifying event is on the second timeline page, past the embedded
    first page: the job must page the tail before scoring, then close + Done."""
    item = _issue_with_timeline(
        "i_ticket",
        _xref_event(merged=False, state="OPEN", repo=DEST_REPO),
        timeline_has_next=True,
        timeline_cursor="head_cur",
    )
    tail = {"I_i_ticket": [([_xref_event(merged=True, state="MERGED",
                                         repo=DEST_REPO)], False)]}
    client = TimelinePagingFakeClient(_single_page([item]), tail)

    result = run_sync(client, PROJECT_ID, destination_repos={DEST_REPO})

    assert result.written == [("i_ticket", Status.DONE)]
    assert client.closed == ["I_i_ticket"]

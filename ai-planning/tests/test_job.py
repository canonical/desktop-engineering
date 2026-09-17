"""Orchestration tests for the sync job, driven by a fake GraphQL client.

The fake records every mutation and serves canned query responses, so we assert
the job's external behaviour — which cards get which Status, which are skipped —
with no network and no dependence on GitHub's live schema.
"""

import pytest

from ai_planning.client import GraphQLClient, GraphQLError
from ai_planning.sync_status import Facts, Status, make_facts
from ai_planning.job import (
    MapCascadeAction,
    compute_map_cascade,
    fetch_status_field,
    iter_project_items,
    run_sync,
    seed_board,
)
from ai_planning.queries import (
    ADD_ITEM_MUTATION,
    CLOSE_ISSUE_MUTATION,
    ISSUE_LINKED_PRS_QUERY,
    PROJECT_ITEM_QUERY,
    PROJECT_ITEMS_QUERY,
    REOPEN_ISSUE_MUTATION,
    REPO_ISSUES_QUERY,
    STATUS_FIELD_QUERY,
    UPDATE_STATUS_MUTATION,
)

from tests.fixtures import issue_item, linked_pr

PROJECT_ID = "PVT_project"

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
        self.reopened = []

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
        if query == REOPEN_ISSUE_MUTATION:
            self.reopened.append(variables["issueId"])
            return {"reopenIssue": {"issue": {"id": variables["issueId"],
                                              "state": "OPEN"}}}
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
    read: no mutation is sent at all. A closed card whose column already
    reads Done is recorded as `unchanged`, exactly like an already-correct
    open card — closed cards are ordinary write-candidates, just cheap ones
    when already settled."""
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
    """A closed card gets its Status computed (Done here) and, being out of
    sync (no Status set yet), written back just like an open card."""
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
    # Every mutation targets the right project, item and field, including
    # the closed card.
    assert all(m["projectId"] == PROJECT_ID for m in client.mutations)
    assert all(m["fieldId"] == "PVTSSF_status" for m in client.mutations)
    assert "i_done" in [m["itemId"] for m in client.mutations]


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


def test_partial_success_returns_data_despite_field_errors():
    # GitHub answers `issue(number:N)` on a PR/absent number with the nullable
    # field nulled *and* a NOT_FOUND error. That is not fatal: the data is
    # returned so the caller can null-check the field.
    def transport(_payload):
        return {
            "data": {"repository": {"issue": None}},
            "errors": [
                {
                    "type": "NOT_FOUND",
                    "path": ["repository", "issue"],
                    "message": "Could not resolve to an Issue with the number of 15.",
                }
            ],
        }

    client = GraphQLClient(transport)

    assert client.execute("query {}", {}) == {"repository": {"issue": None}}


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


def test_in_review_child_lifts_parent_to_in_progress():
    """A child in In review (its own open non-draft PR) counts as started, so a
    parent with no facts of its own is lifted to In progress. The parent's own
    In review is reserved for the parent's *own* PR, so a child's In review only
    rolls up to In progress."""
    child = _issue("i_child", prs=[{"state": "OPEN", "isDraft": False}])  # leaf -> In review
    parent = _issue("i_parent")  # otherwise Ready
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.written) == {
        "i_child": Status.IN_REVIEW,
        "i_parent": Status.IN_PROGRESS,
    }


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


def test_stale_closed_card_is_healed_to_done():
    """Regression (UDENG: issue closed while its card stayed 'In progress'
    because the Project's native 'Item closed' workflow was disabled): a
    closed card is a write-candidate exactly like an open one, so a stale
    column is corrected to Done by the sweep itself, without depending on any
    native Project automation being enabled."""
    item = _issue("i_stale_closed", state="CLOSED", status_option_id="opt_ready")
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert [m["itemId"] for m in client.mutations] == ["i_stale_closed"]
    assert result.written == [("i_stale_closed", Status.DONE)]
    assert result.unchanged == []


def test_closed_child_is_read_and_written_and_feeds_roll_up():
    """A closed child gets its own Status computed and written (Done, being
    out of sync) and is also available to the parent roll-up. A Done child
    counts as 'started', so it lifts the parent out of Ready into In
    progress."""
    child = _issue("i_child", state="CLOSED")
    parent = _issue("i_parent")
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    # The closed child's Done status counts as started, so the parent
    # (unassigned, no PR of its own) is lifted to In progress.
    assert dict(result.written) == {
        "i_child": Status.DONE,
        "i_parent": Status.IN_PROGRESS,
    }


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


# --- the self-close-on-merge mechanism ---------------------------------------


def _issue_with_prs(item_id, *prs, state="OPEN", **kwargs):
    return issue_item(item_id, state=state, prs=prs, **kwargs)


def test_merged_linked_pr_closes_issue_and_sets_done():
    """A still-OPEN ticket whose deliberately-linked PR merged is closed (so
    dependents unblock) and its card resolves to Done."""
    item = _issue_with_prs("i_ticket", linked_pr(state="MERGED", merged=True))
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.written == [("i_ticket", Status.DONE)]
    # The underlying issue node id (content id) was closed exactly once.
    assert client.closed == ["I_i_ticket"]
    assert result.closed_issues == ["I_i_ticket"]


def test_open_pr_still_maps_to_in_review_and_does_not_close():
    """Unchanged behaviour: an open non-draft linked PR is In review, and
    nothing is closed while the PR is still open."""
    item = _issue_with_prs("i_review", linked_pr(state="OPEN", is_draft=False))
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.written == [("i_review", Status.IN_REVIEW)]
    assert client.closed == []


def test_open_draft_pr_maps_to_in_progress():
    item = _issue_with_prs("i_draft", linked_pr(state="OPEN", is_draft=True))
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.written == [("i_draft", Status.IN_PROGRESS)]
    assert client.closed == []


def test_already_closed_issue_with_merged_pr_is_not_closed_again():
    """A ticket already CLOSED is Done via `closed`; the mechanism does not
    re-issue a close for it. Being closed doesn't exempt it from writing: it
    is out of sync (no Status set yet) so it is written to Done like any
    other card."""
    item = _issue_with_prs(
        "i_done", linked_pr(state="MERGED", merged=True), state="CLOSED"
    )
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.written == [("i_done", Status.DONE)]
    assert client.closed == []


class LinkedPrPagingFakeClient(FakeClient):
    """A FakeClient that also serves a paged linked-PR tail.

    `tail_pages` maps an issue node id -> a list of (nodes, has_next) pages the
    ISSUE_LINKED_PRS_QUERY returns in order, modelling an issue whose linked-PR
    connection exceeds the single embedded page.
    """

    def __init__(self, item_pages, tail_pages):
        super().__init__(item_pages)
        self._tail_pages = {k: list(v) for k, v in tail_pages.items()}
        self._tail_index = {k: 0 for k in tail_pages}

    def execute(self, query, variables):
        if query == ISSUE_LINKED_PRS_QUERY:
            issue_id = variables["issueId"]
            idx = self._tail_index[issue_id]
            nodes, has_next = self._tail_pages[issue_id][idx]
            self._tail_index[issue_id] = idx + 1
            return {
                "node": {
                    "closedByPullRequestsReferences": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": "t_cur"},
                        "nodes": nodes,
                    }
                }
            }
        return super().execute(query, variables)


def test_merged_pr_found_only_on_a_paged_linked_pr_tail():
    """The qualifying PR is on the second page, past the embedded first page:
    the job must page the tail before scoring, then close + Done."""
    item = _issue_with_prs(
        "i_ticket",
        linked_pr(state="OPEN"),
        prs_has_next=True,
        prs_cursor="head_cur",
    )
    tail = {"I_i_ticket": [([linked_pr(state="MERGED", merged=True)], False)]}
    client = LinkedPrPagingFakeClient(_single_page([item]), tail)

    result = run_sync(client, PROJECT_ID)

    assert result.written == [("i_ticket", Status.DONE)]
    assert client.closed == ["I_i_ticket"]


# --- the map auto-close cascade ----------------------------------------------


def _map(item_id, *, state="OPEN", child_content_ids=()):
    item = _issue(item_id, state=state, labels=("wayfinder:map",))
    item["content"]["subIssues"] = {
        "nodes": [{"id": cid} for cid in child_content_ids]
    }
    return item


def test_map_whose_entire_subtree_is_closed_auto_closes():
    """AC-6: a map with a fully-closed subtree auto-closes."""
    child_a = _issue("i_child_a", state="CLOSED")
    child_b = _issue("i_child_b", state="CLOSED")
    map_item = _map("i_map", child_content_ids=("I_i_child_a", "I_i_child_b"))
    client = FakeClient(_single_page([child_a, child_b, map_item]))

    result = run_sync(client, PROJECT_ID)

    assert client.closed == ["I_i_map"]
    assert result.map_closed == ["I_i_map"]
    assert client.reopened == []


def test_map_with_an_open_descendant_does_not_auto_close():
    child = _issue("i_child")  # OPEN
    map_item = _map("i_map", child_content_ids=("I_i_child",))
    client = FakeClient(_single_page([child, map_item]))

    result = run_sync(client, PROJECT_ID)

    assert client.closed == []
    assert result.map_closed == []


def test_childless_map_never_auto_closes():
    """Childless-map guard: zero descendants means never auto-close, even
    though vacuously "zero open descendants" would otherwise be true."""
    map_item = _map("i_map")
    client = FakeClient(_single_page([map_item]))

    result = run_sync(client, PROJECT_ID)

    assert client.closed == []
    assert result.map_closed == []


def test_closed_map_auto_reopens_when_a_descendant_reopens():
    child = _issue("i_child")  # OPEN
    map_item = _map("i_map", state="CLOSED", child_content_ids=("I_i_child",))
    client = FakeClient(_single_page([child, map_item]))

    result = run_sync(client, PROJECT_ID)

    assert client.reopened == ["I_i_map"]
    assert result.map_reopened == ["I_i_map"]
    assert client.closed == []


def test_map_auto_close_is_reason_agnostic():
    """A subtree closed out-of-scope (NOT_PLANNED) closes the map exactly like
    one closed COMPLETED — `Facts.closed` carries no reason, by design."""
    child = _issue("i_child", state="CLOSED")
    map_item = _map("i_map", child_content_ids=("I_i_child",))
    client = FakeClient(_single_page([child, map_item]))

    result = run_sync(client, PROJECT_ID)

    assert result.map_closed == ["I_i_map"]


def test_off_board_descendant_blocks_the_close():
    """A sub-issue child that isn't itself a Project item has no known closed
    fact, so it is treated conservatively as open — it blocks the close even
    when every *resolved* sibling descendant is closed."""
    closed_child = _issue("i_child", state="CLOSED")
    map_item = _map(
        "i_map", child_content_ids=("I_i_child", "I_off_board")
    )
    client = FakeClient(_single_page([closed_child, map_item]))

    result = run_sync(client, PROJECT_ID)

    assert client.closed == []
    assert result.map_closed == []


def test_childless_because_only_child_is_off_board_never_auto_closes():
    map_item = _map("i_map", child_content_ids=("I_off_board",))
    client = FakeClient(_single_page([map_item]))

    result = run_sync(client, PROJECT_ID)

    assert client.closed == []
    assert result.map_closed == []


def test_merged_linked_pr_descendant_cascade_closes_the_map_in_the_same_sweep():
    """A ticket whose deliberately-linked PR merged resolves to Done even
    before the sweep's own self-close fires this run; the map cascade treats
    it as settled immediately, so the map closes in this same sweep too."""
    ticket = _issue_with_prs("i_ticket", linked_pr(state="MERGED", merged=True))
    map_item = _map("i_map", child_content_ids=("I_i_ticket",))
    client = FakeClient(_single_page([ticket, map_item]))

    result = run_sync(client, PROJECT_ID)

    assert client.closed == ["I_i_ticket", "I_i_map"]
    assert result.map_closed == ["I_i_map"]


def test_nested_map_cascade_settles_deepest_first_in_one_sweep():
    """A closed leaf ticket closes its immediate (inner) map, and that closed
    inner map is itself enough to close the outer map — both settle inside
    this one sweep, with no need for a second run."""
    ticket = _issue("i_ticket", state="CLOSED")
    inner_map = _map("i_inner_map", child_content_ids=("I_i_ticket",))
    outer_map = _map("i_outer_map", child_content_ids=("I_i_inner_map",))
    client = FakeClient(_single_page([ticket, inner_map, outer_map]))

    result = run_sync(client, PROJECT_ID)

    assert set(client.closed) == {"I_i_inner_map", "I_i_outer_map"}
    assert set(result.map_closed) == {"I_i_inner_map", "I_i_outer_map"}


def test_nested_map_stays_open_while_the_inner_map_still_has_an_open_child():
    open_ticket = _issue("i_ticket")  # OPEN
    inner_map = _map("i_inner_map", child_content_ids=("I_i_ticket",))
    outer_map = _map("i_outer_map", child_content_ids=("I_i_inner_map",))
    client = FakeClient(_single_page([open_ticket, inner_map, outer_map]))

    result = run_sync(client, PROJECT_ID)

    assert client.closed == []
    assert result.map_closed == []


def test_compute_map_cascade_is_a_pure_function_over_facts():
    """Direct unit test of the reducer: no client, no run_sync — just the
    subtree-closure decision from in-memory facts."""
    facts_by_item_id = {
        "i_map": make_facts(
            closed=False, open_blocker_count=0, has_open_non_draft_pr=False,
            assigned=False, is_map=True,
        ),
        "i_child": make_facts(
            closed=True, open_blocker_count=0, has_open_non_draft_pr=False,
            assigned=False,
        ),
    }
    item_id_by_content_id = {"C_map": "i_map", "C_child": "i_child"}
    child_content_ids_by_item_id = {"i_map": ["C_child"], "i_child": []}

    actions = compute_map_cascade(
        facts_by_item_id, item_id_by_content_id, child_content_ids_by_item_id
    )

    assert actions == [MapCascadeAction("i_map", "C_map", close=True)]

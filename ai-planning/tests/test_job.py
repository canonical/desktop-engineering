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
    ADD_LABEL_MUTATION,
    ARCHIVE_ITEM_MUTATION,
    CLEAR_FIELD_VALUE_MUTATION,
    CLOSE_ISSUE_MUTATION,
    FIELD_BY_NAME_QUERY,
    ISSUE_LINKED_PRS_QUERY,
    ISSUE_SUB_ISSUES_QUERY,
    ISSUE_SUBTREE_QUERY,
    LABEL_ID_QUERY,
    PROJECT_ITEM_QUERY,
    PROJECT_ITEMS_QUERY,
    PROJECT_VIEWS_QUERY,
    REOPEN_ISSUE_MUTATION,
    REPO_ISSUES_QUERY,
    REMOVE_LABEL_MUTATION,
    STATUS_FIELD_QUERY,
    UNARCHIVE_ITEM_MUTATION,
    UPDATE_STATUS_MUTATION,
)

from tests.fixtures import ShapeFakeMixin, issue_item, linked_pr, pr_item

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
                {"id": "opt_approved", "name": "Approved"},
                {"id": "opt_done", "name": "Done"},
            ],
        }
    }
}


def _issue(item_id, *, state="OPEN", assignees=0, labels=(), blocked_by=0, prs=(),
           status_option_id=None, child_content_ids=(), parent=None):
    return issue_item(
        item_id,
        state=state,
        assignees=assignees,
        labels=labels,
        blocked_by=blocked_by,
        prs=prs,
        child_content_ids=child_content_ids,
        parent=parent,
        status_option_id=status_option_id,
    )


class FakeClient(ShapeFakeMixin):
    """Serves the board shape, one or more item pages, and records mutations."""

    def __init__(self, item_pages, *, label_missing=False):
        self._item_pages = list(item_pages)
        self.label_missing = label_missing
        self.labels_added = []
        self.labels_removed = []
        self._page_index = 0
        self.mutations = []
        self.closed = []
        self.reopened = []
        self.archived = []
        self._init_shape()

    def execute(self, query, variables):
        shape_response = self._execute_shape(query, variables)
        if shape_response is not None:
            return shape_response
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
        if query == LABEL_ID_QUERY:
            label = None if self.label_missing else {"id": "L_archived"}
            return {"repository": {"label": label}}
        if query == ADD_LABEL_MUTATION:
            self.labels_added.append(variables["issueId"])
            return {"addLabelsToLabelable": {"clientMutationId": None}}
        if query == REMOVE_LABEL_MUTATION:
            self.labels_removed.append(variables["issueId"])
            return {"removeLabelsFromLabelable": {"clientMutationId": None}}
        if query == ARCHIVE_ITEM_MUTATION:
            self.archived.append(variables["itemId"])
            return {"archiveProjectV2Item": {"item": {"id": variables["itemId"]}}}
        if query == UNARCHIVE_ITEM_MUTATION:
            self.unarchived.append(variables["itemId"])
            return {"unarchiveProjectV2Item": {"item": {"id": variables["itemId"]}}}
        if query == CLEAR_FIELD_VALUE_MUTATION:
            self.cleared.append((variables["itemId"], variables["fieldId"]))
            return {"clearProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}
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

    assert result.status_unchanged == [("i_steady", Status.IN_PROGRESS)]
    assert result.status_written == [
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
    assert [item_id for item_id, _ in result.status_unchanged] == ["i_ready", "i_done"]
    assert result.status_written == []


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

    assert result.status_written == [
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


def test_review_beats_blocker_through_the_full_pipeline():
    item = _issue(
        "i_x", blocked_by=2, prs=[{"state": "OPEN", "isDraft": False}], assignees=1
    )
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.status_written == [("i_x", Status.IN_REVIEW)]


def test_maps_are_skipped_never_written():
    items = [
        _issue("i_map", labels=("wayfinder:map",)),
        _issue("i_task", assignees=1),
    ]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert result.skipped_maps == ["i_map"]
    assert [item_id for item_id, _ in result.status_written] == ["i_task"]
    # The map gets its Map stamp (a stamp mutation, not a Status one); no
    # Status write ever targets it.
    status_mutations = [
        m for m in client.mutations if m["fieldId"] == "PVTSSF_status"
    ]
    assert [m["itemId"] for m in status_mutations] == ["i_task"]


def test_contentless_items_are_skipped():
    items = [{"id": "i_draft", "content": None}, _issue("i_task", assignees=1)]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert result.skipped_contentless == ["i_draft"]
    assert [item_id for item_id, _ in result.status_written] == ["i_task"]


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

    assert dict(result.status_written) == {
        "i_child": Status.IN_PROGRESS,
        "i_parent": Status.IN_PROGRESS,
    }
    # Written in the Project's original item order: child, then parent.
    assert [item_id for item_id, _ in result.status_written] == ["i_child", "i_parent"]


def test_parent_stays_ready_when_no_child_is_in_progress():
    child = _issue("i_child")  # leaf, unassigned -> Ready
    parent = _issue("i_parent")
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.status_written) == {
        "i_child": Status.READY,
        "i_parent": Status.READY,
    }


def test_child_roll_up_beats_parents_blocker():
    child = _issue("i_child", assignees=1)  # leaf -> In progress
    parent = _issue("i_parent", blocked_by=1)
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.status_written)["i_parent"] == Status.IN_PROGRESS


def test_parents_own_review_pr_beats_child_roll_up():
    child = _issue("i_child", assignees=1)  # leaf -> In progress
    parent = _issue("i_parent", prs=[{"state": "OPEN", "isDraft": False}])
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.status_written)["i_parent"] == Status.IN_REVIEW


def test_child_in_review_no_longer_lifts_the_parent():
    """The roll-up rung is retired: PR cards carry the review lifecycle now, so
    a child in In review does NOT lift its parent — the parent reads its own
    facts (here: its own draft spec PR keeps it In progress)."""
    child = _issue("i_child", prs=[{"state": "OPEN", "isDraft": False}])  # leaf -> In review
    parent = _issue("i_parent", prs=[{"state": "OPEN", "isDraft": True}])  # otherwise In progress
    parent["content"]["subIssues"] = {"nodes": [{"id": "I_i_child"}]}
    client = FakeClient(_single_page([child, parent]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.status_written) == {
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
    assert dict(result.status_written) == {"i_child": Status.IN_PROGRESS}


def test_child_not_on_board_does_not_make_an_item_a_parent():
    """A sub-issue child that isn't itself a Project item can't be synced,
    so it can't be rolled up either: the item syncs as a plain leaf."""
    item = _issue("i_solo")
    item["content"]["subIssues"] = {"nodes": [{"id": "I_off_board"}]}
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert dict(result.status_written) == {"i_solo": Status.READY}


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
    assert result.status_written == [("i_stale_closed", Status.DONE)]
    assert result.status_unchanged == []


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
    assert dict(result.status_written) == {
        "i_child": Status.DONE,
        "i_parent": Status.IN_PROGRESS,
    }


PLANNING_REPO = "acme/acme-ai-planning"


class SeedingFakeClient(ShapeFakeMixin):
    """Models a *mutable* board over a fixed 'world' of issues.

    `world` maps content_id -> its facts (state, labels, blocked_by, prs,
    assignees) and `child_content_ids`. `repo_open` is what the planning repo
    reports as OPEN issues (REPO_ISSUES_QUERY). `on_board` is the content
    currently carded; ADD_ITEM grows it, and PROJECT_ITEMS reflects it — so the
    transitive sub-issue closure a real board would expose is modelled here too.
    """

    def __init__(self, world, repo_open, on_board=(), *, list_lag=False):
        self.repo_issue_labels = []
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
        self._init_shape()

    def _item(self, content_id):
        spec = self.world[content_id]
        if spec.get("is_pr"):
            return pr_item(
                item_id=f"PVTI_{content_id}",
                content_id=content_id,
                number=spec.get("number", 10),
                title=spec.get("title", "A pull request"),
                state=spec.get("state", "OPEN"),
                is_draft=spec.get("is_draft", False),
                merged=spec.get("merged", False),
                base_ref=spec.get("base_ref", "main"),
                head_ref=spec.get("head_ref", "feature"),
                review_decision=spec.get("review_decision"),
                rollup_state=spec.get("rollup_state"),
                status_option_id=spec.get("status_option_id"),
                map_option_id=spec.get("map_option_id"),
                spec_option_id=spec.get("spec_option_id"),
                is_archived=spec.get("is_archived", False),
            )
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
            map_option_id=spec.get("map_option_id"),
            spec_option_id=spec.get("spec_option_id"),
            is_archived=spec.get("is_archived", False),
            number=spec.get("number", 1),
            title=spec.get("title", "An issue"),
            sub_has_next=spec.get("sub_has_next", False),
            sub_cursor=spec.get("sub_cursor"),
        )

    def execute(self, query, variables):
        shape_response = self._execute_shape(query, variables)
        if shape_response is not None:
            return shape_response
        if query == STATUS_FIELD_QUERY:
            return STATUS_FIELD_RESPONSE
        if query == REPO_ISSUES_QUERY:
            wanted = variables.get("labels")
            self.repo_issue_labels.append(wanted)
            return {
                "repository": {
                    "issues": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {"id": cid}
                            for cid in self.repo_open
                            if not wanted
                            or set(wanted) <= set(self.world[cid].get("labels", ()))
                        ],
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
        if query == CLEAR_FIELD_VALUE_MUTATION:
            self.cleared.append((variables["itemId"], variables["fieldId"]))
            return {"clearProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}
        if query == ARCHIVE_ITEM_MUTATION:
            self.archived.append(variables["itemId"])
            return {"archiveProjectV2Item": {"item": {"id": variables["itemId"]}}}
        if query == UNARCHIVE_ITEM_MUTATION:
            self.unarchived.append(variables["itemId"])
            return {"unarchiveProjectV2Item": {"item": {"id": variables["itemId"]}}}
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


def test_all_board_seeds_every_open_issue_without_a_label_filter():
    world = {
        "C_apps": {"labels": ("squad:apps",)},
        "C_core": {"labels": ("squad:core",)},
        "C_none": {},
    }
    client = SeedingFakeClient(world=world, repo_open=list(world))

    added = seed_board(client, PROJECT_ID, PLANNING_REPO)

    assert set(added) == {"C_apps", "C_core", "C_none"}
    assert client.repo_issue_labels == [None]


def test_squad_board_seeds_only_issues_with_its_squad_label():
    world = {
        "C_apps": {"labels": ("squad:apps",)},
        "C_core": {"labels": ("squad:core",)},
        "C_none": {},
    }
    client = SeedingFakeClient(world=world, repo_open=list(world))

    added = seed_board(client, PROJECT_ID, PLANNING_REPO, seed_labels=("squad:apps",))

    assert set(added) == {"C_apps"}
    assert client.repo_issue_labels == [["squad:apps"]]


def test_seed_unions_explicit_labels():
    """A board with explicit seed labels pages the repo once per label and seeds
    the union — an issue carrying either label lands, one carrying neither (nor
    nothing at all) doesn't."""
    world = {
        "C_agent": {"labels": ("ready-for-agent",)},
        "C_map": {"labels": ("wayfinder:map",)},
        "C_bug": {"labels": ("bug",)},
        "C_none": {},
    }
    client = SeedingFakeClient(world=world, repo_open=list(world))

    added = seed_board(
        client,
        PROJECT_ID,
        PLANNING_REPO,
        seed_labels=("ready-for-agent", "wayfinder:map"),
    )

    assert set(added) == {"C_agent", "C_map"}
    assert client.repo_issue_labels == [["ready-for-agent"], ["wayfinder:map"]]


def test_squad_board_still_pulls_in_cross_squad_subissues_of_its_maps():
    world = {
        "C_map": {"labels": ("squad:apps",), "child_content_ids": ("C_core_child",)},
        "C_core_child": {"labels": ("squad:core",)},
    }
    client = SeedingFakeClient(world=world, repo_open=list(world))

    added = seed_board(client, PROJECT_ID, PLANNING_REPO, seed_labels=("squad:apps",))

    assert set(added) == {"C_map", "C_core_child"}


def test_run_sync_seeds_then_syncs_the_newly_carded_issue():
    """End to end: an open planning-repo task that starts off-board is carded by
    pass 0 and then given its Status by the sweep in the same run."""
    client = SeedingFakeClient(
        world={"C_task": {"assignees": 1}}, repo_open=["C_task"]
    )

    result = run_sync(client, PROJECT_ID, planning_repo=PLANNING_REPO)

    assert result.seeded == ["C_task"]
    assert dict(result.status_written) == {"PVTI_C_task": Status.IN_PROGRESS}


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
    assert dict(result.status_written) == {"PVTI_C_task": Status.IN_PROGRESS}
    assert [w["itemId"] for w in client.status_writes] == ["PVTI_C_task"]


def test_run_sync_without_planning_repo_does_not_seed():
    """Backward-compatible: omit the repo and pass 0 is skipped entirely — no
    REPO_ISSUES_QUERY, no add mutation."""
    items = [_issue("i_task", assignees=1)]
    client = FakeClient(_single_page(items))

    result = run_sync(client, PROJECT_ID)

    assert result.seeded == []
    assert [item_id for item_id, _ in result.status_written] == ["i_task"]


# --- the self-close-on-merge mechanism ---------------------------------------


def _issue_with_prs(item_id, *prs, state="OPEN", **kwargs):
    return issue_item(item_id, state=state, prs=prs, **kwargs)


def test_merged_linked_pr_closes_issue_and_sets_done():
    """A still-OPEN ticket whose deliberately-linked PR merged is closed (so
    dependents unblock) and its card resolves to Done."""
    item = _issue_with_prs("i_ticket", linked_pr(state="MERGED", merged=True))
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.status_written == [("i_ticket", Status.DONE)]
    # The underlying issue node id (content id) was closed exactly once.
    assert client.closed == ["I_i_ticket"]
    assert result.closed_issues == ["I_i_ticket"]


def test_open_pr_still_maps_to_in_review_and_does_not_close():
    """Unchanged behaviour: an open non-draft linked PR is In review, and
    nothing is closed while the PR is still open."""
    item = _issue_with_prs("i_review", linked_pr(state="OPEN", is_draft=False))
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.status_written == [("i_review", Status.IN_REVIEW)]
    assert client.closed == []


def test_open_draft_pr_maps_to_in_progress():
    item = _issue_with_prs("i_draft", linked_pr(state="OPEN", is_draft=True))
    client = FakeClient(_single_page([item]))

    result = run_sync(client, PROJECT_ID)

    assert result.status_written == [("i_draft", Status.IN_PROGRESS)]
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

    assert result.status_written == [("i_done", Status.DONE)]
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

    assert result.status_written == [("i_ticket", Status.DONE)]
    assert client.closed == ["I_i_ticket"]


# --- the map auto-close cascade ----------------------------------------------


def _map(item_id, *, state="OPEN", child_content_ids=(), labels=()):
    item = _issue(item_id, state=state, labels=("wayfinder:map", *labels))
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


def test_closed_map_with_an_open_descendant_is_reopened_and_its_closed_spec_still_archives():
    """The cascade reopens the map (its subtree gained an open descendant); the
    archive arm then hides what is actually closed — the settled spec — while
    the reopened map and the live work stay visible."""
    ticket = _issue("i_ticket", state="CLOSED")
    spec = _issue(
        "i_spec", state="CLOSED", child_content_ids=("I_i_ticket",)
    )
    still_open = _issue("i_open")
    unrelated = _issue("i_unrelated", state="CLOSED")
    map_item = _map(
        "i_map",
        state="CLOSED",
        child_content_ids=("I_i_spec", "I_i_open"),
    )
    client = FakeClient(_single_page([ticket, spec, still_open, unrelated, map_item]))

    result = run_sync(client, PROJECT_ID)

    assert result.map_reopened == ["I_i_map"]
    # The reopened map is open, so it is not archived; the closed spec and its
    # closed ticket are (the family hides together).
    assert map_item["id"] not in client.archived
    assert client.archived == ["i_ticket", "i_spec"]
    assert result.unarchived == []


ARCHIVED = "wayfinder:archived"

class TreeFakeClient(FakeClient):
    """FakeClient that also answers the sub-issue walk and unarchive mutation.

    `graph` maps an issue node id to
    `(ref, state, project item id, archived, child ids)`.
    """

    def __init__(self, item_pages, graph):
        super().__init__(item_pages)
        self.graph = graph
        self.unarchived = []

    def execute(self, query, variables):
        if query == ISSUE_SUBTREE_QUERY:
            ref, state, item_id, archived, children = self.graph[variables["issueId"]]
            repo, _, number = ref.partition("#")
            return {
                "node": {
                    "id": variables["issueId"],
                    "number": int(number),
                    "state": state,
                    "repository": {"nameWithOwner": repo},
                    "projectItems": {
                        "nodes": [
                            {
                                "id": item_id,
                                "isArchived": archived,
                                "project": {"id": PROJECT_ID},
                            }
                        ]
                    },
                    "subIssues": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"id": child} for child in children],
                    },
                }
            }
        if query == UNARCHIVE_ITEM_MUTATION:
            self.unarchived.append(variables["itemId"])
            return {"unarchiveProjectV2Item": {"item": {"id": variables["itemId"]}}}
        return super().execute(query, variables)


def test_closed_map_with_only_invisible_children_is_not_reopened():
    """Archived children are not on the board read; they must not look open."""
    map_item = _map("i_map", state="CLOSED", child_content_ids=("I_archived",))
    client = FakeClient(_single_page([map_item]))

    result = run_sync(client, PROJECT_ID)

    assert result.map_reopened == []
    assert client.reopened == []


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
            closed=False, open_blocker_count=0,
            assigned=False, is_map=True,
        ),
        "i_child": make_facts(
            closed=True, open_blocker_count=0,
            assigned=False,
        ),
    }
    item_id_by_content_id = {"C_map": "i_map", "C_child": "i_child"}
    child_content_ids_by_item_id = {"i_map": ["C_child"], "i_child": []}

    actions = compute_map_cascade(
        facts_by_item_id, item_id_by_content_id, child_content_ids_by_item_id
    )

    assert actions == [MapCascadeAction("i_map", "C_map", close=True)]


# --- the PR-centric arms: typing+stamping, PR carding, the vanish, archives ----


def _stamp_writes(client):
    """The stamp mutations (Map/Spec field writes), as (itemId, fieldId) pairs."""

    writes = client.status_writes + getattr(client, "mutations", [])
    return [
        (m["itemId"], m["fieldId"])
        for m in writes
        if m.get("fieldId") in ("PVTSSF_Map", "PVTSSF_Spec")
    ]


def _status_writes_only(client):
    return [m for m in client.mutations if m.get("fieldId") == "PVTSSF_status"] + [
        w for w in getattr(client, "status_writes", [])
        if w.get("fieldId") == "PVTSSF_status"
    ]


def test_a_map_tree_grows_the_stamp_fields_and_stamps_every_card():
    world = {
        "C_map": {
            "labels": ("wayfinder:map",),
            "number": 1,
            "title": "Map: the effort",
            "child_content_ids": ("C_phase1", "C_spec"),
        },
        "C_phase1": {"labels": ("wayfinder:research",), "number": 2, "title": "Research"},
        "C_spec": {
            "labels": ("ready-for-agent",),
            "number": 5,
            "title": "Spec: the slice",
            "child_content_ids": ("C_impl",),
        },
        "C_impl": {"labels": ("ready-for-agent",), "number": 7, "title": "Impl: the ticket"},
    }
    client = SeedingFakeClient(world=world, repo_open=[], on_board=list(world))

    result = run_sync(client, PROJECT_ID, planning_repo=PLANNING_REPO)

    # Both stamp fields are created by the sweep itself.
    assert sorted(result.fields_created) == ["Map", "Spec"]
    stamp_pairs = set(_stamp_writes(client))
    # Map stamps: the map card, its phase-1 ticket, its spec.
    assert ("PVTI_C_map", "PVTSSF_Map") in stamp_pairs
    assert ("PVTI_C_phase1", "PVTSSF_Map") in stamp_pairs
    assert ("PVTI_C_spec", "PVTSSF_Map") in stamp_pairs
    # Spec stamps: the spec card and its implementation ticket.
    assert ("PVTI_C_spec", "PVTSSF_Spec") in stamp_pairs
    assert ("PVTI_C_impl", "PVTSSF_Spec") in stamp_pairs
    # The map and its phase-1 ticket share one Map option; the spec and its
    # ticket share one Spec option.
    def option_for(item_id, field_id):
        for m in client.status_writes:
            if m["itemId"] == item_id and m["fieldId"] == field_id:
                return m["optionId"]
        raise AssertionError(f"no stamp write for {item_id}/{field_id}")

    assert option_for("PVTI_C_map", "PVTSSF_Map") == option_for("PVTI_C_phase1", "PVTSSF_Map")
    assert option_for("PVTI_C_spec", "PVTSSF_Spec") == option_for("PVTI_C_impl", "PVTSSF_Spec")
    # The impl ticket carries NO Map stamp (it is a grandchild: *Parent issue*
    # places it in the tree views).
    assert ("PVTI_C_impl", "PVTSSF_Map") not in stamp_pairs
    # Statuses still flow: the map is skipped, the rest are scored.
    assert result.skipped_maps == ["PVTI_C_map"]
    assert dict(result.status_written) == {
        "PVTI_C_phase1": Status.READY,
        "PVTI_C_spec": Status.READY,
        "PVTI_C_impl": Status.READY,
    }


def test_a_settled_tree_re_stamps_nothing():
    world = {
        "C_map": {
            "labels": ("wayfinder:map",),
            "number": 1,
            "title": "Map: the effort",
            "child_content_ids": ("C_spec",),
        },
        "C_spec": {"labels": ("ready-for-agent",), "number": 5, "title": "Spec: the slice"},
    }
    client = SeedingFakeClient(world=world, repo_open=[], on_board=list(world))
    run_sync(client, PROJECT_ID, planning_repo=PLANNING_REPO)
    first_stamp_writes = _stamp_writes(client)

    # Second run: everything already stamped -> the sweep writes nothing.
    client_second = SeedingFakeClient(
        world={
            key: {**value, "map_option_id": "opt_new_1_0", "spec_option_id": "opt_new_2_0"}
            for key, value in world.items()
        },
        repo_open=[],
        on_board=list(world),
    )
    # Give the cards their settled Status too, so no status write fires either.
    client_second.world["C_map"]["status_option_id"] = "opt_ready"
    client_second.world["C_spec"]["status_option_id"] = "opt_ready"
    run_sync(client_second, PROJECT_ID, planning_repo=PLANNING_REPO)

    assert _stamp_writes(client_second) == []
    assert client_second.status_writes == []
    assert first_stamp_writes  # the first run did stamp (sanity)


def test_spec_and_stack_prs_are_carded_and_stamped_the_vanish_clears_the_ticket():
    owner, name = PLANNING_REPO.split("/", 1)
    world = {
        "C_map": {
            "labels": ("wayfinder:map",),
            "number": 1,
            "title": "Map: the effort",
            "child_content_ids": ("C_spec",),
        },
        "C_spec": {
            "labels": ("ready-for-agent",),
            "number": 5,
            "title": "Spec: the slice",
            "child_content_ids": ("C_impl",),
        },
        "C_impl": {
            "labels": ("ready-for-agent",),
            "number": 7,
            "title": "Impl: the ticket",
            # Its own stack PR is open against it (the closing link was
            # authored by the link arm, so the issue-side connection sees it).
            "prs": (linked_pr(state="OPEN", is_draft=True, pr_id="PR_14"),),
            # The settled state before the PR opened: the ticket carried its
            # spec's stamp, so the vanish has something to clear.
            "spec_option_id": "opt_spec",
        },
        "PR_14": {
            "is_pr": True,
            "number": 14,
            "title": "feat: the ticket",
            "is_draft": True,
            "base_ref": "the-slice/base",
            "head_ref": "the-slice/7-ticket",
        },
    }
    repo_prs = [
        {
            "id": "PR_14",
            "number": 14,
            "state": "OPEN",
            "isDraft": True,
            "baseRefName": "the-slice/base",
            "headRefName": "the-slice/7-ticket",
            "closingRefs": {
                "nodes": [
                    {
                        "number": 7,
                        "id": "C_impl",
                        "repository": {"owner": {"login": owner}, "name": name},
                    }
                ]
            },
        }
    ]
    client = SeedingFakeClient(
        world=world, repo_open=[], on_board=["C_map", "C_spec", "C_impl"]
    )
    # The Spec field already exists with the spec's option (the settled state
    # before the PR opened), so the vanish has a real value to clear.
    client.shape_fields["Spec"] = {
        "id": "PVTSSF_Spec",
        "options": [{"id": "opt_spec", "name": "Spec: the slice #5"}],
    }
    client.world["C_spec"]["spec_option_id"] = "opt_spec"

    result = run_sync(
        client, PROJECT_ID, planning_repo=PLANNING_REPO, repo_prs=repo_prs
    )

    # The stack PR became a card.
    assert result.pr_cards_added == ["PR_14"]
    stamp_pairs = set(_stamp_writes(client))
    # The impl ticket's Spec stamp is CLEARED (the vanish): its PR card takes
    # over the implementation surface.
    assert ("PVTI_C_impl", "PVTSSF_Spec") in [tuple(c) for c in client.cleared]
    # The PR card is stamped with its spec.
    assert ("PVTI_PR_14", "PVTSSF_Spec") in stamp_pairs
    # The spec itself is NOT vanished (its own spec PR is not open).
    assert ("PVTI_C_spec", "PVTSSF_Spec") not in [tuple(c) for c in client.cleared]
    # Statuses: the draft PR is In progress; so is the ticket it implements.
    assert dict(result.status_written)["PVTI_PR_14"] == Status.IN_PROGRESS
    assert dict(result.status_written)["PVTI_C_impl"] == Status.IN_PROGRESS


def test_a_spec_pr_replaces_its_spec_in_the_maps_surface():
    owner, name = PLANNING_REPO.split("/", 1)
    world = {
        "C_map": {
            "labels": ("wayfinder:map",),
            "number": 1,
            "title": "Map: the effort",
            "child_content_ids": ("C_spec",),
        },
        "C_spec": {
            "labels": ("ready-for-agent",),
            "number": 5,
            "title": "Spec: the slice",
            # Its own spec PR is open (a draft into main).
            "prs": (linked_pr(state="OPEN", is_draft=True, pr_id="PR_11"),),
        },
        "PR_11": {
            "is_pr": True,
            "number": 11,
            "title": "feat: the spec",
            "is_draft": True,
            "base_ref": "main",
            "head_ref": "the-slice/base",
        },
    }
    repo_prs = [
        {
            "id": "PR_11",
            "number": 11,
            "state": "OPEN",
            "isDraft": True,
            "baseRefName": "main",
            "headRefName": "the-slice/base",
            "closingRefs": {
                "nodes": [
                    {
                        "number": 5,
                        "id": "C_spec",
                        "repository": {"owner": {"login": owner}, "name": name},
                    }
                ]
            },
        }
    ]
    client = SeedingFakeClient(world=world, repo_open=[], on_board=["C_map", "C_spec"])
    # The settled pre-PR state: both stamp fields exist with their options and
    # the spec card carries them, so the vanish has real values to clear.
    client.shape_fields["Map"] = {
        "id": "PVTSSF_Map",
        "options": [{"id": "opt_map", "name": "Map: the effort #1"}],
    }
    client.shape_fields["Spec"] = {
        "id": "PVTSSF_Spec",
        "options": [{"id": "opt_spec", "name": "Spec: the slice #5"}],
    }
    client.world["C_map"]["map_option_id"] = "opt_map"
    client.world["C_spec"]["map_option_id"] = "opt_map"
    client.world["C_spec"]["spec_option_id"] = "opt_spec"

    result = run_sync(
        client, PROJECT_ID, planning_repo=PLANNING_REPO, repo_prs=repo_prs
    )

    assert result.pr_cards_added == ["PR_11"]
    # The spec ticket vanishes from BOTH surfaces; the spec PR card replaces
    # it in Maps (Map stamp) and carries Specs (Spec stamp).
    cleared = [tuple(c) for c in client.cleared]
    assert ("PVTI_C_spec", "PVTSSF_Map") in cleared
    assert ("PVTI_C_spec", "PVTSSF_Spec") in cleared
    stamp_pairs = set(_stamp_writes(client))
    assert ("PVTI_PR_11", "PVTSSF_Map") in stamp_pairs
    assert ("PVTI_PR_11", "PVTSSF_Spec") in stamp_pairs
    # The draft spec PR reads In progress.
    assert dict(result.status_written)["PVTI_PR_11"] == Status.IN_PROGRESS


def test_a_standalone_pr_into_main_is_never_carded():
    repo_prs = [
        {
            "id": "PR_solo",
            "number": 20,
            "state": "OPEN",
            "isDraft": False,
            "baseRefName": "main",
            "headRefName": "quickfix",
            "closingRefs": {"nodes": []},
        }
    ]
    client = SeedingFakeClient(world={}, repo_open=[], on_board=[])

    result = run_sync(
        client, PROJECT_ID, planning_repo=PLANNING_REPO, repo_prs=repo_prs
    )

    assert result.pr_cards_added == []
    assert "PR_solo" not in client.on_board


def test_the_merged_family_archives_and_phase1_stays_visible():
    map_item = _map("i_map", child_content_ids=("I_i_spec", "I_i_res"))
    spec = _issue("i_spec", state="CLOSED", child_content_ids=("I_i_impl",))
    impl = _issue(
        "i_impl",
        state="OPEN",
        prs=[{"id": "PR_m", "state": "MERGED", "isDraft": False, "merged": True}],
    )
    research = _issue("i_res", state="CLOSED", labels=("wayfinder:research",))
    client = FakeClient(
        _single_page([map_item, spec, impl, research])
    )

    result = run_sync(client, PROJECT_ID)

    # The closed spec, its closed ticket and the map itself archive; the
    # closed phase-1 research ticket stays visible (Done).
    assert set(client.archived) == {"i_spec", "i_impl", "i_map"}
    assert "i_res" not in client.archived
    assert result.archived == client.archived


def test_a_reopened_spec_comes_back_from_the_archive():
    map_item = _map("i_map", child_content_ids=("I_i_spec",))
    spec = _issue("i_spec", state="OPEN")
    spec["isArchived"] = True  # hidden by the earlier close; the work resumed
    client = FakeClient(_single_page([map_item, spec]))

    result = run_sync(client, PROJECT_ID)

    assert client.unarchived == ["i_spec"]
    assert result.unarchived == ["i_spec"]


def test_a_hand_archived_standalone_card_stays_hidden():
    """The sweep respects the hand: a standalone issue archived manually is
    never force-restored (and never auto-archived either)."""
    standalone = _issue("i_solo", state="OPEN")
    standalone["isArchived"] = True
    client = FakeClient(_single_page([standalone]))

    result = run_sync(client, PROJECT_ID)

    assert client.archived == []
    assert client.unarchived == []
    assert result.archived == []
    assert result.unarchived == []



def test_a_sub_issue_tail_beyond_one_page_is_paged_and_ingested():
    """A spec with more tickets than one embed page (50) must not be silently
    truncated: the tail is fetched and folded in, so the closure, the typing
    and the roll-up see the full set."""
    child_ids = [f"C_child_{i}" for i in range(55)]
    world = {
        "C_map": {
            "labels": ("wayfinder:map",),
            "number": 1,
            "title": "Map: the effort",
            "child_content_ids": ("C_spec",),
        },
        "C_spec": {
            "labels": ("ready-for-agent",),
            "number": 5,
            "title": "Spec: the slice",
            "child_content_ids": tuple(child_ids[:50]),  # the embedded page
            "sub_has_next": True,
            "sub_cursor": "sub-cur-0",
        },
    }
    for cid in child_ids:
        world[cid] = {"labels": ("ready-for-agent",), "number": 100, "title": "Impl"}
    client = SeedingFakeClient(
        world=world,
        repo_open=[],
        on_board=["C_map", "C_spec"] + child_ids[:50],
    )
    # The sub-issue pager: the issue-side query returns the 5-child tail.
    def fake_sub_issues(query, variables):
        assert variables["issueId"] == "C_spec"
        return {
            "node": {
                "subIssues": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{"id": cid} for cid in child_ids[50:]],
                }
            }
        }

    client._extra_handlers = {ISSUE_SUB_ISSUES_QUERY: fake_sub_issues}
    original_execute = client.execute

    def execute_with_extra(query, variables):
        handler = getattr(client, "_extra_handlers", {}).get(query)
        if handler is not None:
            return handler(query, variables)
        return original_execute(query, variables)

    client.execute = execute_with_extra

    result = run_sync(client, PROJECT_ID, planning_repo=PLANNING_REPO)

    # The tail children were seeded (carded) and typed impl — not truncated.
    assert len(result.seeded) == 5
    stamp_writes = {(m["itemId"], m["fieldId"]) for m in client.status_writes
                    if m["fieldId"] == "PVTSSF_Spec"}
    assert len(stamp_writes) >= 5  # the tail tickets carry their spec's stamp


def test_a_detached_impl_ticket_loses_its_stale_spec_stamp():
    """A card that LOST its association (its spec was unlinked from the map)
    has its stale stamp cleared: the drift-clears settle both stamp fields of
    every card each sweep, so nothing stays grouped under a map/spec it no
    longer belongs to."""
    world = {
        "C_map": {
            "labels": ("wayfinder:map",),
            "number": 1,
            "title": "Map: the effort",
            # The spec was UNLINKED: the map no longer lists it.
        },
        "C_spec": {
            "labels": ("ready-for-agent",),
            "number": 5,
            "title": "Spec: the slice",
            "child_content_ids": ("C_impl",),
            "map_option_id": "opt_map",  # stale stamps from before the unlink
            "spec_option_id": "opt_spec",
        },
        "C_impl": {
            "labels": ("ready-for-agent",),
            "number": 7,
            "title": "Impl: the ticket",
            "spec_option_id": "opt_spec",  # the stale stamp to clear
        },
    }
    client = SeedingFakeClient(
        world=world, repo_open=[], on_board=["C_map", "C_spec", "C_impl"]
    )
    client.shape_fields["Map"] = {
        "id": "PVTSSF_Map",
        "options": [{"id": "opt_map", "name": "Map: the effort #1"}],
    }
    client.shape_fields["Spec"] = {
        "id": "PVTSSF_Spec",
        "options": [{"id": "opt_spec", "name": "Spec: the slice #5"}],
    }
    client.world["C_map"]["map_option_id"] = "opt_map"

    run_sync(client, PROJECT_ID, planning_repo=PLANNING_REPO)

    cleared = [tuple(c) for c in client.cleared]
    # The unlinked spec and its detached ticket lose their stale stamps.
    assert ("PVTI_C_spec", "PVTSSF_Spec") in cleared
    assert ("PVTI_C_spec", "PVTSSF_Map") in cleared
    assert ("PVTI_C_impl", "PVTSSF_Spec") in cleared
    # The map keeps its own stamp.
    assert ("PVTI_C_map", "PVTSSF_Map") not in [tuple(c) for c in client.cleared]

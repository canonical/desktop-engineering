"""Shared test helpers: build GraphQL Project item payloads.

Both the mapper tests and the orchestration tests need item payloads shaped like
the GraphQL response. Keeping the builder in one place means a schema change is a
single edit, not shotgun surgery across two test files.
"""

from ai_planning.queries import (
    CREATE_SINGLE_SELECT_FIELD_MUTATION,
    CREATE_VIEW_MUTATION,
    FIELD_BY_NAME_QUERY,
    PROJECT_FIELDS_QUERY,
    PROJECT_VIEWS_QUERY,
    UPDATE_FIELD_OPTIONS_MUTATION,
    UPDATE_VIEW_MUTATION,
)
from ai_planning.shape import STATUS_OPTIONS, WANTED_VIEWS


def linked_pr(
    *,
    state="OPEN",
    is_draft=False,
    merged=False,
    review_decision=None,
    rollup_state=None,
    pr_id="PR_x",
):
    """One node of the `closedByPullRequestsReferences(userLinkedOnly: false)`
    connection: a closing-linked PR, shaped like the GraphQL response. The
    nodes are full PullRequest objects, so the review decision and the check
    rollup ride along."""

    return {
        "id": pr_id,
        "state": state,
        "isDraft": is_draft,
        "merged": merged,
        "reviewDecision": review_decision,
        "statusCheckRollup": {"state": rollup_state} if rollup_state is not None else None,
    }


def issue_item(
    item_id="PVTI_item",
    *,
    state="OPEN",
    assignees=0,
    labels=(),
    blocked_by=0,
    prs=(),
    content_id=None,
    child_content_ids=(),
    parent=None,
    repository="canonical/test",
    status_option_id=None,
    map_option_id=None,
    spec_option_id=None,
    is_archived=False,
    number=1,
    title="An issue",
    prs_has_next=False,
    prs_cursor=None,
    sub_has_next=False,
    sub_cursor=None,
):
    """An Issue-content Project item with the fields the fetch shell reads.

    `content_id` is the underlying issue's own node id (defaults to a value
    computed from `item_id` so tests don't have to invent one unless they need
    a specific id to correlate a parent with its children).
    `child_content_ids` lists the content ids of this item's native sub-issue
    children, for the two-pass roll-up.
    `status_option_id` is the Status single-select option id already set on the
    card, if any, used by the job's skip-if-unchanged guard; `map_option_id` /
    `spec_option_id` are the same for the Map and Spec stamp fields.
    `prs` is the list of deliberately-linked PR nodes (build them with
    `linked_pr`) on `closedByPullRequestsReferences`, and
    `prs_has_next`/`prs_cursor` model that connection's `pageInfo` for the
    paging path.
    """

    return {
        "id": item_id,
        "isArchived": is_archived,
        "status": (
            {"optionId": status_option_id} if status_option_id is not None else None
        ),
        "map": {"optionId": map_option_id} if map_option_id is not None else None,
        "spec": {"optionId": spec_option_id} if spec_option_id is not None else None,
        "content": {
            "__typename": "Issue",
            "id": content_id if content_id is not None else f"I_{item_id}",
            "number": number,
            "title": title,
            "state": state,
            "repository": {"nameWithOwner": repository},
            "parent": parent,
            "assignees": {"totalCount": assignees},
            "labels": {"nodes": [{"name": name} for name in labels]},
            "issueDependenciesSummary": {"blockedBy": blocked_by},
            "closedByPullRequestsReferences": {
                "pageInfo": {
                    "hasNextPage": prs_has_next,
                    "endCursor": prs_cursor,
                },
                "nodes": list(prs),
            },
            "subIssues": {
                "pageInfo": {"hasNextPage": sub_has_next, "endCursor": sub_cursor},
                "nodes": [{"id": cid} for cid in child_content_ids],
            },
        },
    }


def pr_item(
    item_id="PVTI_pr",
    *,
    number=10,
    title="A pull request",
    state="OPEN",
    is_draft=False,
    merged=False,
    base_ref="main",
    head_ref="feature/one",
    review_decision=None,
    rollup_state=None,
    content_id=None,
    labels=(),
    status_option_id=None,
    map_option_id=None,
    spec_option_id=None,
    is_archived=False,
):
    """A PullRequest-content Project item with the fields the fetch shell reads."""

    return {
        "id": item_id,
        "isArchived": is_archived,
        "status": (
            {"optionId": status_option_id} if status_option_id is not None else None
        ),
        "map": {"optionId": map_option_id} if map_option_id is not None else None,
        "spec": {"optionId": spec_option_id} if spec_option_id is not None else None,
        "content": {
            "__typename": "PullRequest",
            "id": content_id if content_id is not None else f"PR_{item_id}",
            "number": number,
            "title": title,
            "state": state,
            "isDraft": is_draft,
            "merged": merged,
            "baseRefName": base_ref,
            "headRefName": head_ref,
            "reviewDecision": review_decision,
            "statusCheckRollup": (
                {"state": rollup_state} if rollup_state is not None else None
            ),
            "assignees": {"totalCount": 0},
            "labels": {"nodes": [{"name": name} for name in labels]},
        },
    }


def converged_status_options():
    """The six Status options with the test suite's stable option ids."""

    test_ids = {
        "Blocked": "opt_blocked",
        "Ready": "opt_ready",
        "In progress": "opt_in_progress",
        "In review": "opt_in_review",
        "Approved": "opt_approved",
        "Done": "opt_done",
    }
    return [
        {"id": test_ids[option["name"]], "name": option["name"],
         "description": option["description"], "color": option["color"]}
        for option in STATUS_OPTIONS
    ]


CONVERGED_FIELD_NAMES = [
    "Title",
    "Assignees",
    "Status",
    "Labels",
    "Linked pull requests",
    "Milestone",
    "Repository",
    "Reviewers",
    "Parent issue",
    "Sub-issues progress",
    "Created",
    "Updated",
    "Closed",
    "Map",
    "Spec",
]


class ShapeFakeMixin:
    """Answers the board-shape queries from an in-memory converged board.

    The default board is already converged (the six Status columns with their
    designed descriptions, the three views with their filters and visible
    fields), so a settled sweep issues no shape mutation at all — the shape
    mutations the tests DO see are the ones under test. `shape_fields` holds
    every single-select field by name; tests seed `Map`/`Spec` here when they
    exercise stamping.
    """

    def _init_shape(self):
        self.shape_fields = {
            "Status": {"id": "PVTSSF_status", "options": converged_status_options()}
        }
        self.shape_views = [
            {
                "id": f"PVTV_{wanted['name']}",
                "name": wanted["name"],
                "layout": wanted["layout"],
                "filter": wanted["filter"],
                "fields": {"nodes": [{"name": name} for name in wanted["fields"]]},
            }
            for wanted in WANTED_VIEWS
        ]
        self.fields_created = []
        self.views_created = []
        self.views_updated = []
        self.cleared = []
        self.unarchived = []
        self.shape_mutations = []

    def _execute_shape(self, query, variables):
        if query == FIELD_BY_NAME_QUERY:
            field = self.shape_fields.get(variables["fieldName"])
            return {
                "node": {
                    "field": (
                        {"id": field["id"], "options": field["options"]}
                        if field
                        else None
                    )
                }
            }
        if query == PROJECT_FIELDS_QUERY:
            names = set(CONVERGED_FIELD_NAMES) | set(self.shape_fields)
            nodes = [
                {
                    "id": (
                        self.shape_fields[name]["id"]
                        if name in self.shape_fields
                        else "PVTF_" + name.replace(" ", "_")
                    ),
                    "name": name,
                }
                for name in sorted(names)
            ]
            return {"node": {"fields": {"nodes": nodes}}}
        if query == PROJECT_VIEWS_QUERY:
            return {"node": {"views": {"nodes": list(self.shape_views)}}}
        if query == CREATE_SINGLE_SELECT_FIELD_MUTATION:
            options = [
                {"id": f"opt_new_{len(self.shape_fields)}_{i}", **option}
                for i, option in enumerate(variables["options"])
            ]
            field_id = "PVTSSF_" + variables["fieldName"]
            self.shape_fields[variables["fieldName"]] = {
                "id": field_id,
                "options": options,
            }
            self.fields_created.append(variables["fieldName"])
            self.shape_mutations.append(query)
            return {
                "createProjectV2Field": {
                    "projectV2Field": {"id": field_id, "options": options}
                }
            }
        if query == UPDATE_FIELD_OPTIONS_MUTATION:
            merged = []
            for option in variables["options"]:
                kept = dict(option)
                if "id" not in kept:
                    kept["id"] = "opt_new_%d" % len(merged)
                if "description" not in kept:
                    kept["description"] = ""
                merged.append(kept)
            for name, field in self.shape_fields.items():
                if field["id"] == variables["fieldId"]:
                    self.shape_fields[name] = {"id": field["id"], "options": merged}
                    break
            self.shape_mutations.append(query)
            return {
                "updateProjectV2Field": {
                    "projectV2Field": {
                        "id": variables["fieldId"],
                        "options": merged,
                    }
                }
            }
        if query == CREATE_VIEW_MUTATION:
            view = {
                "id": "PVTV_new_%d" % len(self.shape_views),
                "name": variables["name"],
                "layout": variables["layout"],
                "filter": "",
                "fields": {"nodes": []},
            }
            self.shape_views.append(view)
            self.views_created.append(variables["name"])
            self.shape_mutations.append(query)
            return {"createProjectV2View": {"projectV2View": view}}
        if query == UPDATE_VIEW_MUTATION:
            for view in self.shape_views:
                if view["id"] == variables["viewId"]:
                    if variables.get("filter") is not None:
                        view["filter"] = variables["filter"]
                    if variables.get("visibleFieldIds") is not None:
                        id_to_name = {
                            field["id"]: name for name, field in self.shape_fields.items()
                        }
                        for name in CONVERGED_FIELD_NAMES:
                            id_to_name.setdefault(
                                "PVTF_" + name.replace(" ", "_"), name
                            )
                        names = [
                            id_to_name[field_id]
                            for field_id in variables["visibleFieldIds"]
                            if field_id in id_to_name
                        ]
                        view["fields"] = {"nodes": [{"name": name} for name in names]}
                    self.views_updated.append(view["name"])
                    self.shape_mutations.append(query)
                    break
            return {"updateProjectV2View": {"projectV2View": {"id": variables["viewId"]}}}
        return None

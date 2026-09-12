"""Shared test helper: build a GraphQL Project item payload.

Both the mapper tests and the orchestration tests need item payloads shaped like
the GraphQL response. Keeping the builder in one place means a schema change is a
single edit, not shotgun surgery across two test files.
"""


def linked_pr(*, state="OPEN", is_draft=False, merged=False):
    """One node of the `closedByPullRequestsReferences(userLinkedOnly: true)`
    connection: a deliberately-linked PR, shaped like the GraphQL response."""

    return {"state": state, "isDraft": is_draft, "merged": merged}


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
    status_option_id=None,
    prs_has_next=False,
    prs_cursor=None,
):
    """An Issue-content Project item with the fields the fetch shell reads.

    `content_id` is the underlying issue's own node id (defaults to a value
    computed from `item_id` so tests don't have to invent one unless they need
    a specific id to correlate a parent with its children).
    `child_content_ids` lists the content ids of this item's native sub-issue
    children, for the two-pass roll-up.
    `status_option_id` is the Status single-select option id already set on the
    card, if any, used by the job's skip-if-unchanged guard.
    `prs` is the list of deliberately-linked PR nodes (build them with
    `linked_pr`) on `closedByPullRequestsReferences`, and
    `prs_has_next`/`prs_cursor` model that connection's `pageInfo` for the
    paging path.
    """

    return {
        "id": item_id,
        "status": (
            {"optionId": status_option_id} if status_option_id is not None else None
        ),
        "content": {
            "__typename": "Issue",
            "id": content_id if content_id is not None else f"I_{item_id}",
            "state": state,
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
            "subIssues": {"nodes": [{"id": cid} for cid in child_content_ids]},
        },
    }

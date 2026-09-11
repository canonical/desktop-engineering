"""Shared test helper: build a GraphQL Project item payload.

Both the mapper tests and the orchestration tests need item payloads shaped like
the GraphQL response. Keeping the builder in one place means a schema change is a
single edit, not shotgun surgery across two test files.
"""


def _xref_event(*, merged=False, state="OPEN", cross_repo=True, repo=None,
                will_close=False):
    """A CROSS_REFERENCED_EVENT timeline node sourced from a PullRequest.

    Shaped like the GraphQL response the fetch shell reads: `merged`/`state`
    say whether the PR merged, `cross_repo` is `isCrossRepository`, `repo` is the
    source PR's `nameWithOwner`, and `will_close` is `willCloseTarget` (always
    false for a spec-branch PR — carried only so tests can prove the fact does
    not key off it).
    """

    return {
        "willCloseTarget": will_close,
        "isCrossRepository": cross_repo,
        "source": {
            "__typename": "PullRequest",
            "number": 1,
            "state": state,
            "merged": merged,
            "baseRefName": "some-spec-branch",
            "repository": {"nameWithOwner": repo} if repo is not None else None,
        },
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
    status_option_id=None,
    timeline=(),
    timeline_has_next=False,
    timeline_cursor=None,
):
    """An Issue-content Project item with the fields the fetch shell reads.

    `content_id` is the underlying issue's own node id (defaults to a value
    computed from `item_id` so tests don't have to invent one unless they need
    a specific id to correlate a parent with its children).
    `child_content_ids` lists the content ids of this item's native sub-issue
    children, for the two-pass roll-up.
    `status_option_id` is the Status single-select option id already set on the
    card, if any, used by the job's skip-if-unchanged guard.
    `timeline` is the list of CROSS_REFERENCED_EVENT nodes on the issue timeline
    (build them with `_xref_event`), and `timeline_has_next`/`timeline_cursor`
    model the timeline connection's `pageInfo` for the paging path.
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
            "closedByPullRequestsReferences": {"nodes": list(prs)},
            "timelineItems": {
                "pageInfo": {
                    "hasNextPage": timeline_has_next,
                    "endCursor": timeline_cursor,
                },
                "nodes": list(timeline),
            },
            "subIssues": {"nodes": [{"id": cid} for cid in child_content_ids]},
        },
    }

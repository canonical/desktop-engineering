"""Map a raw GraphQL Project item onto the pure function's `Facts` input.

This is the *read* half of the I/O shell: it turns the native GitHub facts
GraphQL returns into the exact `Facts` tuple `sync_status` eats. It extracts
facts only — it holds **no** precedence branching. The ladder lives solely in
`sync_status`; here we only read what GitHub reports.

A card scores off exactly one PR read: `closedByPullRequestsReferences(
userLinkedOnly: false, includeClosedPrs: true)`, GitHub's closing-link
connection (a closing keyword or a manually attached link). A mere mention
scores nothing — only closing references appear in this connection at all.
The nodes are full PullRequest objects, so the folded PR facts (`pr_state`,
`pr_ci_ok`, `pr_approved`) come off the same connection. A PR *card* scores
its own fields instead (`isDraft`, `statusCheckRollup`, `reviewDecision`).

A Project item whose `content` is null (a draft item, or an issue the token
cannot see) yields `None`: there is no underlying issue/PR to score, so the job
skips it rather than inventing facts.
"""

from __future__ import annotations

from typing import Any

from ai_planning.sync_status import Facts, make_facts

MAP_LABEL = "wayfinder:map"


def _label_names(content: dict[str, Any]) -> list[str]:
    return [node["name"] for node in (content.get("labels") or {}).get("nodes", [])]


def _linked_pr_nodes(content: dict[str, Any]) -> list[dict[str, Any]]:
    """This issue's deliberately-linked PR nodes, or an empty list."""

    refs = content.get("closedByPullRequestsReferences") or {}
    return refs.get("nodes") or []


def _rollup_ok(pr: dict[str, Any]) -> bool:
    """True when this PR's check rollup is green — or it runs no checks.

    `statusCheckRollup.state` is `SUCCESS` when every check passed and `None`
    when the PR runs no checks at all (both count as green); `FAILURE`,
    `ERROR`, `PENDING` and `EXPECTED` mean not-green yet, whatever the PR's
    draft flag says.
    """

    rollup = pr.get("statusCheckRollup") or {}
    return rollup.get("state") in (None, "SUCCESS")


def _fold_open_prs(content: dict[str, Any]) -> tuple[str | None, bool | None, bool]:
    """Fold the issue's open linked PRs into `(pr_state, pr_ci_ok, pr_approved)`.

    The most advanced open PR wins for the state (ready over draft). CI is
    scored only for ready PRs (a draft is expected to be red — the agent is
    still working): green-and-or-check-free across all of them, `False` when
    any is not green, `None` when there is no ready PR. `pr_approved` is True
    when any open PR carries `reviewDecision == APPROVED` (GitHub blocks
    self-approval and approving a draft, so this is always a second
    reviewer's verdict on a reviewable PR).
    """

    state: str | None = None
    ci_ok: bool | None = None
    approved = False
    for pr in _linked_pr_nodes(content):
        if pr.get("state") != "OPEN":
            continue
        if pr.get("reviewDecision") == "APPROVED":
            approved = True
        if pr.get("isDraft", False):
            if state is None:
                state = "draft"
            continue
        # An open, non-draft PR: ready for review.
        if state != "ready":
            state = "ready"
        ok = _rollup_ok(pr)
        ci_ok = ok if ci_ok is None else (ci_ok and ok)
    return state, ci_ok, approved


def _merged_pr(content: dict[str, Any]) -> bool:
    """True when a deliberately-linked PR has merged.

    Keyed off `state == "MERGED"`, equivalently the boolean `merged`: either
    is enough, so a payload carrying only one of the two still scores. This
    completes the ticket even while the issue itself is still OPEN (e.g. a
    spec-branch PR, whose closing keyword GitHub treats as inert) — the job
    self-closes the issue when it detects this.
    """

    for pr in _linked_pr_nodes(content):
        if pr.get("merged") is True or pr.get("state") == "MERGED":
            return True
    return False


def linked_prs_page_info(item: dict[str, Any]) -> tuple[bool, str | None]:
    """`(has_next_page, end_cursor)` for this item's linked-PR connection.

    Read-only structural helper: the job uses it to decide whether to page the
    rest of an issue's `closedByPullRequestsReferences` connection (via
    `ISSUE_LINKED_PRS_QUERY`) when it carries more linked PRs than one page.
    """

    content = item.get("content") or {}
    refs = content.get("closedByPullRequestsReferences") or {}
    page_info = refs.get("pageInfo") or {}
    return bool(page_info.get("hasNextPage")), page_info.get("endCursor")


def extend_item_linked_prs(item: dict[str, Any], nodes: list[dict[str, Any]]) -> None:
    """Append paged linked-PR nodes onto this item's content.

    Lets the job fold a paged linked-PR tail back into the item so the single
    `item_to_facts` read scores the full set. A no-op for a contentless item.
    """

    content = item.get("content")
    if not content:
        return
    refs = content.setdefault("closedByPullRequestsReferences", {"nodes": []})
    refs.setdefault("nodes", []).extend(nodes)


def item_is_archived(item: dict[str, Any]) -> bool:
    """Whether this card is currently archived (hidden from every view)."""

    return bool(item.get("isArchived"))


def item_current_status_option_id(item: dict[str, Any]) -> str | None:
    """The Status single-select option id already set on this card, if any.

    Read-only, like the other structural helpers here. The job compares this
    against the option id it is about to write and skips the mutation when they
    match, so a card that is already in the right column is never re-written
    (no redundant API call, no board flash).
    """

    status = item.get("status") or {}
    return status.get("optionId")


def item_current_stamp_option_ids(item: dict[str, Any]) -> dict[str, str | None]:
    """The option ids currently set on this card's `Map` and `Spec` fields.

    The job diffs these against the computed stamp plan and writes (or
    clears) only what drifted, so a settled board issues no stamp mutations.
    A field with no value reads as `None` — exactly what a clear leaves
    behind and what a vanish wants.
    """

    stamps: dict[str, str | None] = {}
    for key in ("map", "spec"):
        value = item.get(key) or {}
        stamps[key.capitalize()] = value.get("optionId")
    return stamps


def item_content_id(item: dict[str, Any]) -> str | None:
    """The underlying issue/PR's own GraphQL node id, or `None` if contentless.

    This is distinct from the Project item's id: sub-issue children are
    reported by their *content* id, so the job needs this to correlate a
    parent's listed children with the Project items that carry them.
    """

    content = item.get("content")
    if not content:
        return None
    return content.get("id")


def item_child_content_ids(item: dict[str, Any]) -> list[str]:
    """The content ids of this item's native sub-issue children, if any.

    Read-only structural extraction, same as the rest of this module: it does
    not know or care what those children's Status is, only which content ids
    to look up.
    """

    content = item.get("content")
    if not content:
        return []
    sub_issues = content.get("subIssues") or {}
    return [
        node["id"] for node in (sub_issues.get("nodes") or []) if node.get("id")
    ]


def _pr_facts_for_pr_item(content: dict[str, Any]) -> tuple[str | None, bool | None, bool]:
    """A PR card scores its own fields: draft-or-ready, rollup, review decision."""

    if content.get("state") != "OPEN":
        return None, None, False
    if content.get("isDraft", False):
        return "draft", None, False
    return "ready", _rollup_ok(content), content.get("reviewDecision") == "APPROVED"


def item_to_facts(item: dict[str, Any]) -> Facts | None:
    """Map one GraphQL Project item to `Facts`, or `None` if it has no content.

    `None` means "nothing to score" (draft item / invisible content); the job
    skips it. A non-null content of any type (Issue or PullRequest) is mapped:
    every field is read defensively so a partial payload never raises.

    Every PR-derived fact is sourced solely from
    `closedByPullRequestsReferences(userLinkedOnly: false)` for an issue card
    (a closing link — keyword or manual — cross-repo or same-repo alike; no
    allow-list needed, the closing link itself is the guard), and from the
    PR's own fields for a PR card.
    """

    content = item.get("content")
    if not content:
        return None

    labels = _label_names(content)
    assignees = content.get("assignees") or {}
    summary = content.get("issueDependenciesSummary") or {}

    if content.get("__typename") == "PullRequest":
        pr_state, pr_ci_ok, pr_approved = _pr_facts_for_pr_item(content)
        closed = content.get("state") in ("CLOSED", "MERGED") or content.get(
            "merged"
        ) is True
        return make_facts(
            closed=closed,
            open_blocker_count=0,
            assigned=False,
            pr_state=pr_state,
            pr_ci_ok=pr_ci_ok,
            pr_approved=pr_approved,
            is_map=False,
        )

    pr_state, pr_ci_ok, pr_approved = _fold_open_prs(content)
    return make_facts(
        closed=content.get("state") == "CLOSED",
        open_blocker_count=summary.get("blockedBy") or 0,
        assigned=(assignees.get("totalCount") or 0) >= 1,
        pr_state=pr_state,
        pr_ci_ok=pr_ci_ok,
        pr_approved=pr_approved,
        is_map=MAP_LABEL in labels,
        has_merged_linked_pr=_merged_pr(content),
    )

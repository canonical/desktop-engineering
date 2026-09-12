"""The reconcile arm (ticket 33): author missing deliberate PR<->ticket links.

Detection (`facts_mapping`) scores a card off a deliberate native link only,
so it is inert until one exists. This is the arm that rides the existing
full-board sweep so correctness never depends on the immediate arm (ticket
35, not built here) having already fired: it scans a fixed set of
*destination* repos from the **PR side** — an unlinked cross-repo PR is
invisible from the issue side — and authors whichever single link
`link_authoring.pick_link_target` resolves for it, skipping any PR that
already carries a deliberate link and surfacing (never guessing at) an
ambiguous one.

The scan scope is named `AI_PLANNING_LINK_SCAN_REPOS` (see `__main__`) —
deliberately distinct from the detection guard `AI_PLANNING_DESTINATION_REPOS`
that ticket 31 already retired, even though it may hold the same repo list in
practice.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ai_planning.client import SupportsExecute
from ai_planning.link_authoring import (
    TicketCandidate,
    TicketRef,
    parse_candidate_refs,
    pick_link_target,
)
from ai_planning.queries import (
    ADD_CLOSE_ISSUE_REFERENCES_MUTATION,
    ISSUE_BY_NUMBER_QUERY,
    REPO_PRS_QUERY,
)

MAP_SPEC_LABEL = "wayfinder:spec"


@dataclass
class LinkAuthoringResult:
    """What one reconcile-arm pass did, for logging."""

    authored: list[tuple[str, TicketRef]] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    no_candidates: list[str] = field(default_factory=list)


def iter_repo_prs(
    client: SupportsExecute, owner: str, name: str, *, page_size: int = 20
) -> Iterator[dict[str, Any]]:
    """Yield every OPEN or MERGED PR in `owner/name`, cursor-paged."""

    cursor: str | None = None
    while True:
        data = client.execute(
            REPO_PRS_QUERY,
            {"owner": owner, "name": name, "pageSize": page_size, "cursor": cursor},
        )
        prs = ((data.get("repository") or {}).get("pullRequests")) or {}
        yield from prs.get("nodes", [])
        page_info = prs.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return
        cursor = page_info.get("endCursor")


def _already_linked_refs(pr: dict[str, Any]) -> set[TicketRef]:
    """Every ticket this PR already carries a deliberate link to."""

    refs: set[TicketRef] = set()
    for node in (pr.get("closingIssuesReferences") or {}).get("nodes") or []:
        repository = node.get("repository") or {}
        owner = (repository.get("owner") or {}).get("login")
        repo = repository.get("name")
        number = node.get("number")
        if owner and repo and number is not None:
            refs.add(TicketRef(owner=owner, repo=repo, number=number))
    return refs


def resolve_candidate(
    client: SupportsExecute, ref: TicketRef, *, pr_owner: str, pr_repo: str
) -> TicketCandidate | None:
    """Resolve one parsed `TicketRef` to a `TicketCandidate`, or `None` when
    the referenced issue doesn't exist or the token can't see it."""

    data = client.execute(
        ISSUE_BY_NUMBER_QUERY,
        {"owner": ref.owner, "name": ref.repo, "number": ref.number},
    )
    issue = (data.get("repository") or {}).get("issue")
    if issue is None:
        return None
    labels = [node["name"] for node in (issue.get("labels") or {}).get("nodes", [])]
    is_same_repo_spec = (
        MAP_SPEC_LABEL in labels
        and ref.owner == pr_owner
        and ref.repo == pr_repo
    )
    return TicketCandidate(
        ref=ref, node_id=issue["id"], is_same_repo_spec=is_same_repo_spec
    )


def _process_pr(
    client: SupportsExecute,
    result: LinkAuthoringResult,
    pr: dict[str, Any],
    *,
    owner: str,
    name: str,
) -> None:
    """Decide and, if unambiguous and not already linked, author this PR's
    one missing link — folding the outcome into `result` either way."""

    pr_label = f"{owner}/{name}#{pr['number']}"
    refs = parse_candidate_refs(pr.get("body"), default_owner=owner, default_repo=name)
    if not refs:
        result.no_candidates.append(pr_label)
        return

    candidates = [
        candidate
        for ref in refs
        if (candidate := resolve_candidate(client, ref, pr_owner=owner, pr_repo=name))
        is not None
    ]
    target = pick_link_target(candidates)
    if target is None:
        result.ambiguous.append(pr_label)
        return

    if target.ref in _already_linked_refs(pr):
        result.unchanged.append(pr_label)
        return

    client.execute(
        ADD_CLOSE_ISSUE_REFERENCES_MUTATION,
        {"issueId": target.node_id, "pullRequestId": pr["id"]},
    )
    result.authored.append((pr_label, target.ref))


def author_missing_links(
    client: SupportsExecute, destination_repos: list[str], *, page_size: int = 20
) -> LinkAuthoringResult:
    """Scan every destination repo's PRs and author whichever link each one
    is missing (see module docstring for the scan and the shared rule).
    """

    result = LinkAuthoringResult()
    for repo_full_name in destination_repos:
        owner, name = repo_full_name.split("/", 1)
        for pr in iter_repo_prs(client, owner, name, page_size=page_size):
            _process_pr(client, result, pr, owner=owner, name=name)
    return result

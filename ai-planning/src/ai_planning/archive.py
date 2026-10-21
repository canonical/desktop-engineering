"""Manually archive (or restore) the Project cards under a closed Map.

Run on demand from the planning repo's `archive-map.yml` workflow. It walks the
Map's native sub-issue tree at any depth, cross-repo, and archives the Project
card of every descendant, open or closed. Archived cards leave every view of the
board without touching any issue, label or Status, and are restored with the
`unarchive` mode. The Map's own card is left alone.

`plan_archive` is the pure decision; the rest is thin GraphQL I/O.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from ai_planning.boards import BoardsError, parse_boards, select_board
from ai_planning.client import GraphQLClient, SupportsExecute
from ai_planning.queries import (
    ARCHIVE_ITEM_MUTATION,
    ISSUE_ROOT_QUERY,
    ISSUE_SUBTREE_QUERY,
    UNARCHIVE_ITEM_MUTATION,
)

MAP_LABEL = "wayfinder:map"
ARCHIVE = "archive"
UNARCHIVE = "unarchive"

_REF = re.compile(r"^(?:(?P<owner>[\w.-]+)/(?P<name>[\w.-]+))?#?(?P<number>\d+)$")


class ArchiveError(RuntimeError):
    """The requested Map cannot be archived/restored; nothing was changed."""


@dataclass(frozen=True)
class TreeIssue:
    """One issue in the Map's tree and its card on this Project, if any."""

    issue_id: str
    ref: str
    state: str
    item_id: str | None
    archived: bool


@dataclass
class ArchivePlan:
    to_change: list[TreeIssue] = field(default_factory=list)
    already_done: list[TreeIssue] = field(default_factory=list)
    off_board: list[TreeIssue] = field(default_factory=list)


def subtree_item_ids(
    root_item_ids: set[str],
    included_item_ids: set[str],
    item_id_by_content_id: dict[str, str],
    child_content_ids_by_item_id: dict[str, list[str]],
) -> list[str]:
    """Project item ids to archive for the given closed Maps, from board data.

    `root_item_ids` are closed Maps whose own card stays; `included_item_ids`
    are children of an already-archived closed Map, archived along with their
    own descendants. Only cards still on the board can be reached, which is all
    that is left to hide. The result keeps first-visit order and has no repeats.
    """

    found: dict[str, None] = {}
    stack = list(included_item_ids)
    for root in root_item_ids:
        stack.extend(
            item_id_by_content_id[child]
            for child in child_content_ids_by_item_id.get(root, [])
            if child in item_id_by_content_id
        )
    while stack:
        item_id = stack.pop()
        if item_id in found or item_id in root_item_ids:
            continue
        found[item_id] = None
        stack.extend(
            item_id_by_content_id[child]
            for child in child_content_ids_by_item_id.get(item_id, [])
            if child in item_id_by_content_id
        )
    return list(found)


def archive_item(client: SupportsExecute, project_id: str, item_id: str) -> None:
    client.execute(
        ARCHIVE_ITEM_MUTATION, {"projectId": project_id, "itemId": item_id}
    )


def restore_tree(
    client: SupportsExecute, project_id: str, root_issue_id: str
) -> list[TreeIssue]:
    """Unarchive every archived card below the root issue; return those restored."""

    plan = plan_archive(
        collect_descendants(client, project_id, root_issue_id), UNARCHIVE
    )
    for issue in plan.to_change:
        client.execute(
            UNARCHIVE_ITEM_MUTATION,
            {"projectId": project_id, "itemId": issue.item_id},
        )
    return plan.to_change


def parse_map_ref(value: str, default_repo: str) -> tuple[str, str, int]:
    """Accept `123`, `#123` or `owner/repo#123`; bare numbers use `default_repo`."""

    match = _REF.match(value.strip())
    if match is None:
        raise ArchiveError(f"cannot parse map reference {value!r}")
    owner, name = match["owner"], match["name"]
    if owner is None:
        owner, name = default_repo.split("/", 1)
    return owner, name, int(match["number"])


def plan_archive(descendants: list[TreeIssue], mode: str) -> ArchivePlan:
    """Decide what to do with each descendant card.

    Archive hides every card that is still visible; unarchive restores every
    archived one. Issues without a card on this Project are only reported.
    """

    plan = ArchivePlan()
    for issue in descendants:
        if issue.item_id is None:
            plan.off_board.append(issue)
        elif issue.archived == (mode == ARCHIVE):
            plan.already_done.append(issue)
        else:
            plan.to_change.append(issue)
    return plan


def fetch_root(
    client: SupportsExecute, owner: str, name: str, number: int
) -> dict[str, Any]:
    data = client.execute(
        ISSUE_ROOT_QUERY, {"owner": owner, "name": name, "number": number}
    )
    issue = (data.get("repository") or {}).get("issue")
    if issue is None:
        raise ArchiveError(f"{owner}/{name}#{number} not found or not visible")
    return issue


def _fetch_children(
    client: SupportsExecute, issue_id: str, project_id: str
) -> tuple[TreeIssue, list[str]]:
    children: list[str] = []
    cursor: str | None = None
    while True:
        node = client.execute(
            ISSUE_SUBTREE_QUERY, {"issueId": issue_id, "subCursor": cursor}
        )["node"]
        children += [child["id"] for child in node["subIssues"]["nodes"]]
        page = node["subIssues"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]

    card = next(
        (
            item
            for item in node["projectItems"]["nodes"]
            if item["project"]["id"] == project_id
        ),
        None,
    )
    issue = TreeIssue(
        issue_id=node["id"],
        ref=f"{node['repository']['nameWithOwner']}#{node['number']}",
        state=node["state"],
        item_id=card["id"] if card else None,
        archived=bool(card and card["isArchived"]),
    )
    return issue, children


def collect_descendants(
    client: SupportsExecute, project_id: str, root_issue_id: str
) -> list[TreeIssue]:
    """Every issue below the root, at any depth (the root itself excluded)."""

    seen = {root_issue_id}
    found: list[TreeIssue] = []
    stack = [root_issue_id]
    while stack:
        _, children = _fetch_children(client, stack.pop(), project_id)
        for child_id in children:
            if child_id in seen:
                continue
            seen.add(child_id)
            issue, _ = _fetch_children(client, child_id, project_id)
            found.append(issue)
            stack.append(child_id)
    return found


def run_archive(
    client: SupportsExecute,
    project_id: str,
    map_ref: tuple[str, str, int],
    *,
    mode: str = ARCHIVE,
    dry_run: bool = False,
) -> ArchivePlan:
    root = fetch_root(client, *map_ref)
    ref = f"{map_ref[0]}/{map_ref[1]}#{map_ref[2]}"
    labels = {label["name"] for label in root["labels"]["nodes"]}
    if MAP_LABEL not in labels:
        raise ArchiveError(f"{ref} is not a Map (missing {MAP_LABEL})")
    if mode == ARCHIVE and root["state"] != "CLOSED":
        raise ArchiveError(f"{ref} is still open; close the Map first")

    plan = plan_archive(collect_descendants(client, project_id, root["id"]), mode)
    if not dry_run:
        mutation = ARCHIVE_ITEM_MUTATION if mode == ARCHIVE else UNARCHIVE_ITEM_MUTATION
        for issue in plan.to_change:
            client.execute(
                mutation, {"projectId": project_id, "itemId": issue.item_id}
            )
    return plan


def main() -> int:
    token = os.environ.get("AI_PLANNING_TOKEN")
    board_slug = os.environ.get("AI_PLANNING_BOARD")
    planning_repo = os.environ.get("AI_PLANNING_REPO")
    map_value = os.environ.get("AI_PLANNING_MAP")
    mode = os.environ.get("AI_PLANNING_ARCHIVE_MODE", ARCHIVE)
    dry_run = os.environ.get("AI_PLANNING_DRY_RUN", "").lower() in {"1", "true"}
    if not (token and board_slug and planning_repo and map_value):
        print(
            "set AI_PLANNING_TOKEN, AI_PLANNING_BOARDS, AI_PLANNING_BOARD, "
            "AI_PLANNING_REPO and AI_PLANNING_MAP",
            file=sys.stderr,
        )
        return 2
    try:
        project_id = select_board(
            parse_boards(os.environ.get("AI_PLANNING_BOARDS")), board_slug
        ).project_id
    except BoardsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if mode not in {ARCHIVE, UNARCHIVE}:
        print(f"unknown mode {mode!r} (archive|unarchive)", file=sys.stderr)
        return 2

    try:
        plan = run_archive(
            GraphQLClient.with_token(token),
            project_id,
            parse_map_ref(map_value, planning_repo),
            mode=mode,
            dry_run=dry_run,
        )
    except ArchiveError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    verb = f"would {mode}" if dry_run else f"{mode}d"
    for issue in plan.to_change:
        print(f"{verb} {issue.ref}")
    print(
        f"changed={len(plan.to_change)} already={len(plan.already_done)} "
        f"off_board={len(plan.off_board)}"
        f"{' dry_run=1' if dry_run else ''}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

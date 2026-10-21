"""Keep a Map's tree hidden or visible in step with the Map's own card.

An archived Map card means "this effort is hidden", so its whole tree is
archived with it; restoring the Map card restores the tree. GitHub raises no
event when a Project card is archived or restored, so the sweep infers it from
what it can see — only active cards — plus one marker on the Map issue, the
`wayfinder:archived` label, meaning "this Map's tree was archived by the sweep".

For each Map the sweep can see (its card is active):

* closed, no marker   -> just finished: archive its tree, then its own card, then
  add the marker;
* closed, marker      -> the user restored it: if any child is no longer visible,
  restore the archived tree (the marker stays so it is not hidden again);
* open, marker        -> it was reopened: restore the tree and remove the marker.

For a closed Map whose own card is archived (so the sweep cannot see it), any
visible child of it is archived with its subtree and the Map gets the marker. A
Map with no marker label available in its repo is left alone, never half-handled.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from ai_planning.archive import archive_item, restore_tree, subtree_item_ids
from ai_planning.client import SupportsExecute
from ai_planning.queries import (
    ADD_LABEL_MUTATION,
    LABEL_ID_QUERY,
    REMOVE_LABEL_MUTATION,
)

ARCHIVED_LABEL = "wayfinder:archived"
MAP_LABEL = "wayfinder:map"


@dataclass
class VisibilityResult:
    archived: list[str] = field(default_factory=list)  # Project item ids
    restored: list[str] = field(default_factory=list)  # issue node ids
    labeled: list[str] = field(default_factory=list)  # Map issue node ids
    unlabeled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # Map issue node ids


def _label_names(labels: dict[str, Any] | None) -> set[str]:
    return {node["name"] for node in (labels or {}).get("nodes") or []}


def closed_archived_map_parent(
    item: dict[str, Any], project_id: str
) -> tuple[str, str] | None:
    """`(content id, repo)` of this item's parent when it is a closed Map whose
    card on this Project is archived, else None."""

    parent = (item.get("content") or {}).get("parent") or {}
    if parent.get("state") != "CLOSED" or MAP_LABEL not in _label_names(
        parent.get("labels")
    ):
        return None
    cards = [
        card
        for card in (parent.get("projectItems") or {}).get("nodes") or []
        if (card.get("project") or {}).get("id") == project_id
    ]
    if not cards or not all(card.get("isArchived") for card in cards):
        return None
    return parent["id"], (parent.get("repository") or {}).get("nameWithOwner", "")


class _Marker:
    """Adds/removes the marker label, caching each repo's label id."""

    def __init__(self, client: SupportsExecute) -> None:
        self._client = client
        self._ids: dict[str, str | None] = {}

    def label_id(self, repo: str) -> str | None:
        if repo not in self._ids:
            owner, _, name = repo.partition("/")
            data = self._client.execute(
                LABEL_ID_QUERY, {"owner": owner, "name": name, "label": ARCHIVED_LABEL}
            )
            label = (data.get("repository") or {}).get("label")
            self._ids[repo] = label["id"] if label else None
        return self._ids[repo]

    def add(self, issue_id: str, repo: str) -> None:
        self._client.execute(
            ADD_LABEL_MUTATION, {"issueId": issue_id, "labelId": self.label_id(repo)}
        )

    def remove(self, issue_id: str, repo: str) -> None:
        self._client.execute(
            REMOVE_LABEL_MUTATION,
            {"issueId": issue_id, "labelId": self.label_id(repo)},
        )


def reconcile_map_visibility(
    client: SupportsExecute,
    project_id: str,
    *,
    items_by_id: dict[str, dict[str, Any]],
    item_order: list[str],
    closed_map_item_ids: set[str],
    open_map_item_ids: set[str],
    item_id_by_content_id: dict[str, str],
    child_content_ids_by_item_id: dict[str, list[str]],
) -> VisibilityResult:
    result = VisibilityResult()
    marker = _Marker(client)
    done: set[str] = set()

    def content(item_id: str) -> dict[str, Any]:
        return items_by_id[item_id]["content"]

    def repo_of(item_id: str) -> str:
        return (content(item_id).get("repository") or {}).get("nameWithOwner", "")

    def has_marker(item_id: str) -> bool:
        return ARCHIVED_LABEL in _label_names(content(item_id).get("labels"))

    def archive_all(item_ids: list[str]) -> None:
        for item_id in item_ids:
            if item_id not in done:
                done.add(item_id)
                archive_item(client, project_id, item_id)
                result.archived.append(item_id)

    def restore(map_item_id: str) -> None:
        for issue in restore_tree(client, project_id, content(map_item_id)["id"]):
            result.restored.append(issue.issue_id)

    for item_id in item_order:
        if item_id not in closed_map_item_ids and item_id not in open_map_item_ids:
            continue
        if item_id not in items_by_id:
            continue
        map_issue_id = content(item_id)["id"]
        repo = repo_of(item_id)

        if item_id in open_map_item_ids:
            if has_marker(item_id):
                restore(item_id)
                if marker.label_id(repo):
                    marker.remove(map_issue_id, repo)
                    result.unlabeled.append(map_issue_id)
            continue

        if has_marker(item_id):
            children = child_content_ids_by_item_id.get(item_id, [])
            if any(child not in item_id_by_content_id for child in children):
                restore(item_id)
            continue

        if not marker.label_id(repo):
            print(
                f"warning: label {ARCHIVED_LABEL!r} missing in {repo}; "
                f"not archiving the tree of {map_issue_id}",
                file=sys.stderr,
            )
            result.skipped.append(map_issue_id)
            continue
        archive_all(
            subtree_item_ids(
                {item_id}, set(), item_id_by_content_id, child_content_ids_by_item_id
            )
        )
        archive_all([item_id])
        marker.add(map_issue_id, repo)
        result.labeled.append(map_issue_id)

    # Closed Maps whose own card is already archived: hide any visible children.
    children_by_parent: dict[tuple[str, str], set[str]] = {}
    for item_id in item_order:
        parent = closed_archived_map_parent(items_by_id.get(item_id) or {}, project_id)
        if parent is not None:
            children_by_parent.setdefault(parent, set()).add(item_id)
    for (parent_id, repo), children in children_by_parent.items():
        archive_all(
            subtree_item_ids(
                set(), children, item_id_by_content_id, child_content_ids_by_item_id
            )
        )
        if marker.label_id(repo):
            marker.add(parent_id, repo)
            result.labeled.append(parent_id)

    return result

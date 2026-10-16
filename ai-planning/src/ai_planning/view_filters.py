"""Pure helpers for keeping map-completion filters on the Board view."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


# The sync owns negative parent-issue qualifiers on the Board view. Keep every
# other user-authored filter term intact while replacing the generated set.
_NEGATED_PARENT_ISSUE_FILTER = re.compile(r"(?<!\S)-parent-issue:\S+")


def closed_map_parent_issue_refs(
    closed_map_item_ids: Iterable[str],
    item_id_by_content_id: Mapping[str, str],
    child_content_ids_by_item_id: Mapping[str, list[str]],
    issue_ref_by_item_id: Mapping[str, str],
) -> set[str]:
    """Return each parent issue ref needed to hide a closed Map's full subtree.

    Projects filter by a sub-issue's *immediate* parent. Include every node in
    the closed Map's tree that itself has children (the Map and any nested specs
    or maps), so grandchildren and deeper descendants are hidden as well.
    ``compute_map_cascade`` ensures a Map stays closed only while its known
    descendants are closed; if one reopens, the Map is reopened before this
    function is called.
    """

    parent_refs: set[str] = set()

    for root_item_id in closed_map_item_ids:
        stack = [root_item_id]
        visited: set[str] = set()

        while stack:
            parent_item_id = stack.pop()
            if parent_item_id in visited:
                continue
            visited.add(parent_item_id)

            child_content_ids = child_content_ids_by_item_id.get(parent_item_id, [])
            if child_content_ids:
                issue_ref = issue_ref_by_item_id.get(parent_item_id)
                if issue_ref is None:
                    raise ValueError(
                        "cannot build closed-map filter: missing issue reference "
                        f"for parent project item {parent_item_id}"
                    )
                parent_refs.add(issue_ref)

            for child_content_id in child_content_ids:
                child_item_id = item_id_by_content_id.get(child_content_id)
                if child_item_id is not None and child_item_id not in visited:
                    stack.append(child_item_id)

    return parent_refs


def board_filter_for_closed_maps(
    current_filter: str | None, parent_issue_refs: Iterable[str]
) -> str:
    """Replace generated Map parent exclusions, preserving other Board filters."""

    base_filter = _NEGATED_PARENT_ISSUE_FILTER.sub("", current_filter or "")
    base_filter = " ".join(base_filter.split())

    exclusions = []
    for issue_ref in sorted(set(parent_issue_refs)):
        if any(character.isspace() or character in '"\r\n' for character in issue_ref):
            raise ValueError(f"invalid issue reference for project filter: {issue_ref!r}")
        exclusions.append(f'-parent-issue:"{issue_ref}"')

    return " ".join(part for part in (base_filter, *exclusions) if part)

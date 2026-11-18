"""Ensure the board can carry the design: columns, stamp fields, views.

The sweep runs this before anything else, so a board predating the design —
or a brand-new one — converges on the first run with no hand configuration
beyond the three native-workflow toggles (UI-only, printed by the setup).
Everything here is idempotent and **identity-preserving**: an option that
already exists is always sent back WITH its id, which GitHub honours as "same
option" — item values survive (verified live; an option rewrite without ids
re-creates every option and wipes the values).

- **Status** — the six ladder columns, exact names, in order, each with its
  one-line description. Matched by name (the vocabulary is fixed), refreshed
  when a description drifts, and missing options (e.g. Approved on a board
  from the five-column era) are appended in the right position by rewriting
  the full ordered list with ids.
- **Map / Spec** — the stamp fields, created lazily: only when the sweep has
  discovered at least one map (resp. spec) to put in them, so a fresh board
  never grows an empty field or a placeholder option. New maps/specs append
  one option each (`<title> #<number>`); a renamed map or spec renames its
  option in place — the option's identity is pinned by the option id already
  set on the map's (or spec's) own card, so a rename never orphans a value.
- **Views** — Maps (board, `-no:map`), Efforts (table, `is:issue`) and Specs
  (board, `-no:spec`), ensured by name with their filters and visible
  fields. The API sets no slice, so the slice-by field stays a one-time hand
  click (Map / Parent issue / Spec) that the setup output calls out.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from ai_planning.client import SupportsExecute
from ai_planning.queries import (
    CREATE_SINGLE_SELECT_FIELD_MUTATION,
    CREATE_VIEW_MUTATION,
    FIELD_BY_NAME_QUERY,
    PROJECT_FIELDS_QUERY,
    PROJECT_VIEWS_QUERY,
    UPDATE_FIELD_OPTIONS_MUTATION,
    UPDATE_VIEW_MUTATION,
)

BOARD_LAYOUT = "BOARD_LAYOUT"
TABLE_LAYOUT = "TABLE_LAYOUT"

# The six ladder columns, in order, exactly as designed. (name, color, description)
STATUS_OPTIONS: list[dict[str, str]] = [
    {
        "name": "Blocked",
        "color": "RED",
        "description": "Open blockers; nothing claimed, no PR yet.",
    },
    {
        "name": "Ready",
        "color": "GRAY",
        "description": "Unclaimed, unblocked — claim it.",
    },
    {
        "name": "In progress",
        "color": "YELLOW",
        "description": "Claimed ticket, or PR open as draft (agent watches CI).",
    },
    {
        "name": "In review",
        "color": "BLUE",
        "description": "PR ready: CI green; awaiting human review.",
    },
    {
        "name": "Approved",
        "color": "PURPLE",
        "description": "PR approved — human merges next (stacks: bottom-up).",
    },
    {
        "name": "Done",
        "color": "GREEN",
        "description": "Merged or closed; nothing to act on.",
    },
]

# The three views, ensured by name. (name, layout, filter, visible-field names)
WANTED_VIEWS: list[dict[str, Any]] = [
    {
        "name": "Maps",
        "layout": BOARD_LAYOUT,
        "filter": "label:wayfinder:map",
        "fields": ["Title", "Assignees", "Status", "Labels", "Spec", "Sub-issues progress"],
    },
    {
        "name": "Efforts",
        "layout": TABLE_LAYOUT,
        "filter": "is:issue",
        "fields": [
            "Title",
            "Status",
            "Labels",
            "Map",
            "Spec",
            "Sub-issues progress",
            "Updated",
        ],
    },
    {
        "name": "Specs",
        "layout": BOARD_LAYOUT,
        "filter": "-label:wayfinder:map",
        "fields": ["Title", "Assignees", "Status", "Labels", "Map", "Sub-issues progress"],
    },
]


@dataclass
class BoardShape:
    """What the shape pass established, for the sweep's writes."""

    status_field_id: str
    status_option_ids: dict[str, str]
    map_field_id: str | None = None
    map_option_ids: dict[str, str] = field(default_factory=dict)
    spec_field_id: str | None = None
    spec_option_ids: dict[str, str] = field(default_factory=dict)
    status_options_changed: bool = False
    fields_created: list[str] = field(default_factory=list)
    views_created: list[str] = field(default_factory=list)
    views_updated: list[str] = field(default_factory=list)


def _field_by_name(
    client: SupportsExecute, project_id: str, name: str
) -> dict[str, Any] | None:
    data = client.execute(
        FIELD_BY_NAME_QUERY, {"projectId": project_id, "fieldName": name}
    )
    return (data.get("node") or {}).get("field")


def _options_of(field_node: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not field_node:
        return []
    return field_node.get("options") or []


def _merged_option_input(
    current: list[dict[str, Any]], wanted: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """The full ordered option list to send: wanted order, identities kept.

    An existing option (matched by name) is passed back with its id and any
    refreshed description; a wanted option no current option carries is
    appended without an id (created). Unwanted existing options are dropped
    from the list — for Status the wanted set is closed, so this never
    fires; stamp fields are grown, never shrunk, by their callers.
    """

    by_name = {option["name"]: option for option in current}
    merged: list[dict[str, Any]] = []
    for entry in wanted:
        existing = by_name.get(entry["name"])
        input_option: dict[str, Any] = {
            "name": entry["name"],
            "color": entry.get("color", "GRAY"),
            "description": entry.get("description", ""),
        }
        if existing is not None:
            input_option["id"] = existing["id"]
        merged.append(input_option)
    return merged


def ensure_status_options(
    client: SupportsExecute, project_id: str
) -> tuple[str, dict[str, str], bool]:
    """The Status field's id, its name->option-id map, and whether it changed.

    Rewrites the option list only when something drifted (a missing column,
    a stale description); the rewrite carries every existing id, so card
    values survive.
    """

    field_node = _field_by_name(client, project_id, "Status")
    if field_node is None:
        raise RuntimeError("the Project has no Status field")
    current = _options_of(field_node)
    current_by_name = {option["name"]: option for option in current}
    drifted = len(current) != len(STATUS_OPTIONS) or any(
        (existing := current_by_name.get(entry["name"])) is None
        or existing.get("description") != entry["description"]
        for entry in STATUS_OPTIONS
    )
    if drifted:
        data = client.execute(
            UPDATE_FIELD_OPTIONS_MUTATION,
            {
                "fieldId": field_node["id"],
                "options": _merged_option_input(current, STATUS_OPTIONS),
            },
        )
        field_node = (
            ((data.get("updateProjectV2Field") or {}).get("projectV2Field")) or {}
        )
        current = _options_of(field_node)
    option_ids = {option["name"]: option["id"] for option in current}
    return field_node["id"], option_ids, drifted


def _grow_options(
    client: SupportsExecute,
    project_id: str,
    name: str,
    field_node: dict[str, Any] | None,
    entries: list[dict[str, str]],
    identity_by_key: dict[str, str | None],
) -> tuple[str | None, dict[str, str], bool]:
    """Ensure `entries` all exist as options of field `name`; return ids by key.

    `entries` are `{key, name, color}` — the key is the map/spec content id
    the option belongs to. `identity_by_key` pins an entry to an existing
    option id (the id already set on that map's or spec's own card), so a
    renamed entry updates its option in place instead of spawning a second
    one. Entries whose name matches no existing option and carries no pinned
    identity are appended (created).

    Returns `(field_id, option_id_by_key, changed)`; `field_id` is None only
    when the field does not exist and there is nothing to put in it yet.
    """

    if not entries and field_node is None:
        return None, {}, False
    current = _options_of(field_node)
    by_id = {option["id"]: option for option in current}
    by_name = {option["name"]: option for option in current}
    # NOTE: no copies — `merged` must alias `current`'s dicts so a rename
    # applied through `by_id`/`by_name` below is what the update sends.
    merged: list[dict[str, Any]] = list(current)
    changed = False
    option_id_by_key: dict[str, str] = {}
    for entry in entries:
        key, name_wanted = entry["key"], entry["name"]
        pinned_id = identity_by_key.get(key)
        existing = (
            by_id.get(pinned_id)
            if pinned_id
            else by_name.get(name_wanted)
        )
        if existing is None:
            merged.append(
                {
                    "name": name_wanted,
                    "color": entry.get("color", "GRAY"),
                    "description": entry.get("description", ""),
                }
            )
            changed = True
        elif existing.get("name") != name_wanted:
            existing["name"] = name_wanted
            changed = True
    if field_node is None:
        data = client.execute(
            CREATE_SINGLE_SELECT_FIELD_MUTATION,
            {
                "projectId": project_id,
                "fieldName": name,
                "options": [
                    {
                        "name": option["name"],
                        "color": option.get("color", "GRAY"),
                        "description": option.get("description", ""),
                    }
                    for option in merged
                ],
            },
        )
        field_node = (
            (data.get("createProjectV2Field") or {}).get("projectV2Field") or {}
        )
        current = _options_of(field_node)
        by_name = {option["name"]: option for option in current}
        changed = False  # the create carried everything; nothing further drifted
    elif changed:
        data = client.execute(
            UPDATE_FIELD_OPTIONS_MUTATION,
            {
                "fieldId": field_node["id"],
                "options": [
                    {
                        key: option[key]
                        for key in ("id", "name", "color", "description")
                        if key in option and option[key] is not None
                    }
                    for option in merged
                ],
            },
        )
        current = _options_of(
            (data.get("updateProjectV2Field") or {}).get("projectV2Field") or {}
        )
        by_name = {option["name"]: option for option in current}
    name_to_id = {option["name"]: option["id"] for option in current}
    for entry in entries:
        option_id = name_to_id.get(entry["name"])
        if option_id is not None:
            option_id_by_key[entry["key"]] = option_id
    return (field_node or {}).get("id"), option_id_by_key, changed


def ensure_stamp_fields(
    client: SupportsExecute,
    project_id: str,
    map_entries: list[dict[str, str]],
    spec_entries: list[dict[str, str]],
    map_identity: dict[str, str | None],
    spec_identity: dict[str, str | None],
) -> tuple[str | None, dict[str, str], str | None, dict[str, str], list[str]]:
    """Ensure the Map and Spec fields carry one option per live map/spec.

    Returns `(map_field_id, map_option_id_by_key, spec_field_id,
    spec_option_id_by_key, created_field_names)`. Either field is created
    lazily — only when there is at least one entry for it.
    """

    created: list[str] = []
    map_node = _field_by_name(client, project_id, "Map")
    spec_node = _field_by_name(client, project_id, "Spec")
    map_created = map_node is None and bool(map_entries)
    spec_created = spec_node is None and bool(spec_entries)
    map_field_id, map_ids, _ = _grow_options(
        client, project_id, "Map", map_node, map_entries, map_identity
    )
    spec_field_id, spec_ids, _ = _grow_options(
        client, project_id, "Spec", spec_node, spec_entries, spec_identity
    )
    if map_created:
        created.append("Map")
    if spec_created:
        created.append("Spec")
    return map_field_id, map_ids, spec_field_id, spec_ids, created


def _field_ids_by_name(
    client: SupportsExecute, project_id: str
) -> dict[str, str]:
    """Every field of the project, name -> node id (one read, reused)."""

    data = client.execute(PROJECT_FIELDS_QUERY, {"projectId": project_id})
    nodes = ((data.get("node") or {}).get("fields") or {}).get("nodes") or []
    if ((data.get("node") or {}).get("fields") or {}).get("pageInfo", {}).get(
        "hasNextPage"
    ):
        print(
            "warning: the project has more fields than one page — visible"
            " fields beyond it are not resolvable",
            file=sys.stderr,
        )
    return {node.get("name"): node["id"] for node in nodes if node.get("id")}


def ensure_views(
    client: SupportsExecute, project_id: str
) -> tuple[list[str], list[str]]:
    """Ensure the three views exist with their filters and visible fields.

    Returns `(created_names, updated_names)`. The slice-by field is UI-only
    and never set here. Views are read across all pages (a long-lived
    project accumulates views; matching against one page would re-create
    duplicates every sweep).
    """

    by_name: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    while True:
        data = client.execute(
            PROJECT_VIEWS_QUERY,
            {"projectId": project_id, "pageSize": 50, "cursor": cursor},
        )
        views = (data.get("node") or {}).get("views") or {}
        for view in views.get("nodes") or []:
            by_name[view["name"]] = view
        page_info = views.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    field_ids_by_name = _field_ids_by_name(client, project_id)
    created: list[str] = []
    updated: list[str] = []
    for wanted in WANTED_VIEWS:
        view = by_name.get(wanted["name"])
        if view is None:
            data = client.execute(
                CREATE_VIEW_MUTATION,
                {"projectId": project_id, "name": wanted["name"], "layout": wanted["layout"]},
            )
            view = (data.get("createProjectV2View") or {}).get("projectV2View") or {}
            if not view.get("id"):
                print(
                    f"warning: could not create the {wanted['name']!r} view"
                    " (GitHub returned no view); the next sweep retries",
                    file=sys.stderr,
                )
                continue
            created.append(wanted["name"])
        field_ids = [
            field_ids_by_name[name] for name in wanted["fields"] if name in field_ids_by_name
        ]
        current_names = [
            node.get("name")
            for node in ((view.get("fields") or {}).get("nodes") or [])
        ]
        # Order-insensitive: GitHub may hand the visible fields back in its own
        # order; what matters is that the wanted set is all there.
        drifted = view.get("filter") != wanted["filter"] or (
            field_ids and sorted(current_names) != sorted(wanted["fields"])
        )
        if drifted and view.get("id"):
            client.execute(
                UPDATE_VIEW_MUTATION,
                {
                    "viewId": view["id"],
                    "filter": wanted["filter"],
                    "visibleFieldIds": field_ids or None,
                },
            )
            if wanted["name"] not in created:
                updated.append(wanted["name"])
    return created, updated


def ensure_board_shape(client: SupportsExecute, project_id: str) -> BoardShape:
    """One idempotent pass that leaves the board able to carry the design."""

    shape = BoardShape(status_field_id="", status_option_ids={})
    (
        shape.status_field_id,
        shape.status_option_ids,
        shape.status_options_changed,
    ) = ensure_status_options(client, project_id)
    return shape

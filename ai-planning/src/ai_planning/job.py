"""The sync job: shape the board, card the work, stamp it, score it, write it.

One event-driven sweep reconciles the whole board from live GitHub facts:

    pass 0  seed the board — the repo's open agent-vocabulary issues, plus
            their transitive native sub-issues, so no agent ever item-adds
    shape   ensure the board can carry the design (Status columns, the Map
            and Spec stamp fields, the three views) — idempotent, and
            identity-preserving (existing options are always sent back with
            their ids, so card values never wipe)
    card    the repo's open PRs: a spec PR (head `<spec-slug>/base`) and
            every PR whose base chain bottoms out in a spec branch (ticket
            PRs and the fix PRs stacked above them) become cards; standalone
            PRs into main do not
    type    every issue card is typed by labels and tree position (map,
            phase-1 decision ticket, spec, implementation ticket) — see
            `card_model`
    stamp   compute each card's Map/Spec stamps and write only the drift —
            a ticket whose own PR is open loses the stamps that would place
            it beside that PR (the vanish, self-healing on the PR's close)
    score   two passes: leaves first, then parents with their children's
            synced statuses rolled up; the ladder is CI-aware (a ready PR
            with red checks stays In progress) and tops out at Approved
    write   statuses, then the reconcile arms: self-close a ticket whose
            linked PR merged, cascade maps whose subtrees settled, and
            archive every closed card (and unarchive on reopen) so nothing
            Done lingers on any view

The sync runs in two passes so a parent's child roll-up (`Facts.
child_started_count`) reflects its children's *synced* Status, not their raw
facts. `sync_status` stays pure; the job owns the ordering.

Maps get no Status written. Items with no content (draft items / invisible
issues) are skipped. A map auto-closes and reopens by `compute_map_cascade`,
a pure reducer over each map's native sub-issue subtree.

Nothing is deployed in any code repo: a PR's facts are reached remotely
through the same GraphQL client.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from ai_planning.card_model import (
    CardType,
    StampPlan,
    compute_stamps,
    is_map_content,
    is_phase1_content,
    is_spec_pr,
    stack_family_pr_numbers,
    type_issue_card,
)
from ai_planning.client import SupportsExecute
from ai_planning.shape import (
    BoardShape,
    ensure_board_shape,
    ensure_stamp_fields,
    ensure_views,
)
from ai_planning.sync_status import Facts, Status, sync_status
from ai_planning.facts_mapping import (
    extend_item_linked_prs,
    extend_item_sub_issues,
    item_child_content_ids,
    item_content_id,
    item_current_stamp_option_ids,
    item_current_status_option_id,
    item_is_archived,
    linked_prs_page_info,
    sub_issues_page_info,
    item_to_facts,
)
from ai_planning.queries import (
    ADD_ITEM_MUTATION,
    ARCHIVE_ITEM_MUTATION,
    CLEAR_FIELD_VALUE_MUTATION,
    CLOSE_ISSUE_MUTATION,
    ISSUE_LINKED_PRS_QUERY,
    ISSUE_SUB_ISSUES_QUERY,
    PROJECT_ITEM_QUERY,
    PROJECT_ITEMS_QUERY,
    REOPEN_ISSUE_MUTATION,
    REPO_ISSUES_QUERY,
    UNARCHIVE_ITEM_MUTATION,
    UPDATE_STATUS_MUTATION,
)


@dataclass(frozen=True)
class StatusField:
    """A single-select field: its node id and name -> option-id lookup."""

    field_id: str
    option_ids: dict[str, str]

    def option_id_for(self, status: Status) -> str:
        return self.option_ids[status.value]


@dataclass
class SyncResult:
    """What one sync pass did, for logging."""

    seeded: list[str] = field(default_factory=list)
    pr_cards_added: list[str] = field(default_factory=list)
    status_written: list[tuple[str, Status]] = field(default_factory=list)
    status_unchanged: list[tuple[str, Status]] = field(default_factory=list)
    stamps_set: list[tuple[str, str]] = field(default_factory=list)
    stamps_cleared: list[tuple[str, str]] = field(default_factory=list)
    fields_created: list[str] = field(default_factory=list)
    options_grown: list[str] = field(default_factory=list)
    views_created: list[str] = field(default_factory=list)
    views_updated: list[str] = field(default_factory=list)
    skipped_maps: list[str] = field(default_factory=list)
    skipped_contentless: list[str] = field(default_factory=list)
    closed_issues: list[str] = field(default_factory=list)
    map_closed: list[str] = field(default_factory=list)
    map_reopened: list[str] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)
    unarchived: list[str] = field(default_factory=list)


def fetch_status_field(
    client: SupportsExecute, project_id: str
) -> StatusField:
    """The Status field as a `StatusField`, after the shape pass ran."""

    shape = ensure_board_shape(client, project_id)
    return StatusField(shape.status_field_id, shape.status_option_ids)


def iter_project_items(
    client: SupportsExecute, project_id: str, *, page_size: int = 50
) -> Iterator[dict[str, Any]]:
    """Yield every Project item, following GraphQL cursor pagination."""

    cursor: str | None = None
    while True:
        data = client.execute(
            PROJECT_ITEMS_QUERY,
            {"projectId": project_id, "pageSize": page_size, "cursor": cursor},
        )
        items = (data.get("node") or {}).get("items") or {}
        yield from items.get("nodes", [])
        page_info = items.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return
        cursor = page_info.get("endCursor")


def set_field_option(
    client: SupportsExecute,
    project_id: str,
    item_id: str,
    field_id: str,
    option_id: str,
) -> None:
    """Set one single-select field (Status, Map or Spec) on a card."""

    client.execute(
        UPDATE_STATUS_MUTATION,
        {
            "projectId": project_id,
            "itemId": item_id,
            "fieldId": field_id,
            "optionId": option_id,
        },
    )


def clear_field(
    client: SupportsExecute, project_id: str, item_id: str, field_id: str
) -> None:
    """Clear one field's value on a card (the vanish)."""

    client.execute(
        CLEAR_FIELD_VALUE_MUTATION,
        {"projectId": project_id, "itemId": item_id, "fieldId": field_id},
    )


def write_status(
    client: SupportsExecute,
    project_id: str,
    item_id: str,
    status_field: StatusField,
    status: Status,
) -> None:
    """Write one synced Status onto a card as its single-select option."""

    set_field_option(
        client,
        project_id,
        item_id,
        status_field.field_id,
        status_field.option_id_for(status),
    )


def iter_repo_open_issues(
    client: SupportsExecute,
    owner: str,
    name: str,
    *,
    page_size: int = 50,
) -> Iterator[dict[str, Any]]:
    """Yield `{id, labels}` for every OPEN issue in `owner/name`.

    One unlabelled scan: the caller filters by label union client-side (the
    per-label variant paged the repo once per label to end at the same
    union). Labels ride along for exactly that filter.
    """

    cursor: str | None = None
    while True:
        data = client.execute(
            REPO_ISSUES_QUERY,
            {
                "owner": owner,
                "name": name,
                "pageSize": page_size,
                "cursor": cursor,
            },
        )
        issues = (data.get("repository") or {}).get("issues") or {}
        for node in issues.get("nodes", []):
            if node.get("id"):
                yield {
                    "id": node["id"],
                    "labels": [
                        label["name"]
                        for label in (node.get("labels") or {}).get("nodes", [])
                        if label.get("name")
                    ],
                }
        page_info = issues.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return
        cursor = page_info.get("endCursor")


def add_item(client: SupportsExecute, project_id: str, content_id: str) -> str:
    """Add one issue/PR (by content id) to the Project; idempotent on GitHub.

    Returns the Project *item* node id — for a content already carded, GitHub
    returns the existing item — so the caller can read that item back directly
    even before the eventually-consistent board list reflects the add.
    """

    data = client.execute(
        ADD_ITEM_MUTATION, {"projectId": project_id, "contentId": content_id}
    )
    return ((data.get("addProjectV2ItemById") or {}).get("item") or {})["id"]


def fetch_project_item(
    client: SupportsExecute, item_id: str
) -> dict[str, Any] | None:
    """Read a single Project item by its item node id, or None if it's gone.

    A read by item id is consistent immediately after `add_item`, unlike the
    paged board list, so the job uses this to sync a just-seeded card the
    re-read hasn't surfaced yet.
    """

    data = client.execute(PROJECT_ITEM_QUERY, {"itemId": item_id})
    return data.get("node")


def iter_issue_linked_prs(
    client: SupportsExecute,
    issue_id: str,
    *,
    cursor: str | None,
    page_size: int = 50,
) -> Iterator[dict[str, Any]]:
    """Yield an issue's remaining linked-PR nodes past `cursor`.

    Only used when an issue carries more deliberately-linked PRs than the
    single page embedded in the item read; `cursor` is that embedded page's
    end cursor.
    """

    while True:
        data = client.execute(
            ISSUE_LINKED_PRS_QUERY,
            {"issueId": issue_id, "pageSize": page_size, "cursor": cursor},
        )
        refs = (data.get("node") or {}).get("closedByPullRequestsReferences") or {}
        yield from refs.get("nodes", [])
        page_info = refs.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return
        cursor = page_info.get("endCursor")


def page_item_linked_prs(
    client: SupportsExecute, item: dict[str, Any], *, page_size: int = 50
) -> None:
    """Fold any paged linked-PR tail back into `item` in place.

    The item read embeds only the first page of an issue's
    `closedByPullRequestsReferences` connection. When more pages exist, fetch
    them by the issue's node id and append them so the single `item_to_facts`
    read scores the full set. A no-op when the embedded page is already
    complete (the common case).
    """

    has_next, cursor = linked_prs_page_info(item)
    if not has_next:
        return
    issue_id = item_content_id(item)
    if issue_id is None:
        return
    extend_item_linked_prs(
        item,
        list(
            iter_issue_linked_prs(
                client, issue_id, cursor=cursor, page_size=page_size
            )
        ),
    )


def iter_issue_sub_issues(
    client: SupportsExecute,
    issue_id: str,
    *,
    cursor: str | None,
    page_size: int = 50,
) -> Iterator[dict[str, Any]]:
    """Yield an issue's remaining sub-issue nodes past `cursor`.

    Only used when an issue carries more sub-issue children than the single
    page embedded in the item read; `cursor` is that embedded page's end
    cursor.
    """

    while True:
        data = client.execute(
            ISSUE_SUB_ISSUES_QUERY,
            {"issueId": issue_id, "pageSize": page_size, "cursor": cursor},
        )
        refs = (data.get("node") or {}).get("subIssues") or {}
        yield from refs.get("nodes", [])
        page_info = refs.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return
        cursor = page_info.get("endCursor")


def page_item_sub_issues(
    client: SupportsExecute, item: dict[str, Any], *, page_size: int = 50
) -> None:
    """Fold any paged sub-issue tail back into `item` in place.

    The item read embeds only the first page of an issue's `subIssues`
    connection (50); a spec with more tickets than that would otherwise be
    silently truncated in the seed's closure, the tree typing and the child
    roll-up. A no-op when the embedded page is already complete.
    """

    has_next, cursor = sub_issues_page_info(item)
    if not has_next:
        return
    issue_id = item_content_id(item)
    if issue_id is None:
        return
    extend_item_sub_issues(
        item,
        list(
            iter_issue_sub_issues(
                client, issue_id, cursor=cursor, page_size=page_size
            )
        ),
    )


def close_issue(client: SupportsExecute, issue_id: str) -> None:
    """Close one issue (COMPLETED) by its node id, clearing its dependency edges."""

    client.execute(CLOSE_ISSUE_MUTATION, {"issueId": issue_id})


def reopen_issue(client: SupportsExecute, issue_id: str) -> None:
    """Reopen one issue by its node id. Used solely by the map cascade."""

    client.execute(REOPEN_ISSUE_MUTATION, {"issueId": issue_id})


@dataclass(frozen=True)
class MapCascadeAction:
    """One map to close or reopen, decided by `compute_map_cascade`."""

    item_id: str
    content_id: str
    close: bool


def compute_map_cascade(
    facts_by_item_id: dict[str, Facts],
    item_id_by_content_id: dict[str, str],
    child_content_ids_by_item_id: dict[str, list[str]],
) -> list[MapCascadeAction]:
    """Pure reducer: decide which maps this sweep should close or reopen.

    A map auto-closes when its **subtree** (every native sub-issue descendant,
    at any depth — not just direct children) has at least one descendant and
    zero open descendants; "open" is reason-agnostic, so a descendant closed as
    `NOT_PLANNED`/out-of-scope counts the same as one closed `COMPLETED`. A
    closed map **auto-reopens** the moment any descendant is open again. A
    **childless map never auto-closes**, regardless of its own state.

    A descendant this run never ingested (off-board, archived, or contentless)
    has no known closed fact, so it is conservatively treated as open for the
    purpose of *closing* — it can block a close — but it never causes a reopen:
    only a descendant the sweep can see open does.

    A descendant counts as "closed" for this predicate when it is `closed` OR
    has a merged deliberately-linked PR (`has_merged_linked_pr`) — the same
    Done precedence `sync_status` uses — so a spec-branch ticket the sweep is
    about to self-close (its closing keyword being inert) settles the cascade
    in this same pass rather than waiting for the next sweep's re-read of the
    close that just fired.

    Nested maps cascade in the same pass: this function iterates to a fixed
    point, so a deeply-nested map that this same call decides to close is
    already reflected as closed when its own ancestor map's subtree is
    evaluated, in whatever order the maps happen to be visited.

    Returns the ordered list of decided actions; no client I/O happens here —
    the caller issues each mutation and folds the result back onto its own
    `facts_by_item_id` for the rest of the sweep.
    """

    content_id_by_item_id = {v: k for k, v in item_id_by_content_id.items()}

    def children_of(item_id: str) -> tuple[list[str], list[str]]:
        """This item's direct sub-issue children, split into
        `(resolved_item_ids, unresolved_content_ids)` — resolved is any child
        content id that is itself a Project item on this board; unresolved is
        one that isn't (off-board, or never ingested), and so has no further
        children of its own and no known closed fact.
        """
        resolved: list[str] = []
        unresolved: list[str] = []
        for content_id in child_content_ids_by_item_id.get(item_id, []):
            child_item_id = item_id_by_content_id.get(content_id)
            if child_item_id is None:
                unresolved.append(content_id)
            else:
                resolved.append(child_item_id)
        return resolved, unresolved

    def descendants_of(item_id: str) -> tuple[set[str], set[str]]:
        """The full subtree below `item_id`, as `(item_ids, unresolved_content_ids)`.

        `item_ids` is every on-board descendant, at any depth. Each entry in
        `unresolved_content_ids` is a descendant the board can't resolve to a
        Facts read (a leaf as far as this traversal is concerned) — it still
        counts as a descendant, and, having no known closed fact, always
        counts as open (see the caller).
        """
        seen: set[str] = set()
        unresolved: set[str] = set()
        stack = [item_id]
        while stack:
            current = stack.pop()
            resolved_children, unresolved_children = children_of(current)
            unresolved.update(unresolved_children)
            for child_item_id in resolved_children:
                if child_item_id not in seen:
                    seen.add(child_item_id)
                    stack.append(child_item_id)
        return seen, unresolved

    closed_by_item_id = {
        item_id: facts.closed or facts.has_merged_linked_pr
        for item_id, facts in facts_by_item_id.items()
    }
    map_item_ids = [
        item_id for item_id, facts in facts_by_item_id.items() if facts.is_map
    ]

    actions: list[MapCascadeAction] = []
    changed = True
    while changed:
        changed = False
        for item_id in map_item_ids:
            descendant_item_ids, unresolved_content_ids = descendants_of(item_id)
            if not descendant_item_ids and not unresolved_content_ids:
                continue  # childless-map guard: never auto-close
            # An unresolved descendant has no known closed fact, so it always
            # counts as open — it can block a close but never causes one.
            known_open_count = sum(
                1
                for descendant in descendant_item_ids
                if closed_by_item_id.get(descendant) is not True
            )
            open_descendant_count = len(unresolved_content_ids) + known_open_count
            currently_closed = closed_by_item_id.get(item_id, False)
            content_id = content_id_by_item_id.get(item_id)
            if content_id is None:
                continue
            if open_descendant_count == 0 and not currently_closed:
                actions.append(MapCascadeAction(item_id, content_id, close=True))
                closed_by_item_id[item_id] = True
                changed = True
            # Reopen only on positive evidence: a descendant we can see is open.
            # An unresolved one may just be archived (hidden with its closed
            # Map's tree), so it blocks a close but never reopens a closed Map.
            elif known_open_count > 0 and currently_closed:
                actions.append(MapCascadeAction(item_id, content_id, close=False))
                closed_by_item_id[item_id] = False
                changed = True

    return actions


def _board_content_ids(
    client: SupportsExecute, project_id: str, page_size: int
) -> set[str]:
    """The content ids of every issue/PR already carded on the board."""

    return {
        content_id
        for item in iter_project_items(client, project_id, page_size=page_size)
        if (content_id := item_content_id(item)) is not None
    }


def seed_board(
    client: SupportsExecute,
    project_id: str,
    planning_repo: str,
    *,
    seed_labels: Sequence[str] | None = None,
    page_size: int = 50,
) -> dict[str, str]:
    """Pass 0: ensure every effort issue is a card, so no agent runs `item-add`.

    First seed the planning repo's own OPEN issues (maps, tasks, research,
    implementation tickets) — only those carrying at least one of `seed_labels`
    when given (the union, paged once per label), all of them when it is None.
    Then take the **transitive closure over native sub-issues**: a map's child
    that lives in another repo — a spec — is only visible once the map itself
    is on the board, so re-scan the board's sub-issue edges and pull in any
    child not yet carded, repeating until a scan adds nothing. We diff against
    the board first, and `add_item` is idempotent anyway, so a settled board
    issues no add mutations.

    Returns a mapping of each newly added content id -> its Project item id, in
    insertion order. The item ids let the sweep sync a fresh card directly (by
    item id) even when the eventually-consistent board list read hasn't caught
    up to the add yet.
    """

    owner, name = planning_repo.split("/", 1)
    on_board = _board_content_ids(client, project_id, page_size)
    added: dict[str, str] = {}

    # ONE unlabelled scan, filtered client-side on the label union: the
    # per-label variant paged the repo once per label (seven scans on a
    # repo-board) to end up with the same union.
    wanted_labels = set(seed_labels) if seed_labels is not None else None
    for node in iter_repo_open_issues(
        client, owner, name, page_size=page_size
    ):
        if wanted_labels is not None and not (
            set(node.get("labels") or ()) & wanted_labels
        ):
            continue
        content_id = node["id"]
        if content_id not in on_board:
            added[content_id] = add_item(client, project_id, content_id)
            on_board.add(content_id)

    while True:
        newly_added: dict[str, str] = {}
        for item in iter_project_items(client, project_id, page_size=page_size):
            # The embed holds only the first 50 sub-issues; fold any tail in
            # or a big spec's later tickets are never seeded at all.
            page_item_sub_issues(client, item, page_size=page_size)
            for child_id in item_child_content_ids(item):
                if child_id not in on_board:
                    newly_added[child_id] = add_item(client, project_id, child_id)
                    on_board.add(child_id)
        if not newly_added:
            break
        added.update(newly_added)

    return added


def card_spec_family_prs(
    client: SupportsExecute,
    project_id: str,
    repo_full_name: str,
    repo_prs: Sequence[dict[str, Any]],
    on_board: set[str],
) -> list[str]:
    """Card every open spec-family PR not yet carded; return the added ids.

    A spec PR is one whose head branch is `<spec-slug>/base`; a stack PR is
    one whose base chain bottoms out in a spec branch (ticket PRs and the fix
    PRs stacked above them). Both become cards; a standalone PR into `main`
    does not.
    """

    open_prs = [pr for pr in repo_prs if pr.get("state") == "OPEN"]
    family = stack_family_pr_numbers(open_prs)
    added: list[str] = []
    for pr in open_prs:
        if pr["number"] not in family:
            continue
        content_id = pr["id"]
        if content_id in on_board:
            continue
        add_item(client, project_id, content_id)
        on_board.add(content_id)
        added.append(content_id)
    return added


def type_issue_cards(
    items_by_id: dict[str, dict[str, Any]],
    item_id_by_content_id: dict[str, str],
    child_content_ids_by_item_id: dict[str, list[str]],
) -> dict[str, CardType]:
    """Type every issue card by labels and tree position.

    The walk starts at the map cards (the `wayfinder:map` label) and follows
    the board's own sub-issue edges: a map's non-phase-1 children are specs,
    a spec's children are implementation tickets, everything else is
    standalone. A card whose parent is on the board and already typed as a
    spec is an implementation ticket even when no map is reachable above it
    (an orphaned spec tree still types its tickets correctly).
    """

    typed: dict[str, CardType] = {}
    map_items = [
        (item_id, items_by_id[item_id])
        for item_id, item in items_by_id.items()
        if (content := item.get("content")) is not None and is_map_content(content)
    ]
    for map_item_id, map_item in map_items:
        map_content_id = item_content_id(map_item)
        if map_content_id is None:
            continue
        typed[map_content_id] = CardType("map", map_id=map_content_id)
        for child_content_id in child_content_ids_by_item_id.get(map_item_id, []):
            child_item_id = item_id_by_content_id.get(child_content_id)
            if child_item_id is None:
                continue
            child_content = items_by_id[child_item_id].get("content") or {}
            if is_phase1_content(child_content):
                typed[child_content_id] = CardType("phase1", map_id=map_content_id)
            else:
                typed[child_content_id] = CardType(
                    "spec", map_id=map_content_id, spec_id=child_content_id
                )
    # Specs' children: implementation tickets.
    spec_content_ids = [
        content_id
        for content_id, card_type in typed.items()
        if card_type.kind == "spec"
    ]
    for spec_content_id in spec_content_ids:
        spec_item_id = item_id_by_content_id.get(spec_content_id)
        if spec_item_id is None:
            continue
        spec_type = typed[spec_content_id]
        for child_content_id in child_content_ids_by_item_id.get(spec_item_id, []):
            if child_content_id not in typed:
                typed[child_content_id] = CardType(
                    "impl", map_id=spec_type.map_id, spec_id=spec_type.spec_id
                )
    return typed


def _option_name_for(content: dict[str, Any]) -> str | None:
    """The `<title> #<number>` an option carries for one map or spec."""

    number = content.get("number")
    title = content.get("title")
    if number is None or not title:
        return None
    return f"{title} #{number}"


def _stamp_identity(
    typed: dict[str, CardType],
    item_id_by_content_id: dict[str, str],
    stamps_by_item_id: dict[str, dict[str, str | None]],
    child_content_ids_by_item_id: dict[str, list[str]],
    pr_meta_by_content_id: dict[str, dict[str, str | None]],
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Pin each map/spec option to its existing option id, when one is set.

    The identity evidence is any family card's current stamp value: the
    map's own card, its phase-1 tickets, its specs, their tickets, and —
    crucially when the spec and every ticket are VANISHED (their stamps
    cleared while their PRs are open) — the family's PR cards, whose Spec
    value still points at the option. Without that evidence a retitle of a
    fully-vanished spec would find no pin and spawn a second option.
    """

    pr_content_ids_by_spec: dict[str, list[str]] = {}
    for pr_content_id, meta in pr_meta_by_content_id.items():
        spec_id = meta.get("spec_content_id")
        if spec_id:
            pr_content_ids_by_spec.setdefault(spec_id, []).append(pr_content_id)

    map_identity: dict[str, str | None] = {}
    spec_identity: dict[str, str | None] = {}

    def evidence_for(content_id: str) -> tuple[str | None, str | None]:
        map_option: str | None = None
        spec_option: str | None = None
        roots = [content_id]
        if content_id in item_id_by_content_id:
            item_id = item_id_by_content_id[content_id]
            roots.extend(child_content_ids_by_item_id.get(item_id, []))
        roots.extend(pr_content_ids_by_spec.get(content_id, []))
        for candidate_content_id in roots:
            candidate_item_id = item_id_by_content_id.get(candidate_content_id)
            if candidate_item_id is None:
                continue
            stamps = stamps_by_item_id.get(candidate_item_id) or {}
            map_option = map_option or stamps.get("Map")
            spec_option = spec_option or stamps.get("Spec")
        return map_option, spec_option

    for content_id, card_type in typed.items():
        if card_type.kind == "map":
            map_identity[content_id] = evidence_for(content_id)[0]
        elif card_type.kind == "spec":
            map_option, spec_option = evidence_for(content_id)
            spec_identity[content_id] = spec_option
            if card_type.map_id is not None:
                existing = map_identity.get(card_type.map_id)
                if existing is None and map_option is not None:
                    map_identity[card_type.map_id] = map_option
    return map_identity, spec_identity


def plan_and_write_stamps(
    client: SupportsExecute,
    project_id: str,
    shape: BoardShape,
    typed: dict[str, CardType],
    items_by_id: dict[str, dict[str, Any]],
    item_id_by_content_id: dict[str, str],
    child_content_ids_by_item_id: dict[str, list[str]],
    stamps_by_item_id: dict[str, dict[str, str | None]],
    pr_meta_by_content_id: dict[str, dict[str, str | None]],
    item_order: Sequence[str],
    result: SyncResult,
) -> None:
    """Grow the stamp options, then write only the stamp drift.

    Option growth is identity-preserving; the per-card writes are a diff
    against the card's current stamp values, so a settled board issues no
    stamp mutations at all.
    """

    map_entries: list[dict[str, str]] = []
    spec_entries: list[dict[str, str]] = []
    for content_id, card_type in typed.items():
        item_id = item_id_by_content_id.get(content_id)
        if item_id is None:
            continue
        content = items_by_id[item_id].get("content") or {}
        name = _option_name_for(content)
        if name is None:
            continue
        if card_type.kind == "map":
            map_entries.append({"key": content_id, "name": name, "color": "ORANGE"})
        elif card_type.kind == "spec":
            spec_entries.append({"key": content_id, "name": name, "color": "BLUE"})
    map_identity, spec_identity = _stamp_identity(
        typed,
        item_id_by_content_id,
        stamps_by_item_id,
        child_content_ids_by_item_id,
        pr_meta_by_content_id,
    )
    (
        map_field_id,
        map_option_ids,
        spec_field_id,
        spec_option_ids,
        created_fields,
    ) = ensure_stamp_fields(
        client, project_id, map_entries, spec_entries, map_identity, spec_identity
    )
    result.fields_created.extend(created_fields)
    shape.map_field_id, shape.map_option_ids = map_field_id, map_option_ids
    shape.spec_field_id, shape.spec_option_ids = spec_field_id, spec_option_ids

    option_name_by_content_id: dict[str, dict[str, str]] = {}
    for content_id, card_type in typed.items():
        entry: dict[str, str] = {}
        if card_type.kind == "map":
            name = _option_name_for(
                items_by_id[item_id_by_content_id[content_id]].get("content") or {}
            )
            if name:
                entry["map"] = name
        elif card_type.kind == "spec":
            name = _option_name_for(
                items_by_id[item_id_by_content_id[content_id]].get("content") or {}
            )
            if name:
                entry["spec"] = name
            if card_type.map_id is not None and card_type.map_id in item_id_by_content_id:
                map_name = _option_name_for(
                    items_by_id[
                        item_id_by_content_id[card_type.map_id]
                    ].get("content")
                    or {}
                )
                if map_name:
                    entry["map"] = map_name
        if entry:
            option_name_by_content_id[content_id] = entry
    for spec_content_id, meta in pr_meta_by_content_id.items():
        owner_content_id = meta.get("spec_content_id")
        if not owner_content_id:
            continue
        entry = option_name_by_content_id.setdefault(owner_content_id, {})
        owner_type = typed.get(owner_content_id)
        if owner_type is None or owner_type.kind not in ("map", "spec"):
            continue
        owner_item_id = item_id_by_content_id.get(owner_content_id)
        if owner_item_id is None:
            continue
        name = _option_name_for(
            items_by_id[owner_item_id].get("content") or {}
        )
        if name is None:
            continue
        if owner_type.kind == "map":
            entry["map"] = name
        else:
            entry["spec"] = name
            if owner_type.map_id is not None and owner_type.map_id in item_id_by_content_id:
                map_name = _option_name_for(
                    items_by_id[item_id_by_content_id[owner_type.map_id]].get("content")
                    or {}
                )
                if map_name:
                    entry["map"] = map_name

    plans: list[StampPlan] = compute_stamps(
        typed,
        issue_ids_with_open_pr=_open_pr_content_ids(items_by_id),
        pr_card_meta=pr_meta_by_content_id,
        option_name_by_content_id=option_name_by_content_id,
    )
    field_ids = {"Map": map_field_id, "Spec": spec_field_id}
    # Resolve plan option names to ids through the shape's per-key maps.
    name_to_option_id: dict[str, dict[str, str]] = {"Map": {}, "Spec": {}}
    for entry in map_entries:
        if (option_id := map_option_ids.get(entry["key"])) is not None:
            name_to_option_id["Map"][entry["name"]] = option_id
    for entry in spec_entries:
        if (option_id := spec_option_ids.get(entry["key"])) is not None:
            name_to_option_id["Spec"][entry["name"]] = option_id

    planned_stamps = {plan.content_id: plan.stamps for plan in plans}
    for plan in plans:
        item_id = item_id_by_content_id.get(plan.content_id)
        if item_id is None:
            continue
        current = stamps_by_item_id.get(item_id) or {}
        for field_name, wanted_name in plan.stamps.items():
            field_id = field_ids.get(field_name)
            if field_id is None:
                continue
            wanted_option_id = (
                name_to_option_id[field_name].get(wanted_name)
                if wanted_name is not None
                else None
            )
            if wanted_name is not None and wanted_option_id is None:
                continue  # option not established yet; the next sweep stamps
            if wanted_option_id is None:
                if current.get(field_name) is not None:
                    clear_field(client, project_id, item_id, field_id)
                    result.stamps_cleared.append((item_id, field_name))
                continue
            if current.get(field_name) != wanted_option_id:
                set_field_option(client, project_id, item_id, field_id, wanted_option_id)
                result.stamps_set.append((item_id, field_name))

    # The drift-clears: a card whose plan no longer mentions a field it
    # currently carries has LOST that association (an impl ticket detached
    # from its spec, a spec unlinked from its map, a card that fell out of
    # the model entirely) — the stale stamp would keep it grouped under a
    # map/spec it no longer belongs to, so it is cleared. The pass walks
    # EVERY ingested card (a detached card is untyped — that is the point),
    # settles both stamp fields of each, and a settled board writes nothing.
    content_id_by_item_id = {
        iid: cid for cid, iid in item_id_by_content_id.items()
    }
    for item_id in item_order:
        if item_id not in stamps_by_item_id:
            continue
        content_id = content_id_by_item_id.get(item_id)
        if content_id is None:
            continue
        wanted = planned_stamps.get(content_id) or {}
        current = stamps_by_item_id.get(item_id) or {}
        for field_name, field_id in field_ids.items():
            if field_id is None or field_name in wanted:
                continue
            if current.get(field_name) is not None:
                clear_field(client, project_id, item_id, field_id)
                result.stamps_cleared.append((item_id, field_name))


def _open_pr_content_ids(items_by_id: dict[str, dict[str, Any]]) -> set[str]:
    """Content ids of ISSUE cards that an OPEN closing-linked PR closes.

    This is the vanish set: a card in it has work running on a PR, so the
    stamps that would place it beside that PR's card are cleared.
    """

    issue_ids: set[str] = set()
    for item in items_by_id.values():
        content = item.get("content") or {}
        if content.get("__typename") != "Issue":
            continue
        content_id = content.get("id")
        if content_id is None:
            continue
        for pr in (content.get("closedByPullRequestsReferences") or {}).get(
            "nodes"
        ) or []:
            if pr.get("state") == "OPEN":
                issue_ids.add(content_id)
                break
    return issue_ids


def resolve_pr_specs(
    repo_full_name: str,
    repo_prs: Sequence[dict[str, Any]],
    family_numbers: set[int],
    typed: dict[str, CardType],
) -> dict[str, dict[str, str | None]]:
    """Map each family PR card's content id to the spec it implements.

    The mapping rides the PR's effective closing links (`Closes #<n>`, authored
    by the link arm for non-default targets): a spec PR closes its spec; a
    stack PR closes its implementation ticket, whose typed card names the
    spec. A PR whose links don't resolve (an ambiguous body, a standalone
    issue, a body missing the line entirely) maps to no spec: the card stays
    unstamped — invisible on every view — and the sweep says so on stderr so
    the missing `Closes #<n>` line is loud, not silent. When a body closes
    tickets of several specs, the first connection match wins and the
    ambiguity is logged; fixing the body heals it on the next sweep.
    """

    if "/" not in repo_full_name:
        return {}
    owner, name = repo_full_name.split("/", 1)
    meta: dict[str, dict[str, str | None]] = {}
    for pr in repo_prs:
        if pr.get("state") != "OPEN" or pr.get("number") not in family_numbers:
            continue
        kind = "spec" if is_spec_pr(pr.get("headRefName")) else "stack"
        spec_content_id: str | None = None
        matched: list[str] = []
        for node in (pr.get("closingRefs") or {}).get("nodes") or []:
            repository = node.get("repository") or {}
            if (repository.get("owner") or {}).get("login") != owner:
                continue
            if repository.get("name") != name:
                continue
            issue_content_id = node.get("id")
            card_type = typed.get(issue_content_id)
            if card_type is None:
                continue
            if kind == "spec" and card_type.kind == "spec":
                matched.append(issue_content_id)
            elif kind == "stack" and card_type.kind in ("impl", "spec"):
                matched.append(card_type.spec_id or issue_content_id)
        if matched:
            spec_content_id = matched[0]
            if len(matched) > 1:
                print(
                    f"warning: PR #{pr.get('number')} closes tickets of"
                    f" {len(matched)} specs — stamping with the first; fix the"
                    f" body so each PR closes one ticket",
                    file=sys.stderr,
                )
        else:
            print(
                f"warning: PR #{pr.get('number')} resolves to no spec — its"
                f" body needs a `Closes #<ticket>` line (the spec PR:"
                f" `Closes #<spec>`); the card stays unstampeded until then",
                file=sys.stderr,
            )
        meta[pr["id"]] = {
            "kind": kind,
            "spec_content_id": spec_content_id,
        }
    return meta


def run_sync(
    client: SupportsExecute,
    project_id: str,
    *,
    planning_repo: str | None = None,
    seed_labels: Sequence[str] | None = None,
    repo_prs: Sequence[dict[str, Any]] | None = None,
    page_size: int = 50,
) -> SyncResult:
    """Shape the board, card the work, stamp it, score it, write it back.

    When `planning_repo` is given, pass 0 seeds the board first (every
    planning-repo issue plus their transitive sub-issue children), so the
    sweep reconciles a board it also keeps populated. When `repo_prs` is
    given (the link arm's fetched nodes), the sweep cards the spec-family PRs
    among them. Every card, closed or open, is a write-candidate: the sweep
    is authoritative for the Status column. The skip-if-unchanged guard keeps
    a settled board cheap — no mutation where nothing drifted.
    """

    seeded_items: dict[str, str] = {}
    if planning_repo:
        seeded_items = seed_board(
            client,
            project_id,
            planning_repo,
            seed_labels=seed_labels,
            page_size=page_size,
        )

    shape = ensure_board_shape(client, project_id)
    result = SyncResult(seeded=list(seeded_items))

    if repo_prs is not None and planning_repo:
        on_board = _board_content_ids(client, project_id, page_size)
        result.pr_cards_added = card_spec_family_prs(
            client, project_id, planning_repo, repo_prs, on_board
        )

    status_field = StatusField(shape.status_field_id, shape.status_option_ids)

    items = list(iter_project_items(client, project_id, page_size=page_size))

    item_order: list[str] = []
    facts_by_item_id: dict[str, Facts] = {}
    current_option_id_by_item_id: dict[str, str | None] = {}
    stamps_by_item_id: dict[str, dict[str, str | None]] = {}
    archived_by_item_id: dict[str, bool] = {}
    item_id_by_content_id: dict[str, str] = {}
    child_content_ids_by_item_id: dict[str, list[str]] = {}
    issue_ids_to_close: dict[str, str] = {}
    items_by_id: dict[str, dict[str, Any]] = {}

    def ingest(item: dict[str, Any]) -> None:
        item_id: str = item["id"]
        item_order.append(item_id)
        current_option_id_by_item_id[item_id] = item_current_status_option_id(item)
        stamps_by_item_id[item_id] = item_current_stamp_option_ids(item)
        archived_by_item_id[item_id] = item_is_archived(item)

        # Fold any paged linked-PR / sub-issue tails in before scoring so the
        # merged-PR fact, the seed closure, the tree typing and the roll-up
        # all see the full sets, not just the first embedded pages.
        page_item_linked_prs(client, item, page_size=page_size)
        page_item_sub_issues(client, item, page_size=page_size)

        facts = item_to_facts(item)
        if facts is None:
            result.skipped_contentless.append(item_id)
            return

        facts_by_item_id[item_id] = facts
        content_id = item_content_id(item)
        if content_id is not None:
            item_id_by_content_id[content_id] = item_id
            if facts.has_merged_linked_pr and not facts.closed:
                issue_ids_to_close[item_id] = content_id
        child_content_ids_by_item_id[item_id] = item_child_content_ids(item)
        items_by_id[item_id] = item

    for item in items:
        ingest(item)

    # Backfill any card seeded or carded this run that the board list didn't
    # return yet: Projects v2 list reads are eventually consistent, so a
    # just-added item can be missing here, but a read by its item id (which
    # `add_item` returned) is consistent.
    for content_id, item_id in seeded_items.items():
        if content_id in item_id_by_content_id:
            continue
        item = fetch_project_item(client, item_id)
        if item is not None:
            ingest(item)

    # Type every issue card from labels and tree position, then resolve each
    # family PR card to the spec it implements.
    typed = type_issue_cards(
        items_by_id, item_id_by_content_id, child_content_ids_by_item_id
    )
    pr_meta_by_content_id: dict[str, dict[str, str | None]] = {}
    if repo_prs is not None:
        open_prs = [pr for pr in repo_prs if pr.get("state") == "OPEN"]
        family_numbers = stack_family_pr_numbers(open_prs)
        pr_meta_by_content_id = resolve_pr_specs(
            planning_repo or "", repo_prs, family_numbers, typed
        )

    # Stamps: grow the options, then write only the drift (the vanish is a
    # cleared stamp, self-healing when the PR closes without merging).
    plan_and_write_stamps(
        client,
        project_id,
        shape,
        typed,
        items_by_id,
        item_id_by_content_id,
        child_content_ids_by_item_id,
        stamps_by_item_id,
        pr_meta_by_content_id,
        item_order,
        result,
    )

    # Views come AFTER the stamp fields: a filter referencing a field that
    # does not exist yet is stored as an invalid filter the string
    # comparison can never detect. `force_filters` rewrites every filter on
    # the sweep that created the fields, repairing boards whose views were
    # written before their fields.
    views_created, views_updated = ensure_views(
        client, project_id, force_filters=bool(result.fields_created)
    )
    result.views_created = views_created
    result.views_updated = views_updated

    # Close any still-open issue whose deliberately-linked PR merged: closing
    # clears its native blocked_by edges so dependents unblock, and fires an
    # `issues: closed` event that reconciles the board again.
    for item_id in item_order:
        issue_id = issue_ids_to_close.get(item_id)
        if issue_id is not None:
            close_issue(client, issue_id)
            result.closed_issues.append(issue_id)

    # Map auto-close cascade: fold each map's subtree closure into this same
    # sweep, no new trigger.
    closed_map_item_ids = {
        item_id
        for item_id, facts in facts_by_item_id.items()
        if facts.is_map and (facts.closed or facts.has_merged_linked_pr)
    }
    map_actions = compute_map_cascade(
        facts_by_item_id, item_id_by_content_id, child_content_ids_by_item_id
    )
    for action in map_actions:
        if action.close:
            close_issue(client, action.content_id)
            result.map_closed.append(action.content_id)
            closed_map_item_ids.add(action.item_id)
        else:
            reopen_issue(client, action.content_id)
            result.map_reopened.append(action.content_id)
            closed_map_item_ids.discard(action.item_id)
        facts_by_item_id[action.item_id] = replace(
            facts_by_item_id[action.item_id], closed=action.close
        )

    # A "parent" is any item with at least one sub-issue child that is itself
    # a Project item on this board; everything else syncs as a leaf in
    # pass 1, including items with children the board can't see.
    parent_item_ids = {
        item_id
        for item_id, child_ids in child_content_ids_by_item_id.items()
        if any(child_id in item_id_by_content_id for child_id in child_ids)
    }

    status_by_item_id: dict[str, Status | None] = {}

    # Pass 1: leaves.
    for item_id, facts in facts_by_item_id.items():
        if item_id in parent_item_ids:
            continue
        status_by_item_id[item_id] = sync_status(facts)

    # Pass 2: parents, rolling their children's synced Status up first. A
    # child counts as "started" once its synced Status is In progress,
    # In review, Approved or Done.
    STARTED = {
        Status.IN_PROGRESS,
        Status.IN_REVIEW,
        Status.APPROVED,
        Status.DONE,
    }
    for item_id in parent_item_ids:
        facts = facts_by_item_id[item_id]
        child_ids = child_content_ids_by_item_id.get(item_id, [])
        child_statuses = [
            status_by_item_id.get(item_id_by_content_id.get(child_id))
            for child_id in child_ids
        ]
        child_started_count = sum(1 for s in child_statuses if s in STARTED)
        rolled_up_facts = replace(facts, child_started_count=child_started_count)
        status_by_item_id[item_id] = sync_status(rolled_up_facts)

    # Write back in the Project's original item order, skipping no-op writes.
    for item_id in item_order:
        if item_id not in facts_by_item_id:
            continue  # already recorded in skipped_contentless
        status = status_by_item_id[item_id]
        if status is None:  # a map: no work-Status, never forced into a column
            result.skipped_maps.append(item_id)
            continue
        target_option_id = status_field.option_id_for(status)
        if current_option_id_by_item_id.get(item_id) == target_option_id:
            result.status_unchanged.append((item_id, status))
            continue
        write_status(client, project_id, item_id, status_field, status)
        result.status_written.append((item_id, status))

    # The archive arm: a closed card of the spec family (a map, a spec, an
    # implementation ticket, or any PR card) hides from every view; an open
    # one that was archived comes back when its work resumes. Phase-1
    # decision tickets and standalone issues are NOT archived — they settle
    # visibly into Done (or the native auto-archive, if wanted), and a card
    # hidden by hand comes back while its content is open: the sweep has no
    # marker to tell a hand-hide from a stale archive, so it errs toward
    # visibility.
    for item_id in item_order:
        facts = facts_by_item_id.get(item_id)
        if facts is None:
            continue
        content = items_by_id[item_id].get("content") or {}
        content_id = item_content_id(items_by_id[item_id])
        card_type = typed.get(content_id) if content_id is not None else None
        is_family_card = card_type is not None and card_type.kind in (
            "map",
            "spec",
            "impl",
        )
        if content.get("__typename") == "PullRequest":
            is_family_card = True
        if not is_family_card:
            continue
        is_closed = facts.closed or facts.has_merged_linked_pr
        was_archived = archived_by_item_id.get(item_id, False)
        if is_closed and not was_archived:
            client.execute(
                ARCHIVE_ITEM_MUTATION, {"projectId": project_id, "itemId": item_id}
            )
            result.archived.append(item_id)
        elif not is_closed and was_archived:
            client.execute(
                UNARCHIVE_ITEM_MUTATION, {"projectId": project_id, "itemId": item_id}
            )
            result.unarchived.append(item_id)

    return result

"""The sync job: fetch every card's facts, sync its Status, write it back.

This is the orchestration shell (ticket 03). It composes thin steps around the
pure function and holds no precedence branching itself:

    pass 0: seed the board — add every planning-repo issue, and transitively via
            native sub-issues any cross-repo child (e.g. a spec), so no agent
            ever runs `item-add`; a card seeded this run is read back by its item
            id so it's synced now, not left blank until the next run
    read (GraphQL) -> item_to_facts -> sync_status -> write (GraphQL)

The sync runs in **two passes** so a parent's child roll-up (`Facts.
child_in_progress_count`) reflects its children's *synced* Status, not their
raw facts:

    pass 1: sync every leaf item (no sub-issue children present on the board)
    pass 2: for each parent, count children whose pass-1 Status is In progress,
            fold that count into the parent's own Facts, then sync the parent

`sync_status` stays pure and knows nothing about passes; the job owns the
ordering. Results are written back in the Project's original item order,
regardless of which pass produced them.

Maps (`sync_status` returns `None`) get no Status written; they are recorded so
the caller can, optionally, surface an "all children closed" hint. A map is never
auto-closed. Items with no content (draft items / invisible issues) are skipped.

A **closed card is never written**: only open cards board-wide are write-
candidates. A closed card's facts are still read and scored — its synced Status
feeds the child roll-up and the future map-cascade — but the sweep leaves the
column itself alone; the native "closed → Done" Project workflow already owns
it, so writing here would just be a wasted mutation, and a finished effort's
closed cards would otherwise dominate the API-call count of every sweep as N
grows. See `run_sync`'s final write loop.

Nothing is deployed in any code repo: a spec's PR state is reached remotely
through the same GraphQL client, cross-repo.

Scaling note (documented, not built): one sweep fully paginates the board up to
three times over — `seed_board`'s `_board_content_ids` diff read, its closure
loop's own `iter_project_items` pass(es), and `run_sync`'s main `items` read.
That is a flat cost regardless of N today; at N≈500+ cards it is the first
place worth cutting (e.g. a single cached board read shared across all three),
but is a pre-agreed future lever, not a problem this prefactor solves.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from ai_planning.client import SupportsExecute
from ai_planning.sync_status import Facts, Status, sync_status
from ai_planning.facts_mapping import (
    extend_item_linked_prs,
    item_child_content_ids,
    item_content_id,
    item_current_status_option_id,
    linked_prs_page_info,
    item_to_facts,
)
from ai_planning.queries import (
    ADD_ITEM_MUTATION,
    CLOSE_ISSUE_MUTATION,
    ISSUE_LINKED_PRS_QUERY,
    PROJECT_ITEM_QUERY,
    PROJECT_ITEMS_QUERY,
    REPO_ISSUES_QUERY,
    STATUS_FIELD_QUERY,
    UPDATE_STATUS_MUTATION,
)


@dataclass(frozen=True)
class StatusField:
    """The Project's Status field: its node id and name -> option-id lookup."""

    field_id: str
    option_ids: dict[str, str]

    def option_id_for(self, status: Status) -> str:
        return self.option_ids[status.value]


@dataclass
class SyncResult:
    """What one sync pass did, for logging and the map hint."""

    seeded: list[str] = field(default_factory=list)
    written: list[tuple[str, Status]] = field(default_factory=list)
    unchanged: list[tuple[str, Status]] = field(default_factory=list)
    skipped_maps: list[str] = field(default_factory=list)
    skipped_contentless: list[str] = field(default_factory=list)
    skipped_closed: list[tuple[str, Status]] = field(default_factory=list)
    closed_issues: list[str] = field(default_factory=list)


def fetch_status_field(client: SupportsExecute, project_id: str) -> StatusField:
    """Read the Status field id and its option-name -> option-id map."""

    data = client.execute(STATUS_FIELD_QUERY, {"projectId": project_id})
    field_node = (data.get("node") or {}).get("field") or {}
    option_ids = {
        option["name"]: option["id"] for option in field_node.get("options", [])
    }
    return StatusField(field_id=field_node["id"], option_ids=option_ids)


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


def write_status(
    client: SupportsExecute,
    project_id: str,
    item_id: str,
    status_field: StatusField,
    status: Status,
) -> None:
    """Write one synced Status onto a card as its single-select option."""

    client.execute(
        UPDATE_STATUS_MUTATION,
        {
            "projectId": project_id,
            "itemId": item_id,
            "fieldId": status_field.field_id,
            "optionId": status_field.option_id_for(status),
        },
    )


def iter_repo_open_issue_ids(
    client: SupportsExecute, owner: str, name: str, *, page_size: int = 50
) -> Iterator[str]:
    """Yield the content node id of every OPEN issue in `owner/name`."""

    cursor: str | None = None
    while True:
        data = client.execute(
            REPO_ISSUES_QUERY,
            {"owner": owner, "name": name, "pageSize": page_size, "cursor": cursor},
        )
        issues = (data.get("repository") or {}).get("issues") or {}
        for node in issues.get("nodes", []):
            content_id = node.get("id")
            if content_id:
                yield content_id
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


def close_issue(client: SupportsExecute, issue_id: str) -> None:
    """Close one issue (COMPLETED) by its node id, clearing its dependency edges."""

    client.execute(CLOSE_ISSUE_MUTATION, {"issueId": issue_id})


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
    page_size: int = 50,
) -> dict[str, str]:
    """Pass 0: ensure every effort issue is a card, so no agent runs `item-add`.

    First seed the planning repo's own OPEN issues (maps, tasks, research,
    implementation tickets). Then take the **transitive closure over native
    sub-issues**: a map's child that lives in another repo — a spec — is only
    visible once the map itself is on the board, so re-scan the board's
    sub-issue edges and pull in any child not yet carded, repeating until a
    scan adds nothing. We diff against the board first, and `add_item` is
    idempotent anyway, so a settled board issues no add mutations.

    Returns a mapping of each newly added content id -> its Project item id, in
    insertion order. The item ids let the sweep sync a fresh card directly (by
    item id) even when the eventually-consistent board list read hasn't caught
    up to the add yet.
    """

    owner, name = planning_repo.split("/", 1)
    on_board = _board_content_ids(client, project_id, page_size)
    added: dict[str, str] = {}

    for content_id in iter_repo_open_issue_ids(
        client, owner, name, page_size=page_size
    ):
        if content_id not in on_board:
            added[content_id] = add_item(client, project_id, content_id)
            on_board.add(content_id)

    while True:
        newly_added: dict[str, str] = {}
        for item in iter_project_items(client, project_id, page_size=page_size):
            for child_id in item_child_content_ids(item):
                if child_id not in on_board:
                    newly_added[child_id] = add_item(client, project_id, child_id)
                    on_board.add(child_id)
        if not newly_added:
            break
        added.update(newly_added)

    return added


def run_sync(
    client: SupportsExecute,
    project_id: str,
    *,
    planning_repo: str | None = None,
    page_size: int = 50,
) -> SyncResult:
    """Score every card and write each synced Status back, two passes deep.

    When `planning_repo` is given, pass 0 seeds the board first (every
    planning-repo issue plus their transitive sub-issue children), so the sweep
    reconciles a board it also keeps populated. Any card seeded this run that the
    (eventually-consistent) board list read doesn't return yet is fetched back by
    its item id so it is still synced now. Pass 1 syncs every leaf (an item with
    no sub-issue children present on this board). Pass 2 syncs every parent,
    first rolling its children's pass-1 Status up into `child_in_progress_count`.
    Writes happen afterwards, in the Project's original item order. Only **open**
    cards are write-candidates: a closed card's Status is still computed (it
    feeds the child roll-up) but never written back, since the native
    "closed -> Done" Project workflow already owns that column.

    Every card scores off `item_to_facts`'s sole PR read — a deliberately-linked
    PR (`closedByPullRequestsReferences(userLinkedOnly: true)`), cross-repo or
    same-repo alike, no allow-list required. When a linked PR has merged while
    its issue is still OPEN (e.g. a spec-branch PR, whose closing keyword
    GitHub treats as inert), the job self-closes that issue (COMPLETED) so its
    native `blocked_by` edges clear and dependents unblock; the card itself
    resolves to Done here regardless of when that close lands.
    """

    seeded_items: dict[str, str] = {}
    if planning_repo:
        seeded_items = seed_board(
            client, project_id, planning_repo, page_size=page_size
        )

    status_field = fetch_status_field(client, project_id)
    result = SyncResult(seeded=list(seeded_items))

    items = list(iter_project_items(client, project_id, page_size=page_size))

    item_order: list[str] = []
    facts_by_item_id: dict[str, Facts] = {}
    current_option_id_by_item_id: dict[str, str | None] = {}
    item_id_by_content_id: dict[str, str] = {}
    child_content_ids_by_item_id: dict[str, list[str]] = {}
    # Issue node ids to close: a merged, deliberately-linked PR completed the
    # ticket, but the issue is still OPEN (its closing keyword was inert, e.g. a
    # spec-branch PR). Closing it clears the native blocked_by edges so
    # dependents unblock.
    issue_ids_to_close: dict[str, str] = {}

    def ingest(item: dict[str, Any]) -> None:
        item_id: str = item["id"]
        item_order.append(item_id)
        current_option_id_by_item_id[item_id] = item_current_status_option_id(item)

        # Fold any paged linked-PR tail in before scoring so the merged-PR fact
        # sees the full set, not just the first embedded page.
        page_item_linked_prs(client, item, page_size=page_size)

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

    for item in items:
        ingest(item)

    # Backfill any card seeded this run that the board list didn't return yet:
    # Projects v2 list reads are eventually consistent, so a just-added item can
    # be missing here, but a read by its item id (which `add_item` returned) is
    # consistent. Without this, a freshly seeded card would be left with no
    # Status until the next run.
    for content_id, item_id in seeded_items.items():
        if content_id in item_id_by_content_id:
            continue
        item = fetch_project_item(client, item_id)
        if item is not None:
            ingest(item)

    # Close any still-open issue whose deliberately-linked PR merged: closing
    # clears its native blocked_by edges so dependents unblock, and fires an
    # `issues: closed` event that reconciles the board again. Ordered by first
    # appearance for a deterministic sweep. The card's own Status is already
    # Done via `has_merged_linked_pr`, independent of this close. A harmless
    # no-op when GitHub's own native close already fired.
    for item_id in item_order:
        issue_id = issue_ids_to_close.get(item_id)
        if issue_id is not None:
            close_issue(client, issue_id)
            result.closed_issues.append(issue_id)

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

    # Pass 2: parents, rolling their children's synced Status up first.
    for item_id in parent_item_ids:
        facts = facts_by_item_id[item_id]
        child_ids = child_content_ids_by_item_id.get(item_id, [])
        child_in_progress_count = sum(
            1
            for child_id in child_ids
            if status_by_item_id.get(item_id_by_content_id.get(child_id))
            == Status.IN_PROGRESS
        )
        rolled_up_facts = replace(
            facts, child_in_progress_count=child_in_progress_count
        )
        status_by_item_id[item_id] = sync_status(rolled_up_facts)

    # Write back in the Project's original item order. A card already showing
    # the synced Status is left untouched: re-writing the same option id is a
    # no-op on GitHub's side, so we skip it to save an API call and avoid any
    # needless board churn. A closed card is never written at all: its Status
    # is already owned by the native "closed -> Done" Project workflow, and a
    # finished effort's closed cards would otherwise dominate every sweep's
    # write volume as N grows. Its synced Status is still computed above (it
    # feeds the child roll-up and the future map-cascade), just not written.
    for item_id in item_order:
        if item_id not in facts_by_item_id:
            continue  # already recorded in skipped_contentless
        status = status_by_item_id[item_id]
        if status is None:  # a map: no work-Status, never forced into a column
            result.skipped_maps.append(item_id)
            continue
        if facts_by_item_id[item_id].closed:
            result.skipped_closed.append((item_id, status))
            continue
        target_option_id = status_field.option_id_for(status)
        if current_option_id_by_item_id.get(item_id) == target_option_id:
            result.unchanged.append((item_id, status))
            continue
        write_status(client, project_id, item_id, status_field, status)
        result.written.append((item_id, status))

    return result

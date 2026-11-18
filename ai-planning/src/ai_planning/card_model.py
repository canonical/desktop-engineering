"""The pure card model: what a card is, which PRs belong on the board, and
which stamps each card carries.

Everything here is label-and-structure logic over native GitHub facts — no
network, no configuration. The sweep (`job`) feeds it raw reads and applies
what it decides; this module holds every rule so the tests can pin the whole
board behaviour without a client.

## Card typing (labels first)

- `wayfinder:map`                       -> a map. Never status-written; its
    `Map` stamp is itself (the section header's clickable entry).
- `wayfinder:research|grilling|prototype|task` -> a phase-1 decision ticket.
    Never vanishes, never carries a PR; the plain Ready/Blocked/In
    progress/Done ladder.
- any other issue is typed by **tree position**: a child of a map is a
    **spec**; a child of a spec is an **implementation ticket**; anything
    else (no wayfinder type, no map ancestry) is **standalone**. The parent
    chain comes from GitHub's own sub-issue edges, so no label is needed to
    tell a spec from an implementation ticket — only the wayfinder labels
    separate decision work from everything else.

## Which PRs are cards

- **spec PR**: its head branch is `<spec-slug>/base`. It implements one spec
  (its `Closes #<spec>` link names it) and carries the spec's whole lifecycle.
- **stack PR** (a ticket's PR, or a fix PR on top): its base ref is either a
  `<spec-slug>/base` branch or the head branch of another stack PR — the
  chain closure over the repo's open PRs, so a fix PR stacked above a ticket
  PR is carded without carrying any ticket link of its own.
- anything else (a standalone PR into `main`) is not a card.

## Stamps (the two single-select fields that place cards in views)

`Map` places a card in the Maps/Efforts surfaces; `Spec` places it in the
Specs surface. Both are *computed* every sweep and self-heal:

- map card            -> Map = itself.
- phase-1 ticket      -> Map = its map.
- spec, no open spec PR -> Map = its map, Spec = itself.
- spec, spec PR open  -> no stamps at all: the spec **vanishes** from the
  planning surfaces and its spec PR card replaces it there (Map = the spec's
  map, Spec = the spec).
- implementation ticket, no open PR -> Spec = its spec (Map stays empty: it
  is a grandchild — *Parent issue* places it in the tree views, not a stamp).
- implementation ticket, PR open -> no Spec: it vanishes from Specs while
  its PR card carries the work; it stays in the tree views via its parent.
- spec PR card        -> Map = the spec's map, Spec = the spec.
- stack/fix PR card   -> Spec = the spec its chain bottoms out in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAP_LABEL = "wayfinder:map"
PHASE1_LABELS = (
    "wayfinder:research",
    "wayfinder:grilling",
    "wayfinder:prototype",
    "wayfinder:task",
)

_SPEC_BASE_RE = re.compile(r"^[^/]+/base$")


def label_names(content: dict[str, Any]) -> list[str]:
    """An issue/PR's label names, defensively read.

    Accepts both the GraphQL connection shape (`{"nodes": [...]}`) and a bare
    node list, so callers can pass either.
    """

    labels = content.get("labels")
    if isinstance(labels, list):
        nodes = labels
    else:
        nodes = (labels or {}).get("nodes") or []
    return [node["name"] for node in nodes if isinstance(node, dict) and node.get("name")]


def is_map_content(content: dict[str, Any]) -> bool:
    """True when the content carries the map label."""

    return MAP_LABEL in label_names(content)


def is_phase1_content(content: dict[str, Any]) -> bool:
    """True when the content carries any wayfinder decision-ticket label."""

    return any(label in PHASE1_LABELS for label in label_names(content))


@dataclass(frozen=True)
class CardType:
    """What a card is, derived from labels and tree position.

    `map_id` / `spec_id` are the content node ids of the card's root map and
    owning spec (the card itself for a map / spec card); `None` when the card
    sits outside that relationship (a standalone issue, or an implementation
    ticket whose spec somehow can't be resolved).
    """

    kind: str  # "map" | "phase1" | "spec" | "impl" | "standalone"
    map_id: str | None = None
    spec_id: str | None = None


def type_issue_card(
    content: dict[str, Any],
    parent_content: dict[str, Any] | None,
    parent_type: CardType | None,
) -> CardType:
    """Type one issue card from its labels and its direct parent's type.

    `parent_content` is the issue's native `parent` (or None for a root
    issue); `parent_type` is the already-typed card of that parent (the job
    types maps first, then walks down). The parent's own labels decide
    map-vs-spec when the parent's type is unavailable (an off-board parent):
    a map-labelled parent makes this a spec, anything else leaves this
    standalone.
    """

    if is_map_content(content):
        return CardType("map", map_id=content.get("id"))
    if is_phase1_content(content):
        if parent_content is not None and is_map_content(parent_content):
            return CardType("phase1", map_id=parent_content.get("id"))
        return CardType("phase1")
    if parent_content is None:
        return CardType("standalone")
    if is_map_content(parent_content):
        return CardType("spec", map_id=parent_content.get("id"), spec_id=content.get("id"))
    if parent_type is not None and parent_type.kind == "spec":
        return CardType("impl", map_id=parent_type.map_id, spec_id=parent_type.spec_id)
    return CardType("standalone")


def is_spec_pr(head_ref: str | None) -> bool:
    """True when a PR's head branch is a spec branch (`<spec-slug>/base`)."""

    return bool(head_ref) and bool(_SPEC_BASE_RE.match(head_ref))


def stack_family_pr_numbers(
    prs: list[dict[str, Any]],
) -> set[int]:
    """The numbers of the open PRs belonging to spec-branch stacks.

    `prs` are the repo's open PRs, each with `number`, `baseRefName` and
    `headRefName`. A PR is in the family when its base chain bottoms out in a
    spec branch: the bottom stack PR targets `<spec-slug>/base` directly, and
    every PR above it (including review-fix PRs, which carry no ticket link)
    targets the branch below it. The walk is a fixed-point closure so any
    chain depth works.
    """

    heads_by_number = {
        pr["number"]: pr.get("headRefName")
        for pr in prs
        if pr.get("number") is not None
    }
    family: set[int] = {
        pr["number"] for pr in prs if is_spec_pr(pr.get("headRefName"))
    }
    changed = True
    while changed:
        changed = False
        for pr in prs:
            number = pr["number"]
            if number in family:
                continue
            base = pr.get("baseRefName")
            if base is not None and (
                _SPEC_BASE_RE.match(base) or _head_of_family(base, heads_by_number, family)
            ):
                family.add(number)
                changed = True
    return family


def _head_of_family(
    base: str, heads_by_number: dict[int, str | None], family: set[int]
) -> bool:
    """True when `base` is the head branch of a PR already in the family."""

    return any(head == base for number, head in heads_by_number.items() if number in family)


@dataclass(frozen=True)
class StampPlan:
    """The stamps one card should carry, as field-name -> option-name.

    Keyed by the card's *content* id (the job maps content ids to Project
    item ids). An absent key means "leave untouched"; a `None` value means
    "clear the field" (the vanish). Option *names* are used here and resolved
    to ids by the job, so this module never touches GraphQL.
    """

    content_id: str
    stamps: dict[str, str | None]


def compute_stamps(
    typed_cards: dict[str, CardType],
    issue_ids_with_open_pr: set[str],
    pr_card_meta: dict[str, dict[str, str | None]],
    option_name_by_content_id: dict[str, dict[str, str]],
) -> list[StampPlan]:
    """The stamp writes this sweep should make, as a list of plans.

    `typed_cards` maps content id -> CardType for every issue card on the
    board. `issue_ids_with_open_pr` is the set of ISSUE content ids that an
    OPEN closing-linked PR closes — a card in that set is the vanish case.
    `pr_card_meta` maps a PR card's content id to its kind (`"spec"` or
    `"stack"`) and, for both, the content id of the spec it implements
    (`spec_content_id`). `option_name_by_content_id` maps a map or spec
    content id to the option name its field should carry (the `<title>
    #<n>` the option was created with).

    The rules (see the module docstring) reduce to: an issue card whose own
    PR is open loses the stamps that would place it next to that PR (the
    vanish, self-healing on the PR's close); a spec loses both, an
    implementation ticket only Spec; PR cards carry the stamps of the spec
    they implement, and a spec PR additionally carries its map.
    """

    plans: list[StampPlan] = []
    for content_id, card_type in typed_cards.items():
        stamps: dict[str, str | None] = {}
        if card_type.kind == "map":
            name = option_name_by_content_id.get(content_id, {}).get("map")
            if name is not None:
                stamps["Map"] = name
        elif card_type.kind == "phase1":
            if card_type.map_id is not None:
                name = option_name_by_content_id.get(card_type.map_id, {}).get("map")
                if name is not None:
                    stamps["Map"] = name
        elif card_type.kind == "spec":
            spec_name = option_name_by_content_id.get(content_id, {}).get("spec")
            map_name = (
                option_name_by_content_id.get(card_type.map_id, {}).get("map")
                if card_type.map_id is not None
                else None
            )
            if content_id in issue_ids_with_open_pr:
                if map_name is not None:
                    stamps["Map"] = None
                if spec_name is not None:
                    stamps["Spec"] = None
            else:
                if map_name is not None:
                    stamps["Map"] = map_name
                if spec_name is not None:
                    stamps["Spec"] = spec_name
        elif card_type.kind == "impl":
            if card_type.spec_id is None:
                continue
            spec_name = option_name_by_content_id.get(card_type.spec_id, {}).get("spec")
            if spec_name is None:
                continue
            stamps["Spec"] = (
                None if content_id in issue_ids_with_open_pr else spec_name
            )
        if stamps:
            plans.append(StampPlan(content_id=content_id, stamps=stamps))

    for content_id, meta in pr_card_meta.items():
        spec_id = meta.get("spec_content_id")
        if not spec_id:
            continue
        option_names = option_name_by_content_id.get(spec_id, {})
        stamps: dict[str, str | None] = {}
        spec_name = option_names.get("spec")
        if spec_name is not None:
            stamps["Spec"] = spec_name
        if meta.get("kind") == "spec":
            map_name = option_names.get("map")
            if map_name is not None:
                stamps["Map"] = map_name
        if stamps:
            plans.append(StampPlan(content_id=content_id, stamps=stamps))

    return plans

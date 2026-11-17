"""The planning repo's boards: one `all` board plus one board per squad.

A single planning repo feeds several Projects. The `AI_PLANNING_BOARDS` setting
(a repo variable) is a JSON object mapping a board slug to its Project node id:

    {"all": "PVT_...", "apps": "PVT_...", "core": "PVT_..."}

Each value may instead be an object declaring the board's own seed source —
the repo whose open issues seed the board and the labels that filter them
(fallback for both: the caller's planning repo and the slug-derived
`squad:<slug>` label, or no filter for `all`):

    {"warty-whisperer": {
        "project_id": "PVT_...",
        "repo": "canonical/warty-whisperer",
        "labels": ["ready-for-agent", "wayfinder:map"]
    }}

Which issues a board carries is decided by label: the `all` board carries every
open planning-repo issue, a squad board only those labelled `squad:<slug>`. Both
also carry, transitively, every native sub-issue below those (so a spec living in
a code repo follows its Map). Each board keeps its own archived-Map marker, since
archiving a closed Map's tree is a per-board act.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

ALL_BOARD = "all"
SQUAD_LABEL_PREFIX = "squad:"
ARCHIVED_LABEL_PREFIX = "wayfinder:archived:"


class BoardsError(ValueError):
    """`AI_PLANNING_BOARDS` is missing, malformed or lacks a requested board."""


@dataclass(frozen=True)
class Board:
    slug: str
    project_id: str
    # The repo (owner/name) whose open issues seed this board. None: the
    # caller's planning repo (AI_PLANNING_REPO / the action's caller repo).
    repo: str | None = None
    # Explicit seed labels; None: derive from the slug (see `seed_labels`).
    explicit_labels: tuple[str, ...] | None = field(default=None, repr=False)

    @property
    def seed_label(self) -> str | None:
        """Label an issue needs to be seeded onto this board (None: every issue)."""

        return None if self.slug == ALL_BOARD else f"{SQUAD_LABEL_PREFIX}{self.slug}"

    @property
    def seed_labels(self) -> tuple[str, ...] | None:
        """Every label that seeds this board, as a union (None: every issue).

        An explicitly declared board seeds the union of its labels; a derived
        one seeds the single slug-derived label (None: every issue, the `all`
        board)."""

        if self.explicit_labels is not None:
            return self.explicit_labels
        single = self.seed_label
        return None if single is None else (single,)

    @property
    def archived_label(self) -> str:
        return f"{ARCHIVED_LABEL_PREFIX}{self.slug}"


def parse_boards(raw: str | None) -> list[Board]:
    """Parse the `AI_PLANNING_BOARDS` JSON object into boards, in its order."""

    if not raw or not raw.strip():
        raise BoardsError("AI_PLANNING_BOARDS is empty")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise BoardsError(f"AI_PLANNING_BOARDS is not valid JSON: {error}") from error
    if not isinstance(data, dict) or not data:
        raise BoardsError("AI_PLANNING_BOARDS must be a non-empty JSON object")
    boards = []
    for slug, value in data.items():
        if isinstance(value, str):
            if not value:
                raise BoardsError(f"board {slug!r} has no Project id")
            boards.append(Board(slug=slug, project_id=value))
            continue
        if not isinstance(value, dict):
            raise BoardsError(
                f"board {slug!r} must be a Project id or an object with one"
            )
        project_id = value.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise BoardsError(f"board {slug!r} has no Project id")
        repo = value.get("repo")
        if repo is not None and (
            not isinstance(repo, str) or repo.count("/") != 1 or not repo.strip()
        ):
            raise BoardsError(f"board {slug!r} has an invalid repo (want owner/name)")
        labels = value.get("labels")
        if labels is not None:
            if (
                not isinstance(labels, list)
                or not labels
                or not all(isinstance(label, str) and label for label in labels)
            ):
                raise BoardsError(
                    f"board {slug!r} has invalid labels (want a non-empty list of strings)"
                )
            labels = tuple(labels)
        boards.append(
            Board(slug=slug, project_id=project_id, repo=repo, explicit_labels=labels)
        )
    return boards


def select_board(boards: list[Board], slug: str) -> Board:
    for board in boards:
        if board.slug == slug:
            return board
    known = ", ".join(board.slug for board in boards)
    raise BoardsError(f"unknown board {slug!r} (known: {known})")

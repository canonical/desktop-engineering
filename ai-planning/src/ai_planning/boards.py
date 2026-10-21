"""The planning repo's boards: one `all` board plus one board per squad.

A single planning repo feeds several Projects. The `AI_PLANNING_BOARDS` setting
(a repo variable) is a JSON object mapping a board slug to its Project node id:

    {"all": "PVT_...", "apps": "PVT_...", "core": "PVT_..."}

Which issues a board carries is decided by label: the `all` board carries every
open planning-repo issue, a squad board only those labelled `squad:<slug>`. Both
also carry, transitively, every native sub-issue below those (so a spec living in
a code repo follows its Map). Each board keeps its own archived-Map marker, since
archiving a closed Map's tree is a per-board act.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

ALL_BOARD = "all"
SQUAD_LABEL_PREFIX = "squad:"
ARCHIVED_LABEL_PREFIX = "wayfinder:archived:"


class BoardsError(ValueError):
    """`AI_PLANNING_BOARDS` is missing, malformed or lacks a requested board."""


@dataclass(frozen=True)
class Board:
    slug: str
    project_id: str

    @property
    def seed_label(self) -> str | None:
        """Label an issue needs to be seeded onto this board (None: every issue)."""

        return None if self.slug == ALL_BOARD else f"{SQUAD_LABEL_PREFIX}{self.slug}"

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
    for slug, project_id in data.items():
        if not isinstance(project_id, str) or not project_id:
            raise BoardsError(f"board {slug!r} has no Project id")
        boards.append(Board(slug=slug, project_id=project_id))
    return boards


def select_board(boards: list[Board], slug: str) -> Board:
    for board in boards:
        if board.slug == slug:
            return board
    known = ", ".join(board.slug for board in boards)
    raise BoardsError(f"unknown board {slug!r} (known: {known})")

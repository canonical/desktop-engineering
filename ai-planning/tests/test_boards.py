import json

import pytest

from ai_planning.boards import (
    ALL_BOARD,
    Board,
    BoardsError,
    parse_boards,
    select_board,
)


def test_parse_boards_keeps_order_and_ids():
    boards = parse_boards(json.dumps({"all": "PVT_all", "apps": "PVT_apps"}))

    assert boards == [Board("all", "PVT_all"), Board("apps", "PVT_apps")]


def test_all_board_seeds_every_issue():
    assert Board(ALL_BOARD, "PVT_all").seed_label is None


def test_squad_board_seeds_only_its_squad_label():
    assert Board("apps", "PVT_apps").seed_label == "squad:apps"


def test_each_board_has_its_own_archived_marker():
    assert Board("all", "x").archived_label == "wayfinder:archived:all"
    assert Board("wsl", "x").archived_label == "wayfinder:archived:wsl"


@pytest.mark.parametrize(
    "raw", [None, "", "  ", "not json", "[]", "{}", '{"apps": ""}', '{"apps": 3}']
)
def test_parse_boards_rejects_bad_input(raw):
    with pytest.raises(BoardsError):
        parse_boards(raw)


def test_select_board_names_the_known_boards_when_missing():
    boards = parse_boards('{"all": "A", "apps": "B"}')

    assert select_board(boards, "apps").project_id == "B"
    with pytest.raises(BoardsError, match="known: all, apps"):
        select_board(boards, "gaming")

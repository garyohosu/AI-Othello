import pytest

import game
from game import BLACK, WHITE

INITIAL_TEXT = (
    "□□□□□□□□\n"
    "□□□□□□□□\n"
    "□□□□□□□□\n"
    "□□□〇●□□□\n"
    "□□□●〇□□□\n"
    "□□□□□□□□\n"
    "□□□□□□□□\n"
    "□□□□□□□□\n"
)


def board_from(rows: list[str]) -> game.Board:
    return game.parse_board("\n".join(rows))


def test_initial_board_matches_spec():
    assert game.format_board(game.initial_board()) == INITIAL_TEXT
    assert game.parse_board(INITIAL_TEXT) == game.initial_board()


def test_stone_code_points():
    assert game.BLACK_STONE == "●"
    assert game.WHITE_STONE == "〇"
    assert game.EMPTY == "□"


def test_parse_accepts_missing_final_newline():
    assert game.parse_board(INITIAL_TEXT.rstrip("\n")) == game.initial_board()


@pytest.mark.parametrize(
    "text",
    [
        INITIAL_TEXT.replace("〇", "○", 1),  # U+25CB は不正
        INITIAL_TEXT + "□□□□□□□□\n",  # 9行
        INITIAL_TEXT.replace("□□□□□□□□\n", "□□□□□□□\n", 1),  # 7文字
        "A " + INITIAL_TEXT,
        "﻿" + INITIAL_TEXT,
    ],
)
def test_parse_rejects_invalid_board(text):
    with pytest.raises(game.BoardFormatError):
        game.parse_board(text)


def test_coordinates():
    assert game.coord_to_index("A1") == (0, 0)
    assert game.coord_to_index("H8") == (7, 7)
    assert game.coord_to_index("D3") == (2, 3)
    assert game.index_to_coord(2, 3) == "D3"
    for bad in ["d3", "I1", "A9", "A0", "", "D33"]:
        with pytest.raises(ValueError):
            game.coord_to_index(bad)


def test_initial_legal_moves_black():
    assert sorted(game.legal_moves(game.initial_board(), BLACK)) == ["C4", "D3", "E6", "F5"]


def test_initial_legal_moves_white():
    assert sorted(game.legal_moves(game.initial_board(), WHITE)) == ["C5", "D6", "E3", "F4"]


def test_first_move_flips():
    board = game.apply_move(game.initial_board(), BLACK, "D3")
    assert game.format_board(board) == (
        "□□□□□□□□\n"
        "□□□□□□□□\n"
        "□□□●□□□□\n"
        "□□□●●□□□\n"
        "□□□●〇□□□\n"
        "□□□□□□□□\n"
        "□□□□□□□□\n"
        "□□□□□□□□\n"
    )
    assert game.count_stones(board) == {BLACK: 4, WHITE: 1, "empty": 59}


@pytest.mark.parametrize(
    "rows, move, expected_flips",
    [
        # 各方向を個別に検証する（D4 に黒を打つ）
        (["□□□□□□□□", "□□□●□□□□", "□□□〇□□□□", "□□□□□□□□"] + ["□□□□□□□□"] * 4, "D4", ["D3"]),  # 上
        (["□□□□□□□□"] * 3 + ["□□□□□□□□", "□□□〇□□□□", "□□□●□□□□"] + ["□□□□□□□□"] * 2, "D4", ["D5"]),  # 下
        (["□□□□□□□□"] * 3 + ["□●〇□□□□□"] + ["□□□□□□□□"] * 4, "D4", ["C4"]),  # 左
        (["□□□□□□□□"] * 3 + ["□□□□〇●□□"] + ["□□□□□□□□"] * 4, "D4", ["E4"]),  # 右
        (["□□□□□□□□", "□●□□□□□□", "□□〇□□□□□"] + ["□□□□□□□□"] * 5, "D4", ["C3"]),  # 左上
        (["□□□□□□□□", "□□□□□●□□", "□□□□〇□□□"] + ["□□□□□□□□"] * 5, "D4", ["E3"]),  # 右上
        (["□□□□□□□□"] * 4 + ["□□〇□□□□□", "□●□□□□□□"] + ["□□□□□□□□"] * 2, "D4", ["C5"]),  # 左下
        (["□□□□□□□□"] * 4 + ["□□□□〇□□□", "□□□□□●□□"] + ["□□□□□□□□"] * 2, "D4", ["E5"]),  # 右下
    ],
    ids=["up", "down", "left", "right", "up-left", "up-right", "down-left", "down-right"],
)
def test_flip_each_direction(rows, move, expected_flips):
    board = board_from(rows)
    assert game.flips_for(board, BLACK, move) == expected_flips
    after = game.apply_move(board, BLACK, move)
    for coord in expected_flips:
        r, c = game.coord_to_index(coord)
        assert after[r][c] == game.BLACK_STONE


def test_flip_all_eight_directions_at_once():
    rows = [
        "□●□●□●□□",
        "□□〇〇〇□□□",
        "□●〇□〇●□□",
        "□□〇〇〇□□□",
        "□●□●□●□□",
        "□□□□□□□□",
        "□□□□□□□□",
        "□□□□□□□□",
    ]
    board = board_from(rows)
    after = game.apply_move(board, BLACK, "D3")
    assert game.count_stones(after) == {BLACK: 8 + 1 + 8, WHITE: 0, "empty": 64 - 17}


def test_flip_multiple_stones_in_a_line_and_stop_at_own_stone():
    board = board_from(["□〇〇〇●〇〇●"] + ["□□□□□□□□"] * 7)
    after = game.apply_move(board, BLACK, "A1")
    assert after[0] == "●●●●●〇〇●"


def test_no_flip_without_closing_stone():
    board = board_from(["□〇〇〇□□□□"] + ["□□□□□□□□"] * 7)
    assert game.flips_for(board, BLACK, "A1") == []


def test_illegal_move_does_not_change_board():
    board = game.initial_board()
    for coord in ["A1", "D4", "E5", "H8"]:
        with pytest.raises(game.IllegalMoveError):
            game.apply_move(board, BLACK, coord)
    assert board == game.initial_board()


def test_apply_move_is_pure():
    board = game.initial_board()
    game.apply_move(board, BLACK, "D3")
    assert board == game.initial_board()


def test_pass_situation_one_side_has_no_moves():
    # 白は打てるが黒は打てない
    board = board_from(["〇〇●□□□□□"] + ["□□□□□□□□"] * 7)
    assert game.legal_moves(board, BLACK) == []
    assert game.legal_moves(board, WHITE) == ["D1"]
    assert not game.is_game_over(board)


def test_game_over_when_both_have_no_moves():
    board = board_from(["●●□□□□□□"] + ["□□□□□□□□"] * 7)
    assert game.is_game_over(board)
    assert game.winner(board) == BLACK


def test_game_over_when_full_and_draw():
    board = board_from(["●●●●〇〇〇〇"] * 8)
    assert game.is_game_over(board)
    assert game.count_stones(board) == {BLACK: 32, WHITE: 32, "empty": 0}
    assert game.winner(board) is None


def test_winner_white():
    board = board_from(["〇〇〇●□□□□"] + ["□□□□□□□□"] * 7)
    assert game.winner(board) == WHITE


def test_initial_game_not_over():
    assert not game.is_game_over(game.initial_board())


def test_opponent():
    assert game.opponent(BLACK) == WHITE
    assert game.opponent(WHITE) == BLACK
    with pytest.raises(ValueError):
        game.opponent("red")

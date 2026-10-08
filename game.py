"""オセロのルールエンジン。

盤面は8要素のタプル（各要素は8文字の文字列）で表す。すべて純粋関数で、
引数の盤面を変更しない。
"""

from __future__ import annotations

import hashlib

BLACK = "black"
WHITE = "white"

BLACK_STONE = "●"  # U+25CF
WHITE_STONE = "〇"  # U+3007（U+25CB の ○ ではない）
EMPTY = "□"  # U+25A1

STONE = {BLACK: BLACK_STONE, WHITE: WHITE_STONE}
COLOR_NAME_JA = {BLACK: "黒", WHITE: "白"}

SIZE = 8
COLUMNS = "ABCDEFGH"
DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

Board = tuple[str, ...]


class BoardFormatError(ValueError):
    """board.txt の形式が不正。"""


class IllegalMoveError(ValueError):
    """合法手ではない着手。"""


def opponent(color: str) -> str:
    if color == BLACK:
        return WHITE
    if color == WHITE:
        return BLACK
    raise ValueError(f"unknown color: {color!r}")


def initial_board() -> Board:
    rows = [EMPTY * SIZE for _ in range(SIZE)]
    rows[3] = EMPTY * 3 + WHITE_STONE + BLACK_STONE + EMPTY * 3
    rows[4] = EMPTY * 3 + BLACK_STONE + WHITE_STONE + EMPTY * 3
    return tuple(rows)


def parse_board(text: str) -> Board:
    """board.txt の文字列を盤面に変換する。最終行の改行は有無を問わない。"""
    if text.startswith("﻿"):
        raise BoardFormatError("BOM付きUTF-8は扱わない")
    body = text[:-1] if text.endswith("\n") else text
    rows = body.split("\n")
    if len(rows) != SIZE:
        raise BoardFormatError(f"行数が{SIZE}ではない: {len(rows)}")
    allowed = {BLACK_STONE, WHITE_STONE, EMPTY}
    for i, row in enumerate(rows, start=1):
        if len(row) != SIZE:
            raise BoardFormatError(f"{i}行目の文字数が{SIZE}ではない: {len(row)}")
        bad = set(row) - allowed
        if bad:
            raise BoardFormatError(f"{i}行目に不正な文字: {''.join(sorted(bad))!r}")
    return tuple(rows)


def format_board(board: Board) -> str:
    """盤面を board.txt の文字列にする（各行末と最終行末にLF）。"""
    return "".join(row + "\n" for row in board)


def board_sha256(board: Board) -> str:
    return hashlib.sha256(format_board(board).encode("utf-8")).hexdigest()


def coord_to_index(coord: str) -> tuple[int, int]:
    """'D3' -> (行, 列) = (2, 3)。大文字のA1～H8のみ受け付ける。"""
    if len(coord) != 2 or coord[0] not in COLUMNS or coord[1] not in "12345678":
        raise ValueError(f"invalid coordinate: {coord!r}")
    return int(coord[1]) - 1, COLUMNS.index(coord[0])


def index_to_coord(row: int, col: int) -> str:
    if not (0 <= row < SIZE and 0 <= col < SIZE):
        raise ValueError(f"out of board: {(row, col)}")
    return f"{COLUMNS[col]}{row + 1}"


def _flips(board: Board, color: str, row: int, col: int) -> list[tuple[int, int]]:
    if board[row][col] != EMPTY:
        return []
    mine = STONE[color]
    theirs = STONE[opponent(color)]
    result: list[tuple[int, int]] = []
    for dr, dc in DIRECTIONS:
        r, c = row + dr, col + dc
        line: list[tuple[int, int]] = []
        while 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == theirs:
            line.append((r, c))
            r, c = r + dr, c + dc
        if line and 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == mine:
            result.extend(line)
    return result


def flips_for(board: Board, color: str, coord: str) -> list[str]:
    """coord に置いたとき反転する石の座標一覧。"""
    row, col = coord_to_index(coord)
    return [index_to_coord(r, c) for r, c in _flips(board, color, row, col)]


def legal_moves(board: Board, color: str) -> list[str]:
    """合法手を行優先（A1, B1, ..., H8）の順で返す。"""
    return [
        index_to_coord(r, c)
        for r in range(SIZE)
        for c in range(SIZE)
        if _flips(board, color, r, c)
    ]


def has_legal_move(board: Board, color: str) -> bool:
    return any(_flips(board, color, r, c) for r in range(SIZE) for c in range(SIZE))


def apply_move(board: Board, color: str, coord: str) -> Board:
    """着手して反転した新しい盤面を返す。非合法なら IllegalMoveError。"""
    row, col = coord_to_index(coord)
    flips = _flips(board, color, row, col)
    if not flips:
        raise IllegalMoveError(f"{coord} は{COLOR_NAME_JA[color]}の合法手ではない")
    cells = [list(r) for r in board]
    stone = STONE[color]
    cells[row][col] = stone
    for r, c in flips:
        cells[r][c] = stone
    return tuple("".join(r) for r in cells)


def count_stones(board: Board) -> dict[str, int]:
    text = "".join(board)
    return {
        BLACK: text.count(BLACK_STONE),
        WHITE: text.count(WHITE_STONE),
        "empty": text.count(EMPTY),
    }


def is_game_over(board: Board) -> bool:
    """盤面が満杯、または両者とも合法手がなければ終局。"""
    if count_stones(board)["empty"] == 0:
        return True
    return not has_legal_move(board, BLACK) and not has_legal_move(board, WHITE)


def winner(board: Board) -> str | None:
    """石が多い色を返す。同数なら None（引き分け）。"""
    counts = count_stones(board)
    if counts[BLACK] > counts[WHITE]:
        return BLACK
    if counts[WHITE] > counts[BLACK]:
        return WHITE
    return None

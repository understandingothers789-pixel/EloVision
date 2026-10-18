from pathlib import Path

import chess
import pytest

from elovision.chess_state import parse_pgn, replay_position, valid_board
from elovision.errors import VisionError


def test_opera_game_navigation_and_checkmate():
    game = parse_pgn(Path("samples/opera-game.pgn").read_text())["games"][0]
    assert len(game["moves"]) == 33
    assert len(game["positions"]) == 34
    assert game["positions"][0]["actual_move"] == "e2e4"
    assert game["positions"][1]["turn"] == "black"
    assert game["positions"][1]["pieces"]["e4"] == "P"
    assert game["positions"][-1]["outcome"] == "Checkmate"
    assert game["positions"][-1]["actual_move"] is None
    for ply, position in enumerate(game["positions"]):
        board = replay_position(
            position["fen"], game["initial_fen"], [m["uci"] for m in game["moves"][:ply]]
        )
        assert board.fen(en_passant="fen") == position["fen"]


def test_multiple_games_variations_and_bom():
    data = parse_pgn(
        '\ufeff[White "A"]\n\n1. e4 (1. d4 d5) e5 2. Nf3 *\n\n[White "B"]\n\n1. d4 d5 *'
    )
    assert len(data["games"]) == 2
    assert [m["san"] for m in data["games"][0]["moves"]] == ["e4", "e5", "Nf3"]
    assert data["games"][1]["headers"]["White"] == "B"


def test_custom_fen_black_to_move():
    pgn = '[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/8/4K2R b K - 0 30"]\n\n30... Kd7 *'
    game = parse_pgn(pgn)["games"][0]
    assert game["moves"][0]["color"] == "black"
    assert game["moves"][0]["number"] == 30
    assert game["positions"][1]["pieces"]["d7"] == "k"


@pytest.mark.parametrize("text", ["", "nonsense, this is not chess", "1. e4 e5 2. Ke3 *"])
def test_invalid_pgn_is_actionable(text):
    with pytest.raises(VisionError):
        parse_pgn(text)


def test_history_must_match_fen():
    with pytest.raises(VisionError, match="does not lead"):
        replay_position(chess.STARTING_FEN, chess.STARTING_FEN, ["e2e4"])
    with pytest.raises(VisionError, match="Illegal history"):
        replay_position(chess.STARTING_FEN, chess.STARTING_FEN, ["e2e5"])
    with pytest.raises(VisionError):
        valid_board("8/8/8/8/8/8/8/8 w - - 0 1")


def test_malformed_starting_fen_is_actionable():
    with pytest.raises(VisionError):
        parse_pgn('[SetUp "1"]\n[FEN "not a chess position"]\n\n*')

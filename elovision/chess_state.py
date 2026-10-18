"""PGN and position validation, with no inference or UI dependencies."""

import hashlib
import io

import chess
import chess.pgn

from .errors import VisionError

MAX_PGN_BYTES = 2_000_000
MAX_GAMES = 100
MAX_PLIES = 3000


def valid_board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise VisionError("invalid_fen", "Enter a complete, valid standard-chess FEN.") from exc
    if not board.is_valid():
        raise VisionError("invalid_position", "This FEN describes an invalid chess position.")
    return board


def replay_position(fen: str, initial_fen: str | None, moves: list[str]) -> chess.Board:
    target = valid_board(fen)
    if initial_fen is None:
        if moves:
            raise VisionError("missing_history_root", "Move history needs an initial FEN.")
        return target
    if len(moves) > MAX_PLIES:
        raise VisionError("history_too_long", f"History may contain at most {MAX_PLIES} plies.")
    board = valid_board(initial_fen)
    for index, uci in enumerate(moves):
        try:
            board.push_uci(uci)
        except (ValueError, chess.IllegalMoveError) as exc:
            raise VisionError(
                "invalid_history", f"Illegal history move at ply {index + 1}."
            ) from exc
    if board.fen(en_passant="fen") != target.fen(en_passant="fen"):
        raise VisionError("history_mismatch", "Move history does not lead to the supplied FEN.")
    return board


def describe_position(board: chess.Board, last_move=None, next_move=None) -> dict:
    outcome = board.outcome(claim_draw=False)
    return {
        "fen": board.fen(en_passant="fen"),
        "turn": "white" if board.turn else "black",
        "fullmove": board.fullmove_number,
        "check": chess.square_name(board.king(board.turn)) if board.is_check() else None,
        "pieces": {
            chess.square_name(sq): piece.symbol() for sq, piece in board.piece_map().items()
        },
        "last_move": last_move,
        "actual_move": next_move,
        "legal_count": board.legal_moves.count(),
        "outcome": outcome.termination.name.replace("_", " ").title() if outcome else None,
    }


class QuietGameBuilder(chess.pgn.GameBuilder):
    def handle_error(self, error):
        self.game.errors.append(error)


def parse_pgn(text: str) -> dict:
    if not text.strip():
        raise VisionError("empty_pgn", "The PGN is empty. Choose a file containing a game.")
    if len(text.encode("utf-8")) > MAX_PGN_BYTES:
        raise VisionError("pgn_too_large", "PGN files must be smaller than 2 MB.")
    stream = io.StringIO(text.lstrip("\ufeff"))
    games = []
    while (game := chess.pgn.read_game(stream, Visitor=QuietGameBuilder)) is not None:
        if len(games) >= MAX_GAMES:
            raise VisionError("too_many_games", f"Import at most {MAX_GAMES} games at once.")
        if game.errors:
            raise VisionError(
                "invalid_pgn",
                f"Game {len(games) + 1} contains invalid moves: {str(game.errors[0])[:180]}",
            )
        if game.headers.get("Variant", "Standard").lower() not in {"standard", "chess", "normal"}:
            raise VisionError(
                "unsupported_variant", "Only standard chess is supported in version 1."
            )
        try:
            board = valid_board(game.board().fen(en_passant="fen"))
        except ValueError as exc:
            raise VisionError("invalid_pgn_fen", "The PGN's starting FEN is invalid.") from exc
        initial_fen = board.fen(en_passant="fen")
        moves = list(game.mainline_moves())
        if len(moves) > MAX_PLIES:
            raise VisionError("game_too_long", f"A game may contain at most {MAX_PLIES} plies.")
        if not moves and not text.lstrip().startswith("[") and initial_fen == chess.STARTING_FEN:
            raise VisionError(
                "invalid_pgn", "No recognizable PGN headers or chess moves were found."
            )
        positions, notation = [], []
        for i in range(len(moves) + 1):
            positions.append(
                describe_position(
                    board,
                    moves[i - 1].uci() if i else None,
                    moves[i].uci() if i < len(moves) else None,
                )
            )
            if i < len(moves):
                move = moves[i]
                notation.append(
                    {
                        "ply": i + 1,
                        "san": board.san(move),
                        "uci": move.uci(),
                        "number": board.fullmove_number,
                        "color": positions[-1]["turn"],
                    }
                )
                board.push(move)
        games.append(
            {
                "id": hashlib.sha256((text + str(len(games))).encode()).hexdigest()[:16],
                "headers": dict(game.headers),
                "initial_fen": initial_fen,
                "moves": notation,
                "positions": positions,
            }
        )
    if not games:
        raise VisionError("invalid_pgn", "No chess games were found in this file.")
    return {
        "games": games,
        "warnings": [
            "Variations and comments are preserved in the source "
            "file; navigation follows each game's mainline."
        ],
    }

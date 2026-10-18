import math

import chess
import pytest

from elovision.config import RATINGS
from elovision.errors import VisionError
from elovision.inference import PredictionRequest
from elovision.probability import validate_distribution

POSITIONS = [
    chess.STARTING_FEN,
    "r3k2r/ppp2ppp/2n1bn2/3qp3/3P4/2N1PN2/PPP2PPP/R2QKB1R w KQkq - 0 9",
    "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1",
    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
    "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
    "4k3/P7/8/8/8/8/8/4K3 w - - 0 1",
    "4k3/8/8/8/8/8/p7/4K3 b - - 0 1",
]


@pytest.mark.parametrize("fen", POSITIONS)
def test_complete_legal_distribution(service, fen):
    result = service.predict(PredictionRequest(fen))
    assert {m["uci"] for m in result["moves"]} == {m.uci() for m in chess.Board(fen).legal_moves}
    assert math.isclose(sum(m["probability"] for m in result["moves"]), 1)
    assert [m["rank"] for m in result["moves"]] == list(range(1, len(result["moves"]) + 1))


@pytest.mark.parametrize(
    "fen", ["7k/6Q1/6K1/8/8/8/8/8 b - - 0 1", "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"]
)
def test_terminal_positions_never_invent_policy(service, fen):
    result = service.predict(PredictionRequest(fen))
    assert result["moves"] == []
    assert result["probability_sum"] == 0
    assert service.policy.calls == []


def test_linked_ratings_batches_and_independent_api(service):
    for rating in [1600, 2200]:
        prediction = service.predict(PredictionRequest(chess.STARTING_FEN, rating))
        assert prediction["player_elo"] == prediction["opponent_elo"] == rating
        assert service.policy.calls[-1][1] == [(rating, rating)]
    results = service.predict_many(PredictionRequest(chess.STARTING_FEN), [(r, r) for r in RATINGS])
    assert len(results) == 14
    assert [(p["player_elo"], p["opponent_elo"]) for p in results] == [(r, r) for r in RATINGS]
    service.predict(PredictionRequest(chess.STARTING_FEN, 1000, 2400))
    assert service.policy.calls[-1][1] == [(1000, 2400)]


def test_cache_uses_history_ratings_and_model_and_isolation(service):
    request = PredictionRequest(chess.STARTING_FEN)
    first = service.predict(request)
    second = service.predict(request)
    assert not first["cached"] and second["cached"]
    second["moves"][0]["probability"] = 100
    assert service.predict(request)["moves"][0]["probability"] < 1
    service.policy.metadata = {"id": "changed-test-model"}
    assert not service.predict(request)["cached"]
    board = chess.Board()
    moves = ["g1f3", "g8f6", "f3g1", "f6g8"]
    for move in moves:
        board.push_uci(move)
    with_history = PredictionRequest(
        board.fen(), initial_fen=chess.STARTING_FEN, moves=tuple(moves)
    )
    result = service.predict(with_history)
    bare = service.predict(PredictionRequest(board.fen()))
    assert result["position_id"] != bare["position_id"]
    assert service.policy.calls[-2][2] == 4


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.1, 1.2])
def test_invalid_probabilities_fail_closed(bad):
    with pytest.raises(VisionError):
        validate_distribution([{"uci": "e2e4", "probability": bad}], {"e2e4"})


def test_missing_moves_or_unnormalized_policy_fails():
    with pytest.raises(VisionError):
        validate_distribution([{"uci": "e2e4", "probability": 0.7}], {"e2e4"})
    with pytest.raises(VisionError):
        validate_distribution([], {"e2e4"})


@pytest.mark.parametrize("rating", [399, 3001, 1600.5, True])
def test_invalid_rating_is_not_clamped(service, rating):
    with pytest.raises(VisionError):
        service.predict(PredictionRequest(chess.STARTING_FEN, rating))


def test_bounded_lru(service):
    object.__setattr__(service.config, "cache_size", 14)
    for rating in range(400, 440):
        service.predict(PredictionRequest(chess.STARTING_FEN, rating))
    assert service.status()["cache_entries"] == 14
    assert not service.predict(PredictionRequest(chess.STARTING_FEN, 400))["cached"]

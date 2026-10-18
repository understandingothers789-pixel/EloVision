"""Only official, checksum-verified 79M weights may satisfy these integration tests."""

import math

import chess
import pytest

from elovision.config import RATINGS, ModelConfig
from elovision.inference import InferenceService, PredictionRequest

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def real_service():
    config = ModelConfig()
    if not config.checkpoint.exists():
        pytest.skip("Official Maia 3 79M weights are not installed")
    service = InferenceService(config)
    yield service
    service.close()


@pytest.mark.parametrize(
    "fen",
    [
        chess.STARTING_FEN,
        "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
        "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        "4k3/P7/8/8/8/8/8/4K3 w - - 0 1",
        "4k3/8/8/8/8/8/p7/4K3 b - - 0 1",
    ],
)
def test_real_distribution(real_service, fen):
    result = real_service.predict(PredictionRequest(fen))
    assert result["model"]["id"] == "maia3-79m"
    assert {m["uci"] for m in result["moves"]} == {m.uci() for m in chess.Board(fen).legal_moves}
    assert all(math.isfinite(m["probability"]) and m["probability"] >= 0 for m in result["moves"])
    assert math.isclose(result["probability_sum"], 1, abs_tol=1e-6)


def test_real_linked_rating_conditioning_and_cache(real_service):
    request = PredictionRequest(chess.STARTING_FEN)
    results = real_service.predict_many(request, [(r, r) for r in RATINGS])
    assert len(results) == 14
    assert all(p["player_elo"] == p["opponent_elo"] for p in results)
    distributions = [{m["uci"]: m["probability"] for m in p["moves"]} for p in results]
    assert distributions[0] != distributions[-1]
    assert real_service.predict(request)["cached"]

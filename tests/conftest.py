import chess
import pytest

from elovision.config import ModelConfig
from elovision.inference import InferenceService


class RecordingPolicy:
    """Deterministic test double. Never used by the application or real-model tests."""

    metadata = {"id": "test-double", "weights_sha256": "test-only"}

    def __init__(self):
        self.calls = []

    def predict(self, board: chess.Board, ratings: list[tuple[int, int]]):
        self.calls.append((board.fen(), ratings, len(board.move_stack)))
        legal = list(board.legal_moves)
        result = []
        for player, opponent in ratings:
            values = [i + 1 + (player + opponent) / 100 for i in range(len(legal))]
            total = sum(values)
            result.append(
                [
                    {"uci": m.uci(), "san": board.san(m), "probability": v / total}
                    for m, v in zip(legal, values)
                ]
            )
        return result


@pytest.fixture
def service(tmp_path):
    return InferenceService(ModelConfig(model_dir=tmp_path), RecordingPolicy())

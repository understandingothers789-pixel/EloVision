"""Real-model benchmark; writes measurements only after successful inference."""

import json
import time

import chess

from elovision.config import RATINGS
from elovision.inference import InferenceService, PredictionRequest

service = InferenceService()
request = PredictionRequest(chess.STARTING_FEN)
try:
    start = time.perf_counter()
    service.policy.load()
    load = time.perf_counter() - start
    start = time.perf_counter()
    service.predict(request)
    one = time.perf_counter() - start
    start = time.perf_counter()
    # New position avoids reusing the single-rating result above.
    board = chess.Board()
    board.push_uci("e2e4")
    service.predict_many(
        PredictionRequest(board.fen(), initial_fen=chess.STARTING_FEN, moves=("e2e4",)),
        [(r, r) for r in RATINGS],
    )
    batch = time.perf_counter() - start
    start = time.perf_counter()
    for _ in range(100):
        assert service.predict(request)["cached"]
    cached = (time.perf_counter() - start) / 100
    print(
        json.dumps(
            {
                "device": "cpu",
                "threads": service.config.threads,
                "load_seconds": load,
                "single_seconds": one,
                "all_14_seconds": batch,
                "cached_mean_seconds": cached,
            },
            indent=2,
        )
    )
finally:
    service.close()

# Reusing the backend, including future Nocturne integration

The `elovision.inference` module does not import FastAPI or frontend code. Keep this single implementation when adding another GUI; do not copy model logic or use UCI MultiPV as a policy API. No Nocturne code is included in this project.

## Python API, schema 1.0

Install ELO Vision and the official weights as described in the README. `InferenceService` owns a lazy, CPU-only Maia 3 79M model and a bounded cache. Share one service per application session. The first nonterminal request verifies and initializes the checkpoint; `service.policy.load()` may be used for an explicit warm-up.

```python
import chess
from elovision.inference import InferenceService, PredictionRequest

service = InferenceService()
try:
    board = chess.Board()
    board.push_uci("e2e4")
    result = service.predict(PredictionRequest(
        fen=board.fen(en_passant="fen"),
        initial_fen=chess.STARTING_FEN,
        moves=("e2e4",),
        player_elo=1000,
        opponent_elo=1800,  # independent inputs already supported in the backend
    ))
    for move in result["moves"]:
        print(move["uci"], move["san"], move["probability"], move["rank"])
finally:
    service.close()
```

Omitting `opponent_elo` links it to `player_elo`. UI, comparison and export requests always use linked ratings. The Python API accepts integer ratings 400–3000 (not only 200-point slider steps) and rejects out-of-range inputs instead of silently clamping. Pass an `initial_fen` and the full UCI mainline leading to `fen`; inconsistent histories are rejected. Without history, upstream padding repeats the current position and a warning is returned. The model ultimately uses the latest eight positions.

For several rating pairs, call `service.predict_many(request, [(1000, 1000), (2400, 2400)])`. Results preserve pair order and include all legal moves. Return dictionaries are isolated copies; caller mutations cannot poison the cache. `close()` clears model/cache references. Use a worker thread from a GUI; synchronous Python calls intentionally block their caller.

## Response fields

| Field | Meaning |
| --- | --- |
| `schema_version` | `1.0`; additive fields may be introduced within this version |
| `position_id` | SHA-256 of position/history and model configuration |
| `fen`, `initial_fen`, `history` | Exact validated position and supplied context |
| `side_to_move` | `white` or `black` |
| `player_elo`, `opponent_elo` | Actual rating inputs, never UI labels alone |
| `moves` | Complete probability-sorted list of `{uci, san, probability, rank}` |
| `probability_sum` | Approximately 1 for playable positions; 0 if no legal moves |
| `model` | Model ID, weights revision/SHA-256, upstream source revision, CPU float32, history size, masking/softmax settings, and rating system |
| `warnings` | Human-readable caveats about interpretation, history and rating coverage |
| `terminal` | python-chess outcome identifier or null |
| `cached`, `elapsed_ms` | Cache status and time for this call (not a hardware benchmark) |

There are no illustrative numeric policy responses here: obtain an actual response from a verified installed model. Every probability is a unit-interval float, not a percentage, logit, score or sampled frequency. All legal moves, including underpromotions, have entries. Illegal moves have zero probability in the masked vocabulary and are omitted from the returned legal-move list.

## Local HTTP API

Start `python -m elovision serve`. The service binds only to loopback. API documentation is at `/docs` on that server; schema at `/openapi.json`. A different GUI may call it from its native process. Browser cross-origin access is intentionally rejected; another browser GUI must use a same-origin bridge rather than enabling permissive CORS.

```http
POST /api/v1/predict
Content-Type: application/json

{
  "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
  "player_elo": 1000,
  "opponent_elo": 1800
}
```

Endpoints:

- `GET /api/v1/health`: installation/loading/cache status; does not trigger model loading.
- `POST /api/v1/position`: `{fen}` → board description.
- `POST /api/v1/pgn`: `{pgn}` → game metadata, mainline moves and position states.
- `POST /api/v1/predict`: position/history and independent rating inputs → one prediction.
- `POST /api/v1/analyze`: position/history and `ratings: [1000,2400]` → `{schema_version, predictions}` using linked pairs.
- `POST /api/v1/export`: same as analyze, plus `format: "csv" | "json"`, optional `game_id` and `ply`. Reuses computed/cache probabilities and retains float precision.

## Failures and lifecycle

Python raises `VisionError` with `code`, message and HTTP `status`; HTTP responds with `{"error":{"code":"…","message":"…"}}`. Key codes: `model_missing`, `model_checksum`, `model_initialization`, `invalid_rating`, `invalid_fen`, `invalid_position`, `invalid_history`, `history_mismatch`, `invalid_policy`, and `busy`. Missing/corrupt models are 503, invalid inputs 400/422, invalid output 500, and queue saturation 429. Show actionable errors; never substitute a synthetic policy.

Model execution is serialized, with at most four admitted HTTP work requests; rating batches are internally chunked to four. A bounded LRU (1024 predictions) includes full supplied history, exact FEN including counters/castling/en-passant, both ratings, weights identity, source revision and inference settings. The frontend debounces changes and rejects superseded responses. Aborting a request can cancel queued work but cannot interrupt an already running PyTorch call.

Restart the service after installing different weights. Ctrl+C cleanly shuts down the server and its executor. Run `python scripts/benchmark.py` to measure initialization, one rating, all 14 ratings and repeated cache hits on the actual machine. Target Windows latency and AMD GPU acceleration are not yet verified.

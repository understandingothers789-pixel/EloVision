"""Version 1 Python inference interface. No FastAPI, HTML, or frontend state here."""

import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Protocol

import chess

from .chess_state import replay_position
from .config import UPSTREAM_REVISION, ModelConfig
from .errors import VisionError
from .model_files import verified_manifest
from .probability import validate_distribution


@dataclass(frozen=True)
class PredictionRequest:
    fen: str
    player_elo: int = 1600
    opponent_elo: int | None = None
    initial_fen: str | None = None
    moves: tuple[str, ...] = field(default_factory=tuple)


class PolicyModel(Protocol):
    metadata: dict

    def predict(self, board: chess.Board, ratings: list[tuple[int, int]]) -> list[list[dict]]: ...


class MaiaPolicy:
    """Adapter to the pinned official model, preprocessing and move vocabulary."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.model = None
        self.metadata = {}
        self.load_seconds = None

    def load(self):
        if self.model is not None:
            return
        started = time.perf_counter()
        manifest = verified_manifest(self.config)
        try:
            import torch
            from maia3.models import MAIA3Model
            from maia3.uci import parse_args
            from maia3.utils import get_all_possible_moves

            torch.set_num_threads(self.config.threads)
            self.cfg = parse_args(["--model", "maia3-79m", "--device", "cpu", "--no-use-amp"])
            self.cfg.checkpoint_path = str(self.config.checkpoint)
            model = MAIA3Model(self.cfg)
            checkpoint = torch.load(self.config.checkpoint, map_location="cpu", weights_only=True)
            state = checkpoint.get("model_state_dict", checkpoint)
            # Same legacy key mapping as official load_model, with strict validation.
            state = {key.replace("smolgen", "gab"): value for key, value in state.items()}
            model.load_state_dict(state, strict=True)
            self.model = model.eval()
            self.vocabulary = {move: i for i, move in enumerate(get_all_possible_moves())}
            self.metadata = {
                "id": "maia3-79m",
                "weights_sha256": manifest["sha256"],
                "weights_revision": manifest["revision"],
                "source_revision": UPSTREAM_REVISION,
                "device": "cpu",
                "precision": "float32",
                "history_positions": 8,
                "policy": "legal-mask-softmax",
                "temperature": 1,
                "top_p": 1,
                "rating_system": "Lichess blitz",
            }
            self.load_seconds = time.perf_counter() - started
        except (ImportError, RuntimeError, ValueError, OSError, KeyError) as exc:
            self.model = None
            raise VisionError(
                "model_initialization",
                "Maia 3 could not initialize. Check the "
                "pinned dependencies and reinstall the official weights. "
                f"Details: {str(exc)[:240]}",
                503,
            ) from exc

    def predict(self, board: chess.Board, ratings: list[tuple[int, int]]) -> list[list[dict]]:
        self.load()
        import torch
        from maia3.dataset import get_historical_tokens, get_legal_moves_mask, tokenize_board
        from maia3.utils import mirror_move

        # Match the upstream --use-uci-history behavior: each past board tokenizes
        # from that past board's own side-to-move perspective, including black.
        history_boards = [board.copy(stack=True)]
        while history_boards[-1].move_stack and len(history_boards) < self.cfg.history:
            previous = history_boards[-1].copy(stack=True)
            previous.pop()
            history_boards.append(previous)
        history = deque(
            (tokenize_board(b) for b in reversed(history_boards)), maxlen=self.cfg.history
        )
        tokens = get_historical_tokens(history, self.cfg, 0.0, 0.0, 0.0, 0.0)
        mask = get_legal_moves_mask(board, self.vocabulary)
        legal = list(board.legal_moves)
        indices = [self.vocabulary[m.uci() if board.turn else mirror_move(m.uci())] for m in legal]
        if int(mask.sum()) != len(legal):
            raise VisionError("unsupported_move", "The model vocabulary missed a legal move.", 500)
        output = []
        # Small chunks bound attention memory on CPU while sharing input preparation.
        with torch.inference_mode():
            for start in range(0, len(ratings), 4):
                chunk = ratings[start : start + 4]
                logits, _, _ = self.model(
                    tokens.unsqueeze(0).expand(len(chunk), -1, -1),
                    torch.tensor([r[0] for r in chunk], dtype=torch.long),
                    torch.tensor([r[1] for r in chunk], dtype=torch.long),
                )
                if logits.shape != (len(chunk), 4352) or not torch.isfinite(logits[:, mask]).all():
                    raise VisionError("invalid_policy", "Maia returned invalid policy logits.", 500)
                probabilities = torch.softmax(logits.float().masked_fill(~mask, -torch.inf), dim=-1)
                for row in probabilities:
                    distribution = [
                        {
                            "uci": move.uci(),
                            "san": board.san(move),
                            "probability": float(row[index]),
                        }
                        for move, index in zip(legal, indices)
                    ]
                    validate_distribution(distribution, {m.uci() for m in legal})
                    output.append(distribution)
        return output


class InferenceService:
    """Thread-safe model lifetime and bounded LRU. Calls return independent dictionaries."""

    def __init__(self, config: ModelConfig | None = None, policy: PolicyModel | None = None):
        self.config = config or ModelConfig()
        self.policy = policy or MaiaPolicy(self.config)
        self._cache = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def status(self) -> dict:
        # No model loading or hashing on the health endpoint.
        return {
            "model": "Maia 3 79M",
            "loaded": getattr(self.policy, "model", None) is not None,
            "installed": self.config.checkpoint.is_file() and self.config.manifest.is_file(),
            "device": "CPU",
            "cache_entries": len(self._cache),
            "cache_hits": self.hits,
            "cache_misses": self.misses,
            "load_seconds": getattr(self.policy, "load_seconds", None),
        }

    def predict(self, request: PredictionRequest) -> dict:
        opponent = request.opponent_elo if request.opponent_elo is not None else request.player_elo
        return self.predict_many(request, [(request.player_elo, opponent)])[0]

    def predict_many(
        self, request: PredictionRequest, ratings: list[tuple[int, int]]
    ) -> list[dict]:
        if not ratings or len(ratings) > 14:
            raise VisionError("invalid_ratings", "Request between 1 and 14 rating pairs.")
        for pair in ratings:
            if any(type(elo) is not int or not 400 <= elo <= 3000 for elo in pair):
                raise VisionError(
                    "invalid_rating", "Ratings must be integers between 400 and 3000."
                )
        board = replay_position(request.fen, request.initial_fen, list(request.moves))
        started = time.perf_counter()
        with self._lock:
            # Loading before cache lookup fixes the model identity for the entire session.
            if board.legal_moves.count() and hasattr(self.policy, "load"):
                self.policy.load()
            context = {
                "fen": board.fen(en_passant="fen"),
                "initial_fen": request.initial_fen,
                "moves": request.moves,
                "model": self.policy.metadata,
            }
            position_id = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
            keys = [(position_id, a, b) for a, b in ratings]
            missing = list(dict.fromkeys(key for key in keys if key not in self._cache))
            legal = {move.uci() for move in board.legal_moves}
            if missing:
                distributions = (
                    self.policy.predict(board, [(key[1], key[2]) for key in missing])
                    if legal
                    else [[] for _ in missing]
                )
                if len(distributions) != len(missing):
                    raise VisionError(
                        "invalid_policy", "Maia returned an incomplete rating batch.", 500
                    )
                for key, distribution in zip(missing, distributions):
                    validate_distribution(distribution, legal)
                    distribution.sort(key=lambda m: (-m["probability"], m["uci"]))
                    for rank, move in enumerate(distribution, 1):
                        move["rank"] = rank
                    warnings = [
                        "Predicted human behavior, not measured frequencies or engine evaluations.",
                        "The published inference code accepts ratings 0–5000; rating-specific "
                        "training/evaluation coverage is not established by that API. "
                        "Use particular caution at 400 and 3000; no ratings are clamped.",
                    ]
                    if request.initial_fen is None:
                        warnings.append(
                            "No move history supplied; the current position is repeated "
                            "to fill the model's eight-position context."
                        )
                    outcome = board.outcome(claim_draw=False)
                    self._cache[key] = {
                        "schema_version": "1.0",
                        "position_id": position_id,
                        "fen": context["fen"],
                        "initial_fen": request.initial_fen,
                        "history": list(request.moves),
                        "side_to_move": "white" if board.turn else "black",
                        "player_elo": key[1],
                        "opponent_elo": key[2],
                        "model": copy.deepcopy(self.policy.metadata),
                        "moves": distribution,
                        "probability_sum": sum(m["probability"] for m in distribution),
                        "warnings": warnings,
                        "terminal": outcome.termination.name if outcome else None,
                    }
                self.misses += len(missing)
            results = []
            for key in keys:
                cached = key not in missing
                self.hits += int(cached)
                self._cache.move_to_end(key)
                result = copy.deepcopy(self._cache[key])
                result["cached"] = cached
                result["elapsed_ms"] = (time.perf_counter() - started) * 1000
                results.append(result)
            while len(self._cache) > max(14, self.config.cache_size):
                self._cache.popitem(last=False)
            return results

    def close(self):
        with self._lock:
            self._cache.clear()
            if hasattr(self.policy, "model"):
                self.policy.model = None

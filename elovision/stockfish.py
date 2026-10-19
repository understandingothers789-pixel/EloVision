"""Optional, user-supplied Stockfish 19 UCI engine integration."""

import os
import threading
from pathlib import Path

import chess
import chess.engine

from .chess_state import replay_position
from .errors import VisionError
from .inference import PredictionRequest

ENGINE_DIR = Path(__file__).resolve().parents[1] / ".engines"
MAX_ENGINE_BYTES = 100 * 1024 * 1024


class StockfishService:
    """Manage a locally installed Stockfish binary without bundling third-party code."""

    def __init__(self, engine_dir: Path = ENGINE_DIR):
        self.engine_dir = engine_dir
        self._lock = threading.RLock()
        self._engine_path = engine_dir / ("stockfish.exe" if os.name == "nt" else "stockfish")
        self._channel_path = engine_dir / "channel.json"
        configured = os.environ.get("ELOVISION_STOCKFISH")
        configured_channel = os.environ.get("ELOVISION_STOCKFISH_CHANNEL")
        self._channel = configured_channel or "official19"
        if self._channel not in {"official19", "development"}:
            self._channel = "official19"
        if not configured_channel and not configured:
            try:
                saved = self._channel_path.read_text(encoding="utf-8").strip()
                if saved in {"official19", "development"}:
                    self._channel = saved
            except OSError:
                pass
        if configured:
            self._engine_path = Path(configured).expanduser().resolve()

    def _identify(self, path: Path, channel: str | None = None):
        channel = channel or self._channel
        if not path.is_file():
            raise VisionError(
                "stockfish_missing",
                "Choose a Stockfish executable to enable engine analysis.",
                503,
            )
        try:
            with chess.engine.SimpleEngine.popen_uci(str(path), timeout=12) as engine:
                name = engine.id.get("name", "Unknown UCI engine")
                lower_name = name.lower()
                valid_name = (
                    lower_name.startswith("stockfish 19")
                    if channel == "official19"
                    else lower_name.startswith(("stockfish dev", "stockfish development"))
                )
                if not valid_name:
                    expected = (
                        "Stockfish 19"
                        if channel == "official19"
                        else "a Stockfish development build"
                    )
                    raise VisionError(
                        "stockfish_version",
                        f"This mode expects {expected}; the selected engine identifies as {name}.",
                        422,
                    )
                return name
        except VisionError:
            raise
        except (
            OSError,
            TimeoutError,
            ValueError,
            chess.engine.EngineError,
            chess.engine.EngineTerminatedError,
        ) as exc:
            raise VisionError(
                "stockfish_start",
                "Stockfish could not start. Choose the extracted "
                "Stockfish executable for this computer.",
                422,
            ) from exc

    def status(self):
        try:
            name = self._identify(self._engine_path)
        except VisionError as exc:
            if exc.code == "stockfish_missing":
                return {"available": False, "name": None, "channel": self._channel}
            return {"available": False, "name": None, "channel": self._channel, "message": str(exc)}
        return {"available": True, "name": name, "channel": self._channel}

    def install(self, filename: str, content: bytes, channel: str = "official19"):
        if channel not in {"official19", "development"}:
            raise VisionError(
                "stockfish_channel", "Choose Stockfish 19 or a development build.", 422
            )
        if not content:
            raise VisionError("stockfish_empty", "The selected engine file is empty.", 400)
        if len(content) > MAX_ENGINE_BYTES:
            raise VisionError("stockfish_too_large", "Engine files must be 100 MB or smaller.", 413)
        suffix = Path(filename).suffix.lower()
        if suffix not in {".exe", ".bin", ""}:
            raise VisionError(
                "stockfish_file_type",
                "Choose the extracted Stockfish executable, not its ZIP file.",
                400,
            )
        self.engine_dir.mkdir(parents=True, exist_ok=True)
        destination = self.engine_dir / ("stockfish.exe" if os.name == "nt" else "stockfish")
        with self._lock:
            # UCI launches the temporary path, so preserve the platform executable suffix.
            temporary = self.engine_dir / f".stockfish-upload{destination.suffix or '.bin'}"
            try:
                temporary.write_bytes(content)
                if os.name != "nt":
                    temporary.chmod(0o700)
                name = self._identify(temporary, channel)
                os.replace(temporary, destination)
                if os.name != "nt":
                    destination.chmod(0o700)
                channel_temporary = self._channel_path.with_suffix(".tmp")
                channel_temporary.write_text(channel, encoding="utf-8")
                os.replace(channel_temporary, self._channel_path)
            finally:
                temporary.unlink(missing_ok=True)
        self._engine_path = destination
        self._channel = channel
        return {"available": True, "name": name, "channel": channel}

    def analyze(self, request: PredictionRequest, depth: int = 16, multipv: int = 5):
        if not 10 <= depth <= 22:
            raise VisionError("stockfish_depth", "Choose a search depth between 10 and 22.", 422)
        if not 1 <= multipv <= 12:
            raise VisionError(
                "stockfish_multipv", "Request between one and twelve engine lines.", 422
            )
        board = replay_position(request.fen, request.initial_fen, list(request.moves))
        if not board.legal_moves.count():
            return {
                "engine": self._identify(self._engine_path),
                "channel": self._channel,
                "side_to_move": "white" if board.turn else "black",
                "depth": depth,
                "lines": [],
            }
        with self._lock:
            if not self._engine_path.is_file():
                raise VisionError(
                    "stockfish_missing",
                    "Choose the Stockfish 19 executable to enable engine analysis.",
                    503,
                )
            try:
                with chess.engine.SimpleEngine.popen_uci(
                    str(self._engine_path), timeout=90
                ) as engine:
                    name = engine.id.get("name", "Unknown UCI engine")
                    lower_name = name.lower()
                    valid_name = (
                        lower_name.startswith("stockfish 19")
                        if self._channel == "official19"
                        else lower_name.startswith(("stockfish dev", "stockfish development"))
                    )
                    if not valid_name:
                        expected = (
                            "Stockfish 19"
                            if self._channel == "official19"
                            else "a Stockfish development build"
                        )
                        raise VisionError(
                            "stockfish_version",
                            f"This mode expects {expected}; the selected engine identifies "
                            f"as {name}.",
                            422,
                        )
                    threads = max(
                        1, min(8, int(os.environ.get("ELOVISION_STOCKFISH_THREADS", "2")))
                    )
                    options = {}
                    if "Threads" in engine.options:
                        options["Threads"] = threads
                    if "Hash" in engine.options:
                        options["Hash"] = 256
                    if options:
                        engine.configure(options)
                    infos = engine.analyse(
                        board,
                        chess.engine.Limit(depth=depth),
                        multipv=min(multipv, board.legal_moves.count()),
                    )
            except VisionError:
                raise
            except (
                OSError,
                TimeoutError,
                ValueError,
                chess.engine.EngineError,
                chess.engine.EngineTerminatedError,
            ) as exc:
                raise VisionError(
                    "stockfish_analysis",
                    "Stockfish stopped during analysis. Retry or choose the engine again.",
                    503,
                ) from exc
        if isinstance(infos, dict):
            infos = [infos]
        lines = []
        for rank, info in enumerate(infos, 1):
            pv = info.get("pv", [])
            score = info.get("score")
            relative = score.pov(chess.WHITE) if score else None
            mate = relative.mate() if relative else None
            cp = relative.score(mate_score=100000) if relative else None
            if mate is not None:
                score_text = f"M{mate}" if mate > 0 else f"−M{abs(mate)}"
            elif cp is not None:
                score_text = f"{cp / 100:+.2f}"
            else:
                score_text = "—"
            line_board = board.copy(stack=True)
            pv_san = []
            for move in pv[:10]:
                pv_san.append(line_board.san(move))
                line_board.push(move)
            lines.append(
                {
                    "rank": rank,
                    "uci": pv[0].uci() if pv else None,
                    "san": board.san(pv[0]) if pv else None,
                    "score_cp": cp,
                    "mate": mate,
                    "score": score_text,
                    "pv": pv_san,
                    "depth": info.get("depth", depth),
                }
            )
        return {
            "engine": name,
            "channel": self._channel,
            "side_to_move": "white" if board.turn else "black",
            "depth": max((line["depth"] for line in lines), default=depth),
            "lines": lines,
        }

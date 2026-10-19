"""Optional, user-supplied Stockfish 19 UCI engine integration."""

import os
import platform
import sys
import tempfile
import threading
from pathlib import Path

import chess
import chess.engine

from .chess_state import replay_position
from .errors import VisionError
from .inference import PredictionRequest

ENGINE_DIR = Path(__file__).resolve().parents[1] / ".engines"
MAX_ENGINE_BYTES = 512 * 1024 * 1024
MAX_ENGINE_SIZE_LABEL = f"{MAX_ENGINE_BYTES // (1024 * 1024)} MiB"


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
            with path.open("rb") as binary:
                signature = binary.read(4)
            if os.name == "nt" and signature == b"\x7fELF":
                raise VisionError(
                    "stockfish_platform",
                    "This is a Linux engine. Choose the Stockfish build for Windows "
                    "and your PC’s processor.",
                    422,
                )
            if os.name != "nt" and signature[:2] == b"MZ":
                system = "Linux" if sys.platform.startswith("linux") else "this operating system"
                message = (
                    f"This is a Windows .exe, but ELO Vision is running on {system}. "
                    "Choose a native Stockfish build for this computer."
                )
                raise VisionError(
                    "stockfish_platform",
                    message,
                    422,
                )
            # Large Windows releases can take several seconds to map their embedded
            # NNUE networks on first launch, especially while antivirus scans them.
            with chess.engine.SimpleEngine.popen_uci(str(path), timeout=60) as engine:
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
            reason = str(exc).strip()
            detail = f" Details: {reason[:240]}" if reason else ""
            raise VisionError(
                "stockfish_start",
                "Stockfish could not start. Choose the extracted "
                "Stockfish executable built for this computer’s operating system and processor."
                + detail,
                422,
            ) from exc

    def status(self):
        host = f"{platform.system()} {platform.machine()}"
        try:
            name = self._identify(self._engine_path)
        except VisionError as exc:
            if exc.code == "stockfish_missing":
                return {
                    "available": False,
                    "name": None,
                    "channel": self._channel,
                    "host": host,
                }
            return {
                "available": False,
                "name": None,
                "channel": self._channel,
                "host": host,
                "message": str(exc),
            }
        return {"available": True, "name": name, "channel": self._channel, "host": host}

    def install(self, filename: str, content: bytes, channel: str = "official19"):
        """Compatibility wrapper for callers that already hold an in-memory upload."""
        if channel not in {"official19", "development"}:
            raise VisionError(
                "stockfish_channel", "Choose Stockfish 19 or a development build.", 422
            )
        if not content:
            raise VisionError("stockfish_empty", "The selected engine file is empty.", 400)
        if len(content) > MAX_ENGINE_BYTES:
            raise VisionError(
                "stockfish_too_large",
                f"Engine files must be {MAX_ENGINE_SIZE_LABEL} or smaller.",
                413,
            )
        self.engine_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".stockfish-upload-",
                suffix=suffix,
                dir=self.engine_dir,
                delete=False,
            ) as upload:
                temporary = Path(upload.name)
                upload.write(content)
            return self.install_file(filename, temporary, channel)
        except OSError as exc:
            raise VisionError(
                "stockfish_storage",
                "Could not save the engine. Check free disk space and write access "
                "to the ELO Vision folder.",
                507,
            ) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def install_file(self, filename: str, source: Path, channel: str = "official19"):
        """Validate and atomically install a staged upload without reading it into memory."""
        if channel not in {"official19", "development"}:
            raise VisionError(
                "stockfish_channel", "Choose Stockfish 19 or a development build.", 422
            )
        suffix = Path(filename).suffix.lower()
        if suffix not in {".exe", ".bin", ""}:
            raise VisionError(
                "stockfish_file_type",
                "Choose the extracted Stockfish executable, not its ZIP file.",
                400,
            )
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise VisionError(
                "stockfish_upload_missing", "The uploaded engine file could not be read.", 400
            ) from exc
        if not size:
            raise VisionError("stockfish_empty", "The selected engine file is empty.", 400)
        if size > MAX_ENGINE_BYTES:
            raise VisionError(
                "stockfish_too_large",
                f"Engine files must be {MAX_ENGINE_SIZE_LABEL} or smaller.",
                413,
            )
        self.engine_dir.mkdir(parents=True, exist_ok=True)
        destination = self.engine_dir / ("stockfish.exe" if os.name == "nt" else "stockfish")
        with self._lock:
            channel_temporary = self._channel_path.with_suffix(".tmp")
            try:
                if os.name != "nt":
                    source.chmod(0o700)
                name = self._identify(source, channel)
                os.replace(source, destination)
                if os.name != "nt":
                    destination.chmod(0o700)
                channel_temporary.write_text(channel, encoding="utf-8")
                os.replace(channel_temporary, self._channel_path)
            except OSError as exc:
                raise VisionError(
                    "stockfish_storage",
                    "Could not install the engine. Check free disk space and write access "
                    "to the ELO Vision folder.",
                    507,
                ) from exc
            finally:
                channel_temporary.unlink(missing_ok=True)
        self._engine_path = destination
        self._channel = channel
        return {"available": True, "name": name, "channel": channel}

    def analyze(
        self,
        request: PredictionRequest,
        depth: int = 16,
        multipv: int = 20,
        hash_mb: int = 8192,
        threads: int = 14,
    ):
        if not 10 <= depth <= 22:
            raise VisionError("stockfish_depth", "Choose a search depth between 10 and 22.", 422)
        if not 1 <= multipv <= 40:
            raise VisionError(
                "stockfish_multipv", "Request between one and forty engine lines.", 422
            )
        if not 1 <= hash_mb <= 65536:
            raise VisionError("stockfish_hash", "Choose a hash size between 1 MiB and 64 GiB.", 422)
        if not 1 <= threads <= 256:
            raise VisionError("stockfish_threads", "Choose between 1 and 256 engine threads.", 422)
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
                    options = {}
                    for option_name, value in (("Threads", threads), ("Hash", hash_mb)):
                        option = engine.options.get(option_name)
                        if option is None:
                            continue
                        if option.min is not None and value < option.min:
                            raise VisionError(
                                "stockfish_option_limit",
                                f"This engine requires {option_name} to be at least {option.min}.",
                                422,
                            )
                        if option.max is not None and value > option.max:
                            unit = " MiB" if option_name == "Hash" else " threads"
                            raise VisionError(
                                "stockfish_option_limit",
                                f"This engine supports {option_name} up to {option.max}{unit}. "
                                "Lower that setting and retry.",
                                422,
                            )
                        options[option_name] = value
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
                reason = str(exc).strip()
                detail = f" Details: {reason[:240]}" if reason else ""
                raise VisionError(
                    "stockfish_analysis",
                    "Stockfish stopped during analysis. Retry or choose the engine again." + detail,
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

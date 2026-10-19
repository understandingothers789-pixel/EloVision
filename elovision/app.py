"""Loopback-only local API. Import inference.py for a GUI-independent Python API."""

import asyncio
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .chess_state import describe_position, parse_pgn, valid_board
from .config import RATINGS
from .errors import VisionError
from .export import export_csv, export_json
from .inference import InferenceService, PredictionRequest
from .stockfish import MAX_ENGINE_BYTES, MAX_ENGINE_SIZE_LABEL, StockfishService


class PositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fen: str = Field(max_length=160)
    initial_fen: str | None = Field(default=None, max_length=160)
    moves: list[str] = Field(default_factory=list, max_length=3000)

    def prediction(self, player=1600, opponent=None):
        return PredictionRequest(self.fen, player, opponent, self.initial_fen, tuple(self.moves))


class PredictInput(PositionInput):
    player_elo: int = Field(default=1600, ge=400, le=3000)
    opponent_elo: int | None = Field(default=None, ge=400, le=3000)


class MatchupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    player_elo: int = Field(ge=400, le=3000)
    opponent_elo: int = Field(ge=400, le=3000)


class AnalysisInput(PositionInput):
    ratings: list[int] = Field(default_factory=lambda: [1600], min_length=1, max_length=14)
    matchups: list[MatchupInput] | None = Field(default=None, min_length=1, max_length=14)

    def rating_pairs(self):
        return (
            [(item.player_elo, item.opponent_elo) for item in self.matchups]
            if self.matchups is not None
            else [(rating, rating) for rating in self.ratings]
        )


class ExportInput(AnalysisInput):
    format: str = "json"
    game_id: str | None = Field(default=None, max_length=100)
    ply: int | None = Field(default=None, ge=0, le=3000)


class PgnInput(BaseModel):
    pgn: str = Field(max_length=2_000_000)


class StockfishInput(PositionInput):
    depth: int = Field(default=16, ge=10, le=22)
    multipv: int = Field(default=5, ge=1, le=12)


def create_app(
    service: InferenceService | None = None,
    stockfish_service: StockfishService | None = None,
):
    engine = service or InferenceService()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="maia")
    stockfish = stockfish_service or StockfishService()
    stockfish_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stockfish")
    pending = asyncio.Semaphore(4)
    stockfish_pending = asyncio.Semaphore(1)

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=True, cancel_futures=True)
        stockfish_executor.shutdown(wait=True, cancel_futures=True)
        engine.close()

    app = FastAPI(title="ELO Vision local API", version="1.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.state.engine = engine
    app.state.stockfish = stockfish

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse(
                {
                    "error": {
                        "code": "origin_denied",
                        "message": "Use the local ELO Vision application.",
                    }
                },
                403,
            )
        try:
            limit = MAX_ENGINE_BYTES if request.url.path == "/api/v1/engine/install" else 2_500_000
            if int(request.headers.get("content-length", "0")) > limit:
                message = (
                    f"Engine files must be {MAX_ENGINE_SIZE_LABEL} or smaller."
                    if request.url.path == "/api/v1/engine/install"
                    else "Request exceeds the upload limit."
                )
                return JSONResponse(
                    {"error": {"code": "request_too_large", "message": message}},
                    413,
                )
        except ValueError:
            return PlainTextResponse("Invalid Content-Length", 400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(VisionError)
    async def vision_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Check the position, ratings, and request fields.",
                }
            },
            422,
        )

    async def work(fn, *args):
        if pending.locked():
            raise VisionError("busy", "Analysis is busy. Wait a moment and retry.", 429)
        async with pending:
            try:
                return await asyncio.get_running_loop().run_in_executor(executor, fn, *args)
            except VisionError:
                raise
            except Exception as exc:
                logging.exception("Local analysis failed")
                raise VisionError(
                    "analysis_failed",
                    "Analysis failed. Check the server log and "
                    "retry; no probabilities were substituted.",
                    500,
                ) from exc

    async def stockfish_work(fn, *args):
        if stockfish_pending.locked():
            raise VisionError(
                "stockfish_busy", "Stockfish is busy. Wait for the current search to finish.", 429
            )
        async with stockfish_pending:
            try:
                return await asyncio.get_running_loop().run_in_executor(
                    stockfish_executor, fn, *args
                )
            except VisionError:
                raise
            except Exception as exc:
                logging.exception("Stockfish request failed")
                raise VisionError(
                    "stockfish_failed", "Stockfish could not complete that request.", 500
                ) from exc

    @app.get("/api/v1/engine/status")
    async def stockfish_status():
        return await stockfish_work(stockfish.status)

    @app.post("/api/v1/engine/install")
    async def stockfish_install(request: Request):
        filename = (
            unquote(request.headers.get("x-engine-filename", "")).replace("\\", "/").split("/")[-1]
        )
        if not filename:
            raise VisionError("stockfish_filename", "The engine filename is missing.", 400)
        channel = request.headers.get("x-engine-channel", "official19")
        if channel not in {"official19", "development"}:
            raise VisionError(
                "stockfish_channel", "Choose Stockfish 19 or a development build.", 422
            )
        if Path(filename).suffix.lower() not in {".exe", ".bin", ""}:
            raise VisionError(
                "stockfish_file_type",
                "Choose the extracted Stockfish executable, not its ZIP file.",
                400,
            )
        if stockfish_pending.locked():
            raise VisionError(
                "stockfish_busy", "Stockfish is busy. Wait for the current search to finish.", 429
            )

        upload_path = None
        try:
            stockfish.engine_dir.mkdir(parents=True, exist_ok=True)
            suffix = ".exe" if os.name == "nt" else Path(filename).suffix.lower()
            with tempfile.NamedTemporaryFile(
                prefix=".stockfish-received-",
                suffix=suffix,
                dir=stockfish.engine_dir,
                delete=False,
            ) as upload:
                upload_path = Path(upload.name)
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_ENGINE_BYTES:
                        raise VisionError(
                            "stockfish_too_large",
                            f"Engine files must be {MAX_ENGINE_SIZE_LABEL} or smaller.",
                            413,
                        )
                    upload.write(chunk)
            return await stockfish_work(stockfish.install_file, filename, upload_path, channel)
        except OSError as exc:
            raise VisionError(
                "stockfish_storage",
                "Could not save the engine upload. Check free disk space and write access "
                "to the ELO Vision folder.",
                507,
            ) from exc
        finally:
            if upload_path is not None:
                upload_path.unlink(missing_ok=True)

    @app.post("/api/v1/engine/analyze")
    async def stockfish_analyze(data: StockfishInput):
        return await stockfish_work(stockfish.analyze, data.prediction(), data.depth, data.multipv)

    @app.get("/api/v1/samples")
    def samples():
        import json

        catalog = Path(__file__).parent / "static" / "sample-games.json"
        return json.loads(catalog.read_text(encoding="utf-8"))

    @app.get("/api/v1/health")
    def health():
        return {"schema_version": "1.0", "status": "ok", "ratings": RATINGS, **engine.status()}

    @app.post("/api/v1/pgn")
    async def pgn(data: PgnInput):
        return await work(parse_pgn, data.pgn)

    @app.post("/api/v1/position")
    def position(data: PositionInput):
        return describe_position(valid_board(data.fen))

    @app.post("/api/v1/predict")
    async def predict(data: PredictInput):
        return await work(engine.predict, data.prediction(data.player_elo, data.opponent_elo))

    @app.post("/api/v1/analyze")
    async def analyze(data: AnalysisInput):
        predictions = await work(engine.predict_many, data.prediction(), data.rating_pairs())
        return {"schema_version": "1.0", "predictions": predictions}

    @app.post("/api/v1/export")
    async def export(data: ExportInput):
        if data.format not in {"json", "csv"}:
            raise VisionError("invalid_format", "Choose JSON or CSV for export.")
        predictions = await work(engine.predict_many, data.prediction(), data.rating_pairs())
        exporter = export_json if data.format == "json" else export_csv
        content = exporter(predictions, data.game_id, data.ply)
        return Response(
            content,
            media_type="application/json" if data.format == "json" else "text/csv",
            headers={"Content-Disposition": f'attachment; filename="elovision.{data.format}"'},
        )

    app.mount(
        "/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="frontend"
    )
    return app

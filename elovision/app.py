"""Loopback-only local API. Import inference.py for a GUI-independent Python API."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

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


class AnalysisInput(PositionInput):
    ratings: list[int] = Field(default_factory=lambda: [1600], min_length=1, max_length=14)


class ExportInput(AnalysisInput):
    format: str = "json"
    game_id: str | None = Field(default=None, max_length=100)
    ply: int | None = Field(default=None, ge=0, le=3000)


class PgnInput(BaseModel):
    pgn: str = Field(max_length=2_000_000)


def create_app(service: InferenceService | None = None):
    engine = service or InferenceService()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="maia")
    pending = asyncio.Semaphore(4)

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=True, cancel_futures=True)
        engine.close()

    app = FastAPI(title="ELO Vision local API", version="1.0", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.state.engine = engine

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
            if int(request.headers.get("content-length", "0")) > 2_500_000:
                return JSONResponse(
                    {"error": {"code": "request_too_large", "message": "Request exceeds 2.5 MB."}},
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
        predictions = await work(
            engine.predict_many, data.prediction(), [(r, r) for r in data.ratings]
        )
        return {"schema_version": "1.0", "predictions": predictions}

    @app.post("/api/v1/export")
    async def export(data: ExportInput):
        if data.format not in {"json", "csv"}:
            raise VisionError("invalid_format", "Choose JSON or CSV for export.")
        predictions = await work(
            engine.predict_many, data.prediction(), [(r, r) for r in data.ratings]
        )
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

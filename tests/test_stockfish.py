import os
import sys

import chess
import pytest
from fastapi.testclient import TestClient

from elovision.app import create_app
from elovision.errors import VisionError
from elovision.stockfish import StockfishService

FAKE_STOCKFISH = f"""#!{sys.executable}
import sys
for raw in sys.stdin:
    line = raw.strip()
    if line == "uci":
        print("id name Stockfish 19 protocol fixture")
        print("option name Threads type spin default 1 min 1 max 8")
        print("option name Hash type spin default 16 min 1 max 1024")
        print("option name MultiPV type spin default 1 min 1 max 5")
        print("uciok", flush=True)
    elif line == "isready":
        print("readyok", flush=True)
    elif line.startswith("go "):
        print("info depth 16 multipv 1 score cp 35 pv e2e4", flush=True)
        print("info depth 16 multipv 2 score cp 21 pv d2d4", flush=True)
        print("info depth 16 multipv 3 score cp 12 pv g1f3", flush=True)
        print("bestmove e2e4", flush=True)
    elif line == "quit":
        break
""".encode()


@pytest.mark.skipif(os.name == "nt", reason="The protocol fixture uses a Unix executable script.")
def test_stockfish_upload_and_multipv_api(tmp_path):
    service = StockfishService(tmp_path / ".engines")
    with TestClient(create_app(stockfish_service=service)) as client:
        assert client.get("/api/v1/engine/status").json()["available"] is False
        installed = client.post(
            "/api/v1/engine/install",
            content=FAKE_STOCKFISH,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Engine-Filename": "stockfish19.bin",
                "X-Engine-Channel": "official19",
            },
        )
        assert installed.status_code == 200
        assert installed.json()["name"].startswith("Stockfish 19")
        response = client.post(
            "/api/v1/engine/analyze",
            json={"fen": chess.STARTING_FEN, "depth": 16, "multipv": 3},
        )
        assert response.status_code == 200
        result = response.json()
        assert [line["san"] for line in result["lines"]] == ["e4", "d4", "Nf3"]
        assert [line["score"] for line in result["lines"]] == ["+0.35", "+0.21", "+0.12"]
        assert result["channel"] == "official19"


@pytest.mark.skipif(os.name == "nt", reason="The protocol fixture uses a Unix executable script.")
def test_stockfish_development_channel_accepts_dev_build_and_persists(tmp_path):
    dev_engine = FAKE_STOCKFISH.replace(b"Stockfish 19", b"Stockfish dev-20261019").replace(
        b"max 5", b"max 12"
    )
    engine_dir = tmp_path / ".engines"
    service = StockfishService(engine_dir)
    result = service.install("stockfish-dev.bin", dev_engine, "development")
    assert result["channel"] == "development"
    assert result["name"].startswith("Stockfish dev-")
    status = StockfishService(engine_dir).status()
    assert status["available"] is True
    assert status["channel"] == "development"


@pytest.mark.skipif(os.name == "nt", reason="The protocol fixture uses a Unix executable script.")
def test_stockfish_development_channel_api(tmp_path):
    dev_engine = FAKE_STOCKFISH.replace(b"Stockfish 19", b"Stockfish dev-20261019")
    service = StockfishService(tmp_path / ".engines")
    with TestClient(create_app(stockfish_service=service)) as client:
        installed = client.post(
            "/api/v1/engine/install",
            content=dev_engine,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Engine-Filename": "stockfish-dev.bin",
                "X-Engine-Channel": "development",
            },
        )
        assert installed.status_code == 200
        assert installed.json()["channel"] == "development"
        assert client.get("/api/v1/engine/status").json()["channel"] == "development"


def test_stockfish_rejects_non_executable_file_type(tmp_path):
    service = StockfishService(tmp_path / ".engines")
    with pytest.raises(VisionError, match="Choose the extracted Stockfish executable"):
        service.install("engine.zip", b"not an engine")


@pytest.mark.skipif(os.name == "nt", reason="The protocol fixture uses a Unix executable script.")
def test_stockfish_development_channel_rejects_official_binary(tmp_path):
    service = StockfishService(tmp_path / ".engines")
    with pytest.raises(VisionError, match="development build"):
        service.install("stockfish19.bin", FAKE_STOCKFISH, "development")

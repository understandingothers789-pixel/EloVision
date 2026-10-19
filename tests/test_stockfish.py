import os
import sys

import chess
import pytest
from fastapi.testclient import TestClient

from elovision.app import create_app
from elovision.errors import VisionError
from elovision.stockfish import MAX_ENGINE_BYTES, MAX_ENGINE_SIZE_LABEL, StockfishService

FAKE_STOCKFISH = f"""#!{sys.executable}
import os
import sys
for raw in sys.stdin:
    line = raw.strip()
    if line == "uci":
        print("id name Stockfish 19 protocol fixture")
        print("option name Threads type spin default 1 min 1 max 256")
        print("option name Hash type spin default 16 min 1 max 32768")
        print("option name MultiPV type spin default 1 min 1 max 40")
        print("uciok", flush=True)
    elif line == "isready":
        print("readyok", flush=True)
    elif line.startswith("setoption"):
        with open(os.environ["ELOVISION_TEST_UCI_LOG"], "a", encoding="utf-8") as log:
            log.write(line + "\\n")
    elif line.startswith("go "):
        print("info depth 16 multipv 1 score cp 35 pv e2e4", flush=True)
        print("info depth 16 multipv 2 score cp 21 pv d2d4", flush=True)
        print("info depth 16 multipv 3 score cp 12 pv g1f3", flush=True)
        print("info depth 16 multipv 4 score cp 10 pv b1c3", flush=True)
        print("info depth 16 multipv 5 score cp 9 pv b1a3", flush=True)
        print("info depth 16 multipv 6 score cp 8 pv g1h3", flush=True)
        remaining_moves = (
            "a2a3", "a2a4", "b2b3", "b2b4", "c2c3", "c2c4", "d2d3",
            "e2e3", "f2f3", "f2f4", "g2g3", "g2g4", "h2h3", "h2h4",
        )
        for index, move in enumerate(remaining_moves, 7):
            print(f"info depth 16 multipv {{index}} score cp 5 pv {{move}}", flush=True)
        print("bestmove e2e4", flush=True)
    elif line == "quit":
        break
""".encode()


@pytest.mark.skipif(os.name == "nt", reason="The protocol fixture uses a Unix executable script.")
def test_stockfish_upload_and_multipv_api(tmp_path, monkeypatch):
    service = StockfishService(tmp_path / ".engines")
    uci_log = tmp_path / "uci-options.log"
    monkeypatch.setenv("ELOVISION_TEST_UCI_LOG", str(uci_log))
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
        assert [line["san"] for line in result["lines"][:3]] == ["e4", "d4", "Nf3"]
        assert [line["score"] for line in result["lines"][:3]] == ["+0.35", "+0.21", "+0.12"]
        assert result["channel"] == "official19"
        configured = uci_log.read_text(encoding="utf-8")
        assert "setoption name Threads value 14" in configured
        assert "setoption name Hash value 8192" in configured
        wide = client.post(
            "/api/v1/engine/analyze",
            json={"fen": chess.STARTING_FEN, "depth": 16, "multipv": 40},
        )
        assert wide.status_code == 200, wide.text
        assert len(wide.json()["lines"]) == 20
        assert client.post(
            "/api/v1/engine/analyze",
            json={"fen": chess.STARTING_FEN, "depth": 16, "multipv": 41},
        ).status_code == 422


@pytest.mark.skipif(os.name == "nt", reason="The protocol fixture uses a Unix executable script.")
def test_stockfish_development_channel_accepts_dev_build_and_persists(tmp_path):
    dev_engine = FAKE_STOCKFISH.replace(b"Stockfish 19", b"Stockfish dev-20261019")
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


def test_stockfish_accepts_150_mib_engine_without_loading_it_into_memory(tmp_path, monkeypatch):
    engine_dir = tmp_path / ".engines"
    engine_dir.mkdir()
    staged = engine_dir / ".stockfish-received.exe"
    size = 150 * 1024 * 1024
    with staged.open("wb") as upload:
        upload.truncate(size)

    service = StockfishService(engine_dir)
    monkeypatch.setattr(service, "_identify", lambda path, channel=None: "Stockfish 19 fixture")
    result = service.install_file("stockfish.exe", staged, "official19")

    installed = engine_dir / ("stockfish.exe" if os.name == "nt" else "stockfish")
    assert result["available"] is True
    assert installed.stat().st_size == size


def test_stockfish_rejects_engine_larger_than_upload_limit(tmp_path):
    engine_dir = tmp_path / ".engines"
    engine_dir.mkdir()
    staged = engine_dir / ".stockfish-received.bin"
    with staged.open("wb") as upload:
        upload.truncate(MAX_ENGINE_BYTES + 1)

    service = StockfishService(engine_dir)
    with pytest.raises(VisionError, match="512 MiB"):
        service.install_file("stockfish.bin", staged)


@pytest.mark.skipif(os.name == "nt", reason="A Windows executable is valid on Windows.")
def test_stockfish_reports_windows_executable_on_non_windows_host(tmp_path):
    service = StockfishService(tmp_path / ".engines")
    with pytest.raises(VisionError, match="This is a Windows .exe"):
        service.install("stockfish-windows-x86-64.exe", b"MZ\x90\x00not a runnable fixture")


def test_stockfish_upload_stream_limit_without_content_length(tmp_path, monkeypatch):
    import elovision.app as app_module

    monkeypatch.setattr(app_module, "MAX_ENGINE_BYTES", 8)
    monkeypatch.setattr(app_module, "MAX_ENGINE_SIZE_LABEL", "8 bytes")
    service = StockfishService(tmp_path / ".engines")

    def chunks():
        yield b"012345"
        yield b"6789ab"

    with TestClient(create_app(stockfish_service=service)) as client:
        response = client.post(
            "/api/v1/engine/install",
            content=chunks(),
            headers={
                "X-Engine-Filename": "stockfish.bin",
                "X-Engine-Channel": "official19",
            },
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "stockfish_too_large"
    assert not list(service.engine_dir.glob(".stockfish-received-*"))


def test_stockfish_upload_content_length_uses_the_same_limit(tmp_path):
    service = StockfishService(tmp_path / ".engines")
    with TestClient(create_app(stockfish_service=service)) as client:
        response = client.post(
            "/api/v1/engine/install",
            content=b"x",
            headers={
                "Content-Length": str(MAX_ENGINE_BYTES + 1),
                "X-Engine-Filename": "stockfish.bin",
            },
        )

    assert response.status_code == 413
    assert MAX_ENGINE_SIZE_LABEL in response.json()["error"]["message"]


@pytest.mark.skipif(os.name == "nt", reason="The protocol fixture uses a Unix executable script.")
def test_stockfish_development_channel_rejects_official_binary(tmp_path):
    service = StockfishService(tmp_path / ".engines")
    with pytest.raises(VisionError, match="development build"):
        service.install("stockfish19.bin", FAKE_STOCKFISH, "development")

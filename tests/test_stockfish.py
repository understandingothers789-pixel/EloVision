import os
import sys
import threading

import chess
import pytest
from fastapi.testclient import TestClient

from elovision.app import create_app
from elovision.errors import VisionError
from elovision.inference import PredictionRequest
from elovision.stockfish import MAX_ENGINE_BYTES, MAX_ENGINE_SIZE_LABEL, StockfishService

FAKE_STOCKFISH = f"""#!{sys.executable}
import os
import sys
multipv = 1
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
        if line.startswith("setoption name MultiPV value "):
            multipv = int(line.rsplit(" ", 1)[1])
        with open(os.environ["ELOVISION_TEST_UCI_LOG"], "a", encoding="utf-8") as log:
            log.write(line + "\\n")
    elif line.startswith("go "):
        moves = (
            "e2e4", "d2d4", "g1f3", "b1c3", "b1a3", "g1h3", "a2a3", "a2a4",
            "b2b3", "b2b4", "c2c3", "c2c4", "d2d3", "e2e3", "f2f3", "f2f4",
            "g2g3", "g2g4", "h2h3", "h2h4",
        )
        scores = (35, 21, 12, 10, 9, 8)
        for index, move in enumerate(moves[:multipv], 1):
            score = scores[index - 1] if index <= len(scores) else 5
            pv = "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1" if index == 1 else move
            print(f"info depth 16 multipv {{index}} score cp {{score}} pv {{pv}}", flush=True)
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
        assert result["lines"][0]["pv"] == [
            "e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1"
        ]
        assert result["channel"] == "official19"
        configured = uci_log.read_text(encoding="utf-8")
        assert "setoption name Threads value 14" in configured
        assert "setoption name Hash value 8192" in configured
        wide = client.post(
            "/api/v1/engine/analyze",
            json={"fen": chess.STARTING_FEN, "depth": 40, "multipv": 5},
        )
        assert wide.status_code == 200, wide.text
        assert len(wide.json()["lines"]) == 5
        assert client.post(
            "/api/v1/engine/analyze",
            json={"fen": chess.STARTING_FEN, "depth": 16, "multipv": 6},
        ).status_code == 422
        assert client.post(
            "/api/v1/engine/analyze",
            json={"fen": chess.STARTING_FEN, "depth": 41, "multipv": 5},
        ).status_code == 422


def test_new_stockfish_request_stops_search_and_keeps_best_so_far(tmp_path, monkeypatch):
    started = threading.Event()
    stopped = threading.Event()

    class Analysis:
        multipv = [{"pv": [chess.Move.from_uci("e2e4")], "depth": 7}]
        info = {}

        def wait(self):
            assert stopped.wait(2)

        def stop(self):
            stopped.set()

    class Engine:
        id = {"name": "Stockfish 19 test"}
        options = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def configure(self, _options):
            pass

        def analysis(self, *_args, **_kwargs):
            started.set()
            return Analysis()

    engine_dir = tmp_path / ".engines"
    engine_dir.mkdir()
    binary = engine_dir / ("stockfish.exe" if os.name == "nt" else "stockfish")
    binary.write_bytes(b"fixture")
    service = StockfishService(engine_dir)
    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", lambda *_a, **_k: Engine())
    service_request = PredictionRequest(chess.STARTING_FEN, 1800)
    result = []
    worker = threading.Thread(
        target=lambda: result.append(service.analyze(service_request, depth=10))
    )
    worker.start()
    assert started.wait(2)
    service.cancel_active_analysis()
    worker.join(2)
    assert not worker.is_alive()
    assert result[0]["depth"] == 7
    assert result[0]["lines"][0]["san"] == "e4"
    current_generation = service.cancel_active_analysis()
    with pytest.raises(VisionError, match="newer Stockfish search took priority"):
        service.analyze(service_request, depth=10, request_generation=current_generation - 1)


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

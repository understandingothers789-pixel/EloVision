import csv
import io
import json

import chess
from fastapi.testclient import TestClient

from elovision.app import create_app


def test_api_linked_ratings_full_precision_exports_and_validation(service):
    with TestClient(create_app(service)) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        payload = {"fen": chess.STARTING_FEN, "ratings": [1000, 2400]}
        response = client.post("/api/v1/analyze", json=payload)
        assert response.status_code == 200
        predictions = response.json()["predictions"]
        assert [(p["player_elo"], p["opponent_elo"]) for p in predictions] == [
            (1000, 1000),
            (2400, 2400),
        ]
        body = {**payload, "format": "json", "game_id": "game1", "ply": 0}
        exported = client.post("/api/v1/export", json=body).json()
        assert exported["game_id"] == "game1" and exported["ply"] == 0
        assert exported["predictions"][0]["moves"] == predictions[0]["moves"]
        body["format"] = "csv"
        rows = list(csv.DictReader(io.StringIO(client.post("/api/v1/export", json=body).text)))
        assert len(rows) == 40
        assert float(rows[0]["probability"]) == predictions[0]["moves"][0]["probability"]
        assert json.loads(rows[0]["model_settings"])["id"] == "test-double"
        assert client.post("/api/v1/predict", json={"fen": "bad"}).status_code == 400
        assert (
            client.post("/api/v1/analyze", json={**payload, "ratings": [3001]}).status_code == 400
        )
        assert (
            client.post(
                "/api/v1/predict",
                json={"fen": chess.STARTING_FEN, "player_elo": 1000, "opponent_elo": 2400},
            ).json()["opponent_elo"]
            == 2400
        )


def test_missing_model_is_actionable_and_frontend_assets_exist(tmp_path):
    from elovision.config import ModelConfig
    from elovision.inference import InferenceService

    with TestClient(create_app(InferenceService(ModelConfig(model_dir=tmp_path)))) as client:
        assert "ELO Vision" in client.get("/").text
        assert "<svg" in client.get("/pieces/wK.svg").text
        response = client.post("/api/v1/predict", json={"fen": chess.STARTING_FEN})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "model_missing"
        assert client.post("/api/v1/pgn", json={"pgn": ""}).status_code == 400
        assert (
            client.post("/api/v1/position", json={"fen": chess.STARTING_FEN}).json()["legal_count"]
            == 20
        )


def test_local_origin_and_host_restrictions(service):
    with TestClient(create_app(service)) as client:
        assert client.get("/api/v1/health", headers={"Host": "evil.example"}).status_code == 400
        assert (
            client.post(
                "/api/v1/predict",
                json={"fen": chess.STARTING_FEN},
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )

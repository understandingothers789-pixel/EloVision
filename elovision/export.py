import csv
import io
import json


def export_json(predictions: list[dict], game_id=None, ply=None) -> str:
    return json.dumps(
        {"schema_version": "1.0", "game_id": game_id, "ply": ply, "predictions": predictions},
        indent=2,
        allow_nan=False,
    )


def export_csv(predictions: list[dict], game_id=None, ply=None) -> str:
    stream = io.StringIO(newline="")
    fields = [
        "schema_version",
        "position_id",
        "fen",
        "game_id",
        "ply",
        "side_to_move",
        "player_elo",
        "opponent_elo",
        "uci",
        "san",
        "rank",
        "probability",
        "model_id",
        "weights_sha256",
        "model_settings",
        "initial_fen",
        "history",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for prediction in predictions:
        for move in prediction["moves"]:
            row = {
                key: prediction[key]
                for key in (
                    "schema_version",
                    "position_id",
                    "fen",
                    "side_to_move",
                    "player_elo",
                    "opponent_elo",
                )
            }
            row.update(
                game_id=game_id,
                ply=ply,
                **move,
                model_id=prediction["model"].get("id"),
                weights_sha256=prediction["model"].get("weights_sha256"),
                model_settings=json.dumps(prediction["model"], sort_keys=True),
                initial_fen=prediction["initial_fen"],
                history=json.dumps(prediction["history"]),
            )
            writer.writerow(row)
    return stream.getvalue()

"""Benchmark actual Maia 3 inference on CPU and available PyTorch GPUs."""

import argparse
import json
import math
import statistics
import time
from dataclasses import replace

import chess
import torch

from elovision.config import RATINGS, ModelConfig
from elovision.device import resolve_device
from elovision.inference import MaiaPolicy


def sync(device):
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)


def benchmark(device, repeats):
    config = replace(ModelConfig(), device=device)
    policy = MaiaPolicy(config)
    actual_device = None
    try:
        start = time.perf_counter()
        policy.load()
        load_seconds = time.perf_counter() - start
        actual_device = str(next(policy.model.parameters()).device)
        sync(actual_device)

        board = chess.Board()
        def predict(ratings):
            return policy.predict(board, ratings)
        for _ in range(5):
            predict([(1600, 1600)])
        sync(actual_device)
        if actual_device.startswith("cuda"):
            torch.cuda.reset_peak_memory_stats(actual_device)

        latencies = []
        for _ in range(repeats):
            sync(actual_device)
            started = time.perf_counter()
            distribution = predict([(1600, 1600)])[0]
            sync(actual_device)
            latencies.append(time.perf_counter() - started)

        sync(actual_device)
        started = time.perf_counter()
        rating_pairs = [(rating, rating) for rating in RATINGS]
        all_ratings = [
            {"player_elo": pair[0], "opponent_elo": pair[1], "moves": moves}
            for pair, moves in zip(rating_pairs, predict(rating_pairs))
        ]
        sync(actual_device)
        all_ratings_seconds = time.perf_counter() - started

        peak_vram_mb = (
            round(torch.cuda.max_memory_allocated(actual_device) / (1024**2), 2)
            if actual_device.startswith("cuda")
            else None
        )
        median = statistics.median(latencies)
        p95 = sorted(latencies)[math.ceil(len(latencies) * 0.95) - 1]
        return {
            "requested_device": device,
            **policy.metadata,
            "threads": config.threads,
            "checkpoint_load_seconds": round(load_seconds, 3),
            "single_position_median_ms": round(median * 1000, 3),
            "single_position_p95_ms": round(p95 * 1000, 3),
            "single_position_positions_per_second": round(1 / median, 2),
            "all_14_ratings_seconds": round(all_ratings_seconds, 3),
            "all_14_ratings_per_second": round(14 / all_ratings_seconds, 2),
            "peak_vram_mb": peak_vram_mb,
            "legal_move_count": len(distribution),
            "probability_sum": sum(item["probability"] for item in distribution),
            "all_rating_results": all_ratings,
        }
    finally:
        policy.model = None
        if actual_device and actual_device.startswith("cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devices", choices=("cpu", "auto", "both"), default="both")
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    if args.repeats < 3 or args.repeats > 1000:
        parser.error("--repeats must be between 3 and 1000")

    if args.devices == "both":
        devices = ["cpu"]
        try:
            if resolve_device(torch, "auto").startswith("cuda"):
                devices.append("cuda")
        except Exception:
            pass
    else:
        devices = [args.devices]

    results = [benchmark(device, args.repeats) for device in devices]
    cpu_results = next((item for item in results if item["device"] == "cpu"), None)
    if cpu_results:
        cpu_by_move = {
            (item["player_elo"], item["opponent_elo"]): {
                move["uci"]: move["probability"] for move in item["moves"]
            }
            for item in cpu_results["all_rating_results"]
        }
        for result in results:
            if result["device"] == "cpu":
                continue
            deltas = [
                abs(
                    probability
                    - cpu_by_move[(entry["player_elo"], entry["opponent_elo"])][move["uci"]]
                )
                for entry in result["all_rating_results"]
                for move in entry["moves"]
                for probability in [move["probability"]]
            ]
            result["cpu_gpu_max_probability_delta"] = max(deltas, default=0.0)
    for result in results:
        result.pop("all_rating_results", None)
    print(json.dumps({"benchmarks": results}, indent=2))


if __name__ == "__main__":
    main()

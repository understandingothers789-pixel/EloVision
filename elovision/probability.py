"""Fail closed on invalid model output; never supply a fallback distribution."""

import math

from .errors import VisionError


def validate_distribution(moves: list[dict], legal_uci: set[str]) -> None:
    found = [move["uci"] for move in moves]
    if len(found) != len(set(found)) or set(found) != legal_uci:
        raise VisionError(
            "invalid_policy", "Maia's policy did not cover exactly the legal moves.", 500
        )
    values = [move["probability"] for move in moves]
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in values):
        raise VisionError(
            "invalid_policy", "Maia returned a nonfinite or invalid probability.", 500
        )
    if legal_uci and not math.isclose(math.fsum(values), 1.0, abs_tol=1e-6):
        raise VisionError(
            "invalid_policy", "Maia's legal-move probabilities did not sum to 1.", 500
        )

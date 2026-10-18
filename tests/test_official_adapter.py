"""Exercise the official tokenizer, vocabulary and adapter using explicit test logits."""

from collections import deque

import chess
import pytest
import torch
from maia3.dataset import get_historical_tokens, tokenize_board
from maia3.uci import parse_args
from maia3.utils import get_all_possible_moves, mirror_move

from elovision.config import ModelConfig
from elovision.inference import MaiaPolicy
from elovision.probability import validate_distribution


class LogitRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, tokens, self_elos, oppo_elos):
        self.calls.append((tokens.clone(), self_elos.tolist(), oppo_elos.tolist()))
        # Distinct deterministic logits expose wrong move indices or mirrored promotions.
        logits = torch.arange(4352).float().unsqueeze(0).expand(len(self_elos), -1) / 1000
        return logits, None, None


def adapter(tmp_path):
    policy = MaiaPolicy(ModelConfig(model_dir=tmp_path))
    policy.cfg = parse_args(["--model", "79m", "--device", "cpu", "--no-use-amp"])
    policy.vocabulary = {move: i for i, move in enumerate(get_all_possible_moves())}
    policy.model = LogitRecorder()
    return policy


@pytest.mark.parametrize(
    "fen",
    [
        chess.STARTING_FEN,
        "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
        "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        "4k3/P7/8/8/8/8/8/4K3 w - - 0 1",
        "4k3/8/8/8/8/8/p7/4K3 b - - 0 1",
    ],
)
def test_mask_softmax_and_all_special_moves(tmp_path, fen):
    policy = adapter(tmp_path)
    board = chess.Board(fen)
    result = policy.predict(board, [(1000, 1000), (2400, 2400)])
    assert len(result) == 2
    validate_distribution(result[0], {m.uci() for m in board.legal_moves})
    indices = [
        policy.vocabulary[m["uci"] if board.turn else mirror_move(m["uci"])] for m in result[0]
    ]
    expected = torch.softmax(torch.tensor(indices).float() / 1000, dim=0)
    assert [m["probability"] for m in result[0]] == pytest.approx(expected.tolist(), abs=1e-7)
    assert policy.model.calls[0][1:] == ([1000, 2400], [1000, 2400])


def test_real_history_matches_official_preprocessing(tmp_path):
    policy = adapter(tmp_path)
    board = chess.Board()
    history = deque([tokenize_board(board)], maxlen=8)
    for move in ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1"]:
        board.push_uci(move)
        history.append(tokenize_board(board))
    policy.predict(board, [(1600, 2200)])
    expected = get_historical_tokens(history, policy.cfg, 0, 0, 0, 0)
    assert torch.equal(policy.model.calls[0][0][0], expected)
    assert policy.model.calls[0][1:] == ([1600], [2200])

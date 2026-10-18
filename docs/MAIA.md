# Maia 3 integration research

Inspected official repository: `https://github.com/CSSLab/maia3`, commit `1e13597c42d4858b7cfd7cfdae01e297263364b2`. The installed dependency is pinned to that archive; no upstream modifications are made.

## What the source establishes

- `maia3/model_registry.py` declares `maia3-79m` → `UofTCSSLab/Maia3-79M/maia3-79m.pt`, with eight history positions, 1024 transformer width, eight blocks and 32 attention heads.
- `maia3/models.py::MAIA3Model.forward` accepts `(tokens, self_elos, oppo_elos)` and returns move logits of shape `(B,4352)`, value logits and ponder logits. Only move logits are used.
- `maia3/dataset.py` and `maia3/utils.py` define tokenization, history padding, vocabulary, legal masking and black-side mirroring. Each history board is tokenized using **its own side-to-move perspective**, exactly as upstream's `--use-uci-history` replay does. Do not reinterpret all historical boards from the final player's perspective.
- `maia3/uci.py::score_moves` masks illegal logits to negative infinity then applies softmax with no temperature for its reported policy. Its sampling method and UCI WDL/centipawn compatibility fields are separate. ELO Vision calls the neural model directly and preserves that legal-policy transformation, with all legal moves retained.
- The vocabulary has 4096 source/destination pairs plus 256 promotion entries. Mirroring converts black promotions to the supported seventh-to-eighth-rank representation. SAN/UCI and legal move generation come from python-chess, including castling and en passant.
- The official loader handles `model_state_dict` wrappers and the legacy `smolgen`→`gab` naming. ELO Vision retains those rules but requires strict key matching to avoid accepting an incompletely loaded model. It always uses tensor-only deserialization.
- Rating embeddings interpolate numeric inputs after clamping to 0–5000. **This is an implementation bound, not a statement about training/evaluation coverage.** Within ELO Vision's requested 400–3000 interval, the inputs are passed unchanged. The UI links the two inputs; the reusable API can pass them independently.

## Licensing and acquisition

The official source `LICENSE` is GNU AGPL v3. ELO Vision ships that license and uses compatible AGPL licensing. No model weights are bundled or committed. Weight acquisition is an explicit separate command, with official LFS SHA-256 verification and an immutable resolved revision recorded locally.

The official 79M metadata and model card were retrieved at revision `a107d6ceb7b298cb04ae1da4edffe2939858b894`. The model card explicitly states **AGPLv3** and training on Lichess games from January 2023 through July 2025. Its structured YAML does not include a license field, so the install manifest's fallback is “see model card.” Both Xet and the supported regular HTTP download route failed on the weight CDN `us.aws.cdn.hf.co` under the cloud proxy. The default installer uses HTTP to avoid requiring Xet transfer support; TLS and checksum verification remain intact.

The official README links the Chessformer paper (`arxiv.org/abs/2605.19091`) and model collection. Neither the inspected inference package, its README, nor the model card establishes rating-specific training/evaluation support. That question remains open; the UI warns about it, particularly at the extremes. No unsupported claim of calibration or FIDE transfer is made.

## Remaining empirical validation

Adapter tests verify exact official input tensors, move mapping, masking/softmax, black promotions and rating passage with **test-only logits**. Those checks do not establish neural accuracy or checkpoint compatibility. Six integration tests and the benchmark require the actual checksum-verified 79M weights. A successful download, strict load, real-policy tests and target-Windows smoke run remain necessary before calling the end-to-end product verified.

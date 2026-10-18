# Validation record

Current development environment: Linux x86-64, Python 3.12.14, CPU PyTorch 2.8.0+cpu, pinned Maia source `1e13597c42d4858b7cfd7cfdae01e297263364b2`, headless system Chromium. No Windows machine or AMD GPU was available.

## Completed checks

- Production dependency installation and editable installation with development dependencies.
- **45 passed, 6 skipped** using the full pytest suite with `ELOVISION_BROWSER_URL` and system Chromium configured. The six skips are explicitly the real-model tests.
- Chess tests: opening, middlegame and endgame legal moves; both colors; castling, en passant, all promotions; checkmate and stalemate; PGN mainline navigation; variations; multi-game and custom-FEN imports; malformed PGNs and invalid/mismatched histories.
- Policy tests: legal-set completeness, nonfinite/negative/unnormalized outputs rejected, linked versus independent rating passage, all 14 groups, rating bounds, history/model-sensitive caching, LRU capacity and defensive copies.
- Official adapter tests: exact upstream history tensors, legal-mask/softmax parity, black-side move mirroring and promotion indices. Logits in these tests are deterministic **test fixtures**, not Maia predictions.
- HTTP tests: independent and linked rating endpoints, missing-weight errors, local-origin/host restrictions, bundled assets, and full-precision CSV/JSON equality with computed policies. Policy values in these isolated API tests come from an explicitly injected test double.
- Browser tests: upload the actual Opera Game PGN, synchronize board and notation, arrow-key/ply navigation, preserve the position when changing Elo, flip orientation, checkmate display, invalid FEN feedback, responsive widths 1024 and 390; comparison sorting, 14-column spectrum, chart selection, download interaction and debounced latest-rating results. Rendering tests route explicit test policies; the production app has no fake-policy mode.
- Ruff checks/formatting, Python bytecode compilation, JavaScript syntax, and local server startup.
- Standalone-preview regression: production styling and JavaScript, SVG pieces and actual sample-game states are embedded in one HTML file. In a sandboxed iframe with all network requests blocked, the board renders, pieces load, sample navigation and rating changes work, and no uncaught JavaScript errors or external requests occur. No model probabilities are embedded.

## Blocked / unverified

- **Official model acquisition:** Python requests retrieved official metadata and the model card, but the weight transfer fails at `us.aws.cdn.hf.co` under the cloud proxy. Both Xet and regular HTTP were tested. Required hosts have been saved in the environment draft. Saving that draft does not apply the runtime network policy or publish a snapshot.
- **Real 79M inference and benchmarks:** six model tests are skipped, and no latency numbers or accuracy measurements are reported. The app correctly displays an actionable missing-model message.
- **Windows 11 / Ryzen / RX 9070 XT:** launchers and CPU-only dependency selection are implemented, but actual Windows execution is untested.
- **Training rating coverage:** the official source and retrieved model card do not specify rating-specific coverage; the paper has not been retrieved. The card states AGPLv3 and Lichess training data from January 2023 through July 2025. The app labels rating uncertainty, and no weights are redistributed.

## Finish verification after access is available

From the project root, with the virtual environment's Python:

```sh
python -m elovision model install
python -m elovision model verify
python -m pytest -q -m model
python scripts/benchmark.py
```

Stop/restart the app. Import `samples/opera-game.pgn`, select a playable middlegame, compare 1600 and 2200 linked ratings, inspect every legal move, compare 1000 vs. 2400, run Spectrum, return to a previous position and confirm a cache hit, and export both formats. Verify displayed probabilities and exported raw values refer to the same position and rating conditions. Repeat on Windows 11 using `install.bat` then `start.bat`. Verify initialization, one-rating, all-rating and cached latency on the user's actual CPU.

Inspect the official model card/paper for the supported rating distribution before upgrading the UI's coverage wording. A successful tensor load or a normalized policy is not evidence of predictive calibration.

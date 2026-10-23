# Validation record

Current development environment: Linux x86-64, Python 3.12.14, CPU PyTorch 2.8.0+cpu, pinned Maia source `1e13597c42d4858b7cfd7cfdae01e297263364b2`, headless system Chromium. No Windows machine, AMD GPU, or NVIDIA GPU was available.

## Completed checks

- Maia/Stockfish continuations: **34 passed** in the complete browser/preview
  suite; **100 passed, 1 skipped** in the non-model, non-browser suite. New
  checks exercise legal UCI `searchmoves`, rejection of invalid/duplicate root
  moves, searching only missing Maia choices, preserving the independent engine
  ranking and gauge, numbered continuations for both colors, navigation cache
  reuse, MultiPV isolation, cancellation on navigation, recoverable errors,
  per-line expansion, SF Only graph visibility, and mobile overflow. Browser
  policies and engine lines are explicit fixtures; UCI checks use an executable
  protocol fixture. These do not establish real Stockfish strength or neural
  accuracy. JavaScript syntax, Ruff lint/format checks for all Python sources,
  and `git diff --check` pass. Existing Python formatting inconsistencies were
  normalized to satisfy the repository's formatting check.
- Adjustable workspaces: **31 passed** with the complete browser/standalone-preview
  suite in Chromium against the local server. Checks cover dragging the notebook
  below the board, all eight resize handles, square-board scaling, collision
  handling, keyboard movement/resizing, Escape cancellation, saved layouts,
  per-page presets/reset, corrupt or unavailable storage, mobile fallback, and
  existing PGN/analysis/engine controls. Moving/resizing the live SF Only rating
  graph preserves its controls and does not submit another analysis request.
  Browser rendering fixtures do not validate neural accuracy. JavaScript syntax,
  Ruff on changed Python files, `git diff --check`, and preview generation passed.
  Board focus additionally verifies a board at least 700 pixels wide on a
  1920×1080 display, a fully visible square board at 1366×768 and 1600×900,
  optional statistics, compact desktop spacing, and persistence after customization.
- NVIDIA Windows environment addition: **45 passed** using
  `pytest -q tests/test_windows_runtime.py tests/test_device.py`. Coverage includes
  the existing AMD path, CUDA wheel selection for older cards and Blackwell,
  NVIDIA-only and mixed-vendor startup, failed/partial installs, failed inference
  and native crashes, explicit CPU/GPU overrides, rejecting CPU output from a GPU
  probe, probability-comparison validation, and reuse of the loaded model. These
  use mocked Windows/GPU subprocesses and model results; they are not actual CUDA
  inference. The official CUDA 12.6/12.8 indexes list Torch 2.8.0 Windows Python
  3.12 wheels. CLI help, Ruff checks on changed Python files, and
  `git diff --check` passed. No Python or Torch installation was changed here.
- Latest Windows CPU/AMD environment changes: **80 passed, 8 skipped** with
  `pytest -q -m 'not browser'`; 20 browser tests were deselected. Seven skips need
  real model weights/GPU hardware; one standalone-preview check needs Chromium
  configuration. Ruff and `git diff --check` passed. The local server started,
  served HTML and health requests successfully, and was stopped after the check.
  Windows orchestration tests cover adapter discovery, discrete Radeon selection,
  CPU/GPU probability comparison validation, partial installs, exact AMD Torch
  constraints, explicit device overrides, failed inference/native crashes, and
  CPU fallback. These orchestration tests use mocked subprocesses, not a Windows GPU.
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
- **Windows 11 / Ryzen / RX 9070 XT:** isolated CPU/AMD installation, adapter detection,
  real-inference launch checks, and CPU fallback are implemented. Actual Windows
  execution, AMD package download/installation and RX 9070 XT inference remain
  untested in the cloud. See [Windows GPU setup](WINDOWS_GPU.md); the installer
  requires a local real-model CPU/GPU comparison before enabling the AMD environment.
- **Windows NVIDIA:** isolated CUDA installation, real-inference startup checks,
  device selection, and CPU fallback are implemented and covered by mocked tests.
  Actual Windows CUDA package installation, GPU inference, performance, and VRAM
  use remain unverified here. The local installer must pass real Maia CPU/CUDA
  comparisons before `.venv-nvidia` is eligible for automatic selection.
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

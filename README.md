# ELO Vision

Explore how human chess choices change with playing strength. Import a PGN, move through a game, and compare Maia 3 79M's complete legal-move policy across **400–3000 Lichess blitz ratings**. Everything runs locally; normal analysis has no network dependency or paid API.

**Validation status:** the Python backend, official Maia tokenizer/vocabulary adapter, PGN navigation, exports, and browser interactions have been tested on Linux with CPU PyTorch. Official model metadata and the AGPLv3 model card were retrieved, but the cloud proxy blocks the weight CDN. Real-model loading/inference, model benchmarks, and Windows execution have **not** been verified. The app reports missing weights and never supplies fabricated probabilities. See [validation](docs/VALIDATION.md) for exact checks and remaining acceptance steps.

## Run on Windows 11

1. Install **64-bit Python 3.12** from [python.org](https://www.python.org/downloads/windows/), including the Python launcher.
2. Download and extract this repository, or clone it. Keep the whole project directory together.
3. Double-click **`install.bat`**. It creates `.venv`, installs CPU PyTorch and the pinned official Maia code, then downloads and SHA-256 verifies the official 79M checkpoint. Internet is required for this one-time step. The terminal stays open if a step fails.
4. Double-click **`start.bat`**. The local server starts and opens your browser. Keep its terminal open while using the application; close it or press Ctrl+C to stop.
5. Click **Import PGN**, or **Open a sample game**. Use the move list, navigation controls, or left/right keys. The slider defaults to **1600 vs. 1600**.

The recommended initial device is **CPU**, including on the Ryzen 7 9800X3D / RX 9070 XT system. No CUDA assumption or AMD GPU requirement is made. The 79M checkpoint has roughly 316 MB of float32 parameters; the download/cache can use additional disk space. Performance and peak memory have not yet been measured on the target PC.

## Features

- Offline piece graphics, board flip, coordinates, last-move and check highlights, and ply navigation.
- Multi-game PGN import; UTF-8/BOM, UTF-16 and Windows-1252 files; custom starting FENs; standard-chess mainlines. Variations do not alter the mainline and are not navigable in v1.
- Top 5, top 10, or every legal move, including actual-game move probability and rank.
- Equal-rated opponents everywhere in the UI: selecting 2200 sends **2200 for both ratings**.
- Two-rating comparison with signed percentage-point differences and five sorting options.
- All 14 rating groups, a scrollable legal-move matrix, and a move-specific line chart.
- Full-precision CSV/JSON exports with FEN, game/ply, rating conditions, history, and model provenance.
- A reusable, versioned Python/HTTP backend for later [Nocturne reuse](docs/BACKEND.md), without any Nocturne integration.
- Lazy model loading once per session, bounded history-aware LRU cache, background inference, request debouncing, and rejection of stale UI responses.

## Linux / macOS development

Python 3.12 is recommended. Run from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m elovision model install
.venv/bin/python -m elovision serve --open
```

On macOS, install `torch==2.8.0` from the default PyPI index instead of the CPU-specific index. macOS itself has not been tested. On Windows the Python executable is `.venv\Scripts\python.exe`.

The server binds to `127.0.0.1:8765` and rejects foreign hosts/origins. Use `serve --port 8766` if that port is occupied. This is a single-user local application; it is not configured for public hosting. Import limits: 2 MB per PGN, 100 games per file, 3000 plies per game. API docs are served at `/docs` by the running app.

## Model acquisition and inference

The official code is pinned to [CSSLab/maia3 at 1e13597](https://github.com/CSSLab/maia3/tree/1e13597c42d4858b7cfd7cfdae01e297263364b2). The installer resolves [UofTCSSLab/Maia3-79M](https://huggingface.co/UofTCSSLab/Maia3-79M) to an immutable revision, downloads `maia3-79m.pt` using the official HTTP transport, verifies the SHA-256 from the official Hugging Face LFS metadata, and records the revision, checksum, and any structured license metadata in `.models/manifest.json`. The inspected model card explicitly states AGPLv3, although its YAML has no license field. Model weights and virtual environments are ignored by Git.

```sh
python -m elovision model install          # retain an already verified installation
python -m elovision model verify          # verify the local checksum without network access
python -m elovision model install --force  # explicitly replace corrupted or outdated weights
```

Normal inference reads only these local files and uses `torch.load(weights_only=True)` with strict state-dict loading. The adapter reuses upstream preprocessing, eight-position history, 4352-entry move vocabulary, black-side mirroring, promotion encoding, legal masking, and unmodified softmax. It does not use UCI MultiPV, a sampling temperature, top-k, top-p filtering, or a chess engine as a substitute. See [research notes](docs/MAIA.md).

For an offline PC, install on a connected machine with the same OS/Python version first, then copy the project including `.models` and prepare an appropriate local wheelhouse. Virtual environments should be recreated on the destination machine, not moved between operating systems. All frontend resources are bundled.

Optional local settings:

| Variable | Purpose | Default |
| --- | --- | --- |
| `ELOVISION_MODEL_DIR` | Directory containing the checkpoint and manifest | Project `.models` |
| `ELOVISION_THREADS` | CPU inference thread limit, capped at 4 | min(4, CPU count) |

Do not change model files while the server is running; restart to use a new checkpoint. The installer needs public access to `github.com`, `codeload.github.com`, package indexes, `huggingface.co`, and the Hugging Face download hosts. No account or API key should be needed for the public release. A cloud network-policy denial is resolved in environment settings, not by providing a token.

## Rating interpretation

This predicts **human choices conditioned on Lichess blitz ratings**, not FIDE ratings, measured frequencies, or objectively strongest moves. The inference implementation accepts 0–5000 before its own clamp; ELO Vision exposes the requested 400–3000 without changing the requested rating. That numerical acceptance does not prove training or evaluation support at every rating. Rating-specific coverage remains unverified; the interface explicitly warns about uncertainty, especially at the extremes. No inference accuracy claim is made from the unit tests.

## Tests

```sh
python -m pytest -q                         # includes real-model tests when weights exist
python -m pytest -q -m model                # real 79M integration checks; skipped if absent
ruff check elovision tests scripts
ruff format --check elovision tests scripts
node --check elovision/static/app.js        # optional JS syntax check for developers
python scripts/benchmark.py                # requires real verified weights
```

Browser tests use Playwright and a running local server. Install Chromium with `python -m playwright install chromium`, start the app in another terminal, and set `ELOVISION_BROWSER_URL` to its local address before running `python -m pytest -q -m browser`. `ELOVISION_CHROMIUM` can point to a system Chromium executable. Browser presentation fixtures are test-only and do not validate neural inference. Windows PowerShell uses `$env:ELOVISION_BROWSER_URL = 'http://127.0.0.1:8765'`.

## Troubleshooting

- **Python not found:** install Python 3.12 with its launcher; verify `py -3.12 --version` and rerun `install.bat`.
- **Weights missing / download denied:** rerun `install.bat` with network access, or `python -m elovision model install` inside the virtual environment. Keep package signatures, TLS and checksum verification enabled.
- **Checksum mismatch:** stop the server and run `python -m elovision model install --force`.
- **Model initialization failure:** use the pinned dependencies and 79M weights, not a different-sized checkpoint. Reinstall into a clean virtual environment if necessary.
- **PGN error:** check the indicated game and illegal move. Only standard chess is supported. A malformed PGN is rejected instead of displaying a silently truncated game.
- **Slow first analysis:** initialization and checksum verification happen once, on the first prediction. Subsequent calls reuse the model. All-rating inference runs in small CPU batches; the browser remains interactive.
- **No moves:** checkmate/stalemate return an empty move list and no fabricated policy. Other legally playable draw positions can still expose legal-move predictions.
- **Port occupied:** run `python -m elovision serve --port 8766 --open`. Do not start a second server on the same port.

## License and credits

ELO Vision is licensed under **AGPL-3.0**, consistent with the official Maia source dependency and the inspected 79M model card. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md). Weights are not redistributed in this repository. Chess rules and bundled SVG piece graphics use python-chess. The sample is Paul Morphy's 1858 Opera Game.

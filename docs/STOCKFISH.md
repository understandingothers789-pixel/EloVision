# Optional Stockfish 19 analysis

Maia and Stockfish answer different questions. Maia estimates the moves humans choose at a given Lichess blitz rating. Stockfish searches the position and reports engine evaluations and principal variations. The two outputs are shown separately so a popular human move is not mistaken for the engine's strongest move.

## Install a local engine

1. Download the official Stockfish 19 build for the computer running ELO Vision from [stockfishchess.org/download](https://stockfishchess.org/download/).
2. Extract the downloaded archive.
3. In ELO Vision, open the **Stockfish 19** panel and choose the extracted engine executable. The app checks its UCI identification and saves the selected program under `.engines/` for later runs.

Choose the build matching the computer's operating system and processor. On a Windows PC, choose the `.exe` file. The engine is optional and is not included in the ELO Vision ZIP; it does not change Maia installation or analysis. A CPU build works without CUDA.

The app starts Stockfish as a separate UCI process. It searches the currently displayed position and game history, then shows up to five principal variations, the first move of each line, the search depth, and evaluation from White's perspective. Choose a deeper search for more analysis time. `ELOVISION_STOCKFISH` can point to an existing Stockfish 19 executable instead of using the in-app file chooser. `ELOVISION_STOCKFISH_THREADS` sets the engine thread count (default 2, maximum 8).

The official upstream repository contains the `sf_19` source tag. Stockfish is GPLv3 licensed. ELO Vision does not redistribute its binary; users obtain the matching build from the official download site. See the [Stockfish source and license](https://github.com/official-stockfish/Stockfish/tree/sf_19).

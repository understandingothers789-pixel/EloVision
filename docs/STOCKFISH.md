# Optional Stockfish engine analysis

Maia and Stockfish answer different questions. Maia estimates the moves humans choose at a given Lichess blitz rating. Stockfish searches the position and reports engine evaluations and principal variations. The main **Human + SF** view shows these side by side; **Stockfish** switches to engine-only analysis. Maia’s gauge is the probability of its top predicted human move. Stockfish’s gauge is its evaluation from White’s perspective.

In the **Analysis** workspace, choose the human rating from the Maia column heading. The comparison card shows each model’s favorite and how frequently Maia predicts the engine favorite. Hover or focus a move for its probability, available engine score, rank, and loss versus the best engine line; its arrow is isolated on the board. Moves outside the requested engine lines show “Not searched.” Use **All legal moves** to expand the human list.

**Moves by Rating** plots the top human choices and includes the engine favorite when it falls outside that group. Move colors match the human list and chart legend. Hover the graph or focus a point for exact values; click legend labels to hide or show curves. The horizontal axis is Lichess blitz rating and the vertical axis is Maia move probability. The chart respects the selected opponent rating setting. **Analysis options** contains arrow counts, search depth, line count, variations, and opponent settings. The separate **Maia Explorer** tab keeps the rating columns, comparison matrix, spectrum, and exports.

## Install a local engine

1. In **Engine setup**, choose **Official Stockfish 19** or **My development build**. Download Stockfish 19 from [stockfishchess.org/download](https://stockfishchess.org/download/), or use the link there to get a current development build from [the Stockfish testing server](https://tests.stockfishchess.org/).
2. Extract the downloaded archive.
3. Choose the extracted engine executable (up to **512 MiB**, about 537 MB). The upload streams to disk, then the app starts it and completes a UCI handshake before replacing the previously installed engine. Development builds must identify themselves as `Stockfish dev…` over UCI.

Choose the build matching the computer's operating system and processor. On a Windows PC, choose the `.exe` file. The engine is optional and is not included in the ELO Vision ZIP; it does not change Maia installation or analysis. A CPU build works without CUDA.

The engine must match the operating system running ELO Vision, not just the browser. For example, a Windows `.exe` needs the Windows app from `start.bat`; a browser connected to a Linux-hosted app cannot run that `.exe`. ELO Vision reports obvious Windows/Linux binary mismatches and UCI startup failures. Also make sure the selected executable matches **Official Stockfish 19** or **My development build**.

The app starts Stockfish as a separate UCI process. It searches the currently displayed position and game history, then shows up to twelve candidate moves and evaluations. Turn on **Show variations** to display the principal variation for each line. Choose a deeper search or more lines for more analysis time. `ELOVISION_STOCKFISH` can point to an existing engine executable instead of using the in-app file chooser; set `ELOVISION_STOCKFISH_CHANNEL=development` for a dev build. `ELOVISION_STOCKFISH_THREADS` sets the engine thread count (default 2, maximum 8).

The official upstream repository contains the `sf_19` source tag. Stockfish is GPLv3 licensed. ELO Vision does not redistribute either binary; users obtain the matching build from the official download or testing sites. See the [Stockfish 19 source and license](https://github.com/official-stockfish/Stockfish/tree/sf_19).

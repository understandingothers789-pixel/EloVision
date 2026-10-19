# Optional Stockfish engine analysis

Maia and Stockfish answer different questions. Maia estimates the moves humans choose at a given Lichess blitz rating. Stockfish searches the position and reports engine evaluations and principal variations. The main **Human + SF** view shows these side by side; **Stockfish** switches to engine-only analysis. Maia’s gauge is the probability of its top predicted human move. Stockfish’s gauge is its evaluation from White’s perspective.

## Install a local engine

1. In **Engine setup**, choose **Official Stockfish 19** or **My development build**. Download Stockfish 19 from [stockfishchess.org/download](https://stockfishchess.org/download/), or use the link there to get a current development build from [the Stockfish testing server](https://tests.stockfishchess.org/).
2. Extract the downloaded archive.
3. Choose the extracted engine executable (up to **512 MiB**, about 537 MB). The upload streams to disk, then the app starts it and completes a UCI handshake before replacing the previously installed engine. Development builds must identify themselves as `Stockfish dev…` over UCI.

Choose the build matching the computer's operating system and processor. On a Windows PC, choose the `.exe` file. The engine is optional and is not included in the ELO Vision ZIP; it does not change Maia installation or analysis. A CPU build works without CUDA.

The engine must match the operating system running ELO Vision, not just the browser. For example, a Windows `.exe` needs the Windows app from `start.bat`; a browser connected to a Linux-hosted app cannot run that `.exe`. ELO Vision reports obvious Windows/Linux binary mismatches and UCI startup failures. Also make sure the selected executable matches **Official Stockfish 19** or **My development build**.

The app starts Stockfish as a separate UCI process. It searches the currently displayed position and game history, then shows up to twelve candidate moves and evaluations. Turn on **Show variations** to display the principal variation for each line. Choose a deeper search or more lines for more analysis time. `ELOVISION_STOCKFISH` can point to an existing engine executable instead of using the in-app file chooser; set `ELOVISION_STOCKFISH_CHANNEL=development` for a dev build. `ELOVISION_STOCKFISH_THREADS` sets the engine thread count (default 2, maximum 8).

The official upstream repository contains the `sf_19` source tag. Stockfish is GPLv3 licensed. ELO Vision does not redistribute either binary; users obtain the matching build from the official download or testing sites. See the [Stockfish 19 source and license](https://github.com/official-stockfish/Stockfish/tree/sf_19).

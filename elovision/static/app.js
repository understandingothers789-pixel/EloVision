const $ = (id) => document.getElementById(id);
const RATINGS = Array.from({ length: 14 }, (_, i) => 400 + i * 200);
const MAX_ENGINE_BYTES = 512 * 1024 * 1024;
const MOVE_COLORS = ["#ffd76c", "#58b36e", "#228f4c", "#e3e5ad", "#ed755e"];
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
// Set only by the standalone preview builder; contains real board states, never policy data.
const preview = globalThis.ELOVISION_PREVIEW || null;
const localUrl = (path) => new URL(path, document.baseURI).href;
const state = {
  games: [],
  ratingValues: [1400, 1800, 2200],
  opponentValues: [1400, 1800, 2200],
  game: null,
  ply: 0,
  position: null,
  flipped: false,
  workspaceTab: "analysis",
  mode: "dual",
  analysisMode: "dual",
  maiaMode: "triple",
  ratingPredictions: [],
  maiaCache: new Map(),
  stockfishPositionKey: null,
  stockfishCache: new Map(),
  predictions: [],
  stockfish: null,
  stockfishAvailable: false,
  wholeGameController: null,
  hoverMove: null,
  hiddenChartMoves: new Set(),
  selectedMove: null,
  revision: 0,
  timer: null,
  controller: null,
};

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    $("toast").hidden = true;
  }, 3000);
}
function alert(message = "") {
  $("alert").textContent = message;
  $("alert").hidden = !message;
}
function readMaiaCache(data) {
  const key = JSON.stringify(data);
  if (!state.maiaCache.has(key)) return null;
  const cached = state.maiaCache.get(key);
  state.maiaCache.delete(key);
  state.maiaCache.set(key, cached);
  return {
    ...structuredClone(cached),
    predictions: cached.predictions.map((prediction) => ({
      ...structuredClone(prediction),
      cached: true,
    })),
  };
}
async function api(path, data, signal) {
  if (preview) {
    if (path === "health") return { loaded: false, installed: false };
    if (path === "engine/status") return { available: false, message: "Stockfish analysis requires the installed local app." };
    if (path.startsWith("engine/")) throw new Error("Stockfish analysis requires the installed local app.");
    if (path === "samples") return preview.samples.map(({ metadata }) => metadata);
    if (path === "position") {
      for (const sample of preview.samples) {
        const position = sample.parsed.games[0].positions.find((p) => p.fen === data.fen);
        if (position) return structuredClone(position);
      }
    }
    if (path === "pgn") {
      const sample = preview.samples.find((entry) => entry.metadata.pgn === data.pgn);
      if (sample) return structuredClone(sample.parsed);
    }
    throw new Error(
      "This standalone preview supports the sample game and board navigation. " +
        "Run start.bat in the installed ELO Vision app for PGN imports and real Maia analysis.",
    );
  }
  const cacheKey = path === "analyze" ? JSON.stringify(data) : null;
  if (cacheKey) {
    const cached = readMaiaCache(data);
    if (cached) return cached;
  }
  const response = await fetch(
    localUrl(`api/v1/${path}`),
    data === undefined
      ? { signal }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
          signal,
        },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(
      data.error?.message || `Request failed (${response.status}).`,
    );
    error.status = response.status;
    error.code = data.error?.code;
    throw error;
  }
  const result = await response.json();
  if (cacheKey && Array.isArray(result.predictions)) {
    state.maiaCache.set(cacheKey, structuredClone(result));
    while (state.maiaCache.size > 256)
      state.maiaCache.delete(state.maiaCache.keys().next().value);
  }
  return result;
}
function payload() {
  const base = { fen: state.position.fen };
  if (state.game) {
    base.initial_fen = state.game.initial_fen;
    base.moves = state.game.moves.slice(0, state.ply).map((m) => m.uci);
  }
  return base;
}
function selectedRatings() {
  if (state.mode === "spectrum") return RATINGS;
  if (state.mode === "compare")
    return [Number($("rating-a").value), Number($("rating-b").value)];
  if (state.mode === "triple") return state.ratingValues;
  return [Number($("elo").value)];
}
function selectedMatchups() {
  if (["dual", "explore"].includes(state.mode)) {
    const player = Number($("elo").value);
    const opponent = $("dual-equal").checked
      ? player
      : Number($("dual-opponent-elo").value);
    return [{ player_elo: player, opponent_elo: opponent }];
  }
  if (state.mode !== "triple") return undefined;
  const equal = $("equal-opponents").checked;
  return state.ratingValues.map((rating, i) => ({
    player_elo: rating,
    opponent_elo: equal ? rating : state.opponentValues[i],
  }));
}
function analysisRequest() {
  const request = { ...payload() };
  const matchups = selectedMatchups();
  if (matchups) request.matchups = matchups;
  else request.ratings = selectedRatings();
  return request;
}
function renderBoard() {
  const pos = state.position;
  if (!pos) return;
  const board = $("board");
  board.replaceChildren();
  const files = state.flipped ? "hgfedcba" : "abcdefgh";
  const ranks = state.flipped ? "12345678" : "87654321";
  const last = pos.last_move
    ? [pos.last_move.slice(0, 2), pos.last_move.slice(2, 4)]
    : [];
  for (let r = 0; r < 8; r++)
    for (let f = 0; f < 8; f++) {
      const square = files[f] + ranks[r];
      const dark = (files.charCodeAt(f) - 97 + Number(ranks[r])) % 2 === 1;
      const cell = node(
        "div",
        `square${dark ? " dark" : ""}${last.includes(square) ? " last" : ""}${pos.check === square ? " check" : ""}`,
      );
      cell.dataset.square = square;
      const piece = pos.pieces[square];
      if (piece) {
        const img = node("img", "piece");
        const color = piece === piece.toUpperCase() ? "w" : "b";
        const pieceId = `${color}${piece.toUpperCase()}`;
        img.src = preview
          ? preview.pieces[pieceId]
          : localUrl(`pieces/${pieceId}.svg`);
        const names = {
          p: "pawn",
          n: "knight",
          b: "bishop",
          r: "rook",
          q: "queen",
          k: "king",
        };
        img.alt = `${color === "w" ? "White" : "Black"} ${names[piece.toLowerCase()]} on ${square}`;
        img.draggable = false;
        cell.append(img);
      }
      if (f === 0)
        cell.append(node("span", "coordinate rank-coordinate", ranks[r]));
      if (r === 7)
        cell.append(node("span", "coordinate file-coordinate", files[f]));
      board.append(cell);
    }
  board.setAttribute(
    "aria-label",
    `Chessboard, ${pos.turn} to move${pos.check ? ", in check" : ""}`,
  );
  $("turn").textContent =
    pos.outcome ||
    `${capitalize(pos.turn)} to move${pos.check ? " · Check" : ""}`;
  $("legal-count").textContent = `${pos.outcome || `${capitalize(pos.turn)} to move`} · ${pos.legal_count} legal moves`;
  document.querySelectorAll(".game-player-line").forEach((line) => {
    line.classList.toggle("active-turn", line.dataset.color === pos.turn);
  });
  $("fen-display").textContent = pos.fen;
  $("ply-label").textContent = state.ply
    ? `Ply ${state.ply} / ${state.game?.moves.length || 0}`
    : "Start position";
  const end = state.game?.moves.length || 0;
  $("first").disabled = $("prev").disabled = state.ply === 0;
  $("last").disabled = $("next").disabled = state.ply >= end;
  for (const [where, color] of [
    ["top", state.flipped ? "White" : "Black"],
    ["bottom", state.flipped ? "Black" : "White"],
  ]) {
    $(where + "-player").textContent = state.game?.headers[color] || color;
    $(where + "-rating").textContent = state.game?.headers[color + "Elo"]
      ? `${state.game.headers[color + "Elo"]} · ${color} pieces`
      : `${color} pieces`;
    $(where + "-avatar").textContent = color[0];
    $(where + "-avatar").classList.toggle("light", color === "White");
  }
  document.querySelectorAll(".move-button").forEach((button) => {
    const selected = Number(button.dataset.ply) === state.ply;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-current", selected ? "step" : "false");
  });
  document
    .querySelector(".move-button.selected")
    ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  renderGauges();
  if (state.predictions.length || state.stockfish?.lines?.length)
    renderMoveArrows(state.predictions);
}
function capitalize(value) {
  return value[0].toUpperCase() + value.slice(1);
}
function navigate(ply) {
  if (!state.game) return;
  state.ply = Math.max(0, Math.min(state.game.moves.length, ply));
  state.position = state.game.positions[state.ply];
  clearStockfishResult();
  renderBoard();
  scheduleAnalysis(100);
}
function renderGame() {
  const game = state.game;
  updateWholeGameButton();
  const meta = $("game-meta");
  meta.replaceChildren();
  meta.classList.add("imported");
  meta.append(
    node(
      "h3",
      "",
      `${game.headers.White || "White"} — ${game.headers.Black || "Black"}`,
    ),
  );
  const players = node("div", "game-players");
  for (const color of ["White", "Black"]) {
    const line = node("div", "game-player-line");
    line.dataset.color = color.toLowerCase();
    line.append(node("i", `player-dot ${color.toLowerCase()}`), node("strong", "", game.headers[color] || color), node("small", "", game.headers[`${color}Elo`] || color));
    players.append(line);
  }
  meta.append(players);
  for (const [label, value] of [
    ["Event", game.headers.Event],
    ["Date", game.headers.Date],
    ["Result", game.headers.Result],
  ]) {
    const row = node("div", "metadata-line");
    row.append(node("span", "", label), node("strong", "", value || "—"));
    meta.append(row);
  }
  $("game-count").textContent =
    `${state.games.length} GAME${state.games.length === 1 ? "" : "S"}`;
  $("game-result").textContent =
    `${game.headers.Result || "*"} · Mainline · ${game.moves.length} plies`;
  const notation = $("notation");
  notation.replaceChildren();
  let row, number;
  for (const move of game.moves) {
    if (number !== move.number) {
      number = move.number;
      row = node("div", "move-row");
      row.append(node("span", "move-number", `${number}.`));
      if (move.color === "black") row.append(node("span"));
      notation.append(row);
    }
    const button = node("button", "move-button", move.san);
    button.dataset.ply = move.ply;
    button.title = `${move.number}${move.color === "white" ? "." : "…"} ${move.san}`;
    button.addEventListener("click", () => navigate(move.ply));
    row.append(button);
  }
  if (!game.moves.length)
    notation.append(
      node(
        "div",
        "notation-empty",
        "This game starts at a custom position and contains no moves.",
      ),
    );
  navigate(0);
}
async function importPgn(text) {
  const data = await api("pgn", { pgn: text });
  state.games = data.games;
  state.game = data.games[0];
  $("game-select").replaceChildren(
    ...data.games.map((game, i) => {
      const option = node(
        "option",
        "",
        `${i + 1}. ${game.headers.White} — ${game.headers.Black}`,
      );
      option.value = String(i);
      return option;
    }),
  );
  $("game-select").disabled = false;
  alert();
  renderGame();
  toast(
    `Imported ${data.games.length} game${data.games.length === 1 ? "" : "s"}`,
  );
}
function scheduleAnalysis(delay = 0) {
  if (!state.position) return;
  const cachedMaia = !preview && state.mode !== "stockfish"
    ? readMaiaCache(analysisRequest())
    : null;
  hideMoveInspector();
  if (state.chartFen !== state.position.fen) {
    state.hiddenChartMoves.clear();
    state.chartFen = state.position.fen;
  }
  const revision = ++state.revision;
  clearTimeout(state.timer);
  state.controller?.abort();
  state.chartController?.abort();
  state.predictions = [];
  if (state.mode === "dual") {
    state.ratingPredictions = [];
    $("rating-comparison-chart").replaceChildren(
      node("span", "stockfish-loading", "Updating rating comparison…"),
    );
  } else if (state.mode === "stockfish") {
    state.ratingPredictions = [];
    $("rating-comparison-chart").replaceChildren(
      node("span", "stockfish-loading", "Updating rating comparison…"),
    );
  }
  $("dual-human-moves").replaceChildren(node("div", "stockfish-loading", "Waiting for Maia analysis…"));
  $("results").replaceChildren();
  $("actual-card").hidden = true;
  $("dual-actual-card").hidden = true;
  $("comparison-more").hidden = true;
  $("spectrum-chart").hidden = true;
  setExportButtonsDisabled(true);
  renderGauges();
  renderMoveArrows();
  if (state.mode === "stockfish") {
    $("loading").hidden = true;
    $("analysis-indicator").textContent = state.stockfishAvailable ? "STOCKFISH" : "ENGINE NEEDED";
    if (state.stockfishAvailable) state.timer = setTimeout(() => analyzeStockfish(), delay);
    else engineMessage("Choose a Stockfish executable in Engine setup to analyze this position.");
    loadRatingComparisonChart(revision);
    return;
  }
  $("loading").hidden = state.mode === "dual" || Boolean(cachedMaia);
  $("analysis-indicator").textContent = cachedMaia ? "CACHED" : "ANALYZING";
  $("probability-total").textContent = "Full legal policy · No sampling";
  if (cachedMaia) {
    state.predictions = cachedMaia.predictions;
    renderPredictions();
    setExportButtonsDisabled(false);
    $("model-status").textContent = "Ready · CPU · Offline";
    if (state.mode === "dual") loadRatingComparisonChart(revision);
  }
  state.timer = setTimeout(() => {
    if (!cachedMaia) analyze(revision);
    if (state.mode === "dual" && state.stockfishAvailable && !state.stockfish)
      analyzeStockfish();
  }, delay);
}
function setExportButtonsDisabled(disabled) {
  for (const id of ["export-json", "export-csv", "export-json-tab", "export-csv-tab"])
    $(id).disabled = disabled;
}
async function analyze(revision) {
  const controller = new AbortController();
  state.controller = controller;
  try {
    const data = await api(
      "analyze",
      analysisRequest(),
      controller.signal,
    );
    if (revision !== state.revision) return;
    state.predictions = data.predictions;
    renderPredictions();
    setExportButtonsDisabled(false);
    $("analysis-indicator").textContent = data.predictions.every(
      (p) => p.cached,
    )
      ? "CACHED"
      : "MAIA 3";
    $("model-status").textContent = "Ready · CPU · Offline";
    if (state.mode === "dual") loadRatingComparisonChart(revision);
  } catch (error) {
    if (revision !== state.revision || error.name === "AbortError") return;
    const empty = node("div", "empty-state");
    empty.append(
      node("span", "empty-symbol", "✦"),
      node(
        "h3",
        "",
        preview
          ? "Analysis runs in the local app."
          : "Analysis is unavailable.",
      ),
      node("p", "", error.message),
    );
    $(state.mode === "dual" ? "dual-human-moves" : "results").replaceChildren(empty);
    if (state.mode === "dual") $("rating-comparison-chart").replaceChildren(
      node("div", "chart-empty", "The rating graph appears when local Maia analysis is available."),
    );
    $("analysis-indicator").textContent = preview ? "PREVIEW" : "UNAVAILABLE";
    $("model-status").textContent = preview
      ? "Interface preview · No backend"
      : "Model needs attention";
  } finally {
    if (revision === state.revision) $("loading").hidden = true;
  }
}
const pct = (p) => `${(p * 100).toFixed(2)}%`;
function limitRows(rows, selector = "maia-move-limit") {
  return $(selector).value === "all"
    ? rows
    : rows.slice(0, Number($(selector).value));
}
function renderPredictions() {
  const predictions = state.predictions;
  if (!predictions.length) return;
  const container = $("results");
  container.replaceChildren();
  $("spectrum-chart").hidden = true;
  $("actual-card").hidden = true;
  if (!predictions[0].moves.length) {
    const empty = node("div", "empty-state");
    empty.append(
      node(
        "h3",
        "",
        predictions[0].terminal?.replaceAll("_", " ") || "No legal moves",
      ),
      node(
        "p",
        "",
        "There is no next-move probability distribution in this position.",
      ),
    );
    const resultContainer = state.mode === "dual" ? $("dual-human-moves") : container;
    resultContainer.replaceChildren(empty);
    $("probability-total").textContent = "No legal moves";
    renderGauges();
    return;
  }
  if (state.mode === "dual") {
    $("dual-human-moves").replaceChildren();
    renderHumanComparison(predictions[0]);
    $("human-model-rating").textContent = `Maia ${predictions[0].player_elo}: Human Moves`;
    renderMoveArrows(predictions);
  }
  else if (state.mode === "triple") renderTriple(container, predictions);
  else if (state.mode === "explore") renderExplore(container, predictions[0]);
  else if (state.mode === "compare") renderCompare(container, predictions);
  else renderSpectrum(container, predictions);
  renderGauges();
  const elapsed = Math.max(...predictions.map((p) => p.elapsed_ms || 0));
  const cached = predictions.every((p) => p.cached);
  $("probability-total").textContent =
    `${cached ? "Cached" : "Model pass"} · ${elapsed.toFixed(1)} ms · ${predictions.length} matchup${predictions.length === 1 ? "" : "s"}`;
  $("history-note").textContent = state.game
    ? "Using the PGN mainline, including up to seven previous positions. Short history is padded exactly as in the official Maia pipeline."
    : "No PGN history supplied. The current position is repeated to fill the eight-position model input.";
}
function renderExplore(container, prediction, limitId = "maia-move-limit", actualId = "actual-card") {
  $(actualId).hidden = true;
  const actual = prediction.moves.find(
    (m) => m.uci === state.position.actual_move,
  );
  if (actual) {
    const card = $(actualId);
    card.replaceChildren(
      node("span", "", "Played in game: "),
      node("strong", "", actual.san),
      node(
        "span",
        "",
        ` · ${pct(actual.probability)} · rank ${actual.rank} of ${prediction.moves.length}`,
      ),
    );
    card.hidden = false;
  }
  for (const move of limitRows(prediction.moves, limitId)) {
    const row = node("div", "move-prediction");
    row.dataset.uci = move.uci;
    const label = node("div", "prediction-label");
    label.append(
      node("span", "prediction-rank", String(move.rank).padStart(2, "0")),
      node("span", "prediction-san", move.san),
      node("span", "prediction-uci", move.uci),
    );
    if (move.uci === state.position.actual_move)
      label.append(node("span", "played-tag", "PLAYED"));
    label.append(node("span", "prediction-percent", pct(move.probability)));
    const track = node("div", "probability-track");
    const bar = node("div", "probability-bar");
    bar.style.width = `${move.probability * 100}%`;
    track.append(bar);
    row.append(label, track);
    container.append(row);
  }
}
function comparisonMoves() {
  const prediction = state.predictions[0] || state.ratingPredictions[0];
  if (!prediction) return [];
  const moves = prediction.moves.slice(0, 5);
  const engineBest = state.stockfish?.lines?.[0];
  const engineMove = prediction.moves.find((move) => move.uci === engineBest?.uci);
  if (engineMove && !moves.some((move) => move.uci === engineMove.uci)) {
    if (moves.length === 5) moves.pop();
    moves.push(engineMove);
  }
  return moves;
}
function comparisonColor(uci) {
  const index = comparisonMoves().findIndex((move) => move.uci === uci);
  return index < 0 ? "#b4bbc4" : MOVE_COLORS[index];
}
function renderHumanComparison(prediction) {
  const container = $("dual-human-moves");
  container.replaceChildren();
  $("dual-actual-card").hidden = true;
  $("comparison-more").hidden = prediction.moves.length <= 5;
  $("comparison-more").textContent = $("move-limit").value === "all" ? "Top 5 moves ⌃" : `All ${prediction.moves.length} legal moves ⌄`;
  for (const move of limitRows(prediction.moves, "move-limit")) {
    const row = node("button", "move-prediction comparison-move");
    row.type = "button";
    row.dataset.uci = move.uci;
    row.style.setProperty("--move-color", comparisonColor(move.uci));
    row.append(node("span", "prediction-san", move.san), node("span", "prediction-percent", `${(move.probability * 100).toFixed(1)}%`));
    if (move.uci === state.position?.actual_move) {
      row.classList.add("is-played");
      row.setAttribute("aria-label", `${move.san}, played in game, ${pct(move.probability)}`);
    }
    bindMoveInspection(row, move.uci);
    container.append(row);
  }
}
function renderComparisonSummary() {
  const container = $("comparison-summary");
  const human = state.predictions[0]?.moves?.[0];
  const engine = state.stockfish?.lines?.[0];
  const differs = Boolean(human && engine && human.uci !== engine.uci);
  container.replaceChildren();
  container.classList.toggle("moves-disagree", differs);
  const label = node("span", "comparison-label");
  const text = node("p");
  if (state.position?.legal_count === 0) {
    label.textContent = "POSITION COMPLETE";
    text.textContent = state.position.outcome || "There are no legal moves in this position.";
  } else if (state.mode === "stockfish") {
    label.textContent = "ENGINE ANALYSIS";
    text.textContent = engine ? `Stockfish prefers ${engine.san} at ${engine.score} from White’s perspective. Hover a move to inspect it on the board.` : "Choose your local engine in Engine setup to search this position.";
  } else if (human && engine) {
    const same = human.uci === engine.uci;
    label.textContent = same ? "SHARED FAVORITE" : "≠ TOP MOVES DIFFER";
    label.classList.toggle("agrees", same);
    label.classList.toggle("disagrees", !same);
    text.append("Maia favors ", node("strong", "human-text", `${human.san} (${(human.probability * 100).toFixed(1)}%)`), "; Stockfish prefers ", node("strong", "engine-text", `${engine.san} (${engine.score})`), ". ");
    const engineInPolicy = state.predictions[0].moves.find((move) => move.uci === engine.uci);
    if (!same && engineInPolicy) text.append(`The engine favorite is Maia’s #${engineInPolicy.rank} choice at ${(engineInPolicy.probability * 100).toFixed(1)}%.`);
    if (same) text.append("Human choice and engine search agree on the top move.");
  } else {
    label.textContent = "HUMAN CHOICE · ENGINE SEARCH";
    text.textContent = human ? "Choose a Stockfish engine below to compare human choices with engine evaluations." : engine ? "Stockfish is ready. Local Maia analysis is needed to compare human move probabilities." : "Load a position and enable local Maia and Stockfish analysis to compare their favorite moves.";
  }
  container.append(label, text);
}
function hideMoveInspector() {
  state.hoverMove = null;
  const tooltip = $("move-inspector");
  if (tooltip) tooltip.hidden = true;
}
function bindMoveInspection(row, uci) {
  row.setAttribute("aria-describedby", "move-inspector");
  const show = () => {
    if (state.workspaceTab !== "analysis") return;
    state.hoverMove = uci;
    renderMoveArrows();
    const human = state.predictions[0]?.moves.find((move) => move.uci === uci);
    const line = state.stockfish?.lines?.find((move) => move.uci === uci);
    const best = state.stockfish?.lines?.[0];
    const tooltip = $("move-inspector");
    tooltip.replaceChildren(node("strong", "inspector-move", human?.san || line?.san || uci));
    for (const [label, value, color] of [
      ["Maia", human ? pct(human.probability) : "Unavailable", "human-text"],
      ["SF eval (White)", line?.score || "Not searched", "engine-text"],
      ["Maia rank", human ? `#${human.rank}` : "—", ""],
    ]) {
      const detail = node("div", "inspector-row");
      detail.append(node("span", color, label), node("strong", "", value));
      tooltip.append(detail);
    }
    if (Number.isFinite(best?.score_cp) && Number.isFinite(line?.score_cp) && best.mate == null && line.mate == null) {
      const loss = Math.max(0, (best.score_cp - line.score_cp) * (state.position.turn === "white" ? 1 : -1));
      const detail = node("div", "inspector-row");
      detail.append(node("span", "engine-text", "Loss vs. best"), node("strong", "", `${(loss / 100).toFixed(2)} pawns`));
      tooltip.append(detail);
    }
    tooltip.hidden = false;
    const rect = row.getBoundingClientRect();
    const width = tooltip.offsetWidth;
    tooltip.style.left = `${Math.max(8, Math.min(innerWidth - width - 8, rect.right + width + 10 < innerWidth ? rect.right + 10 : rect.left - width - 10))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(innerHeight - tooltip.offsetHeight - 8, rect.top))}px`;
  };
  const hide = () => { hideMoveInspector(); renderMoveArrows(); };
  row.addEventListener("pointerenter", show);
  row.addEventListener("focus", show);
  row.addEventListener("pointerleave", hide);
  row.addEventListener("blur", hide);
}
function renderTriple(container, predictions) {
  const grid = node("div", "triple-results");
  grid.style.setProperty("--rating-count", predictions.length);
  for (const prediction of predictions) {
    const card = node("section", "triple-card");
    const rating = prediction.player_elo;
    const color = eloColor(rating);
    const heading = node("h4", "triple-card-heading");
    const swatch = node("span", "elo-swatch");
    swatch.style.backgroundColor = color;
    heading.append(swatch, node("span", "", `${rating} vs. ${prediction.opponent_elo}`));
    card.append(heading);
    for (const move of limitRows(prediction.moves, "maia-move-limit")) {
      const row = node("div", "triple-move");
      row.append(node("span", "prediction-rank", String(move.rank).padStart(2, "0")), node("strong", "", move.san), node("span", "", pct(move.probability)));
      const track = node("div", "probability-track");
      const bar = node("div", "probability-bar");
      bar.style.width = `${move.probability * 100}%`;
      bar.style.backgroundColor = color;
      track.append(bar);
      row.append(track);
      card.append(row);
    }
    grid.append(card);
  }
  container.append(grid);
  renderMoveArrows(predictions);
}
function eloColor(rating) {
  const ratio = (rating - 400) / 2600;
  return `hsl(${Math.round(30 + ratio * 180)} 72% 61%)`;
}
function renderGauges() {
  const human = state.predictions?.[0]?.moves?.[0];
  const humanFill = $("maia-gauge-fill");
  const humanMarker = $("maia-gauge-marker");
  if (human) {
    const percent = human.probability * 100;
    humanFill.style.height = `${percent}%`;
    humanMarker.textContent = `${percent.toFixed(1)}%`;
    humanMarker.style.top = `${100 - percent}%`;
  } else {
    humanFill.style.height = "0%";
    humanMarker.textContent = "—";
    humanMarker.style.top = "100%";
  }
  const best = state.stockfish?.lines?.[0];
  const fill = $("sf-gauge-fill");
  const marker = $("sf-gauge-marker");
  if (!best) {
    fill.style.height = "0%";
    fill.style.top = "auto";
    fill.style.bottom = "50%";
    marker.textContent = "—";
    marker.style.top = "50%";
    renderBoardInsight();
    return;
  }
  const mate = best.mate;
  const cp = mate === null || mate === undefined ? Number(best.score_cp || 0) : Math.sign(mate || 1) * 400;
  const bounded = Math.max(-400, Math.min(400, cp));
  const percent = Math.abs(bounded) / 800 * 100;
  if (bounded >= 0) {
    fill.style.top = "auto";
    fill.style.bottom = "50%";
  } else {
    fill.style.bottom = "auto";
    fill.style.top = "50%";
  }
  fill.style.height = `${percent}%`;
  marker.textContent = mate ? (mate > 0 ? `M${mate}` : `−M${Math.abs(mate)}`) : best.score;
  marker.style.top = `${100 - (bounded + 400) / 8}%`;
  renderBoardInsight();
}
function renderBoardInsight() {
  renderComparisonSummary();
  const prediction = state.predictions?.[0];
  const playedUci = state.position?.actual_move;
  const played = prediction?.moves?.find((move) => move.uci === playedUci);
  const topMove = prediction?.moves?.[0];
  const move = played || topMove;
  const engine = state.stockfish?.lines?.[0];
  $("insight-move-label").textContent = played ? "Move in game" : "Top human move";
  $("insight-move").textContent = move?.san || "—";
  $("insight-probability").textContent = move ? pct(move.probability) : "—";
  $("insight-rank").textContent = move ? `${move.rank} / ${prediction.moves.length}` : "—";
  $("insight-rating").textContent = prediction ? `Maia ${prediction.player_elo}` : "Waiting for Maia";
  $("insight-engine").textContent = engine?.score || "Waiting";
  $("insight-fill").style.width = move ? `${move.probability * 100}%` : "0%";
  $("insight-note").textContent = played
    ? `At ${prediction.player_elo}, Maia ranks ${played.san} ${played.rank} of ${prediction.moves.length} legal moves. Stockfish's independent evaluation is shown when an engine is available.`
    : state.position?.actual_move
      ? "Waiting for Maia to score the move played in this game."
      : "No game move is selected here. Import a PGN to compare the played move with Maia and Stockfish.";
}
function renderMoveArrows(predictions = state.predictions) {
  const svg = $("move-arrows");
  svg.replaceChildren();
  const showMaia = ["dual", "triple"].includes(state.mode) && predictions?.length;
  const showEngine = ["dual", "stockfish", "triple"].includes(state.mode) && state.stockfish?.lines?.length;
  svg.hidden = !showMaia && !showEngine && !state.position?.actual_move;
  if (svg.hidden) return;
  const ns = "http://www.w3.org/2000/svg";
  const make = (tag, attrs = {}) => {
    const el = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    return el;
  };
  const defs = make("defs");
  for (const [id, fill] of [["maia-arrowhead", "context-stroke"], ["engine-arrowhead", "context-stroke"], ["played-arrowhead", "context-stroke"]]) {
    const marker = make("marker", { id, viewBox: "0 0 10 10", refX: "8", refY: "5", markerWidth: "4", markerHeight: "4", orient: "auto" });
    marker.append(make("path", { d: "M 0 0 L 10 5 L 0 10 z", fill }));
    defs.append(marker);
  }
  svg.append(defs);
  const point = (square) => {
    const file = square.charCodeAt(0) - 97;
    const rank = Number(square[1]);
    return state.flipped ? [7 - file + .5, rank - .5] : [file + .5, 8 - rank + .5];
  };
  const appendArrow = (uci, color, label, markerId, width = ".12", opacity = ".86", dashed = false) => {
    if (!uci || uci.length < 4) return;
    if (state.hoverMove && state.hoverMove !== uci) return;
    const [x1, y1] = point(uci.slice(0, 2));
    const [x2, y2] = point(uci.slice(2, 4));
    const attrs = { x1, y1, x2, y2, stroke: color, "stroke-width": width, "stroke-linecap": "round", "marker-end": `url(#${markerId})`, opacity };
    if (dashed) attrs["stroke-dasharray"] = ".2 .1";
    const line = make("line", attrs);
    const title = make("title");
    title.textContent = label;
    line.append(title);
    svg.append(line, make("circle", { cx: x2, cy: y2, r: ".13", fill: color, stroke: "#142019", "stroke-width": ".035", opacity }));
  };
  if (showMaia && state.mode === "triple") {
    for (const prediction of [...predictions].sort((a, b) => a.player_elo - b.player_elo)) {
      for (const move of prediction.moves.slice(0, 5))
        appendArrow(move.uci, eloColor(prediction.player_elo), `${prediction.player_elo} Elo: ${move.san} ${pct(move.probability)}`, "maia-arrowhead", ".105", ".8");
    }
  } else if (showMaia && state.mode === "dual") {
    const count = $("move-limit").value === "all" ? predictions[0].moves.length : Number($("move-limit").value);
    const arrowCount = $("analysis-arrows").value === "all" ? count : Math.min(count, Number($("analysis-arrows").value));
    for (const move of predictions[0].moves.filter((move, index) => state.hoverMove ? move.uci === state.hoverMove : index < arrowCount))
      appendArrow(move.uci, "#ef726b", `Maia ${predictions[0].player_elo}: ${move.san} ${pct(move.probability)}`, "maia-arrowhead", ".12", ".82");
  }
  if (showEngine) {
    const count = $("analysis-arrows").value === "all" ? Number($("stockfish-lines-count").value) : Math.min(Number($("stockfish-lines-count").value), Number($("analysis-arrows").value));
    const colors = ["#67aaff", "#78b2fa", "#8dbafa", "#a4c6f5", "#bdd3f4", "#d3e0f3", "#adc7e4", "#9ab8dc", "#86a9d4", "#739bc9", "#618dc0", "#527eaf"];
    for (const line of state.stockfish.lines.filter((line, index) => state.hoverMove ? line.uci === state.hoverMove : index < count))
      appendArrow(line.uci, colors[Math.min(line.rank - 1, colors.length - 1)], `Stockfish ${line.rank}: ${line.san} (${line.score} White eval)`, "engine-arrowhead", line.rank === 1 ? ".12" : ".095", line.rank === 1 ? ".95" : ".72");
  }
  const played = state.position?.actual_move;
  if (played) appendArrow(played, "#9bdff5", `Played in game: ${played}`, "played-arrowhead", ".14", ".98", true);
}

function createTable(headers, spectrum = false) {
  const wrap = node("div", "table-scroll");
  const table = node(
    "table",
    `compare-table${spectrum ? " spectrum-table" : ""}`,
  );
  const caption = node(
    "caption",
    "sr-only",
    spectrum
      ? "Legal move probabilities by linked rating"
      : "Move probability comparison with equal-rated opponents at each rating",
  );
  const head = node("thead"),
    row = node("tr"),
    body = node("tbody");
  for (const text of headers) {
    const th = node("th", "", text);
    th.scope = "col";
    row.append(th);
  }
  head.append(row);
  table.append(caption, head, body);
  wrap.append(table);
  return { wrap, body };
}
function moveCell(move) {
  const cell = node("td", "", move.san);
  cell.title = move.uci;
  if (move.uci === state.position.actual_move)
    cell.append(node("span", "played-tag", "●"));
  return cell;
}
function renderCompare(container, predictions) {
  const [a, b] = predictions;
  const second = new Map(b.moves.map((m) => [m.uci, m.probability]));
  const rows = a.moves.map((m) => ({
    ...m,
    a: m.probability,
    b: second.get(m.uci),
    delta: second.get(m.uci) - m.probability,
  }));
  const sort = $("compare-sort").value;
  const score = (r) =>
    ({
      absolute: Math.abs(r.delta),
      positive: r.delta,
      negative: -r.delta,
      a: r.a,
      b: r.b,
    })[sort];
  rows.sort((x, y) => score(y) - score(x));
  const { wrap, body } = createTable([
    "Move",
    `${a.player_elo}`,
    `${b.player_elo}`,
    "Δ pp (B − A)",
  ]);
  for (const move of limitRows(rows)) {
    const row = node("tr");
    row.append(
      moveCell(move),
      node("td", "", pct(move.a)),
      node("td", "", pct(move.b)),
      node(
        "td",
        move.delta >= 0 ? "increase" : "decrease",
        `${move.delta > 0 ? "+" : ""}${(move.delta * 100).toFixed(2)}`,
      ),
    );
    body.append(row);
  }
  container.append(wrap);
}
function renderSpectrum(container, predictions) {
  const { wrap, body } = createTable(
    ["Move", ...predictions.map((p) => String(p.player_elo))],
    true,
  );
  const maps = predictions.map(
    (p) => new Map(p.moves.map((m) => [m.uci, m.probability])),
  );
  const moves = [...predictions[0].moves].sort((a, b) =>
    a.san.localeCompare(b.san),
  );
  for (const move of moves) {
    const row = node("tr");
    row.append(moveCell(move));
    for (const map of maps) {
      const cell = node("td", "", pct(map.get(move.uci)));
      cell.style.backgroundColor = `rgba(182,219,165,${Math.min(0.4, map.get(move.uci) * 1.5)})`;
      row.append(cell);
    }
    body.append(row);
  }
  container.append(wrap);
  const select = $("chart-move");
  select.replaceChildren(
    ...moves.map((m) => {
      const option = node("option", "", `${m.san} · ${m.uci}`);
      option.value = m.uci;
      return option;
    }),
  );
  if (!moves.some((m) => m.uci === state.selectedMove))
    state.selectedMove =
      state.position.actual_move || predictions[0].moves[0].uci;
  select.value = state.selectedMove;
  $("spectrum-chart").hidden = false;
  renderChart();
}
function renderChart() {
  if (!state.predictions.length) return;
  const values = state.predictions.map((p) => ({
    rating: p.player_elo,
    value: p.moves.find((m) => m.uci === state.selectedMove).probability * 100,
  }));
  const max = Math.min(
    100,
    Math.max(5, Math.ceil(Math.max(...values.map((v) => v.value)) / 5) * 5),
  );
  const ns = "http://www.w3.org/2000/svg";
  function svgEl(tag, attributes = {}, text) {
    const el = document.createElementNS(ns, tag);
    for (const [key, val] of Object.entries(attributes))
      el.setAttribute(key, val);
    if (text !== undefined) el.textContent = text;
    return el;
  }
  const svg = svgEl("svg", { viewBox: "0 0 340 180" });
  svg.append(
    svgEl(
      "title",
      {},
      `Probability of ${$("chart-move").selectedOptions[0]?.textContent} across Lichess blitz ratings`,
    ),
  );
  const x = (rating) => 35 + ((rating - 400) / 2600) * 295;
  const y = (value) => 145 - (value / max) * 120;
  for (const value of [0, max / 2, max]) {
    svg.append(
      svgEl("line", {
        x1: 35,
        x2: 330,
        y1: y(value),
        y2: y(value),
        class: "chart-grid",
      }),
      svgEl(
        "text",
        { x: 29, y: y(value) + 3, "text-anchor": "end" },
        `${value}%`,
      ),
    );
  }
  for (const value of [400, 1000, 1600, 2200, 3000])
    svg.append(
      svgEl(
        "text",
        { x: x(value), y: 164, "text-anchor": "middle" },
        String(value),
      ),
    );
  const path = values
    .map((v, i) => `${i ? "L" : "M"} ${x(v.rating)} ${y(v.value)}`)
    .join(" ");
  svg.append(
    svgEl("path", { d: `${path} L 330 145 L 35 145 Z`, class: "chart-area" }),
    svgEl("path", { d: path, class: "chart-line" }),
  );
  for (const value of values) {
    const dot = svgEl("circle", {
      cx: x(value.rating),
      cy: y(value.value),
      r: 3.3,
      class: "chart-dot",
    });
    dot.append(
      svgEl(
        "title",
        {},
        `${value.rating} vs. ${value.rating}: ${value.value.toFixed(2)}%`,
      ),
    );
    svg.append(dot);
  }
  $("chart").replaceChildren(svg);
}
async function loadRatingComparisonChart(revision) {
  if (preview || !["dual", "stockfish"].includes(state.mode)) return;
  const controller = new AbortController();
  state.chartController = controller;
  $("rating-comparison-chart").replaceChildren(
    node("span", "stockfish-loading", "Calculating move probabilities across ratings…"),
  );
  try {
    const request = $("dual-equal").checked
      ? { ...payload(), ratings: RATINGS }
      : { ...payload(), matchups: RATINGS.map((rating) => ({ player_elo: rating, opponent_elo: Number($("dual-opponent-elo").value) })) };
    const result = await api("analyze", request, controller.signal);
    if (revision !== state.revision || !["dual", "stockfish"].includes(state.mode)) return;
    state.ratingPredictions = result.predictions;
    renderRatingComparisonChart();
  } catch (error) {
    if (error.name === "AbortError" || revision !== state.revision) return;
    $("rating-comparison-chart").replaceChildren(
      node("span", "stockfish-loading", `Rating chart unavailable: ${error.message}`),
    );
  }
}
function renderRatingComparisonChart() {
  const predictions = [...state.ratingPredictions].sort((a, b) => a.player_elo - b.player_elo);
  if (!predictions?.length) return;
  const moves = comparisonMoves();
  if (!moves.length) {
    $("rating-comparison-chart").replaceChildren(node("p", "chart-empty", "No legal moves to compare in this position."));
    return;
  }
  const ns = "http://www.w3.org/2000/svg";
  const make = (tag, attrs = {}, text) => {
    const el = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const container = $("rating-comparison-chart");
  container.replaceChildren();
  const legend = node("div", "rating-chart-legend-controls");
  const svg = make("svg", { viewBox: "0 0 420 308", role: "group", "aria-label": "Maia move probabilities by Lichess blitz rating" });
  svg.append(make("title", {}, "Moves by Rating"), make("desc", {}, "Each curve shows one move’s probability. Focus any point for the exact rating and value. Click legend buttons to hide or show curves."));
  const series = moves.map((move, index) => ({
    move,
    color: MOVE_COLORS[index],
    values: predictions.map((prediction) => ({
      rating: prediction.player_elo,
      probability: prediction.moves.find((candidate) => candidate.uci === move.uci)?.probability || 0,
    })),
  }));
  const visible = series.filter((item) => !state.hiddenChartMoves.has(item.move.uci));
  const maximum = Math.max(0.1, ...visible.flatMap((item) => item.values.map((point) => point.probability)));
  const maxTick = Math.min(1, Math.ceil(maximum / 0.2) * 0.2);
  const x = (rating) => 54 + ((rating - 400) / 2600) * 306;
  const y = (probability) => 258 - probability / maxTick * 226;
  for (let i = 0; i <= 4; i++) {
    const tick = maxTick * i / 4;
    svg.append(make("line", { x1: 54, x2: 360, y1: y(tick), y2: y(tick), class: "rating-chart-grid" }));
    svg.append(make("text", { x: 46, y: y(tick) + 3, "text-anchor": "end", class: "rating-chart-axis" }, `${Math.round(tick * 100)}%`));
  }
  for (const rating of [400, 800, 1200, 1600, 2000, 2400, 3000]) {
    svg.append(make("line", { x1: x(rating), x2: x(rating), y1: 32, y2: 258, class: "rating-chart-grid" }));
    svg.append(make("text", { x: x(rating), y: 277, "text-anchor": "middle", class: "rating-chart-axis" }, String(rating)));
  }
  svg.append(make("text", { x: 207, y: 301, "text-anchor": "middle", class: "rating-chart-axis-title" }, "Lichess blitz rating"));
  svg.append(make("text", { x: 15, y: 145, transform: "rotate(-90 15 145)", "text-anchor": "middle", class: "rating-chart-axis-title human-axis" }, "Maia probability"));
  svg.append(make("line", { x1: x(Number($("elo").value)), x2: x(Number($("elo").value)), y1: 32, y2: 258, class: "rating-selected-rating" }));
  const defs = make("defs");
  svg.append(defs);
  const endpointLabels = visible.map((item) => ({ item, target: y(item.values.at(-1).probability) })).sort((a, b) => a.target - b.target);
  endpointLabels.forEach((label, index) => { label.labelY = Math.max(label.target, index ? endpointLabels[index - 1].labelY + 13 : 34); });
  if (endpointLabels.length) {
    const overflow = Math.max(0, endpointLabels.at(-1).labelY - 258);
    endpointLabels.forEach((label) => { label.labelY -= overflow; });
  }
  const tooltip = node("div", "rating-chart-tooltip");
  tooltip.hidden = true;
  const crosshair = make("line", { x1: 54, x2: 54, y1: 32, y2: 258, class: "rating-chart-crosshair", visibility: "hidden" });
  const showTooltip = (index) => {
    const prediction = predictions[index];
    tooltip.replaceChildren(node("strong", "", `${prediction.player_elo} vs. ${prediction.opponent_elo ?? prediction.player_elo} Elo`));
    for (const item of visible) {
      const row = node("div", "chart-tooltip-row");
      const label = node("span", "", item.move.san);
      label.style.color = item.color;
      row.append(label, node("strong", "", pct(item.values[index].probability)));
      tooltip.append(row);
    }
    crosshair.setAttribute("x1", x(prediction.player_elo));
    crosshair.setAttribute("x2", x(prediction.player_elo));
    crosshair.setAttribute("visibility", "visible");
    tooltip.hidden = false;
    const chartWidth = container.clientWidth;
    const anchor = x(prediction.player_elo) / 420 * chartWidth;
    tooltip.style.left = `${Math.max(3, Math.min(chartWidth - tooltip.offsetWidth - 3, anchor + (anchor > chartWidth / 2 ? -tooltip.offsetWidth - 12 : 12)))}px`;
    tooltip.style.top = `${legend.offsetHeight + 28}px`;
  };
  for (const [seriesIndex, item] of series.entries()) {
    const button = node("button", "chart-legend-button", item.move.san);
    button.type = "button";
    button.style.setProperty("--series-color", item.color);
    button.setAttribute("aria-pressed", String(!state.hiddenChartMoves.has(item.move.uci)));
    button.title = `Show or hide ${item.move.san}`;
    button.addEventListener("click", () => {
      if (state.hiddenChartMoves.has(item.move.uci)) state.hiddenChartMoves.delete(item.move.uci);
      else state.hiddenChartMoves.add(item.move.uci);
      renderRatingComparisonChart();
    });
    legend.append(button);
    if (state.hiddenChartMoves.has(item.move.uci)) continue;
    const gradient = make("linearGradient", { id: `rating-fill-${seriesIndex}`, x1: "0", y1: "0", x2: "0", y2: "1" });
    gradient.append(make("stop", { offset: "0%", "stop-color": item.color, "stop-opacity": ".23" }), make("stop", { offset: "100%", "stop-color": item.color, "stop-opacity": "0" }));
    defs.append(gradient);
    let d = `M ${x(item.values[0].rating)} ${y(item.values[0].probability)}`;
    item.values.slice(1).forEach((point, index) => {
      const previous = item.values[index];
      const middle = (x(previous.rating) + x(point.rating)) / 2;
      d += ` C ${middle} ${y(previous.probability)}, ${middle} ${y(point.probability)}, ${x(point.rating)} ${y(point.probability)}`;
    });
    svg.append(make("path", { d: `${d} L 360 258 L 54 258 Z`, fill: `url(#rating-fill-${seriesIndex})`, class: "rating-chart-area" }));
    svg.append(make("path", { d, class: "rating-chart-line", stroke: item.color, "data-uci": item.move.uci }));
    item.values.forEach((point, index) => {
      const dot = make("circle", { cx: x(point.rating), cy: y(point.probability), r: "3.1", fill: item.color, class: "rating-chart-dot", tabindex: "0", role: "button", "aria-label": `${item.move.san} at ${point.rating} Elo: ${pct(point.probability)}` });
      dot.append(make("title", {}, `${item.move.san} · ${point.rating}: ${pct(point.probability)}`));
      dot.addEventListener("focus", () => showTooltip(index));
      dot.addEventListener("blur", () => { tooltip.hidden = true; crosshair.setAttribute("visibility", "hidden"); });
      svg.append(dot);
    });
    const label = endpointLabels.find((entry) => entry.item === item);
    svg.append(make("line", { x1: 363, y1: label.target, x2: 370, y2: label.labelY, stroke: item.color, "stroke-opacity": ".5" }));
    svg.append(make("text", { x: 374, y: label.labelY + 3, class: "rating-chart-end-label", fill: item.color }, item.move.san));
  }
  svg.append(crosshair);
  if (!visible.length) svg.append(make("text", { x: 207, y: 145, "text-anchor": "middle", class: "rating-chart-axis" }, "Choose a move above to show its curve."));
  svg.addEventListener("pointermove", (event) => {
    const bounds = svg.getBoundingClientRect();
    const rating = 400 + (((event.clientX - bounds.left) / bounds.width * 420 - 54) / 306) * 2600;
    let nearest = 0;
    predictions.forEach((prediction, index) => { if (Math.abs(prediction.player_elo - rating) < Math.abs(predictions[nearest].player_elo - rating)) nearest = index; });
    showTooltip(nearest);
  });
  svg.addEventListener("pointerleave", () => { tooltip.hidden = true; crosshair.setAttribute("visibility", "hidden"); });
  container.append(legend, svg, tooltip);
  const chartSubject = state.stockfish?.lines?.length ? "Top human choices + engine favorite" : "Top human choices";
  $("rating-chart-context").textContent = $("dual-equal").checked
    ? `${chartSubject} · equal-rated opponents`
    : `${chartSubject} · opponent ${$("dual-opponent-elo").value} Elo`;
}
function setMode(mode) {
  state.mode = mode;
  if (!["dual", "stockfish"].includes(mode)) state.maiaMode = mode;
  else state.analysisMode = mode;
  const view = mode === "dual" ? "dual" : mode === "stockfish" ? "stockfish" : "maia";
  document.querySelectorAll(".view-tab").forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = view === "maia" && tab.dataset.mode === mode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $("maia-tabs").hidden = state.workspaceTab !== "explorer" || view !== "maia";
  $("dual-view").hidden = state.workspaceTab !== "analysis" || view === "maia";
  $("maia-view").hidden = state.workspaceTab !== "explorer" || view !== "maia";
  $("dual-results").classList.toggle("pure-stockfish", view === "stockfish");
  $("stockfish-results").classList.toggle("show-variations", $("show-variations").checked || view === "stockfish");
  document.querySelector(".dual-toolbar").classList.remove("pure-stockfish");
  $("rating-control").hidden = mode === "triple" || mode === "compare" || mode === "spectrum";
  $("triple-controls").hidden = mode !== "triple";
  $("compare-controls").hidden = mode !== "compare";
  $("limit-label").hidden = mode === "spectrum";
  $("rating-comparison-chart").closest(".rating-chart-panel").hidden = view === "maia";
  $("analysis-indicator").textContent = view === "stockfish" ? "STOCKFISH" : view === "dual" ? "MAIA + SF" : "MAIA 3";
  $("results-title").textContent = {
    triple: "Top moves by rating",
    explore: "Predicted moves",
    compare: "How choices change",
    spectrum: "The full rating spectrum",
  }[mode];
  $("results-subtitle").textContent = {
    triple: "Move probabilities and arrows · higher Elo draws on top",
    explore: "A window into human choice",
    compare: "Each rating faces an equal-rated opponent",
    spectrum: "14 linked rating groups · Scroll to explore",
  }[mode];
  scheduleAnalysis();
}
function setWorkspaceTab(tab) {
  if (!["analysis", "explorer"].includes(tab)) return;
  state.workspaceTab = tab;
  const workspace = document.querySelector(".workspace");
  workspace.classList.toggle("analysis-layout", tab === "analysis" || tab === "explorer");
  workspace.classList.toggle("explorer-layout", tab === "explorer");
  document.body.classList.add("analysis-theme");
  document.querySelectorAll(".workspace-tab").forEach((button) => {
    const active = button.dataset.workspace === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelector(".analysis-panel .panel-heading h2").textContent =
    tab === "analysis" ? "Analysis" : "Human move explorer";
  placeAnalysisControls();
  hideMoveInspector();
  setMode(tab === "analysis" ? state.analysisMode : state.maiaMode);
}
function placeAnalysisControls() {
  if (state.workspaceTab === "analysis") $("analysis-control-slot").append($("rating-control"));
  else document.querySelector(".analysis-panel").insertBefore($("rating-control"), $("triple-controls"));
  $("analysis-options").hidden = state.workspaceTab !== "analysis";
  $("analysis-collapse").hidden = state.workspaceTab !== "analysis";
}
function setSettingsTab(tab) {
  if (!["engine", "options", "export"].includes(tab)) return;
  for (const name of ["engine", "options", "export"]) {
    const active = name === tab;
    const button = $("settings-tab-" + name);
    const panel = $("settings-panel-" + name);
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    panel.hidden = !active;
  }
}
const DEFAULT_ENGINE_SETTINGS = { multipv: 5, hash: 8, threads: 14, depth: 20, variations: false };
const ENGINE_SETTINGS_KEY = "elovision-engine-settings-v1";
function saveEngineSettings() {
  const settings = {
    multipv: Number($("stockfish-lines-count").value),
    hash: Number($("stockfish-hash").value),
    threads: Number($("stockfish-threads").value),
    depth: Number($("stockfish-depth").value),
    variations: $("show-variations").checked,
  };
  try { localStorage.setItem(ENGINE_SETTINGS_KEY, JSON.stringify(settings)); } catch { /* Optional preference storage. */ }
}
function restoreEngineSettings() {
  try {
    const settings = JSON.parse(localStorage.getItem(ENGINE_SETTINGS_KEY) || "null");
    if (!settings || typeof settings !== "object") return;
    if ([1, 2, 3, 4, 5].includes(settings.multipv)) $("stockfish-lines-count").value = String(settings.multipv);
    if (Number.isInteger(settings.hash) && settings.hash >= 1 && settings.hash <= 64) $("stockfish-hash").value = String(settings.hash);
    if (Number.isInteger(settings.threads) && settings.threads >= 1 && settings.threads <= 256) $("stockfish-threads").value = String(settings.threads);
    if ([10, 15, 20, 25, 30, 35, 40].includes(settings.depth)) $("stockfish-depth").value = String(settings.depth);
    if (typeof settings.variations === "boolean") $("show-variations").checked = settings.variations;
  } catch { /* Ignore stale or unavailable browser preferences. */ }
}
function setView(view) {
  if (state.workspaceTab !== "analysis") return;
  if (view === "dual") setMode("dual");
  else if (view === "stockfish") setMode("stockfish");
}
async function exportResults(format) {
  setExportButtonsDisabled(true);
  try {
    const response = await fetch(localUrl("api/v1/export"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...analysisRequest(),
        format,
        game_id: state.game?.id || null,
        ply: state.game ? state.ply : null,
      }),
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error?.message || "Export failed.");
    }
    const url = URL.createObjectURL(await response.blob());
    const a = node("a");
    a.href = url;
    a.download = `elovision-ply${state.ply}-${state.mode}.${format}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    toast(`${format.toUpperCase()} exported at full precision`);
  } catch (error) {
    alert(error.message);
  } finally {
    setExportButtonsDisabled(!state.predictions.length);
  }
}

for (const id of ["rating-a", "rating-b"]) {
  $(id).replaceChildren(
    ...RATINGS.map((rating) => {
      const option = node("option", "", String(rating));
      option.value = rating;
      return option;
    }),
  );
  $(id).value = id === "rating-a" ? 1000 : 2400;
  $(id).addEventListener("change", () => scheduleAnalysis());
}
$("analysis-rating").replaceChildren(...Array.from({ length: 27 }, (_, index) => {
  const value = 400 + index * 100;
  const option = node("option", "", `Maia ${value}: Human Moves`);
  option.value = value;
  return option;
}));
$("analysis-rating").value = $("elo").value;
$("analysis-rating").addEventListener("change", () => {
  $("elo").value = $("analysis-rating").value;
  $("elo").dispatchEvent(new Event("input"));
});
$("analysis-collapse").addEventListener("click", () => {
  const collapsed = !$("analysis-card").hidden;
  $("analysis-card").hidden = collapsed;
  $("analysis-collapse").textContent = collapsed ? "Show" : "Hide";
  $("analysis-collapse").setAttribute("aria-expanded", String(!collapsed));
});
$("analysis-arrows").addEventListener("change", () => renderMoveArrows());
$("comparison-more").addEventListener("click", () => {
  $("move-limit").value = $("move-limit").value === "all" ? "5" : "all";
  renderPredictions();
  renderMoveArrows();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") { hideMoveInspector(); renderMoveArrows(); }
});
$("elo").addEventListener("input", () => {
  $("elo-value").textContent = $("elo").value;
  if ($("dual-equal").checked) $("dual-opponent-elo").value = $("elo").value;
  $("matchup").textContent = `${$("elo").value} vs. ${$("dual-equal").checked ? $("elo").value : $("dual-opponent-elo").value}`;
  $("human-model-rating").textContent = `Maia ${$("elo").value}: Human Moves`;
  $("analysis-rating").value = $("elo").value;
  scheduleAnalysis(200);
});
$("dual-equal").addEventListener("change", () => {
  const equal = $("dual-equal").checked;
  if (equal) $("dual-opponent-elo").value = $("elo").value;
  $("dual-opponent-elo").disabled = equal;
  $("matchup").textContent = `${$("elo").value} vs. ${equal ? $("elo").value : $("dual-opponent-elo").value}`;
  scheduleAnalysis(100);
});
$("dual-opponent-elo").addEventListener("change", () => {
  const value = Math.max(400, Math.min(3000, Math.round(Number($("dual-opponent-elo").value) / 100) * 100));
  $("dual-opponent-elo").value = value;
  $("matchup").textContent = `${$("elo").value} vs. ${value}`;
  scheduleAnalysis(100);
});
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => setMode(tab.dataset.mode)),
);
document.querySelectorAll(".view-tab").forEach((tab) =>
  tab.addEventListener("click", () => setView(tab.dataset.view)),
);
document.querySelectorAll(".workspace-tab").forEach((tab) =>
  tab.addEventListener("click", () => setWorkspaceTab(tab.dataset.workspace)),
);
$("move-limit").addEventListener("change", () => {
  renderPredictions();
  renderMoveArrows();
});
$("maia-move-limit").addEventListener("change", renderPredictions);
$("show-variations").addEventListener("change", () => {
  $("stockfish-results").classList.toggle("show-variations", $("show-variations").checked || state.mode === "stockfish");
  saveEngineSettings();
});
for (const id of ["stockfish-depth", "stockfish-lines-count", "stockfish-hash", "stockfish-threads"]) {
  $(id).addEventListener("change", () => {
    saveEngineSettings();
    analyzeStockfish(true);
  });
}
function updateWholeGameButton() {
  const button = $("whole-game-analyze");
  if (!button) return;
  const running = Boolean(state.wholeGameController);
  button.disabled = !running && (!state.game || !state.stockfishAvailable);
  button.textContent = running ? "Cancel analysis" : "Analyze Whole Game";
}
function clearStockfishResult() {
  const key = state.position ? stockfishRequestKey() : null;
  const cached = key ? state.stockfishCache.get(key) : null;
  if (cached) {
    state.stockfishCache.delete(key);
    state.stockfishCache.set(key, cached);
    showStockfishResult(cached, key, false, false);
  } else {
    state.stockfish = null;
    state.stockfishPositionKey = null;
    $("stockfish-results").replaceChildren();
  }
  renderGauges();
  renderMoveArrows();
}
function engineMessage(message, className = "") {
  const line = node("div", `stockfish-loading${className ? ` ${className}` : ""}`, message);
  $("stockfish-results").replaceChildren(line);
}
function stockfishError(message = "") {
  const panel = $("stockfish-panel");
  $("stockfish-error").textContent = message;
  $("stockfish-error").hidden = !message;
  if (message) {
    panel.open = true;
    setSettingsTab("engine");
  }
}
function setStockfishChannelLink() {
  const development = $("stockfish-channel").value === "development";
  const link = $("stockfish-download");
  link.href = development ? "https://tests.stockfishchess.org/" : "https://stockfishchess.org/download/";
  link.textContent = development ? "Get development builds ↗" : "Download Stockfish 19 ↗";
}
$("stockfish-channel").addEventListener("change", setStockfishChannelLink);
async function refreshStockfishStatus() {
  try {
    const result = await api("engine/status");
    state.stockfishAvailable = Boolean(result.available);
    $("stockfish-host").textContent = result.host ? `Engine runs on this computer: ${result.host}` : "";
    if (result.available && result.channel) $("stockfish-channel").value = result.channel;
    $("stockfish-status").textContent = result.available
      ? `${result.name} · ready`
      : result.message || "Not installed · choose an engine executable";
    $("sf-engine-title").textContent = result.available
      ? `${result.name}: Engine Moves`
      : "Stockfish 19: Engine Moves";
    $("stockfish-analyze").disabled = !result.available;
    updateWholeGameButton();
    if (result.message) $("stockfish-status").title = result.message;
    stockfishError(result.message || "");
    setStockfishChannelLink();
    if (result.available && state.position && ["dual", "stockfish"].includes(state.mode))
      analyzeStockfish();
  } catch (error) {
    state.stockfishAvailable = false;
    updateWholeGameButton();
    const outdated = error.status === 404;
    $("stockfish-status").textContent = outdated
      ? "Older ELO Vision server detected"
      : "Stockfish is unavailable";
    $("stockfish-status").title = error.message;
    stockfishError(
      outdated
        ? "This browser is connected to an older ELO Vision backend that has no Stockfish status route. Start the updated app again; it will choose a free port and open the correct address."
        : error.message,
    );
  }
}
function renderStockfish(result) {
  const container = $("stockfish-results");
  container.replaceChildren();
  container.classList.toggle("show-variations", $("show-variations").checked || state.mode === "stockfish");
  $("sf-engine-title").textContent = `${result.engine}: Engine Moves`;
  $("sf-engine-title").title = result.engine;
  $("engine-depth").textContent = `d${result.depth}`;
  if (!result.lines.length) {
    container.append(node("div", "stockfish-loading", "This position has no legal moves."));
    return;
  }
  for (const line of result.lines) {
    const row = node("button", `stockfish-line${line.rank === 1 ? " best" : ""}`);
    row.type = "button";
    row.dataset.uci = line.uci;
    row.style.setProperty("--move-color", comparisonColor(line.uci));
    row.append(node("span", "engine-rank", String(line.rank).padStart(2, "0")), node("strong", "", line.san || "—"), node("strong", "", line.score));
    row.append(node("span", "engine-pv", line.pv.join(" ")));
    row.setAttribute("aria-label", `${line.san}, Stockfish evaluation ${line.score} from White’s perspective`);
    bindMoveInspection(row, line.uci);
    container.append(row);
  }
}
function stockfishRequestKey(positionPayload = payload(), settings = null) {
  const selected = settings || {
    depth: $("stockfish-depth").value,
    multipv: $("stockfish-lines-count").value,
    hash: $("stockfish-hash").value,
    threads: $("stockfish-threads").value,
  };
  return `${JSON.stringify(positionPayload)}|${selected.depth}|${selected.multipv}|${selected.hash}|${selected.threads}`;
}
function rememberStockfishResult(key, result) {
  state.stockfishCache.delete(key);
  state.stockfishCache.set(key, result);
  while (state.stockfishCache.size > 4096)
    state.stockfishCache.delete(state.stockfishCache.keys().next().value);
}
function showStockfishResult(result, key, remember = true, refreshHuman = true) {
  state.stockfish = result;
  state.stockfishPositionKey = key;
  if (remember) rememberStockfishResult(key, result);
  stockfishError();
  renderStockfish(result);
  if (refreshHuman && state.mode === "dual") {
    renderPredictions();
    renderRatingComparisonChart();
  }
  renderGauges();
  renderMoveArrows();
  if (["dual", "stockfish"].includes(state.mode) && state.ratingPredictions.length)
    renderRatingComparisonChart();
}
async function analyzeWholeGame() {
  if (state.wholeGameController) {
    state.wholeGameController.abort();
    $("whole-game-status").textContent = "Stopping after the current engine request…";
    return;
  }
  if (!state.game || !state.stockfishAvailable) return;
  const game = state.game;
  const settings = {
    depth: Number($("stockfish-depth").value),
    multipv: Number($("stockfish-lines-count").value),
    hash: Number($("stockfish-hash").value),
    threads: Number($("stockfish-threads").value),
  };
  if (!Number.isInteger(settings.hash) || settings.hash < 1 || settings.hash > 64 ||
      !Number.isInteger(settings.threads) || settings.threads < 1 || settings.threads > 256) {
    $("whole-game-status").textContent = "Check Hash (1–64 GB) and Threads (1–256) settings.";
    return;
  }
  const controller = new AbortController();
  state.wholeGameController = controller;
  updateWholeGameButton();
  const total = game.positions.length;
  let completed = 0;
  try {
    for (let ply = 0; ply < total; ply += 1) {
      if (controller.signal.aborted) break;
      const positionPayload = {
        fen: game.positions[ply].fen,
        initial_fen: game.initial_fen,
        moves: game.moves.slice(0, ply).map((move) => move.uci),
      };
      const key = stockfishRequestKey(positionPayload, settings);
      if (!state.stockfishCache.has(key)) {
        $("whole-game-status").textContent = `Analyzing position ${ply + 1} of ${total} · depth ${settings.depth}, MultiPV ${settings.multipv}`;
        const response = await fetch(localUrl("api/v1/engine/analyze"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...positionPayload,
            depth: settings.depth,
            multipv: settings.multipv,
            hash_mb: settings.hash * 1024,
            threads: settings.threads,
          }),
          signal: controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error?.message || `Engine request failed (${response.status}).`);
        rememberStockfishResult(key, data);
        if (state.game === game && state.position?.fen === positionPayload.fen && key === stockfishRequestKey())
          showStockfishResult(data, key, false);
      }
      completed += 1;
      $("whole-game-status").textContent = `Analyzed ${completed} of ${total} positions`;
    }
    if (controller.signal.aborted) $("whole-game-status").textContent = `Stopped · ${completed} of ${total} positions analyzed`;
    else $("whole-game-status").textContent = `Complete · ${completed} positions analyzed`;
  } catch (error) {
    if (error.name === "AbortError") $("whole-game-status").textContent = `Stopped · ${completed} of ${total} positions analyzed`;
    else $("whole-game-status").textContent = `Stopped at ${completed + 1} of ${total}: ${error.message}`;
  } finally {
    if (state.wholeGameController === controller) state.wholeGameController = null;
    updateWholeGameButton();
  }
}
async function analyzeStockfish(force = false) {
  const hashGb = Number($("stockfish-hash").value);
  const threads = Number($("stockfish-threads").value);
  if (!Number.isInteger(hashGb) || hashGb < 1 || hashGb > 64) {
    engineMessage("Choose a Hash size from 1 to 64 GB.");
    $("stockfish-hash").focus();
    return;
  }
  if (!Number.isInteger(threads) || threads < 1 || threads > 256) {
    engineMessage("Choose between 1 and 256 Stockfish threads.");
    $("stockfish-threads").focus();
    return;
  }
  if (!state.position || !state.stockfishAvailable) {
    if (state.mode === "stockfish") engineMessage("Choose a Stockfish executable in Engine setup to analyze this position.");
    return;
  }
  const key = stockfishRequestKey();
  if (!force && key === state.stockfishPositionKey) return;
  if (!force && state.stockfishCache.has(key)) {
    const cached = state.stockfishCache.get(key);
    state.stockfishCache.delete(key);
    state.stockfishCache.set(key, cached);
    showStockfishResult(cached, key, false, false);
    return;
  }
  const button = $("stockfish-analyze");
  const requestPosition = JSON.stringify(payload());
  const requestDepth = Number($("stockfish-depth").value);
  const requestMultiPv = Number($("stockfish-lines-count").value);
  const requestHashMb = hashGb * 1024;
  const requestThreads = threads;
  const requestPayload = { ...payload(), depth: requestDepth, multipv: requestMultiPv, hash_mb: requestHashMb, threads: requestThreads };
  button.disabled = true;
  engineMessage("Stockfish is searching this position…");
  try {
    const response = await fetch(localUrl("api/v1/engine/analyze"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`${data.error?.code ? `${data.error.code}: ` : ""}${data.error?.message || `Engine request failed (${response.status}).`}`);
    if (JSON.stringify(payload()) !== requestPosition || Number($("stockfish-depth").value) !== requestDepth || Number($("stockfish-lines-count").value) !== requestMultiPv || Number($("stockfish-hash").value) * 1024 !== requestHashMb || Number($("stockfish-threads").value) !== requestThreads) return;
    showStockfishResult(data, key);
  } catch (error) {
    if (JSON.stringify(payload()) === requestPosition) {
      engineMessage(error.message);
      stockfishError(error.message);
    }
  } finally {
    button.disabled = !state.stockfishAvailable;
  }
}
async function installStockfish(file) {
  if (!file) return;
  const engineWasAvailable = state.stockfishAvailable;
  stockfishError();
  if (file.size > MAX_ENGINE_BYTES) {
    const message = "Choose a Stockfish executable no larger than 512 MiB (about 537 MB).";
    engineMessage(message);
    stockfishError(message);
    return;
  }
  const channel = $("stockfish-channel").value;
  $("stockfish-choose").disabled = true;
  $("stockfish-status").textContent = channel === "official19"
    ? "Uploading and checking Stockfish 19…"
    : "Uploading and checking development build…";
  try {
    const response = await fetch(localUrl("api/v1/engine/install"), {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Engine-Filename": encodeURIComponent(file.name), "X-Engine-Channel": channel },
      body: file,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const code = data.error?.code;
      const detail = data.error?.message || `Engine install failed (${response.status}).`;
      const stale = code === "request_too_large" && detail.includes("2.5 MB");
      throw new Error(
        stale
          ? "This browser is connected to an older ELO Vision backend with the 2.5 MB request limit. Start the updated app; it will open on the correct free port."
          : `${code ? `${code}: ` : ""}${detail}`,
      );
    }
    state.stockfishAvailable = true;
    state.stockfish = null;
    state.stockfishPositionKey = null;
    state.stockfishCache.clear();
    $("sf-engine-title").textContent = `${data.name}: Engine Moves`;
    $("stockfish-status").textContent = `${data.name} · ready`;
    $("stockfish-channel").value = data.channel;
    $("stockfish-analyze").disabled = false;
    updateWholeGameButton();
    engineMessage(`${data.name} is ready.`);
    stockfishError();
    setStockfishChannelLink();
    if (["dual", "stockfish"].includes(state.mode)) analyzeStockfish(true);
  } catch (error) {
    // Installation replaces the old binary only after the candidate validates.
    // Keep the existing engine usable when a replacement upload is rejected.
    state.stockfishAvailable = engineWasAvailable;
    $("stockfish-analyze").disabled = !engineWasAvailable;
    updateWholeGameButton();
    const outdated = error.message.includes("older ELO Vision backend");
    $("stockfish-status").textContent = outdated
      ? "Old server still answering on this address"
      : engineWasAvailable
        ? "Current engine remains ready · replacement failed"
        : "Engine setup needs attention";
    engineMessage(error.message);
    stockfishError(error.message);
  } finally {
    $("stockfish-choose").disabled = false;
    $("stockfish-file").value = "";
  }
}
$("stockfish-analyze").addEventListener("click", () => analyzeStockfish(true));
$("whole-game-analyze").addEventListener("click", analyzeWholeGame);
$("engine-reset-defaults").addEventListener("click", () => {
  $("stockfish-lines-count").value = String(DEFAULT_ENGINE_SETTINGS.multipv);
  $("stockfish-hash").value = String(DEFAULT_ENGINE_SETTINGS.hash);
  $("stockfish-threads").value = String(DEFAULT_ENGINE_SETTINGS.threads);
  $("stockfish-depth").value = String(DEFAULT_ENGINE_SETTINGS.depth);
  $("show-variations").checked = DEFAULT_ENGINE_SETTINGS.variations;
  $("stockfish-results").classList.toggle("show-variations", state.mode === "stockfish");
  saveEngineSettings();
  analyzeStockfish(true);
});
document.querySelectorAll(".settings-tab").forEach((tab) =>
  tab.addEventListener("click", () => setSettingsTab(tab.dataset.settingsTab)),
);
$("stockfish-choose").addEventListener("click", () => $("stockfish-file").click());
$("stockfish-file").addEventListener("change", (event) => installStockfish(event.target.files[0]));
function generatedRatings(count, requestedSpacing) {
  if (count === 1) {
    $("spacing-note").textContent = "Single rating centered on 1800; edit it below.";
    return [1800];
  }
  const maximumSpacing = Math.floor(2600 / (count - 1) / 100) * 100;
  const spacing = Math.min(requestedSpacing, maximumSpacing);
  const first = Math.max(400, Math.min(3000 - (count - 1) * spacing, Math.round((1800 - (count - 1) * spacing / 2) / 100) * 100));
  if (spacing !== requestedSpacing) {
    $("spacing-note").textContent = `${requestedSpacing} requested; using ${spacing} Elo to keep all ratings within 400–3000.`;
  } else {
    $("spacing-note").textContent = "Centered on 1800; edit any Elo below.";
  }
  return Array.from({ length: count }, (_, i) => first + i * spacing);
}
function renderRatingInputs() {
  $("triple-ratings").style.setProperty("--rating-count", state.ratingValues.length);
  $("opponent-inputs").style.setProperty("--rating-count", state.opponentValues.length);
  const renderInputs = (container, ratings, className, label) => {
    container.replaceChildren(...ratings.map((rating, index) => {
      const field = node("label", "rating-slot");
      const swatch = node("span", "elo-swatch");
      swatch.style.backgroundColor = eloColor(rating);
      field.append(swatch, document.createTextNode(` ${label} ${index + 1}`));
      const input = node("input", className);
      input.type = "number";
      input.min = "400"; input.max = "3000"; input.step = "100"; input.value = String(rating);
      input.dataset.index = String(index);
      input.setAttribute("aria-label", `${label} ${index + 1} Elo`);
      field.append(input);
      return field;
    }));
  };
  renderInputs($("triple-ratings"), state.ratingValues, "elo-input", "Player");
  renderInputs($("opponent-inputs"), state.opponentValues, "opponent-input", "Opponent");
  $("opponent-inputs").hidden = $("equal-opponents").checked;
}
function regenerateRatings() {
  const count = Number($("rating-count").value);
  const custom = $("rating-spacing").value === "custom";
  const spacing = Number(custom ? $("custom-spacing").value : $("rating-spacing").value);
  state.ratingValues = generatedRatings(count, spacing);
  state.opponentValues = [...state.ratingValues];
  $("rating-count-value").value = String(count);
  $("rating-count-value").textContent = String(count);
  renderRatingInputs();
  if (state.revision) scheduleAnalysis(100);
}
$("rating-count").addEventListener("input", regenerateRatings);
$("rating-spacing").addEventListener("change", () => {
  $("custom-spacing").hidden = $("rating-spacing").value !== "custom";
  regenerateRatings();
});
$("custom-spacing").addEventListener("change", regenerateRatings);
$("triple-ratings").addEventListener("change", (event) => {
  const input = event.target.closest(".elo-input");
  if (!input) return;
  const index = Number(input.dataset.index);
  const value = Math.max(400, Math.min(3000, Math.round(Number(input.value) / 100) * 100));
  state.ratingValues[index] = value;
  input.value = String(value);
  input.closest("label").querySelector(".elo-swatch").style.backgroundColor = eloColor(value);
  if ($("equal-opponents").checked) state.opponentValues[index] = value;
  scheduleAnalysis(100);
});
$("opponent-inputs").addEventListener("change", (event) => {
  const input = event.target.closest(".opponent-input");
  if (!input) return;
  const index = Number(input.dataset.index);
  const value = Math.max(400, Math.min(3000, Math.round(Number(input.value) / 100) * 100));
  state.opponentValues[index] = value;
  input.value = String(value);
  scheduleAnalysis(100);
});
$("equal-opponents").addEventListener("change", () => {
  if ($("equal-opponents").checked) state.opponentValues = [...state.ratingValues];
  renderRatingInputs();
  scheduleAnalysis(100);
});
renderRatingInputs();
$("compare-sort").addEventListener("change", renderPredictions);
$("chart-move").addEventListener("change", () => {
  state.selectedMove = $("chart-move").value;
  renderChart();
});
$("retry").addEventListener("click", () => scheduleAnalysis());
$("flip").addEventListener("click", () => {
  state.flipped = !state.flipped;
  renderBoard();
});
$("first").addEventListener("click", () => navigate(0));
$("prev").addEventListener("click", () => navigate(state.ply - 1));
$("next").addEventListener("click", () => navigate(state.ply + 1));
$("last").addEventListener("click", () => navigate(state.game.moves.length));
document.addEventListener("keydown", (event) => {
  if (
    ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(
      document.activeElement.tagName,
    ) ||
    $("fen-dialog").open
  )
    return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    navigate(state.ply + (event.key === "ArrowRight" ? 1 : -1));
  }
});
$("game-select").addEventListener("change", () => {
  state.game = state.games[Number($("game-select").value)];
  renderGame();
});
$("import").addEventListener("click", () => $("pgn-file").click());
$("pgn-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 2_000_000)
      throw new Error("PGN files must be smaller than 2 MB.");
    const bytes = await file.arrayBuffer();
    let text;
    const bom = new Uint8Array(bytes, 0, Math.min(2, bytes.byteLength));
    if (bom[0] === 255 && bom[1] === 254)
      text = new TextDecoder("utf-16le").decode(bytes);
    else if (bom[0] === 254 && bom[1] === 255)
      text = new TextDecoder("utf-16be").decode(bytes);
    else {
      try {
        text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      } catch {
        text = new TextDecoder("windows-1252").decode(bytes);
      }
    }
    await importPgn(text);
  } catch (error) {
    alert(error.message);
  } finally {
    event.target.value = "";
  }
});
async function loadSamples() {
  const samples = await api("samples");
  const select = $("sample-game-select");
  select.replaceChildren(node("option", "", `Choose a sample game (${samples.length})`));
  for (const sample of samples) {
    const option = node("option", "", `${sample.title} · ${sample.year}`);
    option.value = sample.id;
    option.title = sample.description;
    select.append(option);
  }
  select.addEventListener("change", async () => {
    const sample = samples.find((item) => item.id === select.value);
    if (!sample) return;
    try { await importPgn(sample.pgn); }
    catch (error) { alert(error.message); }
  });
}
$("sample").addEventListener("click", async () => {
  const select = $("sample-game-select");
  const opera = Array.from(select.options).find((option) => option.value === "opera");
  if (opera) select.value = opera.value;
  try {
    const response = await api("samples");
    const game = response.find((item) => item.id === "opera");
    if (game) await importPgn(game.pgn);
  } catch (error) { alert(error.message); }
});
$("copy-fen").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(state.position.fen);
    toast("FEN copied");
  } catch {
    toast("Open Position details to select and copy the FEN.");
  }
});
$("fen-open").addEventListener("click", () => {
  $("fen-input").value = state.position.fen;
  $("fen-error").textContent = "";
  $("fen-dialog").showModal();
});
$("fen-close").addEventListener("click", () => $("fen-dialog").close());
$("fen-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const position = await api("position", {
      fen: $("fen-input").value.trim(),
    });
    state.position = position;
    state.game = null;
    state.ply = 0;
    updateWholeGameButton();
    clearStockfishResult();
    $("game-select").selectedIndex = -1;
    $("notation").replaceChildren(
      node("div", "notation-empty", "Standalone FEN · No game history"),
    );
    $("game-meta").replaceChildren(
      node("h3", "", "Custom position"),
      node("p", "", "Standalone FEN. Import a PGN to supply move history."),
    );
    $("game-result").textContent = "Standalone FEN · Standard chess";
    $("fen-dialog").close();
    renderBoard();
    scheduleAnalysis();
  } catch (error) {
    $("fen-error").textContent = error.message;
  }
});
$("export-json").addEventListener("click", () => exportResults("json"));
$("export-csv").addEventListener("click", () => exportResults("csv"));
$("export-json-tab").addEventListener("click", () => exportResults("json"));
$("export-csv-tab").addEventListener("click", () => exportResults("csv"));
if (preview) {
  $("import").disabled = true;
  $("stockfish-analyze").disabled = true;
  $("stockfish-choose").disabled = true;
  $("stockfish-choose").title = "Engine installation requires the locally running Python app.";
  $("import").title =
    "PGN file imports require the locally running Python app.";
  $("fen-open").disabled = true;
  $("fen-open").title =
    "Custom FEN validation requires the locally running Python app.";
  document.querySelector(".local-badge").textContent = "Standalone preview";
  document.querySelector(".brand").addEventListener("click", (event) => {
    event.preventDefault();
    navigate(0);
  });
}
placeAnalysisControls();
restoreEngineSettings();
refreshStockfishStatus();
loadSamples().catch((error) => {
  $("sample-game-select").replaceChildren(node("option", "", "Sample library unavailable"));
  alert(error.message);
});
try {
  const [health, position] = await Promise.all([
    api("health"),
    api("position", { fen: START_FEN }),
  ]);
  state.position = position;
  $("model-status").textContent = health.loaded
    ? "Ready · CPU · Offline"
    : health.installed
      ? "Installed · Loading on first analysis"
      : "Weights not installed";
  renderBoard();
  scheduleAnalysis();
} catch (error) {
  alert(`Could not reach the local backend. ${error.message}`);
}

const $ = (id) => document.getElementById(id);
const RATINGS = Array.from({ length: 14 }, (_, i) => 400 + i * 200);
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
  mode: "dual",
  maiaMode: "triple",
  ratingPredictions: [],
  stockfishPositionKey: null,
  predictions: [],
  stockfish: null,
  stockfishAvailable: false,
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
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.error?.message || `Request failed (${response.status}).`,
    );
  }
  return response.json();
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
  $("legal-count").textContent = `${pos.legal_count} legal moves`;
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
  clearStockfishResult();
  state.ply = Math.max(0, Math.min(state.game.moves.length, ply));
  state.position = state.game.positions[state.ply];
  renderBoard();
  scheduleAnalysis(100);
}
function renderGame() {
  const game = state.game;
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
  }
  $("dual-human-moves").replaceChildren(node("div", "stockfish-loading", "Waiting for Maia analysis…"));
  $("results").replaceChildren();
  $("actual-card").hidden = true;
  $("dual-actual-card").hidden = true;
  $("spectrum-chart").hidden = true;
  $("export-json").disabled = $("export-csv").disabled = true;
  renderGauges();
  if (state.mode === "stockfish") {
    $("loading").hidden = true;
    $("analysis-indicator").textContent = state.stockfishAvailable ? "STOCKFISH" : "ENGINE NEEDED";
    if (state.stockfishAvailable) state.timer = setTimeout(() => analyzeStockfish(), delay);
    else engineMessage("Choose a Stockfish executable in Engine setup to analyze this position.");
    return;
  }
  $("loading").hidden = state.mode === "dual";
  $("analysis-indicator").textContent = "ANALYZING";
  $("probability-total").textContent = "Full legal policy · No sampling";
  state.timer = setTimeout(() => {
    analyze(revision);
    if (state.mode === "dual" && state.stockfishAvailable && !state.stockfish)
      analyzeStockfish();
  }, delay);
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
    $("export-json").disabled = $("export-csv").disabled = false;
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
    renderExplore($("dual-human-moves"), predictions[0], "move-limit", "dual-actual-card");
    $("human-model-rating").textContent = `${predictions[0].player_elo} Elo`;
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
    for (const move of predictions[0].moves.slice(0, count))
      appendArrow(move.uci, "#ef726b", `Maia ${predictions[0].player_elo}: ${move.san} ${pct(move.probability)}`, "maia-arrowhead", ".12", ".82");
  }
  if (showEngine) {
    const count = Number($("stockfish-lines-count").value);
    const colors = ["#67aaff", "#78b2fa", "#8dbafa", "#a4c6f5", "#bdd3f4", "#d3e0f3", "#adc7e4", "#9ab8dc", "#86a9d4", "#739bc9", "#618dc0", "#527eaf"];
    for (const line of state.stockfish.lines.slice(0, count))
      appendArrow(line.uci, colors[Math.min(line.rank - 1, colors.length - 1)], `Stockfish ${line.rank}: ${line.san} (${line.score} White eval)`, "engine-arrowhead", line.rank === 1 ? ".12" : ".095", line.rank === 1 ? ".95" : ".72");
  }
  const played = state.position?.actual_move;
  if (played) appendArrow(played, "#e9c85e", `Played in game: ${played}`, "played-arrowhead", ".14", ".98", true);
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
  if (preview || state.mode !== "dual") return;
  const controller = new AbortController();
  state.chartController = controller;
  $("rating-comparison-chart").replaceChildren(
    node("span", "stockfish-loading", "Calculating move probabilities across ratings…"),
  );
  try {
    const result = await api("analyze", { ...payload(), ratings: RATINGS }, controller.signal);
    if (revision !== state.revision || state.mode !== "dual") return;
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
  const predictions = state.ratingPredictions;
  if (!predictions?.length) return;
  const currentRating = Number($("elo").value);
  const nearest = [...predictions].sort((a, b) => Math.abs(a.player_elo - currentRating) - Math.abs(b.player_elo - currentRating))[0];
  const moves = nearest.moves.slice(0, 5);
  if (!moves.length) return;
  const ns = "http://www.w3.org/2000/svg";
  const make = (tag, attrs = {}, text) => {
    const el = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const svg = make("svg", { viewBox: "0 0 360 190", role: "img", "aria-label": "Maia human-move probabilities across ratings" });
  const colors = ["#f07870", "#69c978", "#70a9ff", "#efb358", "#b88bf0"];
  const series = moves.map((move, index) => ({
    move,
    color: colors[index],
    values: predictions.map((prediction) => ({
      rating: prediction.player_elo,
      probability: prediction.moves.find((candidate) => candidate.uci === move.uci)?.probability || 0,
    })),
  }));
  const maximum = Math.max(0.1, ...series.flatMap((item) => item.values.map((point) => point.probability)));
  const maxTick = Math.min(1, Math.ceil(maximum * 10) / 10);
  const x = (rating) => 34 + ((rating - 400) / 2600) * 316;
  const y = (probability) => 145 - probability / maxTick * 112;
  for (const tick of [0, maxTick / 2, maxTick]) {
    svg.append(make("line", { x1: 34, x2: 352, y1: y(tick), y2: y(tick), class: "rating-chart-grid" }));
    svg.append(make("text", { x: 29, y: y(tick) + 3, "text-anchor": "end", class: "rating-chart-axis" }, `${Math.round(tick * 100)}%`));
  }
  for (const rating of [400, 1000, 1600, 2200, 3000])
    svg.append(make("text", { x: x(rating), y: 161, "text-anchor": "middle", class: "rating-chart-axis" }, String(rating)));
  series.forEach((item, seriesIndex) => {
    const d = item.values.map((point, index) => `${index ? "L" : "M"} ${x(point.rating)} ${y(point.probability)}`).join(" ");
    svg.append(make("path", { d, class: "rating-chart-line", stroke: item.color }));
    item.values.forEach((point) => svg.append(make("circle", { cx: x(point.rating), cy: y(point.probability), r: "2.2", fill: item.color, class: "rating-chart-dot" })));
    const legendX = 40 + seriesIndex * 63;
    svg.append(make("text", { x: legendX, y: 12, class: "rating-chart-legend", fill: item.color }, item.move.san));
  });
  $("rating-comparison-chart").replaceChildren(svg);
}
function setMode(mode) {
  state.mode = mode;
  if (!["dual", "stockfish"].includes(mode)) state.maiaMode = mode;
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
  $("maia-tabs").hidden = view !== "maia";
  $("dual-view").hidden = view === "maia";
  $("maia-view").hidden = view !== "maia";
  $("dual-results").classList.toggle("pure-stockfish", view === "stockfish");
  document.querySelector(".dual-toolbar").classList.toggle("pure-stockfish", view === "stockfish");
  $("rating-control").hidden = mode === "stockfish" || mode === "triple" || mode === "compare" || mode === "spectrum";
  $("triple-controls").hidden = mode !== "triple";
  $("compare-controls").hidden = mode !== "compare";
  $("limit-label").hidden = mode === "spectrum";
  $("rating-comparison-chart").closest(".rating-chart-panel").hidden = view !== "dual";
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
function setView(view) {
  if (view === "dual") setMode("dual");
  else if (view === "stockfish") setMode("stockfish");
  else setMode(state.maiaMode || "triple");
}
async function exportResults(format) {
  const button = $("export-" + format);
  button.disabled = true;
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
    button.disabled = !state.predictions.length;
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
$("elo").addEventListener("input", () => {
  $("elo-value").textContent = $("elo").value;
  if ($("dual-equal").checked) $("dual-opponent-elo").value = $("elo").value;
  $("matchup").textContent = `${$("elo").value} vs. ${$("dual-equal").checked ? $("elo").value : $("dual-opponent-elo").value}`;
  $("human-model-rating").textContent = `${$("elo").value} Elo`;
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
$("move-limit").addEventListener("change", () => {
  renderPredictions();
  renderMoveArrows();
});
$("maia-move-limit").addEventListener("change", renderPredictions);
$("show-variations").addEventListener("change", () => {
  $("stockfish-results").classList.toggle("show-variations", $("show-variations").checked);
});
$("stockfish-depth").addEventListener("change", () => analyzeStockfish(true));
$("stockfish-lines-count").addEventListener("change", () => analyzeStockfish(true));
function clearStockfishResult() {
  state.stockfish = null;
  state.stockfishPositionKey = null;
  $("stockfish-results").replaceChildren();
  renderGauges();
  renderMoveArrows();
}
function engineMessage(message, className = "") {
  const line = node("div", `stockfish-loading${className ? ` ${className}` : ""}`, message);
  $("stockfish-results").replaceChildren(line);
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
    if (result.available && result.channel) $("stockfish-channel").value = result.channel;
    $("stockfish-status").textContent = result.available
      ? `${result.name} · ready`
      : result.message || "Not installed · choose an engine executable";
    $("sf-engine-title").textContent = result.available
      ? `${result.name} · Engine moves`
      : "Stockfish · Engine moves";
    $("stockfish-analyze").disabled = !result.available;
    if (result.message) $("stockfish-status").title = result.message;
    setStockfishChannelLink();
    if (result.available && state.position && ["dual", "stockfish"].includes(state.mode))
      analyzeStockfish();
  } catch (error) {
    state.stockfishAvailable = false;
    $("stockfish-status").textContent = "Stockfish is unavailable";
    $("stockfish-status").title = error.message;
  }
}
function renderStockfish(result) {
  const container = $("stockfish-results");
  container.replaceChildren();
  container.classList.toggle("show-variations", $("show-variations").checked);
  $("sf-engine-title").textContent = `${result.engine} · Engine moves`;
  if (!result.lines.length) {
    container.append(node("div", "stockfish-loading", "This position has no legal moves."));
    return;
  }
  const summary = node("div", "stockfish-result-summary");
  summary.append(node("span", "", `${result.engine} · depth ${result.depth}`), node("span", "", "Eval from White’s perspective"));
  container.append(summary);
  for (const line of result.lines) {
    const row = node("div", `stockfish-line${line.rank === 1 ? " best" : ""}`);
    row.append(node("span", "engine-rank", String(line.rank).padStart(2, "0")), node("strong", "", line.san || "—"), node("strong", "", line.score));
    row.append(node("span", "engine-pv", line.pv.join(" ")));
    row.title = `${line.score} · ${line.pv.join(" ")}`;
    container.append(row);
  }
}
function stockfishRequestKey() {
  return `${JSON.stringify(payload())}|${$("stockfish-depth").value}|${$("stockfish-lines-count").value}`;
}
async function analyzeStockfish(force = false) {
  if (!state.position || !state.stockfishAvailable) {
    if (state.mode === "stockfish") engineMessage("Choose a Stockfish executable in Engine setup to analyze this position.");
    return;
  }
  const key = stockfishRequestKey();
  if (!force && key === state.stockfishPositionKey) return;
  const button = $("stockfish-analyze");
  const requestPosition = JSON.stringify(payload());
  const requestDepth = Number($("stockfish-depth").value);
  const requestMultiPv = Number($("stockfish-lines-count").value);
  const requestPayload = { ...payload(), depth: requestDepth, multipv: requestMultiPv };
  button.disabled = true;
  engineMessage("Stockfish is searching this position…");
  try {
    const response = await fetch(localUrl("api/v1/engine/analyze"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error?.message || `Engine request failed (${response.status}).`);
    if (JSON.stringify(payload()) !== requestPosition || Number($("stockfish-depth").value) !== requestDepth || Number($("stockfish-lines-count").value) !== requestMultiPv) return;
    state.stockfish = data;
    state.stockfishPositionKey = key;
    renderStockfish(data);
    renderGauges();
    renderMoveArrows();
  } catch (error) {
    if (JSON.stringify(payload()) === requestPosition) engineMessage(error.message);
  } finally {
    button.disabled = !state.stockfishAvailable;
  }
}
async function installStockfish(file) {
  if (!file) return;
  if (file.size > 100 * 1024 * 1024) {
    engineMessage("Choose a Stockfish executable no larger than 100 MB.");
    return;
  }
  const channel = $("stockfish-channel").value;
  $("stockfish-choose").disabled = true;
  $("stockfish-status").textContent = channel === "official19" ? "Checking Stockfish 19…" : "Checking development build…";
  try {
    const response = await fetch(localUrl("api/v1/engine/install"), {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Engine-Filename": encodeURIComponent(file.name), "X-Engine-Channel": channel },
      body: file,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error?.message || `Engine install failed (${response.status}).`);
    state.stockfishAvailable = true;
    state.stockfish = null;
    state.stockfishPositionKey = null;
    $("sf-engine-title").textContent = `${data.name} · Engine moves`;
    $("stockfish-status").textContent = `${data.name} · ready`;
    $("stockfish-channel").value = data.channel;
    $("stockfish-analyze").disabled = false;
    engineMessage(`${data.name} is ready.`);
    setStockfishChannelLink();
    if (["dual", "stockfish"].includes(state.mode)) analyzeStockfish(true);
  } catch (error) {
    state.stockfishAvailable = false;
    $("stockfish-status").textContent = "Engine setup needs attention";
    engineMessage(error.message);
  } finally {
    $("stockfish-choose").disabled = false;
    $("stockfish-file").value = "";
  }
}
$("stockfish-analyze").addEventListener("click", () => analyzeStockfish(true));
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
    clearStockfishResult();
    state.position = position;
    state.game = null;
    state.ply = 0;
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

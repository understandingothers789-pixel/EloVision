const $ = (id) => document.getElementById(id);
const RATINGS = Array.from({ length: 14 }, (_, i) => 400 + i * 200);
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
// Set only by the standalone preview builder; contains real board states, never policy data.
const preview = globalThis.ELOVISION_PREVIEW || null;
const localUrl = (path) => new URL(path, document.baseURI).href;
const state = {
  games: [],
  game: null,
  ply: 0,
  position: null,
  flipped: false,
  mode: "explore",
  predictions: [],
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
    if (path === "position") {
      const position = preview.sample.games[0].positions.find(
        (p) => p.fen === data.fen,
      );
      if (position) return structuredClone(position);
    }
    if (path === "pgn" && data.pgn === preview.pgn)
      return structuredClone(preview.sample);
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
  return [Number($("elo").value)];
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
}
function capitalize(value) {
  return value[0].toUpperCase() + value.slice(1);
}
function navigate(ply) {
  if (!state.game) return;
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
  state.predictions = [];
  $("results").replaceChildren();
  $("actual-card").hidden = true;
  $("spectrum-chart").hidden = true;
  $("export-json").disabled = $("export-csv").disabled = true;
  $("loading").hidden = false;
  $("analysis-indicator").textContent = "ANALYZING";
  $("probability-total").textContent = "Full legal policy · No sampling";
  state.timer = setTimeout(() => analyze(revision), delay);
}
async function analyze(revision) {
  const controller = new AbortController();
  state.controller = controller;
  try {
    const data = await api(
      "analyze",
      { ...payload(), ratings: selectedRatings() },
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
    $("results").replaceChildren(empty);
    $("analysis-indicator").textContent = preview ? "PREVIEW" : "UNAVAILABLE";
    $("model-status").textContent = preview
      ? "Interface preview · No backend"
      : "Model needs attention";
  } finally {
    if (revision === state.revision) $("loading").hidden = true;
  }
}
const pct = (p) => `${(p * 100).toFixed(2)}%`;
function limitRows(rows) {
  return $("move-limit").value === "all"
    ? rows
    : rows.slice(0, Number($("move-limit").value));
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
    container.append(empty);
    $("probability-total").textContent = "No legal moves";
    return;
  }
  if (state.mode === "explore") renderExplore(container, predictions[0]);
  else if (state.mode === "compare") renderCompare(container, predictions);
  else renderSpectrum(container, predictions);
  $("probability-total").textContent =
    `Full policy: ${(predictions[0].probability_sum * 100).toFixed(2)}% · ${predictions[0].moves.length} moves`;
  $("history-note").textContent = state.game
    ? "Using the PGN mainline, including up to seven previous positions. Short history is padded exactly as in the official Maia pipeline."
    : "No PGN history supplied. The current position is repeated to fill the eight-position model input.";
}
function renderExplore(container, prediction) {
  const actual = prediction.moves.find(
    (m) => m.uci === state.position.actual_move,
  );
  if (actual) {
    const card = $("actual-card");
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
  for (const move of limitRows(prediction.moves)) {
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
function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.mode === mode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelector(".rating-control").hidden = mode !== "explore";
  $("compare-controls").hidden = mode !== "compare";
  $("limit-label").hidden = mode === "spectrum";
  $("results-title").textContent = {
    explore: "Predicted moves",
    compare: "How choices change",
    spectrum: "The full rating spectrum",
  }[mode];
  $("results-subtitle").textContent = {
    explore: "A window into human choice",
    compare: "Each rating faces an equal-rated opponent",
    spectrum: "14 linked rating groups · Scroll to explore",
  }[mode];
  if (mode === "compare") $("move-limit").value = "all";
  scheduleAnalysis();
}
async function exportResults(format) {
  const button = $("export-" + format);
  button.disabled = true;
  try {
    const response = await fetch(localUrl("api/v1/export"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...payload(),
        ratings: selectedRatings(),
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
  $("matchup").textContent = `${$("elo").value} vs. ${$("elo").value}`;
  scheduleAnalysis(200);
});
document
  .querySelectorAll(".tab")
  .forEach((tab) =>
    tab.addEventListener("click", () => setMode(tab.dataset.mode)),
  );
$("move-limit").addEventListener("change", renderPredictions);
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
$("sample").addEventListener("click", async () => {
  try {
    await importPgn(
      preview
        ? preview.pgn
        : await (await fetch(localUrl("example.pgn"))).text(),
    );
  } catch (error) {
    alert(error.message);
  }
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

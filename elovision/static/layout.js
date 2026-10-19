/* Local, dependency-free panel arrangement. Move the live DOM, never clone it. */
const workspace = document.querySelector(".workspace");
const layoutKey = "elovision-workspace-layout-v1";
const columns = 24;
const row = 16;
const gap = 12;
const desktop = matchMedia("(min-width: 1100px)");
const panelDefinitions = {
  game: { selector: ".game-panel", title: "Game notebook", minWidth: 230, minHeight: 300 },
  board: { selector: ".board-panel", title: "Chessboard", minWidth: 300, minHeight: 340 },
  analysis: { selector: ".analysis-panel", title: "Analysis", minWidth: 320, minHeight: 240 },
  chart: { selector: ".rating-chart-panel", title: "Moves by Rating", minWidth: 300, minHeight: 210 },
  settings: { selector: "#analysis-options", title: "Engine / Maia Options / Export", minWidth: 280, minHeight: 180 },
};
const pagePanels = { analysis: ["game", "board", "analysis", "chart", "settings"], explorer: ["game", "board", "analysis"] };
const panels = {};
let page = "analysis";
let editing = false;
let attached = false;
let gesture = null;
let renderFrame = 0;
let gestureFrame = 0;
let layouts = readLayouts();
let focusedBoard = false;

function copy(value) { return JSON.parse(JSON.stringify(value)); }
function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
function announce(message) { document.getElementById("layout-status").textContent = message; }

function readLayouts() {
  const result = {};
  try {
    const stored = JSON.parse(localStorage.getItem(layoutKey));
    if (stored?.version !== 1) return result;
    for (const [name, ids] of Object.entries(pagePanels)) {
      const candidate = stored.pages?.[name];
      if (!candidate || !ids.every((id) => {
        const rect = candidate.panels?.[id];
        return rect && ["x", "y", "w", "h"].every((key) => Number.isInteger(rect[key]))
          && rect.x >= 0 && rect.y >= 0 && rect.y <= 2000 && rect.w >= 1
          && rect.x + rect.w <= columns && rect.h >= 1 && rect.h <= 160;
      })) continue;
      result[name] = {
        preset: ["focus", "notebook", "custom"].includes(candidate.preset) ? candidate.preset : "custom",
        boardFocus: candidate.boardFocus === true || candidate.preset === "focus",
        panels: Object.fromEntries(ids.map((id) => [id, { ...candidate.panels[id] }])),
      };
    }
  } catch { /* Layout storage is optional, including opaque-origin previews. */ }
  return result;
}

function saveLayout(message = "Layout saved for this browser.") {
  try {
    localStorage.setItem(layoutKey, JSON.stringify({ version: 1, pages: layouts }));
    announce(message);
  } catch { announce("Layout changed for this session. Browser storage is unavailable."); }
}

function minimum(id) {
  const definition = panelDefinitions[id];
  const unit = workspace.clientWidth / columns;
  return {
    w: Math.min(columns, Math.ceil((definition.minWidth + gap) / unit)),
    h: Math.ceil((definition.minHeight + gap) / row),
  };
}

function bounded(id, rect) {
  const min = minimum(id);
  const w = clamp(rect.w, min.w, columns);
  return {
    x: clamp(rect.x, 0, columns - w), y: clamp(rect.y, 0, 1000),
    w, h: clamp(rect.h, min.h, 160),
  };
}

function intersects(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

function makeRoom(rects, priority = null) {
  const ids = pagePanels[page];
  const order = ids.filter((id) => id !== priority).sort((a, b) => rects[a].y - rects[b].y || rects[a].x - rects[b].x);
  if (priority) order.unshift(priority);
  const occupied = [];
  for (const id of order) {
    const rect = bounded(id, rects[id]);
    let collision;
    while ((collision = occupied.find((other) => intersects(rect, other)))) {
      rect.y = collision.y + collision.h;
    }
    rects[id] = rect;
    occupied.push(rect);
  }
}

function seedLayout() {
  const origin = workspace.getBoundingClientRect();
  const unit = workspace.clientWidth / columns;
  const rects = {};
  for (const id of pagePanels[page]) {
    const bounds = panels[id].content.getBoundingClientRect();
    let height = bounds.height;
    if (id === "analysis" && page === "analysis") {
      height = panels.chart.content.getBoundingClientRect().top - bounds.top - 12;
    }
    rects[id] = bounded(id, {
      x: Math.round((bounds.left - origin.left) / unit),
      y: Math.max(0, Math.round((bounds.top - origin.top) / row)),
      w: Math.round((bounds.width + gap) / unit),
      h: Math.ceil((height + gap + 24) / row),
    });
  }
  makeRoom(rects);
  return { preset: "custom", panels: rects };
}

function presetLayout(preset) {
  const rect = (x, y, w, h) => ({ x, y, w, h });
  const result = preset === "notebook" ? {
    board: rect(0, 0, 14, 45), analysis: rect(14, 0, 10, page === "analysis" ? 23 : 65),
    chart: rect(14, 23, 10, 22), game: rect(0, 45, 14, 24), settings: rect(14, 45, 10, 24),
  } : {
    game: rect(0, 0, 5, 30), board: rect(5, 0, 13, 55),
    analysis: rect(18, 0, 6, page === "analysis" ? 24 : 55),
    chart: rect(18, 24, 6, 23), settings: rect(0, 30, 5, 24),
  };
  const rects = Object.fromEntries(pagePanels[page].map((id) => [id, result[id]]));
  makeRoom(rects);
  return { preset, boardFocus: preset === "focus", panels: rects };
}

function attachPanels() {
  if (attached) return;
  for (const { content, frame } of Object.values(panels)) {
    frame.append(content);
    content.classList.add("dock-content");
    workspace.append(frame);
  }
  attached = true;
}

function detachPanels() {
  if (!attached) return;
  for (const { content, frame, anchor } of Object.values(panels)) {
    anchor.after(content);
    content.classList.remove("dock-content");
    frame.remove();
  }
  attached = false;
}

function sizeBoard() {
  if (!attached) return;
  const board = panels.board.content;
  const stage = board.querySelector(".board-analysis-stage");
  let overhead = 0;
  for (const child of board.children) {
    if (child === stage) continue;
    const style = getComputedStyle(child);
    if (style.display !== "none") overhead += child.getBoundingClientRect().height
      + parseFloat(style.marginTop || 0) + parseFloat(style.marginBottom || 0);
  }
  const style = getComputedStyle(board);
  const available = board.clientHeight - overhead - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
  const viewportSpace = focusedBoard && layouts[page].panels.board.y === 0
    ? innerHeight - stage.getBoundingClientRect().top - window.scrollY - 12
    : Infinity;
  const size = Math.max(120, Math.min(board.clientWidth - 76, available - 2, viewportSpace));
  board.style.setProperty("--dock-board-size", `${size}px`);
}

function renderLayout() {
  const active = desktop.matches && Boolean(layouts[page]);
  const focus = active && Boolean(layouts[page].boardFocus);
  document.body.classList.toggle("board-focus-layout", focus);
  if (focus !== focusedBoard) {
    document.getElementById("board-extras").open = !focus;
    focusedBoard = focus;
  }
  if (active) attachPanels();
  else detachPanels();
  workspace.classList.toggle("custom-layout", active);
  workspace.classList.toggle("layout-editing", active && editing);
  document.getElementById("layout-help").hidden = !editing || !desktop.matches;
  const edit = document.getElementById("layout-edit");
  edit.disabled = !desktop.matches;
  edit.title = desktop.matches ? "Arrange panels on this page" : "Widen the window to arrange panels; your saved layout will return.";
  edit.textContent = editing && desktop.matches ? "Done arranging" : "Arrange layout";
  edit.setAttribute("aria-pressed", String(editing && desktop.matches));
  document.getElementById("layout-preset").disabled = !desktop.matches;
  document.getElementById("layout-preset").value = layouts[page]?.preset || "classic";
  if (!active) {
    workspace.style.removeProperty("height");
    return;
  }
  const rects = copy(layouts[page].panels);
  if (!gesture) makeRoom(rects);
  const unit = workspace.clientWidth / columns;
  let bottom = 0;
  for (const [id, { frame, handle }] of Object.entries(panels)) {
    const rect = rects[id];
    frame.hidden = !pagePanels[page].includes(id);
    if (frame.hidden) continue;
    Object.assign(frame.style, {
      left: `${rect.x * unit}px`, top: `${rect.y * row}px`,
      width: `${rect.w * unit - gap}px`, height: `${rect.h * row - gap}px`,
    });
    handle.textContent = `⠿  ${id === "analysis" && page === "explorer" ? "Maia Explorer" : panelDefinitions[id].title}`;
    bottom = Math.max(bottom, (rect.y + rect.h) * row);
  }
  workspace.style.height = `${bottom + (editing ? 120 : 0)}px`;
  sizeBoard();
}

function queueRender() {
  if (renderFrame) return;
  renderFrame = requestAnimationFrame(() => { renderFrame = 0; renderLayout(); });
}

function finishGesture(cancel = false) {
  if (!gesture) return;
  const current = gesture;
  gesture = null;
  cancelAnimationFrame(gestureFrame);
  panels[current.id].frame.classList.remove("layout-moving");
  document.body.classList.remove("layout-dragging");
  if (cancel) layouts[page].panels = current.snapshot;
  else {
    makeRoom(layouts[page].panels, current.id);
    layouts[page].preset = "custom";
    saveLayout(`${panelDefinitions[current.id].title} ${current.edge ? "resized" : "moved"}. Layout saved.`);
  }
  renderLayout();
  if (current.target.hasPointerCapture(current.pointer)) current.target.releasePointerCapture(current.pointer);
}

function updateGesture() {
  if (!gesture) return;
  const { id, edge, original, clientX, clientY, startX, startY, scrollY } = gesture;
  const dx = Math.round((clientX - startX) / (workspace.clientWidth / columns));
  const dy = Math.round((clientY - startY + window.scrollY - scrollY) / row);
  const min = minimum(id);
  const next = { ...original };
  if (!edge) {
    next.x += dx;
    next.y += dy;
  } else {
    if (edge.includes("e")) next.w = clamp(original.w + dx, min.w, columns - original.x);
    if (edge.includes("s")) next.h = clamp(original.h + dy, min.h, 160);
    if (edge.includes("w")) {
      next.x = clamp(original.x + dx, 0, original.x + original.w - min.w);
      next.w = original.x + original.w - next.x;
    }
    if (edge.includes("n")) {
      next.y = clamp(original.y + dy, Math.max(0, original.y + original.h - 160), original.y + original.h - min.h);
      next.h = original.y + original.h - next.y;
    }
  }
  const candidate = bounded(id, next);
  const current = layouts[page].panels[id];
  if (["x", "y", "w", "h"].some((key) => candidate[key] !== current[key])) {
    layouts[page].panels[id] = candidate;
    renderLayout();
  }
  const scroll = clientY > innerHeight - 50 ? 14 : clientY < 70 ? -14 : 0;
  if (scroll) window.scrollBy(0, scroll);
  gestureFrame = requestAnimationFrame(updateGesture);
}

function beginGesture(event, id, edge = "") {
  if (!editing || !desktop.matches || gesture || event.button !== 0) return;
  event.preventDefault();
  event.currentTarget.focus({ preventScroll: true });
  makeRoom(layouts[page].panels);
  gesture = {
    id, edge, original: { ...layouts[page].panels[id] }, snapshot: copy(layouts[page].panels),
    startX: event.clientX, startY: event.clientY, clientX: event.clientX, clientY: event.clientY,
    scrollY: window.scrollY, pointer: event.pointerId, target: event.currentTarget,
  };
  gesture.target.setPointerCapture(event.pointerId);
  panels[id].frame.classList.add("layout-moving");
  document.body.classList.add("layout-dragging");
  gestureFrame = requestAnimationFrame(updateGesture);
}

function moveWithKeyboard(event, id) {
  if (!editing || !desktop.matches || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
  event.preventDefault();
  event.stopPropagation();
  makeRoom(layouts[page].panels);
  const rect = { ...layouts[page].panels[id] };
  const direction = ["ArrowLeft", "ArrowUp"].includes(event.key) ? -1 : 1;
  const horizontal = ["ArrowLeft", "ArrowRight"].includes(event.key);
  const field = event.shiftKey ? (horizontal ? "w" : "h") : (horizontal ? "x" : "y");
  rect[field] += direction;
  layouts[page].panels[id] = bounded(id, rect);
  makeRoom(layouts[page].panels, id);
  layouts[page].preset = "custom";
  renderLayout();
  saveLayout(`${panelDefinitions[id].title} ${event.shiftKey ? "resized" : "moved"}. Layout saved.`);
}

for (const [id, definition] of Object.entries(panelDefinitions)) {
  const content = document.querySelector(definition.selector);
  const anchor = document.createComment(`layout home: ${id}`);
  content.before(anchor);
  const frame = document.createElement("section");
  frame.className = "dock-frame";
  frame.dataset.layoutPanel = id;
  frame.setAttribute("aria-label", `${definition.title} panel`);
  const handle = document.createElement("button");
  handle.type = "button";
  handle.className = "layout-panel-handle";
  handle.setAttribute("aria-label", `Move ${definition.title}`);
  handle.title = "Drag to move. Arrow keys move; Shift + arrows resize.";
  handle.setAttribute("aria-describedby", "layout-help");
  handle.addEventListener("pointerdown", (event) => beginGesture(event, id));
  handle.addEventListener("keydown", (event) => moveWithKeyboard(event, id));
  frame.append(handle);
  for (const edge of ["n", "e", "s", "w", "ne", "se", "sw", "nw"]) {
    const resize = document.createElement("button");
    resize.type = "button";
    resize.className = `layout-resize layout-resize-${edge}`;
    resize.setAttribute("aria-label", `Resize ${definition.title} ${edge}`);
    resize.title = "Drag to resize. Shift + arrow keys resize from the panel header.";
    resize.tabIndex = -1;
    resize.addEventListener("pointerdown", (event) => beginGesture(event, id, edge));
    frame.append(resize);
  }
  panels[id] = { content, anchor, frame, handle };
}

function refreshFocusPresets() {
  if (!desktop.matches) return;
  // Pure presets follow updated definitions; hand-arranged layouts keep their geometry.
  const current = page;
  for (const name of Object.keys(layouts)) {
    if (layouts[name].preset !== "focus") continue;
    page = name;
    layouts[name] = presetLayout("focus");
  }
  page = current;
}
refreshFocusPresets();

document.getElementById("layout-edit").addEventListener("click", () => {
  if (!desktop.matches) return;
  finishGesture(true);
  if (!layouts[page]) layouts[page] = seedLayout();
  editing = !editing;
  renderLayout();
  if (!editing) saveLayout();
});
document.getElementById("layout-preset").addEventListener("change", (event) => {
  finishGesture(true);
  const preset = event.target.value;
  if (preset === "classic") {
    delete layouts[page];
    editing = false;
  } else layouts[page] = presetLayout(preset);
  renderLayout();
  saveLayout();
});
document.getElementById("layout-reset").addEventListener("click", () => {
  finishGesture(true);
  delete layouts[page];
  editing = false;
  renderLayout();
  saveLayout("Default layout restored for this page.");
});
document.addEventListener("elovision:workspace-changed", (event) => {
  finishGesture(true);
  page = event.detail;
  editing = false;
  renderLayout();
});
window.addEventListener("pointermove", (event) => {
  if (gesture && gesture.pointer === event.pointerId) {
    gesture.clientX = event.clientX;
    gesture.clientY = event.clientY;
  }
});
window.addEventListener("pointerup", (event) => {
  if (gesture?.pointer === event.pointerId) {
    gesture.clientX = event.clientX;
    gesture.clientY = event.clientY;
    cancelAnimationFrame(gestureFrame);
    updateGesture();
    finishGesture();
  }
});
window.addEventListener("pointercancel", () => finishGesture(true));
window.addEventListener("blur", () => finishGesture(true));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && gesture) {
    event.preventDefault();
    event.stopImmediatePropagation();
    finishGesture(true);
  }
}, true);
desktop.addEventListener("change", () => {
  finishGesture(true);
  refreshFocusPresets();
  queueRender();
});
new ResizeObserver(() => {
  if (attached && desktop.matches && !gesture) {
    queueRender();
  }
}).observe(workspace);
window.addEventListener("resize", queueRender);
panels.board.content.querySelector(".position-details").addEventListener("toggle", queueRender);
document.getElementById("board-extras").addEventListener("toggle", queueRender);
renderLayout();

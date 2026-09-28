/**
 * ui.js
 * =====
 *
 * The small pieces every screen builds itself out of.
 *
 * Nothing here builds HTML out of strings. Not only for safety, though that
 * matters: a profile named with a < in it should show a < rather than eating
 * the rest of the page.
 *
 * The icons are inline SVG, drawn from a handful of path strings. A font or a
 * sprite sheet would be another file to fetch and another thing to go missing,
 * and there are eleven of them.
 */
import * as T from "./theme.js";

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function put(parent, ...children) {
  for (const child of children) if (child) parent.append(child);
  return parent;
}

export function clear(node) {
  while (node.firstChild) node.firstChild.remove();
  return node;
}

export function button(label, className, onClick, tooltip = "") {
  const node = el("button", className, label);
  if (tooltip) node.title = tooltip;
  node.addEventListener("click", onClick);
  return node;
}

export function swatch(color) {
  const dot = el("span", "swatch");
  dot.style.background = color;
  return dot;
}

export function notice(text, bad = false) {
  return el("p", bad ? "notice bad" : "notice", text);
}

/** A text box that reports its value when you leave it or press Enter. */
export function field(value, onDone, { type = "text", placeholder = "" } = {}) {
  const node = el("input");
  node.type = type;
  node.value = value ?? "";
  node.placeholder = placeholder;
  node.addEventListener("change", () => onDone(node.value));
  node.addEventListener("keydown", event => {
    if (event.key === "Enter") node.blur();
  });
  return node;
}

/** A labelled number box. */
export function numberField(label, value, onDone, { step = 1, min = null } = {}) {
  const box = el("input");
  box.type = "number";
  box.value = value;
  box.step = step;
  if (min !== null) box.min = min;
  box.addEventListener("change", () => {
    const asked = Number(box.value);
    if (Number.isFinite(asked)) onDone(asked);
  });
  return put(el("label", "field"), el("span", "small faint", label), box);
}

/** A labelled dropdown. `choices` is [value, label] pairs. */
export function choose(label, choices, current, onPick) {
  const picker = el("select");
  for (const [value, text] of choices) {
    const option = el("option", null, text);
    option.value = String(value);
    option.selected = String(value) === String(current);
    put(picker, option);
  }
  picker.addEventListener("change", () => onPick(picker.value));
  return label
    ? put(el("label", "field"), el("span", "small faint", label), picker)
    : picker;
}

/** A row of color dots, one of them ringed. */
export function colors(current, onPick) {
  const dots = el("div", "dots");
  for (const color of T.SWATCHES) {
    const dot = button("", color === current ? "on" : "", () => onPick(color), color);
    dot.style.background = color;
    put(dots, dot);
  }
  return dots;
}

// ---------------------------------------------------------------------------
// ICONS
// ---------------------------------------------------------------------------
// Drawn on a 24 by 24 grid, stroked rather than filled so one shape works on
// any background and at any size. A button with a picture AND a word on it is
// understood faster than either alone, which is the whole reason these exist:
// "Draw room" is not obvious until you have used it once, and a pencil over a
// polygon is obvious immediately.

const PATHS = {
  select: "M5 3l14 8-6 1.5L10 19z",
  draw: "M4 20V7l7-3 9 4v12H4z M4 7l7 3 9-4 M11 10v10",
  rectangle: "M4 6h16v12H4z",
  square: "M6 6h12v12H6z",
  circle: "M12 5a7 7 0 100 14 7 7 0 100-14z",
  triangle: "M12 5l8 14H4z",
  lshape: "M4 4h8v8h8v8H4z",
  box: "M4 8h16v11H4z M4 8l3-4h10l3 4 M12 4v4",
  fit: "M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5",
  undo: "M9 14L4 9l5-5 M4 9h10a6 6 0 010 12H8",
  redo: "M15 14l5-5-5-5 M20 9H10a6 6 0 100 12h6",
  cancel: "M6 6l12 12 M18 6L6 18",
  back: "M15 5l-7 7 7 7",
  plan: "M4 4h16v16H4z M4 11h9 M13 4v16",
  items: "M4 6h16 M4 12h16 M4 18h16",
  three: "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5",
  search: "M11 5a6 6 0 100 12 6 6 0 100-12z M20 20l-4.5-4.5",
  trash: "M5 7h14 M9 7V5h6v2 M7 7l1 13h8l1-13",
  copy: "M9 9h11v11H9z M5 15V4h11",
  lock: "M6 11h12v9H6z M9 11V8a3 3 0 016 0v3",
  step: "M4 19h16 M8 19V9l8-5v15",
};

/** One icon, as an inline SVG element. */
export function icon(name, size = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", PATHS[name] ?? PATHS.select);
  put(svg, path);
  return svg;
}

/** A button with a picture and a word on it.
 *
 *  Both, not one. A picture alone needs learning and a word alone is a wall
 *  of text on a toolbar; together the picture is what you find it by after
 *  the first time and the word is what tells you the first time.
 */
export function toolButton(name, label, { on = false, tooltip = "", onClick }) {
  const node = button("", `tool${on ? " on" : ""}`, onClick, tooltip || label);
  put(node, icon(name), el("span", null, label));
  node.setAttribute("aria-pressed", String(Boolean(on)));
  return node;
}

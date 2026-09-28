/**
 * theme.js
 * ========
 *
 * The same palette and the same spacing as theme.py, so the browser version
 * looks like the desktop one instead of merely similar.
 *
 * TWO COPIES OF A PALETTE IS A MAINTENANCE PROBLEM, SO IT IS CHECKED
 * ------------------------------------------------------------------
 * There is no build step here and no way for a browser to read a Python file,
 * so these values do have to be written down twice. What can be avoided is
 * the two copies quietly drifting apart, which is the actual failure: nobody
 * notices a hex digit, and six months later the two programs are slightly
 * different shades of the same app.
 *
 * So parity_cases.py hands out every name and value from theme.py and
 * parity.mjs checks this file against them. Change a color in one place and
 * the harness says which one, by name.
 *
 * The CSS does not get a third copy. apply() below writes these onto the
 * document as custom properties, and app.css reads var(--accent).
 */

// Backgrounds, darkest to lightest. Layering a few near-black grays like this
// rather than using pure black everywhere is most of what makes a dark
// interface look considered instead of flat.
export const BG_APP = "#0d0f14";
export const BG_SIDEBAR = "#12151c";
export const BG_PANEL = "#161a22";
export const BG_CARD = "#1b2029";
export const BG_INPUT = "#11141a";
export const BG_HOVER = "#232936";
export const BG_ACTIVE = "#2b3243";

export const BORDER = "#262c3a";
export const BORDER_LIGHT = "#333b4d";

export const TEXT = "#e8ebf2";
export const TEXT_MUTED = "#98a1b5";
export const TEXT_FAINT = "#5d677d";

export const ACCENT = "#4f7cff";
export const ACCENT_HOVER = "#6b91ff";
export const ACCENT_SOFT = "#1e2a4d";

export const DANGER = "#f2555a";
export const DANGER_HOVER = "#ff6b70";
export const SUCCESS = "#33d6a0";
export const WARNING = "#f0a726";

// The room canvas has its own slightly darker background so it reads as a
// separate workspace rather than more panel.
export const CANVAS_BG = "#0a0c10";
export const GRID_MINOR = "#141821";
export const GRID_MAJOR = "#1c2230";
export const CANVAS_ORIGIN = "#2a3346";

/** The colors offered whenever you color-code something: a profile, floor,
 *  room, container, item or tag. Twelve fits a tidy six by two grid. */
export const SWATCHES = [
  "#4f7cff",  // blue
  "#33d6a0",  // mint
  "#f0a726",  // amber
  "#f2555a",  // coral
  "#a78bfa",  // violet
  "#22d3ee",  // cyan
  "#f472b6",  // pink
  "#84cc16",  // lime
  "#fb923c",  // orange
  "#e879f9",  // magenta
  "#facc15",  // yellow
  "#94a3b8",  // slate
];

// Spacing comes from one small set of numbers rather than being picked per
// widget. Consistent spacing is a surprisingly large part of why an interface
// looks designed rather than assembled.
export const SPACE_XS = 4;
export const SPACE_SM = 8;
export const SPACE_MD = 12;
export const SPACE_LG = 16;
export const SPACE_XL = 24;

export const RADIUS_SM = 6;
export const RADIUS_MD = 8;
export const RADIUS_LG = 12;

export const FONT_SIZE = 13;
export const FONT_SIZE_SM = 11;
export const FONT_SIZE_LG = 16;
export const FONT_SIZE_XL = 22;

// The spacing of the fine grid in scene units, and what room corners and
// containers snap to while being dragged.
export const GRID_SIZE = 20;
export const GRID_MAJOR_EVERY = 5;

// The font stack is the one thing here that is deliberately NOT the Python's.
// theme.py names Segoe UI first because it is running on Windows and knows it.
// A browser might be on a phone, so system-ui asks the device for whatever it
// considers normal, which is the right answer on all of them.
export const FONT_FAMILY =
  'system-ui, -apple-system, "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif';

/** Write the palette onto the document as CSS custom properties.
 *
 *  So app.css can say var(--accent) without the values being written out a
 *  third time. Called once, at startup, before anything is drawn.
 */
export function apply(root = document.documentElement) {
  const named = {
    "bg-app": BG_APP, "bg-sidebar": BG_SIDEBAR, "bg-panel": BG_PANEL,
    "bg-card": BG_CARD, "bg-input": BG_INPUT, "bg-hover": BG_HOVER,
    "bg-active": BG_ACTIVE, "border": BORDER, "border-light": BORDER_LIGHT,
    "text": TEXT, "text-muted": TEXT_MUTED, "text-faint": TEXT_FAINT,
    "accent": ACCENT, "accent-hover": ACCENT_HOVER, "accent-soft": ACCENT_SOFT,
    "danger": DANGER, "danger-hover": DANGER_HOVER, "success": SUCCESS,
    "warning": WARNING, "canvas-bg": CANVAS_BG,
  };
  for (const [name, value] of Object.entries(named)) {
    root.style.setProperty(`--${name}`, value);
  }
  for (const [name, value] of Object.entries({
    xs: SPACE_XS, sm: SPACE_SM, md: SPACE_MD, lg: SPACE_LG, xl: SPACE_XL,
  })) {
    root.style.setProperty(`--space-${name}`, `${value}px`);
  }
  for (const [name, value] of Object.entries({
    sm: RADIUS_SM, md: RADIUS_MD, lg: RADIUS_LG,
  })) {
    root.style.setProperty(`--radius-${name}`, `${value}px`);
  }
  root.style.setProperty("--font", FONT_FAMILY);
  root.style.setProperty("--size", `${FONT_SIZE}px`);
  root.style.setProperty("--size-sm", `${FONT_SIZE_SM}px`);
  root.style.setProperty("--size-lg", `${FONT_SIZE_LG}px`);
  root.style.setProperty("--size-xl", `${FONT_SIZE_XL}px`);
}

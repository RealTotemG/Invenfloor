/**
 * model.js
 * ========
 *
 * The port of models.py. Same record shapes, same save-file format, same
 * geometry, same arithmetic. Nothing in here knows what a screen is.
 *
 * WHY THIS FILE EXISTS BEFORE ANY OF THE SCREENS DO
 * -------------------------------------------------
 * models.py is the part of the desktop app that took the most thinking and
 * has the most tests behind it: which walls face away from you, whether a
 * container is really inside an L-shaped room, what a stored 60 meant before
 * the height presets were halved. None of that is about Qt, and none of it
 * should be worked out a second time just because the drawing moved to a
 * canvas. So it comes across first, on its own, and is checked against the
 * original before a single pixel is drawn.
 *
 * THE SAVE FILE IS THE SAME FILE
 * ------------------------------
 * toDict and fromDict produce and accept exactly what the Python does, field
 * for field, including the schema number and the migration. A profile
 * exported from the desktop app opens here, and one written here opens
 * there. That is deliberate and it is worth keeping: the day this replaces
 * the desktop app is a day that should not need a converter.
 *
 * Plain ES modules, no build step. Open the page and it runs. A bundler is a
 * thing that breaks and needs maintaining, and nothing here needs one.
 */

// ---------------------------------------------------------------------------
// IDS AND TIMESTAMPS
// ---------------------------------------------------------------------------

/** The current date and time as text, e.g. "2026-09-27T14:05:32".
 *
 *  Sliced rather than formatted because toISOString gives UTC with a Z and
 *  milliseconds, and the Python writes local time to the second. Matching it
 *  matters: these strings are sorted as plain text to get "newest first". */
export function nowStamp() {
  const now = new Date();
  const pad = n => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
       + `T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

/** A short unique id, e.g. "a3f9c1d2". Eight hex characters, same as the
 *  Python's uuid4().hex[:8]: far more than enough for a personal app, and it
 *  keeps the save file readable. */
export function newId() {
  const bytes = new Uint8Array(4);
  if (globalThis.crypto && globalThis.crypto.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    // Older runtimes without the web crypto API. These ids label rooms and
    // drawers rather than guarding anything, so ordinary randomness is
    // plenty. (The first version of this reached for require() here, which
    // does not exist in an ES module at all: it would have thrown "require
    // is not defined" instead of falling back, on exactly the old runtimes
    // the fallback was written for.)
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  return [...bytes].map(b => b.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------------------
// NAMES
// ---------------------------------------------------------------------------
//
// Two limits, because they answer two questions. NAME_MAX_LENGTH is what you
// may type. NAME_DISPLAY_LENGTH is what fits on screen. "Upstairs hallway
// closet" is a perfectly good name that shows as "Upstairs hallway c…".

export const NAME_MAX_LENGTH = 40;
export const NAME_DISPLAY_LENGTH = 20;

/** Tidy a typed name and cap its length. Runs of whitespace collapse to one
 *  space, so a pasted line break does not survive into the save file. */
export function cleanName(text, fallback = "Untitled") {
  const tidy = String(text).split(/\s+/).filter(Boolean).join(" ");
  return tidy.slice(0, NAME_MAX_LENGTH).trim() || fallback;
}

/** The on-screen form of a name: at most `limit` characters, ellipsis
 *  included in the count rather than added on top, so `limit` really is the
 *  widest this can ever be. */
export function short(text, limit = NAME_DISPLAY_LENGTH) {
  const tidy = String(text).trim();
  if (tidy.length <= limit) return tidy;
  return tidy.slice(0, limit - 1).replace(/\s+$/, "") + "…";
}

/** "Kitchen" becomes "Kitchen copy", then "Kitchen copy 2", and so on.
 *  The ORIGINAL is trimmed rather than the suffix, so the part that makes
 *  the name unique is the part that always survives the length cap. */
export function copyName(original, taken) {
  const used = new Set([...taken].map(name => String(name).trim().toLowerCase()));
  for (let attempt = 1; ; attempt++) {
    const suffix = attempt === 1 ? " copy" : ` copy ${attempt}`;
    const room = NAME_MAX_LENGTH - suffix.length;
    const candidate = String(original).trim().slice(0, room).trim() + suffix;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
}

// ---------------------------------------------------------------------------
// HEIGHTS
// ---------------------------------------------------------------------------
//
// Four presets rather than a free number, because "waist high" is a thing
// people know about their own furniture and "72" is not.

export const CONTAINER_HEIGHTS = [
  ["Low", 15.0],          // a crate, a low drawer unit
  ["Medium", 30.0],       // a chest of drawers, a workbench
  ["Tall", 50.0],         // a cabinet, a bookcase
  ["Full height", 75.0],  // a wardrobe, floor to ceiling shelving
];

export const DEFAULT_HEIGHT = 30.0;   // Medium, and what every older file becomes
export const MIN_HEIGHT = 6.0;
export const MAX_HEIGHT = 120.0;

/** What Python's float() does, and only what it does.
 *
 *  Worth being fussy about, because this decides what a hand-edited or
 *  half-corrupted save file becomes, and the desktop app and this one have
 *  to agree or the same file opens as two different rooms.
 *
 *    float(True) is 1.0            parseFloat(true) is NaN
 *    float("30abc") raises          parseFloat("30abc") is 30
 *    float("") raises               Number("") is 0
 *    float("inf") is infinity       Number("inf") is NaN
 *
 *  Number() rather than parseFloat() for strings, because parseFloat reads
 *  as far as it can and gives up quietly, which is how "30abc" would become
 *  a perfectly good height here and an error over there. */
const asNumber = value => {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number") return value;
  if (typeof value !== "string") return null;          // None, lists, objects

  const text = value.trim();
  if (!text) return null;                              // float("") raises
  // Python accepts these spellings; JavaScript's Number does not.
  const infinite = /^[+-]?(inf|infinity)$/i.exec(text);
  if (infinite) return text.startsWith("-") ? -Infinity : Infinity;
  if (/^[+-]?nan$/i.test(text)) return NaN;

  // Number() and float() disagree at the edges in both directions:
  //
  //    float("0x10") raises        Number("0x10") is 16
  //    float("1_0")  is 10.0       Number("1_0")  is NaN
  //
  // So reject anything carrying a character a plain decimal cannot, then
  // drop the underscores Python allows between digits. (Python is fussier
  // still, rejecting "1__0" and "_1"; those become 10 and null here, which
  // is a difference nothing outside a fuzzer will ever produce.)
  if (/[^0-9eE+\-._]/.test(text)) return null;
  const n = Number(text.replace(/_/g, ""));
  return Number.isNaN(n) ? null : n;
};

/** The preset nearest a number. What the 3D height handle snaps to. */
export function nearestHeight(height) {
  const n = asNumber(height);
  // NaN compares false against everything, so Python's min() keeps its first
  // candidate and returns Low. Reduce does the same, which is the behavior
  // worth matching rather than the behavior worth having.
  // Every comparison against NaN is false, so reduce (and Python's min)
  // would quietly hand back whichever preset happens to be first.
  if (n === null || Number.isNaN(n)) return DEFAULT_HEIGHT;
  return closestPreset(n)[1];
}

/** The closest preset NAME for a height. Closest rather than exact, because
 *  a file written before the handle snapped can hold a container at 83, and
 *  "Tall" is a more useful thing to read than nothing. */
export function heightName(height) {
  return closestPreset(asNumber(height) ?? DEFAULT_HEIGHT)[0];
}

function closestPreset(height) {
  // Reduce rather than sort, and keep the FIRST on a tie, to match Python's
  // min(), which is stable. A height exactly between two presets has to pick
  // the same one in both languages or the parity check will catch it.
  return CONTAINER_HEIGHTS.reduce((best, pair) =>
    Math.abs(pair[1] - height) < Math.abs(best[1] - height) ? pair : best);
}

/** Keep a container's height sane, whatever set it. */
export function clampHeight(value) {
  const n = asNumber(value);
  // NaN is unreadable, same as null or "oops". Letting it through writes
  // `"height": NaN` into the save file, which Python's json module accepts
  // as an extension and every other JSON reader rejects.
  if (n === null || Number.isNaN(n)) return DEFAULT_HEIGHT;
  return Math.min(Math.max(n, MIN_HEIGHT), MAX_HEIGHT);
}

// ---------------------------------------------------------------------------
// WHAT VERSION A SAVE FILE IS
// ---------------------------------------------------------------------------
//
// Almost every format change is handled by a default on read: a file missing
// a key gets a sensible one. That covers ADDING things.
//
// It does not cover changing what an existing number MEANS. When the height
// presets were halved, a stored 60 stopped meaning "medium" and started
// meaning "tall", and no default can tell those apart.
//
//   1  the original format, and everything written before this counter
//   2  container heights on the halved scale

export const SCHEMA = 2;

export function schemaOf(raw) {
  const n = parseInt(raw?.schema, 10);
  return Number.isFinite(n) ? Math.max(n, 1) : 1;
}

/** Bring an older save file up to the current format, in place.
 *
 *  Works on the raw object rather than on built records, and that is the
 *  whole trick. By the time a Container exists, a missing height has already
 *  been filled in with today's default, and there is no way left to tell
 *  "the user chose 30" from "this file is older than heights". In the raw
 *  object the key is either there or it is not. */
export function migrate(raw) {
  if (schemaOf(raw) < 2) {
    for (const floor of raw.floors ?? []) {
      for (const room of floor.rooms ?? []) {
        for (const container of room.containers ?? []) {
          if (!Object.prototype.hasOwnProperty.call(container, "height")) continue;
          // Halve BEFORE clamping. The limits moved with the scale, so
          // clamping first would squash an old and perfectly legal 150 down
          // to today's maximum and then halve that instead.
          const stored = asNumber(container.height);
          container.height = clampHeight(stored === null ? stored : stored / 2);
        }
      }
    }
  }
  raw.schema = SCHEMA;
  return raw;
}

// ---------------------------------------------------------------------------
// GEOMETRY
// ---------------------------------------------------------------------------

export const MIN_CONTAINER_SIZE = 20;   // one grid square

// How close to a wall still counts as on it. A container flush against a
// wall has corners sitting exactly on the line, and floating point being
// what it is, "exactly" needs a little room either side.
export const ON_WALL = 0.001;

/** Every edge of a polygon as a pair of corners, including the closing one. */
export function wallsOf(points) {
  return points.map((point, index) => [point, points[(index + 1) % points.length]]);
}

/** The point on segment A-B nearest to P, and how far away it is.
 *  A projection: how far along A-B does P land, clamped to the ends so the
 *  answer is always on the actual segment rather than the infinite line. */
export function closestPointOnSegment(ax, ay, bx, by, px, py) {
  const dx = bx - ax, dy = by - ay;
  if (dx === 0 && dy === 0) return [ax, ay, Math.hypot(px - ax, py - ay)];

  let along = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy);
  along = Math.max(0, Math.min(1, along));

  const cx = ax + along * dx, cy = ay + along * dy;
  return [cx, cy, Math.hypot(px - cx, py - cy)];
}

/** Is this point inside the outline? A point ON the outline counts as in.
 *
 *  The on-the-outline case is checked first and on purpose: a container
 *  pushed flush into a corner has two corners sitting exactly on the walls,
 *  and calling those "outside" would refuse the most natural place in the
 *  room to put a cabinet.
 *
 *  The rest is the standard ray cast. The height comparison is deliberately
 *  lopsided, one end counted and the other not, so a ray passing exactly
 *  through a corner is counted once rather than twice or not at all. */
export function pointInPolygon(points, px, py) {
  for (const [[ax, ay], [bx, by]] of wallsOf(points)) {
    if (closestPointOnSegment(ax, ay, bx, by, px, py)[2] <= ON_WALL) return true;
  }
  let inside = false;
  for (const [[ax, ay], [bx, by]] of wallsOf(points)) {
    if ((ay > py) === (by > py)) continue;
    const crossingX = ax + ((py - ay) * (bx - ax)) / (by - ay);
    if (px < crossingX) inside = !inside;
  }
  return inside;
}

/** Do segments A-B and C-D properly cross?
 *
 *  Properly means each has one end on either side of the other's line.
 *  Touching at a point, or lying along each other, does not count: a
 *  container flush against a wall shares a line with it, and that has to
 *  read as fitting rather than as poking through. */
export function segmentsCross(a, b, c, d) {
  const side = (ax, ay, bx, by, px, py) =>
    (bx - ax) * (py - ay) - (by - ay) * (px - ax);
  return side(c[0], c[1], d[0], d[1], a[0], a[1])
       * side(c[0], c[1], d[0], d[1], b[0], b[1]) < 0
    && side(a[0], a[1], b[0], b[1], c[0], c[1])
       * side(a[0], a[1], b[0], b[1], d[0], d[1]) < 0;
}

/** Is this whole rectangle inside the room's outline?
 *
 *  Four questions, in the order they arrived in, each ruling out a shape of
 *  mistake the ones before it let through. Worth saying plainly because the
 *  first version looked finished and was not. */
export function roomContainsRect(room, x, y, width, height) {
  const points = room.points;
  if (points.length < 3) return false;

  const corners = [[x, y], [x + width, y],
                   [x + width, y + height], [x, y + height]];

  // 1. Every corner in the room. Catches a container dragged through a wall.
  for (const [px, py] of corners) {
    if (!pointInPolygon(points, px, py)) return false;
  }

  // 2. No wall slicing across the rectangle with both ends outside it. A
  //    square notch can never do that; a narrow spike can, and it would slip
  //    past the corner test untouched.
  for (const [wallA, wallB] of wallsOf(points)) {
    for (const [edgeA, edgeB] of wallsOf(corners)) {
      if (segmentsCross(edgeA, edgeB, wallA, wallB)) return false;
    }
  }

  // 3. No corner of the ROOM strictly inside the rectangle. This is the one
  //    a fireplace found: a divot smaller than the container dragged over it
  //    sits entirely INSIDE the rectangle, so no wall crosses any edge and
  //    all four corners are still in the room. Strictly inside, because a
  //    container flush into a corner has a room corner sitting ON its edge.
  for (const [px, py] of points) {
    if (px > x + ON_WALL && px < x + width - ON_WALL
     && py > y + ON_WALL && py < y + height - ON_WALL) return false;
  }

  // 4. And the middle in the room, which sounds like it must already follow
  //    and does not. Lay a container exactly over that divot, edge for edge,
  //    and every corner of it is a corner of the room, nothing crosses
  //    anything, and no room corner is strictly inside it.
  return pointInPolygon(points, x + width / 2, y + height / 2);
}

/** Move and shrink a rectangle until it sits inside the room.
 *
 *  Every route that sets a container's geometry comes through here: dragging
 *  it, dragging its handles, typing numbers, drawing a new one, and loading
 *  a save file. One clamp with six callers, rather than six that disagree.
 *
 *  `stay` is where the container is RIGHT NOW, and it is what makes the
 *  room's real shape enforceable. A bounding rectangle you can clamp to; an
 *  outline with a notch has no such answer, and the honest one is "then it
 *  does not go there". Slide along one axis if that fits, else stay put. */
export function fitInRoom(room, x, y, width, height, stay = null) {
  const [roomLeft, roomTop, roomW, roomH] = boundsOf(room);

  width = Math.min(Math.max(width, MIN_CONTAINER_SIZE), roomW);
  height = Math.min(Math.max(height, MIN_CONTAINER_SIZE), roomH);

  // The inner max guards a room narrower than the smallest container, where
  // the right-hand limit would otherwise land left of the left one.
  x = Math.min(Math.max(x, roomLeft), Math.max(roomLeft, roomLeft + roomW - width));
  y = Math.min(Math.max(y, roomTop), Math.max(roomTop, roomTop + roomH - height));

  if (stay === null || roomContainsRect(room, x, y, width, height)) {
    return [x, y, width, height];
  }

  // Already outside before this move: stranded by an older version, or by a
  // room reshaped around it. Refusing would trap it there forever.
  if (!roomContainsRect(room, stay[0], stay[1], stay[2], stay[3])) {
    return [x, y, width, height];
  }

  const [oldX, oldY] = stay;
  for (const [slidX, slidY] of [[x, oldY], [oldX, y]]) {
    if (roomContainsRect(room, slidX, slidY, width, height)) {
      return [slidX, slidY, width, height];
    }
  }
  return [...stay];
}

/** The closest spot to (x, y) where a container this size actually fits.
 *
 *  Only used to repair a save file, where there is no "where it was a moment
 *  ago" to fall back on. The candidates come from the room's own corner
 *  coordinates, each tried as a left edge and as a right edge: in a room of
 *  straight walls, every position flush against something lines up with one
 *  of those numbers. */
export function nearestFit(room, x, y, width, height) {
  const xs = new Set([...room.points.map(p => p[0]),
                      ...room.points.map(p => p[0] - width), x]);
  const ys = new Set([...room.points.map(p => p[1]),
                      ...room.points.map(p => p[1] - height), y]);

  let best = null;
  for (const tryX of [...xs].sort((a, b) => a - b)) {
    for (const tryY of [...ys].sort((a, b) => a - b)) {
      const spot = fitInRoom(room, tryX, tryY, width, height);
      if (!roomContainsRect(room, spot[0], spot[1], spot[2], spot[3])) continue;
      const away = (spot[0] - x) ** 2 + (spot[1] - y) ** 2;
      if (best === null || away < best[0]) best = [away, spot];
    }
  }
  // Nothing fits anywhere: the room is smaller than the container, or has no
  // real shape. The bounding clamp is still the best on offer.
  return best === null ? fitInRoom(room, x, y, width, height) : best[1];
}

/** Pull one container back inside its room, in place. True if it moved. */
export function fitContainer(room, container) {
  let [x, y, width, height] =
    fitInRoom(room, container.x, container.y, container.w, container.h);

  if (!roomContainsRect(room, x, y, width, height)) {
    [x, y, width, height] = nearestFit(room, x, y, width, height);
  }
  if (x === container.x && y === container.y
   && width === container.w && height === container.h) return false;

  container.x = x; container.y = y;
  container.w = width; container.h = height;
  return true;
}

// ---------------------------------------------------------------------------
// ROOM SHAPES
// ---------------------------------------------------------------------------

export const rectanglePoints = (width, height) =>
  [[0, 0], [width, 0], [width, height], [0, height]];

export const squarePoints = size => rectanglePoints(size, size);

/** A triangle with its apex centered along the top edge. */
export const trianglePoints = (width, height) =>
  [[width / 2, 0], [width, height], [0, height]];

/** A circle (or oval) as a many-sided polygon. Twenty segments reads clearly
 *  as a circle without leaving so many corner handles that it gets fiddly. */
export function circlePoints(width, height, segments = 20) {
  const radiusX = width / 2, radiusY = height / 2;
  const points = [];
  for (let step = 0; step < segments; step++) {
    const angle = (Math.PI * 2 * step) / segments;
    // +radius shifts the circle so its bounding box starts at (0, 0),
    // matching every other preset.
    points.push([radiusX + radiusX * Math.cos(angle),
                 radiusY + radiusY * Math.sin(angle)]);
  }
  return points;
}

/** An L. The notch is cut out of the top-right by default. */
export function lShapePoints(width, height, notchWidth = null, notchHeight = null) {
  if (notchWidth === null) notchWidth = width * 0.45;
  if (notchHeight === null) notchHeight = height * 0.45;
  return [
    [0, 0],
    [width - notchWidth, 0],
    [width - notchWidth, notchHeight],
    [width, notchHeight],
    [width, height],
    [0, height],
  ];
}

/** Offered in the shape menu. Add an entry and it appears there; nothing
 *  else needs changing. */
export const ROOM_PRESETS = [
  ["Rectangle", (w, h) => rectanglePoints(w, h)],
  ["Square", (w, h) => squarePoints(Math.min(w, h))],
  ["Circle", (w, h) => circlePoints(w, h)],
  ["Triangle", (w, h) => trianglePoints(w, h)],
  ["L-shape", (w, h) => lShapePoints(w, h)],
];

// ---------------------------------------------------------------------------
// THE RECORDS
// ---------------------------------------------------------------------------
//
// Plain classes with toDict and fromDict, matching the Python field for
// field. Every read uses a default, so an older or hand-edited save file
// loads instead of throwing.

const pick = (raw, key, fallback) =>
  raw[key] === undefined ? fallback : raw[key];

const whole = (value, fallback = 0) => {
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? n : fallback;
};

export class Tag {
  constructor({ id = newId(), name = "New tag", color = "#4f7cff" } = {}) {
    Object.assign(this, { id, name, color });
  }
  toDict() { return { id: this.id, name: this.name, color: this.color }; }
  static fromDict(raw) {
    return new Tag({
      id: pick(raw, "id", newId()),
      name: pick(raw, "name", "Untitled"),
      color: pick(raw, "color", "#4f7cff"),
    });
  }
}

/** "This many of this item, in this container, on this tier."
 *
 *  `tier` is 0 for "just in the container", and 1, 2, 3... for a shelf.
 *  Zero rather than null because it is a number either way and there is no
 *  arithmetic to guard: tier 0 sorts first, which is where loose things go.
 *
 *  The same item CAN appear twice in one container on different tiers.
 *  Shoes on tier 1 and shoes on tier 3 are two honest facts. */
export class Placement {
  constructor(containerId, quantity = 1, tier = 0) {
    Object.assign(this, { containerId, quantity, tier });
  }
  toDict() {
    return { container_id: this.containerId, quantity: this.quantity, tier: this.tier };
  }
  static fromDict(raw) {
    return new Placement(
      pick(raw, "container_id", undefined),
      pick(raw, "quantity", 1),
      // Saved before tiers existed means no tier, which is what zero means.
      Math.max(whole(pick(raw, "tier", 0)), 0),
    );
  }
}

export class Item {
  constructor(fields = {}) {
    const now = nowStamp();
    Object.assign(this, {
      id: newId(), name: "New item", color: "#94a3b8", notes: "",
      placements: [], unfiledQuantity: 1, tagIds: [],
      // Par level: warn when the total drops below this. Zero means "no
      // level set", which keeps the spin box simple with 0 shown as "off".
      minQuantity: 0,
      createdAt: now, updatedAt: now,
    }, fields);
  }

  touch() { this.updatedAt = nowStamp(); }

  /** Below its par level. False when no level has been set. */
  isLow() { return this.minQuantity > 0 && this.totalQuantity() < this.minQuantity; }

  /** How many you own altogether. Once an item has places the quantity lives
   *  in those places; before that, unfiledQuantity is what lets you write
   *  down "24 tent pegs" before you have drawn a single room. */
  totalQuantity() {
    if (this.placements.length) {
      return this.placements.reduce((total, p) => total + p.quantity, 0);
    }
    return this.unfiledQuantity;
  }

  /** The placement in one container, or null. `tier` null means any tier. */
  placementIn(containerId, tier = null) {
    for (const placement of this.placements) {
      if (placement.containerId !== containerId) continue;
      if (tier === null || placement.tier === tier) return placement;
    }
    return null;
  }

  placementsIn(containerId) {
    return this.placements.filter(p => p.containerId === containerId);
  }

  isUnfiled() { return this.placements.length === 0; }

  toDict() {
    return {
      id: this.id, name: this.name, color: this.color, notes: this.notes,
      placements: this.placements.map(p => p.toDict()),
      unfiled_quantity: this.unfiledQuantity,
      tag_ids: [...this.tagIds],
      min_quantity: this.minQuantity,
      created_at: this.createdAt,
      updated_at: this.updatedAt,
    };
  }

  /** Old files stored a single container_id and quantity. Detecting that
   *  shape here, in one place, is why nothing else in the app has to know
   *  two formats ever existed. */
  static fromDict(raw) {
    let placements;
    if ("placements" in raw) {
      placements = raw.placements.map(Placement.fromDict);
    } else {
      placements = [];
      const oldContainer = pick(raw, "container_id", null);
      if (oldContainer) {
        placements = [new Placement(oldContainer, pick(raw, "quantity", 1))];
      }
    }
    // Drop any placement that lost its container id along the way.
    placements = placements.filter(p => p.containerId);

    // An old unfiled item still knew how many there were.
    const unfiled = pick(raw, "unfiled_quantity", pick(raw, "quantity", 1));
    const created = pick(raw, "created_at", null) || nowStamp();

    return new Item({
      id: pick(raw, "id", newId()),
      name: pick(raw, "name", "Untitled"),
      color: pick(raw, "color", "#94a3b8"),
      notes: pick(raw, "notes", ""),
      placements,
      unfiledQuantity: Math.max(whole(unfiled, 1), 0),
      tagIds: [...pick(raw, "tag_ids", [])],
      minQuantity: Math.max(whole(pick(raw, "min_quantity", 0)), 0),
      // Items saved before timestamps existed get one now. Slightly wrong,
      // but a plausible date beats an empty field everywhere it is sorted on.
      createdAt: created,
      updatedAt: pick(raw, "updated_at", null) || created,
    });
  }
}

/** A drawer, cabinet, shelf or bin inside a room.
 *
 *  `h` is DEPTH on the floor plan, not height. The name predates the 3D view
 *  and renaming it would break every save file, so the standing-up direction
 *  is `height` and the two are kept well apart. */
export class Container {
  constructor(fields = {}) {
    Object.assign(this, {
      id: newId(), name: "New container", color: "#f0a726",
      x: 0, y: 0, w: 80, h: 60,
      height: DEFAULT_HEIGHT,
      tagIds: [],
      // Deliberately just a count. Tiers are not named or colored, because a
      // shelf's tiers do not have names, they have positions.
      tierCount: 0,
    }, fields);
  }

  /** [1, 2, 3...] for a tiered container. Empty for a plain one. */
  tiers() {
    return Array.from({ length: this.tierCount }, (_, i) => i + 1);
  }

  toDict() {
    return {
      id: this.id, name: this.name, color: this.color,
      x: this.x, y: this.y, w: this.w, h: this.h,
      height: this.height,
      tag_ids: [...this.tagIds],
      tier_count: this.tierCount,
    };
  }

  static fromDict(raw) {
    return new Container({
      id: pick(raw, "id", newId()),
      name: pick(raw, "name", "Untitled"),
      color: pick(raw, "color", "#f0a726"),
      x: pick(raw, "x", 0), y: pick(raw, "y", 0),
      w: pick(raw, "w", 80), h: pick(raw, "h", 60),
      // Files written before the 3D view have no height, and Medium is a
      // fair guess for a drawer unit you have not told us about.
      height: clampHeight(pick(raw, "height", DEFAULT_HEIGHT)),
      tagIds: [...pick(raw, "tag_ids", [])],
      tierCount: Math.max(whole(pick(raw, "tier_count", 0)), 0),
    });
  }
}

/** A polygon on a floor. `points` is [x, y] pairs measured from the room's
 *  own origin. Three points is the minimum that encloses an area. */
export class Room {
  constructor(fields = {}) {
    Object.assign(this, {
      id: newId(), name: "New room", color: "#4f7cff",
      x: 0, y: 0, points: [], tagIds: [], locked: false, containers: [],
    }, fields);
  }

  center() {
    if (!this.points.length) return [0, 0];
    const xs = this.points.map(p => p[0]), ys = this.points.map(p => p[1]);
    return [(Math.min(...xs) + Math.max(...xs)) / 2,
            (Math.min(...ys) + Math.max(...ys)) / 2];
  }

  bounds() { return boundsOf(this); }

  /** Add a corner on whichever edge is closest to (x, y).
   *
   *  The new corner goes ON the edge rather than at the exact spot you
   *  clicked, so the outline does not change shape the instant you add one.
   *  You add a corner, then drag it where you want it. Dropping it at the raw
   *  click point puts a dent in the wall before anybody asked for one.
   *
   *  Returns the index of the new point, so the caller can select it.
   */
  insertPointOnNearestEdge(x, y) {
    if (this.points.length < 2) return null;

    let bestIndex = 0;
    let bestDistance = null;
    let bestPoint = null;

    for (let index = 0; index < this.points.length; index++) {
      const [ax, ay] = this.points[index];
      const [bx, by] = this.points[(index + 1) % this.points.length];
      const [cx, cy, distance] = closestPointOnSegment(ax, ay, bx, by, x, y);
      // The tolerance decides ties, and a tie is not a freak case: click the
      // exact middle of a circle and all twenty edges are equally close.
      // Without it the winner is whichever one floating point rounded a
      // fraction lower, and Python and JavaScript do not round the same way,
      // so the two programs put the new corner on different edges of the same
      // room from the same click. Both answers are correct and they should
      // still be the same answer, so ties go to the earlier edge.
      if (bestDistance === null || distance < bestDistance - 1e-9) {
        bestDistance = distance;
        bestIndex = index;
        bestPoint = [cx, cy];
      }
    }

    this.points.splice(bestIndex + 1, 0, [bestPoint[0], bestPoint[1]]);
    return bestIndex + 1;
  }

  /** Delete one corner. Refuses below three, which is the fewest that still
   *  encloses an area. */
  removePoint(index) {
    if (this.points.length <= 3) return false;
    if (!(index >= 0 && index < this.points.length)) return false;
    this.points.splice(index, 1);
    return true;
  }

  /** Stretch the whole room to a new width and height.
   *
   *  Every point moves in proportion, so the shape is kept: stretch a circle
   *  and you get an oval, stretch an L and the notch stays where it should be.
   *  This is what the corner handles on a selected room do.
   *
   *  anchorLeft and anchorTop say where the new bounding box should start.
   *  Leave them out to keep the current top-left corner still.
   */
  resizeTo(newWidth, newHeight, anchorLeft = null, anchorTop = null) {
    const [left, top, width, height] = this.bounds();
    if (width <= 0 || height <= 0) return;

    const atLeft = anchorLeft === null ? left : anchorLeft;
    const atTop = anchorTop === null ? top : anchorTop;
    const scaleX = newWidth / width;
    const scaleY = newHeight / height;

    for (const point of this.points) {
      point[0] = atLeft + (point[0] - left) * scaleX;
      point[1] = atTop + (point[1] - top) * scaleY;
    }
  }

  toDict() {
    return {
      id: this.id, name: this.name, color: this.color,
      x: this.x, y: this.y,
      points: this.points.map(([px, py]) => [px, py]),
      tag_ids: [...this.tagIds],
      locked: this.locked,
      containers: this.containers.map(c => c.toDict()),
    };
  }

  static fromDict(raw) {
    const room = new Room({
      id: pick(raw, "id", newId()),
      name: pick(raw, "name", "Untitled"),
      color: pick(raw, "color", "#4f7cff"),
      x: pick(raw, "x", 0), y: pick(raw, "y", 0),
      points: pick(raw, "points", []).map(p => [...p]),
      tagIds: [...pick(raw, "tag_ids", [])],
      // Files written before locks existed have no such key, and unlocked is
      // the right thing for them to become.
      locked: Boolean(pick(raw, "locked", false)),
      containers: pick(raw, "containers", []).map(Container.fromDict),
    });
    // An older version could leave a container stranded outside its room,
    // where it could not be clicked. Those repair themselves on the way in
    // rather than waiting to be found.
    if (room.points.length) {
      for (const container of room.containers) fitContainer(room, container);
    }
    return room;
  }
}

/** Kept as a function so fitInRoom can take anything with `points` rather
 *  than only a real Room. The demo passes a bare object. */
/** A room's corners in FLOOR coordinates, not its own.
 *
 *  A room's points are relative to its own x and y, which is what lets you
 *  drag one around without rewriting every corner. Comparing two rooms means
 *  putting both in the same coordinates first, and forgetting to is how you
 *  get two rooms that look separated on screen and identical to the maths.
 */
export function roomOutline(room) {
  return room.points.map(([x, y]) => [x + room.x, y + room.y]);
}

/** Every corner, nudged a hair towards the middle of its own shape.
 *
 *  The corners themselves are the wrong thing to ask about, and this is the
 *  whole difficulty of roomsOverlap below. Two rooms side by side share a
 *  wall, so two of one room's corners sit exactly ON the other's outline, and
 *  pointInPolygon counts a point on the boundary as inside. Asked with the
 *  raw corners, every pair of neighbouring rooms in a correctly drawn plan
 *  reports as overlapping, and a warning that fires on the normal case is a
 *  warning nobody reads.
 *
 *  What is actually being asked is whether a corner is in the other room's
 *  INTERIOR. Moving it a thousandth of the way towards its own centre is how
 *  you ask that: a corner that was only touching steps off the line, and one
 *  that was genuinely inside stays inside.
 */
function justInside(outline) {
  const xs = outline.map(([x]) => x);
  const ys = outline.map(([, y]) => y);
  const middleX = (Math.min(...xs) + Math.max(...xs)) / 2;
  const middleY = (Math.min(...ys) + Math.max(...ys)) / 2;
  return outline.map(([x, y]) =>
    [x + (middleX - x) * 0.001, y + (middleY - y) * 0.001]);
}

/** Do these two rooms cover any of the same floor?
 *
 *  Bounding boxes would be quicker and would lie: two L-shapes can have boxes
 *  that overlap while the rooms themselves sit comfortably apart, and a
 *  warning that cries wolf gets ignored, which is worse than no warning.
 *
 *  So it is the real test, which is three questions rather than one:
 *
 *    1. does any wall of one cross any wall of the other
 *    2. is a corner of one inside the other
 *    3. is a corner of the other inside the one
 *
 *  The second and third are not the same question asked twice. One room
 *  entirely inside another crosses no walls at all, and only one of the two
 *  has corners inside the other.
 */
export function roomsOverlap(first, second) {
  const ours = roomOutline(first);
  const theirs = roomOutline(second);
  if (ours.length < 3 || theirs.length < 3) return false;

  for (const [a, b] of wallsOf(ours)) {
    for (const [c, d] of wallsOf(theirs)) {
      if (segmentsCross(a, b, c, d)) return true;
    }
  }

  if (justInside(ours).some(([x, y]) => pointInPolygon(theirs, x, y))) return true;
  if (justInside(theirs).some(([x, y]) => pointInPolygon(ours, x, y))) return true;
  return false;
}

/** Every other room on this floor that `room` is sitting on top of. */
export function roomsOverlapping(floor, room) {
  return floor.rooms.filter(other => other !== room && roomsOverlap(room, other));
}

export function boundsOf(room) {
  if (!room.points || !room.points.length) return [0, 0, 0, 0];
  const xs = room.points.map(p => p[0]), ys = room.points.map(p => p[1]);
  const left = Math.min(...xs), top = Math.min(...ys);
  return [left, top, Math.max(...xs) - left, Math.max(...ys) - top];
}

/** One level of a building. A floor has no level number: its position in the
 *  profile's list IS its height. Index 0 is the lowest. */
export class Floor {
  constructor(fields = {}) {
    Object.assign(this, {
      id: newId(), name: "New floor", color: "#4f7cff", rooms: [],
    }, fields);
  }
  toDict() {
    return {
      id: this.id, name: this.name, color: this.color,
      rooms: this.rooms.map(r => r.toDict()),
    };
  }
  static fromDict(raw) {
    return new Floor({
      id: pick(raw, "id", newId()),
      name: pick(raw, "name", "Untitled"),
      color: pick(raw, "color", "#4f7cff"),
      rooms: pick(raw, "rooms", []).map(Room.fromDict),
    });
  }
}

/** A whole separate inventory: its own floors, its own tags, its own items. */
export class Profile {
  constructor(fields = {}) {
    Object.assign(this, {
      id: newId(), name: "New profile", color: "#4f7cff",
      floors: [], tags: [], items: [],
      // Show rooms in 3D when you step inside one. Kept with the profile so
      // it survives closing the app and so two profiles can disagree.
      view3d: true,
      schema: SCHEMA,
    }, fields);
  }

  toDict() {
    return {
      id: this.id, name: this.name, color: this.color,
      view_3d: this.view3d, schema: SCHEMA,
      floors: this.floors.map(f => f.toDict()),
      tags: this.tags.map(t => t.toDict()),
      items: this.items.map(i => i.toDict()),
    };
  }

  static fromDict(raw) {
    raw = migrate(raw);
    return new Profile({
      id: pick(raw, "id", newId()),
      name: pick(raw, "name", "Untitled"),
      color: pick(raw, "color", "#4f7cff"),
      // On for a file that predates the setting, because it is on by default
      // and an existing profile should get the new view too.
      view3d: Boolean(pick(raw, "view_3d", true)),
      schema: schemaOf(raw),
      floors: pick(raw, "floors", []).map(Floor.fromDict),
      tags: pick(raw, "tags", []).map(Tag.fromDict),
      items: pick(raw, "items", []).map(Item.fromDict),
    });
  }

  tagById(tagId) { return this.tags.find(t => t.id === tagId) ?? null; }

  *allRooms() {
    for (const floor of this.floors) for (const room of floor.rooms) yield [floor, room];
  }

  *allContainers() {
    for (const [floor, room] of this.allRooms()) {
      for (const container of room.containers) yield [floor, room, container];
    }
  }

  containerById(containerId) {
    for (const [, , container] of this.allContainers()) {
      if (container.id === containerId) return container;
    }
    return null;
  }

  /** "Ground Floor / Garage / Tall shelving" for a container id. */
  whereIs(containerId) {
    for (const [floor, room, container] of this.allContainers()) {
      if (container.id === containerId) return [floor, room, container];
    }
    return null;
  }

  /** Turn a list of tag ids into real Tags.
   *
   *  Ids that no longer exist are skipped, so deleting a tag can never leave
   *  a room or an item pointing at nothing.
   */
  tagsFor(tagIds) {
    return tagIds.map(id => this.tagById(id)).filter(Boolean);
  }

  /** [floor, room, container], or [null, null, null] if it is gone. */
  findContainer(containerId) {
    return this.whereIs(containerId) ?? [null, null, null];
  }

  findRoom(roomId) {
    for (const [floor, room] of this.allRooms()) {
      if (room.id === roomId) return [floor, room];
    }
    return [null, null];
  }

  /** "Ground Floor / Kitchen / Top drawer", or null if it is gone. */
  containerPath(containerId) {
    const [floor, room, container] = this.findContainer(containerId);
    if (!container) return null;
    return `${floor.name} / ${room.name} / ${container.name}`;
  }

  // -- where an item is -----------------------------------------------------

  /** Every place this item is kept, as [floor, room, container, quantity, tier].
   *
   *  Placements whose container has been deleted are skipped, so this can be
   *  shorter than item.placements.
   */
  locationsOf(item) {
    const found = [];
    for (const placement of item.placements) {
      const [floor, room, container] = this.findContainer(placement.containerId);
      if (container) {
        found.push([floor, room, container, placement.quantity, placement.tier]);
      }
    }
    return found;
  }

  /** A short line saying where an item lives.
   *
   *  One place gets the full path; several get a count, because three full
   *  paths on one row is unreadable. The items screen expands to show them.
   */
  locationOf(item) {
    const places = this.locationsOf(item);
    if (!places.length) return "Unfiled";
    if (places.length === 1) {
      const [floor, room, container, , tier] = places[0];
      return `${floor.name} / ${room.name} / ${container.name}`
             + (tier ? ` · Tier ${tier}` : "");
    }
    return `${places.length} places`;
  }

  /** What is in one container, as [item, quantity, tier].
   *
   *  One row per PLACEMENT rather than per item, because a thing can sit on
   *  two tiers of the same shelf and both are worth showing. Sorted by tier,
   *  so whatever is loose in the container comes first and then tier 1
   *  downward.
   *
   *  Pass no tier for everything, or a number for one tier, including 0 for
   *  the part of the container that has no tier.
   */
  contentsOf(containerId, tier = null) {
    const found = [];
    for (const item of this.items) {
      for (const placement of item.placementsIn(containerId)) {
        if (tier === null || placement.tier === tier) {
          found.push([item, placement.quantity, placement.tier]);
        }
      }
    }
    found.sort((a, b) => a[2] - b[2]
      || a[0].name.toLowerCase().localeCompare(b[0].name.toLowerCase()));
    return found;
  }

  /** How many DIFFERENT items are in a container, not how many units.
   *
   *  Counted by item, so a thing kept on two tiers of one shelf is still one
   *  thing in that shelf.
   */
  itemCountInContainer(containerId) {
    return new Set(this.contentsOf(containerId).map(([item]) => item.id)).size;
  }

  /** Every distinct item with at least one placement in this room.
   *
   *  An item kept in two drawers of the same room is counted once: the
   *  question is "what is in here", not "how many boxes".
   */
  itemsInRoom(room) {
    const ids = new Set(room.containers.map(container => container.id));
    return this.items.filter(item =>
      item.placements.some(placement => ids.has(placement.containerId)));
  }

  unfiledItems() { return this.items.filter(item => item.isUnfiled()); }

  /** Everything below its par level. */
  lowItems() { return this.items.filter(item => item.isLow()); }

  itemsWithTag(tagId) {
    return this.items.filter(item => item.tagIds.includes(tagId));
  }

  /** Which rooms carry this tag, as [floor, room].
   *
   *  The other half of the tag idea: a tag on an ITEM says what the thing is,
   *  and the same tag on a ROOM says where things like that are supposed to
   *  live. Comparing the two is how you spot something filed in the wrong
   *  place.
   */
  *roomsWithTag(tagId) {
    for (const [floor, room] of this.allRooms()) {
      if (room.tagIds.includes(tagId)) yield [floor, room];
    }
  }

  /** Items sitting somewhere their own tags say they should not be.
   *
   *  If an item is tagged Tools, some room is tagged Tools, and the item is
   *  in none of those rooms, it is probably in the wrong place.
   *
   *  Two deliberate exclusions. If no room carries the tag at all there is no
   *  expectation to break, so there is nothing to report. And unfiled items
   *  are not misfiled: they are not anywhere yet, which is a different
   *  problem with its own view.
   *
   *  Returns [item, tag, expectedRooms] so a screen can say exactly why each
   *  entry is listed.
   */
  misfiledItems() {
    const reports = [];
    for (const item of this.items) {
      const places = this.locationsOf(item);
      if (!places.length) continue;
      const roomsItIsIn = places.map(([, room]) => room);

      for (const tagId of item.tagIds) {
        const expected = [...this.roomsWithTag(tagId)].map(([, room]) => room);
        if (!expected.length) continue;
        if (!roomsItIsIn.some(room => room.tagIds.includes(tagId))) {
          reports.push([item, this.tagById(tagId), expected]);
        }
      }
    }
    return reports;
  }

  /** Newest first. ISO timestamps sort correctly as plain strings. */
  recentItems(limit = null) {
    const ordered = [...this.items].sort((a, b) =>
      a.createdAt < b.createdAt ? 1 : (a.createdAt > b.createdAt ? -1 : 0));
    return limit ? ordered.slice(0, limit) : ordered;
  }

  // -- changing things ------------------------------------------------------

  /** Put, or update, a quantity of an item in a container, on a tier.
   *
   *  A quantity of zero or less removes the placement, which is what makes
   *  "I have used them all up" the same gesture as "wrong drawer".
   *
   *  Matches on container AND tier, so putting shoes on tier 3 does not
   *  overwrite the shoes already on tier 1.
   */
  setPlacement(item, containerId, quantity, tier = 0) {
    const existing = item.placementIn(containerId, tier);

    if (quantity <= 0) {
      if (existing) {
        item.placements = item.placements.filter(each => each !== existing);
      }
      return;
    }
    if (!existing) item.placements.push(new Placement(containerId, quantity, tier));
    else existing.quantity = quantity;
  }

  /** Move some of an item from one tier of a container to another.
   *
   *  Takes a quantity rather than moving the whole pile, because a shelf's
   *  whole point is that four of a thing can be on one level and two on
   *  another. Moving part of a stack leaves the rest where it was.
   *
   *  The destination is added to, never replaced: two already on tier 3 plus
   *  two moved there is four.
   */
  moveToTier(item, containerId, fromTier, toTier, quantity) {
    const source = item.placementIn(containerId, fromTier);
    if (!source || toTier === fromTier) return;

    const moving = Math.min(Math.max(Math.trunc(quantity) || 0, 0), source.quantity);
    if (moving <= 0) return;

    source.quantity -= moving;
    if (source.quantity <= 0) {
      item.placements = item.placements.filter(each => each !== source);
    }

    const destination = item.placementIn(containerId, toTier);
    if (!destination) item.placements.push(new Placement(containerId, moving, toTier));
    else destination.quantity += moving;

    item.touch();
  }

  /** Change how many tiers a container has.
   *
   *  Removing tiers throws nothing away. Items on a tier that no longer
   *  exists come back to the container itself, which is the honest answer:
   *  you still own them and they are still in that cupboard, you just stopped
   *  dividing it up.
   */
  setTierCount(container, count) {
    const tiers = Math.max(Math.trunc(count) || 0, 0);
    container.tierCount = tiers;
    for (const item of this.items) {
      for (const placement of item.placementsIn(container.id)) {
        if (placement.tier > tiers) placement.tier = 0;
      }
    }
  }

  /** Remove a tag, and strip it from everything that referenced it.
   *
   *  Cleaning up references at the moment of deletion is what stops a save
   *  file slowly filling with ids pointing at things that are not there.
   */
  deleteTag(tagId) {
    this.tags = this.tags.filter(tag => tag.id !== tagId);
    const strip = holder => {
      holder.tagIds = holder.tagIds.filter(id => id !== tagId);
    };
    this.items.forEach(strip);
    for (const [, room] of this.allRooms()) {
      strip(room);
      room.containers.forEach(strip);
    }
  }

  /** Remove a container. Items keep their other places.
   *
   *  Deleting a drawer should not delete the record of what was in it: you
   *  almost certainly still own those things. An item kept only there becomes
   *  unfiled; one kept elsewhere too is untouched apart from losing that one
   *  placement.
   */
  deleteContainer(containerId) {
    for (const [, room] of this.allRooms()) {
      room.containers = room.containers.filter(each => each.id !== containerId);
    }
    for (const item of this.items) {
      item.placements = item.placements.filter(
        placement => placement.containerId !== containerId);
    }
  }

  /** Remove a room, and every placement inside its containers. */
  deleteRoom(roomId) {
    for (const floor of this.floors) {
      for (const room of [...floor.rooms]) {
        if (room.id !== roomId) continue;
        for (const container of [...room.containers]) {
          this.deleteContainer(container.id);
        }
        floor.rooms = floor.rooms.filter(each => each !== room);
      }
    }
  }

  deleteFloor(floorId) {
    for (const floor of [...this.floors]) {
      if (floor.id !== floorId) continue;
      for (const room of [...floor.rooms]) this.deleteRoom(room.id);
      this.floors = this.floors.filter(each => each !== floor);
    }
  }

  /** Where this floor sits in the stack. 0 is the lowest. */
  floorIndex(floor) {
    return this.floors.findIndex(candidate => candidate.id === floor.id);
  }
}

/** A deep copy of a room or container with brand new ids.
 *
 *  Works by writing the thing out and reading it back, the same round trip
 *  saving already does. That is the point: there is no second copy of "what
 *  a room consists of" to keep in step.
 *
 *  Nothing inside a container comes along. Items live in the catalog and say
 *  which containers they are in, so a duplicated shelf stands empty. Copying
 *  the contents would mean claiming you own twice as many shoes as you do. */
export function duplicate(thing, name = null) {
  const made = thing.constructor.fromDict(thing.toDict());
  made.id = newId();
  for (const container of made.containers ?? []) container.id = newId();
  if (name !== null) made.name = name;
  return made;
}

export function duplicateFloor(floor, name = null) {
  const made = Floor.fromDict(floor.toDict());
  made.id = newId();
  for (const room of made.rooms) {
    room.id = newId();
    for (const container of room.containers) container.id = newId();
  }
  if (name !== null) made.name = name;
  return made;
}

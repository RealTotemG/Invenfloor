/**
 * floor.js
 * ========
 *
 * The floor plan: the grid, panning and zooming, drawing rooms, reshaping
 * them, and dropping containers into them. The browser's answer to
 * floor_view.py and floor_items.py together.
 *
 * THE TOOLS
 * ---------
 * The canvas is always in exactly one mode, and every pointer event asks
 * which one first. Keeping that as a single variable, rather than a scatter
 * of booleans like `drawing` and `placing`, is what stops canvas code turning
 * into a mess, because there is only ever one answer to "what does a press
 * mean right now?".
 *
 *     select    press to select. What dragging then does is decided by the
 *               room edit mode below. Double-press a room to step inside it.
 *     draw      press to place each corner, press the first corner again to
 *               close the shape
 *     shape     drag out one of the preset shapes, or press once for a
 *               default-sized one
 *     box       drag a rectangle inside a room to make a container there
 *
 * MOVE, RESIZE, SHAPE
 * -------------------
 * A second setting, shared by every room on the canvas, answering "what does
 * dragging a selected room do?": move it, stretch it, or pull its corners
 * about. It sticks as you press from room to room, which is why it belongs to
 * the canvas rather than to each room.
 *
 *     Move     drag the room around.
 *     Resize   square handles round the outside. Dragging one stretches the
 *              WHOLE room and keeps its shape: an oval stays an oval, an L
 *              keeps its notch. This is what you want nine times in ten.
 *     Shape    round handles on every corner, one per corner. Press an edge
 *              to add a corner, double-press one to take it away.
 *
 * Splitting the last two up is deliberate. A circle is stored as a twenty
 * sided polygon, and twenty round handles all over it would be unusable, but
 * four corner handles to stretch it into an oval is exactly right.
 *
 * STEPPING INSIDE
 * ---------------
 * Double-pressing a room focuses it: the others fade back, the focused one
 * stops moving so it cannot be shoved by accident, and its containers become
 * draggable. Press empty space to come back out. Same idea as the Sims
 * dropping into one room to furnish it.
 *
 * TWO FINGERS ARE THE CAMERA
 * --------------------------
 * The desktop app pans with the right mouse button, which a phone does not
 * have. So: one finger is the tool, two fingers are the camera, pinching to
 * zoom and sliding to pan. That is what every drawing app on a phone does,
 * which means it is what hands already expect. On a desktop the wheel zooms
 * and the middle button or space bar pans, and the left button is the tool,
 * which is what hands expect there.
 */
import * as M from "./model.js";
import * as T from "./theme.js";

export const SELECT = "select";
export const DRAW = "draw";
export const SHAPE = "shape";
export const BOX = "box";

export const MOVE = "move";
export const RESIZE = "resize";
export const VERTICES = "vertices";

const MIN_ZOOM = 0.15;
const MAX_ZOOM = 5;
const DRAG_SLOP = 4;              // pixels before a press counts as a drag
const DOUBLE_GAP = 320;           // milliseconds for a double press
const CLOSE_DISTANCE = 20;        // press this near the first corner to close
const DEFAULT_SHAPE = 160;        // a preset pressed rather than dragged out

// Handles are drawn small and hit large. A nine pixel square is what the
// desktop draws and is about a third of what a fingertip can reliably land
// on, so the drawn size and the hit size are two different numbers here.
const HANDLE_DRAWN = 9;
// How close a press has to land, in CSS pixels, measured from the middle of a
// handle. Bigger than what is drawn, for both: a nine pixel square needs a
// twenty-four pixel target with a mouse, and about twice that with a finger.
//
// Being stingy here is worse than it sounds. A resize handle sits ON the edge
// of a room, so half the area around it is outside the room, and a press that
// misses the handle outward lands on empty floor and deselects the room. The
// handles then vanish, which reads as the app refusing to be resized.
const GRAB_MOUSE = 12;
const GRAB_TOUCH = 22;

/** The eight points a resize box is dragged by, as fractions of its bounds.
 *  Corners first, so a press near a corner wins over the edge beside it. */
const GRIP_SPOTS = [
  ["nw", 0, 0], ["ne", 1, 0], ["se", 1, 1], ["sw", 0, 1],
  ["n", 0.5, 0], ["e", 1, 0.5], ["s", 0.5, 1], ["w", 0, 0.5],
];

export function snap(value) {
  return Math.round(value / T.GRID_SIZE) * T.GRID_SIZE;
}

export class FloorView {
  constructor(canvas, {
    onChanged = () => {}, onSelected = () => {}, onFocused = () => {},
    onModeChanged = () => {},
  } = {}) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.onChanged = onChanged;
    this.onSelected = onSelected;
    this.onFocused = onFocused;
    this.onModeChanged = onModeChanged;

    this.profile = null;
    this.floor = null;

    this.mode = SELECT;
    this.preset = null;             // which preset, while mode is SHAPE
    this.editMode = MOVE;

    this.selected = null;           // a Room or a Container
    this.focused = null;            // a Room being worked inside

    this.scale = 1;
    this.panX = 0;
    this.panY = 0;
    // Has anybody moved the camera yet? Until they have, the view refits
    // itself whenever the canvas changes size, which matters more than it
    // sounds: the toolbars above it are built after the canvas, so the first
    // fit happens against a canvas that is about to get shorter, and without
    // this the rooms stay parked wherever that first guess put them. It also
    // means turning a phone sideways shows you the floor rather than a corner
    // of it. Once somebody has panned or zoomed, their camera is theirs.
    this.cameraMoved = false;

    this.pointers = new Map();      // live pointers, for pinch and pan
    this.drag = null;
    this.drawing = null;            // corners placed so far, while drawing
    this.lastPress = { at: 0, thing: null };
    this.spaceHeld = false;

    this.watcher = new ResizeObserver(() => this.resize());
    this.watcher.observe(canvas.parentElement ?? canvas);

    this.listeners = [
      [canvas, "pointerdown", event => this.pressed(event)],
      [canvas, "pointermove", event => this.moved(event)],
      [canvas, "pointerup", event => this.released(event)],
      [canvas, "pointercancel", event => this.released(event)],
      [canvas, "wheel", event => this.wheeled(event), { passive: false }],
      [canvas, "contextmenu", event => event.preventDefault()],
      [window, "keydown", event => this.keyDown(event)],
      [window, "keyup", event => this.keyUp(event)],
    ];
    for (const [target, name, handler, options] of this.listeners) {
      target.addEventListener(name, handler, options);
    }
  }

  stop() {
    this.watcher.disconnect();
    for (const [target, name, handler, options] of this.listeners) {
      target.removeEventListener(name, handler, options);
    }
  }

  show(profile, floor) {
    this.profile = profile;
    this.floor = floor;
    this.selected = null;
    this.focused = null;
    this.drawing = null;
    this.cameraMoved = false;
    this.resize();
  }

  setMode(mode, preset = null) {
    this.mode = mode;
    this.preset = preset;
    this.drawing = null;
    if (mode !== SELECT) this.select(null);
    this.onModeChanged(mode, preset);
    this.draw();
  }

  setEditMode(editMode) {
    this.editMode = editMode;
    this.draw();
  }

  select(thing) {
    if (this.selected === thing) return;
    this.selected = thing;
    this.onSelected(thing);
    this.draw();
  }

  stepInto(room) {
    this.focused = room;
    this.selected = room ? null : this.selected;
    this.onFocused(room);
    this.onSelected(this.selected);
    this.draw();
  }

  // -- the camera -----------------------------------------------------------

  resize() {
    const box = this.canvas.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(box.width * ratio);
    this.canvas.height = Math.round(box.height * ratio);
    if (this.cameraMoved) this.draw(); else this.fit();
  }

  /** Put everything on this floor on screen, with a margin. */
  fit() {
    const rooms = this.floor?.rooms ?? [];
    if (!rooms.length) {
      this.scale = window.devicePixelRatio || 1;
      this.panX = this.canvas.width / 2;
      this.panY = this.canvas.height / 2;
      this.draw();
      return;
    }

    let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    for (const room of rooms) {
      const [x, y, w, h] = room.bounds();
      left = Math.min(left, x + room.x);
      top = Math.min(top, y + room.y);
      right = Math.max(right, x + room.x + w);
      bottom = Math.max(bottom, y + room.y + h);
    }

    // Room names are drawn above their outline, so a strip at the top is set
    // aside for them and the rooms are centred in what is left. Adding the
    // strip on afterwards instead, which is what this did first, pushes
    // everything to the bottom and leaves a band of empty grid above it.
    const ratio = window.devicePixelRatio || 1;
    const pad = 30 * ratio;
    const labels = 26 * ratio;
    const wide = Math.max(right - left, 1);
    const high = Math.max(bottom - top, 1);

    this.scale = this.clampZoom(Math.min(
      (this.canvas.width - pad * 2) / wide,
      (this.canvas.height - pad * 2 - labels) / high));
    this.panX = (this.canvas.width - wide * this.scale) / 2 - left * this.scale;
    this.panY = labels + (this.canvas.height - labels - high * this.scale) / 2
                - top * this.scale;
    this.draw();
  }

  clampZoom(value) {
    const ratio = window.devicePixelRatio || 1;
    return Math.max(MIN_ZOOM * ratio, Math.min(MAX_ZOOM * ratio, value));
  }

  /** Zoom about a fixed point on the canvas, so whatever is under the pointer
   *  stays under it. Zooming about the middle instead is the thing that makes
   *  a canvas feel like it is fighting you. */
  zoomAt(canvasX, canvasY, factor) {
    this.cameraMoved = true;
    const was = this.scale;
    this.scale = this.clampZoom(this.scale * factor);
    const change = this.scale / was;
    this.panX = canvasX - (canvasX - this.panX) * change;
    this.panY = canvasY - (canvasY - this.panY) * change;
    this.draw();
  }

  toScreen(x, y) {
    return { x: x * this.scale + this.panX, y: y * this.scale + this.panY };
  }

  toScene(canvasX, canvasY) {
    return [(canvasX - this.panX) / this.scale, (canvasY - this.panY) / this.scale];
  }

  /** A pointer event in canvas pixels. */
  at(event) {
    const box = this.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    return [(event.clientX - box.left) * ratio, (event.clientY - box.top) * ratio];
  }

  /** How far a press may land from a handle and still count, in canvas
   *  pixels. Bigger for a finger than for a mouse, because a fingertip covers
   *  about ten times the area a cursor points at. */
  grabRadius(event) {
    const ratio = window.devicePixelRatio || 1;
    return (event?.pointerType === "touch" ? GRAB_TOUCH : GRAB_MOUSE) * ratio;
  }

  // -- what is where --------------------------------------------------------

  /** A room's outline in scene coordinates, with its position folded in. */
  outline(room) {
    return room.points.map(([x, y]) => [x + room.x, y + room.y]);
  }

  /** The bounding box of a room in scene coordinates. */
  boxOf(room) {
    const [x, y, w, h] = room.bounds();
    return [x + room.x, y + room.y, w, h];
  }

  /** Where the eight resize grips sit for a room, in scene coordinates. */
  gripsFor(room) {
    const [x, y, w, h] = this.boxOf(room);
    return GRIP_SPOTS.map(([name, fx, fy]) =>
      ({ name, x: x + w * fx, y: y + h * fy }));
  }

  roomAt(sceneX, sceneY) {
    // Backwards, so the room drawn last, and therefore on top, is the one a
    // press finds first.
    const rooms = this.floor?.rooms ?? [];
    for (let at = rooms.length - 1; at >= 0; at--) {
      if (M.pointInPolygon(this.outline(rooms[at]), sceneX, sceneY)) return rooms[at];
    }
    return null;
  }

  containerAt(room, sceneX, sceneY) {
    for (let at = room.containers.length - 1; at >= 0; at--) {
      const box = room.containers[at];
      if (sceneX >= box.x + room.x && sceneX <= box.x + room.x + box.w
          && sceneY >= box.y + room.y && sceneY <= box.y + room.y + box.h) {
        return room.containers[at];
      }
    }
    return null;
  }

  // -- drawing --------------------------------------------------------------

  draw() {
    const ctx = this.context;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = T.CANVAS_BG;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.floor) return;

    this.drawGrid();

    for (const room of this.floor.rooms) this.drawRoom(room);
    if (this.drawing) this.drawInProgress();
    if (this.drag?.kind === "newShape") this.drawNewShape();
    if (this.drag?.kind === "newBox") this.drawNewBox();

    const chosen = this.selected;
    if (chosen instanceof M.Room && !this.focused && !chosen.locked) {
      if (this.editMode === RESIZE) this.drawGrips(chosen);
      if (this.editMode === VERTICES) this.drawVertices(chosen);
    }
    if (chosen instanceof M.Container) this.drawBoxGrips(chosen);
  }

  drawGrid() {
    const ctx = this.context;
    const step = T.GRID_SIZE * this.scale;
    // Below about six pixels a grid stops being a guide and becomes noise, so
    // the fine lines drop out and only every fifth one is left.
    const fine = step >= 6;
    const major = step * T.GRID_MAJOR_EVERY;
    if (major < 5) return;

    const [left, top] = this.toScene(0, 0);
    const [right, bottom] = this.toScene(this.canvas.width, this.canvas.height);
    const ratio = window.devicePixelRatio || 1;

    const lines = (spacing, color, width) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width * ratio;
      ctx.beginPath();
      const startX = Math.floor(left / spacing) * spacing;
      for (let x = startX; x <= right; x += spacing) {
        const at = this.toScreen(x, 0).x;
        ctx.moveTo(at, 0);
        ctx.lineTo(at, this.canvas.height);
      }
      const startY = Math.floor(top / spacing) * spacing;
      for (let y = startY; y <= bottom; y += spacing) {
        const at = this.toScreen(0, y).y;
        ctx.moveTo(0, at);
        ctx.lineTo(this.canvas.width, at);
      }
      ctx.stroke();
    };

    if (fine) lines(T.GRID_SIZE, T.GRID_MINOR, 1);
    lines(T.GRID_SIZE * T.GRID_MAJOR_EVERY, T.GRID_MAJOR, 1);

    // The origin, so a floor has somewhere recognizable in it however far you
    // have wandered off.
    ctx.strokeStyle = T.CANVAS_ORIGIN;
    ctx.lineWidth = 1.5 * ratio;
    ctx.beginPath();
    const zero = this.toScreen(0, 0);
    ctx.moveTo(zero.x, 0); ctx.lineTo(zero.x, this.canvas.height);
    ctx.moveTo(0, zero.y); ctx.lineTo(this.canvas.width, zero.y);
    ctx.stroke();
  }

  path(points) {
    const ctx = this.context;
    ctx.beginPath();
    points.forEach(([x, y], at) => {
      const point = this.toScreen(x, y);
      if (at) ctx.lineTo(point.x, point.y); else ctx.moveTo(point.x, point.y);
    });
    ctx.closePath();
  }

  drawRoom(room) {
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const chosen = room === this.selected;
    const inside = room === this.focused;
    // Everything else fades back while you are working inside one room, which
    // is the whole point of stepping in.
    const dim = this.focused && !inside;

    this.path(this.outline(room));
    ctx.fillStyle = tint(room.color, dim ? 0.04 : (chosen ? 0.18 : (inside ? 0.16 : 0.10)));
    ctx.fill();

    ctx.strokeStyle = tint(room.color, dim ? 0.25 : 0.95);
    ctx.lineWidth = (inside ? 3 : (chosen ? 2.5 : 1.6)) * ratio;
    ctx.lineJoin = "round";
    // A locked room gets a dashed outline. Selecting one shows no handles, and
    // without a visible difference that just looks like the app ignoring you.
    ctx.setLineDash(room.locked && !inside ? [7 * ratio, 5 * ratio] : []);
    ctx.stroke();
    ctx.setLineDash([]);

    for (const box of room.containers) this.drawContainer(room, box, dim);
    this.drawRoomLabel(room, dim);

    // While resizing, outline the bounding box faintly so it is obvious what
    // the handles are moving.
    if (chosen && !inside && !room.locked && this.editMode === RESIZE) {
      const [x, y, w, h] = this.boxOf(room);
      const a = this.toScreen(x, y), b = this.toScreen(x + w, y + h);
      ctx.strokeStyle = tint(T.ACCENT, 0.45);
      ctx.lineWidth = ratio;
      ctx.setLineDash([5 * ratio, 4 * ratio]);
      ctx.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
      ctx.setLineDash([]);
    }
  }

  drawContainer(room, box, dim) {
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const a = this.toScreen(box.x + room.x, box.y + room.y);
    const b = this.toScreen(box.x + room.x + box.w, box.y + room.y + box.h);
    const chosen = box === this.selected;

    ctx.fillStyle = tint(box.color, dim ? 0.10 : 0.42);
    ctx.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
    ctx.strokeStyle = tint(chosen ? T.ACCENT : box.color, dim ? 0.3 : 0.95);
    ctx.lineWidth = (chosen ? 2.4 : 1.2) * ratio;
    ctx.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);

    // Tiers as lines across the box, the same information the 3D view draws
    // as shelves. Only when there is room to see them.
    if (box.tierCount > 1 && Math.abs(b.y - a.y) > 16 * ratio) {
      ctx.strokeStyle = tint(box.color, 0.5);
      ctx.lineWidth = ratio;
      ctx.beginPath();
      for (let tier = 1; tier < box.tierCount; tier++) {
        const at = a.y + (b.y - a.y) * tier / box.tierCount;
        ctx.moveTo(a.x, at);
        ctx.lineTo(b.x, at);
      }
      ctx.stroke();
    }

    const size = 11 * ratio;
    if (Math.abs(b.x - a.x) > size * 3 && Math.abs(b.y - a.y) > size * 1.6) {
      ctx.fillStyle = dim ? T.TEXT_FAINT : T.TEXT;
      ctx.font = `600 ${size}px ${T.FONT_FAMILY}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(M.short(box.name, 14), (a.x + b.x) / 2, (a.y + b.y) / 2,
                   Math.abs(b.x - a.x) - 6 * ratio);
    }
  }

  /** The room's name above its outline, with a count on the right.
   *
   *  Above rather than in the middle: the middle of a room is where the
   *  containers are once you have filled it in.
   */
  drawRoomLabel(room, dim) {
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const [x, y, w] = this.boxOf(room);
    const at = this.toScreen(x, y);
    const size = 12 * ratio;
    if (w * this.scale < size * 3) return;

    ctx.font = `600 ${size}px ${T.FONT_FAMILY}`;
    ctx.textBaseline = "alphabetic";
    ctx.textAlign = "left";
    ctx.fillStyle = dim ? T.TEXT_FAINT : T.TEXT;
    ctx.fillText(M.short(room.name, 22), at.x, at.y - 6 * ratio);

    const count = room.containers.length;
    if (count) {
      ctx.textAlign = "right";
      ctx.fillStyle = T.TEXT_FAINT;
      ctx.font = `${size * 0.9}px ${T.FONT_FAMILY}`;
      ctx.fillText(`${count}`, at.x + w * this.scale, at.y - 6 * ratio);
    }
  }

  drawGrips(room) {
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const size = HANDLE_DRAWN * ratio;
    for (const grip of this.gripsFor(room)) {
      const at = this.toScreen(grip.x, grip.y);
      ctx.fillStyle = T.ACCENT;
      ctx.strokeStyle = T.BG_APP;
      ctx.lineWidth = 1.5 * ratio;
      ctx.fillRect(at.x - size / 2, at.y - size / 2, size, size);
      ctx.strokeRect(at.x - size / 2, at.y - size / 2, size, size);
    }
  }

  drawVertices(room) {
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const radius = (HANDLE_DRAWN / 2 + 1) * ratio;
    for (const [x, y] of this.outline(room)) {
      const at = this.toScreen(x, y);
      ctx.beginPath();
      ctx.arc(at.x, at.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = T.SUCCESS;
      ctx.fill();
      ctx.strokeStyle = T.BG_APP;
      ctx.lineWidth = 1.5 * ratio;
      ctx.stroke();
    }
  }

  drawBoxGrips(box) {
    const room = this.roomOf(box);
    if (!room) return;
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const size = HANDLE_DRAWN * ratio;
    for (const [, fx, fy] of GRIP_SPOTS.slice(0, 4)) {
      const at = this.toScreen(box.x + room.x + box.w * fx,
                               box.y + room.y + box.h * fy);
      ctx.fillStyle = T.ACCENT;
      ctx.strokeStyle = T.BG_APP;
      ctx.lineWidth = 1.5 * ratio;
      ctx.fillRect(at.x - size / 2, at.y - size / 2, size, size);
      ctx.strokeRect(at.x - size / 2, at.y - size / 2, size, size);
    }
  }

  /** The corners placed so far, while a room is being drawn. */
  drawInProgress() {
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const points = this.drawing.points;
    if (!points.length) return;

    ctx.strokeStyle = T.ACCENT;
    ctx.lineWidth = 2 * ratio;
    ctx.beginPath();
    points.forEach(([x, y], at) => {
      const point = this.toScreen(x, y);
      if (at) ctx.lineTo(point.x, point.y); else ctx.moveTo(point.x, point.y);
    });
    if (this.drawing.hover) {
      const point = this.toScreen(...this.drawing.hover);
      ctx.lineTo(point.x, point.y);
    }
    ctx.stroke();

    for (const [x, y] of points) {
      const at = this.toScreen(x, y);
      ctx.beginPath();
      ctx.arc(at.x, at.y, 4 * ratio, 0, Math.PI * 2);
      ctx.fillStyle = T.ACCENT;
      ctx.fill();
    }

    // The first corner gets a ring once there are enough points to close, so
    // it is obvious that pressing it again finishes the room.
    if (points.length >= 3) {
      const at = this.toScreen(...points[0]);
      ctx.beginPath();
      ctx.arc(at.x, at.y, 9 * ratio, 0, Math.PI * 2);
      ctx.strokeStyle = T.SUCCESS;
      ctx.lineWidth = 2 * ratio;
      ctx.stroke();
    }
  }

  drawNewShape() {
    const { x, y, w, h } = this.drag.box;
    const points = presetPoints(this.preset, Math.abs(w), Math.abs(h));
    if (!points) return;
    const left = w < 0 ? x + w : x;
    const top = h < 0 ? y + h : y;
    this.path(points.map(([px, py]) => [px + left, py + top]));
    const ctx = this.context;
    ctx.fillStyle = tint(T.ACCENT, 0.18);
    ctx.fill();
    ctx.strokeStyle = tint(T.ACCENT, 0.9);
    ctx.lineWidth = 2 * (window.devicePixelRatio || 1);
    ctx.stroke();
  }

  drawNewBox() {
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const { x, y, w, h } = this.drag.box;
    const a = this.toScreen(Math.min(x, x + w), Math.min(y, y + h));
    const b = this.toScreen(Math.max(x, x + w), Math.max(y, y + h));
    ctx.fillStyle = tint(this.drag.fits ? T.ACCENT : T.DANGER, 0.25);
    ctx.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
    ctx.strokeStyle = tint(this.drag.fits ? T.ACCENT : T.DANGER, 0.9);
    ctx.lineWidth = 2 * ratio;
    ctx.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
  }

  roomOf(container) {
    for (const room of this.floor?.rooms ?? []) {
      if (room.containers.includes(container)) return room;
    }
    return null;
  }

  // -- pressing things ------------------------------------------------------

  pressed(event) {
    // Capture can throw when the pointer is not one the browser is tracking,
    // which happens for a synthesized event and, rarely, for a real one that
    // was already released. Losing capture makes a drag stop early; it does
    // not make it wrong, so it is not worth failing the press over.
    try {
      this.canvas.setPointerCapture(event.pointerId);
    } catch { /* carry on without it */ }
    this.pointers.set(event.pointerId, this.at(event));

    // Two fingers down means the camera, whatever the tool was doing. Anything
    // half-finished is abandoned rather than left to finish at a random place
    // when the second finger lifts.
    if (this.pointers.size === 2) {
      this.drag = null;
      this.pinch = this.pinchState();
      this.draw();
      return;
    }
    if (this.pointers.size > 2) return;

    const [cx, cy] = this.at(event);
    const middleOrSpace = event.button === 1 || this.spaceHeld;
    if (middleOrSpace) {
      this.drag = { kind: "pan", fromX: cx, fromY: cy,
                    panX: this.panX, panY: this.panY, pointer: event.pointerId };
      return;
    }

    event.preventDefault();
    const scene = this.toScene(cx, cy);

    if (this.mode === DRAW) return this.pressedWhileDrawing(scene);
    if (this.mode === SHAPE) {
      this.drag = { kind: "newShape", pointer: event.pointerId, moved: false,
                    box: { x: snap(scene[0]), y: snap(scene[1]), w: 0, h: 0 },
                    fromX: cx, fromY: cy };
      return;
    }
    if (this.mode === BOX) return this.pressedToAddBox(event, scene, cx, cy);

    this.pressedToSelect(event, scene, cx, cy);
  }

  pressedWhileDrawing(scene) {
    const point = [snap(scene[0]), snap(scene[1])];
    if (!this.drawing) this.drawing = { points: [], hover: null };

    const first = this.drawing.points[0];
    if (first && this.drawing.points.length >= 3) {
      const a = this.toScreen(...first);
      const b = this.toScreen(...point);
      const ratio = window.devicePixelRatio || 1;
      if (Math.hypot(a.x - b.x, a.y - b.y) <= CLOSE_DISTANCE * ratio) {
        this.finishDrawing();
        return;
      }
    }
    this.drawing.points.push(point);
    this.draw();
  }

  finishDrawing() {
    const points = this.drawing?.points ?? [];
    this.drawing = null;
    if (points.length < 3) { this.draw(); return; }

    // Stored relative to the room's own origin, which is what the save format
    // expects and what makes moving a room one number rather than all of them.
    const left = Math.min(...points.map(p => p[0]));
    const top = Math.min(...points.map(p => p[1]));
    // Named and colored exactly the way floor_view.py does it, so a room
    // made here and a room made there come out the same. copyName is not the
    // function for this: it always appends "copy", because its job is naming
    // a duplicate.
    const room = new M.Room({
      name: `Room ${this.floor.rooms.length + 1}`,
      color: T.SWATCHES[this.floor.rooms.length % T.SWATCHES.length],
      x: left, y: top,
      points: points.map(([x, y]) => [x - left, y - top]),
    });
    this.floor.rooms.push(room);
    this.setMode(SELECT);
    this.select(room);
    this.onChanged();
  }

  pressedToAddBox(event, scene, cx, cy) {
    const room = this.focused ?? this.roomAt(scene[0], scene[1]);
    if (!room) return;
    this.drag = {
      kind: "newBox", pointer: event.pointerId, room, moved: false, fits: false,
      box: { x: snap(scene[0]), y: snap(scene[1]), w: 0, h: 0 },
      fromX: cx, fromY: cy,
    };
  }

  pressedToSelect(event, scene, cx, cy) {
    const now = Date.now();
    const radius = this.grabRadius(event);

    // A selected room's own handles come first: they sit on its edge, and a
    // press there means the handle, not the room underneath it.
    if (this.selected instanceof M.Room && !this.focused && !this.selected.locked) {
      const room = this.selected;
      if (this.editMode === RESIZE) {
        for (const grip of this.gripsFor(room)) {
          const at = this.toScreen(grip.x, grip.y);
          if (Math.hypot(at.x - cx, at.y - cy) <= radius) {
            this.drag = { kind: "stretch", pointer: event.pointerId, room,
                          grip: grip.name, start: this.boxOf(room), moved: false };
            return;
          }
        }
      }
      if (this.editMode === VERTICES) {
        const corners = this.outline(room);
        for (let index = 0; index < corners.length; index++) {
          const at = this.toScreen(...corners[index]);
          if (Math.hypot(at.x - cx, at.y - cy) > radius) continue;
          // A second press on the same corner takes it away. Three corners is
          // the fewest that still encloses an area, so it can refuse.
          if (this.lastPress.thing === corners[index].join()
              && now - this.lastPress.at < DOUBLE_GAP) {
            if (room.removePoint(index)) this.onChanged();
            this.lastPress = { at: 0, thing: null };
            this.draw();
            return;
          }
          this.lastPress = { at: now, thing: corners[index].join() };
          this.drag = { kind: "vertex", pointer: event.pointerId, room, index,
                        moved: false };
          return;
        }

        // Not on a corner but inside the room: add one on the nearest edge.
        if (M.pointInPolygon(this.outline(room), scene[0], scene[1])) {
          const at = room.insertPointOnNearestEdge(scene[0] - room.x,
                                                   scene[1] - room.y);
          if (at !== null) this.onChanged();
          this.draw();
          return;
        }
      }
    }

    // A selected container's corners, for resizing it.
    if (this.selected instanceof M.Container) {
      const box = this.selected;
      const room = this.roomOf(box);
      if (room) {
        for (const [name, fx, fy] of GRIP_SPOTS.slice(0, 4)) {
          const at = this.toScreen(box.x + room.x + box.w * fx,
                                   box.y + room.y + box.h * fy);
          if (Math.hypot(at.x - cx, at.y - cy) <= radius) {
            this.drag = { kind: "boxStretch", pointer: event.pointerId, box, room,
                          grip: name, start: [box.x, box.y, box.w, box.h],
                          moved: false };
            return;
          }
        }
      }
    }

    const room = this.roomAt(scene[0], scene[1]);

    // Inside a focused room, a press is about its containers.
    if (this.focused) {
      const box = this.containerAt(this.focused, scene[0], scene[1]);
      if (box) {
        this.select(box);
        this.drag = { kind: "moveBox", pointer: event.pointerId, box,
                      room: this.focused, moved: false,
                      fromX: scene[0], fromY: scene[1],
                      startX: box.x, startY: box.y };
        return;
      }
      if (room !== this.focused) this.stepInto(null);
      this.select(null);
      return;
    }

    if (!room) {
      this.select(null);
      this.lastPress = { at: 0, thing: null };
      return;
    }

    // Two presses on the same room steps inside it.
    if (this.lastPress.thing === room.id && now - this.lastPress.at < DOUBLE_GAP) {
      this.lastPress = { at: 0, thing: null };
      this.stepInto(room);
      return;
    }
    this.lastPress = { at: now, thing: room.id };
    this.select(room);

    if (!room.locked && this.editMode === MOVE) {
      this.drag = { kind: "moveRoom", pointer: event.pointerId, room, moved: false,
                    fromX: scene[0], fromY: scene[1],
                    startX: room.x, startY: room.y };
    }
  }

  // -- moving ---------------------------------------------------------------

  moved(event) {
    if (this.pointers.has(event.pointerId)) {
      this.pointers.set(event.pointerId, this.at(event));
    }

    if (this.pointers.size === 2 && this.pinch) {
      this.cameraMoved = true;
      const now = this.pinchState();
      const factor = now.spread / (this.pinch.spread || 1);
      this.scale = this.clampZoom(this.scale * factor);
      this.panX = now.x - (this.pinch.x - this.panX) * (this.scale / this.pinch.scale);
      this.panY = now.y - (this.pinch.y - this.panY) * (this.scale / this.pinch.scale);
      this.pinch = { ...now, scale: this.scale };
      this.draw();
      return;
    }

    if (this.mode === DRAW && this.drawing) {
      const [sx, sy] = this.toScene(...this.at(event));
      this.drawing.hover = [snap(sx), snap(sy)];
      this.draw();
      return;
    }

    if (!this.drag || event.pointerId !== this.drag.pointer) return;
    const [cx, cy] = this.at(event);
    const scene = this.toScene(cx, cy);

    if (this.drag.kind === "pan") {
      this.cameraMoved = true;
      this.panX = this.drag.panX + (cx - this.drag.fromX);
      this.panY = this.drag.panY + (cy - this.drag.fromY);
      this.draw();
      return;
    }

    if (!this.drag.moved) {
      // A drag that recorded where it started has to travel a little before
      // it counts, because a finger never holds still and without this every
      // tap nudges whatever it landed on.
      //
      // A drag that did not record one is a handle, and a handle has no slop.
      // The press already landed on a target the size of a fingernail, so
      // there is nothing left to protect against. This used to fall through
      // to the same threshold with a made-up distance of DRAG_SLOP + 1, which
      // is five, and the threshold is four times the pixel ratio, which is
      // eight on any retina screen. So every resize handle and every corner
      // silently did nothing on exactly the machines most people have.
      if (this.drag.fromX === undefined) {
        this.drag.moved = true;
      } else {
        const travelled = Math.hypot(cx - this.drag.fromX, cy - this.drag.fromY);
        if (travelled < DRAG_SLOP * (window.devicePixelRatio || 1)) return;
        this.drag.moved = true;
      }
    }

    switch (this.drag.kind) {
      case "newShape": this.dragNewShape(scene); break;
      case "newBox": this.dragNewBox(scene); break;
      case "moveRoom": this.dragRoom(scene); break;
      case "stretch": this.dragStretch(scene); break;
      case "vertex": this.dragVertex(scene); break;
      case "moveBox": this.dragBox(scene); break;
      case "boxStretch": this.dragBoxStretch(scene); break;
    }
    this.draw();
  }

  dragNewShape([sx, sy]) {
    this.drag.box.w = snap(sx) - this.drag.box.x;
    this.drag.box.h = snap(sy) - this.drag.box.y;
  }

  dragNewBox([sx, sy]) {
    const box = this.drag.box;
    box.w = snap(sx) - box.x;
    box.h = snap(sy) - box.y;
    const room = this.drag.room;
    this.drag.fits = M.roomContainsRect(
      room, Math.min(box.x, box.x + box.w) - room.x,
      Math.min(box.y, box.y + box.h) - room.y,
      Math.abs(box.w), Math.abs(box.h));
  }

  dragRoom([sx, sy]) {
    this.drag.room.x = snap(this.drag.startX + (sx - this.drag.fromX));
    this.drag.room.y = snap(this.drag.startY + (sy - this.drag.fromY));
  }

  /** Stretch the whole room by one of the eight grips.
   *
   *  The opposite side stays where it is, which is what a resize handle has
   *  meant since the first drawing program. A minimum of one grid square
   *  stops a room being squashed to nothing by a slip of the hand, and
   *  nothing can be turned inside out.
   */
  dragStretch([sx, sy]) {
    const [x, y, w, h] = this.drag.start;
    const grip = this.drag.grip;
    let left = x, top = y, right = x + w, bottom = y + h;

    if (grip.includes("w")) left = Math.min(snap(sx), right - T.GRID_SIZE);
    if (grip.includes("e")) right = Math.max(snap(sx), left + T.GRID_SIZE);
    if (grip.includes("n")) top = Math.min(snap(sy), bottom - T.GRID_SIZE);
    if (grip.includes("s")) bottom = Math.max(snap(sy), top + T.GRID_SIZE);

    const room = this.drag.room;
    room.resizeTo(right - left, bottom - top, 0, 0);
    room.x = left;
    room.y = top;
    // Containers keep their place in the room rather than scaling with it,
    // and some of them will not fit any more. Pull those back inside instead
    // of leaving a shelf sticking through a wall.
    for (const box of room.containers) M.fitContainer(room, box);
  }

  dragVertex([sx, sy]) {
    const room = this.drag.room;
    room.points[this.drag.index] = [snap(sx) - room.x, snap(sy) - room.y];
    for (const box of room.containers) M.fitContainer(room, box);
  }

  dragBox([sx, sy]) {
    const { box, room } = this.drag;
    const [x, y] = M.fitInRoom(room,
      snap(this.drag.startX + (sx - this.drag.fromX)),
      snap(this.drag.startY + (sy - this.drag.fromY)),
      box.w, box.h, [this.drag.startX, this.drag.startY, box.w, box.h]);
    box.x = x;
    box.y = y;
  }

  dragBoxStretch([sx, sy]) {
    const { box, room, grip } = this.drag;
    const [ox, oy, ow, oh] = this.drag.start;
    let left = ox, top = oy, right = ox + ow, bottom = oy + oh;
    const wantedX = snap(sx) - room.x;
    const wantedY = snap(sy) - room.y;

    if (grip.includes("w")) left = Math.min(wantedX, right - M.MIN_CONTAINER_SIZE);
    if (grip.includes("e")) right = Math.max(wantedX, left + M.MIN_CONTAINER_SIZE);
    if (grip.includes("n")) top = Math.min(wantedY, bottom - M.MIN_CONTAINER_SIZE);
    if (grip.includes("s")) bottom = Math.max(wantedY, top + M.MIN_CONTAINER_SIZE);

    // Only take the new size if it actually fits. Refusing is better than
    // silently moving the box somewhere else while somebody is resizing it.
    if (M.roomContainsRect(room, left, top, right - left, bottom - top)) {
      box.x = left; box.y = top;
      box.w = right - left; box.h = bottom - top;
    }
  }

  // -- letting go -----------------------------------------------------------

  released(event) {
    this.pointers.delete(event.pointerId);
    try {
      if (this.canvas.hasPointerCapture(event.pointerId)) {
        this.canvas.releasePointerCapture(event.pointerId);
      }
    } catch { /* see pressed() */ }
    if (this.pointers.size < 2) this.pinch = null;

    if (!this.drag || event.pointerId !== this.drag.pointer) return;
    const finished = this.drag;
    this.drag = null;

    if (finished.kind === "newShape") this.finishShape(finished);
    else if (finished.kind === "newBox") this.finishBox(finished);
    else if (finished.moved) this.onChanged();

    this.draw();
  }

  finishShape(drag) {
    const { x, y, w, h } = drag.box;
    // A press without a drag still makes a room, at a sensible default size.
    // Requiring a drag means a tap does nothing, and a tap doing nothing reads
    // as the button being broken.
    const wide = Math.abs(w) < T.GRID_SIZE ? DEFAULT_SHAPE : Math.abs(w);
    const high = Math.abs(h) < T.GRID_SIZE ? DEFAULT_SHAPE : Math.abs(h);
    const points = presetPoints(this.preset, wide, high);
    if (!points) return;

    // "Room 3", not "Rectangle 3". A preset is where a shape starts, not
    // what it is: the moment it exists you can drag any corner of it, so
    // naming it after the button would be a lie a week later. The desktop
    // sends presets through the same naming as the freehand tool for the
    // same reason.
    const room = new M.Room({
      name: `Room ${this.floor.rooms.length + 1}`,
      color: T.SWATCHES[this.floor.rooms.length % T.SWATCHES.length],
      x: w < 0 ? x + w : x, y: h < 0 ? y + h : y,
      points,
    });
    this.floor.rooms.push(room);
    this.setMode(SELECT);
    this.select(room);
    this.onChanged();
  }

  finishBox(drag) {
    const { box, room } = drag;
    let left = Math.min(box.x, box.x + box.w) - room.x;
    let top = Math.min(box.y, box.y + box.h) - room.y;
    let wide = Math.max(Math.abs(box.w), M.MIN_CONTAINER_SIZE);
    let high = Math.max(Math.abs(box.h), M.MIN_CONTAINER_SIZE);

    // Nudge it somewhere legal rather than refusing. Somebody who dragged a
    // rectangle wants a container; landing slightly over a wall is a slip,
    // not a decision.
    [left, top, wide, high] = M.nearestFit(room, left, top, wide, high);
    if (!M.roomContainsRect(room, left, top, wide, high)) return;

    const made = new M.Container({
      name: `Container ${room.containers.length + 1}`,
      color: T.SWATCHES[(room.containers.length + 2) % T.SWATCHES.length],
      x: left, y: top, w: wide, h: high,
    });
    room.containers.push(made);
    this.setMode(SELECT);
    if (!this.focused) this.stepInto(room);
    this.select(made);
    this.onChanged();
  }

  // -- the camera, by wheel and by keys -------------------------------------

  wheeled(event) {
    event.preventDefault();
    const [cx, cy] = this.at(event);
    // ctrl+wheel is a pinch on a trackpad, and a plain wheel is a scroll. Both
    // mean zoom here, because there is nothing else for a wheel to do on a
    // canvas that pans by dragging.
    this.zoomAt(cx, cy, Math.exp(-event.deltaY * 0.0015));
  }

  keyDown(event) {
    if (event.target instanceof HTMLInputElement) return;
    if (event.code === "Space") { this.spaceHeld = true; return; }
    if (event.key === "Escape") {
      if (this.drawing) { this.drawing = null; this.setMode(SELECT); return; }
      if (this.mode !== SELECT) { this.setMode(SELECT); return; }
      if (this.focused) { this.stepInto(null); return; }
      this.select(null);
      return;
    }
    if (event.key === "Enter" && this.drawing) {
      this.finishDrawing();
      return;
    }
  }

  keyUp(event) {
    if (event.code === "Space") this.spaceHeld = false;
  }

  pinchState() {
    const [a, b] = [...this.pointers.values()];
    return {
      x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2,
      spread: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1,
      scale: this.scale,
    };
  }
}

/** A color at a given opacity, as a CSS rgba string. */
function tint(hex, alpha) {
  const [r, g, b] = [1, 3, 5].map(at => parseInt(hex.slice(at, at + 2), 16));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** The points for one of the presets, by name. Null for an unknown one.
 *
 *  ROOM_PRESETS in model.js is the list, and it is the list the toolbar is
 *  built from too, so adding a shape there puts a button on screen and makes
 *  it drawable without touching anything here.
 */
export function presetPoints(name, width, height) {
  const found = M.ROOM_PRESETS.find(([label]) => label === name);
  return found ? found[1](width, height) : null;
}

/**
 * room.js
 * =======
 *
 * The inside of one room, drawn on a canvas, with containers you can pick up
 * and move. The browser's answer to room_view_3d.py.
 *
 * All the geometry lives in iso.js and all the rules about where a container
 * may stand live in model.js. What is left here is the part that is actually
 * about a canvas: sizing it, ordering the polygons, turning a finger or a
 * mouse into a position on the floor, and putting the ink down.
 *
 * WHAT THE DRAW ORDER HAS TO GET RIGHT
 * ------------------------------------
 * Walls and boxes are sorted together in one list, not walls first and boxes
 * after. Drawing all the walls first is the obvious version and it is wrong:
 * a container standing against the back wall belongs in front of it, and a
 * container by the near wall belongs behind that one. They interleave, so
 * they sort together.
 *
 * The order itself comes from iso.paintOrder, which does not use a depth
 * number at all. It sorts on "A ends before B starts", which is the thing that
 * is actually true about a wall and a box, and it is worth reading the comment
 * over it before touching any of this: the two obvious shortcuts both draw a
 * correct picture in one room and a wrong one in the next.
 *
 * PICKING THINGS UP
 * -----------------
 * A click is tested against a box's SILHOUETTE, the six-sided shape you see,
 * not against its footprint on the floor. The floor point under a click on a
 * tall cabinet's lid is somewhere behind the cabinet, so testing the
 * footprint ignores exactly the part of a tall box that people aim at.
 *
 * Dragging moves by the difference between where the pointer is now and where
 * it started, rather than putting the box under the pointer. Put the box under
 * the pointer and it jumps the moment you grab it by a corner.
 */
import * as M from "./model.js";
import * as iso from "./iso.js";
import * as T from "./theme.js";

// How far a pointer may travel before a press counts as a drag rather than a
// tap. A finger never holds perfectly still, and without this every tap on a
// phone nudges whatever it landed on.
const DRAG_SLOP = 3;

export class RoomView {
  /**
   * @param canvas   the <canvas> to draw in
   * @param onChanged  called after a container has been moved, so the app can
   *                   save. Not called while the drag is still in progress.
   * @param onSelected called when the selection changes
   */
  constructor(canvas, { onChanged = () => {}, onSelected = () => {} } = {}) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.onChanged = onChanged;
    this.onSelected = onSelected;

    this.profile = null;
    this.room = null;
    this.selectedId = null;

    this.scale = 1;
    this.originX = 0;
    this.originY = 0;
    this.drag = null;

    this.watcher = new ResizeObserver(() => this.resize());
    this.watcher.observe(canvas.parentElement ?? canvas);

    canvas.addEventListener("pointerdown", event => this.pressed(event));
    canvas.addEventListener("pointermove", event => this.moved(event));
    canvas.addEventListener("pointerup", event => this.released(event));
    canvas.addEventListener("pointercancel", event => this.released(event));
  }

  stop() {
    this.watcher.disconnect();
  }

  /** What to draw. Pass null for the room to show nothing. */
  show(profile, room) {
    this.profile = profile;
    this.room = room;
    this.selectedId = null;
    this.resize();
  }

  get selected() {
    return this.room?.containers.find(c => c.id === this.selectedId) ?? null;
  }

  select(id) {
    if (this.selectedId === id) return;
    this.selectedId = id;
    this.onSelected(this.selected);
    this.draw();
  }

  // -- sizing ---------------------------------------------------------------

  /** Match the canvas to its box and work out where to put the camera.
   *
   *  A canvas has two sizes, the one CSS gives it and the one its bitmap is,
   *  and letting them differ is why canvas drawings look soft. The bitmap is
   *  set to the CSS size times the device pixel ratio, which on a phone is
   *  two or three.
   */
  resize() {
    const box = this.canvas.getBoundingClientRect();
    if (!box.width || !box.height) return;

    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(box.width * ratio);
    this.canvas.height = Math.round(box.height * ratio);

    if (this.room?.points.length >= 3) {
      const tallest = Math.max(0,
        ...this.room.containers.map(container => container.height));
      const [left, top, wide, high] =
        iso.roomBounds(this.room.points, iso.WALL_HEIGHT, tallest);

      // A tenth of the room's height of headroom, for the floating label over
      // whichever container is selected. Proportional rather than a fixed
      // number of pixels, because it has to survive both a phone and a
      // 4K monitor.
      const margin = high * 0.12;
      this.scale = Math.min(this.canvas.width / wide,
                            this.canvas.height / (high + margin)) * 0.92;
      this.originX = (this.canvas.width - wide * this.scale) / 2
                     - left * this.scale;
      this.originY = (this.canvas.height - (high + margin) * this.scale) / 2
                     - (top - margin) * this.scale;
    }
    this.draw();
  }

  /** A screen point from iso.project, in canvas pixels. */
  toCanvas(point) {
    return { x: point.x * this.scale + this.originX,
             y: point.y * this.scale + this.originY };
  }

  /** A pointer event, as a point on the room's floor. */
  floorUnder(event) {
    const box = this.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const x = (event.clientX - box.left) * ratio;
    const y = (event.clientY - box.top) * ratio;
    return iso.floorAt({ x: (x - this.originX) / this.scale,
                         y: (y - this.originY) / this.scale });
  }

  // -- the order things are drawn in ----------------------------------------

  /** Every wall and every container, in the order they have to be drawn.
   *
   *  Walls and boxes go in ONE list. Drawing all the walls first is the
   *  obvious version and it is wrong for any room that is not a rectangle: the
   *  back wall of an L's foot stands in front of whatever is in the other arm,
   *  and drawing it first leaves a cabinet sitting on top of a wall it is
   *  standing behind.
   */
  layers() {
    if (!this.room) return [];

    const things = [];
    for (const wall of iso.farWalls(this.room.points)) {
      things.push({ kind: "wall", wall, footprint: iso.wallFootprint(wall) });
    }
    for (const container of this.room.containers) {
      things.push({ kind: "box", container,
                    footprint: iso.boxFootprint(container.x, container.y,
                                                container.w, container.h) });
    }
    return iso.paintOrder(things);
  }

  // -- drawing --------------------------------------------------------------

  draw() {
    const ctx = this.context;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = T.CANVAS_BG;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    if (!this.room || this.room.points.length < 3) return;

    ctx.setTransform(this.scale, 0, 0, this.scale, this.originX, this.originY);
    ctx.lineJoin = "round";

    this.drawFloor();
    for (const layer of this.layers()) {
      if (layer.kind === "wall") this.drawWall(layer.wall);
      else this.drawBox(layer.container);
    }

    const chosen = this.selected;
    if (chosen) this.drawLabel(chosen);
  }

  /** One polygon, in room coordinates. Line widths are divided by the scale
   *  so a hairline stays a hairline however far the room is zoomed. */
  fill(shape, color, stroke = null, width = 1.2) {
    const ctx = this.context;
    ctx.beginPath();
    shape.forEach((point, at) =>
      at ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
    ctx.closePath();
    if (color) {
      ctx.fillStyle = color;
      ctx.fill();
    }
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width / this.scale;
      ctx.stroke();
    }
  }

  drawFloor() {
    const color = this.room.color;
    this.fill(iso.polygon(this.room.points.map(([x, y]) => [x, y, 0])),
              iso.mix(color, T.CANVAS_BG, 0.74), iso.shade(color, -0.05), 1.6);
  }

  drawWall([a, b]) {
    const color = this.room.color;
    const face = iso.shade(color, -0.12);
    // Filled and stroked in the same color, so a wall meeting its neighbour
    // at a corner reads as one surface instead of showing a seam.
    this.fill(iso.polygon([[a[0], a[1], 0], [b[0], b[1], 0],
                           [b[0], b[1], iso.WALL_HEIGHT],
                           [a[0], a[1], iso.WALL_HEIGHT]]), face, face);

    // Then the top edge only, lighter, which is what gives a wall a lip and
    // stops it reading as a flat ribbon lying on the floor.
    const ctx = this.context;
    const top = [iso.project(a[0], a[1], iso.WALL_HEIGHT),
                 iso.project(b[0], b[1], iso.WALL_HEIGHT)];
    ctx.beginPath();
    ctx.moveTo(top[0].x, top[0].y);
    ctx.lineTo(top[1].x, top[1].y);
    ctx.strokeStyle = iso.shade(color, 0.18);
    ctx.lineWidth = 1.4 / this.scale;
    ctx.stroke();
  }

  /** One container as a solid box.
   *
   *  Three faces, never six. From a fixed camera the back, the bottom and the
   *  far side can never be seen, so they are never drawn, and that is most of
   *  why this is cheap enough to redraw on every frame of a drag.
   */
  drawBox(container) {
    const { x, y, w, h, height, color } = container;
    const d = h;                       // h is the container's DEPTH on the floor

    this.fill(iso.leftFace(x, y, w, d, height),
              iso.shade(color, iso.LEFT_LIGHT),
              iso.shade(color, iso.LEFT_LIGHT - 0.3));
    this.fill(iso.rightFace(x, y, w, d, height),
              iso.shade(color, iso.RIGHT_LIGHT),
              iso.shade(color, iso.RIGHT_LIGHT - 0.3));
    this.fill(iso.topFace(x, y, w, d, height),
              iso.shade(color, iso.TOP_LIGHT),
              iso.shade(color, iso.TOP_LIGHT - 0.3));

    // Tiers as shelf lines across the two faces you can see, meeting at the
    // near vertical edge so a shelf reads as going round the corner. The count
    // is already in the data, so this costs a few strokes and turns "3 tiers"
    // from a number in a panel into something you can look at.
    const ctx = this.context;
    if (container.tierCount > 1 && height > 20) {
      ctx.strokeStyle = iso.mix(color, "#000000", 0.55);
      ctx.lineWidth = 1 / this.scale;
      for (let tier = 1; tier < container.tierCount; tier++) {
        const z = height * tier / container.tierCount;
        const left = iso.project(x, y + d, z);
        const corner = iso.project(x + w, y + d, z);
        const right = iso.project(x + w, y, z);
        ctx.beginPath();
        ctx.moveTo(left.x, left.y);
        ctx.lineTo(corner.x, corner.y);
        ctx.lineTo(right.x, right.y);
        ctx.stroke();
      }
    }

    this.drawTierContents(container);

    if (container.id === this.selectedId) {
      this.fill(iso.boxOutline(x, y, w, d, height), null, T.ACCENT, 2.4);
    }
  }

  /** What is on each shelf, as a row of colored marks along the tier line.
   *
   *  The reason tiers are worth having at all. A number in a panel saying
   *  "4 tiers" tells you the shelf is divided up; seeing the sockets sitting
   *  on the second one tells you where to reach. One mark per item on that
   *  tier, in the item's own color, so a shelf you have seen once is
   *  recognisable from across the room.
   *
   *  Loose things, the ones on no tier at all, are drawn along the bottom
   *  edge. They are not on a shelf and pretending they are on the first one
   *  would be a lie about the only thing this drawing is for.
   */
  drawTierContents(container) {
    if (!this.profile) return;
    const { x, y, w, h: d, height } = container;
    const ctx = this.context;
    if (height < 12 || w < 24) return;    // no room to draw anything readable

    const shelf = height / Math.max(container.tierCount, 1);
    // Tall enough to see and short enough to sit under the shelf above.
    const tall = Math.min(shelf * 0.55, height * 0.16, 9);
    const inset = Math.min(w * 0.05, 4);

    // Tier 0 first, so a container with no tiers at all still shows what is
    // in it along its foot.
    for (const tier of [0, ...container.tiers()]) {
      const onIt = this.profile.contentsOf(container.id, tier);
      if (!onIt.length) continue;

      // Tier 1 is the lowest shelf, and things rest ON a shelf rather than
      // hanging under it, so each row starts at its own shelf line and goes
      // up. Loose things sit on the floor of the container.
      const z = tier === 0 ? 0 : shelf * tier;
      if (z + tall > height) continue;

      // Sized to fill the width between them, so two things on a shelf are
      // two wide blocks and six are six narrow ones. A fixed width looked
      // like grit on the edge of the box at any real container size.
      const across = w - inset * 2;
      const step = across / onIt.length;
      const wide = Math.max(step * 0.78, 1.5);

      onIt.forEach(([item], at) => {
        const left = x + inset + at * step;
        // Against the near-left face, which is the brightest of the two you
        // can see, so the marks read against it instead of disappearing into
        // a shadowed side.
        const corners = [
          iso.project(left, y + d, z),
          iso.project(left + wide, y + d, z),
          iso.project(left + wide, y + d, z + tall),
          iso.project(left, y + d, z + tall),
        ];
        ctx.beginPath();
        corners.forEach((point, index) =>
          index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
        ctx.closePath();
        ctx.fillStyle = iso.shade(item.color, 0.08);
        ctx.fill();
        ctx.strokeStyle = iso.shade(item.color, -0.35);
        ctx.lineWidth = 0.8 / this.scale;
        ctx.stroke();
      });
    }
  }

  /** The name of the selected container, floating over it.
   *
   *  Drawn with the transform reset, so the text sits flat on the screen
   *  rather than being skewed into the projection. Slanting a label to match
   *  the floor looks clever in a screenshot and is unreadable in use, which is
   *  why isometric games keep their text upright too.
   */
  drawLabel(container) {
    const ctx = this.context;
    const ratio = window.devicePixelRatio || 1;
    const above = iso.project(container.x + container.w / 2,
                              container.y + container.h / 2,
                              container.height + (container.w + container.h) / 4 + 16);
    const at = this.toCanvas(above);

    const piles = this.itemsIn(container);
    const total = piles.reduce((sum, [, quantity]) => sum + quantity, 0);
    const kinds = new Set(piles.map(([item]) => item.id)).size;
    const line = kinds
      ? `${container.name}  ·  ${total} in ${kinds} thing${kinds === 1 ? "" : "s"}`
      : container.name;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.font = `600 ${13 * ratio}px ${T.FONT_FAMILY}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    const wide = ctx.measureText(line).width + 18 * ratio;
    const high = 24 * ratio;
    ctx.fillStyle = T.BG_CARD;
    ctx.strokeStyle = T.BORDER_LIGHT;
    ctx.lineWidth = ratio;
    ctx.beginPath();
    ctx.roundRect(at.x - wide / 2, at.y - high / 2, wide, high, 6 * ratio);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = T.TEXT;
    ctx.fillText(line, at.x, at.y);
  }

  /** Every pile in this container, as [item, quantity, tier].
   *
   *  Profile.contentsOf rather than a walk of its own, so this and the panel
   *  and the items screen all answer the question the same way. Three
   *  different walks over the same placements is three chances to disagree
   *  about what is in a drawer.
   */
  itemsIn(container) {
    return this.profile?.contentsOf(container.id) ?? [];
  }

  // -- picking things up ----------------------------------------------------

  /** The container under a floor-and-screen position, nearest first.
   *
   *  Tested against the silhouette rather than the footprint, and walked in
   *  reverse draw order so that when two boxes overlap on screen the one in
   *  front is the one you get.
   */
  containerAt(event) {
    const box = this.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const point = {
      x: ((event.clientX - box.left) * ratio - this.originX) / this.scale,
      y: ((event.clientY - box.top) * ratio - this.originY) / this.scale,
    };

    const boxes = this.layers().filter(layer => layer.kind === "box");
    for (let at = boxes.length - 1; at >= 0; at--) {
      const container = boxes[at].container;
      const shape = iso.boxOutline(container.x, container.y,
                                   container.w, container.h, container.height);
      if (iso.insideShape(shape, point)) return container;
    }
    return null;
  }

  pressed(event) {
    if (!this.room || this.room.locked) return;
    const container = this.containerAt(event);
    this.select(container?.id ?? null);
    if (!container) return;

    this.canvas.setPointerCapture(event.pointerId);
    const [fx, fy] = this.floorUnder(event);
    this.drag = {
      id: container.id, pointer: event.pointerId,
      fromX: fx, fromY: fy,
      startX: container.x, startY: container.y,
      moved: false, screenX: event.clientX, screenY: event.clientY,
    };
    event.preventDefault();
  }

  moved(event) {
    if (!this.drag || event.pointerId !== this.drag.pointer) return;

    if (!this.drag.moved) {
      const travelled = Math.hypot(event.clientX - this.drag.screenX,
                                   event.clientY - this.drag.screenY);
      if (travelled < DRAG_SLOP) return;
      this.drag.moved = true;
    }

    const container = this.room.containers.find(c => c.id === this.drag.id);
    if (!container) return;

    const [fx, fy] = this.floorUnder(event);
    const wanted = [this.drag.startX + (fx - this.drag.fromX),
                    this.drag.startY + (fy - this.drag.fromY)];

    // fitInRoom with a `stay` is what makes a container slide along a wall
    // instead of stopping dead or jumping somewhere legal. The rectangle it
    // is told to stay near is where the drag STARTED, not where the container
    // is this frame, so a drag that wanders outside and comes back lands where
    // it was aimed rather than wherever the last legal frame left it.
    const [x, y] = M.fitInRoom(this.room, wanted[0], wanted[1],
                               container.w, container.h,
                               [this.drag.startX, this.drag.startY,
                                container.w, container.h]);
    if (x === container.x && y === container.y) return;
    container.x = x;
    container.y = y;
    this.draw();
  }

  released(event) {
    if (!this.drag || event.pointerId !== this.drag.pointer) return;
    const shifted = this.drag.moved;
    this.drag = null;
    if (this.canvas.hasPointerCapture(event.pointerId)) {
      this.canvas.releasePointerCapture(event.pointerId);
    }
    // Saved once, at the end. Saving on every frame of a drag would write a
    // hundred times for one movement and fill the daily snapshot with the
    // middle of it.
    if (shifted) this.onChanged();
  }
}

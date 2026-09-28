/**
 * iso.js
 * ======
 *
 * The isometric projection, and the geometry that goes with it. The twin of
 * iso.py, minus the painting: this file works out shapes and orders, and
 * room.js turns them into strokes on a canvas.
 *
 * WHAT "3D" MEANS HERE
 * --------------------
 * Nothing in this app is really three dimensional. There is no 3D engine, no
 * camera, no depth buffer, and no dependency. There is one function:
 *
 *     screenX = (x - y) * cos(30)
 *     screenY = (x + y) * sin(30) - z
 *
 * Feed it a point on the floor and a height and it hands back a point on the
 * screen. That is the whole illusion. Everything else here is either building
 * polygons through that function or working out what order to draw them in.
 *
 * WHY IT IS INVERTIBLE, AND WHY THAT MATTERS
 * ------------------------------------------
 * Drawing is half of it. Dragging a container needs the other direction: a
 * point on the screen back to a point on the floor. Two equations, two
 * unknowns, so it solves exactly:
 *
 *     x = (sx / cos(30) + sy / sin(30)) / 2
 *     y = (sy / sin(30) - sx / cos(30)) / 2
 *
 * That is floorAt below. It assumes z is zero, which is true of anything
 * standing on the floor, and containers always are. Without that assumption a
 * screen point would be ambiguous, a spot on the floor or a spot on top of a
 * box, and dragging would need a real 3D pick.
 *
 * TWO KINDS OF POINT, AND THEY LOOK DIFFERENT ON PURPOSE
 * ------------------------------------------------------
 * A point on the FLOOR is an array, [x, y], which is how model.js writes the
 * corners of a room and what the save file holds.
 *
 * A point on the SCREEN is an object, { x, y }.
 *
 * Mixing the two up is the easiest mistake to make in a file like this and the
 * hardest to see afterwards, because both are just a pair of numbers and the
 * picture that comes out is merely wrong rather than broken. Different shapes
 * mean the mistake is a crash or an undefined instead.
 */

export const COS30 = Math.cos(Math.PI / 6);
export const SIN30 = Math.sin(Math.PI / 6);

// How the three visible faces of a box are tinted. Positive mixes toward
// white, negative toward black. The top catching the most light is what makes
// a flat polygon read as a solid object; take these away and the whole picture
// collapses into a pattern. Light comes from the upper left, so the left face
// is the brighter of the two sides.
export const TOP_LIGHT = 0.26;
export const LEFT_LIGHT = -0.16;
export const RIGHT_LIGHT = -0.32;

// Walls are drawn short on purpose. Full height walls stand taller than the
// furniture and hide the very thing you opened the room to look at.
export const WALL_HEIGHT = 34;

/** A point on the floor, at height z, as a point on the screen. */
export function project(x, y, z = 0) {
  return { x: (x - y) * COS30, y: (x + y) * SIN30 - z };
}

/** A point on the screen, back to the point on the floor under it. */
export function floorAt(point) {
  const across = point.x / COS30;
  const down = point.y / SIN30;
  return [(across + down) / 2, (down - across) / 2];
}

/** How far from the camera. Bigger is nearer, so sort ascending. */
export function depth(x, y) {
  return x + y;
}

// ---------------------------------------------------------------------------
// COLOR
// ---------------------------------------------------------------------------

/** Blend one hex color towards another. Returns "#rrggbb".
 *
 *  Hex out rather than rgb() so the result can go straight back in, which
 *  shade() below relies on and a caller stacking two blends would too.
 */
export function mix(hex, towards, amount) {
  const parse = value => [1, 3, 5].map(at => parseInt(value.slice(at, at + 2), 16));
  const [r1, g1, b1] = parse(hex);
  const [r2, g2, b2] = parse(towards);
  const blend = (from, to) =>
    Math.round(from + (to - from) * amount).toString(16).padStart(2, "0");
  return `#${blend(r1, r2)}${blend(g1, g2)}${blend(b1, b2)}`;
}

/** One face's color. Positive is lit, negative is in shadow. */
export function shade(hex, amount) {
  return amount >= 0 ? mix(hex, "#ffffff", amount) : mix(hex, "#000000", -amount);
}

// ---------------------------------------------------------------------------
// SHAPES
//
// Each of these returns a polygon in screen coordinates rather than drawing
// it. Keeping the shape and the painting apart means the same functions answer
// "where would this be drawn?", which is how hit testing works further down.
// ---------------------------------------------------------------------------

/** A list of [x, y, z] floor points as a list of screen points. */
export function polygon(corners) {
  return corners.map(([x, y, z = 0]) => project(x, y, z));
}

export function topFace(x, y, w, d, height) {
  return polygon([[x, y, height], [x + w, y, height],
                  [x + w, y + d, height], [x, y + d, height]]);
}

// WHICH TWO SIDES YOU CAN ACTUALLY SEE
//
// Worth working out rather than guessing, because guessing wrong leaves a hole
// in the box that is easy to miss in a screenshot and obvious in use.
//
// A point is nearer the camera the bigger its x + y, so the nearest vertical
// edge of a box is the one at (x+w, y+d). The two faces you can see are the
// two that touch that edge:
//
//     the +y face (y = y+d, x varies)  lands on the LEFT of the screen
//     the +x face (x = x+w, y varies)  lands on the RIGHT
//
// The other two face away and are never drawn. The names say where a face
// APPEARS, not which axis it sits on, because where it appears is what you are
// looking at when something is wrong.

/** The side facing down and left on screen: the +y wall of the box. */
export function leftFace(x, y, w, d, height) {
  return polygon([[x, y + d, 0], [x + w, y + d, 0],
                  [x + w, y + d, height], [x, y + d, height]]);
}

/** The side facing down and right on screen: the +x wall of the box. */
export function rightFace(x, y, w, d, height) {
  return polygon([[x + w, y + d, 0], [x + w, y, 0],
                  [x + w, y, height], [x + w, y + d, height]]);
}

/** The silhouette of a whole box: the six-sided shape you see on screen.
 *
 *  This is what hit testing uses, and getting that right is the difference
 *  between a box you can pick up and one that ignores clicks on its lid. The
 *  floor point under a click on the top face is somewhere past the box's
 *  footprint, so testing the footprint misses exactly the part of a tall box
 *  people aim at.
 */
export function boxOutline(x, y, w, d, height) {
  if (height <= 0) return topFace(x, y, w, d, 0);
  return polygon([
    [x, y + d, 0], [x + w, y + d, 0], [x + w, y, 0],
    [x + w, y, height], [x, y, height], [x, y + d, height],
  ]);
}

/** Is a screen point inside a screen polygon? The crossing-number rule, on
 *  { x, y } objects rather than the [x, y] pairs model.js works in. */
export function insideShape(shape, point) {
  let inside = false;
  for (let at = 0, before = shape.length - 1; at < shape.length; before = at++) {
    const a = shape[at], b = shape[before];
    const straddles = (a.y > point.y) !== (b.y > point.y);
    if (straddles
        && point.x < (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x) {
      inside = !inside;
    }
  }
  return inside;
}

// ---------------------------------------------------------------------------
// WHICH WALLS TO DRAW
// ---------------------------------------------------------------------------

/** +1 or -1 for which way round a polygon's corners were listed.
 *
 *  Twice the signed area, reduced to its sign. Needed because the corners of a
 *  room are whatever order somebody clicked them in, and every question of the
 *  form "which side of this edge is the inside?" flips with that order.
 */
export function winding(points) {
  let twiceArea = 0;
  for (let at = 0; at < points.length; at++) {
    const [ax, ay] = points[at];
    const [bx, by] = points[(at + 1) % points.length];
    twiceArea += ax * by - bx * ay;
  }
  return twiceArea < 0 ? -1 : 1;
}

/** Which way an edge faces, pointing out of the room. Not normalized: only
 *  the direction is ever asked about. */
export function outwardNormal(ax, ay, bx, by, sense) {
  return [sense * (by - ay), sense * -(bx - ax)];
}

/** Does this wall face away from the camera, so you see its inside?
 *
 *  Those are the ones to draw. A wall facing the camera would stand between
 *  you and the room, which is what the cutaway exists to avoid. The camera
 *  looks down the x + y diagonal, so facing away is the normal's two
 *  components adding to less than zero.
 *
 *  This used to compare against the middle of the room, and that was wrong.
 *  Asking whether an edge's midpoint sits behind the room's centroid gives the
 *  right answer for a rectangle every time, so it survived a long while. For
 *  an L-shape it gets the notch exactly backwards. An edge knows which way it
 *  faces without being told where the middle of the room is, so it is asked
 *  directly.
 */
export function isFarWall(ax, ay, bx, by, sense) {
  const [nx, ny] = outwardNormal(ax, ay, bx, by, sense);
  return nx + ny < 0;
}

/** The walls worth drawing, as [[ax, ay], [bx, by]] pairs. */
export function farWalls(points) {
  if (points.length < 3) return [];
  const sense = winding(points);
  const walls = [];
  for (let at = 0; at < points.length; at++) {
    const a = points[at], b = points[(at + 1) % points.length];
    if (isFarWall(a[0], a[1], b[0], b[1], sense)) walls.push([a, b]);
  }
  return walls;
}

// ---------------------------------------------------------------------------
// DRAW ORDER
// ---------------------------------------------------------------------------
//
// Painter's algorithm: draw the far things first and let the near things paint
// over them. Everything here describes a thing by its FOOTPRINT, the
// [x0, y0, x1, y1] it covers on the floor. A wall's footprint is flat, zero
// wide in one direction, which is fine because nothing divides by it.
//
// THE OBVIOUS VERSION DOES NOT WORK, AND IT TAKES A WHILE TO SEE WHY
// ------------------------------------------------------------------
// Give everything one number and sort by it. The number people reach for is
// the depth of a corner, x + y, and either corner you pick is wrong:
//
//   The FAR corner breaks on walls. A wall runs the whole length of a side of
//   a room, so it is nearer the camera than some of what shares the room with
//   it and further than the rest, and no single number says where it belongs.
//
//   Cutting the wall into short pieces, so that each piece gets its own
//   number, looks like the fix and swaps one failure for another: a piece
//   three quarters of the way along the back wall now has a big depth, and a
//   container sitting in the far corner has a small one, so the wall is drawn
//   over the container it stands behind.
//
//   The NEAR corner breaks on wide objects. A shelf 400 long against the back
//   wall has a near corner further forward than a small bin standing in front
//   of it, so the shelf is drawn last and covers the bin.
//
// Both were tried. Both produced a picture that was right in the room it was
// tested in and wrong in the next one.
//
// WHAT IS ACTUALLY TRUE
// ---------------------
// "Behind" is not a number, it is a relation between two things, and for
// footprints on a floor seen down the x + y diagonal it is exact:
//
//     A is behind B if A ends before B starts in x, or in y.
//
// One axis is enough. If A is entirely at smaller x then every part of A is
// further from the camera than the part of B beside it, whatever their sizes.
// If neither holds in either axis the two overlap on the floor, which
// containers do not do and walls cannot, and then it does not matter.
//
// That relation is a graph, and drawing order is a topological sort of it.
// Which sounds heavier than it is: a room has a handful of walls and a handful
// of containers, so this is a few hundred comparisons for a whole frame, and
// it is correct rather than correct-so-far.

export function boxFootprint(x, y, w, d) {
  return [x, y, x + w, y + d];
}

export function wallFootprint([[ax, ay], [bx, by]]) {
  return [Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)];
}

/** How far the furthest corner of a footprint is from the camera.
 *
 *  Not the draw order on its own, see above. It is the tie-break inside it,
 *  for the pairs the relation has no opinion about.
 */
export function footprintDepth(footprint) {
  return depth(footprint[0], footprint[1]);
}

/** -1 if A is behind B, 1 if B is behind A, 0 if it makes no difference.
 *
 *  The comparisons are "less than or equal" on purpose. A container pushed
 *  flush against a wall shares an edge with it, and a wall is always behind
 *  what stands against it.
 */
export function behind(a, b) {
  if (a[2] <= b[0] || a[3] <= b[1]) return -1;
  if (b[2] <= a[0] || b[3] <= a[1]) return 1;
  return 0;
}

/** Order things so that nothing is drawn before something it stands behind.
 *
 *  Takes and returns whatever you give it, as long as each entry has a
 *  `footprint`. Kahn's algorithm: repeatedly take something with nothing left
 *  that has to come before it, preferring whichever of those is furthest away
 *  so that the result is stable and looks like the naive order wherever the
 *  relation does not care.
 *
 *  A cycle is possible in principle, three objects each behind the next, and
 *  is what the painter's algorithm has never been able to do without cutting
 *  things up. Nothing in a room makes one, because containers do not overlap
 *  and walls are on the outside of everything. If one turns up anyway the loop
 *  below takes the furthest remaining thing and carries on, so the picture is
 *  slightly wrong rather than missing.
 */
export function paintOrder(things) {
  const count = things.length;
  const afterwards = Array.from({ length: count }, () => []);
  const waitingOn = new Array(count).fill(0);

  for (let a = 0; a < count; a++) {
    for (let b = a + 1; b < count; b++) {
      const order = behind(things[a].footprint, things[b].footprint);
      if (!order) continue;
      const [first, second] = order < 0 ? [a, b] : [b, a];
      afterwards[first].push(second);
      waitingOn[second]++;
    }
  }

  const depths = things.map(thing => footprintDepth(thing.footprint));
  const left = new Set(things.keys());
  const ordered = [];

  while (left.size) {
    let pick = -1;
    for (const at of left) {
      if (waitingOn[at] > 0) continue;
      if (pick < 0 || depths[at] < depths[pick]) pick = at;
    }
    if (pick < 0) {
      // A cycle. Take the furthest thing still waiting and move on.
      for (const at of left) if (pick < 0 || depths[at] < depths[pick]) pick = at;
    }
    left.delete(pick);
    ordered.push(things[pick]);
    for (const next of afterwards[pick]) waitingOn[next]--;
  }
  return ordered;
}

// ---------------------------------------------------------------------------
// FITTING A ROOM ON SCREEN
// ---------------------------------------------------------------------------

/** The screen rectangle a room and its contents occupy, unscaled, as
 *  [x, y, width, height].
 *
 *  Needed before anything is drawn, to work out where to put the camera.
 *  Height matters: a tall cabinet reaches further up the screen than the wall
 *  behind it, and leaving it out of the sum crops the top off it.
 */
export function roomBounds(points, wallHeight = WALL_HEIGHT, tallest = 0) {
  if (!points.length) return [0, 0, 0, 0];

  const reach = Math.max(wallHeight, tallest);
  const corners = [];
  for (const [px, py] of points) {
    corners.push(project(px, py, 0));
    corners.push(project(px, py, reach));
  }

  const xs = corners.map(corner => corner.x);
  const ys = corners.map(corner => corner.y);
  const left = Math.min(...xs), top = Math.min(...ys);
  return [left, top, Math.max(...xs) - left, Math.max(...ys) - top];
}

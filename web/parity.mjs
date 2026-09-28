/**
 * parity.mjs
 * ==========
 *
 * Answer every case in parity_cases.json with model.js and compare against
 * what models.py said. Any disagreement is a bug in the port, and the first
 * few are printed in full so it is obvious which.
 *
 *     python web/parity_cases.py > web/parity_cases.json
 *     node web/parity.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as M from "./model.js";
import * as I from "./iso.js";
import * as T from "./theme.js";

const here = dirname(fileURLToPath(import.meta.url));
const cases = JSON.parse(readFileSync(join(here, "parity_cases.json"), "utf8"));

let checked = 0;
const failures = [];

/** Floating point arithmetic in two languages will not land on identical
 *  bits every time, so numbers compare to a tolerance well below anything
 *  that could change an answer. Everything else compares exactly. */
function same(a, b, tolerance = 1e-9) {
  if (typeof a === "number" && typeof b === "number") {
    return Math.abs(a - b) <= tolerance || (Number.isNaN(a) && Number.isNaN(b));
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((v, i) => same(v, b[i], tolerance));
  }
  if (a && b && typeof a === "object" && typeof b === "object") {
    const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
    return same(ka, kb) && ka.every(k => same(a[k], b[k], tolerance));
  }
  return a === b;
}

function check(group, label, expected, got, context, tolerance = 1e-9) {
  checked++;
  if (same(expected, got, tolerance)) return;
  failures.push({ group, label, expected, got, context });
}

const roomOf = points => ({ points });

// -- geometry ---------------------------------------------------------------
for (const c of cases.point) {
  check("point_in_polygon", `${c.p}`, c.answer,
        M.pointInPolygon(c.points, c.p[0], c.p[1]), c.points.length + " corners");
}

for (const c of cases.cross) {
  const [a, b, d, e] = c.segments;
  check("segments_cross", "", c.answer, M.segmentsCross(a, b, d, e), c.segments);
}

for (const c of cases.contains) {
  check("room_contains_rect", `${c.rect}`, c.answer,
        M.roomContainsRect(roomOf(c.points), ...c.rect), c.points);
}

for (const c of cases.fit) {
  check("fit_in_room", `${c.rect} stay=${c.stay}`, c.answer,
        M.fitInRoom(roomOf(c.points), ...c.rect, c.stay), c.points);
}

for (const c of cases.nearest) {
  check("nearest_fit", `${c.rect}`, c.answer,
        M.nearestFit(roomOf(c.points), ...c.rect), c.points);
}

for (const c of cases.reshape) {
  // A fresh Room each time: all three of these edit the points in place, so
  // reusing one would be asking the second case about the first one's answer.
  const room = new M.Room({ points: c.points.map(point => [...point]) });
  let got;
  if (c.op === "insert") {
    got = { index: room.insertPointOnNearestEdge(c.arg[0], c.arg[1]),
            points: room.points };
  } else if (c.op === "remove") {
    got = { ok: room.removePoint(c.arg), points: room.points };
  } else {
    room.resizeTo(...c.arg);
    got = { points: room.points };
  }
  check(`Room.${c.op}`, c.label, c.answer, got, c.points);
}

for (const c of cases.shapes) {
  check("bounds", c.label, c.bounds, M.boundsOf(roomOf(c.points)));
  check("center", c.label, c.center, new M.Room({ points: c.points }).center());
}

// -- heights ----------------------------------------------------------------
for (const c of cases.height) {
  check("nearest_height", `${c.value}`, c.nearest, M.nearestHeight(c.value));
  check("clamp_height", `${c.value}`, c.clamped, M.clampHeight(c.value));
  if (c.name !== null) {
    check("height_name", `${c.value}`, c.name, M.heightName(c.value));
  }
}

// -- names ------------------------------------------------------------------
for (const c of cases.name) {
  check("clean_name", JSON.stringify(c.value), c.clean, M.cleanName(c.value));
  check("short", JSON.stringify(c.value), c.short, M.short(c.value));
  check("short(8)", JSON.stringify(c.value), c.short8, M.short(c.value, 8));
  const base = c.value || "Untitled";
  check("copy_name", JSON.stringify(c.value), c.copy, M.copyName(base, []));
  check("copy_name 2", JSON.stringify(c.value), c.copy2,
        M.copyName(base, [M.copyName(base, [])]));
}

// -- the save format --------------------------------------------------------
for (const c of cases.migrate) {
  check("migrate", JSON.stringify(c.raw.schema), c.answer,
        M.migrate(structuredClone(c.raw)), c.raw);
}

for (const c of cases.olditem) {
  // created_at and updated_at are filled in with "now" when a file has none,
  // so they cannot match across two runs. Compare everything else.
  const got = M.Item.fromDict(structuredClone(c.raw)).toDict();
  for (const key of ["created_at", "updated_at"]) {
    delete got[key];
    delete c.answer[key];
  }
  check("old item format", c.raw.id, c.answer, got, c.raw);
}

check("round trip: to_dict", "", cases.roundtrip.dict, cases.roundtrip.reloaded);
check("round trip: through JS", "", cases.roundtrip.dict,
      M.Profile.fromDict(structuredClone(cases.roundtrip.dict)).toDict());

// -- the projection ---------------------------------------------------------
// Everything from here to the report needs cases that only exist when
// parity_cases.py could import PySide6. Without it the model half still runs,
// and the tally at the end says plainly that the rest did not, because a
// harness printing "all agreed" while quietly skipping half its work is worse
// than one that fails.
const covered = Boolean(cases.project);
if (covered) {
// iso.js works in { x, y } objects on screen, which the Python writes as a
// QPointF and this file wrote out as a pair. Flattened here rather than in
// iso.js, because a pair is the harness's language and not the app's.
const flat = point => [point.x, point.y];

for (const c of cases.project) {
  check("project", `${c.xyz}`, c.answer, flat(I.project(...c.xyz)));
}

for (const c of cases.floor_at) {
  check("floor_at", `${c.screen}`, c.answer,
        I.floorAt({ x: c.screen[0], y: c.screen[1] }));
}

// Not asked of the Python, because it is not about the Python. project and
// floorAt are each other's inverse or dragging does not work, and that is a
// property worth stating rather than hoping for.
for (const c of cases.project) {
  const [x, y] = c.xyz;
  check("floor_at undoes project", `${x}, ${y}`, [x, y],
        I.floorAt(I.project(x, y, 0)));
}

for (const c of cases.faces) {
  check("top_face", `${c.box}`, c.top, I.topFace(...c.box).map(flat));
  check("left_face", `${c.box}`, c.left, I.leftFace(...c.box).map(flat));
  check("right_face", `${c.box}`, c.right, I.rightFace(...c.box).map(flat));
  check("box_outline", `${c.box}`, c.outline, I.boxOutline(...c.box).map(flat));
  check("box_footprint", `${c.box}`, c.footprint,
        I.boxFootprint(c.box[0], c.box[1], c.box[2], c.box[3]));
}

// -- which walls, and where they land in the order --------------------------
for (const c of cases.walls) {
  check("winding", c.label, c.winding, I.winding(c.points));

  const walls = I.farWalls(c.points);
  check("far_walls", c.label, c.far, walls, c.points);
  check("wall_footprint", c.label, c.footprints, walls.map(I.wallFootprint));
  check("footprint_depth", c.label, c.depths,
        walls.map(wall => I.footprintDepth(I.wallFootprint(wall))));
  check("room_bounds empty", c.label, c.bounds_empty,
        I.roomBounds(c.points, I.WALL_HEIGHT, 0));
  check("room_bounds with something tall in it", c.label, c.bounds_tall,
        I.roomBounds(c.points, I.WALL_HEIGHT, 90));

  // The draw order, which the Python has no equivalent of to compare with:
  // room_view_3d.py sorts on a depth number, and this does not, for the
  // reasons written over paintOrder. So it is checked against the thing it is
  // supposed to guarantee instead.
  //
  // Put this room's walls in with some boxes, order them, and then ask every
  // pair in the result whether it came out the right way round. Exhaustive,
  // rather than a sample: there are only ever a few dozen.
  const things = walls.map(wall =>
    ({ what: `wall ${wall[0]}-${wall[1]}`, footprint: I.wallFootprint(wall) }));
  // Boxes placed the way the app places them, with nearestFit, so they land
  // inside the room rather than lying across a wall. That is not to make the
  // check easy. It is the only arrangement that can occur, because every path
  // that moves a container goes through fitInRoom on the way, and holding the
  // code to a scene it can never be given proves nothing.
  const [x0, y0] = c.points.reduce(
    ([lx, ly], [px, py]) => [Math.min(lx, px), Math.min(ly, py)], [1e9, 1e9]);
  for (let n = 0; n < 6; n++) {
    const [x, y, w, h] = M.nearestFit(
      { points: c.points }, x0 + n * 37, y0 + ((n * 53) % 140), 40 + n * 9, 30);
    things.push({ what: `box ${n}`, footprint: I.boxFootprint(x, y, w, h) });
  }

  const ordered = I.paintOrder(things);
  check("paintOrder keeps everything", c.label, things.length, ordered.length);

  const wrong = [];
  for (let a = 0; a < ordered.length; a++) {
    for (let b = a + 1; b < ordered.length; b++) {
      // ordered[a] is drawn first, so it must not be in front of ordered[b].
      if (I.behind(ordered[a].footprint, ordered[b].footprint) > 0) {
        wrong.push(`${ordered[a].what} drawn before ${ordered[b].what}`);
      }
    }
  }
  check("paintOrder never draws something in front of what it hides",
        c.label, [], wrong);
}

// What happens when the relation contradicts itself. Three footprints each
// behind the next is the oldest hole in the painter's algorithm, and without
// cutting shapes apart the only honest answer is to pick one and carry on.
// What must not happen is losing something or looping forever, so that is
// what this pins down. The scene is hand-built: containers kept inside a room
// by fitInRoom do not make one, which is why the check above can be strict.
{
  const ring = [
    { what: "a", footprint: [-167, -77, -118, -47] },
    { what: "b", footprint: [-50, -93, 0, -50] },
    { what: "c", footprint: [0, -130, 130, -93] },
  ];
  check("a cycle really is a cycle", "three deep", [-1, -1, -1],
        [I.behind(ring[0].footprint, ring[1].footprint),
         I.behind(ring[1].footprint, ring[2].footprint),
         I.behind(ring[2].footprint, ring[0].footprint)]);
  check("a cycle still draws everything, once each", "three deep",
        ["a", "b", "c"], I.paintOrder(ring).map(thing => thing.what).sort());
}

// And the relation itself, on cases small enough to read.
for (const [name, a, b, expected] of [
  ["a wall at x=0 and a box beside it", [0, 0, 0, 300], [10, 40, 200, 100], -1],
  ["a box pushed flush against that wall", [0, 0, 0, 300], [0, 40, 200, 100], -1],
  ["a wall at y=0 and a box further down", [0, 0, 400, 0], [10, 10, 160, 55], -1],
  ["a long shelf behind a small bin", [0, 0, 400, 20], [10, 40, 30, 60], -1],
  ["the same pair the other way round", [10, 40, 30, 60], [0, 0, 400, 20], 1],
  ["two boxes side by side across the view", [0, 100, 20, 120], [100, 0, 120, 20], -1],
  ["a box and itself", [10, 10, 50, 50], [10, 10, 50, 50], 0],
  ["two boxes that overlap on the floor", [0, 0, 50, 50], [20, 20, 70, 70], 0],
]) {
  check("behind", name, expected, I.behind(a, b));
}

// -- color ------------------------------------------------------------------
// To a tolerance of one step per channel, and on purpose. Python's round()
// sends a half to the nearest EVEN number and JavaScript's sends it up, so a
// blend landing exactly on .5 differs by one in the last place. These are
// screen colors, computed fresh in both programs and never written to a file,
// and one unit of blue is not worth a hand-rolled rounding function to chase.
// A real mistake here, a swapped channel or a blend running backwards, is
// nowhere near this small.
const channels = hex => [1, 3, 5].map(at => parseInt(hex.slice(at, at + 2), 16));

for (const c of cases.color) {
  const amount = Math.abs(c.amount);
  check("mix towards white", `${c.hex} ${c.amount}`, channels(c.mix_white),
        channels(I.mix(c.hex, "#ffffff", amount)), null, 1);
  check("mix towards black", `${c.hex} ${c.amount}`, channels(c.mix_black),
        channels(I.mix(c.hex, "#000000", amount)), null, 1);
  check("shade picks the direction from the sign", `${c.hex} ${c.amount}`,
        channels(c.amount >= 0 ? c.mix_white : c.mix_black),
        channels(I.shade(c.hex, c.amount)), null, 1);
}

// -- the palette, and the numbers that decide how a room looks --------------
for (const [name, expected] of Object.entries(cases.palette)) {
  check("theme.js matches theme.py", name, expected, T[name]);
}
for (const [name, expected] of Object.entries(cases.iso_constants)) {
  check("iso.js matches iso.py", name, expected, I[name]);
}
}  // end of the part that needs PySide6

// -- report -----------------------------------------------------------------
const groups = new Map();
for (const f of failures) groups.set(f.group, (groups.get(f.group) ?? 0) + 1);

console.log(`${checked} cases answered by both`);
if (!covered) {
  console.log("\nTHE PROJECTION AND THE PALETTE WERE NOT CHECKED.");
  console.log("parity_cases.py could not import PySide6, so it had nothing");
  console.log("to compare iso.js and theme.js against. pip install -r");
  console.log("requirements.txt and run it again for the whole picture.");
}
if (!failures.length) {
  console.log(covered
    ? "every answer agrees with the Python"
    : "every answer it could ask about agrees with the Python");
  process.exit(covered ? 0 : 2);
}

console.log(`\n${failures.length} DISAGREEMENTS`);
for (const [group, count] of groups) console.log(`   ${group}: ${count}`);
console.log("\nfirst few:");
for (const f of failures.slice(0, 6)) {
  console.log(`\n  ${f.group}  ${f.label}`);
  console.log(`    python: ${JSON.stringify(f.expected)}`);
  console.log(`    js    : ${JSON.stringify(f.got)}`);
  if (f.context) console.log(`    room  : ${JSON.stringify(f.context)}`);
}
process.exit(1);

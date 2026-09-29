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

// -- everything Profile can be asked or told --------------------------------
// The house in parity_cases.py has a thing on two tiers of one shelf, a thing
// in two rooms, a thing pointing at a container that is gone, a thing below
// its par level and a thing tagged for a room it is not in, because each of
// those is a branch in one of these.
{
  const named = thing => thing === null || thing === undefined
    ? null : [thing.id, thing.name];
  const placeList = found => found.map(([floor, room, box, quantity, tier]) =>
    [named(floor), named(room), named(box), quantity, tier]);

  const house = () => M.Profile.fromDict(structuredClone(cases.profile.dict));
  const find = (profile, id) => profile.items.find(item => item.id === id);
  const asked = cases.profile;
  const profile = house();

  check("profile fixture survives the crossing", "",
        cases.profile.dict, profile.toDict());

  check("tagsFor", "", asked.tags_for,
        [[], ["t-tools"], ["t-food", "t-tools"], ["t-gone"], ["t-tools", "t-gone"]]
          .map(ids => profile.tagsFor(ids).map(tag => tag.id)));

  for (const [id, expected] of Object.entries(asked.find_container)) {
    check("findContainer", id, expected, profile.findContainer(id).map(named));
  }
  for (const [id, expected] of Object.entries(asked.find_room)) {
    check("findRoom", id, expected, profile.findRoom(id).map(named));
  }
  for (const [id, expected] of Object.entries(asked.container_path)) {
    check("containerPath", id, expected, profile.containerPath(id));
  }
  for (const [id, expected] of Object.entries(asked.locations_of)) {
    check("locationsOf", id, expected, placeList(profile.locationsOf(find(profile, id))));
  }
  for (const [id, expected] of Object.entries(asked.location_of)) {
    check("locationOf", id, expected, profile.locationOf(find(profile, id)));
  }
  for (const [id, expected] of Object.entries(asked.contents_of)) {
    check("contentsOf", id, expected,
          profile.contentsOf(id).map(([item, q, t]) => [item.id, q, t]));
  }
  for (const [id, tier, expected] of asked.contents_of_tier) {
    check("contentsOf one tier", `${id} tier ${tier}`, expected,
          profile.contentsOf(id, tier).map(([item, q, t]) => [item.id, q, t]));
  }
  for (const [id, expected] of Object.entries(asked.item_count_in_container)) {
    check("itemCountInContainer", id, expected, profile.itemCountInContainer(id));
  }
  for (const [id, expected] of Object.entries(asked.items_in_room)) {
    const [, room] = profile.findRoom(id);
    check("itemsInRoom", id, expected, profile.itemsInRoom(room).map(item => item.id));
  }
  check("unfiledItems", "", asked.unfiled_items,
        profile.unfiledItems().map(item => item.id));
  check("lowItems", "", asked.low_items, profile.lowItems().map(item => item.id));
  for (const [tag, expected] of Object.entries(asked.items_with_tag)) {
    check("itemsWithTag", tag, expected,
          profile.itemsWithTag(tag).map(item => item.id));
  }
  for (const [tag, expected] of Object.entries(asked.rooms_with_tag)) {
    check("roomsWithTag", tag, expected,
          [...profile.roomsWithTag(tag)].map(pair => pair.map(named)));
  }
  check("misfiledItems", "", asked.misfiled_items,
        profile.misfiledItems().map(([item, tag, rooms]) =>
          [item.id, named(tag), rooms.map(room => room.id)]));
  check("recentItems", "", asked.recent_items,
        profile.recentItems().map(item => item.id));
  check("recentItems(3)", "", asked.recent_items_3,
        profile.recentItems(3).map(item => item.id));
  check("floorIndex", "", asked.floor_index,
        [...profile.floors.map(floor => profile.floorIndex(floor)),
         profile.floorIndex(new M.Floor({ id: "nope" }))]);

  // The changes. Each from a fresh house, and the WHOLE profile is compared
  // afterwards, because half of what a delete has to get right is what it
  // left alone.
  const changes = {
    "set_placement new": p => p.setPlacement(find(p, "i5"), "c2", 3, 1),
    "set_placement update": p => p.setPlacement(find(p, "i1"), "c1", 9, 1),
    "set_placement other tier": p => p.setPlacement(find(p, "i1"), "c1", 7, 2),
    "set_placement zero removes": p => p.setPlacement(find(p, "i1"), "c1", 0, 1),
    "set_placement negative removes": p => p.setPlacement(find(p, "i4"), "c2", -5, 0),
    "set_placement zero on nothing": p => p.setPlacement(find(p, "i5"), "c1", 0, 0),
    "move_to_tier part": p => p.moveToTier(find(p, "i3"), "c1", 2, 1, 2),
    "move_to_tier all": p => p.moveToTier(find(p, "i3"), "c1", 2, 1, 6),
    "move_to_tier more than there is": p => p.moveToTier(find(p, "i3"), "c1", 2, 1, 99),
    "move_to_tier onto an occupied one": p => p.moveToTier(find(p, "i1"), "c1", 3, 1, 2),
    "move_to_tier to loose": p => p.moveToTier(find(p, "i1"), "c1", 1, 0, 4),
    "move_to_tier nowhere": p => p.moveToTier(find(p, "i1"), "c1", 1, 1, 2),
    "move_to_tier from an empty tier": p => p.moveToTier(find(p, "i1"), "c1", 2, 1, 1),
    "move_to_tier zero": p => p.moveToTier(find(p, "i1"), "c1", 1, 2, 0),
    "set_tier_count up": p => p.setTierCount(p.floors[0].rooms[0].containers[0], 6),
    "set_tier_count down": p => p.setTierCount(p.floors[0].rooms[0].containers[0], 2),
    "set_tier_count to none": p => p.setTierCount(p.floors[0].rooms[0].containers[0], 0),
    "set_tier_count negative": p => p.setTierCount(p.floors[1].rooms[0].containers[0], -3),
    "delete_tag": p => p.deleteTag("t-tools"),
    "delete_tag that is not there": p => p.deleteTag("t-gone"),
    "delete_container": p => p.deleteContainer("c1"),
    "delete_container that is not there": p => p.deleteContainer("c-gone"),
    "delete_room": p => p.deleteRoom("r1"),
    "delete_room with nothing in it": p => p.deleteRoom("r3"),
    "delete_floor": p => p.deleteFloor("f1"),
    "delete_floor the last one": p => p.deleteFloor("f2"),
  };

  for (const c of cases.profile_changes) {
    const apply = changes[c.label];
    if (!apply) {
      check("a change the JavaScript side has never heard of", c.label, true, false);
      continue;
    }
    const profileNow = house();
    apply(profileNow);
    // moveToTier calls touch(), which stamps "now", and two runs are never
    // the same instant. The stamp is not what is being checked here.
    const flatten = dict => ({ ...dict,
      items: dict.items.map(item => ({ ...item, updated_at: "" })) });
    check("Profile change", c.label, flatten(c.answer), flatten(profileNow.toDict()));
  }
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

// -- which rooms are sitting on top of each other ---------------------------
for (const c of cases.overlap) {
  const first = { ...c.first };
  const second = { ...c.second };
  check("room_outline", c.label, c.outline, M.roomOutline(first));
  check("rooms_overlap", c.label, c.answer, M.roomsOverlap(first, second));
  // Asked the other way round as well. The test is three questions and two
  // of them are each other's mirror, so an implementation that dropped one
  // would answer correctly in one direction and not the other.
  check("rooms_overlap, the other way round", c.label, c.both_ways,
        M.roomsOverlap(second, first));
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

  // The draw order, checked twice over. Once against the Python, which now
  // runs the same algorithm rather than sorting on a depth number, so the two
  // have to produce the same sequence piece for piece. And once against the
  // thing the order is supposed to guarantee, by asking every pair in the
  // result whether it came out the right way round. Exhaustive, rather than a
  // sample: there are only ever a few dozen.
  //
  // Both, because they fail differently. Agreeing with the Python says the
  // port is faithful; it would say that just as happily if both were wrong.
  const things = walls.map((wall, n) =>
    ({ what: `wall ${n}`, footprint: I.wallFootprint(wall) }));
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
  check("paintOrder agrees with iso.paint_order", c.label, c.order,
        ordered.map(thing => thing.what));

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

// The relation used to be able to contradict itself, and this block used to
// hand it a three-deep ring to prove the sort survived one. It cannot make a
// ring any more: behind() returns nothing for a diagonal pair, and with that
// the relation came out antisymmetric and cycle-free on every footprint of a
// small grid and on six hundred thousand random scenes. The old ring is kept
// below as the case that started it, now checked for what is actually true of
// it, and the sort is still handed awkward scenes to prove it does not lose
// anything.
{
  const ring = [
    { what: "a", footprint: [-167, -77, -118, -47] },
    { what: "b", footprint: [-50, -93, 0, -50] },
    { what: "c", footprint: [0, -130, 130, -93] },
  ];
  check("the ring that used to close no longer does", "three deep",
        [-1, 0, 0],
        [I.behind(ring[0].footprint, ring[1].footprint),
         I.behind(ring[1].footprint, ring[2].footprint),
         I.behind(ring[2].footprint, ring[0].footprint)]);
  check("and it still draws everything, once each", "three deep",
        ["a", "b", "c"], I.paintOrder(ring).map(thing => thing.what).sort());

  // Degenerate on purpose: two pieces in the same place, a wall with no width
  // and no length, and a piece that swallows the lot. Nothing here should be
  // ordered confidently, which is exactly when a sort is most likely to drop
  // something.
  const awkward = [
    { what: "same 1", footprint: [10, 10, 50, 50] },
    { what: "same 2", footprint: [10, 10, 50, 50] },
    { what: "a point", footprint: [30, 30, 30, 30] },
    { what: "everything", footprint: [0, 0, 100, 100] },
  ];
  check("degenerate pieces all come back, once each", "awkward",
        ["a point", "everything", "same 1", "same 2"],
        I.paintOrder(awkward).map(thing => thing.what).sort());
}

// And the relation itself, on cases small enough to read.
for (const [name, a, b, expected] of [
  ["a wall at x=0 and a box beside it", [0, 0, 0, 300], [10, 40, 200, 100], -1],
  ["a box pushed flush against that wall", [0, 0, 0, 300], [0, 40, 200, 100], -1],
  ["a wall at y=0 and a box further down", [0, 0, 400, 0], [10, 10, 160, 55], -1],
  ["a long shelf behind a small bin", [0, 0, 400, 20], [10, 40, 30, 60], -1],
  ["the same pair the other way round", [10, 40, 30, 60], [0, 0, 400, 20], 1],
  // Diagonally apart, not one behind the other. The first ends before the
  // second in x and the second ends before the first in y, so both rules fire
  // and neither wins. Their screen columns do not even touch.
  ["two boxes side by side across the view", [0, 100, 20, 120], [100, 0, 120, 20], 0],
  ["and the same pair the other way round", [100, 0, 120, 20], [0, 100, 20, 120], 0],
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

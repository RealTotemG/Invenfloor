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

function check(group, label, expected, got, context) {
  checked++;
  if (same(expected, got)) return;
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

// -- report -----------------------------------------------------------------
const groups = new Map();
for (const f of failures) groups.set(f.group, (groups.get(f.group) ?? 0) + 1);

console.log(`${checked} cases answered by both`);
if (!failures.length) {
  console.log("every answer agrees with models.py");
  process.exit(0);
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

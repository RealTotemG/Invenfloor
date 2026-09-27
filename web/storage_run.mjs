/**
 * storage_run.mjs
 * ===============
 *
 * Run the storage checks in node, with a stand-in for IndexedDB:
 *
 *     npm install --no-save fake-indexeddb
 *     node --import fake-indexeddb/auto web/storage_run.mjs
 *
 * --no-save because there is no package.json here and there should not need
 * to be one. Nothing the app ships depends on this. It installs into
 * node_modules, it is already in .gitignore, and deleting that folder costs
 * you one command to get back.
 *
 * A stand-in is not the real thing, and the difference is the point of
 * dev.html: the same checks run there in a real browser against the real
 * IndexedDB, and that is the run that counts. This one exists because it
 * takes two seconds and no clicking, which is what you want while you are
 * halfway through changing something.
 */
import { runStorageChecks } from "./storage_checks.js";

if (typeof indexedDB === "undefined") {
  console.error("There is no IndexedDB here, so there is nothing to check.\n");
  console.error("  npm install --no-save fake-indexeddb");
  console.error("  node --import fake-indexeddb/auto web/storage_run.mjs\n");
  console.error("The --import is what puts it in place. Without it node has");
  console.error("no database of any kind.");
  process.exit(1);
}

const results = await runStorageChecks("invenfloor-checks-node");
const failed = results.filter(result => !result.ok);

for (const result of results) {
  console.log(`${result.ok ? "  ok  " : " FAIL "} ${result.label}`);
  if (!result.ok && result.why) {
    console.log(`        ${result.why.replace(/\n/g, "\n        ")}`);
  }
}

console.log();
if (!failed.length) {
  console.log(`all ${results.length} checks passed`);
  process.exit(0);
}
console.log(`${failed.length} of ${results.length} FAILED`);
process.exit(1);

/**
 * storage_run.mjs
 * ===============
 *
 * Run the vault and storage checks in node, with a stand-in for IndexedDB:
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
 * takes a couple of seconds and no clicking, which is what you want while you
 * are halfway through changing something.
 */
import { runStorageChecks, runVaultChecks } from "./storage_checks.js";

if (typeof indexedDB === "undefined") {
  console.error("There is no IndexedDB here, so there is nothing to check.\n");
  console.error("  npm install --no-save fake-indexeddb");
  console.error("  node --import fake-indexeddb/auto web/storage_run.mjs\n");
  console.error("The --import is what puts it in place. Without it node has");
  console.error("no database of any kind.");
  process.exit(1);
}

let failed = 0;
let ran = 0;

async function run(title, work) {
  const results = await work();
  const bad = results.filter(result => !result.ok);
  ran += results.length;
  failed += bad.length;

  console.log(`\n${title}`);
  console.log("-".repeat(title.length));
  for (const result of results) {
    console.log(`${result.ok ? "  ok  " : " FAIL "} ${result.label}`);
    if (!result.ok && result.why) {
      console.log(`        ${result.why.replace(/\n/g, "\n        ")}`);
    }
  }
}

await run("The vault", () => runVaultChecks());
await run("Saving, with nothing over it",
          () => runStorageChecks("invenfloor-checks-node"));
// The same set again, with a passphrase on the database. Not a second set of
// checks: the same ones, because the claim encryption has to earn is that it
// changes nothing about how any of this behaves.
await run("Saving, with a passphrase over it",
          () => runStorageChecks("invenfloor-checks-node-locked",
                                 { passphrase: "a checking passphrase" }));

console.log();
if (!failed) {
  console.log(`all ${ran} checks passed`);
  process.exit(0);
}
console.log(`${failed} of ${ran} FAILED`);
process.exit(1);

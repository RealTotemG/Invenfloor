/**
 * storage_checks.js
 * =================
 *
 * What storage.js is supposed to do, written down so a machine can ask.
 *
 * These are checks rather than a parity harness, and the difference is worth
 * being honest about. model.js could be checked against models.py case by
 * case, because both answer the same questions and neither had to be trusted.
 * There is nothing to compare this file against: storage.py talks to a folder
 * and this one talks to a database, so the two cannot answer the same
 * question. So these are ordinary tests, with the ordinary weakness that I
 * wrote them and the code, and a misunderstanding in one can live happily in
 * the other.
 *
 * What they are good for is the thing that actually goes wrong here, which is
 * not arithmetic. It is order: whether a snapshot was taken before the write
 * or after it, whether the broken record moved out of the way before the next
 * save, whether a profile from the future got quietly flattened. Every one of
 * those is a sequence of writes with a wrong answer at the end, and that is
 * exactly what a test can pin down.
 *
 * They run in two places, from this one file:
 *
 *   - the browser, from dev.html, which is where IndexedDB really lives
 *   - node, with fake-indexeddb, which needs no browser and no clicking:
 *
 *         npm install --no-save fake-indexeddb
 *         node --import fake-indexeddb/auto web/storage_run.mjs
 *
 * The browser is the one that counts. node is the one you will actually run
 * twenty times while changing something.
 */
import * as M from "./model.js";
import * as S from "./storage.js";

// ---------------------------------------------------------------------------
// REACHING PAST THE FRONT DOOR
// ---------------------------------------------------------------------------
// Nothing in storage.js lets a caller write a broken record, which is correct
// and also means the checks have to go around it. These four helpers touch the
// database directly. They are here and not there on purpose.

function settled(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = transaction.onabort = () =>
      reject(transaction.error ?? new Error("the write was abandoned"));
  });
}

function answered(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/** Put a record straight into one of the stores, bypassing save(). */
async function plant(store, storeName, key, value) {
  const transaction = store.database.transaction(storeName, "readwrite");
  transaction.objectStore(storeName).put(value, key);
  await settled(transaction);
}

/** Read one record straight out, and every key in a store. */
function peek(store, storeName, key) {
  return answered(store.database.transaction(storeName, "readonly")
                       .objectStore(storeName).get(key));
}

function peekKeys(store, storeName) {
  return answered(store.database.transaction(storeName, "readonly")
                       .objectStore(storeName).getAllKeys());
}

/** Delete a database and do not care why it worked.
 *
 *  onblocked resolves as well. A run that threw halfway can leave a
 *  connection open, and a check page that hangs forever on the way in is
 *  worse than one that starts from a database it did not manage to clear.
 */
function wipe(name) {
  return new Promise(resolve => {
    const request = indexedDB.deleteDatabase(name);
    request.onsuccess = request.onerror = request.onblocked = () => resolve();
  });
}

// ---------------------------------------------------------------------------
// SOMETHING TO SAVE
// ---------------------------------------------------------------------------

/** A small profile that is stable the moment it is built.
 *
 *  Stable matters: a container put somewhere it does not fit gets pulled back
 *  inside on the way in, so a profile built by hand and then compared against
 *  itself after a load can differ for a reason that has nothing to do with
 *  storage. This one fits where it is put.
 */
function madeUp(name) {
  const profile = new M.Profile({ name, color: "#33d6a0" });
  const floor = new M.Floor({ name: "Ground" });
  const room = new M.Room({ name: "Garage", points: M.lShapePoints(400, 300) });
  room.containers = [new M.Container({ name: "Shelving", x: 20, y: 20,
                                       w: 90, h: 50, tierCount: 3 })];
  floor.rooms = [room];
  profile.floors = [floor];
  profile.items = [new M.Item({ name: "Sockets",
    placements: [new M.Placement(room.containers[0].id, 3, 1)] })];
  return profile;
}

/** Valid JSON, and not a profile. What the gate in storage.js is for. */
const NOT_A_PROFILE = { savedAt: 1, profile: { hello: "world" } };

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// ---------------------------------------------------------------------------
// THE CHECKS
// ---------------------------------------------------------------------------

/** Run every check against a database of its own. Returns
 *  [{ label, ok, why }] in the order they ran.
 *
 *  The database is deleted before and after, so this never touches real
 *  profiles and never depends on what a previous run left behind.
 */
export async function runStorageChecks(databaseName = "invenfloor-checks") {
  const results = [];
  const check = (label, ok, why = "") => results.push({ label, ok, why: String(why) });
  let store = null;

  try {
    await wipe(databaseName);
    store = await S.Store.open(databaseName);

    // -- the ordinary path --------------------------------------------------

    let listed = await store.list();
    check("a new database has nothing in it",
          listed.profiles.length === 0 && listed.recoveries.length === 0
          && listed.refused.length === 0);

    const profile = madeUp("Kitchen one");
    const firstSavedAt = await store.save(profile);
    listed = await store.list();
    check("a saved profile comes back",
          listed.profiles.length === 1 && listed.profiles[0].id === profile.id,
          `got ${listed.profiles.length}`);
    check("and comes back with everything on it",
          same(listed.profiles[0].toDict(), profile.toDict()));
    check("savedAt is recorded",
          (await store.savedAt(profile.id)) === firstSavedAt);
    check("savedAt of a profile that is not there is null",
          (await store.savedAt("nosuchid")) === null);

    // -- one snapshot a day, not one a save ---------------------------------

    store.today = () => "2026-09-20";
    check("the first ever save takes no snapshot",
          (await peekKeys(store, "backups")).length === 0,
          "there was nothing yet to preserve");

    profile.name = "Kitchen two";
    await store.save(profile);
    profile.name = "Kitchen three";
    await store.save(profile);
    profile.name = "Kitchen four";
    await store.save(profile);

    let snapshots = await store.snapshots(profile.id);
    check("three more saves in one day leave one snapshot",
          snapshots.length === 1 && snapshots[0].day === "2026-09-20",
          `${snapshots.length} snapshots`);
    check("and it holds the state from before that day's work",
          snapshots[0].name === "Kitchen one", snapshots[0].name);
    check("the previous save is the one just before this one",
          (await peek(store, "previous", profile.id)).profile.name === "Kitchen three");

    store.today = () => "2026-09-21";
    profile.name = "Kitchen five";
    await store.save(profile);
    snapshots = await store.snapshots(profile.id);
    check("a save the next day takes another snapshot",
          snapshots.length === 2 && snapshots[0].day === "2026-09-21",
          snapshots.map(s => s.day).join(" "));
    check("newest snapshot first",
          snapshots[0].day > snapshots[1].day);

    // -- pruning ------------------------------------------------------------

    for (let day = 22; day <= 30; day++) {
      store.today = () => `2026-09-${day}`;
      profile.name = `Kitchen day ${day}`;
      await store.save(profile);
    }
    snapshots = await store.snapshots(profile.id);
    check(`no more than ${S.DAYS_KEPT} snapshots are kept`,
          snapshots.length === S.DAYS_KEPT, `${snapshots.length} kept`);
    check("and the ones kept are the newest",
          snapshots[0].day === "2026-09-30"
          && snapshots[snapshots.length - 1].day === "2026-09-21",
          `${snapshots[snapshots.length - 1].day} to ${snapshots[0].day}`);

    // -- recovery -----------------------------------------------------------

    // Live is wrecked. The previous save is a real one, so that is where this
    // should come from.
    const wanted = (await peek(store, "previous", profile.id)).profile.name;
    await plant(store, "profiles", profile.id, NOT_A_PROFILE);

    listed = await store.list();
    check("a wrecked live record is rescued from the previous save",
          listed.profiles.length === 1 && listed.profiles[0].name === wanted,
          listed.profiles.map(p => p.name).join(",") || "nothing came back");
    check("and it says where it came from",
          listed.recoveries.length === 1
          && listed.recoveries[0].cameFrom === "the previous save"
          && listed.recoveries[0].profileName === wanted,
          listed.recoveries.map(r => r.cameFrom).join(","));

    const brokenKeys = await peekKeys(store, "broken");
    check("the wrecked record is kept, not thrown away",
          brokenKeys.length === 1 && brokenKeys[0].startsWith(`${profile.id}.broken-`),
          brokenKeys.join(","));
    check("and it is the wrecked one that was kept",
          same((await peek(store, "broken", brokenKeys[0])), NOT_A_PROFILE));
    check("its key says which profile and when",
          /^[0-9a-f]+\.broken-\d{4}-\d{2}-\d{2}-\d{6}\.\d{3}$/.test(brokenKeys[0]),
          brokenKeys[0]);

    listed = await store.list();
    check("a second look does not rescue it all over again",
          listed.recoveries.length === 0 && listed.profiles.length === 1,
          `${listed.recoveries.length} recoveries`);

    // This is the one that matters most. If the wrecked record had been left
    // in place, this save would have moved it into previous and the backup
    // that just saved us would be gone.
    profile.name = "Kitchen after the rescue";
    await store.save(profile);
    check("the save after a rescue does not overwrite the backup with rubbish",
          S.looksLikeAProfile((await peek(store, "previous", profile.id)).profile),
          "previous is not a profile any more");

    // Now wreck both, and leave the snapshots alone.
    await plant(store, "profiles", profile.id, NOT_A_PROFILE);
    await plant(store, "previous", profile.id, NOT_A_PROFILE);
    const newestSnapshot = (await store.snapshots(profile.id))[0];

    listed = await store.list();
    check("with the previous save wrecked too, a dated backup is used",
          listed.profiles.length === 1
          && listed.profiles[0].name === newestSnapshot.name,
          listed.profiles.map(p => p.name).join(",") || "nothing came back");
    check("and it says which day it came from",
          listed.recoveries.length === 1
          && listed.recoveries[0].cameFrom === `the backup from ${newestSnapshot.day}`,
          listed.recoveries.map(r => r.cameFrom).join(","));

    // -- what a forgiving loader would have got wrong -----------------------

    const orphan = "aaaa0001";
    await plant(store, "profiles", orphan, NOT_A_PROFILE);
    listed = await store.list();
    check("a stray JSON record does not become a blank profile",
          !listed.profiles.some(p => p.id === orphan)
          && !listed.profiles.some(p => p.name === "Untitled"),
          listed.profiles.map(p => p.name).join(","));
    check("it is reported rather than silently missing",
          listed.refused.length === 1 && listed.refused[0].id === orphan,
          `${listed.refused.length} refused`);
    await store.delete(orphan);

    // -- a profile from a newer version of the app -------------------------

    const future = "aaaa0002";
    const ahead = madeUp("From the future").toDict();
    ahead.id = future;
    ahead.schema = M.SCHEMA + 1;
    ahead.something_new = "a field this build has never heard of";
    await plant(store, "profiles", future, { savedAt: Date.now(), profile: ahead });
    const brokenBefore = (await peekKeys(store, "broken")).length;

    listed = await store.list();
    check("a profile from a newer version is not opened",
          !listed.profiles.some(p => p.id === future),
          listed.profiles.map(p => p.name).join(","));
    check("it is reported with a reason",
          listed.refused.some(r => r.id === future && /newer version/.test(r.why)),
          listed.refused.map(r => r.why).join(" | "));
    check("and nothing of it is touched, so the newer app still has it",
          same((await peek(store, "profiles", future)).profile, ahead)
          && (await peekKeys(store, "broken")).length === brokenBefore,
          "the record was moved or altered");
    check("loading it directly refuses too",
          (await store.load(future)) === null);
    await store.delete(future);

    // -- an older format ---------------------------------------------------

    const old = "aaaa0003";
    await plant(store, "profiles", old, { savedAt: Date.now(), profile: {
      id: old, name: "An old file", schema: 1, floors: [{ id: "f1", rooms: [
        { id: "r1", points: M.rectanglePoints(400, 300),
          containers: [{ id: "c1", height: 60 }] }] }] } });
    const migrated = await store.load(old);
    check("a version 1 record gets its heights halved on the way in",
          migrated.floors[0].rooms[0].containers[0].height === 30,
          `height came out ${migrated?.floors[0].rooms[0].containers[0].height}`);
    check("and it is current by the time it has loaded",
          migrated.schema === M.SCHEMA);
    // Not a check on storage.js so much as on the promise it leans on: a
    // migration edits the object it is given, and this stays right only
    // because IndexedDB hands back a fresh copy on every read. If that were
    // ever untrue, the second load would come back halved again.
    check("reading an old record twice does not halve it twice",
          (await store.load(old)).floors[0].rooms[0].containers[0].height === 30,
          "the stored record was migrated in place");
    await store.delete(old);

    // -- restore -----------------------------------------------------------

    const beforeRestore = (await store.load(profile.id)).name;
    const day = (await store.snapshots(profile.id))[1];
    const restored = await store.restore(profile.id, day.day);
    check("restoring a dated backup brings it back",
          restored.name === day.name
          && (await store.load(profile.id)).name === day.name,
          `${restored.name} vs ${day.name}`);
    check("and what it replaced is still in the previous save",
          (await peek(store, "previous", profile.id)).profile.name === beforeRestore,
          beforeRestore);

    let refusedRestore = "";
    try {
      await store.restore(profile.id, "1999-01-01");
    } catch (error) {
      refusedRestore = error.message;
    }
    check("restoring a day with no backup says so and changes nothing",
          /no backup/.test(refusedRestore)
          && (await store.load(profile.id)).name === day.name,
          refusedRestore || "it did not complain");

    // -- deleting ----------------------------------------------------------

    const doomed = madeUp("Doomed");
    store.today = () => "2026-10-01";
    await store.save(doomed);
    store.today = () => "2026-10-02";
    await store.save(doomed);
    await store.delete(doomed.id);
    check("a deleted profile is gone from the list",
          !(await store.list()).profiles.some(p => p.id === doomed.id));
    check("its previous save goes with it",
          (await peek(store, "previous", doomed.id)) === undefined);
    check("but its dated backups are kept",
          (await store.snapshots(doomed.id)).length === 1,
          "deleting the wrong profile is the accident this is all for");
    check("deleting something twice is not an error",
          await store.delete(doomed.id).then(() => true, () => false));

    // -- export and import -------------------------------------------------

    const sent = M.Profile.fromDict(madeUp("Carried across").toDict());
    const text = S.exportText(sent);
    check("exported text reads back as the same profile",
          same(S.readExport(text).toDict(), sent.toDict()));
    check("exported text is indented, so a person can read it",
          text.includes("\n  \"name\""), JSON.stringify(text.slice(0, 24)));

    const imported = await store.importProfile(text);
    check("importing something new keeps its id",
          imported.id === sent.id, `${imported.id} vs ${sent.id}`);

    const twice = await store.importProfile(text);
    check("importing it again does not overwrite the one already here",
          twice.id !== sent.id && (await store.load(sent.id)) !== null,
          `${twice.id} vs ${sent.id}`);
    check("the second copy is named as a copy",
          twice.name === M.copyName(sent.name, [sent.name]), twice.name);

    for (const [bad, expected] of [["not json at all", /not JSON/],
                                   ['{"a":1}', /not an Invenfloor profile/],
                                   ['[]', /not an Invenfloor profile/]]) {
      let complaint = "";
      try {
        S.readExport(bad);
      } catch (error) {
        complaint = error.message;
      }
      check(`importing ${JSON.stringify(bad)} says why it will not`,
            expected.test(complaint), complaint || "it did not complain");
    }

    // -- the launcher's order ----------------------------------------------

    for (const name of ["zebra", "Apple", "mango"]) {
      await store.save(madeUp(name));
    }
    const names = (await store.list()).profiles.map(p => p.name)
                      .filter(n => ["zebra", "Apple", "mango"].includes(n));
    check("profiles come back sorted by name, ignoring case",
          same(names, ["Apple", "mango", "zebra"]), names.join(","));

    // -- file names --------------------------------------------------------

    check("a download is named after the profile and its id",
          S.fileNameFor(new M.Profile({ id: "a3f9c1d2", name: "Home" }))
          === "Home a3f9c1d2.json",
          S.fileNameFor(new M.Profile({ id: "a3f9c1d2", name: "Home" })));
    check("and a name full of awkward characters still makes a file name",
          S.fileNameFor(new M.Profile({ id: "a3f9c1d2", name: "C:/who\\knows?" }))
          === "Cwhoknows a3f9c1d2.json",
          S.fileNameFor(new M.Profile({ id: "a3f9c1d2", name: "C:/who\\knows?" })));
    check("a name with nothing usable in it still makes a file name",
          S.fileNameFor(new M.Profile({ id: "a3f9c1d2", name: "???" }))
          === "Profile a3f9c1d2.json",
          S.fileNameFor(new M.Profile({ id: "a3f9c1d2", name: "???" })));
  } catch (error) {
    check("the checks ran to the end", false,
          `${error?.message ?? error}\n${error?.stack ?? ""}`);
  } finally {
    if (store) {
      try {
        await store.destroy();
      } catch {
        // A database left behind is untidy, not wrong. The next run wipes it.
      }
    }
  }

  return results;
}

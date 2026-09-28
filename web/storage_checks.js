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
 * THE WHOLE SET RUNS TWICE
 * ------------------------
 * Once on a plain database and once on one with a passphrase over it. Not two
 * sets of checks, the same set, because that is the claim worth making about
 * encryption: it changes nothing. Backups still happen daily, a wrecked record
 * is still rescued from the same places in the same order, the launcher still
 * sorts the same way. If any of the fifty behaves differently with a lock on,
 * the lock is in the wrong place.
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
import * as V from "./vault.js";

// ---------------------------------------------------------------------------
// REACHING PAST THE FRONT DOOR
// ---------------------------------------------------------------------------
// Nothing in storage.js lets a caller write a broken record, which is correct
// and also means the checks have to go around it. These helpers touch the
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

/** The profile name inside a record, sealed or not.
 *
 *  Most of the checks below want to know which version of a profile ended up
 *  in a particular slot. Reading `.profile.name` off the raw record works
 *  until there is a passphrase, at which point there is no `.profile` to
 *  read. This asks the store to open it, so the same check reads the same way
 *  in both runs.
 */
async function nameAt(store, storeName, key) {
  const opened = await store._unseal(await peek(store, storeName, key));
  return opened?.profile?.name ?? null;
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

/** Valid JSON, and not a profile. What the gate in storage.js is for.
 *
 *  Deliberately planted unsealed, even in the locked run. A record that is
 *  not ours is not going to be encrypted the way ours are, so this is the
 *  more realistic corruption of the two. The locked run adds the other kind,
 *  a sealed record with a byte changed, further down. */
const NOT_A_PROFILE = { savedAt: 1, profile: { hello: "world" } };

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Did this throw, and with what? Returns something to read, or "" if it did
 *  not throw at all.
 *
 *  The name is a fallback and not a nicety. Web Crypto rejects with a
 *  DOMException whose message is the empty string in Chrome, where node fills
 *  in a sentence, so a check written as "did it come back with a message"
 *  passes in node and fails in a browser for no reason anybody would guess
 *  from reading it. Falling back to the name keeps the answer truthful in
 *  both. This is exactly why the checks run in a real browser and not only
 *  under a stand-in.
 */
async function refusedWith(work) {
  try {
    await work();
    return "";
  } catch (error) {
    return error?.message || error?.name || String(error) || "it threw";
  }
}

// ---------------------------------------------------------------------------
// THE CHECKS
// ---------------------------------------------------------------------------

/** Run every check against a database of its own. Returns
 *  [{ label, ok, why }] in the order they ran.
 *
 *  Pass a passphrase to run the whole set with a lock on. The database is
 *  deleted before and after either way, so this never touches real profiles
 *  and never depends on what a previous run left behind.
 */
export async function runStorageChecks(databaseName = "invenfloor-checks",
                                       { passphrase = null } = {}) {
  const results = [];
  const check = (label, ok, why = "") => results.push({ label, ok, why: String(why) });
  let store = null;
  let recoveryCode = null;

  try {
    await wipe(databaseName);
    store = await S.Store.open(databaseName);

    if (passphrase) {
      check("a database with no lock on it does not claim to have one",
            !store.hasLock && !store.locked);
      recoveryCode = await store.addLock(passphrase);
      check("adding a passphrase gives back a recovery code",
            /^[0-9A-Z]{5}(-[0-9A-Z]{5}){3}$/.test(recoveryCode), recoveryCode);
      check("and the store is unlocked once it is set up",
            store.hasLock && !store.locked);
    }

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

    if (passphrase) {
      const raw = await peek(store, "profiles", profile.id);
      check("what is actually in the database is sealed",
            raw.profile === undefined && Boolean(raw.sealed)
            && raw.sealed.iv.length === 12,
            JSON.stringify(Object.keys(raw)));
      check("and the ciphertext holds none of the words you typed",
            !new TextDecoder().decode(new Uint8Array(raw.sealed.body))
                 .includes("Kitchen"));
      check("the id stays readable, because it is the key it is filed under",
            raw.id === profile.id);
    }

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
          (await nameAt(store, "previous", profile.id)) === "Kitchen three");

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
    const wanted = await nameAt(store, "previous", profile.id);
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
          (await nameAt(store, "previous", profile.id)) !== null,
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
          (await nameAt(store, "previous", profile.id)) === beforeRestore,
          beforeRestore);

    const refusedRestore = await refusedWith(
      () => store.restore(profile.id, "1999-01-01"));
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
    if (passphrase) {
      // Deliberate, and the interface has to say so where somebody can see
      // it. An export that only opens in the browser that made it is not a
      // backup, it is a second thing to lose the key to.
      check("an export is readable even with a passphrase on the database",
            text.includes("Carried across"));
    }

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
      const complaint = await refusedWith(() => S.readExport(bad));
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

    // -- everything that only applies with a lock on ------------------------

    if (passphrase) {
      const kept = (await store.load(profile.id)).name;

      store.relock();
      check("relocking shuts it again", store.locked);
      check("and nothing can be read while it is shut",
            /locked/i.test(await refusedWith(() => store.list())));
      check("nor written",
            /locked/i.test(await refusedWith(() => store.save(profile))));
      check("but the ids are still countable, for a launcher to say how many",
            (await store.ids()).length > 0);
      check("and so are the dates",
            (await store.savedAt(profile.id)) !== null);

      check("the wrong passphrase is refused",
            (await refusedWith(() => store.unlock("not it"))).length > 0);
      check("and it stays shut after being told the wrong one", store.locked);

      check("the right one opens it",
            (await store.unlock(passphrase)) === "passphrase");
      check("and everything is where it was left",
            (await store.load(profile.id)).name === kept, kept);

      store.relock();
      check("the recovery code opens it too, typed however it was written down",
            (await store.unlock(recoveryCode.toLowerCase().replace(/-/g, " ")))
            === "recovery");

      // A sealed record with one byte changed. The other kind of damage, and
      // the one encryption itself catches: AES-GCM checks the whole record
      // before handing anything back, so a single flipped bit is refused
      // rather than quietly turning into nonsense.
      const good = await peek(store, "profiles", profile.id);
      const bent = new Uint8Array(good.sealed.body.slice(0));
      bent[0] ^= 1;
      await plant(store, "profiles", profile.id,
                  { ...good, sealed: { iv: good.sealed.iv, body: bent.buffer } });
      listed = await store.list();
      check("one altered byte in a sealed record is caught and rescued",
            listed.recoveries.some(r => r.profileName === kept)
            || listed.profiles.some(p => p.id === profile.id),
            listed.refused.map(r => r.why).join(" | "));

      // Changing the passphrase must not touch a single stored record.
      const before = await peek(store, "profiles", profile.id);
      await store.changePassphrase(passphrase, "a completely different one");
      check("changing the passphrase leaves the records alone",
            same(await peek(store, "profiles", profile.id), before));
      check("the old passphrase stops working",
            (await refusedWith(async () => {
              store.relock();
              await store.unlock(passphrase);
            })).length > 0);
      check("the new one works",
            (await store.unlock("a completely different one")) === "passphrase");
      check("and the recovery code is deliberately left alone",
            (await refusedWith(async () => {
              store.relock();
              await store.unlock(recoveryCode);
            })) === "");

      const freshCode = await store.newRecoveryCode();
      store.relock();
      check("a reissued recovery code works",
            (await store.unlock(freshCode)) === "recovery");
      store.relock();
      check("and the one it replaced does not",
            (await refusedWith(() => store.unlock(recoveryCode))).length > 0);

      // The real test of any of this: close the database and open it again.
      await store.unlock(freshCode);
      const namesBefore = (await store.list()).profiles.map(p => p.name).sort();
      store.close();
      store = await S.Store.open(databaseName);
      check("a reopened database knows it has a lock",
            store.hasLock && store.locked);
      await store.unlock("a completely different one");
      check("and gives everything back once it is opened",
            same((await store.list()).profiles.map(p => p.name).sort(),
                 namesBefore));

      // Something sealed under a key this store has never had, which is what
      // a broken record set aside before a passphrase change looks like.
      // Taking the lock off must not write null over it.
      const stranger = await V.create("somebody else's passphrase");
      const orphaned = { id: "aaaa0009", savedAt: 5,
                         sealed: await V.seal(stranger.key, "aaaa0009",
                                              { id: "aaaa0009", floors: [] }) };
      await plant(store, "broken", "aaaa0009.broken-one", orphaned);

      await store.removeLock();
      check("taking the passphrase off leaves the profiles readable",
            !store.hasLock
            && (await peek(store, "profiles", profile.id)).profile !== undefined);
      check("and they still all load",
            same((await store.list()).profiles.map(p => p.name).sort(),
                 namesBefore));
      check("a record that will not open is kept as it is, not wiped",
            same(await peek(store, "broken", "aaaa0009.broken-one"), orphaned),
            "unreadable is not the same as worthless");
    }
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

// ---------------------------------------------------------------------------
// THE VAULT ON ITS OWN
// ---------------------------------------------------------------------------

/** Checks for vault.js that do not need a database.
 *
 *  Kept apart from the storage checks because they are asking a different
 *  question. Those ask whether a lock changes how saving behaves. These ask
 *  whether the lock is any good.
 */
export async function runVaultChecks() {
  const results = [];
  const check = (label, ok, why = "") => results.push({ label, ok, why: String(why) });

  try {
    check("Web Crypto is here at all", V.available(),
          "needs https or localhost");

    const started = Date.now();
    const { record, key, recoveryCode } = await V.create("a passphrase");
    const setUp = Date.now() - started;
    check("setting up a lock takes long enough to be worth guessing at",
          setUp > 20, `${setUp}ms for two derivations at ${V.ITERATIONS} rounds`);

    check("the recovery code is 20 characters in groups of five",
          /^[0-9A-Z]{5}(-[0-9A-Z]{5}){3}$/.test(recoveryCode), recoveryCode);
    check("its alphabet leaves out the letters people mistype",
          !/[ILOU]/.test(recoveryCode), recoveryCode);
    check("two codes in a row are not the same",
          V.newRecoveryCode() !== V.newRecoveryCode());
    check("a code retyped in lower case with spaces still counts",
          V.tidyRecoveryCode(recoveryCode.toLowerCase().replace(/-/g, " "))
          === V.tidyRecoveryCode(recoveryCode));
    check("and a written O or l is read as the 0 or 1 it was meant to be",
          V.tidyRecoveryCode("O1lI0") === "01110");
    check("but Q and V are left alone, because they are real symbols here",
          V.tidyRecoveryCode("QV") === "QV");

    check("the passphrase is nowhere in what gets stored",
          !JSON.stringify(record).includes("a passphrase"));
    check("neither is the recovery code",
          !JSON.stringify(record).includes(recoveryCode.replace(/-/g, "")));
    check("there are two ways in and no more",
          record.locks.length === 2
          && same(record.locks.map(l => l.kind).sort(), ["passphrase", "recovery"]),
          record.locks.map(l => l.kind).join(","));
    check("each way in has its own salt",
          !same(record.locks[0].salt, record.locks[1].salt));

    const sealed = await V.seal(key, "a3f9c1d2", { name: "Kitchen" });
    check("a sealed value gives nothing away",
          !new TextDecoder().decode(new Uint8Array(sealed.body)).includes("Kitchen"));
    check("and comes back out the same",
          same(await V.open(key, "a3f9c1d2", sealed), { name: "Kitchen" }));

    const twice = await V.seal(key, "a3f9c1d2", { name: "Kitchen" });
    check("sealing the same thing twice never repeats the iv",
          !same(sealed.iv, twice.iv),
          "reusing one with the same key is the one unrecoverable mistake");
    check("and so never produces the same ciphertext",
          !same(new Uint8Array(sealed.body), new Uint8Array(twice.body)));

    check("it will not open under a different profile's id",
          (await refusedWith(() => V.open(key, "bbbbbbbb", sealed))).length > 0);

    const bent = new Uint8Array(sealed.body.slice(0));
    bent[2] ^= 1;
    check("one flipped bit is refused rather than half read",
          (await refusedWith(
            () => V.open(key, "a3f9c1d2", { iv: sealed.iv, body: bent.buffer })))
          .length > 0);

    const opened = await V.unlock(record, "a passphrase");
    check("the passphrase opens it", opened.usedKind === "passphrase");
    check("and the key it gives back opens what the first one sealed",
          same(await V.open(opened.key, "a3f9c1d2", sealed), { name: "Kitchen" }));
    check("the recovery code opens it too",
          (await V.unlock(record, recoveryCode)).usedKind === "recovery");

    let kind = "";
    try {
      await V.unlock(record, "nearly the passphrase");
    } catch (error) {
      kind = error.name;
    }
    check("a wrong secret is refused, and says so in its own words",
          kind === "WrongSecret", kind);
  } catch (error) {
    check("the vault checks ran to the end", false,
          `${error?.message ?? error}\n${error?.stack ?? ""}`);
  }

  return results;
}

/**
 * storage.js
 * ==========
 *
 * Reading and writing saves in a browser. Nothing in here knows anything
 * about canvases or screens, and nothing outside this file touches the
 * database.
 *
 * This is the twin of storage.py on purpose: the same names in the same
 * order, and the same three answers to "what survives a bad day". Two
 * reasons. The pair can be read side by side, which is how they stay honest
 * about each other. And when there is a server, it is this file that gets
 * replaced rather than every screen that calls it.
 *
 * WHERE THE SAVES GO
 * ------------------
 * IndexedDB. Every browser has had it for a decade, on desktops and on
 * phones, which is the whole reason the web version is worth building.
 *
 * It is per browser and per origin. Profiles made in Chrome on a desktop are
 * not the profiles Safari shows on a phone, and nothing here can make them
 * the same, because there is no server yet. Say that out loud in the
 * interface rather than letting someone find out by looking for a profile
 * that was never going to be there.
 *
 * ONE RECORD PER PROFILE
 * ----------------------
 * storage.py keeps one .json file per profile. Here that is four object
 * stores, keyed the way those files were named:
 *
 *     profiles    a3f9c1d2                 <-  a3f9c1d2.json
 *     previous    a3f9c1d2                 <-  a3f9c1d2.json.bak
 *     backups     a3f9c1d2-2026-09-20      <-  backups/a3f9c1d2-2026-09-20.json
 *     broken      a3f9c1d2.broken-<stamp>  <-  the file that was set aside
 *
 * A store for each job rather than one store with prefixed keys, so that what
 * a record is never has to be worked out by reading its key.
 *
 * WHAT IS DIFFERENT FROM THE PYTHON, AND WHY
 * ------------------------------------------
 * *Everything here is async.* There is no synchronous way to touch
 * IndexedDB, so every function below returns a promise and every caller
 * awaits. That is the one difference that reaches out of this file.
 *
 * *There is no temporary file, no fsync and no rename dance.* An IndexedDB
 * transaction commits entirely or not at all, and the browser is the one
 * responsible for getting it onto the disk. So the careful three-step write
 * in storage.py collapses into one transaction here, and the sliver of time
 * that file has between its two renames does not exist. This is the one place
 * the browser version is stronger rather than weaker.
 *
 * *There is no modification time*, because there is no file. A savedAt goes
 * in the record instead.
 *
 * *There is no parse step*, because IndexedDB hands back an object rather
 * than text. A record cannot arrive half-written. What is left of the
 * recovery path is a bad import and a profile written by a newer version of
 * the app, and both of those are real, so the path stays.
 *
 * *The browser can throw all of it away.* Storage is evicted when a disk
 * fills, and Safari clears script storage after a week of not visiting the
 * site. requestPersistence below asks the browser not to, and the browser is
 * allowed to say no. So export is not a nicety in the web version the way it
 * is on the desktop. It is the backup that outlives the browser, and the
 * interface should push people towards it.
 */
import { Profile, cleanName, copyName, newId, SCHEMA, schemaOf } from "./model.js";

export const DATABASE_NAME = "invenfloor";
export const DATABASE_VERSION = 1;

// How many daily snapshots to keep per profile. Ten days of use, not ten
// calendar days: a fortnight away from the app doesn't cost you any history.
export const DAYS_KEPT = 10;

const LIVE = "profiles";
const PREVIOUS = "previous";
const SNAPSHOTS = "backups";
const BROKEN = "broken";
const ALL_STORES = [LIVE, PREVIOUS, SNAPSHOTS, BROKEN];

/** Today, as a string, on the clock of whoever is looking.
 *
 *  Local rather than UTC because the point of a daily snapshot is "the state
 *  at the start of a day I was using the app", and the day someone means is
 *  the one on their own wall. Its own function so a check can stand somewhere
 *  else in time without waiting a day to find out whether this works.
 */
export function today(when = new Date()) {
  const pad = number => String(number).padStart(2, "0");
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
}

/** A stamp for a record set aside: 2026-09-27-143002.481.
 *
 *  Down to the millisecond, where storage.py stops at the second. The point
 *  of setting a bad record aside is to keep it, and two rescues inside one
 *  second would land on the same key and the second would write over the
 *  first. Unlikely, and the whole reason this key exists is the unlikely.
 */
function stamp(when = new Date()) {
  const pad = (number, width = 2) => String(number).padStart(width, "0");
  return `${today(when)}-${pad(when.getHours())}${pad(when.getMinutes())}`
         + `${pad(when.getSeconds())}.${pad(when.getMilliseconds(), 3)}`;
}

// ---------------------------------------------------------------------------
// PROMISES OVER AN EVENT-BASED API
// ---------------------------------------------------------------------------

/** The result of one IndexedDB request, as a promise. */
function done(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/** Resolves once a transaction has actually committed.
 *
 *  Awaiting the last request inside a transaction is not the same as knowing
 *  it landed. A transaction can still fail on the way down, and until
 *  oncomplete fires, nothing is saved.
 */
function committed(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () =>
      reject(transaction.error
             ?? new Error("The save was abandoned by the browser."));
  });
}

/** Every key in a store that belongs to one profile.
 *
 *  Snapshot keys are "<id>-<day>", so a bounded range picks out one profile's
 *  snapshots and nobody else's. Ids are always the same length, so no id can
 *  be the beginning of another one and there is no way for this range to
 *  reach into a neighbor.
 */
function keysFor(where, profileId) {
  return done(where.getAllKeys(
    IDBKeyRange.bound(`${profileId}-`, `${profileId}-￿`)));
}

// ---------------------------------------------------------------------------
// IS THIS SOMETHING WE WROTE
// ---------------------------------------------------------------------------

/** Is this parsed object a profile?
 *
 *  Lifted from storage.py, reasoning and all, because the reasoning survives
 *  the move. Profile.fromDict is forgiving by design: every field is read
 *  with a default so that adding a field never breaks an older save. Carried
 *  to its end that means fromDict will happily turn {"hello": "world"} into a
 *  profile named "Untitled" with a freshly minted id, a blank that looks real
 *  enough to pass any test applied to the object afterwards.
 *
 *  Which would be merely odd, except that a blank which loads is a blank that
 *  never triggers recovery. So the gate belongs here, before fromDict, and it
 *  asks the one question fromDict cannot: did the file itself carry these
 *  fields, or are we looking at defaults? Every profile this program has ever
 *  written has both an id and a floors list, including the first version of
 *  the format.
 */
export function looksLikeAProfile(raw) {
  return Boolean(raw) && typeof raw === "object" && !Array.isArray(raw)
         && typeof raw.id === "string" && raw.id.length > 0
         && Array.isArray(raw.floors);
}

/** Written by a version of Invenfloor newer than this one?
 *
 *  Worth catching rather than shrugging at. migrate only ever moves a file
 *  forward, so a schema 3 file handed to a build that knows up to 2 passes
 *  straight through, loses every field this build has never heard of, and
 *  then the next save writes it back as a schema 2 file with the missing
 *  parts gone for good. Silent, permanent, and the kind of thing that only
 *  happens on the machine which is one update behind.
 *
 *  So a profile from the future is not opened at all. It is reported, and the
 *  interface says to update before touching it.
 */
function fromTheFuture(raw) {
  return schemaOf(raw) > SCHEMA;
}

// ---------------------------------------------------------------------------
// WHAT COMES BACK FROM A LOAD
// ---------------------------------------------------------------------------

/** A profile that would not load from its own record, and what we did. */
export class Recovery {
  constructor(profileName, cameFrom, brokenKey) {
    this.profileName = profileName;
    this.cameFrom = cameFrom;       // a phrase for a human: "the previous save"
    this.brokenKey = brokenKey;     // where the bad one went, so it can be seen
  }
}

/** A profile that could not be opened at all, and why.
 *
 *  storage.py has no equivalent: it returns None, the caller skips it, and
 *  the profile simply is not in the launcher any more. A save going quietly
 *  missing is the worst possible way to tell somebody about it, so this
 *  version says so instead.
 */
export class Refused {
  constructor(id, name, why) {
    this.id = id;
    this.name = name;               // best guess, and "" when even that failed
    this.why = why;                 // a sentence to put in front of someone
  }
}

// ---------------------------------------------------------------------------
// THE STORE
// ---------------------------------------------------------------------------

export class Store {
  /** Open the database, creating it the first time.
   *
   *  The name is a parameter for one reason: the checks need a database of
   *  their own so that running them can never touch real profiles. Nothing
   *  else should pass it.
   */
  static open(name = DATABASE_NAME) {
    return new Promise((resolve, reject) => {
      let request;
      try {
        request = indexedDB.open(name, DATABASE_VERSION);
      } catch (error) {
        // Safari in private browsing used to throw right here, and a browser
        // with site data switched off still can. The app can carry on without
        // saving, so this has to be an error the caller can read and explain
        // rather than an exception out of nowhere.
        reject(new Error(`This browser will not open a database: ${error.message}`));
        return;
      }

      request.onupgradeneeded = () => {
        const database = request.result;
        for (const name of ALL_STORES) {
          if (database.objectStoreNames.contains(name)) continue;
          // No keyPath: the key is passed in on every put. A snapshot's key is
          // not a field of a profile, and one rule for all four stores beats
          // two rules.
          database.createObjectStore(name);
        }
      };
      request.onsuccess = () => resolve(new Store(request.result, name));
      request.onerror = () => reject(request.error);
      request.onblocked = () =>
        reject(new Error("Another tab has Invenfloor open on an older version. "
                         + "Close it and reload."));
    });
  }

  constructor(database, name = DATABASE_NAME) {
    this.database = database;
    this.name = name;
    // Replaceable so a check can stand somewhere else in time. See today().
    this.today = today;
  }

  close() {
    this.database.close();
  }

  /** Throw the whole database away. For the checks, and for a "start over"
   *  button if one is ever wanted. */
  destroy() {
    this.close();
    return new Promise((resolve, reject) => {
      const request = indexedDB.deleteDatabase(this.name);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
      request.onblocked = () =>
        reject(new Error("Something still has the database open."));
    });
  }

  // -- writing --------------------------------------------------------------

  /** Save one profile, keeping what was there before. Returns the savedAt.
   *
   *  The order matters, and it is the order storage.py uses:
   *
   *  1. Take today's snapshot first, while the old record is still the live
   *     one. A snapshot taken after the write would hold the new state, which
   *     is not a backup of anything.
   *  2. Move the old record to previous.
   *  3. Put the new one in its place.
   *
   *  All three in one transaction, so there is no moment at which a crash
   *  could leave two of them done and one not.
   *
   *  THE AWAITS IN HERE ARE LOAD-BEARING. A transaction stays open only while
   *  requests keep being made from the chain of microtasks it started.
   *  Awaiting an IndexedDB request is fine, because that request is what
   *  resolves it. Awaiting anything else, a fetch, a timer, reading a file,
   *  hands control back to the browser, the transaction commits early, and
   *  the next line throws TransactionInactiveError. If this ever needs
   *  something from outside the database, get it before the transaction opens.
   */
  async save(profile) {
    const record = { savedAt: Date.now(), profile: profile.toDict() };

    const transaction = this.database.transaction(
      [LIVE, PREVIOUS, SNAPSHOTS], "readwrite");
    const live = transaction.objectStore(LIVE);

    const old = await done(live.get(profile.id));
    if (old !== undefined) {
      await this._keepTodaysSnapshot(
        transaction.objectStore(SNAPSHOTS), profile.id, old);
      transaction.objectStore(PREVIOUS).put(old, profile.id);
    }
    live.put(record, profile.id);

    await committed(transaction);
    return record.savedAt;
  }

  /** Copy the live record into the snapshots once a day, then prune.
   *
   *  Per day rather than per save, and the reason is worth spelling out.
   *  Saves are debounced at half a second, so a ten-deep per-save history
   *  would cover about five seconds and would cheerfully fill itself with ten
   *  copies of the very mistake you are trying to walk back. A day is the
   *  unit that matches how people actually notice something is missing.
   */
  async _keepTodaysSnapshot(snapshots, profileId, record) {
    const key = `${profileId}-${this.today()}`;
    if (await done(snapshots.count(key))) return;      // already have today's

    snapshots.put(record, key);

    // The list includes the one just written, which is what we want:
    // DAYS_KEPT counts snapshots, and today's is one of them.
    const keys = await keysFor(snapshots, profileId);
    keys.sort().reverse();
    for (const stale of keys.slice(DAYS_KEPT)) snapshots.delete(stale);
  }

  // -- reading --------------------------------------------------------------

  /** Every profile, plus a Recovery for each one that needed rescuing and a
   *  Refused for each one that could not be opened at all.
   *
   *  The transaction is readwrite because recovery writes. In the ordinary
   *  case, which is very nearly every case, it writes nothing.
   */
  async list() {
    const transaction = this.database.transaction(ALL_STORES, "readwrite");
    const profiles = [];
    const recoveries = [];
    const refused = [];

    for (const id of await done(transaction.objectStore(LIVE).getAllKeys())) {
      const found = await this._loadOne(transaction, id);
      if (found.profile === null) {
        refused.push(found.refused);
        continue;
      }
      profiles.push(found.profile);
      if (found.recovery) {
        found.recovery.profileName = found.profile.name;
        recoveries.push(found.recovery);
      }
    }

    await committed(transaction);

    // Sorted by name so the launcher shows a stable, predictable order rather
    // than whatever order the database happened to hand back.
    profiles.sort((a, b) =>
      a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    return { profiles, recoveries, refused };
  }

  /** One profile by id, rescued the same way. Null if there is nothing
   *  readable under that id anywhere. */
  async load(id) {
    const transaction = this.database.transaction(ALL_STORES, "readwrite");
    const found = await this._loadOne(transaction, id);
    await committed(transaction);
    return found.profile;
  }

  /** Read one profile, falling back through its backups.
   *
   *  Returns { profile, recovery, refused }. The profile is null when nothing
   *  anywhere could be read, and then refused says why. The recovery is null
   *  in the ordinary case where the record was fine.
   */
  async _loadOne(transaction, id) {
    const live = transaction.objectStore(LIVE);
    const record = await done(live.get(id));

    // A profile from the future is not a broken profile, and reaching for a
    // backup would be wrong: its backups are from the future too, and the
    // live record is the newest thing there is. Leave all of it alone.
    if (record !== undefined && fromTheFuture(record.profile)) {
      return { profile: null, recovery: null,
               refused: new Refused(id, nameIn(record),
                 "Saved by a newer version of Invenfloor. Update before "
                 + "opening it, or this version would quietly drop the parts "
                 + "it does not understand.") };
    }

    const built = build(record);
    if (built) return { profile: built, recovery: null, refused: null };

    for (const [place, description] of await this._fallbacks(transaction, id)) {
      const spare = await done(place.store.get(place.key));
      if (spare !== undefined && fromTheFuture(spare.profile)) continue;

      const rescued = build(spare);
      if (!rescued) continue;

      // The bad record has to move out of the way, and that is not tidiness.
      // Leaving it in place would mean the next save moves the BROKEN record
      // into previous, destroying the very backup we just read from. Setting
      // it aside keeps it as evidence and breaks that chain.
      const brokenKey = `${id}.broken-${stamp()}`;
      if (record !== undefined) {
        transaction.objectStore(BROKEN).put(record, brokenKey);
      }
      live.put(spare, id);

      return { profile: rescued,
               recovery: new Recovery("", description, brokenKey),
               refused: null };
    }

    return { profile: null, recovery: null,
             refused: new Refused(id, nameIn(record),
               record === undefined
                 ? "There is nothing saved under this id."
                 : "This profile would not open, and neither would any of "
                   + "its backups.") };
  }

  /** Everywhere worth looking when the live record is no good, best first.
   *
   *  The previous save comes before the dated snapshots because it is newer
   *  than all of them: a snapshot is the state at the START of a day, and
   *  previous is one save ago.
   */
  async _fallbacks(transaction, id) {
    const snapshots = transaction.objectStore(SNAPSHOTS);
    const places = [
      [{ store: transaction.objectStore(PREVIOUS), key: id }, "the previous save"],
    ];

    const keys = await keysFor(snapshots, id);
    keys.sort().reverse();
    for (const key of keys) {
      // "a3f9c1d2-2026-09-20" -> "2026-09-20"
      places.push([{ store: snapshots, key },
                   `the backup from ${key.slice(id.length + 1)}`]);
    }
    return places;
  }

  /** When this profile was last saved, in milliseconds, or null.
   *
   *  The file system was keeping this for us on the desktop. Here it is in
   *  the record, which is the next best thing: written by the same put that
   *  wrote the profile, so it cannot drift out of step with it.
   */
  async savedAt(id) {
    const transaction = this.database.transaction(LIVE, "readonly");
    const record = await done(transaction.objectStore(LIVE).get(id));
    return record?.savedAt ?? null;
  }

  /** Every dated snapshot for a profile, newest first, as
   *  { day, savedAt, name }.
   *
   *  The desktop app answers "where are my backups" by opening the folder in
   *  Explorer. A browser has no folder to open, so the list has to come from
   *  here and the interface has to show it. Hence this, and restore below.
   */
  async snapshots(id) {
    const store = this.database.transaction(SNAPSHOTS, "readonly")
                      .objectStore(SNAPSHOTS);
    const keys = await keysFor(store, id);
    keys.sort().reverse();

    const found = [];
    for (const key of keys) {
      const record = await done(store.get(key));
      found.push({ day: key.slice(id.length + 1),
                   savedAt: record?.savedAt ?? null,
                   name: nameIn(record) });
    }
    return found;
  }

  /** Put a snapshot back as the live profile, keeping the current one.
   *
   *  What is being replaced goes to previous, exactly as an ordinary save
   *  would move it, so restoring the wrong day is itself undoable.
   */
  async restore(id, day) {
    const transaction = this.database.transaction(
      [LIVE, PREVIOUS, SNAPSHOTS], "readwrite");
    const live = transaction.objectStore(LIVE);

    const snapshot = await done(
      transaction.objectStore(SNAPSHOTS).get(`${id}-${day}`));
    if (snapshot === undefined) {
      transaction.abort();
      throw new Error(`There is no backup of that profile from ${day}.`);
    }

    const current = await done(live.get(id));
    if (current !== undefined) {
      transaction.objectStore(PREVIOUS).put(current, id);
    }
    live.put({ savedAt: Date.now(), profile: snapshot.profile }, id);

    await committed(transaction);
    return build(snapshot);
  }

  // -- deleting -------------------------------------------------------------

  /** Delete a profile and its previous save. Silently fine if already gone.
   *
   *  The dated snapshots are deliberately left alone. Deleting the wrong
   *  profile is exactly the accident this whole file exists for, and a
   *  snapshot that outlives its profile costs a few kilobytes.
   */
  async delete(id) {
    const transaction = this.database.transaction([LIVE, PREVIOUS], "readwrite");
    transaction.objectStore(LIVE).delete(id);
    transaction.objectStore(PREVIOUS).delete(id);
    await committed(transaction);
  }

  // -- importing ------------------------------------------------------------

  /** Read an exported profile and save it. Returns the profile as saved.
   *
   *  A profile whose id is already here gets a new id and a copy name rather
   *  than being written over. The file somebody is importing is usually a
   *  backup of a profile they still have, and quietly replacing the live one
   *  with a week-old copy is the exact accident the rest of this file exists
   *  to prevent. Two profiles is a mess anyone can tidy up in a minute. The
   *  other way around loses a week.
   */
  async importProfile(text) {
    const profile = readExport(text);

    const live = this.database.transaction(LIVE, "readonly").objectStore(LIVE);
    const ids = await done(live.getAllKeys());
    const records = await done(live.getAll());

    if (ids.includes(profile.id)) {
      profile.id = newId();
      profile.name = copyName(profile.name, records.map(nameIn));
    }

    await this.save(profile);
    return profile;
  }
}

/** The profile's name out of a record, or "" if there isn't one to be had. */
function nameIn(record) {
  const name = record?.profile?.name;
  return typeof name === "string" ? name : "";
}

/** A Profile out of a stored record, or null if that record is no good.
 *
 *  The catch is deliberately wide, for the same reason it is wide in
 *  storage.py. This is not untrusted input in the security sense, but it is
 *  data that can have been put there by an import, by a different version of
 *  the app, or by a browser having a bad day, and every one of those produces
 *  a different exception. The alternative to catching them all here is the
 *  app failing to start, which is a worse answer to every one of them.
 */
function build(record) {
  if (!record || !looksLikeAProfile(record.profile)) return null;
  try {
    // fromDict migrates in place, which would be a problem if this object
    // were the database's copy: a version 1 record would come out halved the
    // first time and already-halved the second. It is not. IndexedDB builds a
    // fresh copy of a value on every read, so editing what get() handed back
    // cannot reach the record. That guarantee is doing real work here, so
    // storage_checks.js loads an old record twice and checks it.
    return Profile.fromDict(record.profile);
  } catch (error) {
    console.warn("[storage] Could not read a profile:", error);
    return null;
  }
}

// ---------------------------------------------------------------------------
// EXPORT AND IMPORT
// ---------------------------------------------------------------------------

/** A profile as the text of a save file.
 *
 *  This reads in the desktop app, and what the desktop app writes reads here.
 *  Not byte for byte, and it is worth knowing where the two differ so that a
 *  diff showing changes is not mistaken for a problem:
 *
 *    - Python escapes everything outside ASCII, so a profile called Café is
 *      written there as "Café" and here as "Café".
 *    - Python writes a float as 30.0 where JavaScript writes 30.
 *
 *  Both reload to the same values in both programs, which is the claim that
 *  actually matters. Chasing byte equality would mean formatting numbers by
 *  hand here, and a hand-rolled number formatter is a far better source of
 *  bugs than a cosmetic diff.
 */
export function exportText(profile) {
  return JSON.stringify(profile.toDict(), null, 2);
}

/** What to call the downloaded file.
 *
 *  Named after the profile rather than after its id, because this one is
 *  going into somebody's Downloads folder where a3f9c1d2.json means nothing.
 *  The id goes on the end anyway: two profiles can share a name, and a
 *  download that silently becomes "Home (3).json" is harder to match back up
 *  than one which says which profile it came from.
 */
export function fileNameFor(profile) {
  // Windows will not have \ / : * ? " < > | in a file name, and a leading or
  // trailing dot or space is trouble on top of that. Anything outside letters,
  // digits, spaces, dashes and underscores goes, which is a wider net than
  // strictly needed and leaves nothing to check twice.
  const clean = cleanName(profile.name).replace(/[^\w \-]+/g, "").trim();
  return `${clean || "Profile"} ${profile.id}.json`;
}

/** Read exported text into a Profile, with a message worth showing if not.
 *
 *  Throws rather than returning null, because this one is always the result
 *  of somebody picking a file, and they are owed a reason.
 */
export function readExport(text) {
  let raw;
  try {
    raw = JSON.parse(text);
  } catch (error) {
    throw new Error(`That file is not JSON: ${error.message}`);
  }
  if (!looksLikeAProfile(raw)) {
    throw new Error("That is a JSON file, but not an Invenfloor profile.");
  }
  if (fromTheFuture(raw)) {
    throw new Error("That profile was saved by a newer version of Invenfloor. "
                    + "Update before importing it.");
  }
  return Profile.fromDict(raw);
}

/** Hand a profile to the browser as a download.
 *
 *  The only part of this file that touches the page, and it lives here rather
 *  than in a screen because it belongs beside exportText and fileNameFor.
 */
export function download(profile, page = document) {
  const blob = new Blob([exportText(profile)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = page.createElement("a");
  link.href = url;
  link.download = fileNameFor(profile);
  link.click();
  // Not revoked straight away: some browsers have not finished reading the
  // blob by the time click() returns, and revoking early cancels the save.
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

/** Ask the browser not to evict this site's storage. Returns what it said.
 *
 *  Worth asking, not worth relying on. Chrome grants it once a site looks
 *  like something the person actually uses. Safari says yes and evicts anyway
 *  after seven days of not visiting, unless the site has been added to the
 *  home screen. Which is why export exists.
 */
export async function requestPersistence() {
  if (!navigator.storage?.persist) return false;
  try {
    return await navigator.storage.persist();
  } catch {
    return false;
  }
}

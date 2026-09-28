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
 * stores, keyed the way those files were named, plus one for the lock:
 *
 *     profiles    a3f9c1d2                 <-  a3f9c1d2.json
 *     previous    a3f9c1d2                 <-  a3f9c1d2.json.bak
 *     backups     a3f9c1d2-2026-09-20      <-  backups/a3f9c1d2-2026-09-20.json
 *     broken      a3f9c1d2.broken-<stamp>  <-  the record that was set aside
 *     vault       vault                    <-  nothing on the desktop, see below
 *
 * A store for each job rather than one store with prefixed keys, so that what
 * a record is never has to be worked out by reading its key.
 *
 * A record is { id, savedAt, profile } while there is no lock, and
 * { id, savedAt, sealed } once there is. The id is repeated outside the
 * profile deliberately: records move between stores all the time, a save
 * moves one to previous and a restore moves one back, and the id is what the
 * encryption binds to, so it has to be readable without opening anything.
 *
 * LOCKING
 * -------
 * vault.js can put a passphrase over all of it. When there is one, everything
 * in the four stores is ciphertext and the only things left in the clear are
 * the ids, the dates and how many there are.
 *
 * It changes the shape of this file in one place, and it is worth knowing
 * why. Decrypting is asynchronous and is not a database request, so it cannot
 * happen inside a transaction: the first await that is not an IndexedDB call
 * hands control back to the browser and the transaction commits without you.
 * So reading is in three parts now. Gather every candidate record in one
 * read-only transaction, open them outside it, and if one had to be rescued,
 * repair in a second transaction afterwards. Writing did not need splitting;
 * it seals first and then opens one transaction, the same as before.
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
 * recovery path is a bad import, a profile written by a newer version of the
 * app, and a record that will not decrypt, and all three are real, so the
 * path stays.
 *
 * *The browser can throw all of it away.* Storage is evicted when a disk
 * fills, and Safari clears script storage after a week of not visiting the
 * site. requestPersistence below asks the browser not to, and the browser is
 * allowed to say no. So export is not a nicety in the web version the way it
 * is on the desktop. It is the backup that outlives the browser, and the
 * interface should push people towards it.
 */
import { Profile, cleanName, copyName, newId, SCHEMA, schemaOf } from "./model.js";
import * as vault from "./vault.js";

export const DATABASE_NAME = "invenfloor";

// 2 added the vault store. Nothing else changed, and the upgrade below only
// ever adds what is missing, so a database made by version 1 gains the store
// and keeps everything in it.
export const DATABASE_VERSION = 2;

// How many daily snapshots to keep per profile. Ten days of use, not ten
// calendar days: a fortnight away from the app doesn't cost you any history.
export const DAYS_KEPT = 10;

const LIVE = "profiles";
const PREVIOUS = "previous";
const SNAPSHOTS = "backups";
const BROKEN = "broken";
const VAULT = "vault";
const PROFILE_STORES = [LIVE, PREVIOUS, SNAPSHOTS, BROKEN];
const ALL_STORES = [...PROFILE_STORES, VAULT];
const VAULT_KEY = "vault";

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

/** Thrown when something needs the profiles and the passphrase is not in yet.
 *
 *  Its own class so a screen can send somebody to the unlock box instead of
 *  showing them an error.
 */
export class Locked extends Error {
  constructor(message = "The profiles in this browser are locked.") {
    super(message);
    this.name = "Locked";
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
  static async open(name = DATABASE_NAME) {
    const database = await new Promise((resolve, reject) => {
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
        const opened = request.result;
        for (const store of ALL_STORES) {
          if (opened.objectStoreNames.contains(store)) continue;
          // No keyPath: the key is passed in on every put. A snapshot's key is
          // not a field of a profile, and one rule for all five stores beats
          // two rules.
          opened.createObjectStore(store);
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () =>
        reject(new Error("Another tab has Invenfloor open on an older version. "
                         + "Close it and reload."));
    });

    const store = new Store(database, name);
    await store._readVault();
    return store;
  }

  constructor(database, name = DATABASE_NAME) {
    this.database = database;
    this.name = name;
    // Replaceable so a check can stand somewhere else in time. See today().
    this.today = today;

    // The lock, if there is one. `vaultRecord` is what is stored and is not a
    // secret; `key` is what opens the profiles and exists only in memory, only
    // while unlocked, and is never written anywhere.
    this.vaultRecord = null;
    this.key = null;
  }

  /** Is there a passphrase on this browser's profiles? */
  get hasLock() { return this.vaultRecord !== null; }

  /** Is there one, and is it still shut? */
  get locked() { return this.hasLock && this.key === null; }

  close() {
    this.key = null;
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

  // -- the lock -------------------------------------------------------------

  async _readVault() {
    const found = await done(this.database.transaction(VAULT, "readonly")
                                 .objectStore(VAULT).get(VAULT_KEY));
    this.vaultRecord = found ?? null;
    return this.vaultRecord;
  }

  /** Put a passphrase over everything saved here. Returns the recovery code,
   *  which is the only time it will ever be readable.
   *
   *  Everything already stored is sealed on the way through, in one
   *  transaction, so this either happens or it does not. A half-encrypted
   *  database is not a state anybody could recover from by hand, so it is not
   *  a state that is allowed to exist.
   */
  async addLock(passphrase) {
    if (!vault.available()) {
      throw new Error("This page has no Web Crypto, so it cannot lock "
                      + "anything. That needs https, or localhost.");
    }
    if (this.hasLock) throw new Error("There is already a passphrase on this.");

    const made = await vault.create(passphrase);

    // Read everything first, seal it outside the transaction, write it back
    // inside one. Sealing is not a database request and cannot happen with a
    // transaction open.
    const existing = await this._everything();
    const sealed = [];
    for (const [store, key, record] of existing) {
      sealed.push([store, key, await this._seal(record, made.key)]);
    }

    const transaction = this.database.transaction(ALL_STORES, "readwrite");
    for (const [store, key, record] of sealed) {
      transaction.objectStore(store).put(record, key);
    }
    transaction.objectStore(VAULT).put(made.record, VAULT_KEY);
    await committed(transaction);

    this.vaultRecord = made.record;
    this.key = made.key;
    return made.recoveryCode;
  }

  /** Open the lock with a passphrase or a recovery code.
   *
   *  Slow on purpose, a few hundred milliseconds, because the derivation is
   *  what makes guessing expensive. Say "unlocking" on screen or it reads as
   *  a hang.
   */
  async unlock(secret) {
    if (!this.hasLock) return "none";
    const opened = await vault.unlock(this.vaultRecord, secret);
    this.key = opened.key;
    return opened.usedKind;
  }

  /** Forget the key. The data stays sealed where it is. */
  relock() {
    this.key = null;
  }

  /** Take the passphrase off, leaving the profiles readable again.
   *
   *  Has to be unlocked first, for the obvious reason.
   */
  async removeLock() {
    if (!this.hasLock) return;
    this._insist();

    const existing = await this._everything();
    const plain = [];
    for (const [store, key, record] of existing) {
      // A record that will not open is left exactly as it is. It is almost
      // certainly one of the set-aside broken ones, and writing null over it
      // would destroy the only copy of something somebody may still want
      // picked apart by hand. Unreadable is not the same as worthless.
      plain.push([store, key, (await this._unseal(record)) ?? record]);
    }

    const transaction = this.database.transaction(ALL_STORES, "readwrite");
    for (const [store, key, record] of plain) {
      transaction.objectStore(store).put(record, key);
    }
    transaction.objectStore(VAULT).delete(VAULT_KEY);
    await committed(transaction);

    this.vaultRecord = null;
    this.key = null;
  }

  /** Change the passphrase. Nothing already stored is touched: only the
   *  wrapped copy of the key is rewritten. See vault.js for why. */
  async changePassphrase(current, replacement) {
    if (!this.hasLock) throw new Error("There is no passphrase to change.");
    const opened = await vault.unlock(this.vaultRecord, current);
    const record = await vault.changePassphrase(
      this.vaultRecord, opened.key, replacement);

    const transaction = this.database.transaction(VAULT, "readwrite");
    transaction.objectStore(VAULT).put(record, VAULT_KEY);
    await committed(transaction);

    this.vaultRecord = record;
    this.key = opened.key;
  }

  /** Issue a new recovery code and retire the old one. */
  async newRecoveryCode() {
    if (!this.hasLock) throw new Error("There is no passphrase on this.");
    this._insist();
    const made = await vault.newRecovery(this.vaultRecord, this.key);

    const transaction = this.database.transaction(VAULT, "readwrite");
    transaction.objectStore(VAULT).put(made.record, VAULT_KEY);
    await committed(transaction);

    this.vaultRecord = made.record;
    return made.recoveryCode;
  }

  _insist() {
    if (this.locked) throw new Locked();
  }

  /** Every record in the four profile stores, as [store, key, record]. */
  async _everything() {
    const transaction = this.database.transaction(PROFILE_STORES, "readonly");
    const all = [];
    for (const store of PROFILE_STORES) {
      const where = transaction.objectStore(store);
      const keys = await done(where.getAllKeys());
      const records = await done(where.getAll());
      keys.forEach((key, at) => all.push([store, key, records[at]]));
    }
    return all;
  }

  /** A record on its way into the database: sealed if there is a key. */
  async _seal(record, key = this.key) {
    if (!key || record?.sealed) return record;
    const id = record?.id ?? record?.profile?.id ?? "";
    return { id, savedAt: record.savedAt,
             sealed: await vault.seal(key, id, record.profile) };
  }

  /** A record on its way out: opened if it is sealed.
   *
   *  Returns null when it will not open, which is a real answer rather than
   *  an error: a record that does not decrypt is a record to fall back from,
   *  and the caller upstairs already knows how to do that.
   */
  async _unseal(record) {
    if (!record?.sealed) return record;
    if (!this.key) throw new Locked();
    try {
      return { id: record.id, savedAt: record.savedAt,
               profile: await vault.open(this.key, record.id, record.sealed) };
    } catch {
      return null;
    }
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
   *  could leave two of them done and one not. The old record is moved as it
   *  stands, still sealed if it was sealed, so none of this needs the key.
   *
   *  THE AWAITS IN HERE ARE LOAD-BEARING. A transaction stays open only while
   *  requests keep being made from the chain of microtasks it started.
   *  Awaiting an IndexedDB request is fine, because that request is what
   *  resolves it. Awaiting anything else, a fetch, a timer, encrypting
   *  something, hands control back to the browser, the transaction commits
   *  early, and the next line throws TransactionInactiveError. Which is
   *  exactly why the sealing happens on the line above the transaction and
   *  not inside it.
   */
  async save(profile) {
    this._insist();
    const record = await this._seal(
      { id: profile.id, savedAt: Date.now(), profile: profile.toDict() });

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
   *  Refused for each one that could not be opened at all. */
  async list() {
    this._insist();
    const profiles = [];
    const recoveries = [];
    const refused = [];

    for (const id of await this.ids()) {
      const found = await this._resolve(id);
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

    // Sorted by name so the launcher shows a stable, predictable order rather
    // than whatever order the database happened to hand back.
    profiles.sort((a, b) =>
      a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    return { profiles, recoveries, refused };
  }

  /** The id of every profile saved here. Works locked: an id is not a secret,
   *  and a locked launcher still has to be able to say how many there are. */
  ids() {
    return done(this.database.transaction(LIVE, "readonly")
                    .objectStore(LIVE).getAllKeys());
  }

  /** One profile by id, rescued the same way. Null if there is nothing
   *  readable under that id anywhere. */
  async load(id) {
    this._insist();
    return (await this._resolve(id)).profile;
  }

  /** Find the best readable version of one profile, repairing if it had to
   *  reach for a backup.
   *
   *  In three parts, and the split is what makes decryption possible at all.
   *  _gather is one read-only transaction and nothing else. _look opens
   *  records, which may mean decrypting, and happens with no transaction in
   *  flight. _repair is a second transaction, entered only in the rare case
   *  where something actually had to be rescued.
   */
  async _resolve(id) {
    const { record, fallbacks } = await this._gather(id);

    const first = await this._look(id, record);
    if (first.kind === "ok") {
      return { profile: first.profile, recovery: null, refused: null };
    }
    if (first.kind === "future") {
      // Not a broken profile, and reaching for a backup would be wrong: its
      // backups are from the future too, and the live record is the newest
      // thing there is. Leave all of it alone.
      return { profile: null, recovery: null,
               refused: new Refused(id, first.name,
                 "Saved by a newer version of Invenfloor. Update before "
                 + "opening it, or this version would quietly drop the parts "
                 + "it does not understand.") };
    }

    for (const { spare, description } of fallbacks) {
      const found = await this._look(id, spare);
      if (found.kind !== "ok") continue;

      const brokenKey = await this._repair(id, record, spare);
      return { profile: found.profile,
               recovery: new Recovery("", description, brokenKey),
               refused: null };
    }

    return { profile: null, recovery: null,
             refused: new Refused(id, "",
               record === undefined
                 ? "There is nothing saved under this id."
                 : "This profile would not open, and neither would any of "
                   + "its backups.") };
  }

  /** The live record and everywhere worth looking if it is no good, best
   *  first. One read-only transaction, no decryption, no surprises.
   *
   *  The previous save comes before the dated snapshots because it is newer
   *  than all of them: a snapshot is the state at the START of a day, and
   *  previous is one save ago.
   */
  async _gather(id) {
    const transaction = this.database.transaction(PROFILE_STORES, "readonly");
    const record = await done(transaction.objectStore(LIVE).get(id));

    const fallbacks = [{
      spare: await done(transaction.objectStore(PREVIOUS).get(id)),
      description: "the previous save",
    }];

    const snapshots = transaction.objectStore(SNAPSHOTS);
    const keys = await keysFor(snapshots, id);
    keys.sort().reverse();
    for (const key of keys) {
      fallbacks.push({
        spare: await done(snapshots.get(key)),
        // "a3f9c1d2-2026-09-20" -> "2026-09-20"
        description: `the backup from ${key.slice(id.length + 1)}`,
      });
    }
    return { record, fallbacks };
  }

  /** Open one record. { kind: "ok", profile } | { kind: "future", name } |
   *  { kind: "no" }. Never throws for a bad record: that is an answer. */
  async _look(id, record) {
    if (record === undefined) return { kind: "no" };

    const plain = await this._unseal(record);
    if (!plain || !looksLikeAProfile(plain.profile)) return { kind: "no" };
    if (fromTheFuture(plain.profile)) {
      return { kind: "future", name: nameIn(plain) };
    }

    try {
      // fromDict migrates in place, which would be a problem if this object
      // were the database's copy: a version 1 record would come out halved the
      // first time and already-halved the second. It is not. IndexedDB builds
      // a fresh copy of a value on every read, so editing what get() handed
      // back cannot reach the record. That guarantee is doing real work here,
      // so storage_checks.js loads an old record twice and checks it.
      return { kind: "ok", profile: Profile.fromDict(plain.profile) };
    } catch (error) {
      // Deliberately wide, for the same reason it is wide in storage.py. This
      // is not untrusted input in the security sense, but it is data that can
      // have been put there by an import, by a different version of the app,
      // or by a browser having a bad day, and every one of those produces a
      // different exception. The alternative to catching them all here is the
      // app failing to start, which is a worse answer to every one of them.
      console.warn("[storage] Could not read a profile:", error);
      return { kind: "no" };
    }
  }

  /** Set the bad record aside and promote the one that worked.
   *
   *  Moving the bad record out of the way is not tidiness. Leaving it in place
   *  would mean the next save moved it into previous, destroying the very
   *  backup we were just rescued by.
   *
   *  This is a second transaction, so in principle another tab could have
   *  saved between the read and here, in which case the problem has already
   *  fixed itself and stamping on it would undo a good save. Hence the check
   *  on savedAt: if the live record is not the one we found broken, leave it
   *  alone. Two tabs of this app open on the same broken profile in the same
   *  moment is not a thing that happens, and a rescue that can trample a real
   *  save is not a thing worth shipping either way.
   */
  async _repair(id, broken, good) {
    const transaction = this.database.transaction(
      [LIVE, BROKEN], "readwrite");
    const live = transaction.objectStore(LIVE);

    const now = await done(live.get(id));
    if (now?.savedAt !== broken?.savedAt) {
      transaction.abort();
      return "";
    }

    let brokenKey = "";
    if (broken !== undefined) {
      brokenKey = `${id}.broken-${stamp()}`;
      transaction.objectStore(BROKEN).put(broken, brokenKey);
    }
    live.put(good, id);

    await committed(transaction);
    return brokenKey;
  }

  /** When this profile was last saved, in milliseconds, or null.
   *
   *  The file system was keeping this for us on the desktop. Here it is in
   *  the record, which is the next best thing: written by the same put that
   *  wrote the profile, so it cannot drift out of step with it. Readable
   *  locked, because a date is not a secret.
   */
  async savedAt(id) {
    const record = await done(this.database.transaction(LIVE, "readonly")
                                  .objectStore(LIVE).get(id));
    return record?.savedAt ?? null;
  }

  /** Every dated snapshot for a profile, newest first, as
   *  { day, savedAt, name }. The name is null while locked.
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

    const records = [];
    for (const key of keys) {
      records.push([key, await done(store.get(key))]);
    }

    const found = [];
    for (const [key, record] of records) {
      found.push({ day: key.slice(id.length + 1),
                   savedAt: record?.savedAt ?? null,
                   name: this.locked ? null : nameIn(await this._unseal(record)) });
    }
    return found;
  }

  /** Put a snapshot back as the live profile, keeping the current one.
   *
   *  What is being replaced goes to previous, exactly as an ordinary save
   *  would move it, so restoring the wrong day is itself undoable. The
   *  records move as they are, so this does not need the key either.
   */
  async restore(id, day) {
    this._insist();
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
    live.put({ ...snapshot, savedAt: Date.now() }, id);

    await committed(transaction);
    return (await this._look(id, snapshot)).profile ?? null;
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
    this._insist();
    const profile = readExport(text);

    const taken = await this.ids();
    if (taken.includes(profile.id)) {
      const { profiles } = await this.list();
      profile.id = newId();
      profile.name = copyName(profile.name, profiles.map(p => p.name));
    }

    await this.save(profile);
    return profile;
  }
}

/** The profile's name out of an opened record, or "" if there isn't one. */
function nameIn(record) {
  const name = record?.profile?.name;
  return typeof name === "string" ? name : "";
}

// ---------------------------------------------------------------------------
// EXPORT AND IMPORT
// ---------------------------------------------------------------------------

/** A profile as the text of a save file.
 *
 *  Plain JSON, and deliberately so, even when there is a passphrase on the
 *  database. This is the file that opens in the desktop app, and it is also
 *  the backup that outlives the browser, and an export nobody else can read
 *  is not a backup, it is a second thing to lose the key to. It does mean an
 *  export is as safe as wherever it is put, which the interface should say at
 *  the moment somebody presses the button rather than in a manual.
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

/**
 * vault.js
 * ========
 *
 * A passphrase lock over the profiles saved in this browser. With one set up,
 * what sits in IndexedDB is ciphertext, and there is no way to read it without
 * the passphrase or the recovery code.
 *
 * BE CLEAR ABOUT WHAT THIS IS
 * ---------------------------
 * It is a lock on data at rest in one browser. It stops somebody who sits down
 * at an unlocked laptop, or who copies the browser profile off a disk, from
 * reading what is in your rooms.
 *
 * It is NOT a login. There is no account, no server, and nothing checks who
 * you are. The passphrase is not sent anywhere and not compared against
 * anything, because there is nothing to compare it to. It either derives a key
 * that opens the data or it does not.
 *
 * It is also not protection against somebody who controls the machine or the
 * page. Malware that can read the browser's memory, or a script injected into
 * the app itself, sees the profiles after they are unlocked exactly as you do.
 * Encryption at rest is worth having and is not a force field.
 *
 * WHY BUILD IT NOW, BEFORE ANYONE IS USING IT
 * -------------------------------------------
 * Because it is free right now and it never will be again. Adding encryption
 * to a save format that people already have data in means writing a migration,
 * testing it against every shape of old file, and getting it right the first
 * time on machines you cannot see. Adding it today costs nothing, because the
 * only saves in the world are the ones on this machine.
 *
 * HOW IT IS PUT TOGETHER
 * ----------------------
 * A random 256-bit content key encrypts every record. That key never comes
 * from the passphrase. Instead the passphrase derives a second key, and that
 * second key is used to wrap the content key, which is then stored wrapped.
 *
 * The indirection earns its place three times over:
 *
 *   - Changing the passphrase rewraps 32 bytes. Deriving the content key from
 *     the passphrase directly would mean re-encrypting every profile, every
 *     backup and every snapshot, and a change that can half-finish is a change
 *     that can lose data.
 *   - The recovery code is just a second wrap of the same content key. Without
 *     the indirection there would have to be two copies of everything.
 *   - A server-held wrap, when there is a server, is a third entry in the same
 *     list, and the profiles it syncs stay unreadable to it.
 *
 * WHAT IS STILL IN THE CLEAR
 * --------------------------
 * The profile ids, because they are the keys records are stored under and you
 * cannot look up what you cannot name. How many profiles there are. When each
 * was last saved, and which days have snapshots. Someone reading the raw
 * database learns that you have four profiles and used the app on the 12th.
 * They do not learn a single room, container or item.
 *
 * THERE IS NO PASSWORD RESET
 * --------------------------
 * There cannot be. A reset means somebody, somewhere, can get in without the
 * password, and the whole point is that nobody can. Lose the passphrase and
 * the recovery code and the data is gone, by design rather than by accident.
 *
 * Which is why create() hands back a recovery code and why the interface has
 * to make people write it down rather than mentioning it politely.
 */

// PBKDF2 with SHA-256 at 600,000 iterations, which is what OWASP's password
// storage guidance calls for. Argon2id would be better, and is not in the Web
// Crypto API: having it would mean shipping a WebAssembly build, a build step
// and a dependency, to protect a local database. Not worth it here. Revisit it
// the day there is a server, where the same choice is about everyone's data
// rather than one person's.
//
// It is meant to be slow, and measured rather than guessed at: about 100ms
// for one derivation in Chrome on a desktop, and a few times that on a phone.
// Setting a lock up costs two, because the passphrase and the recovery code
// are wrapped separately. Unlocking with the recovery code also costs two,
// because the passphrase is tried first.
//
// A tenth of a second is slow for a person and is not slow for a graphics
// card, which is the honest limit of PBKDF2 and the reason Argon2id exists.
// It puts a real cost on guessing a decent passphrase and it will not save a
// bad one. Say "unlocking…" in the interface so the pause does not read as a
// bug, and say somewhere that the passphrase should be a long one.
export const ITERATIONS = 600000;

const KEY_BITS = 256;
const SALT_BYTES = 16;
const IV_BYTES = 12;         // 96 bits, which is what AES-GCM is specified for

const text = new TextEncoder();
const fromBytes = new TextDecoder();

/** Thrown when a passphrase or recovery code does not open the vault.
 *
 *  Its own class because the caller has to tell "you typed it wrong" from
 *  "this database is damaged", and those want different words on screen.
 */
export class WrongSecret extends Error {
  constructor(message = "That is not the right passphrase.") {
    super(message);
    this.name = "WrongSecret";
  }
}

function randomBytes(count) {
  return crypto.getRandomValues(new Uint8Array(count));
}

// ---------------------------------------------------------------------------
// THE RECOVERY CODE
// ---------------------------------------------------------------------------

// Crockford's base32 alphabet: the digits and letters left after taking out
// I, L, O and U. The first three because they are the ones people confuse with
// 1 and 0 when copying a code off a sticky note, and U because leaving it out
// means the generator cannot produce a word somebody has to read aloud.
const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const CODE_LENGTH = 20;      // 20 characters of 5 bits each: 100 bits

/** A fresh recovery code, in groups of five: "H7K2M-9QXT4-..."
 *
 *  100 bits of randomness, which is far past anything that can be guessed, so
 *  it does not need a passphrase's careful handling. It does get run through
 *  the same slow derivation anyway, because one code path is easier to be sure
 *  of than two and half a second once is nothing.
 */
export function newRecoveryCode() {
  // Rejection sampling rather than a plain modulo. With 32 symbols it happens
  // to make no difference, because 32 divides 256 exactly and every byte maps
  // to a symbol evenly. It is written this way anyway: an alphabet is exactly
  // the sort of constant somebody edits later, and the day it stops being a
  // power of two a plain modulo starts favouring the first few letters without
  // anything looking wrong.
  const limit = 256 - (256 % ALPHABET.length);
  const picked = [];
  while (picked.length < CODE_LENGTH) {
    for (const byte of randomBytes(CODE_LENGTH)) {
      if (byte >= limit) continue;
      picked.push(ALPHABET[byte % ALPHABET.length]);
      if (picked.length === CODE_LENGTH) break;
    }
  }
  return picked.join("").replace(/(.{5})(?=.)/g, "$1-");
}

/** Tidy a typed recovery code back into the form it was generated in.
 *
 *  People retype these off paper, so the three characters the alphabet leaves
 *  out on purpose are folded back to what they were meant to be: a written O
 *  becomes 0, and I or L becomes 1. Dashes and spaces go entirely, wherever
 *  somebody put them.
 *
 *  Nothing else is touched. Q is a real symbol in this alphabet and so is V,
 *  and "helpfully" mapping either of them would quietly break every code that
 *  happens to contain one.
 */
export function tidyRecoveryCode(code) {
  return String(code).toUpperCase()
    .replace(/[^0-9A-Z]/g, "")
    .replace(/O/g, "0")
    .replace(/[IL]/g, "1");
}

// ---------------------------------------------------------------------------
// KEYS
// ---------------------------------------------------------------------------

/** Turn a secret into a key that can wrap another key.
 *
 *  The salt is what stops one precomputed table from opening every vault in
 *  the world, so it is random per lock and stored beside the wrapped key. It
 *  is not a secret and does not need to be.
 */
async function keyFromSecret(secret, salt, iterations) {
  const base = await crypto.subtle.importKey(
    "raw", text.encode(secret), "PBKDF2", false, ["deriveKey"]);

  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    base,
    { name: "AES-GCM", length: KEY_BITS },
    false,                                  // never needs to leave as bytes
    ["wrapKey", "unwrapKey"]);
}

/** Wrap the content key under a secret, and everything needed to undo it. */
async function lockFor(kind, secret, contentKey) {
  const salt = randomBytes(SALT_BYTES);
  const iv = randomBytes(IV_BYTES);
  const wrapper = await keyFromSecret(secret, salt, ITERATIONS);
  const wrapped = await crypto.subtle.wrapKey(
    "raw", contentKey, wrapper, { name: "AES-GCM", iv });
  return { kind, salt, iv, iterations: ITERATIONS, wrapped };
}

/** Undo one lock, or null if this secret is not the one. */
async function unlockOne(lock, secret) {
  const wrapper = await keyFromSecret(secret, lock.salt, lock.iterations);
  try {
    return await crypto.subtle.unwrapKey(
      "raw", lock.wrapped, wrapper, { name: "AES-GCM", iv: lock.iv },
      { name: "AES-GCM", length: KEY_BITS }, true, ["encrypt", "decrypt"]);
  } catch {
    // AES-GCM is authenticated, so a wrong key does not produce a wrong
    // answer. It fails. That is the whole test, and no separate "is this the
    // right password" value has to be stored anywhere.
    return null;
  }
}

// ---------------------------------------------------------------------------
// THE VAULT RECORD
// ---------------------------------------------------------------------------

export const VAULT_VERSION = 1;

/** Set up a lock for the first time.
 *
 *  Returns the record to store, the key to hold while unlocked, and the
 *  recovery code, which is the only time it exists in readable form. It is not
 *  stored anywhere, because storing it would make it a second password sitting
 *  next to the door.
 */
export async function create(passphrase) {
  if (!String(passphrase)) throw new Error("A lock needs a passphrase.");

  const contentKey = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: KEY_BITS }, true, ["encrypt", "decrypt"]);

  const recoveryCode = newRecoveryCode();
  const record = {
    version: VAULT_VERSION,
    locks: [
      await lockFor("passphrase", String(passphrase), contentKey),
      await lockFor("recovery", tidyRecoveryCode(recoveryCode), contentKey),
    ],
  };
  return { record, key: contentKey, recoveryCode };
}

/** Open a vault with a passphrase or a recovery code.
 *
 *  Both are tried, and which one worked is reported rather than hidden,
 *  because an interface should be able to say "that was your recovery code,
 *  set a new passphrase now" instead of quietly carrying on.
 */
export async function unlock(record, secret) {
  if (!record || record.version !== VAULT_VERSION) {
    throw new Error("This lock was made by a different version of Invenfloor.");
  }

  const typed = String(secret);
  const tidied = tidyRecoveryCode(typed);

  for (const lock of record.locks) {
    const key = await unlockOne(lock, lock.kind === "recovery" ? tidied : typed);
    if (key) return { key, usedKind: lock.kind };
  }
  throw new WrongSecret();
}

/** Change the passphrase, keeping the same content key.
 *
 *  Nothing that is already encrypted is touched. That is not only cheaper, it
 *  is safer: re-encrypting a whole database is an operation that can stop
 *  halfway, and this one cannot.
 *
 *  The recovery code is deliberately left alone. Somebody changing a
 *  passphrase has not lost the piece of paper, and quietly invalidating it
 *  would mean the one thing standing between them and losing everything had
 *  gone stale without being mentioned.
 */
export async function changePassphrase(record, key, newPassphrase) {
  if (!String(newPassphrase)) throw new Error("A lock needs a passphrase.");
  const replacement = await lockFor("passphrase", String(newPassphrase), key);
  return {
    ...record,
    locks: record.locks.map(lock =>
      lock.kind === "passphrase" ? replacement : lock),
  };
}

/** Issue a new recovery code, retiring the old one.
 *
 *  Unlike the passphrase, this one does replace what was there. A recovery
 *  code is only ever reissued because the old paper is gone or has been seen,
 *  and both of those mean the old one should stop working.
 */
export async function newRecovery(record, key) {
  const recoveryCode = newRecoveryCode();
  const replacement = await lockFor("recovery", tidyRecoveryCode(recoveryCode), key);
  return {
    record: { ...record,
              locks: record.locks.map(lock =>
                lock.kind === "recovery" ? replacement : lock) },
    recoveryCode,
  };
}

// ---------------------------------------------------------------------------
// SEALING THINGS
// ---------------------------------------------------------------------------

/** Encrypt one value under the content key.
 *
 *  A FRESH RANDOM IV EVERY TIME, WITHOUT EXCEPTION. Reusing an initialization
 *  vector with the same AES-GCM key is not a weakness, it is a break: two
 *  messages under one IV leak the difference between their plaintexts and hand
 *  over the means to forge more. Twelve random bytes per write is the whole
 *  precaution, and the only way to get it wrong is to try to be clever, cache
 *  one, or count upwards from zero.
 *
 *  `name` is the profile id, and it goes in as additional authenticated data.
 *  It is not encrypted; it is bound. The ciphertext will only open under the
 *  id it was written for, so one profile's record cannot be slid into
 *  another's place. A small guarantee, free to have.
 */
export async function seal(key, name, value) {
  const iv = randomBytes(IV_BYTES);
  const body = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: text.encode(String(name)) },
    key, text.encode(JSON.stringify(value)));
  return { iv, body };
}

/** Decrypt one value, or throw. Wrong key, wrong id, or a single altered byte
 *  all land here, because AES-GCM checks the whole thing before it gives
 *  anything back. */
export async function open(key, name, sealed) {
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: sealed.iv,
      additionalData: text.encode(String(name)) },
    key, sealed.body);
  return JSON.parse(fromBytes.decode(plain));
}

/** Is Web Crypto here at all?
 *
 *  It needs a secure context: https, or localhost. A page served over plain
 *  http from another machine on the network has no crypto.subtle, and the
 *  failure is an undefined property rather than anything that explains itself.
 *  Worth checking once, up front, and saying so.
 */
export function available() {
  return typeof crypto !== "undefined" && Boolean(crypto?.subtle);
}

/**
 * undo.js
 * =======
 *
 * Undo and redo, by keeping whole copies of the profile.
 *
 * WHY WHOLE COPIES AND NOT A LIST OF CHANGES
 * ------------------------------------------
 * The usual way is a command for each kind of edit, each knowing how to undo
 * itself. It is more efficient and it is a great deal more code, and every
 * new feature has to remember to add its command or it silently becomes the
 * one thing undo cannot reach. That last part is the real cost: the bug is
 * invisible until somebody needs it.
 *
 * A profile is a few hundred kilobytes at the outside, and it already knows
 * how to write itself out and read itself back, because that is what saving
 * is. So a step is a snapshot, and the code that has to remember anything is
 * one call in one place.
 *
 * The limit is what keeps that honest. Thirty steps of a large profile is a
 * few megabytes of memory, which is nothing on a desktop and worth not
 * ignoring on a phone.
 */
import { Profile } from "./model.js";

export const STEPS_KEPT = 30;

export class History {
  constructor(profile, kept = STEPS_KEPT) {
    this.kept = kept;
    this.past = [];
    this.future = [];
    this.present = profile.toDict();
  }

  get canUndo() { return this.past.length > 0; }
  get canRedo() { return this.future.length > 0; }

  /** Record the state a change has just produced.
   *
   *  Called AFTER the edit, not before, which is worth being precise about:
   *  what gets pushed onto the past is the state before this one, which this
   *  object has been holding since the last call. Asking callers to remember
   *  to snapshot beforehand is the version that goes wrong, because the one
   *  place that forgets is a change nobody can undo.
   */
  record(profile) {
    this.past.push(this.present);
    if (this.past.length > this.kept) this.past.shift();
    this.future.length = 0;
    this.present = profile.toDict();
  }

  /** Step back. Returns the profile to show, or null if there is nowhere to
   *  go. The caller replaces what it is holding with what comes back. */
  undo() {
    if (!this.past.length) return null;
    this.future.push(this.present);
    this.present = this.past.pop();
    return Profile.fromDict(structuredClone(this.present));
  }

  redo() {
    if (!this.future.length) return null;
    this.past.push(this.present);
    this.present = this.future.pop();
    return Profile.fromDict(structuredClone(this.present));
  }
}

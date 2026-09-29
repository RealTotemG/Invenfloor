/**
 * tags.js
 * =======
 *
 * Tags: making them, putting them on things, and filtering by them.
 *
 * WHY TAGS ARE WORTH A FILE OF THEIR OWN
 * --------------------------------------
 * A tag goes on two different kinds of thing, and the second one is what
 * makes them more than a label.
 *
 *     a tag on an ITEM says what the thing is
 *     the same tag on a ROOM says what belongs in that room
 *
 * Put those together and the app can answer a question nothing else can:
 * which things are somewhere their own tags say they should not be. That is
 * the "In the wrong room" view, and until now it was a tab that could never
 * find anything, because the browser had no way to put a tag on anything.
 *
 * The model has had all of this from the start. tagIds on items, rooms and
 * containers, misfiledItems() to compare them, deleteTag() to clean up after
 * one. Only the screens were missing, so a profile tagged on the desktop
 * opened here with its tags invisible: still in the file, still saved back
 * out, and impossible to see or change. That is worse than not having the
 * feature, because it looks like the app lost them.
 *
 * WHY EVERYTHING HERE IS INLINE RATHER THAN A DIALOG
 * --------------------------------------------------
 * The desktop opens a window to assign tags and another to manage them. This
 * has no windows, and adding a modal layer for one feature would be a lot of
 * machinery for something that fits in a row of chips. Assigning is a
 * dropdown next to the chips; managing is a panel that folds down under the
 * button. Both work the same on a phone, which a dialog would not.
 */
import * as M from "./model.js";
import * as T from "./theme.js";
import { el, put, clear, button, field, colors, choose, icon } from "./ui.js";


/** A tag as a pill, in the tag's own color.
 *
 *  Read-only. It is how a tag looks anywhere one is shown, so that a tag is
 *  recognizable at a glance in a list of twenty items without reading it.
 */
export function tagChip(tag, { onRemove = null } = {}) {
  const chip = el("span", "tag");
  chip.style.color = tag.color;
  chip.style.borderColor = tag.color;
  // The fill is the tag's color at low opacity. color-mix does it without
  // this file having to know how to take a hex string apart.
  chip.style.background = `color-mix(in srgb, ${tag.color} 18%, transparent)`;
  chip.title = tag.name;

  put(chip, el("span", "tag-name", M.short(tag.name, 22)));

  if (onRemove) {
    const drop = button("×", "tag-x", onRemove, `Take off ${tag.name}`);
    drop.style.color = tag.color;
    put(chip, drop);
  }
  return chip;
}


/** The tags on one item, room or container, with a way to add and remove.
 *
 *  `thing` is anything with a tagIds array, which is all three of them. One
 *  function rather than three because the job is identical and the day they
 *  differ is the day one of them quietly stops working.
 */
export function tagRow(profile, thing, { changed, again }) {
  const box = el("div", "tag-row");

  for (const tag of profile.tagsFor(thing.tagIds)) {
    put(box, tagChip(tag, {
      onRemove: () => {
        thing.tagIds = thing.tagIds.filter(id => id !== tag.id);
        if (thing.touch) thing.touch();
        changed();
        again();
      },
    }));
  }

  const spare = profile.tags.filter(tag => !thing.tagIds.includes(tag.id));
  if (!profile.tags.length) {
    put(box, el("span", "note small", "No tags yet. Make one below."));
    return box;
  }
  if (!spare.length) {
    put(box, el("span", "note small", "Every tag is on this already."));
    return box;
  }

  // A dropdown that snaps back to its first option after each pick, because
  // it is an action rather than a setting: it does not hold a value, it adds
  // one. Leaving it showing the tag you just added reads as "this is now the
  // tag", which is exactly what it is not.
  const picker = choose(null,
    [["", "add a tag…"], ...spare.map(tag => [tag.id, tag.name])],
    "", value => {
      if (!value) return;
      thing.tagIds = [...thing.tagIds, value];
      if (thing.touch) thing.touch();
      changed();
      again();
    });
  picker.classList.add("tag-pick");
  put(box, picker);
  return box;
}


/** Make, rename, recolor and delete tags. Folds down under a button.
 *
 *  Deleting takes the tag off everything that had it, which the model does in
 *  deleteTag. Worth confirming rather than undoing, because the undo would
 *  have to put it back on every item it was on and somebody who deletes the
 *  wrong tag will not find out until much later.
 */
export function tagManager(profile, { changed, again }) {
  const box = el("div", "card");

  put(box, el("p", "note",
    "A tag on an item says what the thing is. The same tag on a room says "
    + "what belongs there. Put both on and the In the wrong room view can "
    + "find things that have wandered."));

  if (!profile.tags.length) {
    put(box, el("p", "note",
      "No tags yet. Good first ones are the sort of thing you would say out "
      + "loud looking for something: Tools, Christmas, Fragile."));
  }

  for (const tag of profile.tags) {
    const row = el("div", "row");

    const name = field(tag.name, value => {
      tag.name = M.cleanName(value, tag.name);
      changed();
      again();
    });
    name.className = "grow";
    put(row, name);

    const used = profile.itemsWithTag(tag.id).length;
    const rooms = [...profile.roomsWithTag(tag.id)].length;
    put(row, el("span", "note small",
      `${used} item${used === 1 ? "" : "s"}, ${rooms} room${
        rooms === 1 ? "" : "s"}`));

    const drop = button("", "quiet small danger", () => {
      if (!confirm(`Delete the tag "${tag.name}"? It comes off ${used} item${
        used === 1 ? "" : "s"} and ${rooms} room${rooms === 1 ? "" : "s"}. `
        + "Nothing else is deleted.")) return;
      profile.deleteTag(tag.id);
      changed();
      again();
    }, `Delete ${tag.name}`);
    put(drop, icon("trash"));
    put(row, drop);

    put(box, row);
    put(box, colors(tag.color, color => {
      tag.color = color;
      changed();
      again();
    }));
  }

  put(box, put(el("div", "row"),
    button("New tag", "primary small", () => {
      // Counted off the length rather than made unique against the existing
      // names, because the name is a placeholder: the box it lands in is
      // focused nowhere and somebody is going to type over it immediately.
      // Two tags both called "Tag 3" is not a state worth preventing.
      const made = new M.Tag({
        name: `Tag ${profile.tags.length + 1}`,
        color: T.SWATCHES[profile.tags.length % T.SWATCHES.length],
      });
      profile.tags.push(made);
      changed();
      again();
    }, "Make a tag you can put on items and rooms")));

  return box;
}


/** The row of tag chips on the items screen, for filtering by one.
 *
 *  Pressing a tag shows only the things carrying it; pressing it again clears
 *  it. `state.tagId` holds which one, alongside the saved view, so the two
 *  narrow the list together rather than fighting over it.
 */
export function tagFilterRow(profile, state, { changed, again }) {
  const box = el("div", "tag-row");

  for (const tag of profile.tags) {
    const chip = tagChip(tag);
    const on = state.tagId === tag.id;
    chip.classList.add("tag-button");
    if (on) {
      chip.classList.add("on");
      chip.style.background = `color-mix(in srgb, ${tag.color} 34%, transparent)`;
    }
    chip.title = on ? `Stop filtering by ${tag.name}` : `Only things tagged ${tag.name}`;
    chip.addEventListener("click", () => {
      state.tagId = on ? null : tag.id;
      again();
    });
    put(box, chip);
  }

  return box;
}

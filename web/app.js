/**
 * app.js
 * ======
 *
 * Invenfloor: draw your floor plan and find where things are.
 * Copyright (C) 2026 Malachi (RealTotemG)
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by the
 * Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. It is distributed in the hope that it will be
 * useful, but WITHOUT ANY WARRANTY, without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the LICENSE file at
 * the top of the repository, or <https://www.gnu.org/licenses/>, for the terms.
 *
 * Section 13 of that license is why the footer carries a Source link: a
 * program people reach over a network has to offer them its source, and this
 * one is reached over a network.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 *
 * The shell: what is on screen, and what happens when you press things.
 *
 * Three places. The launcher lists the profiles saved in this browser and
 * handles the passphrase and the import and export of files. Opening one gets
 * you the workspace, which is either the floor plan, the inside of one room in
 * 3D, or the items screen.
 *
 * WHY THE MARKUP IS BUILT HERE RATHER THAN SITTING IN THE HTML
 * ------------------------------------------------------------
 * One place decides what is on the page. The alternative, a page full of
 * hidden sections that get shown and hidden, means the current screen is
 * described in two places at once, and the day they disagree is the day you
 * get a launcher with half a floor plan behind it.
 *
 * TELLING PEOPLE WHAT A BUTTON DOES
 * ---------------------------------
 * Every tool has a picture, a word, and a tooltip, and the strip underneath
 * says what the tool you have picked expects you to do next, in a sentence.
 * That last part is the one that matters. A toolbar can only ever say what a
 * button is called; the line under it can say "press to place each corner,
 * press the first one again to close it", which is the thing somebody
 * actually needs at that moment and cannot guess.
 *
 * WHAT SAVING LOOKS LIKE
 * ----------------------
 * Every change calls touched(), which records an undo step, waits half a
 * second and then writes. A drag is dozens of changes, one undo step and one
 * save. The delay is the same one storage.py assumes when it explains why
 * snapshots are per day rather than per save.
 */
import * as M from "./model.js";
import * as S from "./storage.js";
import * as T from "./theme.js";
import * as F from "./floor.js";
import { RoomView } from "./room.js";
import { FloorView } from "./floor.js";
import { History } from "./undo.js";
import { sample } from "./sample.js";
import { contentsPanel, itemsScreen, tierName } from "./items.js";
import {
  el, put, clear, button, swatch, field, numberField, choose, colors, notice,
  icon, toolButton,
} from "./ui.js";
import { footer, watchForErrors } from "./about.js";
import { makeTag, tagRow } from "./tags.js";

T.apply();

// Installed before anything else so that a failure while the launcher is
// still building is caught too. That is the failure somebody is most likely
// to report, because it is the one where the page never appears.
watchForErrors();

// Where a problem report goes. One place, so moving the project is one edit.
const ISSUES = "https://github.com/RealTotemG/Invenfloor/issues";

const root = document.getElementById("app");
const when = milliseconds =>
  milliseconds ? new Date(milliseconds).toLocaleString() : "never";

// ---------------------------------------------------------------------------
// STATE
// ---------------------------------------------------------------------------

let store = null;
let profile = null;        // the open profile, or null while in the launcher
let floor = null;

// The room you are INSIDE, however it is being drawn.
//
// It used to mean "the room the 3D view is showing", which made being inside
// a room two unrelated states: one for 3D, and the flat view's own `focused`
// for everything else. Stepping into a room and looking at a room in 3D were
// different things that happened to look similar, so Escape out of 3D could
// only ever take you all the way back to the floor.
//
// One idea instead: you are inside this room, and `where` says how it is
// drawn. That is the same shape the desktop app has, and it is what makes
// Escape able to drop from 3D to flat without letting go of the room.
let room = null;
let where = "plan";        // "plan" | "room" | "items"; "room" means 3D

// The room somebody pressed Escape in, so that the flat view does not hand it
// straight back to 3D. Cleared when they step out, so walking back in gives
// them 3D again: it is a "not this time", not a setting.
let flatFor = null;

// True only while showWorkspace is putting the view back the way it was.
// stepInto() fires onFocused, and onFocused is where "stepping into a room
// opens it in 3D" lives, so without this a rebuild of the flat view would
// bounce straight into 3D and take the room away from you.
let restoring = false;

let view = null;           // whichever canvas is up, if any
let history = null;
let saveTimer = null;
let saveTrouble = "";
let corners = 0;           // corners placed so far in a half-drawn room
const itemsState = { search: "", filter: "all", chosenId: null,
                     tagId: null, editingTags: false,
                     adding: false, queue: [], addTo: "", addTier: 0,
                     picked: [] };

// Is the open profile one of the saved ones? False for the made-up house and
// for a file opened when there is nowhere to put it. Changes to those are
// real, they just do not get written, and the bar has to say so rather than
// letting somebody spend twenty minutes on something that evaporates.
let kept = false;

function touched({ step = true } = {}) {
  if (step && history && profile) history.record(profile);
  refreshBar();
  if (!profile || !kept || !store || store.locked) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 500);
}

async function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  if (!profile || !kept || !store || store.locked) return;
  try {
    await store.save(profile);
    saveTrouble = "";
  } catch (error) {
    // Worth saying out loud rather than swallowing. A save that silently
    // fails is how somebody loses an afternoon: everything looks normal until
    // the tab is closed.
    saveTrouble = error.message ?? String(error);
    if (profile) showWorkspace();
  }
}

// A tab being hidden is the last reliable moment before it may be thrown away
// on a phone, and it is the one event that fires when somebody switches apps.
// beforeunload is too late to await anything.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden" && saveTimer) saveNow();
});

// ---------------------------------------------------------------------------
// THE LAUNCHER
// ---------------------------------------------------------------------------

async function showLauncher() {
  profile = null;
  floor = null;
  room = null;
  history = null;
  if (view) { view.stop(); view = null; }

  const screen = el("div", "screen");
  const page = put(el("div", "pad"), el("div", "limit"));
  const inner = page.firstChild;

  const bar = put(el("header", "bar"), el("h1", null, "Invenfloor"));
  put(bar, el("span", "grow"), el("span", "where small", "in this browser"));

  clear(root);
  put(root, bar, put(screen, page));

  await fillLauncher(inner);

  // Last, and outside everything above, because the ways out of fillLauncher
  // are the times it matters most: a browser that will not save, a store
  // nobody can unlock, a list that would not load. Those are the visits where
  // somebody needs to be able to tell you what happened, and they are exactly
  // the visits where an early return would have skipped the footer.
  let saved = "unknown";
  try { saved = store ? (await store.ids()).length : 0; } catch { /* leave it */ }
  put(inner, footer(store, saved, ISSUES, { el, put, button }));
}

async function fillLauncher(inner) {
  if (!store) {
    put(inner, notice("This browser will not save anything. Private browsing, "
                      + "or site data switched off. You can still open a file "
                      + "below and work in it, but nothing will be kept.", true));
    put(inner, importRow(), sampleRow());
    return;
  }

  put(inner, await lockPanel());

  if (store.locked) {
    const ids = await store.ids();
    put(inner, el("p", "note",
      `${ids.length} profile${ids.length === 1 ? "" : "s"} saved here. `
      + "Unlock to open them."));
    return;
  }

  let listed;
  try {
    listed = await store.list();
  } catch (error) {
    put(inner, notice(error.message ?? String(error), true));
    return;
  }

  for (const rescue of listed.recoveries) {
    put(inner, notice(`${rescue.profileName} would not open and was rescued `
                      + `from ${rescue.cameFrom}. The unreadable one is kept.`));
  }
  for (const refused of listed.refused) {
    put(inner, notice(`${refused.name || refused.id} could not be opened. `
                      + refused.why, true));
  }

  put(inner, el("h2", null, "Profiles"));
  const tiles = el("div", "tiles");
  for (const found of listed.profiles) {
    const rooms = [...found.allRooms()].length;
    const containers = [...found.allContainers()].length;

    // The tile is a div holding two separate clickable things, not one button
    // with more buttons inside it. Nesting them is invalid, and the press on
    // Download would open the profile on its way past.
    const tile = el("div", "tile card");
    const open = button("", "open", () => openProfile(found));
    put(open,
        put(el("div", "row tight"), swatch(found.color),
            el("span", "name truncate", found.name)),
        el("span", "stat", `${found.floors.length} floor${
          found.floors.length === 1 ? "" : "s"}, ${rooms} room${
          rooms === 1 ? "" : "s"}, ${containers} container${
          containers === 1 ? "" : "s"}`),
        el("span", "stat", `${found.items.length} item${
          found.items.length === 1 ? "" : "s"}`),
        el("span", "stat faint", `saved ${when(await store.savedAt(found.id))}`));

    put(tile, open, put(el("div", "row tight"),
      button("Download", "quiet small", () => S.download(found)),
      button("Delete", "quiet small danger", async () => {
        if (!confirm(`Delete "${found.name}"? Its dated backups are kept.`)) return;
        await store.delete(found.id);
        showLauncher();
      })));
    put(tiles, tile);
  }
  put(inner, tiles);

  put(inner, put(el("div", "row"),
    button("Start a new profile", "primary small", async () => {
      const made = new M.Profile({
        name: `Profile ${listed.profiles.length + 1}`,
        color: T.SWATCHES[listed.profiles.length % T.SWATCHES.length],
        floors: [new M.Floor({ name: "Ground floor" })],
      });
      await store.save(made);
      openProfile(made);
    })));

  put(inner, el("h2", null, "Open a file"));
  put(inner, el("p", "note",
    "A profile exported from the desktop app, or from here. It is read in "
    + "this page and never uploaded anywhere."));
  put(inner, importRow());

  put(inner, el("h2", null, "Or have a look without one"));
  put(inner, sampleRow());
}

function sampleRow() {
  return put(el("div"),
    el("p", "note", "A made-up house, kept only while this tab is open. "
      + "Nothing is saved unless you press Keep."),
    put(el("div", "row"),
      button("Open a made-up house", "small", () => openProfile(sample(), false))));
}

function importRow() {
  const row = el("div", "row");
  const picker = el("input");
  picker.type = "file";
  picker.accept = ".json,application/json";
  picker.className = "grow";
  const says = el("p", "note");

  picker.addEventListener("change", async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      if (store && !store.locked) {
        openProfile(await store.importProfile(text));
        return;
      }
      openProfile(S.readExport(text), false);
    } catch (error) {
      says.textContent = error.message ?? String(error);
      says.className = "note bad";
    }
  });

  return put(el("div"), put(row, picker), says);
}

// ---------------------------------------------------------------------------
// THE PASSPHRASE
// ---------------------------------------------------------------------------

async function lockPanel() {
  const card = el("div", "card");
  const says = el("p", "note");

  if (!store.hasLock) {
    const box = el("input");
    box.type = "password";
    box.placeholder = "a passphrase, to encrypt everything saved here";
    put(card, put(el("div", "row"), box,
      button("Lock this browser", "small", async () => {
        if (!box.value) { says.textContent = "It needs a passphrase."; return; }
        says.textContent = "Encrypting everything already saved…";
        try {
          const code = await store.addLock(box.value);
          clear(says);
          says.className = "note";
          put(says,
            el("b", "warn", "Write this down now. "),
            document.createTextNode(
              "It is the only way back in if you forget the passphrase, and "
              + "this is the one and only time it is readable. There is no "
              + "reset: that is the point, not an oversight."),
            el("div", "code", code));
        } catch (error) {
          says.textContent = error.message ?? String(error);
          says.className = "note bad";
        }
      })), says);
    return card;
  }

  if (store.locked) {
    const box = el("input");
    box.type = "password";
    box.placeholder = "passphrase, or a recovery code";
    const unlock = async () => {
      says.textContent = "Unlocking…";
      says.className = "note";
      try {
        const used = await store.unlock(box.value);
        if (used === "recovery") says.textContent = "Open, using the recovery code.";
        showLauncher();
      } catch (error) {
        says.textContent = error.message ?? String(error);
        says.className = "note bad";
      }
    };
    box.addEventListener("keydown", event => {
      if (event.key === "Enter") unlock();
    });
    put(card, put(el("div", "row"), box, button("Unlock", "primary small", unlock)),
        says);
    return card;
  }

  put(card, put(el("div", "row"),
    el("span", "grow small muted", "Unlocked. What is in the database is "
      + "ciphertext; only this tab can read it."),
    button("Lock now", "quiet small", () => { store.relock(); showLauncher(); }),
    button("Remove the passphrase", "quiet small", async () => {
      says.textContent = "Decrypting everything…";
      await store.removeLock();
      showLauncher();
    })), says);
  return card;
}

// ---------------------------------------------------------------------------
// THE WORKSPACE
// ---------------------------------------------------------------------------

function openProfile(found, isKept = true) {
  profile = found;
  kept = isKept && Boolean(store) && !store.locked;
  floor = found.floors[0] ?? null;
  room = null;
  where = "plan";
  history = new History(found);
  saveTrouble = "";
  itemsState.search = "";
  itemsState.filter = "all";
  itemsState.tagId = null;
  itemsState.editingTags = false;
  itemsState.adding = false;
  itemsState.queue = [];
  itemsState.addTo = "";
  itemsState.addTier = 0;
  itemsState.picked = [];
  itemsState.chosenId = null;
  showWorkspace();
}

let parts = null;          // the pieces of the workspace, for partial redraws

function showWorkspace() {
  if (view) { view.stop(); view = null; }
  corners = 0;

  const bar = el("header", "bar");
  const workspace = el("div", "workspace");
  const strips = el("div", "strips");
  parts = { bar, strips, panel: null, screen: null };

  put(workspace, strips);
  clear(root);
  put(root, bar, workspace);

  if (where === "items") {
    const screen = el("div", "screen");
    parts.screen = screen;
    put(workspace, screen);
    refreshBar();
    drawStrips();
    drawItems();
    return;
  }

  const split = el("div", "split");
  const stage = el("div", "stage");
  const canvas = el("canvas");
  const panel = el("aside", "panel");
  parts.panel = panel;
  put(stage, canvas);
  put(split, stage, panel);
  put(workspace, split);

  if (where === "room" && room) {
    view = new RoomView(canvas, {
      onChanged: () => touched(),
      onSelected: () => drawPanel(),
      onEscape: () => seeItFlat(),
      onModeChanged: () => drawStrips(),
      onAdded: () => { drawStrips(); drawPanel(); },
    });
    view.show(profile, room);
  } else {
    view = new FloorView(canvas, {
      onChanged: () => touched(),
      // The strips redraw on a selection too, not only the panel: the row
      // that says what dragging a room does is only there while a room is
      // selected, so it has to appear and disappear with one.
      onSelected: () => { drawStrips(); drawPanel(); },
      onFocused: focused => steppedInto(focused),
      onModeChanged: () => drawStrips(),
      onDrawingChanged: placed => { corners = placed; drawStrips(); },
    });
    view.show(profile, floor);

    // Put us back inside whichever room we were in. show() clears the focus,
    // so without this, anything that rebuilds the workspace while you are
    // standing in a room quietly puts you back out on the floor.
    if (room) {
      restoring = true;
      view.stepInto(room);
      restoring = false;
    }
  }

  refreshBar();
  drawStrips();
  drawPanel();
}

/** Somebody stepped into a room, or out of one, on the flat plan.
 *
 *  This is where "stepping into a room opens it in 3D" lives, and it is here
 *  rather than on the double-click because there is more than one way in: the
 *  canvas, the Step inside button, and undo putting you back where you were.
 *  One place means they cannot disagree.
 */
function steppedInto(focused) {
  if (restoring) { drawStrips(); drawPanel(); return; }

  room = focused;

  if (!focused) {
    // Out on the floor again, so the "show me this one flat" note expires.
    // Walking back into the same room should give you 3D, the same as any
    // other room would.
    flatFor = null;
    drawStrips();
    drawPanel();
    return;
  }

  if (profile.view3d && flatFor !== focused.id) {
    where = "room";
    showWorkspace();
    return;
  }

  drawStrips();
  drawPanel();
}

/** Escape out of 3D: the flat plan of the room you are standing in.
 *
 *  Not all the way out to the floor. Leaving the room is the next rung down,
 *  and the flat view already has it, so pressing Escape twice walks you out
 *  the way it always did.
 */
function seeItFlat() {
  if (!room) return;
  flatFor = room.id;
  where = "plan";
  showWorkspace();
}

/** Open the room you are inside in 3D, whatever was said before.
 *
 *  Clears the Escape note, because asking for 3D is a clearer statement than
 *  a note saying you did not want it a minute ago.
 */
function seeItInThree(chosen = room) {
  if (!chosen) return;
  room = chosen;
  flatFor = null;
  where = "room";
  showWorkspace();
}

function refreshBar() {
  if (!parts) return;
  const bar = clear(parts.bar);

  const back = button("", "quiet small", () => { saveNow(); showLauncher(); },
                      "Back to the list of profiles");
  put(back, icon("back"), el("span", null, "Profiles"));

  put(bar, back,
    put(el("div", "grow"),
        put(el("div", "row tight"), swatch(profile.color),
            el("strong", "truncate", profile.name)),
        el("div", "where truncate", whereLine())));

  const undo = button("", "quiet small icon-only", () => step("undo"), "Undo");
  put(undo, icon("undo"));
  undo.disabled = !history?.canUndo;
  const redo = button("", "quiet small icon-only", () => step("redo"), "Redo");
  put(redo, icon("redo"));
  redo.disabled = !history?.canRedo;
  put(bar, undo, redo);

  if (!kept) {
    put(bar, button("Keep", "primary small", async () => {
      if (!store || store.locked) return;
      await store.save(profile);
      kept = true;
      refreshBar();
      drawStrips();
    }, "Save this profile in this browser"));
  }
  put(bar, button("Download", "quiet small", () => S.download(profile),
                  "Save it as a file you can open on the desktop app"));
}

function whereLine() {
  if (where === "items") return "Items";
  if (where === "room" && room) return `${floor.name} / ${room.name} · inside`;
  return floor ? floor.name : "no floors";
}

function step(which) {
  // Where you were, by id, before any of this. Undo swaps the whole profile
  // and the screen is then built again from nothing, so without writing these
  // down first they are simply gone.
  //
  // It matters more than it sounds. Undo is the button people press most
  // while they are fiddling with a shelf, and fiddling with a shelf is done
  // from inside a room with a container selected. Losing both on every press
  // meant one undo cost you your place and walking back took more clicks than
  // the edit did.
  const wasFocused = view?.focused?.id ?? null;
  const wasSelected = view?.selected?.id ?? null;

  const back = which === "undo" ? history?.undo() : history?.redo();
  if (!back) return;
  profile = back;
  // The old Floor and Room objects belong to the profile that was just
  // replaced, so anything holding one is holding a ghost. Find the same ids in
  // the new one, and fall back to the first if whatever was open is gone.
  floor = profile.floors.find(each => each.id === floor?.id) ?? profile.floors[0] ?? null;
  room = floor?.rooms.find(each => each.id === room?.id) ?? null;
  if (!room && where === "room") where = "plan";
  touched({ step: false });
  showWorkspace();
  putBack(wasFocused, wasSelected);
}

/** Step back into the room you were in and reselect what you had.
 *
 *  By id, and quietly if it is not there any more: undoing the making of a
 *  container means the thing that was selected no longer exists, which is an
 *  ordinary outcome of undo rather than a fault.
 */
function putBack(focusedId, selectedId) {
  if (!view) return;

  // The two views want different things. The 3D room takes an id, the floor
  // plan takes the object. Told apart by `where`, which is what decided which
  // of them to build a moment ago, rather than by asking the view what it is.
  if (where === "room") {
    if (selectedId) view.select(selectedId);
    return;
  }

  if (focusedId) {
    const again = floor?.rooms.find(each => each.id === focusedId);
    if (again) view.stepInto(again);
  }

  if (!selectedId) return;
  const chosen = floor?.rooms.find(each => each.id === selectedId)
    ?? floor?.rooms.flatMap(each => each.containers)
                   .find(each => each.id === selectedId);
  if (chosen) view.select(chosen);
}

// ---------------------------------------------------------------------------
// THE TOOLBARS
// ---------------------------------------------------------------------------

function drawStrips() {
  if (!parts) return;
  const strips = clear(parts.strips);

  // The warning belongs here rather than in refreshBar, which runs on every
  // change: prepending it there added another copy of the same line every
  // time anything moved.
  if (!kept) {
    put(strips, put(el("div", "chips"),
      el("span", "small warn", store && !store.locked
        ? "Not saved. Changes stay until this tab closes, unless you press Keep."
        : "Not saved, and there is nowhere to save it. Download it to keep it.")));
  }

  // ONE BAR, WHERE THERE USED TO BE FIVE
  // ------------------------------------
  // Where you are, which floor, and the tools each had a row, with a row of
  // room shapes under those and a row of drag modes under that. Measured on a
  // 900 pixel window it came to 356 pixels of toolbar before any floor plan
  // appeared: forty per cent of the screen spent telling you what you could
  // do, and the rest of it for actually doing it.
  //
  // Three things fixed that. The floors became a dropdown, which they wanted
  // to be anyway the moment there could be six of them. The shapes only
  // appear while a room is being drawn, because that is the only time they do
  // anything. What dragging a room does moved onto the end of the hint line,
  // which is already the line talking about the room you have selected.
  //
  // The tools themselves stayed as buttons with their names showing. They are
  // the part somebody has to find without being told, and a dropdown you have
  // to open before you can see what is in it is how that gets lost.
  const bar = el("div", "chips toolbar");

  put(bar, toolButton("plan", "Floor plan", {
    on: where === "plan",
    // Pressing this from 3D keeps you inside the room, flat, the same as
    // Escape. Being inside a room IS the floor plan, with the rest of it
    // dimmed, so throwing you out to the whole floor as well would be doing
    // two things when you asked for one. Step out is the button for that.
    tooltip: where === "room" && room
      ? `The flat plan, still inside ${room.name}`
      : "Draw rooms and arrange what is in them",
    onClick: () => {
      if (where === "room" && room) { seeItFlat(); return; }
      where = "plan";
      showWorkspace();
    },
  }));
  // The room you are inside gets a chip, and it stays there on the Items
  // screen. That is the whole point of it: go and look something up in the
  // catalog and the way back to the room you were standing in is still on
  // screen, rather than being a hunt back through the floor plan for a room
  // whose name you might not remember.
  if (room) {
    const inThree = where === "room";
    put(bar, toolButton("three",
      `${inThree ? "3D" : "In"}: ${M.short(room.name, 14)}`, {
        on: where !== "items",
        tooltip: where === "items"
          ? `Back to ${room.name}`
          : "The room you are working inside",
        // Says where you are; it does not change how the room is drawn.
        //
        // It used to jump you into 3D when pressed from the flat view, on
        // the reasoning that it was the only way back in after Escape. That
        // was the wrong button to hang it on: a chip that reads "In: Garage"
        // is telling you where you are standing, and a label that moves you
        // somewhere when you press it is a label that lies. Switching how the
        // room is drawn is what the 3D button does, so that is where it went.
        onClick: () => {
          if (where !== "items") return;    // it is a label, not a door
          // Back the way you left it. 3D unless you had asked for this one
          // flat, in which case flat is what you asked for.
          where = (profile.view3d && flatFor !== room.id) ? "room" : "plan";
          showWorkspace();
        },
      }));
  }
  put(bar, toolButton("items", "Items", {
    on: where === "items",
    tooltip: "Everything in the catalog, and where it lives",
    onClick: () => { where = "items"; showWorkspace(); },
  }));

  if (where === "items") {
    put(strips, bar);
    return;
  }

  put(bar, el("span", "sep"), floorPicker());

  if (where === "room") {
    // Adding a container from in here, not only on the flat plan. This is
    // the view where you can see how much wall is free and how tall the
    // thing next to it stands, which is the decision being made when you
    // put a shelf somewhere.
    put(bar, el("span", "sep"), toolButton("box", "Add container", {
      on: view.adding,
      tooltip: "Drag out a rectangle on the floor of this room",
      onClick: () => view.setAdding(!view.adding),
    }));
    put(bar, el("span", "grow"), threeDToggle());
    put(bar, button("See it flat", "quiet small", () => seeItFlat(),
                    "The flat plan of this room, without leaving it. "
                    + "Escape does the same."));
    put(bar, button("Step out", "quiet small",
                    () => { room = null; flatFor = null; where = "plan";
                            showWorkspace(); },
                    "Back to the whole floor"));
    put(strips, bar);

    if (view.adding) {
      put(strips, hintStrip(
        "Drag a rectangle out on the floor to make a container there. It "
        + "turns red where it will not fit.",
        button("Cancel", "quiet small danger", () => view.setAdding(false),
               "Put the tool away")));
    } else {
      put(strips, hintStrip(
        "Drag a container to move it. It slides along a wall rather than "
        + "leaving the room. Press one to see what is inside. Escape gives "
        + "you the flat plan of this room, and again steps out of it."));
    }
    return;
  }

  put(bar, el("span", "sep"));
  const tool = (name, label, mode, tip, preset = null) =>
    toolButton(name, label, {
      on: view.mode === mode && view.preset === preset,
      tooltip: tip,
      onClick: () => view.setMode(mode, preset),
    });
  put(bar,
    tool("select", "Select", F.SELECT,
         "Press a room to pick it. Press it twice to step inside."),
    tool("draw", "Draw room", F.DRAW,
         "Place the corners of a room one at a time, or pick a ready-made "
         + "shape from the row that appears"),
    tool("box", "Add container", F.BOX,
         "Drag a rectangle inside a room to make a shelf, drawer or bin"));
  put(bar, el("span", "grow"), threeDToggle());
  put(bar, toolButton("fit", "Fit", {
    tooltip: "Put everything on this floor back on the screen",
    onClick: () => view.fit(),
  }));
  put(strips, bar);

  // The shapes, and only while a room is being drawn.
  //
  // SHAPE counts as drawing every bit as much as DRAW does, and the test has
  // to allow both. Pressing a preset is how you leave DRAW mode, so checking
  // for DRAW alone would make the row vanish underneath the button somebody
  // had just that moment pressed.
  if (view.mode === F.DRAW || view.mode === F.SHAPE) {
    const shapes = el("div", "chips");
    put(shapes, el("span", "strip-label", "Or start from a shape"));
    const shapeIcons = { Rectangle: "rectangle", Square: "square",
                         Circle: "circle", Triangle: "triangle",
                         "L-shape": "lshape" };
    for (const [name] of M.ROOM_PRESETS) {
      put(shapes, toolButton(shapeIcons[name] ?? "rectangle", name, {
        on: view.mode === F.SHAPE && view.preset === name,
        tooltip: `Drag out a ${name.toLowerCase()} room, or press once for a `
                 + "default sized one",
        onClick: () => view.setMode(F.SHAPE, name),
      }));
    }
    put(strips, shapes);
  }

  put(strips, hintStrip(...hintFor()));
}

/** The 3D switch. A setting, not a trip.
 *
 *  It says what happens the NEXT time you step into a room, which is why it
 *  can be pressed out on the floor overview where nothing visible changes.
 *  The desktop app hit the same thing and answered it in the hint line; this
 *  does it in the tooltip and by staying lit, and the line under the toolbar
 *  mentions 3D while it is on so that pressing it out here is not a button
 *  that appears to do nothing.
 *
 *  Kept on the profile rather than in this tab, so it survives a reload and
 *  so two profiles can disagree. A warehouse of identical racking is easier
 *  flat; a house is easier in 3D.
 */
function threeDToggle() {
  return toolButton("three", "3D", {
    on: profile.view3d,
    tooltip: profile.view3d
      ? "Rooms open in 3D when you step into one. Press to keep them flat."
      : "Rooms stay flat. Press to have them open in 3D when you step in.",
    onClick: () => {
      // Pressed while a room is showing flat because of Escape, with the
      // setting still on. That press means "give me 3D back": the setting is
      // already on, so turning it off would only agree with what is already
      // on the screen. It is also now the only way back into 3D for a room
      // you are standing in, which is what makes it the right button.
      if (room && profile.view3d && flatFor === room.id) {
        flatFor = null;
        where = "room";
        showWorkspace();
        return;
      }

      profile.view3d = !profile.view3d;
      touched();

      // Standing in a room when the switch is thrown, so change what is on
      // screen now rather than making them step out and back in to see it.
      if (room) {
        flatFor = null;
        where = profile.view3d ? "room" : "plan";
      }
      showWorkspace();
    },
  });
}

/** Which floor you are looking at, and a button to add another.
 *
 *  A row of buttons was fine with one floor and would be silly with six. A
 *  dropdown is the same width whatever is in it, which is the whole reason to
 *  use one here.
 *
 *  The wrapper is not class "row", and that is deliberate rather than fussy:
 *  the stylesheet gives a select inside a .row `flex: 1 1 0; width: 0` so that
 *  it fills a panel, and a select told to be zero wide on a toolbar simply
 *  disappears.
 */
function floorPicker() {
  const picker = choose(null,
    profile.floors.map(each => [each.id, M.short(each.name, 24)]),
    floor?.id,
    value => {
      floor = profile.floors.find(each => each.id === value) ?? floor;
      room = null;
      where = "plan";
      showWorkspace();
    });
  picker.className = "floor-pick";
  picker.title = "Which level of the building";

  const add = button("+", "quiet small", () => {
    const made = new M.Floor({
      name: `Floor ${profile.floors.length + 1}`,
      color: T.SWATCHES[profile.floors.length % T.SWATCHES.length],
    });
    profile.floors.push(made);
    floor = made;
    room = null;
    touched();
    showWorkspace();
  }, "Add another level to this building");

  return put(el("div", "pick"), picker, add);
}

/** Move, Resize and Reshape, for the room that is selected.
 *
 *  On the end of the hint line rather than in a row of its own. These only
 *  mean anything while a room is selected, which is exactly when the hint
 *  line is already describing that room, so the two belong on one line.
 */
function editModeButtons() {
  const row = el("div", "row tight");
  for (const [name, label, mode, tip] of [
    ["step", "Move", F.MOVE, "Drag the room around the floor"],
    ["fit", "Resize", F.RESIZE,
     "Square handles round the outside. Dragging one stretches the whole "
     + "room and keeps its shape."],
    ["draw", "Reshape", F.VERTICES,
     "A round handle on every corner. Drag one to move that corner."],
  ]) {
    put(row, toolButton(name, label, {
      on: view.editMode === mode,
      tooltip: tip,
      onClick: () => { view.setEditMode(mode); drawStrips(); },
    }));
  }
  return row;
}

/** The line under the toolbar that says what to do next.
 *
 *  The single most useful thing on the screen for somebody who has not used
 *  this before. A toolbar can only say what a button is called. This can say
 *  what happens when you press the canvas right now, which is the part nobody
 *  can guess and everybody needs exactly once.
 */
function hintStrip(text, extra = null) {
  const strip = el("div", "chips hint");
  put(strip, icon("select", 14), el("span", "small faint grow", text));
  if (extra) put(strip, extra);
  return strip;
}

function hintFor() {
  if (view.mode === F.DRAW) {
    const buttons = put(el("div", "row tight"),
      corners ? button("Take back a corner", "quiet small",
        () => view.undoLastCorner(),
        "Remove the last corner you placed") : null,
      button("Cancel", "quiet small danger", () => view.cancelDrawing(),
             "Throw this shape away and go back to Select"));
    if (!corners) {
      return ["Press the canvas to place the first corner.", buttons];
    }
    if (corners < 3) {
      return [`${corners} corner${corners === 1 ? "" : "s"} placed. A room `
              + `needs at least three.`, buttons];
    }
    return [`${corners} corners. Press the ringed first corner, or Enter, to `
            + "close the room. Escape or Cancel throws it away.", buttons];
  }

  if (view.mode === F.SHAPE) {
    return [`Drag out a ${String(view.preset).toLowerCase()} anywhere on the `
            + "floor, or press once for a default sized one.",
            button("Cancel", "quiet small", () => view.setMode(F.SELECT),
                   "Go back to Select")];
  }

  if (view.mode === F.BOX) {
    return ["Drag a rectangle inside a room to make a container there.",
            button("Cancel", "quiet small", () => view.setMode(F.SELECT),
                   "Go back to Select")];
  }

  if (view.focused) {
    return ["Inside " + view.focused.name + ". Drag a container to move it, "
            + "or drag its corners to resize. Press the floor outside to come "
            + "back out.",
            button("Step back out", "quiet small", () => view.stepInto(null),
                   "Stop working inside this room")];
  }

  if (view.selected instanceof M.Room) {
    const mode = view.editMode === F.RESIZE
      ? "Drag a square handle to stretch the whole room."
      : (view.editMode === F.VERTICES
        ? "Drag a round handle to move one corner. Press inside to add a "
          + "corner, press a corner twice to remove it."
        : "Drag the room to move it.");
    return [`${view.selected.name} selected. ${mode} Press it twice to step `
            + `inside${profile.view3d ? " and see it in 3D" : ""}.`,
            editModeButtons()];
  }

  if (profile.floors.length && floor?.rooms.length) {
    // Saying "and see it in 3D" while the switch is on is what stops that
    // switch being a button that appears to do nothing. Pressed out here on
    // the floor it changes no pixels, because 3D only replaces the canvas
    // once you are inside a room. This line is where it says so.
    return [`Press a room to select it. Press it twice to step inside${
      profile.view3d ? " and see it in 3D" : ""}. Two fingers, or the wheel, `
      + "move the camera."];
  }

  // An empty floor, which is where everybody starts, so it gets the one
  // button rather than a description of where to find it.
  //
  // This used to read "pick a shape above", which was true when the shapes
  // were a row that was always there. They are not any more, and a line
  // pointing at something that is not on the screen is worse than no line:
  // the reader concludes the app is broken rather than that the sentence is
  // out of date. So it names the button that reveals them, and hands it over.
  return ["Nothing on this floor yet. Draw room lets you place the corners "
          + "yourself, or start from a ready-made shape.",
          button("Draw room", "primary small",
                 () => view.setMode(F.DRAW),
                 "Place the corners of a room, or pick a ready-made shape")];
}

// ---------------------------------------------------------------------------
// THE ITEMS SCREEN
// ---------------------------------------------------------------------------

function drawItems() {
  if (!parts?.screen) return;
  itemsScreen(parts.screen, profile, itemsState, {
    changed: () => touched(),
    again: () => drawItems(),
  });
}

// ---------------------------------------------------------------------------
// THE INSPECTOR
// ---------------------------------------------------------------------------

function drawPanel() {
  if (!parts?.panel) return;
  const panel = clear(parts.panel);

  if (saveTrouble) put(panel, notice("That did not save. " + saveTrouble, true));

  const chosen = view?.selected ?? null;
  if (chosen instanceof M.Room) return roomPanel(panel, chosen);
  if (chosen instanceof M.Container) return containerPanel(panel, chosen);
  return emptyPanel(panel);
}

function emptyPanel(panel) {
  put(panel, el("p", "note", where === "room"
    ? "Press a container to see what is in it."
    : "Nothing selected. The line under the toolbar says what the tool you "
      + "have picked will do."));

  const loose = profile.unfiledItems().length;
  if (loose) {
    const row = put(el("div", "row"),
      button(`${loose} item${loose === 1 ? "" : "s"} not in any container`,
             "quiet small", () => {
               where = "items";
               itemsState.filter = "unfiled";
               showWorkspace();
             }, "Show them on the items screen"));
    put(panel, row);
  }
}

/** Name, color and a row of buttons, which every kind of thing wants. */
function header(panel, thing, { onRename, onRecolor, onDelete, onDuplicate }) {
  put(panel, put(el("div", "row"),
    field(thing.name, value => onRename(M.cleanName(value)),
          { placeholder: "name" })));
  put(panel, colors(thing.color, onRecolor));

  const row = el("div", "row tight");
  if (onDuplicate) {
    const copy = button("", "quiet small", onDuplicate, "Make another one like this");
    put(copy, icon("copy"), el("span", null, "Duplicate"));
    put(row, copy);
  }
  if (onDelete) {
    const drop = button("", "quiet small danger", onDelete, "Delete this");
    put(drop, icon("trash"), el("span", null, "Delete"));
    put(row, drop);
  }
  put(panel, row);
}

function roomPanel(panel, chosen) {
  put(panel, el("h3", null, "Room"));
  header(panel, chosen, {
    // drawStrips and refreshBar as well as the panel, because a name is on
    // screen in more places than the box you typed it into. The line under
    // the toolbar says "<name> selected", the chip says "3D: <name>" and the
    // top bar says which room you are inside. Redrawing only the panel left
    // all three saying the old name, and worse, saying it NEXT to the new
    // one: the app called the same room two different things at once until
    // you happened to click something else.
    onRename: name => {
      chosen.name = name;
      touched();
      view.draw();
      drawPanel();
      drawStrips();
      refreshBar();
    },
    onRecolor: color => { chosen.color = color; touched(); view.draw(); drawPanel(); },
    onDuplicate: () => {
      const copy = M.duplicate(chosen, M.copyName(chosen.name,
        floor.rooms.map(r => r.name)));
      copy.x += T.GRID_SIZE * 2;
      copy.y += T.GRID_SIZE * 2;
      floor.rooms.push(copy);
      touched();
      view.select(copy);
      drawStrips();
    },
    onDelete: () => {
      if (!confirm(`Delete "${chosen.name}" and its ${
        chosen.containers.length} container(s)? What was in them stays in the `
        + "catalog, not filed anywhere.")) return;
      profile.deleteRoom(chosen.id);
      touched();
      view.select(null);
      view.draw();
      drawStrips();
    },
  });

  const [, , wide, high] = chosen.bounds();
  put(panel, put(el("div", "row"),
    numberField("Width", wide, value => {
      chosen.resizeTo(Math.max(value, T.GRID_SIZE), high, 0, 0);
      for (const box of chosen.containers) M.fitContainer(chosen, box);
      touched(); view.draw(); drawPanel();
    }, { step: T.GRID_SIZE, min: T.GRID_SIZE }),
    numberField("Depth", high, value => {
      chosen.resizeTo(wide, Math.max(value, T.GRID_SIZE), 0, 0);
      for (const box of chosen.containers) M.fitContainer(chosen, box);
      touched(); view.draw(); drawPanel();
    }, { step: T.GRID_SIZE, min: T.GRID_SIZE })));

  // Where it sits, not just how big it is.
  //
  // Size without position is a trap rather than half a feature. Sketch three
  // rooms roughly, then type their real dimensions, and each one grows from
  // its top-left corner into whatever is beside it, with dragging as the only
  // way back. Typing the real size is the obvious thing to do and it reliably
  // made a mess.
  put(panel, put(el("div", "row"),
    numberField("X", chosen.x, value => {
      chosen.x = Math.round(value);
      touched(); view.draw(); drawPanel();
    }, { step: T.GRID_SIZE }),
    numberField("Y", chosen.y, value => {
      chosen.y = Math.round(value);
      touched(); view.draw(); drawPanel();
    }, { step: T.GRID_SIZE })));

  // And say so when it is sitting on top of a neighbour. A warning rather
  // than a refusal: two rooms on the same spot is nearly always a mistake,
  // but a mezzanine or a stairwell drawn over the room below it is not, and
  // an app that will not let you draw your own building is worse than one
  // that raises an eyebrow.
  const sittingOn = M.roomsOverlapping(floor, chosen);
  if (sittingOn.length) {
    put(panel, notice(
      `This is sitting on top of ${sittingOn.map(r => M.short(r.name, 18))
        .join(", ")}. Rooms are allowed to overlap, but if you did not mean `
      + "it, the X and Y above will move this one out of the way.", true));
  }

  const lock = el("label", "check");
  const tick = el("input");
  tick.type = "checkbox";
  tick.checked = chosen.locked;
  tick.addEventListener("change", () => {
    chosen.locked = tick.checked;
    touched();
    view.draw();
    drawStrips();
  });
  put(lock, tick, el("span", "small", "Locked, so it cannot be moved by accident"));
  put(panel, lock);

  // A tag on a room says what belongs in it, which is the half of the idea
  // that makes "In the wrong room" able to answer anything at all. Tag the
  // Garage with Tools, tag a spanner with Tools, leave the spanner in the
  // kitchen, and the items screen can now say so.
  put(panel, el("h4", null, "What belongs in here"));
  put(panel, tagRow(profile, chosen, {
    changed: () => { touched(); view.draw(); },
    again: () => drawPanel(),
    onNewTag: () => makeTag(profile),
  }));

  // Step inside goes through the view rather than setting anything here, so
  // that it lands in steppedInto() like a double-click on the canvas does and
  // gets the same answer about 3D. Two ways in that decide separately is how
  // one of them ends up flat and the other does not.
  const stepIn = button("", profile.view3d ? "small" : "primary small",
                        () => view.stepInto(chosen),
                        profile.view3d
                          ? "Work on what is in this room, in 3D"
                          : "Work on what is in this room");
  put(stepIn, icon("step"), el("span", null, "Step inside"));
  const row = put(el("div", "row"), stepIn);

  // A separate 3D button only earns its place while the switch is off. With
  // it on, Step inside already gives you 3D and a second button promising the
  // same thing is just something else to read.
  if (!profile.view3d) {
    const three = button("", "primary small", () => seeItInThree(chosen),
                         "See this one room in 3D, without turning 3D on for "
                         + "the rest of them");
    put(three, icon("three"), el("span", null, "3D view"));
    put(row, three);
  }
  put(panel, row);

  put(panel, el("p", "note small",
    `${chosen.points.length} corners, ${chosen.containers.length} container${
      chosen.containers.length === 1 ? "" : "s"}, `
    + `${profile.itemsInRoom(chosen).length} different things in it`));
}

function containerPanel(panel, chosen) {
  const holder = where === "room" ? room : view.roomOf(chosen);
  put(panel, el("h3", null, "Container"));
  if (holder) {
    put(panel, el("p", "small faint truncate", profile.containerPath(chosen.id)));
  }

  header(panel, chosen, {
    // Same as a room's: the name is drawn in the strips and the bar too.
    onRename: name => {
      chosen.name = name;
      touched();
      view.draw();
      drawPanel();
      drawStrips();
      refreshBar();
    },
    onRecolor: color => { chosen.color = color; touched(); view.draw(); drawPanel(); },
    onDuplicate: holder ? () => {
      const copy = M.duplicate(chosen, M.copyName(chosen.name,
        holder.containers.map(c => c.name)));
      const [x, y] = M.nearestFit(holder, copy.x + T.GRID_SIZE,
                                  copy.y + T.GRID_SIZE, copy.w, copy.h);
      copy.x = x; copy.y = y;
      holder.containers.push(copy);
      touched();
      view.select(copy);
      view.draw();
    } : null,
    onDelete: holder ? () => {
      const inside = profile.itemCountInContainer(chosen.id);
      if (inside && !confirm(`Delete "${chosen.name}"? The ${inside} thing${
        inside === 1 ? "" : "s"} in it stay in the catalog, not filed `
        + "anywhere.")) return;
      profile.deleteContainer(chosen.id);
      touched();
      view.select(null);
      view.draw();
    } : null,
  });

  put(panel, put(el("div", "row"),
    numberField("Width", chosen.w, value => {
      resizeContainer(holder, chosen, Math.max(value, M.MIN_CONTAINER_SIZE), chosen.h);
    }, { step: T.GRID_SIZE, min: M.MIN_CONTAINER_SIZE }),
    numberField("Depth", chosen.h, value => {
      resizeContainer(holder, chosen, chosen.w, Math.max(value, M.MIN_CONTAINER_SIZE));
    }, { step: T.GRID_SIZE, min: M.MIN_CONTAINER_SIZE })));

  put(panel, choose("Height, which only the 3D view uses",
    M.CONTAINER_HEIGHTS.map(([name, value]) => [value, name]),
    M.nearestHeight(chosen.height), value => {
      chosen.height = M.clampHeight(Number(value));
      touched();
      view.draw();
    }));

  put(panel, el("h4", null, "Tags"));
  put(panel, tagRow(profile, chosen, {
    changed: () => { touched(); view.draw(); },
    again: () => drawPanel(),
    onNewTag: () => makeTag(profile),
  }));

  contentsPanel(panel, profile, chosen, {
    changed: () => { touched(); view.draw(); },
    again: () => drawPanel(),
  });
}

function resizeContainer(holder, box, wide, high) {
  if (!holder) return;
  if (M.roomContainsRect(holder, box.x, box.y, wide, high)) {
    box.w = wide;
    box.h = high;
  } else {
    const [x, y, w, h] = M.nearestFit(holder, box.x, box.y, wide, high);
    box.x = x; box.y = y; box.w = w; box.h = h;
  }
  touched();
  view.draw();
  drawPanel();
}

// ---------------------------------------------------------------------------
// START
// ---------------------------------------------------------------------------

try {
  store = await S.Store.open();
} catch (error) {
  console.warn("[app] no storage:", error);
  store = null;
}

// ?demo opens the made-up house straight away instead of the profile screen.
//
// It exists so the portfolio site can put THIS on its front page rather than
// a hand-written imitation of it. The imitation was seven hundred lines of a
// second drawing implementation, and a second implementation of anything is a
// promise to fix every bug twice: the draw-order bug lived on in that copy for
// weeks after iso.js was right, because nobody thinks to go and check the
// demo. A page that frames the real app cannot be out of date with the real
// app.
//
// Everything past this line is the ordinary app. The flag decides what is
// open when you arrive and nothing else, so a visitor can press Profiles and
// find their own, and Keep still keeps. `false` is the same second argument
// the "Open a made-up house" button passes: not kept until somebody says so.
if (new URLSearchParams(location.search).has("demo")) {
  openProfile(sample(), false);
} else {
  showLauncher();
}

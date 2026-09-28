/**
 * app.js
 * ======
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
let room = null;           // the room the 3D view is showing
let where = "plan";        // "plan" | "room" | "items"
let view = null;           // whichever canvas is up, if any
let history = null;
let saveTimer = null;
let saveTrouble = "";
let corners = 0;           // corners placed so far in a half-drawn room
const itemsState = { search: "", filter: "all", chosenId: null };

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
    });
    view.show(profile, room);
  } else {
    view = new FloorView(canvas, {
      onChanged: () => touched(),
      // The strips redraw on a selection too, not only the panel: the row
      // that says what dragging a room does is only there while a room is
      // selected, so it has to appear and disappear with one.
      onSelected: () => { drawStrips(); drawPanel(); },
      onFocused: () => { drawStrips(); drawPanel(); },
      onModeChanged: () => drawStrips(),
      onDrawingChanged: placed => { corners = placed; drawStrips(); },
    });
    view.show(profile, floor);
  }

  refreshBar();
  drawStrips();
  drawPanel();
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

  // Which of the three places you are in. Always first, always the same two
  // buttons, so there is one fixed thing on the screen to navigate by.
  const places = el("div", "chips places");
  put(places, toolButton("plan", "Floor plan", {
    on: where === "plan",
    tooltip: "Draw rooms and arrange what is in them",
    onClick: () => { where = "plan"; showWorkspace(); },
  }));
  // The 3D view is a place you can be, so it gets a chip of its own rather
  // than a separate back button somewhere else on the screen. Two buttons
  // both saying "Floor plan", one of them highlighted, is how you make
  // somebody wonder which one they are supposed to press.
  if (where === "room" && room) {
    put(places, toolButton("three", `3D: ${M.short(room.name, 14)}`, {
      on: true,
      tooltip: "Looking inside this room",
      onClick: () => {},
    }));
  }
  put(places, toolButton("items", "Items", {
    on: where === "items",
    tooltip: "Everything in the catalog, and where it lives",
    onClick: () => { where = "items"; showWorkspace(); },
  }));
  put(strips, places);

  if (where === "items") return;

  const floors = el("div", "chips");
  put(floors, el("span", "strip-label", "Floors"));
  for (const each of profile.floors) {
    put(floors, button(M.short(each.name, 20),
      `small${each === floor ? " on" : ""}`, () => {
        floor = each;
        room = null;
        where = "plan";
        showWorkspace();
      }, `Show ${each.name}`));
  }
  put(floors, button("+ Floor", "quiet small", () => {
    const made = new M.Floor({
      name: `Floor ${profile.floors.length + 1}`,
      color: T.SWATCHES[profile.floors.length % T.SWATCHES.length],
    });
    profile.floors.push(made);
    floor = made;
    room = null;
    touched();
    showWorkspace();
  }, "Add another level to this building"));
  put(strips, floors);

  if (where === "room") {
    put(strips, hintStrip(
      "Drag a container to move it. It slides along a wall rather than "
      + "leaving the room. Press one to see what is in it, and which shelf "
      + "each thing is on.",
      button("Back to the floor plan", "quiet small",
             () => { where = "plan"; showWorkspace(); },
             "Stop looking inside this room")));
    return;
  }

  drawPlanTools(strips);
}

function drawPlanTools(strips) {
  const tools = el("div", "chips");
  put(tools, el("span", "strip-label", "Tool"));
  const tool = (name, label, mode, tip, preset = null) =>
    toolButton(name, label, {
      on: view.mode === mode && view.preset === preset,
      tooltip: tip,
      onClick: () => view.setMode(mode, preset),
    });

  put(tools,
    tool("select", "Select", F.SELECT,
         "Press a room to pick it. Press it twice to step inside."),
    tool("draw", "Draw room", F.DRAW,
         "Place the corners of a room one at a time"),
    tool("box", "Add container", F.BOX,
         "Drag a rectangle inside a room to make a shelf, drawer or bin"));
  put(tools, el("span", "grow"));
  const fit = toolButton("fit", "Fit", {
    tooltip: "Put everything on this floor back on the screen",
    onClick: () => view.fit(),
  });
  put(tools, fit);
  put(strips, tools);

  const shapes = el("div", "chips");
  put(shapes, el("span", "strip-label", "Or start from a shape"));
  const shapeIcons = { Rectangle: "rectangle", Square: "square", Circle: "circle",
                       Triangle: "triangle", "L-shape": "lshape" };
  for (const [name] of M.ROOM_PRESETS) {
    put(shapes, toolButton(shapeIcons[name] ?? "rectangle", name, {
      on: view.mode === F.SHAPE && view.preset === name,
      tooltip: `Drag out a ${name.toLowerCase()} room, or press once for a `
               + "default sized one",
      onClick: () => view.setMode(F.SHAPE, name),
    }));
  }
  put(strips, shapes);

  // What dragging a selected room does. Only worth showing when there is one.
  if (view.selected instanceof M.Room && !view.focused) {
    const edits = el("div", "chips");
    put(edits, el("span", "strip-label", "Dragging a room"));
    for (const [name, label, mode, tip] of [
      ["step", "Move", F.MOVE, "Drag the room around the floor"],
      ["fit", "Resize", F.RESIZE,
       "Square handles round the outside. Dragging one stretches the whole "
       + "room and keeps its shape."],
      ["draw", "Reshape", F.VERTICES,
       "A round handle on every corner. Drag one to move that corner."],
    ]) {
      put(edits, toolButton(name, label, {
        on: view.editMode === mode, tooltip: tip,
        onClick: () => { view.setEditMode(mode); drawStrips(); },
      }));
    }
    put(strips, edits);
  }

  put(strips, hintStrip(...hintFor()));
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
            + "inside and work on what is in it."];
  }

  return [profile.floors.length && floor?.rooms.length
    ? "Press a room to select it. Press it twice to step inside. Two fingers, "
      + "or the wheel, move the camera."
    : "Nothing on this floor yet. Pick a shape above and drag it out, or use "
      + "Draw room to place the corners yourself."];
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

  const stepIn = button("", "small", () => view.stepInto(chosen),
                        "Work on what is in this room");
  put(stepIn, icon("step"), el("span", null, "Step inside"));
  const three = button("", "primary small", () => {
    room = chosen;
    where = "room";
    showWorkspace();
  }, "See this room in 3D");
  put(three, icon("three"), el("span", null, "3D view"));
  put(panel, put(el("div", "row"), stepIn, three));

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
showLauncher();

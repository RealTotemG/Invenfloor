/**
 * app.js
 * ======
 *
 * The shell: what is on screen, and what happens when you press things.
 *
 * Two screens. The launcher lists the profiles saved in this browser and
 * handles the passphrase and the import and export of files. Opening one gets
 * you the workspace: a floor plan you can draw rooms on, or the inside of one
 * room in 3D, with an inspector down the side for whatever is selected.
 *
 * WHY THE MARKUP IS BUILT HERE RATHER THAN SITTING IN THE HTML
 * ------------------------------------------------------------
 * One place decides what is on the page. The alternative, a page full of
 * hidden sections that get shown and hidden, means the current screen is
 * described in two places at once, and the day they disagree is the day you
 * get a launcher with half a floor plan behind it.
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

T.apply();

const root = document.getElementById("app");

// ---------------------------------------------------------------------------
// MAKING ELEMENTS
// ---------------------------------------------------------------------------
// Small enough to read in one go, and it means nothing in this file builds
// HTML out of strings. Not only for safety: a profile named with a < in it
// should show a < rather than eating the rest of the page.

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, className, onClick) {
  const node = el("button", className, label);
  node.addEventListener("click", onClick);
  return node;
}

function put(parent, ...children) {
  for (const child of children) if (child) parent.append(child);
  return parent;
}

function clear(node) {
  while (node.firstChild) node.firstChild.remove();
}

function swatch(color) {
  const dot = el("span", "swatch");
  dot.style.background = color;
  return dot;
}

function field(value, onDone, { type = "text", placeholder = "" } = {}) {
  const node = el("input");
  node.type = type;
  node.value = value;
  node.placeholder = placeholder;
  const commit = () => onDone(node.value);
  node.addEventListener("change", commit);
  node.addEventListener("keydown", event => {
    if (event.key === "Enter") { node.blur(); }
  });
  return node;
}

const when = milliseconds =>
  milliseconds ? new Date(milliseconds).toLocaleString() : "never";

// ---------------------------------------------------------------------------
// STATE
// ---------------------------------------------------------------------------

let store = null;
let profile = null;        // the open profile, or null while in the launcher
let floor = null;
let room = null;           // the room the 3D view is showing
let inside = false;        // is the 3D view up, rather than the floor plan
let view = null;           // whichever canvas is up
let history = null;
let saveTimer = null;
let saveTrouble = "";

// Is the open profile one of the saved ones? False for the made-up house and
// for a file opened when there is nowhere to put it. Changes to those are
// real, they just do not get written, and the bar has to say so rather than
// letting somebody spend twenty minutes on something that evaporates.
let kept = false;

/** Something changed. Record it, and write it in a moment.
 *
 *  Half a second, so a drag that fires fifty times writes once. The trailing
 *  edge rather than the leading one: what wants saving is where the room ended
 *  up, not where it was when it started moving.
 */
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
      // Nowhere to put it, so open it anyway rather than refusing. Working in
      // a profile is useful even when nothing can be kept.
      openProfile(S.readExport(text), false);
    } catch (error) {
      says.textContent = error.message ?? String(error);
      says.className = "note bad";
    }
  });

  return put(el("div"), put(row, picker), says);
}

function notice(text, bad = false) {
  return el("p", bad ? "notice bad" : "notice", text);
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
  inside = false;
  history = new History(found);
  saveTrouble = "";
  showWorkspace();
}

let parts = null;          // the pieces of the workspace, for partial redraws

function showWorkspace() {
  if (view) { view.stop(); view = null; }

  const bar = el("header", "bar");
  const workspace = el("div", "workspace");
  const strips = el("div", "strips");
  const split = el("div", "split");
  const stage = el("div", "stage");
  const canvas = el("canvas");
  const panel = el("aside", "panel");

  put(stage, canvas);
  put(split, stage, panel);
  put(workspace, strips, split);
  clear(root);
  put(root, bar, workspace);

  parts = { bar, strips, panel, stage };

  if (inside && room) {
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
    });
    view.show(profile, floor);
  }

  refreshBar();
  drawStrips();
  drawPanel();
}

function refreshBar() {
  if (!parts) return;
  const bar = parts.bar;
  clear(bar);
  put(bar,
    button("‹ Profiles", "quiet small", () => { saveNow(); showLauncher(); }),
    put(el("div", "grow"),
        put(el("div", "row tight"), swatch(profile.color),
            el("strong", "truncate", profile.name)),
        el("div", "where truncate", inside && room
          ? `${floor.name} / ${room.name} · inside`
          : (floor ? floor.name : "no floors"))),
    button("↶", "quiet small icon", () => step("undo")),
    button("↷", "quiet small icon", () => step("redo")),
    kept ? null : button("Keep", "primary small", async () => {
      if (!store || store.locked) return;
      await store.save(profile);
      kept = true;
      refreshBar();
      drawStrips();
    }),
    button("Download", "quiet small", () => S.download(profile)));

  const undo = bar.querySelector("button.icon");
  if (undo) undo.disabled = !history?.canUndo;
  const redo = bar.querySelectorAll("button.icon")[1];
  if (redo) redo.disabled = !history?.canRedo;

}

function step(which) {
  const back = which === "undo" ? history?.undo() : history?.redo();
  if (!back) return;
  profile = back;
  // The old Floor and Room objects belong to the profile that was just
  // replaced, so anything holding one is holding a ghost. Find the same ids in
  // the new one, and fall back to the first if whatever was open is gone.
  floor = profile.floors.find(each => each.id === floor?.id) ?? profile.floors[0] ?? null;
  room = floor?.rooms.find(each => each.id === room?.id) ?? null;
  if (!room) inside = false;
  touched({ step: false });
  showWorkspace();
}

/** The toolbars: floors, then whatever the current canvas needs. */
function drawStrips() {
  if (!parts) return;
  const strips = parts.strips;
  clear(strips);

  // The warning belongs here rather than in refreshBar, which runs on every
  // change: prepending it there added another copy of the same line every
  // time anything moved.
  if (!kept) {
    put(strips, put(el("div", "chips"),
      el("span", "small warn", store && !store.locked
        ? "Not saved. Changes stay until this tab closes, unless you press Keep."
        : "Not saved, and there is nowhere to save it. Download it to keep it.")));
  }

  const floors = el("div", "chips");
  for (const each of profile.floors) {
    put(floors, button(M.short(each.name, 20),
      `small${each === floor ? " on" : ""}`, () => {
        floor = each;
        room = null;
        inside = false;
        showWorkspace();
      }));
  }
  put(floors, button("+ Floor", "quiet small", () => {
    const made = new M.Floor({
      name: `Floor ${profile.floors.length + 1}`,
      color: T.SWATCHES[profile.floors.length % T.SWATCHES.length],
    });
    profile.floors.push(made);
    floor = made;
    room = null;
    inside = false;
    touched();
    showWorkspace();
  }));
  put(strips, floors);

  if (inside) {
    const tools = el("div", "chips");
    put(tools, button("‹ Floor plan", "small", () => {
      inside = false;
      showWorkspace();
    }));
    put(tools, el("span", "small faint",
      "Drag a container to move it. It slides along a wall rather than "
      + "leaving the room."));
    put(strips, tools);
    return;
  }

  // Tools.
  const tools = el("div", "chips");
  const tool = (label, mode, preset = null) =>
    button(label, `small${view.mode === mode
      && view.preset === preset ? " on" : ""}`, () => view.setMode(mode, preset));

  put(tools, tool("Select", F.SELECT), tool("Draw room", F.DRAW));
  for (const [name] of M.ROOM_PRESETS) put(tools, tool(name, F.SHAPE, name));
  put(tools, tool("Add container", F.BOX));
  put(tools, el("span", "grow"));
  put(tools, button("Fit", "quiet small", () => view.fit()));
  put(strips, tools);

  // What dragging a selected room does. Only worth showing when there is one.
  if (view.selected instanceof M.Room && !view.focused) {
    const edits = el("div", "chips");
    put(edits, el("span", "small faint", "Dragging a room:"));
    for (const [label, mode] of
         [["Move", F.MOVE], ["Resize", F.RESIZE], ["Shape", F.VERTICES]]) {
      put(edits, button(label, `small${view.editMode === mode ? " on" : ""}`,
        () => { view.setEditMode(mode); drawStrips(); }));
    }
    if (view.editMode === F.VERTICES) {
      put(edits, el("span", "small faint",
        "Press inside to add a corner, press a corner twice to remove it."));
    }
    put(strips, edits);
  }

  if (view.mode === F.DRAW) {
    const hint = el("div", "chips");
    put(hint, el("span", "small faint",
      "Press to place each corner. Press the first one again, or Enter, to "
      + "close it. Escape gives up."));
    put(strips, hint);
  }
}

// ---------------------------------------------------------------------------
// THE INSPECTOR
// ---------------------------------------------------------------------------

function drawPanel() {
  if (!parts) return;
  const panel = parts.panel;
  clear(panel);

  if (saveTrouble) put(panel, notice("That did not save. " + saveTrouble, true));

  const chosen = view?.selected ?? null;
  if (chosen instanceof M.Room) return roomPanel(panel, chosen);
  if (chosen instanceof M.Container) return containerPanel(panel, chosen);
  return emptyPanel(panel);
}

function emptyPanel(panel) {
  if (inside) {
    put(panel, el("p", "note",
      "Press a container to see what is in it."));
  } else if (!floor?.rooms.length) {
    put(panel, el("p", "note",
      "Nothing on this floor yet. Pick a shape above and drag it out, or use "
      + "Draw room to place the corners yourself."));
  } else {
    put(panel, el("p", "note",
      "Press a room to select it. Press it twice to step inside and work on "
      + "what is in it."));
  }
  const loose = profile.items.filter(item => item.isUnfiled()).length;
  if (loose) {
    put(panel, el("p", "note",
      `${loose} item${loose === 1 ? " is" : "s are"} not in any container. `
      + "The screen for those is not built yet."));
  }
}

/** Name, color and a row of buttons, which every kind of thing wants. */
function header(panel, thing, { onRename, onRecolor, onDelete, onDuplicate }) {
  put(panel, put(el("div", "row"),
    field(thing.name, value => { onRename(M.cleanName(value)); })));

  const dots = el("div", "dots");
  for (const color of T.SWATCHES) {
    const dot = button("", color === thing.color ? "on" : "", () => onRecolor(color));
    dot.style.background = color;
    dot.title = color;
    put(dots, dot);
  }
  put(panel, dots);

  put(panel, put(el("div", "row"),
    onDuplicate ? button("Duplicate", "quiet small", onDuplicate) : null,
    onDelete ? button("Delete", "quiet small danger", onDelete) : null));
}

function numberRow(label, value, onDone, step = T.GRID_SIZE) {
  const box = el("input");
  box.type = "number";
  box.value = Math.round(value);
  box.step = step;
  box.addEventListener("change", () => {
    const asked = Number(box.value);
    if (Number.isFinite(asked)) onDone(asked);
  });
  return put(el("label", "field"), el("span", "small faint", label), box);
}

function roomPanel(panel, chosen) {
  put(panel, el("h3", null, "Room"));
  header(panel, chosen, {
    onRename: name => { chosen.name = name; touched(); view.draw(); drawPanel(); },
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
        chosen.containers.length} container(s)?`)) return;
      floor.rooms = floor.rooms.filter(each => each !== chosen);
      touched();
      view.select(null);
      view.draw();
      drawStrips();
    },
  });

  const [, , wide, high] = chosen.bounds();
  put(panel, put(el("div", "row"),
    numberRow("Width", wide, value => {
      chosen.resizeTo(Math.max(value, T.GRID_SIZE), high, 0, 0);
      for (const box of chosen.containers) M.fitContainer(chosen, box);
      touched(); view.draw(); drawPanel();
    }),
    numberRow("Depth", high, value => {
      chosen.resizeTo(wide, Math.max(value, T.GRID_SIZE), 0, 0);
      for (const box of chosen.containers) M.fitContainer(chosen, box);
      touched(); view.draw(); drawPanel();
    })));

  const lock = el("label", "check");
  const tick = el("input");
  tick.type = "checkbox";
  tick.checked = chosen.locked;
  tick.addEventListener("change", () => {
    chosen.locked = tick.checked;
    touched();
    view.draw();
  });
  put(lock, tick, el("span", "small", "Locked, so it cannot be moved by accident"));
  put(panel, lock);

  put(panel, put(el("div", "row"),
    button("Step inside", "small", () => view.stepInto(chosen)),
    button("3D view", "primary small", () => {
      room = chosen;
      inside = true;
      showWorkspace();
    })));

  put(panel, el("p", "note small",
    `${chosen.points.length} corners, ${chosen.containers.length} container${
      chosen.containers.length === 1 ? "" : "s"}`));
}

function containerPanel(panel, chosen) {
  const holder = inside ? room : view.roomOf(chosen);
  put(panel, el("h3", null, "Container"));
  header(panel, chosen, {
    onRename: name => { chosen.name = name; touched(); view.draw(); drawPanel(); },
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
      holder.containers = holder.containers.filter(each => each !== chosen);
      // The items that were in it are not deleted with it. They become
      // unfiled, which is what the desktop app does and what anybody would
      // expect: taking a shelf out of a room does not mean throwing away
      // what was on it.
      for (const item of profile.items) {
        item.placements = item.placements.filter(
          place => place.containerId !== chosen.id);
      }
      touched();
      view.select(null);
      view.draw();
    } : null,
  });

  put(panel, put(el("div", "row"),
    numberRow("Width", chosen.w, value => {
      resizeContainer(holder, chosen, Math.max(value, M.MIN_CONTAINER_SIZE), chosen.h);
    }),
    numberRow("Depth", chosen.h, value => {
      resizeContainer(holder, chosen, chosen.w, Math.max(value, M.MIN_CONTAINER_SIZE));
    })));

  const heights = el("select");
  for (const [name, value] of M.CONTAINER_HEIGHTS) {
    const option = el("option", null, name);
    option.value = String(value);
    option.selected = M.nearestHeight(chosen.height) === value;
    put(heights, option);
  }
  heights.addEventListener("change", () => {
    chosen.height = M.clampHeight(Number(heights.value));
    touched();
    view.draw();
  });
  put(panel, put(el("label", "field"), el("span", "small faint", "Height"), heights));

  const tiers = el("input");
  tiers.type = "number";
  tiers.min = 0;
  tiers.max = 20;
  tiers.value = chosen.tierCount;
  tiers.addEventListener("change", () => {
    chosen.tierCount = Math.max(0, Math.min(20, Math.round(Number(tiers.value) || 0)));
    touched();
    view.draw();
    drawPanel();
  });
  put(panel, put(el("label", "field"),
    el("span", "small faint", "Tiers, for a shelf with separate levels"), tiers));

  itemsSection(panel, chosen);
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

function itemsSection(panel, container) {
  const found = [];
  for (const item of profile.items) {
    for (const place of item.placements) {
      if (place.containerId === container.id) found.push([item, place]);
    }
  }

  put(panel, el("h3", null, found.length ? "Inside" : "Empty"));
  const list = el("div", "items");
  for (const [item, place] of found) {
    const row = el("div", "item");
    put(row, swatch(item.color), el("span", "grow truncate", item.name));
    put(row, el("span", "qty", `${place.quantity}`));
    put(row, button("−", "quiet small", () => {
      place.quantity = Math.max(0, place.quantity - 1);
      if (!place.quantity) {
        // Out of this container, not out of the catalog. Emptying a shelf is
        // not the same as saying you no longer own the thing.
        item.placements = item.placements.filter(each => each !== place);
        item.updatedAt = M.nowStamp();
      }
      touched(); view.draw(); drawPanel();
    }));
    put(row, button("+", "quiet small", () => {
      place.quantity += 1;
      touched(); view.draw(); drawPanel();
    }));
    put(list, row);
  }
  put(panel, list);

  const box = el("input");
  box.type = "text";
  box.placeholder = "add an item";
  const add = () => {
    const name = M.cleanName(box.value, "");
    if (!name) return;
    profile.items.push(new M.Item({
      name,
      color: T.SWATCHES[profile.items.length % T.SWATCHES.length],
      placements: [new M.Placement(container.id, 1, 0)],
    }));
    box.value = "";
    touched(); view.draw(); drawPanel();
  };
  box.addEventListener("keydown", event => {
    if (event.key === "Enter") add();
  });
  const adder = put(el("div", "row"), box, button("Add", "small", add));
  adder.style.marginTop = "var(--space-sm)";
  put(panel, adder);
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

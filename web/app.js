/**
 * app.js
 * ======
 *
 * The shell: what is on screen, and what happens when you press things.
 *
 * Two screens. The launcher lists the profiles saved in this browser and
 * handles the passphrase and the import and export of files. Opening one gets
 * you the workspace: a floor, a room, the room drawn in 3D, and a panel for
 * whichever container is selected.
 *
 * There is no floor plan canvas yet, so nothing here can draw a new room. A
 * profile arrives by being exported from the desktop app and imported below,
 * which is enough to use the thing and is not enough to ship it. That is the
 * next piece.
 *
 * WHY THE MARKUP IS BUILT HERE RATHER THAN SITTING IN THE HTML
 * ------------------------------------------------------------
 * One place decides what is on the page. The alternative, a page full of
 * hidden sections that get shown and hidden, means the current screen is
 * described in two places at once, and the day they disagree is the day you
 * get a launcher with half a room view behind it.
 *
 * WHAT SAVING LOOKS LIKE
 * ----------------------
 * Every change calls touched(), which waits half a second and then writes. A
 * drag is dozens of changes and one save. The delay is the same one
 * storage.py assumes when it explains why snapshots are per day rather than
 * per save.
 */
import * as M from "./model.js";
import * as S from "./storage.js";
import * as T from "./theme.js";
import { RoomView } from "./room.js";
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

function swatch(color) {
  const dot = el("span", "swatch");
  dot.style.background = color;
  return dot;
}

const when = milliseconds =>
  milliseconds ? new Date(milliseconds).toLocaleString() : "never";

// ---------------------------------------------------------------------------
// STATE
// ---------------------------------------------------------------------------

let store = null;
let profile = null;        // the open profile, or null while in the launcher
let floor = null;
let room = null;
let view = null;           // the RoomView, while the workspace is up
let saveTimer = null;
let saveTrouble = "";

// Is the open profile one of the saved ones? False for the made-up house and
// for a file opened when there is nowhere to put it. Changes to those are
// real, they just do not get written, and the bar has to say so rather than
// letting somebody spend twenty minutes on something that evaporates.
let kept = false;

/** Something changed. Write it, in a moment.
 *
 *  Half a second, so a drag that fires fifty times writes once. The trailing
 *  edge rather than the leading one: what wants saving is where the container
 *  ended up, not where it was when it started moving.
 */
function touched() {
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
    // fails is how somebody loses an afternoon: everything looks normal
    // until the tab is closed.
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
  if (view) { view.stop(); view = null; }

  const screen = el("div", "screen");
  const page = put(el("div", "pad"), el("div", "limit"));
  const inner = page.firstChild;

  const bar = put(el("header", "bar"), el("h1", null, "Invenfloor"));
  put(bar, el("span", "grow"));
  put(bar, el("span", "where small", "in this browser"));

  clear(root);
  put(root, bar, put(screen, page));

  if (!store) {
    put(inner, notice("This browser will not save anything. Private browsing, "
                      + "or site data switched off. You can still open a file "
                      + "below and look at it, but nothing will be kept.", true));
    put(inner, importRow());
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
  if (!listed.profiles.length) {
    put(inner, el("p", "note",
      "Nothing here yet. There is no way to draw a floor plan in the browser "
      + "so far, so a profile starts life in the desktop app: export it there "
      + "and open the file here."));
  }

  const tiles = el("div", "tiles");
  for (const found of listed.profiles) {
    const rooms = [...found.allRooms()].length;
    const containers = [...found.allContainers()].length;

    // The tile is a div holding two separate clickable things, not one button
    // with more buttons inside it. Nesting them is invalid, and the click on
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

  put(inner, el("h2", null, "Open a file"));
  put(inner, el("p", "note",
    "A profile exported from the desktop app, or from here. It is read in "
    + "this page and never uploaded anywhere."));
  put(inner, importRow());

  put(inner, el("h2", null, "Or have a look without one"));
  put(inner, el("p", "note",
    "A made-up house, kept only while this tab is open. Nothing is saved "
    + "unless you download it or press Keep."));
  put(inner, put(el("div", "row"),
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
        const saved = await store.importProfile(text);
        openProfile(saved);
        return;
      }
      // No store to put it in, so open it anyway rather than refusing.
      // Looking at a profile is useful even when nothing can be kept.
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
    const field = el("input");
    field.type = "password";
    field.placeholder = "a passphrase, to encrypt everything saved here";
    put(card, put(el("div", "row"), field,
      button("Lock this browser", "small", async () => {
        if (!field.value) { says.textContent = "It needs a passphrase."; return; }
        says.textContent = "Encrypting everything already saved…";
        try {
          const code = await store.addLock(field.value);
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
    const field = el("input");
    field.type = "password";
    field.placeholder = "passphrase, or a recovery code";
    const unlock = async () => {
      says.textContent = "Unlocking…";
      says.className = "note";
      try {
        const used = await store.unlock(field.value);
        if (used === "recovery") {
          says.textContent = "Open, using the recovery code.";
        }
        showLauncher();
      } catch (error) {
        says.textContent = error.message ?? String(error);
        says.className = "note bad";
      }
    };
    field.addEventListener("keydown", event => {
      if (event.key === "Enter") unlock();
    });
    put(card, put(el("div", "row"), field,
      button("Unlock", "primary small", unlock)), says);
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
  room = floor?.rooms[0] ?? null;
  saveTrouble = "";
  showWorkspace();
}

function showWorkspace() {
  const keep = view;                 // reused below if the room has not changed
  const bar = el("header", "bar");
  put(bar,
    button("‹ Profiles", "quiet small", () => { saveNow(); showLauncher(); }),
    put(el("div", "grow"),
        put(el("div", "row tight"), swatch(profile.color),
            el("strong", "truncate", profile.name)),
        el("div", "where truncate",
           room ? `${floor.name} / ${room.name}` : "nothing to show")),
    kept ? null : button("Keep", "primary small", async () => {
      if (!store || store.locked) return;
      await store.save(profile);
      kept = true;
      showWorkspace();
    }),
    button("Download", "quiet small", () => S.download(profile)));

  const workspace = el("div", "workspace");

  if (!kept) {
    const warning = el("div", "chips");
    put(warning, el("span", "small warn", store && !store.locked
      ? "Not saved. Changes stay until this tab closes, unless you press Keep."
      : "Not saved, and there is nowhere to save it. Download it to keep it."));
    put(workspace, warning);
  }

  // Floors, then the rooms on the chosen floor. One scrolling strip rather
  // than a sidebar, because a sidebar on a phone is most of the phone.
  if (profile.floors.length > 1) {
    const strip = el("div", "chips");
    for (const each of profile.floors) {
      put(strip, button(M.short(each.name, 22),
        `small${each === floor ? " on" : ""}`, () => {
          floor = each;
          room = each.rooms[0] ?? null;
          showWorkspace();
        }));
    }
    put(workspace, strip);
  }

  if (floor && floor.rooms.length) {
    const strip = el("div", "chips");
    for (const each of floor.rooms) {
      put(strip, button(M.short(each.name, 22),
        `small${each === room ? " on" : ""}`, () => {
          room = each;
          showWorkspace();
        }));
    }
    put(workspace, strip);
  }

  const split = el("div", "split");
  const stage = el("div", "stage");
  const canvas = el("canvas");
  put(stage, canvas);

  if (!room) {
    put(stage, el("div", "empty",
      "This profile has no rooms yet. The browser cannot draw a floor plan "
      + "so far, so rooms come from the desktop app."));
  }

  const panel = el("aside", "panel");
  put(split, stage, panel);
  put(workspace, split);

  clear(root);
  put(root, bar, workspace);

  if (keep) keep.stop();
  view = new RoomView(canvas, {
    onChanged: touched,
    onSelected: () => drawPanel(panel),
  });
  view.show(profile, room);
  drawPanel(panel);
}

/** The panel for whichever container is selected. */
function drawPanel(panel) {
  clear(panel);

  if (saveTrouble) {
    put(panel, notice("That did not save. " + saveTrouble, true));
  }

  const container = view?.selected;
  if (!container) {
    put(panel, el("p", "note",
      room ? "Tap a container to see what is in it. Drag one to move it; it "
             + "will slide along a wall rather than leave the room."
           : "Nothing to show."));
    const loose = profile.items.filter(item => item.isUnfiled()).length;
    if (loose) {
      put(panel, el("p", "note",
        `${loose} item${loose === 1 ? " is" : "s are"} not in any container. `
        + "The screen for those is not built yet."));
    }
    return;
  }

  put(panel, put(el("h3"), swatch(container.color),
                 document.createTextNode(" " + container.name)));
  put(panel, el("p", "note small",
    `${M.heightName(container.height)}, ${Math.round(container.w)} by `
    + `${Math.round(container.h)}${container.tierCount > 1
        ? `, ${container.tierCount} tiers` : ""}`));

  // Color, the one property worth changing from here. Size and height belong
  // with a proper inspector, and a proper inspector belongs with the floor
  // plan canvas rather than bolted on to this.
  const dots = el("div", "dots");
  for (const color of T.SWATCHES) {
    const dot = button("", color === container.color ? "on" : "", () => {
      container.color = color;
      touched();
      view.draw();
      drawPanel(panel);
    });
    dot.style.background = color;
    dot.title = color;
    put(dots, dot);
  }
  put(panel, dots);

  const inside = view.itemsIn(container);
  put(panel, el("h3", null, inside.length ? "Inside" : "Empty"));

  const list = el("div", "items");
  for (const [item, placement] of inside) {
    const row = el("div", "item");
    put(row, swatch(item.color), el("span", "grow truncate", item.name));
    put(row, el("span", "qty", `${placement.quantity}`));
    put(row, button("−", "quiet small", () => {
      placement.quantity = Math.max(0, placement.quantity - 1);
      if (!placement.quantity) removePlacement(item, placement);
      touched();
      view.draw();
      drawPanel(panel);
    }));
    put(row, button("+", "quiet small", () => {
      placement.quantity += 1;
      touched();
      view.draw();
      drawPanel(panel);
    }));
    put(list, row);
  }
  put(panel, list);

  const field = el("input");
  field.type = "text";
  field.placeholder = "add an item";
  const add = () => {
    const name = M.cleanName(field.value, "");
    if (!name) return;
    profile.items.push(new M.Item({
      name,
      color: T.SWATCHES[profile.items.length % T.SWATCHES.length],
      placements: [new M.Placement(container.id, 1, 0)],
    }));
    field.value = "";
    touched();
    view.draw();
    drawPanel(panel);
  };
  field.addEventListener("keydown", event => {
    if (event.key === "Enter") add();
  });
  const adder = put(el("div", "row"), field, button("Add", "small", add));
  adder.style.marginTop = "var(--space-sm)";
  put(panel, adder);
}

/** Take an item out of one container. The item itself stays in the catalog.
 *
 *  Deleting the item would be the wrong call: emptying a shelf is not the
 *  same as saying you no longer own the thing, and the desktop app keeps
 *  those as unfiled for exactly that reason.
 */
function removePlacement(item, placement) {
  item.placements = item.placements.filter(each => each !== placement);
  item.updatedAt = M.nowStamp();
}

function clear(node) {
  while (node.firstChild) node.firstChild.remove();
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

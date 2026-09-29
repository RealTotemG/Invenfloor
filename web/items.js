/**
 * items.js
 * ========
 *
 * The items screen, and the contents panel a container shows on the floor
 * plan. Both are about the same question, so they live together: what is in
 * here, how many, and which shelf is it on.
 *
 * TIERS
 * -----
 * A container can be divided into tiers, and a pile of something sits either
 * on one of them or loose in the container itself. That is tier 0, and it is
 * not a missing value: a bin with no shelves has everything loose in it, and
 * so does the floor of a cupboard with three shelves above it.
 *
 * Tiers are not named or colored, on purpose. A shelf's levels do not have
 * names, they have positions, and "Tier 2" already says everything there is
 * to say about one.
 *
 * ONE ROW PER PILE, NOT PER ITEM
 * ------------------------------
 * Four sockets on tier 1 and two on tier 3 are two rows, because they are two
 * piles in two places and merging them into "6 sockets" hides the thing the
 * shelf was divided up for. The items screen shows the same item once with
 * its places underneath, because there the question is "what do I own".
 */
import * as M from "./model.js";
import * as T from "./theme.js";
import {
  el, put, clear, button, swatch, field, numberField, choose, colors, icon,
} from "./ui.js";
import { makeTag, tagChip, tagFilterRow, tagManager, tagRow } from "./tags.js";

/** Something with a caption over it. */
function labelled(caption, control) {
  return put(el("label", "field"), el("span", "small faint", caption), control);
}

/** "Loose", "Tier 1", "Tier 2"... what a tier is called on screen. */
export function tierName(tier) {
  return tier ? `Tier ${tier}` : "Loose";
}

/** The choices for a tier picker on a container. */
function tierChoices(container) {
  return [[0, "Loose"], ...container.tiers().map(level => [level, `Tier ${level}`])];
}

// ---------------------------------------------------------------------------
// WHAT IS IN A CONTAINER
// ---------------------------------------------------------------------------

/**
 * The contents of one container, grouped by tier, with a way to move a pile
 * between tiers and a box to add something.
 *
 * @param panel      where to draw
 * @param profile    the open profile
 * @param container  the container being looked at
 * @param changed()  called after anything is edited
 * @param again()    called when the panel needs rebuilding
 */
export function contentsPanel(panel, profile, container, { changed, again }) {
  const piles = profile.contentsOf(container.id);

  put(panel, put(el("div", "row between"),
    el("h3", null, piles.length ? "Inside" : "Empty"),
    el("span", "small faint", piles.length
      ? `${profile.itemCountInContainer(container.id)} thing${
          profile.itemCountInContainer(container.id) === 1 ? "" : "s"}`
      : "")));

  if (container.tierCount > 0) {
    // Grouped under headings, tier by tier, because the point of dividing a
    // shelf up is knowing which level a thing is on, and a flat list with the
    // tier written on each row makes you read every row to find that out.
    for (const tier of [0, ...container.tiers()]) {
      const onThisTier = piles.filter(([, , at]) => at === tier);
      const heading = put(el("div", "tier-head"),
        el("span", "small", tierName(tier)),
        el("span", "small faint", onThisTier.length
          ? `${onThisTier.reduce((sum, [, q]) => sum + q, 0)}` : "empty"));
      put(panel, heading);
      put(panel, pileList(profile, container, onThisTier, { changed, again }));
    }
  } else {
    put(panel, pileList(profile, container, piles, { changed, again }));
  }

  put(panel, adder(profile, container, { changed, again }));
  put(panel, tierControls(profile, container, { changed, again }));
}

function pileList(profile, container, piles, { changed, again }) {
  const list = el("div", "items");
  if (!piles.length) return list;

  for (const [item, quantity, tier] of piles) {
    const row = el("div", "item");
    put(row, swatch(item.color), el("span", "grow truncate name", item.name));

    if (item.isLow()) {
      const flag = el("span", "small warn", "low");
      flag.title = `Below the ${item.minQuantity} you want to keep`;
      put(row, flag);
    }

    put(row, button("−", "quiet small", () => {
      profile.setPlacement(item, container.id, quantity - 1, tier);
      item.touch();
      changed();
      again();
    }, quantity <= 1 ? "Take the last one out of here" : "One fewer"));
    put(row, el("span", "qty", String(quantity)));
    put(row, button("+", "quiet small", () => {
      profile.setPlacement(item, container.id, quantity + 1, tier);
      item.touch();
      changed();
      again();
    }, "One more"));

    if (container.tierCount > 0) {
      const picker = choose(null, tierChoices(container), tier, value => {
        profile.moveToTier(item, container.id, tier, Number(value), quantity);
        changed();
        again();
      });
      picker.classList.add("tier-pick");
      picker.title = "Which tier these are on";
      put(row, picker);
    }
    put(list, row);
  }
  return list;
}

function adder(profile, container, { changed, again }) {
  const name = el("input");
  name.type = "text";
  name.placeholder = "add an item";
  name.className = "grow";

  let tier = 0;
  const row = put(el("div", "row"), name);
  if (container.tierCount > 0) {
    const picker = choose(null, tierChoices(container), 0, value => {
      tier = Number(value);
    });
    picker.classList.add("tier-pick");
    picker.title = "Which tier to put it on";
    put(row, picker);
  }

  const add = () => {
    const cleaned = M.cleanName(name.value, "");
    if (!cleaned) return;

    // An item with this name already in the catalog gets another placement
    // rather than a second entry. Two rows both called "Motor oil" is how a
    // catalog stops being worth having.
    const already = profile.items.find(
      item => item.name.toLowerCase() === cleaned.toLowerCase());
    if (already) {
      const here = already.placementIn(container.id, tier);
      profile.setPlacement(already, container.id, (here?.quantity ?? 0) + 1, tier);
      already.touch();
    } else {
      const made = new M.Item({
        name: cleaned,
        color: T.SWATCHES[profile.items.length % T.SWATCHES.length],
      });
      profile.setPlacement(made, container.id, 1, tier);
      profile.items.push(made);
    }
    name.value = "";
    changed();
    again();
  };

  name.addEventListener("keydown", event => {
    if (event.key === "Enter") add();
  });
  put(row, button("Add", "small", add, "Put one of these in this container"));
  row.style.marginTop = "var(--space-sm)";
  return row;
}

function tierControls(profile, container, { changed, again }) {
  const box = el("div", "tier-controls");
  put(box, el("p", "note small", container.tierCount
    ? `${container.tierCount} tier${container.tierCount === 1 ? "" : "s"}. `
      + "Things can sit on a tier, or loose in the container itself."
    : "No tiers. Add some for a shelf or a unit with separate levels."));

  put(box, put(el("div", "row tight"),
    button("Add tier", "quiet small", () => {
      profile.setTierCount(container, container.tierCount + 1);
      changed();
      again();
    }, "Divide this container into one more level"),
    container.tierCount > 0 ? button("Remove tier", "quiet small", () => {
      profile.setTierCount(container, container.tierCount - 1);
      changed();
      again();
    }, "Drop the last tier. Anything on it comes back loose in the container, "
     + "nothing is lost.") : null));
  return box;
}

// ---------------------------------------------------------------------------
// THE ITEMS SCREEN
// ---------------------------------------------------------------------------

/** Everything in the catalog, searchable, with where each thing lives.
 *
 * @param screen    the element to fill
 * @param profile   the open profile
 * @param state     { search, filter, chosenId } kept by the caller so it
 *                  survives a redraw
 */
/** Put an item in the catalog, or add to the pile if the name is taken.
 *
 *  The one rule that makes a catalog worth having: two rows both called
 *  "Motor oil" is how it stops being one. A name already in the catalog gets
 *  another placement rather than a second entry.
 *
 *  `containerId` may be empty, which means the catalog but nowhere yet. That
 *  is a real answer rather than a missing one: writing down what you own
 *  before you have decided where it goes is how most lists actually start.
 */
function putInCatalog(profile, name, containerId, tier) {
  const cleaned = M.cleanName(name, "");
  if (!cleaned) return null;

  let item = profile.items.find(
    each => each.name.toLowerCase() === cleaned.toLowerCase());
  if (!item) {
    item = new M.Item({
      name: cleaned,
      color: T.SWATCHES[profile.items.length % T.SWATCHES.length],
    });
    profile.items.push(item);
  }

  if (containerId) {
    const here = item.placementIn(containerId, tier);
    profile.setPlacement(item, containerId, (here?.quantity ?? 0) + 1, tier);
  }
  item.touch();
  return item;
}


/** Type a name, press Enter, type the next one.
 *
 *  WHY THIS IS WORTH A PANEL OF ITS OWN
 *  ------------------------------------
 *  The thing that kills an inventory app is the first two hundred items. If
 *  each one costs a trip to the floor plan, a container to find and a panel
 *  to open, you stop after twenty and the app becomes a half-finished list
 *  you do not trust. Adding one item was only ever possible from inside a
 *  container, which is the slowest door into the catalog and, until now, the
 *  only one.
 *
 *  So this asks where they go ONCE and then gets out of the way. The box
 *  keeps the cursor after every Enter, the names queue up underneath, and
 *  nothing is written to the catalog until Add is pressed, so a mistyped
 *  line is removed rather than undone.
 */
function bulkAdd(profile, state, { changed, again }) {
  const box = el("div", "card");
  put(box, el("h4", null, "Add items"));
  put(box, el("p", "note",
    "Type a name and press Enter, then the next one. Nothing goes in the "
    + "catalog until you press Add at the bottom."));

  // -- where they all go ---------------------------------------------------
  const everywhere = [...profile.allContainers()];
  // "Nowhere yet" first, because it is the answer for anybody writing down
  // what they own before deciding where it lives, and because it is the only
  // answer available at all until there is a container to choose.
  const places = [["", "Nowhere yet, just the catalog"],
                  ...everywhere.map(([floor, room, container]) =>
                    [container.id, `${container.name} \u2014 ${room.name}, ${floor.name}`])];

  const where = choose("Put them all in", places, state.addTo, value => {
    state.addTo = value;
    state.addTier = 0;
    again();
  });
  put(box, where);

  const holder = state.addTo ? profile.findContainer(state.addTo)?.[2] : null;
  if (holder?.tierCount > 0) {
    put(box, choose("On which tier", tierChoices(holder), state.addTier,
      value => { state.addTier = Number(value); again(); }));
  }

  // -- the queue -----------------------------------------------------------
  const typed = el("input");
  typed.type = "text";
  typed.placeholder = "a name, then Enter";
  typed.className = "grow";
  typed.addEventListener("keydown", event => {
    if (event.key !== "Enter") return;
    const cleaned = M.cleanName(typed.value, "");
    if (!cleaned) return;
    state.queue = [...state.queue, cleaned];
    typed.value = "";
    again();
  });
  put(box, put(el("div", "row"), typed));

  if (state.queue.length) {
    const list = el("div", "tag-row");
    state.queue.forEach((name, at) => {
      const chip = el("span", "tag queued");
      put(chip, el("span", "tag-name", M.short(name, 24)));
      put(chip, button("\u00d7", "tag-x", () => {
        state.queue = state.queue.filter((_, n) => n !== at);
        again();
      }, `Take ${name} off the list`));
      put(list, chip);
    });
    put(box, list);
  }

  const row = el("div", "row");
  const count = state.queue.length;
  const add = button(count ? `Add ${count} item${count === 1 ? "" : "s"}`
                           : "Add", "primary small", () => {
    for (const name of state.queue) {
      putInCatalog(profile, name, state.addTo, state.addTier);
    }
    state.queue = [];
    changed();
    again();
  }, "Put everything on the list into the catalog");
  add.disabled = !count;
  put(row, add);
  put(row, button("Done", "quiet small", () => {
    state.adding = false;
    state.queue = [];
    again();
  }, "Close this"));
  put(box, row);

  return box;
}


/** What to do with everything that is ticked.
 *
 *  Tagging twenty things one at a time means twenty items opened, twenty
 *  dropdowns and twenty closes, and by about the fourth you stop bothering
 *  and the tags stop being worth having. This is that job as one press.
 *
 *  Adding and removing are separate buttons rather than one that toggles,
 *  because a toggle over a mixed selection has no honest meaning: half of
 *  these already carry the tag, so "toggle" would take it off some and put it
 *  on others, and nobody pressing it could predict which.
 */
function pickedBar(profile, state, showing, { changed, again }) {
  const box = el("div", "card picked");
  const chosen = profile.items.filter(item => state.picked.includes(item.id));

  put(box, put(el("div", "row"),
    el("strong", null, `${chosen.length} chosen`),
    el("span", "grow"),
    button("Choose all shown", "quiet small", () => {
      state.picked = [...new Set([...state.picked, ...showing.map(i => i.id)])];
      again();
    }, "Tick everything the list is currently showing"),
    button("Clear", "quiet small", () => { state.picked = []; again(); },
           "Untick everything")));

  if (!profile.tags.length) {
    put(box, put(el("div", "row"),
      el("span", "note small", "No tags yet."),
      button("+ New tag", "primary small", () => {
        const made = makeTag(profile);
        if (!made) return;
        for (const item of chosen) {
          if (!item.tagIds.includes(made.id)) {
            item.tagIds = [...item.tagIds, made.id];
            item.touch();
          }
        }
        changed();
        again();
      }, `Make a tag and put it on all ${chosen.length}`)));
    return box;
  }

  const row = el("div", "tag-row");
  for (const tag of profile.tags) {
    const carrying = chosen.filter(item => item.tagIds.includes(tag.id)).length;

    const chip = tagChip(tag);
    chip.classList.add("tag-button");
    // Says how many of the chosen already carry it, so pressing is an
    // informed decision rather than a guess.
    if (carrying) {
      put(chip, el("span", "small faint", `${carrying}/${chosen.length}`));
    }
    chip.title = carrying === chosen.length
      ? `All of them have ${tag.name}`
      : `Put ${tag.name} on all ${chosen.length}`;
    chip.addEventListener("click", () => {
      for (const item of chosen) {
        if (!item.tagIds.includes(tag.id)) {
          item.tagIds = [...item.tagIds, tag.id];
          item.touch();
        }
      }
      changed();
      again();
    });
    put(row, chip);

    if (carrying) {
      const off = button("\u00d7", "tag-x standalone", () => {
        for (const item of chosen) {
          if (item.tagIds.includes(tag.id)) {
            item.tagIds = item.tagIds.filter(id => id !== tag.id);
            item.touch();
          }
        }
        changed();
        again();
      }, `Take ${tag.name} off all ${chosen.length}`);
      off.style.color = tag.color;
      put(row, off);
    }
  }
  put(box, el("p", "note small", "Press a tag to put it on all of them. The "
    + "cross beside one takes it off all of them."));
  put(box, row);
  return box;
}


export function itemsScreen(screen, profile, state, { changed, again }) {
  clear(screen);

  // Fill in anything the caller's state object is missing.
  //
  // The state is a plain object handed in and kept by whoever called, which
  // is what lets a search survive a redraw. The cost is that every key this
  // screen learns about is a key every caller has to have heard of, and the
  // one that had not was the check bench: adding the tick boxes made this
  // screen read state.picked and the bench's state had no such thing, so the
  // whole suite died on a property of undefined. Defaults here rather than a
  // guard at each use, so the next key added is one edit and not a crash.
  state.search ??= "";
  state.filter ??= "all";
  state.tagId ??= null;
  state.editingTags ??= false;
  state.adding ??= false;
  state.queue ??= [];
  state.addTo ??= "";
  state.addTier ??= 0;
  state.picked ??= [];

  const page = put(el("div", "pad"), el("div", "limit"));
  const inner = page.firstChild;
  put(screen, page);

  // -- what to show -------------------------------------------------------
  const counts = {
    all: profile.items.length,
    unfiled: profile.unfiledItems().length,
    low: profile.lowItems().length,
    misfiled: new Set(profile.misfiledItems().map(([item]) => item.id)).size,
  };

  const search = el("input");
  search.type = "search";
  search.placeholder = "search by name or note";
  search.value = state.search;
  search.className = "grow";
  search.addEventListener("input", () => {
    state.search = search.value;
    again();
    // Redrawing replaces the box, so put the cursor back where it was or
    // typing a second letter goes nowhere.
    const fresh = screen.querySelector("input[type=search]");
    if (fresh) { fresh.focus(); fresh.setSelectionRange(fresh.value.length, fresh.value.length); }
  });
  put(inner, put(el("div", "row"), search));

  const tabs = el("div", "chips");
  for (const [key, label] of [["all", "Everything"], ["unfiled", "Not filed"],
                              ["low", "Running low"], ["misfiled", "In the wrong room"]]) {
    put(tabs, button(`${label}${counts[key] ? ` (${counts[key]})` : ""}`,
      `small${state.filter === key ? " on" : ""}`, () => {
        state.filter = key;
        again();
      }));
  }
  put(inner, tabs);

  // -- tags ---------------------------------------------------------------
  // Under the saved views rather than beside them, because they narrow the
  // same list and a tag is a second question about it rather than a rival
  // one: "things I have not filed" AND "tagged Tools" is a sensible thing to
  // ask, and two rows of buttons that fight over one list is not.
  const tagBar = put(el("div", "row"), tagFilterRow(profile, state, { changed, again }));
  put(tagBar, el("span", "grow"));
  put(tagBar, button(state.adding ? "Done adding" : "Add items",
    state.adding ? "quiet small" : "primary small",
    () => { state.adding = !state.adding; state.queue = []; again(); },
    "Type a list of things straight into the catalog"));
  put(tagBar, button(state.editingTags ? "Done" : "Edit tags", "quiet small",
    () => { state.editingTags = !state.editingTags; again(); },
    "Make tags, rename them, or take one away"));
  put(inner, tagBar);
  if (state.adding) put(inner, bulkAdd(profile, state, { changed, again }));
  if (state.editingTags) put(inner, tagManager(profile, { changed, again }));

  // The cursor goes in the box and stays there.
  //
  // Here rather than further down, because further down is after the early
  // return for an empty catalog, and an empty catalog is exactly when
  // somebody reaches for this. It also has to run on EVERY redraw, not just
  // the first: this screen rebuilds itself wholesale after each Enter, which
  // throws away the box the cursor was in, and without putting it back the
  // second name you type goes nowhere at all.
  if (state.adding) {
    const box = inner.querySelector('input[placeholder="a name, then Enter"]');
    if (box) box.focus();
  }

  // -- the list -----------------------------------------------------------
  const wanted = state.search.trim().toLowerCase();
  const misfiledIds = new Set(profile.misfiledItems().map(([item]) => item.id));
  let showing = profile.items;
  if (state.filter === "unfiled") showing = profile.unfiledItems();
  if (state.filter === "low") showing = profile.lowItems();
  if (state.filter === "misfiled") showing = showing.filter(i => misfiledIds.has(i.id));
  if (state.tagId) showing = showing.filter(i => i.tagIds.includes(state.tagId));
  if (wanted) {
    showing = showing.filter(item =>
      item.name.toLowerCase().includes(wanted)
      || item.notes.toLowerCase().includes(wanted));
  }
  showing = [...showing].sort((a, b) =>
    a.name.toLowerCase().localeCompare(b.name.toLowerCase()));

  if (!profile.items.length) {
    put(inner, el("p", "note", "Nothing in the catalog yet. Add items up "
      + "there types a list straight in, or you can put things in a "
      + "container directly from the floor plan."));
    return;
  }
  if (!showing.length) {
    put(inner, el("p", "note", wanted
      ? `Nothing matching "${state.search.trim()}".`
      : "Nothing here."));
  }

  // Whatever is ticked, and what can be done to all of it at once.
  //
  // Only on screen once something is ticked. A bar of controls that do
  // nothing yet is a bar somebody has to read and dismiss every time they
  // come to this screen looking for one thing.
  if (state.picked.length) {
    put(inner, pickedBar(profile, state, showing, { changed, again }));
  }

  const list = el("div", "rows");
  for (const item of showing) {
    const open = item.id === state.chosenId;
    const row = el("div", `listing${open ? " open" : ""}`);

    // The tick box sits OUTSIDE the row's button rather than inside it.
    // A checkbox inside a button is invalid markup and, more to the point,
    // pressing it would open the item on the way past, which is the opposite
    // of what somebody ticking twenty boxes wants.
    const tick = el("input");
    tick.type = "checkbox";
    tick.className = "pick-one";
    tick.checked = state.picked.includes(item.id);
    tick.title = `Choose ${item.name} for tagging`;
    tick.addEventListener("change", () => {
      state.picked = tick.checked
        ? [...state.picked, item.id]
        : state.picked.filter(id => id !== item.id);
      again();
    });
    put(row, tick);

    const head = button("", "listing-head", () => {
      state.chosenId = open ? null : item.id;
      again();
    });
    put(head,
      swatch(item.color),
      put(el("div", "grow"),
        el("div", "truncate name", item.name),
        el("div", "small faint truncate", profile.locationOf(item))),
      el("span", "qty", String(item.totalQuantity())));
    if (item.isLow()) put(head, el("span", "small warn", "low"));
    // Two at most on the row itself. The point here is recognizing a thing
    // at a glance while scrolling, and a row carrying six chips is wider
    // than the name it belongs to.
    for (const tag of profile.tagsFor(item.tagIds).slice(0, 2)) {
      put(head, tagChip(tag));
    }
    if (item.tagIds.length > 2) {
      put(head, el("span", "note small", `+${item.tagIds.length - 2}`));
    }
    put(row, head);

    if (open) put(row, itemDetail(profile, item, { changed, again }));
    put(list, row);
  }
  put(inner, list);
}

function itemDetail(profile, item, { changed, again }) {
  const box = el("div", "listing-body");

  // Labelled, not just placeheld. A placeholder disappears the moment there
  // is anything in the box, so a filled-in form of bare boxes is a form that
  // has stopped saying what any of it is.
  put(box, labelled("Name", field(item.name, value => {
    item.name = M.cleanName(value);
    item.touch();
    changed();
    again();
  })));

  put(box, labelled("Color", colors(item.color, color => {
    item.color = color;
    item.touch();
    changed();
    again();
  })));

  put(box, labelled("Notes", field(item.notes, value => {
    item.notes = value.slice(0, 500);
    item.touch();
    changed();
  }, { placeholder: "a size, a model number, where you bought it" })));

  put(box, numberField("Tell me when it drops below (0 for never)",
    item.minQuantity, value => {
      item.minQuantity = Math.max(0, Math.round(value));
      item.touch();
      changed();
      again();
    }, { min: 0 }));

  // -- tags ---------------------------------------------------------------
  put(box, el("h4", null, "Tags"));
  put(box, tagRow(profile, item, {
    changed, again,
    onNewTag: () => makeTag(profile),
  }));

  // -- where it is --------------------------------------------------------
  const places = profile.locationsOf(item);
  put(box, el("h4", null, places.length ? "Where it is" : "Not filed anywhere"));

  if (!places.length) {
    put(box, el("p", "note small",
      "This is in the catalog but not in any container. Put it somewhere with "
      + "the box below, or find it on the floor plan."));
  }

  for (const [floor, room, container, quantity, tier] of places) {
    const row = el("div", "item");
    put(row, put(el("div", "grow"),
      el("div", "truncate", container.name),
      el("div", "small faint truncate", `${floor.name} / ${room.name}`)));

    if (container.tierCount > 0) {
      const picker = choose(null, tierChoices(container), tier, value => {
        profile.moveToTier(item, container.id, tier, Number(value), quantity);
        changed();
        again();
      });
      picker.classList.add("tier-pick");
      picker.title = "Which tier these are on";
      put(row, picker);
    }

    const count = el("input");
    count.type = "number";
    count.min = 0;
    count.value = quantity;
    count.className = "qty-box";
    count.title = "How many are here";
    count.addEventListener("change", () => {
      profile.setPlacement(item, container.id, Math.max(0, Math.round(Number(count.value) || 0)), tier);
      item.touch();
      changed();
      again();
    });
    put(row, count);

    put(row, button("", "quiet small icon-only", () => {
      profile.setPlacement(item, container.id, 0, tier);
      item.touch();
      changed();
      again();
    }, `Take these out of ${container.name}`));
    put(row.lastChild, icon("trash"));
    put(box, row);
  }

  // -- put it somewhere ---------------------------------------------------
  const everywhere = [...profile.allContainers()];
  if (everywhere.length) {
    let chosenContainer = everywhere[0][2].id;
    let chosenTier = 0;

    const containerPick = choose(null,
      everywhere.map(([floor, room, container]) =>
        [container.id, `${container.name} — ${room.name}, ${floor.name}`]),
      chosenContainer, value => {
        chosenContainer = value;
        again();
      });
    containerPick.classList.add("grow");

    const holder = profile.findContainer(chosenContainer)[2];
    const row = put(el("div", "row"), containerPick);
    if (holder?.tierCount > 0) {
      const tierPick = choose(null, tierChoices(holder), 0, value => {
        chosenTier = Number(value);
      });
      tierPick.classList.add("tier-pick");
      put(row, tierPick);
    }
    put(row, button("Put here", "small", () => {
      const already = item.placementIn(chosenContainer, chosenTier);
      profile.setPlacement(item, chosenContainer,
                           (already?.quantity ?? 0) + 1, chosenTier);
      item.touch();
      changed();
      again();
    }, "Add one of these to that container"));
    put(box, el("h4", null, "Put one somewhere"), row);
  }

  put(box, put(el("div", "row"),
    button("Delete this item", "quiet small danger", () => {
      if (!confirm(`Delete "${item.name}" from the catalog? This takes it out `
                   + "of every container it is in.")) return;
      profile.items = profile.items.filter(each => each !== item);
      changed();
      again();
    }, "Remove it from the catalog entirely")));

  return box;
}

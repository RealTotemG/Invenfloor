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
export function itemsScreen(screen, profile, state, { changed, again }) {
  clear(screen);

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

  // -- the list -----------------------------------------------------------
  const wanted = state.search.trim().toLowerCase();
  const misfiledIds = new Set(profile.misfiledItems().map(([item]) => item.id));
  let showing = profile.items;
  if (state.filter === "unfiled") showing = profile.unfiledItems();
  if (state.filter === "low") showing = profile.lowItems();
  if (state.filter === "misfiled") showing = showing.filter(i => misfiledIds.has(i.id));
  if (wanted) {
    showing = showing.filter(item =>
      item.name.toLowerCase().includes(wanted)
      || item.notes.toLowerCase().includes(wanted));
  }
  showing = [...showing].sort((a, b) =>
    a.name.toLowerCase().localeCompare(b.name.toLowerCase()));

  if (!profile.items.length) {
    put(inner, el("p", "note", "Nothing in the catalog yet. Items are added "
      + "inside a container, on the floor plan: pick a container and use the "
      + "box at the bottom of the panel."));
    return;
  }
  if (!showing.length) {
    put(inner, el("p", "note", wanted
      ? `Nothing matching "${state.search.trim()}".`
      : "Nothing here."));
  }

  const list = el("div", "rows");
  for (const item of showing) {
    const open = item.id === state.chosenId;
    const row = el("div", `listing${open ? " open" : ""}`);

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

/**
 * items_checks.js
 * ===============
 *
 * The contents panel and the items screen, driven the way a hand drives them:
 * by finding the button and pressing it.
 *
 * Both are functions that fill an element, which makes them unusually easy to
 * ask questions of. Give one a div, press things in it, and look at the
 * profile afterwards. The thing being checked is always the profile, not the
 * markup: what matters is that pressing + put one more sock on tier 3, not
 * that the row has a particular class on it.
 */
import * as M from "./model.js";
import { contentsPanel, itemsScreen, tierName } from "./items.js";

function bench() {
  const holder = document.createElement("div");
  holder.style.cssText = "position:fixed;left:-10000px;top:0;width:400px";
  document.body.append(holder);
  return holder;
}

/** A house with a four-tier shelf, something on two of its tiers, something
 *  loose, something unfiled and something below its par level. */
function madeUp() {
  const profile = new M.Profile({ name: "Checks" });
  const floor = new M.Floor({ id: "f1", name: "Ground" });
  const room = new M.Room({ id: "r1", name: "Garage",
                            points: M.rectanglePoints(400, 300) });
  const shelf = new M.Container({ id: "c1", name: "Racking", x: 20, y: 20,
                                  w: 150, h: 45, height: 100, tierCount: 4 });
  const bin = new M.Container({ id: "c2", name: "Bin", x: 220, y: 200,
                                w: 60, h: 60, height: 30 });
  room.containers = [shelf, bin];
  floor.rooms = [room];
  profile.floors = [floor];

  const item = (id, name, places, minQuantity = 0) => {
    const made = new M.Item({ id, name, minQuantity, color: "#4f7cff" });
    made.placements = places.map(
      ([container, quantity, tier]) => new M.Placement(container, quantity, tier));
    return made;
  };
  profile.items = [
    item("i1", "Motor oil", [["c1", 4, 1]]),
    item("i2", "Zip ties", [["c1", 2, 1], ["c1", 6, 4]]),
    item("i3", "Rags", [["c1", 5, 0]]),
    item("i4", "Screws", [["c2", 1, 0]], 10),
    item("i5", "Beach umbrella", []),
  ];
  return { profile, room, shelf, bin };
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Every button in an element whose text is exactly this. */
const buttonsSaying = (root, text) =>
  [...root.querySelectorAll("button")].filter(
    node => node.textContent.trim() === text);

/** The row for one item, by the name showing in it.
 *
 *  Matched on the element that holds ONLY the name. Both shapes of row have
 *  more than one thing with a truncate class on it, so a looser selector
 *  picks up the location line as well and nothing ever matches.
 */
function rowFor(root, name) {
  return [...root.querySelectorAll(".item, .listing")].find(
    node => node.querySelector(".name")?.textContent.trim() === name);
}

export async function runItemsChecks() {
  const results = [];
  const check = (label, ok, why = "") => results.push({ label, ok, why: String(why) });
  const benches = [];

  const fresh = () => {
    const holder = bench();
    benches.push(holder);
    const world = madeUp();
    let changes = 0;
    const panel = document.createElement("div");
    holder.append(panel);
    const draw = () => {
      while (panel.firstChild) panel.firstChild.remove();
      contentsPanel(panel, world.profile, world.shelf,
                    { changed: () => changes++, again: draw });
    };
    draw();
    return { ...world, panel, draw, changed: () => changes };
  };

  try {
    check("a tier has a name and no tier is Loose",
          tierName(0) === "Loose" && tierName(1) === "Tier 1"
          && tierName(12) === "Tier 12");

    // -- the contents panel -------------------------------------------------
    {
      const it = fresh();
      const headings = [...it.panel.querySelectorAll(".tier-head")]
        .map(node => node.firstChild.textContent);
      check("a shelf with four tiers shows five headings, Loose included",
            same(headings, ["Loose", "Tier 1", "Tier 2", "Tier 3", "Tier 4"]),
            headings.join(","));

      const pickers = it.panel.querySelectorAll(".tier-pick");
      // Four piles: rags loose, oil and zip ties on tier 1, zip ties on 4.
      // Plus the one on the add box.
      check("every pile gets a tier picker, and so does the add box",
            pickers.length === 5, `${pickers.length} pickers`);
      check("and a picker offers Loose plus every tier",
            [...pickers[0].options].map(o => o.textContent).join(",")
            === "Loose,Tier 1,Tier 2,Tier 3,Tier 4",
            [...pickers[0].options].map(o => o.textContent).join(","));
    }

    {
      const it = fresh();
      const row = rowFor(it.panel, "Motor oil");
      const picker = row.querySelector(".tier-pick");
      check("a pile's picker starts on the tier it is actually on",
            picker.value === "1", picker.value);

      picker.value = "3";
      picker.dispatchEvent(new Event("change", { bubbles: true }));
      const oil = it.profile.items.find(item => item.id === "i1");
      check("picking another tier moves the whole pile",
            same(oil.placements.map(p => [p.tier, p.quantity]), [[3, 4]]),
            JSON.stringify(oil.placements));
      check("and it says something changed", it.changed() === 1);
    }

    {
      const it = fresh();
      // Zip ties are on tier 1 AND tier 4. Moving the tier 1 pile onto tier 4
      // should add to what is there, not replace it.
      const row = rowFor(it.panel, "Zip ties");
      const picker = row.querySelector(".tier-pick");
      picker.value = "4";
      picker.dispatchEvent(new Event("change", { bubbles: true }));
      const ties = it.profile.items.find(item => item.id === "i2");
      check("moving a pile onto an occupied tier adds to it",
            same(ties.placements.map(p => [p.tier, p.quantity]), [[4, 8]]),
            JSON.stringify(ties.placements.map(p => [p.tier, p.quantity])));
    }

    {
      const it = fresh();
      const row = rowFor(it.panel, "Rags");
      buttonsSaying(row, "+")[0].click();
      let rags = it.profile.items.find(item => item.id === "i3");
      check("plus adds one where it already is",
            same(rags.placements.map(p => [p.tier, p.quantity]), [[0, 6]]),
            JSON.stringify(rags.placements));

      for (let n = 0; n < 6; n++) {
        const again = rowFor(it.panel, "Rags");
        if (again) buttonsSaying(again, "−")[0].click();
      }
      rags = it.profile.items.find(item => item.id === "i3");
      check("taking the last one out takes the pile out of the container",
            rags.placements.length === 0, JSON.stringify(rags.placements));
      check("but leaves the thing in the catalog, because you still own it",
            it.profile.items.some(item => item.id === "i3"));
    }

    {
      const it = fresh();
      const box = it.panel.querySelector("input[type=text]");
      const picker = [...it.panel.querySelectorAll(".tier-pick")].pop();
      box.value = "Cable ties";
      picker.value = "2";
      picker.dispatchEvent(new Event("change", { bubbles: true }));
      buttonsSaying(it.panel, "Add")[0].click();

      const added = it.profile.items.find(item => item.name === "Cable ties");
      check("a new thing goes on the tier the box was set to",
            Boolean(added) && same(added.placements.map(p => [p.tier, p.quantity]),
                                   [[2, 1]]),
            added ? JSON.stringify(added.placements) : "nothing was added");
    }

    {
      const it = fresh();
      const box = it.panel.querySelector("input[type=text]");
      box.value = "motor OIL";
      buttonsSaying(it.panel, "Add")[0].click();
      const oils = it.profile.items.filter(
        item => item.name.toLowerCase() === "motor oil");
      check("adding something already in the catalog does not make a second one",
            oils.length === 1, `${oils.length} entries called motor oil`);
      check("it adds to the pile instead",
            oils[0].totalQuantity() === 5, String(oils[0].totalQuantity()));
    }

    {
      const it = fresh();
      buttonsSaying(it.panel, "Add tier")[0].click();
      check("Add tier adds one", it.shelf.tierCount === 5,
            String(it.shelf.tierCount));

      buttonsSaying(it.panel, "Remove tier")[0].click();
      buttonsSaying(it.panel, "Remove tier")[0].click();
      check("Remove tier takes one away", it.shelf.tierCount === 3,
            String(it.shelf.tierCount));

      const ties = it.profile.items.find(item => item.id === "i2");
      check("and whatever was on a tier that is gone comes back loose",
            ties.placements.some(p => p.tier === 0 && p.quantity === 6),
            JSON.stringify(ties.placements.map(p => [p.tier, p.quantity])));
      check("nothing is thrown away by removing a tier",
            ties.totalQuantity() === 8, String(ties.totalQuantity()));
    }

    {
      const it = fresh();
      const panel = document.createElement("div");
      benches[benches.length - 1].append(panel);
      contentsPanel(panel, it.profile, it.bin, { changed: () => {}, again: () => {} });
      check("a container with no tiers has no tier headings and no pickers",
            !panel.querySelector(".tier-head") && !panel.querySelector(".tier-pick"));
      check("and says how to get some",
            panel.textContent.includes("No tiers"));
    }

    // -- the items screen ---------------------------------------------------
    const screenBench = () => {
      const holder = bench();
      benches.push(holder);
      const world = madeUp();
      const screen = document.createElement("div");
      holder.append(screen);
      const state = { search: "", filter: "all", chosenId: null };
      let changes = 0;
      const draw = () => itemsScreen(screen, world.profile, state,
                                     { changed: () => changes++, again: draw });
      draw();
      return { ...world, screen, state, draw, changed: () => changes };
    };

    {
      const it = screenBench();
      check("every item in the catalog is listed",
            it.screen.querySelectorAll(".listing").length === 5,
            `${it.screen.querySelectorAll(".listing").length} rows`);
      check("and they are in alphabetical order",
            same([...it.screen.querySelectorAll(".listing-head .name")]
                   .map(node => node.textContent),
                 ["Beach umbrella", "Motor oil", "Rags", "Screws", "Zip ties"]),
            [...it.screen.querySelectorAll(".listing-head .name")]
              .map(node => node.textContent).join(","));

      const line = rowFor(it.screen, "Motor oil").textContent;
      check("a row says which tier the thing is on",
            line.includes("Tier 1") && line.includes("Racking"), line);
      check("something in two places says so rather than listing both",
            rowFor(it.screen, "Zip ties").textContent.includes("2 places"));
      check("something nowhere says Unfiled",
            rowFor(it.screen, "Beach umbrella").textContent.includes("Unfiled"));
      check("something under its par level is flagged",
            rowFor(it.screen, "Screws").textContent.includes("low"));
    }

    {
      const it = screenBench();
      it.state.search = "oil";
      it.draw();
      check("searching narrows the list",
            it.screen.querySelectorAll(".listing").length === 1
            && rowFor(it.screen, "Motor oil"),
            `${it.screen.querySelectorAll(".listing").length} rows`);

      it.state.search = "";
      it.state.filter = "unfiled";
      it.draw();
      check("the not-filed tab shows only things that are nowhere",
            same([...it.screen.querySelectorAll(".listing-head .name")]
                   .map(node => node.textContent), ["Beach umbrella"]));

      it.state.filter = "low";
      it.draw();
      check("the running-low tab shows only things under their par level",
            same([...it.screen.querySelectorAll(".listing-head .name")]
                   .map(node => node.textContent), ["Screws"]));
    }

    {
      const it = screenBench();
      it.state.chosenId = "i1";
      it.draw();
      const body = it.screen.querySelector(".listing-body");
      check("opening an item shows where it is", Boolean(body)
            && body.textContent.includes("Racking"));

      const picker = body.querySelector(".tier-pick");
      picker.value = "3";
      picker.dispatchEvent(new Event("change", { bubbles: true }));
      const oil = it.profile.items.find(item => item.id === "i1");
      check("and its tier can be changed from here too",
            same(oil.placements.map(p => p.tier), [3]),
            JSON.stringify(oil.placements));
    }

    {
      const it = screenBench();
      it.state.chosenId = "i5";                 // the unfiled one
      it.draw();
      const body = it.screen.querySelector(".listing-body");
      const put = buttonsSaying(body, "Put here")[0];
      check("an unfiled thing can be put somewhere from here", Boolean(put));
      put.click();
      const umbrella = it.profile.items.find(item => item.id === "i5");
      check("and it lands in the container that was picked",
            umbrella.placements.length === 1
            && umbrella.placements[0].containerId === "c1",
            JSON.stringify(umbrella.placements));
    }

    {
      // Rags are already loose in the racking, which is what the container
      // and tier boxes both start on, so pressing Put here lands on the pile
      // that is already there. The unfiled case above cannot tell adding from
      // replacing, because there is nothing to replace.
      const it = screenBench();
      it.state.chosenId = "i3";
      it.draw();
      const body = it.screen.querySelector(".listing-body");
      buttonsSaying(body, "Put here")[0].click();
      const rags = it.profile.items.find(item => item.id === "i3");
      check("putting one more where some already are adds to the pile",
            rags.totalQuantity() === 6
            && rags.placements.length === 1 && rags.placements[0].tier === 0,
            JSON.stringify(rags.placements.map(p => [p.tier, p.quantity])));
    }

    {
      const it = screenBench();
      it.state.chosenId = "i1";
      it.draw();
      const body = it.screen.querySelector(".listing-body");
      const count = body.querySelector(".qty-box");
      count.value = "12";
      count.dispatchEvent(new Event("change", { bubbles: true }));
      const oil = it.profile.items.find(item => item.id === "i1");
      check("typing a count sets it", oil.totalQuantity() === 12,
            String(oil.totalQuantity()));

      const again = it.screen.querySelector(".listing-body .qty-box");
      again.value = "0";
      again.dispatchEvent(new Event("change", { bubbles: true }));
      const after = it.profile.items.find(item => item.id === "i1");
      check("typing zero takes it out of that container",
            after.placements.length === 0, JSON.stringify(after.placements));
      check("and still leaves it in the catalog",
            it.profile.items.some(item => item.id === "i1"));
    }
  } catch (error) {
    check("the items checks ran to the end", false,
          `${error?.message ?? error}\n${error?.stack ?? ""}`);
  } finally {
    for (const holder of benches) holder.remove();
  }

  return results;
}

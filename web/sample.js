/**
 * sample.js
 * =========
 *
 * A made-up profile, for somebody who has landed here with nothing.
 *
 * Worth having rather than showing an empty launcher and a sentence about
 * exporting from the desktop app. Most people who open this will not have the
 * desktop app, and an app that cannot show you what it does until you have
 * already committed to it is an app nobody tries.
 *
 * It is also the thing the checks and the screenshots run against, so it is
 * deliberately awkward: an L-shaped room, because that is the shape that has
 * broken the wall culling twice; a tall cabinet, because a container taller
 * than the walls is what used to get its top cropped off; and containers
 * against three different walls, because that is where the draw order shows.
 */
import * as M from "./model.js";

export function sample() {
  const profile = new M.Profile({ name: "A made-up house", color: "#33d6a0" });

  const ground = new M.Floor({ name: "Ground floor", color: "#4f7cff" });
  const upstairs = new M.Floor({ name: "Upstairs", color: "#a78bfa" });

  const garage = new M.Room({
    name: "Garage", color: "#33d6a0",
    points: M.lShapePoints(420, 320),
  });
  garage.containers = [
    new M.Container({ name: "Tall shelving", color: "#f0a726",
                      x: 10, y: 10, w: 150, h: 45, height: 100, tierCount: 4 }),
    new M.Container({ name: "Workbench", color: "#94a3b8",
                      x: 10, y: 240, w: 190, h: 60, height: 40 }),
    new M.Container({ name: "Paint bin", color: "#f2555a",
                      x: 250, y: 200, w: 70, h: 70, height: 30, tierCount: 2 }),
  ];

  const kitchen = new M.Room({
    name: "Kitchen", color: "#4f7cff",
    points: M.rectanglePoints(340, 260),
  });
  kitchen.containers = [
    new M.Container({ name: "Pantry", color: "#84cc16",
                      x: 20, y: 20, w: 120, h: 50, height: 120, tierCount: 5 }),
    new M.Container({ name: "Under the sink", color: "#22d3ee",
                      x: 200, y: 180, w: 110, h: 55, height: 30 }),
  ];

  const closet = new M.Room({
    name: "Hall closet", color: "#e879f9",
    points: M.rectanglePoints(180, 140),
  });
  closet.containers = [
    new M.Container({ name: "Top shelf", color: "#fb923c",
                      x: 15, y: 15, w: 140, h: 40, height: 75, tierCount: 3 }),
  ];

  ground.rooms = [garage, kitchen];
  upstairs.rooms = [closet];
  profile.floors = [ground, upstairs];

  const [shelving, bench, paint] = garage.containers;
  const [pantry] = kitchen.containers;
  const [top] = closet.containers;

  profile.items = [
    item("Socket set", "#4f7cff", [[shelving.id, 1, 2]]),
    item("Motor oil", "#f0a726", [[shelving.id, 4, 1]]),
    item("Extension cords", "#33d6a0", [[shelving.id, 3, 3], [bench.id, 1, 0]]),
    item("Wood screws", "#94a3b8", [[bench.id, 6, 0]]),
    item("Exterior white", "#f2555a", [[paint.id, 2, 1]]),
    item("Paint rollers", "#a78bfa", [[paint.id, 5, 2]]),
    item("Tinned tomatoes", "#84cc16", [[pantry.id, 12, 2]]),
    item("Pasta", "#facc15", [[pantry.id, 8, 3]]),
    item("Spare bulbs", "#fb923c", [[top.id, 6, 1]]),
    // One with nowhere to live, so the "not in any container" line has
    // something to count and does not go untested.
    item("Beach umbrella", "#22d3ee", []),
  ];

  // Through fromDict once, the way opening a file does. A container put
  // somewhere it does not fit gets pulled back inside on the way in, so a
  // profile built by hand is not settled until it has been loaded once.
  return M.Profile.fromDict(profile.toDict());
}

function item(name, color, placements) {
  return new M.Item({
    name, color,
    placements: placements.map(
      ([containerId, quantity, tier]) => new M.Placement(containerId, quantity, tier)),
  });
}

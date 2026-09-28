/**
 * floor_checks.js
 * ===============
 *
 * What the floor plan canvas is supposed to do, driven through the same
 * pointer events a hand produces.
 *
 * WHY NOT DRIVE THE REAL PAGE
 * ---------------------------
 * The first version of these checks clicked at fractions of the canvas and
 * hoped a handle was there. It found two real bugs, then spent longer failing
 * for reasons that were the test's fault than the code's: a resize handle is
 * nine pixels wide, and "about two thirds across" is not an address.
 *
 * So these build a FloorView over a canvas of a known size with a room whose
 * corners are known numbers, ask the view where a handle actually is, and
 * press exactly there. What is being checked is the logic, which is where the
 * mistakes live. Whether the strips redraw is a job for looking at it.
 *
 * They run in a browser, from dev.html. A canvas and a ResizeObserver are not
 * things node has, and a stand-in for them would be a stand-in for the part
 * that matters.
 */
import * as M from "./model.js";
import * as T from "./theme.js";
import * as F from "./floor.js";

/** A canvas of a fixed size, off to one side of the page.
 *
 *  Not display:none. A hidden element has no size, a canvas with no size has
 *  nothing to draw on, and everything below would pass by doing nothing.
 */
function bench(width = 800, height = 600) {
  const holder = document.createElement("div");
  holder.style.cssText = `position:fixed;left:-10000px;top:0;`
                       + `width:${width}px;height:${height}px;`;
  const canvas = document.createElement("canvas");
  canvas.style.cssText = "width:100%;height:100%;display:block";
  holder.append(canvas);
  document.body.append(holder);
  return { holder, canvas };
}

/** Press, move and release, in canvas pixels. */
function press(canvas, x, y, pointerId = 1, type = "mouse") {
  send(canvas, "pointerdown", x, y, pointerId, type, 0);
}
function move(canvas, x, y, pointerId = 1, type = "mouse") {
  send(canvas, "pointermove", x, y, pointerId, type, 1);
}
function lift(canvas, x, y, pointerId = 1, type = "mouse") {
  send(canvas, "pointerup", x, y, pointerId, type, 0);
}

function send(canvas, name, canvasX, canvasY, pointerId, pointerType, buttons) {
  const box = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.dispatchEvent(new PointerEvent(name, {
    bubbles: true, cancelable: true, pointerId, pointerType, buttons, button: 0,
    clientX: box.left + canvasX / ratio,
    clientY: box.top + canvasY / ratio,
  }));
}

/** Wait past the double-press window.
 *
 *  Two presses close together on the same thing mean something else: step
 *  inside a room, or take a corner away. A check that selects and then
 *  presses again has to let that window close first, or it is quietly
 *  testing the other gesture. This cost six failing checks before it was
 *  written down.
 */
const settle = () => new Promise(resolve => setTimeout(resolve, 380));

/** A whole drag in one call, with a few steps so the slop threshold is passed. */
function dragBy(canvas, from, to, pointerId = 1, type = "mouse") {
  press(canvas, from[0], from[1], pointerId, type);
  for (let step = 1; step <= 4; step++) {
    move(canvas, from[0] + (to[0] - from[0]) * step / 4,
         from[1] + (to[1] - from[1]) * step / 4, pointerId, type);
  }
  lift(canvas, to[0], to[1], pointerId, type);
}

function madeUp() {
  const profile = new M.Profile({ name: "Checks" });
  const floor = new M.Floor({ name: "Ground" });
  const room = new M.Room({
    name: "Garage", color: "#33d6a0", x: 100, y: 100,
    points: M.rectanglePoints(400, 300),
  });
  room.containers = [new M.Container({ name: "Shelf", x: 40, y: 40,
                                       w: 100, h: 60 })];
  floor.rooms = [room];
  profile.floors = [floor];
  return { profile, floor, room };
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Is this point on one of the polygon's edges, to within a whisker? */
function onOutline(points, [px, py]) {
  for (let at = 0; at < points.length; at++) {
    const [ax, ay] = points[at];
    const [bx, by] = points[(at + 1) % points.length];
    const [, , distance] = M.closestPointOnSegment(ax, ay, bx, by, px, py);
    if (distance < 0.001) return true;
  }
  return false;
}
const round = value => Math.round(value * 1000) / 1000;

/** Run every check. Returns [{ label, ok, why }]. */
export async function runFloorChecks() {
  const results = [];
  const check = (label, ok, why = "") => results.push({ label, ok, why: String(why) });
  const benches = [];

  /** A fresh canvas, profile and view for one check, so nothing inherits a
   *  half-finished drag or a stray selection from the one before. */
  const fresh = (setUp = () => {}) => {
    const made = bench();
    benches.push(made.holder);
    const world = madeUp();
    let changes = 0;
    const view = new F.FloorView(made.canvas, { onChanged: () => changes++ });
    view.show(world.profile, world.floor);
    setUp(view);
    return { ...world, ...made, view, changed: () => changes };
  };

  try {
    // -- the small pieces ---------------------------------------------------

    check("snap rounds to the grid",
          F.snap(0) === 0 && F.snap(9) === 0 && F.snap(11) === 20
          && F.snap(-11) === -20 && F.snap(200) === 200,
          [0, 9, 11, -11].map(F.snap).join(","));
    check("every preset in the list can be drawn",
          M.ROOM_PRESETS.every(([name]) => (F.presetPoints(name, 100, 80) ?? []).length >= 3),
          M.ROOM_PRESETS.map(([name]) => name).join(","));
    check("an unknown preset is refused rather than guessed at",
          F.presetPoints("Hexagon", 100, 80) === null);

    // -- the camera ---------------------------------------------------------

    {
      const it = fresh();
      // Everything on the floor has to be on the screen after a fit, with the
      // room's own corners inside the canvas.
      const onScreen = it.view.outline(it.room).map(([x, y]) => it.view.toScreen(x, y));
      check("fit puts the whole room on the canvas",
            onScreen.every(point => point.x >= 0 && point.y >= 0
                           && point.x <= it.canvas.width && point.y <= it.canvas.height),
            JSON.stringify(onScreen.map(p => [Math.round(p.x), Math.round(p.y)])));

      const middle = [it.canvas.width / 2, it.canvas.height / 2];
      const under = it.view.toScene(...middle);
      it.view.zoomAt(middle[0], middle[1], 2);
      check("zooming keeps the same spot under the pointer",
            same(under.map(round), it.view.toScene(...middle).map(round)),
            `${under} vs ${it.view.toScene(...middle)}`);

      const was = it.view.scale;
      for (let n = 0; n < 40; n++) it.view.zoomAt(0, 0, 4);
      check("zoom stops somewhere sane instead of running away",
            it.view.scale < was * 1000 && Number.isFinite(it.view.scale),
            `${was} -> ${it.view.scale}`);
    }

    // -- selecting ----------------------------------------------------------

    {
      const it = fresh();
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);
      check("a press inside a room selects it", it.view.selected === it.room,
            String(it.view.selected?.name));

      const outside = it.view.toScreen(it.room.x - 200, it.room.y - 200);
      press(it.canvas, outside.x, outside.y);
      lift(it.canvas, outside.x, outside.y);
      check("a press on empty floor deselects", it.view.selected === null);

      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);
      check("two presses on a room step inside it", it.view.focused === it.room);
      check("and stepping in drops the selection, because the room is not "
            + "what you are working on any more", it.view.selected === null);
    }

    // -- moving a room ------------------------------------------------------

    {
      const it = fresh();
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);

      await settle();
      const before = [it.room.x, it.room.y];
      const to = it.view.toScreen(it.room.x + 260, it.room.y + 210);
      dragBy(it.canvas, [centre.x, centre.y], [to.x, to.y]);
      check("dragging a selected room moves it",
            it.room.x === before[0] + 60 && it.room.y === before[1] + 60,
            `${before} -> ${[it.room.x, it.room.y]}`);
      check("and lands on the grid",
            it.room.x % T.GRID_SIZE === 0 && it.room.y % T.GRID_SIZE === 0);
      check("and says so once, not once per frame", it.changed() === 1,
            `${it.changed()} changes`);
    }

    {
      const it = fresh();
      it.room.locked = true;
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);
      await settle();
      const before = [it.room.x, it.room.y];
      const to = it.view.toScreen(it.room.x + 300, it.room.y + 250);
      dragBy(it.canvas, [centre.x, centre.y], [to.x, to.y]);
      check("a locked room does not move", same(before, [it.room.x, it.room.y]),
            `${before} -> ${[it.room.x, it.room.y]}`);
      check("but can still be selected, so it can be unlocked",
            it.view.selected === it.room);
    }

    // -- stretching ---------------------------------------------------------

    {
      const it = fresh(view => view.setEditMode(F.RESIZE));
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);

      await settle();
      const grip = it.view.gripsFor(it.room).find(each => each.name === "se");
      const from = it.view.toScreen(grip.x, grip.y);
      const to = it.view.toScreen(grip.x + 100, grip.y + 60);
      dragBy(it.canvas, [from.x, from.y], [to.x, to.y]);

      const [, , wide, high] = it.room.bounds();
      check("dragging the south-east grip stretches the room",
            Math.round(wide) === 500 && Math.round(high) === 360,
            `${Math.round(wide)} by ${Math.round(high)}`);
      check("and the opposite corner stays put",
            it.room.x === 100 && it.room.y === 100,
            `${it.room.x}, ${it.room.y}`);
    }

    {
      // The other corner, because dragging the south-east one cannot tell the
      // difference between anchoring the far side and anchoring nothing at
      // all: the far side happens to be where it already was. A mutation that
      // dropped the anchor entirely went unnoticed until this was here.
      const it = fresh(view => view.setEditMode(F.RESIZE));
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);
      await settle();

      const grip = it.view.gripsFor(it.room).find(each => each.name === "nw");
      const from = it.view.toScreen(grip.x, grip.y);
      const to = it.view.toScreen(grip.x + 60, grip.y + 40);
      dragBy(it.canvas, [from.x, from.y], [to.x, to.y]);

      const [x, y, wide, high] = it.view.boxOf(it.room);
      check("dragging the north-west grip keeps the far side where it was",
            Math.round(x + wide) === 500 && Math.round(y + high) === 400,
            `far corner is ${Math.round(x + wide)}, ${Math.round(y + high)}`);
      check("and the room shrank by what the grip travelled",
            Math.round(wide) === 340 && Math.round(high) === 260,
            `${Math.round(wide)} by ${Math.round(high)}`);
    }

    {
      const it = fresh(view => view.setEditMode(F.RESIZE));
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);

      await settle();
      const grip = it.view.gripsFor(it.room).find(each => each.name === "nw");
      const from = it.view.toScreen(grip.x, grip.y);
      // Dragged far past the opposite side, which is the slip that would turn
      // a room inside out if nothing stopped it.
      const to = it.view.toScreen(grip.x + 900, grip.y + 900);
      dragBy(it.canvas, [from.x, from.y], [to.x, to.y]);
      const [, , wide, high] = it.room.bounds();
      check("a room cannot be squashed through itself",
            wide >= T.GRID_SIZE && high >= T.GRID_SIZE,
            `${Math.round(wide)} by ${Math.round(high)}`);
      check("and what was inside it is still inside it",
            M.roomContainsRect(it.room, it.room.containers[0].x,
                               it.room.containers[0].y, it.room.containers[0].w,
                               it.room.containers[0].h));
    }

    // -- corners ------------------------------------------------------------

    {
      const it = fresh(view => view.setEditMode(F.VERTICES));
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);
      check("selecting in shape mode does not add a corner on the way",
            it.room.points.length === 4, `${it.room.points.length} corners`);

      await settle();
      const corner = it.view.outline(it.room)[2];
      const from = it.view.toScreen(...corner);
      const to = it.view.toScreen(corner[0] - 80, corner[1] - 60);
      dragBy(it.canvas, [from.x, from.y], [to.x, to.y]);
      check("dragging a corner moves that corner and no other",
            same(it.room.points[2], [320, 240])
            && same(it.room.points[0], [0, 0]) && same(it.room.points[1], [400, 0]),
            JSON.stringify(it.room.points));

      // The added corner sits ON its edge, so the outline is the same until
      // somebody drags it. That is the whole reason it is placed there rather
      // than where the press landed, and it is checked against what the
      // outline WAS rather than a number worked out by hand: the first
      // version of this line guessed 400 by 240 and was simply wrong about
      // the arithmetic, which is a fine way to spend an afternoon chasing
      // code that was right all along.
      const shapeBefore = it.room.points.map(point => [...point]);
      const boundsBefore = it.room.bounds().map(Math.round);

      const inside = it.view.toScreen(it.room.x + 100, it.room.y + 100);
      press(it.canvas, inside.x, inside.y);
      lift(it.canvas, inside.x, inside.y);
      check("a press inside adds a corner on the nearest edge",
            it.room.points.length === shapeBefore.length + 1,
            `${it.room.points.length} corners`);
      check("and adding it does not change the shape",
            same(boundsBefore, it.room.bounds().map(Math.round)),
            `${boundsBefore} -> ${it.room.bounds().map(Math.round)}`);
      check("and the new corner really is on the outline it was added to",
            onOutline(shapeBefore, it.room.points.find(
              point => !shapeBefore.some(was => same(was, point)))),
            JSON.stringify(it.room.points));
    }

    {
      const it = fresh(view => view.setEditMode(F.VERTICES));
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);

      await settle();
      const corner = it.view.outline(it.room)[1];
      const at = it.view.toScreen(...corner);
      press(it.canvas, at.x, at.y); lift(it.canvas, at.x, at.y);
      press(it.canvas, at.x, at.y); lift(it.canvas, at.x, at.y);
      check("pressing a corner twice takes it away",
            it.room.points.length === 3, `${it.room.points.length} corners`);

      await settle();
      const last = it.view.outline(it.room)[0];
      const spot = it.view.toScreen(...last);
      press(it.canvas, spot.x, spot.y); lift(it.canvas, spot.x, spot.y);
      press(it.canvas, spot.x, spot.y); lift(it.canvas, spot.x, spot.y);
      check("but never below three, which is the fewest that encloses an area",
            it.room.points.length === 3, `${it.room.points.length} corners`);
    }

    // -- making rooms -------------------------------------------------------

    {
      const it = fresh(view => view.setMode(F.DRAW));
      const corners = [[600, 100], [900, 100], [900, 400], [600, 400]];
      for (const [x, y] of corners) {
        const at = it.view.toScreen(x, y);
        press(it.canvas, at.x, at.y); lift(it.canvas, at.x, at.y);
      }
      check("a room being drawn is not a room yet",
            it.floor.rooms.length === 1, `${it.floor.rooms.length} rooms`);
      const first = it.view.toScreen(...corners[0]);
      press(it.canvas, first.x, first.y); lift(it.canvas, first.x, first.y);

      check("pressing the first corner again closes it",
            it.floor.rooms.length === 2, `${it.floor.rooms.length} rooms`);
      const made = it.floor.rooms[1];
      check("and it is where it was drawn, stored from its own corner",
            made.x === 600 && made.y === 100
            && same(made.points, [[0, 0], [300, 0], [300, 300], [0, 300]]),
            `${made.x},${made.y} ${JSON.stringify(made.points)}`);
      check("and it is named the way the desktop names one",
            made.name === "Room 2", made.name);
      check("and the tool goes back to Select, so the next press selects",
            it.view.mode === F.SELECT && it.view.selected === made);
    }

    {
      const it = fresh(view => view.setMode(F.DRAW));
      for (const [x, y] of [[600, 100], [900, 100]]) {
        const at = it.view.toScreen(x, y);
        press(it.canvas, at.x, at.y); lift(it.canvas, at.x, at.y);
      }
      it.view.keyDown({ key: "Escape", code: "Escape", target: it.canvas });
      check("giving up on a half-drawn room leaves nothing behind",
            it.floor.rooms.length === 1 && it.view.mode === F.SELECT);
    }

    // Escape is the keyboard way out, and a phone has no keyboard. These are
    // the ones the buttons under the toolbar call.
    {
      let announced = [];
      const made = bench();
      benches.push(made.holder);
      const world = madeUp();
      const view = new F.FloorView(made.canvas, {
        onDrawingChanged: placed => announced.push(placed),
      });
      view.show(world.profile, world.floor);
      view.setMode(F.DRAW);

      for (const [x, y] of [[600, 100], [900, 100], [900, 400]]) {
        const at = view.toScreen(x, y);
        press(made.canvas, at.x, at.y); lift(made.canvas, at.x, at.y);
      }
      check("the view says how many corners have gone down",
            view.cornersPlaced === 3 && same(announced, [1, 2, 3]),
            `${view.cornersPlaced} placed, announced ${announced}`);

      view.undoLastCorner();
      check("taking back a corner takes back exactly one",
            view.cornersPlaced === 2 && announced[announced.length - 1] === 2,
            `${view.cornersPlaced} left`);

      view.cancelDrawing();
      check("cancelling throws the shape away and goes back to Select",
            view.cornersPlaced === 0 && view.mode === F.SELECT
            && world.floor.rooms.length === 1,
            `${world.floor.rooms.length} rooms, mode ${view.mode}`);
      check("and it says so, so a toolbar can put its buttons away",
            announced[announced.length - 1] === 0, String(announced));

      view.undoLastCorner();
      check("taking back a corner when there is none is harmless",
            view.cornersPlaced === 0);
    }

    for (const [name, corners] of [["Rectangle", 4], ["Triangle", 3],
                                   ["Circle", 20], ["L-shape", 6]]) {
      const it = fresh(view => view.setMode(F.SHAPE, name));
      const from = it.view.toScreen(600, 100);
      const to = it.view.toScreen(800, 260);
      dragBy(it.canvas, [from.x, from.y], [to.x, to.y]);
      const made = it.floor.rooms[1];
      check(`dragging out the ${name} preset makes one`,
            Boolean(made) && made.points.length === corners,
            made ? `${made.points.length} corners` : "no room appeared");
      if (!made) continue;
      const [, , wide, high] = made.bounds();
      check(`and the ${name} is the size it was dragged`,
            name === "Square"
              ? Math.round(wide) === Math.round(high)
              : Math.round(wide) === 200 && Math.round(high) === 160,
            `${Math.round(wide)} by ${Math.round(high)}`);
    }

    {
      const it = fresh(view => view.setMode(F.SHAPE, "Rectangle"));
      const at = it.view.toScreen(600, 100);
      press(it.canvas, at.x, at.y);
      lift(it.canvas, at.x, at.y);
      const made = it.floor.rooms[1];
      const [, , wide] = made?.bounds() ?? [0, 0, 0];
      check("pressing a preset without dragging still makes a room",
            Boolean(made) && wide > 0,
            "a tap that does nothing reads as a broken button");
    }

    // -- containers ---------------------------------------------------------

    {
      const it = fresh(view => view.setMode(F.BOX));
      const from = it.view.toScreen(it.room.x + 200, it.room.y + 160);
      const to = it.view.toScreen(it.room.x + 320, it.room.y + 240);
      dragBy(it.canvas, [from.x, from.y], [to.x, to.y]);
      const made = it.room.containers[1];
      check("dragging inside a room makes a container",
            Boolean(made) && made.w === 120 && made.h === 80,
            made ? `${made.w} by ${made.h}` : "nothing appeared");
      check("and it is named the way the desktop names one",
            made?.name === "Container 2", made?.name);
      check("and the view steps inside, because that is what you do next",
            it.view.focused === it.room && it.view.selected === made);
    }

    {
      const it = fresh(view => view.setMode(F.BOX));
      // Dragged half outside the room, which is a slip rather than a wish.
      const from = it.view.toScreen(it.room.x + 340, it.room.y + 240);
      const to = it.view.toScreen(it.room.x + 520, it.room.y + 380);
      dragBy(it.canvas, [from.x, from.y], [to.x, to.y]);
      const made = it.room.containers[1];
      check("one dragged over a wall is nudged inside rather than refused",
            Boolean(made) && M.roomContainsRect(it.room, made.x, made.y, made.w, made.h),
            made ? `${made.x},${made.y} ${made.w}x${made.h}` : "nothing appeared");
    }

    {
      const it = fresh();
      it.view.stepInto(it.room);
      const box = it.room.containers[0];
      const from = it.view.toScreen(it.room.x + box.x + 50, it.room.y + box.y + 30);
      press(it.canvas, from.x, from.y);
      lift(it.canvas, from.x, from.y);
      await settle();
      check("inside a room, a press picks a container", it.view.selected === box,
            String(it.view.selected?.name));

      const to = it.view.toScreen(it.room.x + box.x + 950,
                                  it.room.y + box.y + 30);
      dragBy(it.canvas, [from.x, from.y], [to.x, to.y]);
      check("dragging it far past the wall keeps it in the room",
            M.roomContainsRect(it.room, box.x, box.y, box.w, box.h),
            `${box.x},${box.y}`);
      check("and it slid along the wall rather than staying put",
            box.x > 40, `x is ${box.x}`);
    }

    // -- two fingers --------------------------------------------------------

    {
      const it = fresh();
      const was = it.view.scale;
      press(it.canvas, 300, 300, 1, "touch");
      press(it.canvas, 400, 300, 2, "touch");
      move(it.canvas, 250, 300, 1, "touch");
      move(it.canvas, 450, 300, 2, "touch");
      check("two fingers spreading apart zoom in",
            it.view.scale > was, `${round(was)} -> ${round(it.view.scale)}`);

      const zoomed = it.view.scale;
      move(it.canvas, 300, 300, 1, "touch");
      move(it.canvas, 500, 300, 2, "touch");
      const panned = { x: it.view.panX, y: it.view.panY };
      check("and sliding them together pans without zooming",
            Math.abs(it.view.scale - zoomed) < 1e-6,
            `${round(zoomed)} -> ${round(it.view.scale)}`);
      lift(it.canvas, 300, 300, 1, "touch");
      lift(it.canvas, 500, 300, 2, "touch");
      check("lifting them leaves the camera where it was put",
            it.view.panX === panned.x && it.view.panY === panned.y);
    }

    {
      const it = fresh();
      const centre = it.view.toScreen(it.room.x + 200, it.room.y + 150);
      press(it.canvas, centre.x, centre.y);
      lift(it.canvas, centre.x, centre.y);
      await settle();
      const before = [it.room.x, it.room.y];
      // A second finger arriving mid-drag means the camera, so whatever the
      // first one was doing is abandoned rather than finished at whatever
      // place the second finger happens to leave it.
      press(it.canvas, centre.x, centre.y, 1, "touch");
      move(it.canvas, centre.x + 40, centre.y + 40, 1, "touch");
      press(it.canvas, centre.x + 200, centre.y, 2, "touch");
      move(it.canvas, centre.x + 300, centre.y, 2, "touch");
      lift(it.canvas, centre.x + 300, centre.y, 2, "touch");
      lift(it.canvas, centre.x + 40, centre.y + 40, 1, "touch");
      check("a second finger takes over from a half-finished drag",
            Math.abs(it.room.x - before[0]) <= T.GRID_SIZE
            && Math.abs(it.room.y - before[1]) <= T.GRID_SIZE,
            `${before} -> ${[it.room.x, it.room.y]}`);
    }
  } catch (error) {
    check("the floor checks ran to the end", false,
          `${error?.message ?? error}\n${error?.stack ?? ""}`);
  } finally {
    for (const holder of benches) holder.remove();
  }

  return results;
}

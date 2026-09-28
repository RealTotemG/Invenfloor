"""
order_test.py
=============

What gets drawn before what, in the 3D room.

THE BUG THIS EXISTS FOR
-----------------------
The 3D view used to give every wall and every container one number, the depth
of its far corner, and sort by it. That is the obvious thing to do and it is
wrong, because "behind" is not a number. A wall runs the whole length of a
side of a room, so it is nearer the camera than some of what shares the room
with it and further than the rest, and no single number says where it belongs.

It went unnoticed for a long time because a rectangular room hides it. Put a
tall shelf in a round room and four walls paint straight over it.

The fix is in iso.paint_order, and the argument for it is written above that
function. This file holds the fix to what it promises:

    nothing is ever drawn before something it stands behind.

Checked exhaustively, every pair in the result, because a room only ever has a
few dozen pieces in it. And checked on scenes the app can actually produce:
every preset shape, with containers placed through nearest_fit the way every
path that moves a container places them. Holding the code to a scene it can
never be given proves nothing.

    QT_QPA_PLATFORM=offscreen python order_test.py
"""
import os
import random
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import iso
import models


PASSED = []
FAILED = []


def check(label, ok, why=""):
    (PASSED if ok else FAILED).append(label)
    print(f"{'  ok  ' if ok else ' FAIL '} {label}")
    if not ok and why:
        print(f"        {why}")


def presets():
    return [
        ("a rectangle", models.rectangle_points(400, 300)),
        ("a square", models.square_points(360)),
        ("an L", models.l_shape_points(400, 300)),
        ("a triangle", models.triangle_points(400, 300)),
        ("a circle", models.circle_points(400, 300)),
    ]


def scene(points, boxes):
    """A room's far walls and some containers, as paint_order wants them.

    Returns (pieces, footprint_of) where a piece is (footprint, name). Named
    rather than numbered so a failure says which wall and which box.
    """
    corners = [tuple(p) for p in points]
    pieces = [(iso.wall_footprint(wall), f"wall {n}")
              for n, wall in enumerate(iso.far_walls(corners))]
    pieces += [(iso.box_footprint(*box), f"box {n}")
               for n, box in enumerate(boxes)]
    return pieces, {name: footprint for footprint, name in pieces}


def placed(points, wanted):
    """Containers put in a room the way the app puts them: through nearest_fit.

    Anything that will not fit inside the room comes back moved or shrunk, and
    that is the point. A scene with a container lying across a wall is not a
    scene this program can ever be asked to draw.
    """
    corners = [tuple(p) for p in points]
    room = models.Room(id="r", name="r", points=[list(c) for c in corners])
    left = min(px for px, _ in corners)
    top = min(py for _, py in corners)
    return [models.nearest_fit(room, left + x, top + y, w, h)
            for x, y, w, h in wanted]


def out_of_order(order, footprint_of):
    """Every pair in a drawing order that came out the wrong way round.

    order[a] is painted before order[b], so order[a] must not be standing in
    front of order[b]. Exhaustive rather than sampled.
    """
    wrong = []
    for a in range(len(order)):
        for b in range(a + 1, len(order)):
            if iso.behind(footprint_of[order[a]], footprint_of[order[b]]) > 0:
                wrong.append(f"{order[a]} drawn before {order[b]}, "
                             f"which it stands in front of")
    return wrong


def the_old_way(pieces):
    """The rule that used to be in room_view_3d.py, kept so it can be failed.

    One depth number each, walls winning the ties. Here to prove the scene
    below is a real counterexample and not a straw man: if this ever stops
    failing, the scene has stopped reproducing the bug and needs replacing.
    """
    def key(piece):
        footprint, name = piece
        return (iso.footprint_depth(footprint), 0 if name.startswith("wall") else 1)
    return [name for _, name in sorted(pieces, key=key)]


def main():
    # -- the scene the old rule actually got wrong --------------------------
    # A round room with a tall shelf down one side. Nothing exotic: the circle
    # is one of the app's own preset shapes and the shelf goes in through
    # nearest_fit like every other container.
    points = models.circle_points(400, 300)
    boxes = placed(points, [(0, 30, 70, 240), (250, 0, 90, 20),
                            (120, 100, 60, 40), (300, 200, 50, 50)])
    pieces, footprint_of = scene(points, boxes)

    broken = out_of_order(the_old_way(pieces), footprint_of)
    check("the old depth sort really does get this room wrong",
          len(broken) > 0,
          "if this passes the scene no longer reproduces the bug, so the "
          "check below has stopped meaning anything")
    print(f"        (it draws {len(broken)} pairs the wrong way round, "
          f"first: {broken[0] if broken else ''})")

    fixed = out_of_order([name for _, name in iso.paint_order(pieces)],
                         footprint_of)
    check("and paint_order gets the same room right", not fixed,
          "; ".join(fixed[:3]))

    # -- every preset, and then a lot of rooms nobody chose -----------------
    for label, points in presets():
        for turned, listing in (("as listed", points),
                                ("reversed", list(points)[::-1])):
            boxes = placed(listing, [(0, 30, 70, 240), (250, 0, 90, 20),
                                     (120, 100, 60, 40), (300, 200, 50, 50),
                                     (40, 190, 150, 35), (200, 40, 30, 200)])
            pieces, footprint_of = scene(listing, boxes)
            order = [name for _, name in iso.paint_order(pieces)]

            check(f"{label} {turned}: nothing is drawn before what it hides",
                  not out_of_order(order, footprint_of),
                  "; ".join(out_of_order(order, footprint_of)[:3]))
            check(f"{label} {turned}: and every piece is still in the picture",
                  sorted(order) == sorted(footprint_of),
                  f"{len(order)} of {len(footprint_of)} pieces came back")

    rng = random.Random(20260928)
    worst = 0
    for _ in range(400):
        points = models.rectangle_points(rng.randint(200, 600),
                                         rng.randint(200, 600))
        wanted = [(rng.randint(0, 400), rng.randint(0, 400),
                   rng.randint(20, 220), rng.randint(20, 220))
                  for _ in range(rng.randint(2, 7))]
        pieces, footprint_of = scene(points, placed(points, wanted))
        order = [name for _, name in iso.paint_order(pieces)]
        worst = max(worst, len(out_of_order(order, footprint_of)))
    check("400 rooms of random sizes with random things in them, all right",
          worst == 0, f"the worst had {worst} pairs backwards")

    # -- the tie, which is the case the old code handled by hand ------------
    # A container pushed flush into a corner shares an edge with the wall. The
    # old sort had a second sort key for exactly this. behind() gets it from
    # the <= instead, so the special case is gone rather than reimplemented.
    wall = ((0, 0), (400, 0))
    flush = iso.box_footprint(0, 0, 80, 60)
    check("a wall is behind a container standing flush against it",
          iso.behind(iso.wall_footprint(wall), flush) == -1,
          str(iso.behind(iso.wall_footprint(wall), flush)))
    check("and the container is not behind the wall",
          iso.behind(flush, iso.wall_footprint(wall)) == 1)

    # -- and what the relation is allowed to have no opinion about ----------
    overlapping = [(iso.box_footprint(0, 0, 100, 100), "a"),
                   (iso.box_footprint(50, 50, 100, 100), "b")]
    check("two things overlapping on the floor are not ordered either way",
          iso.behind(overlapping[0][0], overlapping[1][0]) == 0)
    check("and ordering them still returns both",
          len(iso.paint_order(overlapping)) == 2)

    # -- the contradiction that started all this ----------------------------
    # Two containers diagonally apart used to come out behind EACH OTHER: the
    # first ends before the second in x, the second ends before the first in
    # y, and both rules fired. That is a cycle, and a cycle is the one thing a
    # topological sort cannot answer, so it broke an edge and guessed. The
    # scene came out of a real round room with four ordinary containers in it.
    bin_ = (120.0, 100.0, 180.0, 140.0)
    shelf = (227.56, 28.65, 317.56, 48.65)
    check("two things sitting diagonally apart are not ordered either way",
          iso.behind(bin_, shelf) == 0 and iso.behind(shelf, bin_) == 0,
          f"{iso.behind(bin_, shelf)} and {iso.behind(shelf, bin_)}")
    check("and that is right, because their screen columns do not touch",
          max(iso.project(x, y).x() for x in bin_[::2] for y in bin_[1::2])
          <= min(iso.project(x, y).x() for x in shelf[::2]
                 for y in shelf[1::2]))

    # -- the relation, on its own terms -------------------------------------
    # Antisymmetry is what stops a cycle forming between two things, and
    # checking it by hand on chosen pairs would only find the cases already
    # thought of. Every footprint on a small grid, every pair, no exceptions.
    grid = [(x, y, x + w, y + h) for x in range(4) for y in range(4)
            for w in range(4) for h in range(4)]
    broken_pairs = sum(1 for a in grid for b in grid
                       if iso.behind(a, b) != -iso.behind(b, a))
    check(f"over all {len(grid)} footprints on a grid, A behind B always "
          f"means B is not behind A",
          broken_pairs == 0, f"{broken_pairs} pairs disagree with themselves")

    # And then the same grid for rings of three, which is the shape the sort
    # cannot resolve. Exhaustive: every triple, not a sample of them.
    following = {a: [b for b in grid if b != a and iso.behind(a, b) < 0]
                 for a in grid}
    rings = 0
    for a in grid:
        for b in following[a]:
            for c in following[b]:
                if c != a and a in following[c]:
                    rings += 1
    check("and no three of them form a ring", rings == 0, f"{rings} rings")

    # The sort keeps its cycle branch anyway, because "none found" is not
    # "none exists". What it must never do is lose a piece, so it gets the
    # nastiest scenes there are: two things in the same place, a wall with no
    # size at all, and something covering everything.
    awkward = [((10, 10, 50, 50), "same 1"), ((10, 10, 50, 50), "same 2"),
               ((30, 30, 30, 30), "a point"), ((0, 0, 100, 100), "everything")]
    check("degenerate pieces all come back, once each",
          sorted(name for _, name in iso.paint_order(awkward))
          == ["a point", "everything", "same 1", "same 2"],
          str([name for _, name in iso.paint_order(awkward)]))

    check("ordering nothing gives back nothing", iso.paint_order([]) == [])
    one = [(iso.box_footprint(1, 2, 3, 4), "only")]
    check("ordering one thing gives back that thing",
          iso.paint_order(one) == one)

    # -- the same order twice, because two programs draw this room ----------
    # paint_order breaks ties by position in the list, so it has to walk the
    # list in the order it was handed over every time. The browser port makes
    # the same picture out of the same room, and a drawing order that shuffles
    # between runs would make that impossible to check.
    points = models.circle_points(400, 300)
    boxes = placed(points, [(0, 30, 70, 240), (250, 0, 90, 20),
                            (120, 100, 60, 40), (300, 200, 50, 50)])
    pieces, _ = scene(points, boxes)
    runs = {tuple(name for _, name in iso.paint_order(list(pieces)))
            for _ in range(50)}
    check("the same room gives the same order every single time",
          len(runs) == 1, f"{len(runs)} different orders came out")

    # -- and the widget itself, which is what any of this was for -----------
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPointF, Qt
    application = QApplication.instance() or QApplication([])

    import room_view_3d

    room = models.Room(id="r1", name="Round", points=models.circle_points(400, 300))
    room.containers = []
    for n, (x, y, w, h) in enumerate(boxes):
        room.containers.append(models.Container(
            id=f"c{n}", name=f"Box {n}", x=x, y=y, w=w, h=h, height=60))
    floor = models.Floor(id="f1", name="Ground")
    floor.rooms = [room]
    profile = models.Profile(id="p1", name="Check")
    profile.floors = [floor]

    view = room_view_3d.RoomView3D()
    view.resize(900, 700)
    view.set_room(profile, room)

    layers = view._layers()
    names = {id(c): c.name for c in room.containers}
    order = [(f"wall {n}" if kind == "wall" else names[id(thing)])
             for n, (_, kind, thing) in enumerate(layers)]
    footprint_of = {}
    for n, (footprint, kind, thing) in enumerate(layers):
        footprint_of[f"wall {n}" if kind == "wall" else names[id(thing)]] = footprint

    check("the 3D view draws the round room in a workable order",
          not out_of_order(order, footprint_of),
          "; ".join(out_of_order(order, footprint_of)[:3]))
    check("and it has every wall and every container in it",
          len([k for _, k, _ in layers if k == "box"]) == len(room.containers),
          f"{len([k for _, k, _ in layers if k == 'box'])} boxes of "
          f"{len(room.containers)}")

    # Clicking has to agree with drawing, which is why they come from the same
    # method. Where two boxes overlap on screen the one drawn LAST is the one
    # on top, so that is the one a click has to find. Walk the whole widget
    # and check it everywhere rather than at a point somebody chose.
    boxes_in_order = [thing for _, kind, thing in layers if kind == "box"]
    disagreements = 0
    looked_at = 0
    for wx in range(20, view.width(), 17):
        for wy in range(20, view.height(), 17):
            point = QPointF(wx, wy)
            hit = view.container_at(point)
            under = [c for c in boxes_in_order
                     if view._silhouette(c).containsPoint(point, Qt.OddEvenFill)]
            if not under:
                continue
            looked_at += 1
            if hit is not under[-1]:
                disagreements += 1
    check("a click finds the container that was drawn on top of the others",
          disagreements == 0 and looked_at > 0,
          f"{disagreements} of {looked_at} positions picked a box that "
          f"something else had been painted over")
    print(f"        (checked {looked_at} positions that had a box under them)")

    view.deleteLater()

    print()
    if FAILED:
        print(f"{len(FAILED)} of {len(PASSED) + len(FAILED)} FAILED")
        return 1
    print(f"all {len(PASSED)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

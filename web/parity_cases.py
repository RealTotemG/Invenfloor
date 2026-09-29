"""Generate a pile of cases, answer them with models.py, write them to JSON.

The JavaScript port then answers the same cases and the two are compared. A
port that agrees with the original on thousands of cases is a port. One that
passes tests written for it afterwards is a hope: the same misunderstanding
that produced the code produces the test.

Run from the project root:

    python web/parity_cases.py > web/parity_cases.json
"""
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models as M

# iso.py and theme.py both import PySide6. Only their arithmetic is asked
# about here, no window is opened and no QApplication is created, so this runs
# headless wherever the app itself would run.
#
# It is optional anyway. models.py needs nothing but the standard library, and
# a machine that has not installed the app's requirements should still be able
# to check the half of the port that does not care. The JavaScript side is
# told which half it got and says so out loud, because a harness that quietly
# skips work and prints "all agreed" is worse than one that fails.
try:
    import iso as I
    import theme
    HAVE_QT = True
except ImportError:
    I = theme = None
    HAVE_QT = False


def shapes():
    """Every preset, plus hand-built awkward ones, plus random polygons."""
    made = [
        ("rectangle", M.rectangle_points(400, 300)),
        ("square", M.square_points(260)),
        ("triangle", M.triangle_points(380, 290)),
        ("circle", M.circle_points(400, 300)),
        ("L", M.l_shape_points(400, 300)),
        ("thin L", M.l_shape_points(400, 300, 340, 250)),
        # The fireplace. A divot small enough to hide inside a container,
        # which is the case that found conditions 3 and 4.
        ("divot", [[0, 0], [400, 0], [400, 300], [230, 300],
                   [230, 250], [170, 250], [170, 300], [0, 300]]),
        # A spike narrow enough to cross a rectangle without either end
        # being inside it, which is what condition 2 is for.
        ("spike", [[0, 0], [400, 0], [400, 300], [205, 300],
                   [200, 60], [195, 300], [0, 300]]),
        ("tiny", M.rectangle_points(25, 25)),
        ("sliver", M.rectangle_points(400, 22)),
        ("negative origin", [[-200, -150], [200, -150], [200, 150], [-200, 150]]),
    ]
    rng = random.Random(20260927)
    for n in range(8):
        count = rng.randint(3, 9)
        points = []
        for step in range(count):
            angle = math.tau * step / count
            reach = rng.uniform(60, 220)
            points.append([round(reach * math.cos(angle), 3),
                           round(reach * math.sin(angle), 3)])
        made.append((f"random {n}", points))
    return made


def rectangles(rng):
    """Positions and sizes to try, including ones landing exactly on walls."""
    out = []
    for _ in range(26):
        out.append((round(rng.uniform(-260, 420), 2), round(rng.uniform(-220, 360), 2),
                    round(rng.uniform(15, 260), 2), round(rng.uniform(15, 220), 2)))
    # Flush against the obvious edges, and exactly over the divot.
    out += [(0, 0, 100, 80), (0, 0, 400, 300), (170, 250, 60, 50),
            (160, 240, 80, 70), (300, 0, 100, 300), (-5, -5, 50, 50),
            (0, 0, 20, 20), (380, 280, 20, 20)]
    return out


def main():
    rng = random.Random(1)
    cases = {"contains": [], "fit": [], "nearest": [], "point": [],
             "cross": [], "height": [], "name": [], "migrate": [], "shapes": []}

    for label, points in shapes():
        room = M.Room(points=[list(p) for p in points])
        cases["shapes"].append({"label": label, "points": points,
                                "bounds": list(room.bounds()),
                                "center": list(room.center())})

        for (x, y, w, h) in rectangles(rng):
            cases["contains"].append({
                "points": points, "rect": [x, y, w, h],
                "answer": M.room_contains_rect(room, x, y, w, h)})

            cases["fit"].append({
                "points": points, "rect": [x, y, w, h], "stay": None,
                "answer": list(M.fit_in_room(room, x, y, w, h))})

            stay = [10, 10, 40, 40]
            cases["fit"].append({
                "points": points, "rect": [x, y, w, h], "stay": stay,
                "answer": list(M.fit_in_room(room, x, y, w, h, tuple(stay)))})

            cases["nearest"].append({
                "points": points, "rect": [x, y, w, h],
                "answer": list(M.nearest_fit(room, x, y, w, h))})

        for _ in range(30):
            px, py = round(rng.uniform(-260, 430), 2), round(rng.uniform(-220, 360), 2)
            cases["point"].append({"points": points, "p": [px, py],
                                   "answer": M.point_in_polygon(points, px, py)})
        # And every corner, which is the on-the-line case.
        for px, py in points:
            cases["point"].append({"points": points, "p": [px, py],
                                   "answer": M.point_in_polygon(points, px, py)})

    # Reshaping a room: adding a corner, dropping one, and stretching the
    # whole thing. These are what the floor plan canvas does, and every one of
    # them edits the points list in place, which is exactly the kind of code
    # that is easy to port with an off-by-one nobody sees until a room goes
    # inside out.
    cases["reshape"] = []
    for label, points in shapes():
        for (px, py) in [(0, 0), (200, 150), (-40, 30), (400, 300), (123.5, 77.25)]:
            room = M.Room(points=[list(p) for p in points])
            at = room.insert_point_on_nearest_edge(px, py)
            cases["reshape"].append({
                "label": f"{label} insert at {px},{py}", "points": points,
                "op": "insert", "arg": [px, py],
                "answer": {"index": at, "points": room.points}})

        for index in [0, 1, 2, len(points) - 1, len(points), -1, 99]:
            room = M.Room(points=[list(p) for p in points])
            ok = room.remove_point(index)
            cases["reshape"].append({
                "label": f"{label} remove {index}", "points": points,
                "op": "remove", "arg": index,
                "answer": {"ok": ok, "points": room.points}})

        for (w, h, ax, ay) in [(200, 150, None, None), (800, 60, None, None),
                               (100, 100, 0, 0), (250, 250, -50, 25),
                               (0, 0, None, None), (400, 300, None, None)]:
            room = M.Room(points=[list(p) for p in points])
            room.resize_to(w, h, ax, ay)
            cases["reshape"].append({
                "label": f"{label} resize to {w}x{h} at {ax},{ay}",
                "points": points, "op": "resize", "arg": [w, h, ax, ay],
                "answer": {"points": room.points}})

    for _ in range(400):
        quad = [[round(rng.uniform(-100, 100), 2), round(rng.uniform(-100, 100), 2)]
                for _ in range(4)]
        cases["cross"].append({
            "segments": quad,
            "answer": M.segments_cross(tuple(quad[0]), tuple(quad[1]),
                                       tuple(quad[2]), tuple(quad[3]))})

    for value in [0, 6, 7.5, 15, 22.4, 22.5, 22.6, 30, 40, 50, 62.5, 75, 120,
                  200, -10, 1e9, -1e9, "30", " 30 ", "30abc", "1e2", "",
                  "  ", "oops", "inf", "-inf", "Infinity", "nan", "NaN",
                  None, True, False, [], {}, "0x10", "1_0"]:
        try:
            nearest = M.nearest_height(value)
            named = M.height_name(value) if isinstance(value, (int, float)) else None
            clamped = M.clamp_height(value)
        except (TypeError, ValueError):
            continue
        cases["height"].append({"value": value, "nearest": nearest,
                                "name": named, "clamped": clamped})

    names = ["Kitchen", "  spaced   out  ", "", "x" * 60, "Garage",
             "Upstairs hallway closet", "a", "ends with space   "]
    for name in names:
        cases["name"].append({
            "value": name,
            "clean": M.clean_name(name),
            "short": M.short(name),
            "short8": M.short(name, 8),
            "copy": M.copy_name(name or "Untitled", []),
            "copy2": M.copy_name(name or "Untitled",
                                 [M.copy_name(name or "Untitled", [])]),
        })

    # Save files, old and new, through the migration.
    for schema, height in [(1, 60), (1, 150), (1, 30), (2, 60), (None, 60),
                           (1, None), (1, "oops"), (2, 150)]:
        container = {"id": "c1", "name": "Shelf", "x": 0, "y": 0, "w": 60, "h": 40}
        if height is not None:
            container["height"] = height
        raw = {"id": "p1", "name": "Home", "color": "#4f7cff",
               "floors": [{"id": "f1", "name": "Ground", "rooms": [
                   {"id": "r1", "name": "Garage",
                    "points": M.rectangle_points(400, 300),
                    "containers": [container]}]}]}
        if schema is not None:
            raw["schema"] = schema
        before = json.loads(json.dumps(raw))
        after = M.migrate(json.loads(json.dumps(raw)))
        cases["migrate"].append({"raw": before, "answer": after})

    # A full round trip: does to_dict of from_dict come back identical?
    profile = M.Profile(id="p9", name="Round trip", color="#33d6a0")
    floor = M.Floor(id="f9", name="Ground", color="#4f7cff")
    room = M.Room(id="r9", name="Garage", color="#33d6a0", x=5, y=7,
                  points=M.l_shape_points(400, 300), locked=True,
                  tag_ids=["t1"])
    room.containers = [M.Container(id="c9", name="Shelf", color="#f0a726",
                                   x=10, y=10, w=70, h=40, height=50,
                                   tier_count=3, tag_ids=["t1"])]
    floor.rooms = [room]
    profile.floors = [floor]
    profile.tags = [M.Tag(id="t1", name="Tools", color="#f0a726")]
    profile.items = [M.Item(id="i1", name="Sockets", color="#5b85ff",
                            notes="hex", min_quantity=4,
                            created_at="2026-01-01T00:00:00",
                            updated_at="2026-02-02T00:00:00",
                            tag_ids=["t1"],
                            placements=[M.Placement("c9", 3, 1),
                                        M.Placement("c9", 2, 2)])]
    cases["roundtrip"] = {"dict": profile.to_dict(),
                          "reloaded": M.Profile.from_dict(
                              json.loads(json.dumps(profile.to_dict()))).to_dict()}

    profile_cases(cases)

    # The old single-container item format.
    cases["olditem"] = []
    for raw in [{"id": "i2", "name": "Old", "container_id": "cX", "quantity": 7},
                {"id": "i3", "name": "Loose", "quantity": 4},
                {"id": "i4", "name": "Broken", "placements": [
                    {"container_id": "", "quantity": 2},
                    {"container_id": "cY", "quantity": 5, "tier": -3}]}]:
        cases["olditem"].append({"raw": raw,
                                 "answer": M.Item.from_dict(
                                     json.loads(json.dumps(raw))).to_dict()})

    if HAVE_QT:
        iso_cases(cases, rng)
    else:
        print("PySide6 is not installed here, so the projection and the "
              "palette are not covered.\n"
              "  pip install -r requirements.txt", file=sys.stderr)

    total = sum(len(v) for v in cases.values() if isinstance(v, list))
    print(json.dumps(cases), file=sys.stdout)
    print(f"{total} cases", file=sys.stderr)


def a_house():
    """A profile with enough going on to ask real questions of.

    Two floors, four rooms, tagged rooms and tagged items, something on two
    tiers of one shelf, something in two rooms at once, something unfiled,
    something below its par level, and something tagged for a room it is not
    in. Every one of those is a branch in the methods below.
    """
    profile = M.Profile(id="p1", name="House", color="#4f7cff")
    tools = M.Tag(id="t-tools", name="Tools", color="#f0a726")
    food = M.Tag(id="t-food", name="Food", color="#84cc16")
    profile.tags = [tools, food]

    ground = M.Floor(id="f1", name="Ground")
    upstairs = M.Floor(id="f2", name="Upstairs")

    garage = M.Room(id="r1", name="Garage", points=M.l_shape_points(420, 320),
                    tag_ids=["t-tools"])
    garage.containers = [
        M.Container(id="c1", name="Racking", x=10, y=10, w=150, h=45,
                    height=100, tier_count=4, tag_ids=["t-tools"]),
        M.Container(id="c2", name="Bench", x=10, y=240, w=190, h=60, height=40),
    ]
    kitchen = M.Room(id="r2", name="Kitchen", x=480,
                     points=M.rectangle_points(340, 260), tag_ids=["t-food"])
    kitchen.containers = [
        M.Container(id="c3", name="Pantry", x=20, y=20, w=120, h=50,
                    height=120, tier_count=3),
    ]
    empty = M.Room(id="r3", name="Empty", y=400, points=M.rectangle_points(100, 100))
    closet = M.Room(id="r4", name="Closet", points=M.rectangle_points(180, 140))
    closet.containers = [
        M.Container(id="c4", name="Top shelf", x=15, y=15, w=140, h=40,
                    height=75, tier_count=2),
    ]

    ground.rooms = [garage, kitchen, empty]
    upstairs.rooms = [closet]
    profile.floors = [ground, upstairs]

    def item(item_id, name, places, **rest):
        made = M.Item(id=item_id, name=name,
                      created_at=f"2026-01-{int(item_id[1:]):02d}T00:00:00",
                      **rest)
        made.placements = [M.Placement(*place) for place in places]
        return made

    profile.items = [
        # On two tiers of the same shelf, which is what contents_of is for.
        item("i1", "Sockets", [("c1", 4, 1), ("c1", 2, 3)], tag_ids=["t-tools"]),
        # In two rooms at once.
        item("i2", "Tape", [("c1", 1, 0), ("c3", 2, 0)], tag_ids=["t-tools"]),
        # Tagged Food, kept in the Garage, and some room carries Food. Misfiled.
        item("i3", "Tinned beans", [("c1", 6, 2)], tag_ids=["t-food"]),
        # Below its par level.
        item("i4", "Screws", [("c2", 3, 0)], min_quantity=10, tag_ids=["t-tools"]),
        # Nowhere at all.
        item("i5", "Beach umbrella", []),
        # Pointing at a container that does not exist any more, AND tagged.
        # This is the one misfiled_items has to skip: its placements list is
        # not empty, but none of them lead anywhere, so it is not sitting in
        # the wrong room, it is sitting nowhere. A mutation that dropped that
        # guard went unnoticed until this item was tagged.
        item("i6", "Ghost", [("c-gone", 2, 0)], tag_ids=["t-food"]),
        # Unfiled and tagged, which is the same trap from the other side.
        item("i9", "Still in the car", [], tag_ids=["t-tools"]),
        # On a tier past the end of its container, which set_tier_count makes.
        item("i7", "Bulbs", [("c4", 5, 2)]),
        # Tagged for a room it IS in, so not misfiled.
        item("i8", "Pasta", [("c3", 9, 1)], tag_ids=["t-food"]),
    ]
    return profile


def profile_cases(cases):
    """Everything Profile can be asked or told, answered by the Python.

    Objects come out as ids and names rather than whole records: what is being
    compared is which thing was picked, not a second copy of to_dict, which is
    already checked to death above.
    """
    def named(thing):
        return None if thing is None else [thing.id, thing.name]

    def places(found):
        return [[named(floor), named(room), named(box), quantity, tier]
                for floor, room, box, quantity, tier in found]

    profile = a_house()
    cases["profile"] = {
        "dict": profile.to_dict(),
        "tags_for": [profile.tags_for(ids) and [t.id for t in profile.tags_for(ids)]
                     for ids in [[], ["t-tools"], ["t-food", "t-tools"],
                                 ["t-gone"], ["t-tools", "t-gone"]]],
        "find_container": {box: [named(part) for part in profile.find_container(box)]
                           for box in ["c1", "c3", "c4", "c-gone", ""]},
        "find_room": {room: [named(part) for part in profile.find_room(room)]
                      for room in ["r1", "r4", "r-gone"]},
        "container_path": {box: profile.container_path(box)
                           for box in ["c1", "c3", "c4", "c-gone"]},
        "locations_of": {item.id: places(profile.locations_of(item))
                         for item in profile.items},
        "location_of": {item.id: profile.location_of(item) for item in profile.items},
        "contents_of": {box: [[i.id, q, t] for i, q, t in profile.contents_of(box)]
                        for box in ["c1", "c2", "c3", "c4", "c-gone"]},
        "contents_of_tier": [[box, tier,
                              [[i.id, q, t] for i, q, t in profile.contents_of(box, tier)]]
                             for box in ["c1", "c4"] for tier in [0, 1, 2, 3, 9]],
        "item_count_in_container": {box: profile.item_count_in_container(box)
                                    for box in ["c1", "c2", "c3", "c4", "c-gone"]},
        "items_in_room": {room.id: [i.id for i in profile.items_in_room(room)]
                          for floor in profile.floors for room in floor.rooms},
        "unfiled_items": [i.id for i in profile.unfiled_items()],
        "low_items": [i.id for i in profile.low_items()],
        "items_with_tag": {tag: [i.id for i in profile.items_with_tag(tag)]
                           for tag in ["t-tools", "t-food", "t-gone"]},
        "rooms_with_tag": {tag: [[named(f), named(r)]
                                 for f, r in profile.rooms_with_tag(tag)]
                           for tag in ["t-tools", "t-food", "t-gone"]},
        "misfiled_items": [[i.id, named(tag), [r.id for r in rooms]]
                           for i, tag, rooms in profile.misfiled_items()],
        "recent_items": [i.id for i in profile.recent_items()],
        "recent_items_3": [i.id for i in profile.recent_items(3)],
        "floor_index": [profile.floor_index(f) for f in profile.floors]
                       + [profile.floor_index(M.Floor(id="nope"))],
    }

    # The mutations, each from a fresh house so one cannot see the last one's
    # leftovers. The whole profile comes back, because what matters about a
    # delete is as much what it did NOT touch.
    cases["profile_changes"] = []

    def change(label, apply):
        fresh = a_house()
        apply(fresh)
        cases["profile_changes"].append({"label": label, "answer": fresh.to_dict()})

    def find(profile, item_id):
        return next(i for i in profile.items if i.id == item_id)

    change("set_placement new", lambda p: p.set_placement(find(p, "i5"), "c2", 3, 1))
    change("set_placement update", lambda p: p.set_placement(find(p, "i1"), "c1", 9, 1))
    change("set_placement other tier",
           lambda p: p.set_placement(find(p, "i1"), "c1", 7, 2))
    change("set_placement zero removes",
           lambda p: p.set_placement(find(p, "i1"), "c1", 0, 1))
    change("set_placement negative removes",
           lambda p: p.set_placement(find(p, "i4"), "c2", -5, 0))
    change("set_placement zero on nothing",
           lambda p: p.set_placement(find(p, "i5"), "c1", 0, 0))

    change("move_to_tier part",
           lambda p: p.move_to_tier(find(p, "i3"), "c1", 2, 1, 2))
    change("move_to_tier all",
           lambda p: p.move_to_tier(find(p, "i3"), "c1", 2, 1, 6))
    change("move_to_tier more than there is",
           lambda p: p.move_to_tier(find(p, "i3"), "c1", 2, 1, 99))
    change("move_to_tier onto an occupied one",
           lambda p: p.move_to_tier(find(p, "i1"), "c1", 3, 1, 2))
    change("move_to_tier to loose",
           lambda p: p.move_to_tier(find(p, "i1"), "c1", 1, 0, 4))
    change("move_to_tier nowhere",
           lambda p: p.move_to_tier(find(p, "i1"), "c1", 1, 1, 2))
    change("move_to_tier from an empty tier",
           lambda p: p.move_to_tier(find(p, "i1"), "c1", 2, 1, 1))
    change("move_to_tier zero",
           lambda p: p.move_to_tier(find(p, "i1"), "c1", 1, 2, 0))

    change("set_tier_count up",
           lambda p: p.set_tier_count(p.floors[0].rooms[0].containers[0], 6))
    change("set_tier_count down",
           lambda p: p.set_tier_count(p.floors[0].rooms[0].containers[0], 2))
    change("set_tier_count to none",
           lambda p: p.set_tier_count(p.floors[0].rooms[0].containers[0], 0))
    change("set_tier_count negative",
           lambda p: p.set_tier_count(p.floors[1].rooms[0].containers[0], -3))

    change("delete_tag", lambda p: p.delete_tag("t-tools"))
    change("delete_tag that is not there", lambda p: p.delete_tag("t-gone"))
    change("delete_container", lambda p: p.delete_container("c1"))
    change("delete_container that is not there", lambda p: p.delete_container("c-gone"))
    change("delete_room", lambda p: p.delete_room("r1"))
    change("delete_room with nothing in it", lambda p: p.delete_room("r3"))
    change("delete_floor", lambda p: p.delete_floor("f1"))
    change("delete_floor the last one", lambda p: p.delete_floor("f2"))


def point(qpoint):
    return [qpoint.x(), qpoint.y()]


def shape(qpolygon):
    return [point(qpolygon.at(at)) for at in range(qpolygon.count())]


def rect(qrect):
    return [qrect.x(), qrect.y(), qrect.width(), qrect.height()]


def draw_order(corners, walls):
    """The scene room_view_3d.py paints, named piece by piece, back to front.

    Six boxes and the room's far walls, ordered by iso.paint_order, reported as
    a list of names. Names rather than coordinates because the names are what
    the two programs have to agree on: the same pieces, in the same sequence.

    The boxes go through nearest_fit, the way every path that moves a container
    does, so they land inside the room instead of lying across a wall. That is
    not to make the check easy. It is the only arrangement that can occur, and
    holding the code to a scene it can never be given proves nothing.
    """
    # Named by index, not by coordinates. A wall at x 10 prints as "10" in
    # JavaScript and "10.0" in Python, and a name that disagrees would fail
    # this check for a reason that has nothing to do with the draw order. The
    # two lists of walls are already known to match: far_walls is checked
    # against its own case just above.
    things = [(I.wall_footprint(wall), f"wall {n}")
              for n, wall in enumerate(walls)]

    x0 = min(px for px, _ in corners)
    y0 = min(py for _, py in corners)
    room = M.Room(id="r", name="r", points=[list(c) for c in corners])
    for n in range(6):
        x, y, w, h = M.nearest_fit(room, x0 + n * 37, y0 + ((n * 53) % 140),
                                   40 + n * 9, 30)
        things.append((I.box_footprint(x, y, w, h), f"box {n}"))

    return [name for _, name in I.paint_order(things)]


def iso_cases(cases, rng):
    """The projection, the wall culling and the draw order.

    Same idea as everything above: the Python answers, the JavaScript answers,
    and any disagreement is a bug in one of them. This half matters as much as
    the model half, because getting a sign wrong here does not throw. It draws
    a room inside out, which is the kind of thing that survives review and gets
    noticed on a screenshot a week later.
    """
    from PySide6.QtCore import QPointF

    cases["project"] = []
    for _ in range(300):
        x = round(rng.uniform(-400, 400), 3)
        y = round(rng.uniform(-400, 400), 3)
        z = round(rng.uniform(0, 160), 3)
        cases["project"].append({"xyz": [x, y, z], "answer": point(I.project(x, y, z))})

    cases["floor_at"] = []
    for _ in range(300):
        sx = round(rng.uniform(-500, 500), 3)
        sy = round(rng.uniform(-500, 500), 3)
        cases["floor_at"].append(
            {"screen": [sx, sy], "answer": point(I.floor_at(QPointF(sx, sy)))})

    cases["faces"] = []
    for _ in range(120):
        x = round(rng.uniform(-200, 300), 2)
        y = round(rng.uniform(-200, 300), 2)
        w = round(rng.uniform(20, 180), 2)
        d = round(rng.uniform(20, 180), 2)
        h = round(rng.uniform(0, 120), 2)
        cases["faces"].append({
            "box": [x, y, w, d, h],
            "top": shape(I.top_face(x, y, w, d, h)),
            "left": shape(I.left_face(x, y, w, d, h)),
            "right": shape(I.right_face(x, y, w, d, h)),
            "outline": shape(I.box_outline(x, y, w, d, h)),
            "footprint": list(I.box_footprint(x, y, w, d)),
        })
    # A flat box, where box_outline takes its other branch.
    cases["faces"].append({
        "box": [10, 20, 40, 30, 0],
        "top": shape(I.top_face(10, 20, 40, 30, 0)),
        "left": shape(I.left_face(10, 20, 40, 30, 0)),
        "right": shape(I.right_face(10, 20, 40, 30, 0)),
        "outline": shape(I.box_outline(10, 20, 40, 30, 0)),
        "footprint": list(I.box_footprint(10, 20, 40, 30)),
    })

    # Which rooms are sitting on top of each other. Every arrangement two
    # rooms can be in, named, because the ones that must NOT report as
    # overlapping are the whole difficulty: neighbours share a wall, and a
    # warning that fires on a correctly drawn plan is one nobody reads.
    cases["overlap"] = []

    def placed(name, points, x=0, y=0):
        room = M.Room(id=name, name=name, points=[list(p) for p in points])
        room.x = x
        room.y = y
        return room

    square = M.rectangle_points(100, 100)
    ell = M.l_shape_points(200, 200)
    for label, first, second in [
        ("half on top of each other", placed("a", square), placed("b", square, 50)),
        ("well apart", placed("a", square), placed("b", square, 200)),
        ("one wholly inside the other",
         placed("a", square), placed("b", M.rectangle_points(20, 20), 10, 10)),
        ("neighbours sharing a wall", placed("a", square), placed("b", square, 100)),
        ("neighbours sharing a wall, stacked",
         placed("a", square), placed("b", square, 0, 100)),
        ("exactly on top of each other", placed("a", square), placed("b", square)),
        ("touching at a single corner",
         placed("a", square), placed("b", square, 100, 100)),
        ("one unit apart", placed("a", square), placed("b", square, 101)),
        ("a square over an L's body",
         placed("a", ell), placed("b", M.rectangle_points(60, 60), 10, 10)),
        ("a square in an L's notch",
         placed("a", ell), placed("b", M.rectangle_points(60, 60), 130, 10)),
        ("a room with too few corners",
         placed("a", square), placed("b", [(0, 0), (10, 0)])),
    ]:
        cases["overlap"].append({
            "label": label,
            "first": {"points": [list(p) for p in first.points],
                      "x": first.x, "y": first.y},
            "second": {"points": [list(p) for p in second.points],
                       "x": second.x, "y": second.y},
            "outline": [list(p) for p in M.room_outline(first)],
            "answer": M.rooms_overlap(first, second),
            "both_ways": M.rooms_overlap(second, first),
        })

    cases["walls"] = []
    for label, points in shapes():
        # Every room turned every way up. Winding depends on the order the
        # corners were listed in, and half of these presets go one way and half
        # the other, so reversing each one doubles the coverage of the branch
        # that has already been wrong twice.
        for turned, listing in (("as listed", points), ("reversed", points[::-1])):
            corners = [tuple(p) for p in listing]
            walls = I.far_walls(corners)
            cases["walls"].append({
                "label": f"{label} {turned}",
                "points": [list(p) for p in listing],
                "winding": I.winding(corners),
                "far": [[list(a), list(b)] for a, b in walls],
                "footprints": [list(I.wall_footprint(w)) for w in walls],
                "depths": [I.footprint_depth(I.wall_footprint(w)) for w in walls],
                # Twice: once with nothing in the room, once with something
                # taller than the walls, which is the case that used to crop
                # the top off a full-height cabinet.
                "bounds_empty": rect(I.room_bounds(corners, I.WALL_HEIGHT, 0.0)),
                "bounds_tall": rect(I.room_bounds(corners, I.WALL_HEIGHT, 90.0)),
                "order": draw_order(corners, walls),
            })

    cases["color"] = []
    for base in ["#4f7cff", "#33d6a0", "#f0a726", "#000000", "#ffffff", "#7a1b2c"]:
        for amount in [0.0, 0.05, 0.26, 0.5, 0.74, 1.0, -0.16, -0.32]:
            cases["color"].append({
                "hex": base, "amount": amount,
                "mix_white": theme.mix(base, "#ffffff", abs(amount)),
                "mix_black": theme.mix(base, "#000000", abs(amount)),
            })

    # The palette itself, name by name. theme.js has to write these values out
    # a second time, because a browser cannot read a Python file and there is
    # no build step to generate one. What this stops is the second copy
    # quietly drifting: nobody notices a hex digit, and six months later the
    # two programs are slightly different shades of the same app.
    cases["palette"] = {name: getattr(theme, name) for name in [
        "BG_APP", "BG_SIDEBAR", "BG_PANEL", "BG_CARD", "BG_INPUT", "BG_HOVER",
        "BG_ACTIVE", "BORDER", "BORDER_LIGHT", "TEXT", "TEXT_MUTED",
        "TEXT_FAINT", "ACCENT", "ACCENT_HOVER", "ACCENT_SOFT", "DANGER",
        "DANGER_HOVER", "SUCCESS", "WARNING", "CANVAS_BG", "GRID_MINOR",
        "GRID_MAJOR", "CANVAS_ORIGIN", "SWATCHES", "SPACE_XS", "SPACE_SM",
        "SPACE_MD", "SPACE_LG", "SPACE_XL", "RADIUS_SM", "RADIUS_MD",
        "RADIUS_LG", "FONT_SIZE", "FONT_SIZE_SM", "FONT_SIZE_LG",
        "FONT_SIZE_XL", "GRID_SIZE", "GRID_MAJOR_EVERY",
    ]}

    # And the two numbers in iso.py that decide how a room looks. A wall
    # height that differs between the programs is not a bug anything would
    # throw on; it just means the browser draws a different room.
    cases["iso_constants"] = {
        "WALL_HEIGHT": I.WALL_HEIGHT,
        "TOP_LIGHT": I.TOP_LIGHT,
        "LEFT_LIGHT": I.LEFT_LIGHT,
        "RIGHT_LIGHT": I.RIGHT_LIGHT,
    }


if __name__ == "__main__":
    main()

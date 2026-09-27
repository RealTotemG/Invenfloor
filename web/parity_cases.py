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

    total = sum(len(v) for v in cases.values() if isinstance(v, list))
    print(json.dumps(cases), file=sys.stdout)
    print(f"{total} cases", file=sys.stderr)


if __name__ == "__main__":
    main()

"""
models.py
=========

The shape of the data. No windows, no buttons -- just what a profile, floor,
room, container, item and tag ARE.

Keeping this separate matters more as an app grows: you can answer "what does
a room actually consist of?" by reading one short file, and you can change how
something is stored without hunting through screen code.

THE HIERARCHY
-------------

    Profile                  "Home", "Work Locker" -- a whole separate world
      |- floors[]            ordered bottom to top: index 0 is the lowest
      |    |- rooms[]        polygons you draw on the floor
      |         |- containers[]   drawers, cabinets, shelves inside a room
      |- tags[]              the tag vocabulary for this profile
      |- items[]            <- a FLAT list. See below.

WHY ITEMS ARE A FLAT LIST
-------------------------
Items live in containers, and only in containers -- that rule holds. But
rather than storing each item physically inside its container, every item
carries a list of PLACEMENTS saying where its copies are.

The reason is the items screen. If items were nested, listing every item in a
profile would mean four nested loops (floors, then rooms, then containers,
then items) every time you searched. With a flat list it is one loop.

ONE ITEM, SEVERAL PLACES
------------------------
Towels live in the bathroom AND the kitchen, in different numbers. So an item
does not have a single location and a single quantity. It has a list:

    Item("Towels", placements=[
        Placement(container_id="kitchen drawer", quantity=6),
        Placement(container_id="bathroom shelf", quantity=8),
    ])

There is still exactly ONE "Towels" item in the catalog -- one name, one
color, one set of tags -- and its 14 towels are split across two places. That
is the thing worth getting right: duplicating the item would mean renaming or
retagging it twice and having the two copies drift apart.

An item with an empty placements list is "unfiled": you own it, but you have
not said where it lives. That is a normal state, not an error -- it lets you
catalog a box of things quickly and sort out where they go afterward.

ABOUT COORDINATES
-----------------
Rooms are positioned on the floor by (x, y), and their polygon `points` are
measured from that origin rather than from the corner of the floor. So moving
a room means changing x and y only -- the shape itself never has to be
recalculated.

Containers work the same way one level down: their x/y are measured from their
room's origin, so a container automatically travels with its room.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


def now_stamp():
    """The current date and time as text, e.g. "2026-09-11T14:05:32".

    Stored as a string rather than a datetime object so it drops straight into
    JSON with no conversion. ISO format sorts correctly as plain text, which
    means "newest first" is just a normal sort -- no date parsing needed.
    """
    return datetime.now().isoformat(timespec="seconds")


def new_id():
    """A short unique id, e.g. "a3f9c1d2".

    uuid4() generates a random 128-bit value; taking the first 8 hex
    characters is far more than enough to stay unique for a personal app, and
    it keeps the save file readable.
    """
    return uuid4().hex[:8]


# ---------------------------------------------------------------------------
# NAMES
# ---------------------------------------------------------------------------
#
# Two different limits, because they answer two different questions.
#
# NAME_MAX_LENGTH is what you are allowed to type. It exists to stop a name
# running on forever, which is easy to do by accident when you paste something
# in, and which used to push labels clean off the side of a room.
#
# NAME_DISPLAY_LENGTH is what fits on screen. Rooms, chips and list rows are
# narrow, and a name that is legal to store is not automatically a name that
# fits in a 90 pixel box. Anything longer gets cut with an ellipsis, and the
# full name is still there in the tooltip and in the box you edit it in.
#
# Keeping them separate means "Upstairs hallway closet" is a perfectly good
# name to have, it just shows as "Upstairs hallway c…" on the floor plan.

NAME_MAX_LENGTH = 40
NAME_DISPLAY_LENGTH = 20


def clean_name(text, fallback="Untitled"):
    """Tidy up a name a person typed, and cap its length.

    Runs of whitespace collapse to one space, so a stray double space or a
    pasted line break does not survive into the save file. An empty result
    falls back rather than leaving something nameless on the floor plan.

    Every path that accepts a typed name goes through here, including the
    search box, so there is no way in that skips the cap.
    """
    text = " ".join(str(text).split())
    return text[:NAME_MAX_LENGTH].strip() or fallback


def short(text, limit=NAME_DISPLAY_LENGTH):
    """The on-screen form of a name: at most `limit` characters.

    The ellipsis counts toward the limit rather than being added on top, so
    `limit` really is the widest this can ever be. That matters because the
    whole point is fitting a known amount of space.
    """
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# COPYING
# ---------------------------------------------------------------------------

def copy_name(original, taken):
    """"Kitchen" becomes "Kitchen copy", then "Kitchen copy 2", and so on.

    `taken` is every name already in use alongside this one. Duplicating the
    same room five times should give five tellable-apart names rather than
    five things all called "Kitchen copy".

    The result respects the same length cap as a typed name, so a duplicate of
    a name that is already at the limit does not quietly exceed it.
    """
    taken = {str(name).strip().lower() for name in taken}

    attempt = 1
    while True:
        suffix = " copy" if attempt == 1 else f" copy {attempt}"
        # Trim the ORIGINAL, not the suffix, so the part that makes the name
        # unique is the part that always survives.
        room_for_base = NAME_MAX_LENGTH - len(suffix)
        candidate = original.strip()[:room_for_base].strip() + suffix
        if candidate.lower() not in taken:
            return candidate
        attempt += 1


def duplicate(thing, name=None):
    """A deep copy of a room or a container, with brand new ids.

    Works by writing the thing out as a dictionary and reading it back, which
    is the same round trip that saving and loading already does. That is the
    point: there is no second copy of "what a room consists of" to keep in
    step, so a field added to to_dict is duplicated from the day it exists.

    Nothing inside a container comes along. Items live in the catalog and say
    which containers they are in, so a duplicated shelf is a shelf of the same
    size, color and tiers, standing empty. Copying the contents too would mean
    claiming you own twice as many shoes as you do.
    """
    made = type(thing).from_dict(thing.to_dict())
    made.id = new_id()

    for container in getattr(made, "containers", []):
        container.id = new_id()

    if name is not None:
        made.name = name
    return made


def duplicate_floor(floor, name=None):
    """A deep copy of a floor, with every room and container inside it new.

    Same round trip as duplicate() above, one level up: new ids all the way
    down so nothing in the copy points at anything in the original.
    """
    made = Floor.from_dict(floor.to_dict())
    made.id = new_id()

    for room in made.rooms:
        room.id = new_id()
        for container in room.containers:
            container.id = new_id()

    if name is not None:
        made.name = name
    return made


# ---------------------------------------------------------------------------
# TAG
# ---------------------------------------------------------------------------

@dataclass
class Tag:
    """A label you can attach to items, rooms and containers.

    Tags are what let you ask "where is anything to do with camping?" and get
    an answer that spans several rooms.
    """
    id: str = field(default_factory=new_id)
    name: str = "New tag"
    color: str = "#4f7cff"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "color": self.color}

    @staticmethod
    def from_dict(raw):
        # .get() with a fallback everywhere means an older or hand-edited save
        # file with a missing field loads instead of crashing.
        return Tag(
            id=raw.get("id", new_id()),
            name=raw.get("name", "Untitled"),
            color=raw.get("color", "#4f7cff"),
        )


# ---------------------------------------------------------------------------
# PLACEMENT
# ---------------------------------------------------------------------------

@dataclass
class Placement:
    """"This many of this item, in this container, on this tier."

    A tiny class, but giving it a name is what makes the rest of the app
    readable: "item.placements" says what it is far better than a dictionary
    of container ids to numbers would.

    `tier` is 0 for "just in the container", and 1, 2, 3... for a shelf with
    tiers. Zero rather than None because it is a number either way and there
    is no arithmetic to guard: tier 0 sorts first, which is where loose things
    belong in a list.

    The same item CAN appear twice in one container on different tiers. Shoes
    on tier 1 and shoes on tier 3 are two honest facts, so nothing stops you
    recording both.
    """
    container_id: str
    quantity: int = 1
    tier: int = 0

    def to_dict(self):
        return {"container_id": self.container_id, "quantity": self.quantity,
                "tier": self.tier}

    @staticmethod
    def from_dict(raw):
        return Placement(
            container_id=raw.get("container_id"),
            quantity=raw.get("quantity", 1),
            # Saved before tiers existed means no tier, which is exactly what
            # zero means.
            tier=max(int(raw.get("tier", 0)), 0),
        )


# ---------------------------------------------------------------------------
# ITEM
# ---------------------------------------------------------------------------

@dataclass
class Item:
    """One thing you own, possibly kept in more than one place."""
    id: str = field(default_factory=new_id)
    name: str = "New item"
    color: str = "#94a3b8"
    notes: str = ""
    placements: list = field(default_factory=list)
    unfiled_quantity: int = 1
    tag_ids: list = field(default_factory=list)

    # Par level: warn when the total drops below this. Zero means "no level
    # set", which is why it is zero rather than None -- it keeps the spin box
    # in the dialog simple, with 0 displayed as "off".
    min_quantity: int = 0

    created_at: str = field(default_factory=now_stamp)
    updated_at: str = field(default_factory=now_stamp)

    def touch(self):
        """Mark this item as changed just now."""
        self.updated_at = now_stamp()

    def is_low(self):
        """Below its par level. False when no level has been set."""
        return self.min_quantity > 0 and self.total_quantity() < self.min_quantity

    def total_quantity(self):
        """How many you own altogether.

        Once an item has places, the quantity lives in those places and this
        just adds them up. Before that it has nowhere to live, which is what
        `unfiled_quantity` is for: it lets you write down "24 tent pegs" while
        standing over the box, before you have drawn a single room. The moment
        you give the item a place, the per-place numbers take over.
        """
        if self.placements:
            return sum(p.quantity for p in self.placements)
        return self.unfiled_quantity

    def placement_in(self, container_id, tier=None):
        """The placement in one container, or None.

        `tier=None` means "on any tier", which is what you want when asking
        "is this in that drawer at all". Pass a number to mean that tier
        exactly, including 0 for the untiered part of the container.
        """
        for placement in self.placements:
            if placement.container_id != container_id:
                continue
            if tier is None or placement.tier == tier:
                return placement
        return None

    def placements_in(self, container_id):
        """Every placement in one container, one per tier it is kept on."""
        return [p for p in self.placements if p.container_id == container_id]

    def is_unfiled(self):
        return len(self.placements) == 0

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "notes": self.notes,
            "placements": [p.to_dict() for p in self.placements],
            "unfiled_quantity": self.unfiled_quantity,
            "tag_ids": list(self.tag_ids),
            "min_quantity": self.min_quantity,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(raw):
        """Build an Item from saved data, old format or new.

        Earlier versions stored a single "container_id" and a single
        "quantity". Rather than making you convert your save files by hand, we
        detect the old shape and turn it into a one-entry placements list.

        Doing the conversion here, in one place, is why nothing else in the
        app has to know two formats ever existed.
        """
        if "placements" in raw:
            placements = [Placement.from_dict(p) for p in raw["placements"]]
        else:
            # Old format.
            placements = []
            old_container = raw.get("container_id")
            if old_container:
                placements = [Placement(old_container, raw.get("quantity", 1))]

        # Drop any placement that lost its container id along the way.
        placements = [p for p in placements if p.container_id]

        # An old unfiled item still knew how many there were, so keep that
        # number rather than quietly throwing it away during the upgrade.
        unfiled = raw.get("unfiled_quantity", raw.get("quantity", 1))

        return Item(
            id=raw.get("id", new_id()),
            name=raw.get("name", "Untitled"),
            color=raw.get("color", "#94a3b8"),
            notes=raw.get("notes", ""),
            placements=placements,
            unfiled_quantity=max(int(unfiled), 0),
            tag_ids=list(raw.get("tag_ids", [])),
            min_quantity=max(int(raw.get("min_quantity", 0)), 0),
            # Items saved before timestamps existed get one now. Slightly
            # wrong, but a plausible date beats an empty field everywhere it
            # is displayed or sorted on.
            created_at=raw.get("created_at") or now_stamp(),
            updated_at=raw.get("updated_at") or raw.get("created_at") or now_stamp(),
        )


# ---------------------------------------------------------------------------
# CONTAINER
# ---------------------------------------------------------------------------

@dataclass
class Container:
    """A drawer, cabinet, shelf or bin sitting inside a room.

    x/y are measured from the room's origin, so the container moves with its
    room automatically. w/h are its size in the same units.
    """
    id: str = field(default_factory=new_id)
    name: str = "New container"
    color: str = "#f0a726"
    x: float = 0.0
    y: float = 0.0
    w: float = 80.0
    h: float = 60.0
    tag_ids: list = field(default_factory=list)

    # How many tiers this container is divided into. Zero means it is just a
    # box, which is the right default: most drawers are not shelves. A three
    # tier shelf sets this to 3 and its items can then say which tier they
    # are on.
    #
    # Deliberately just a count. Tiers are not named or colored, because a
    # shelf's tiers do not have names, they have positions.
    tier_count: int = 0

    def tiers(self):
        """1, 2, 3... for a tiered container. Empty for a plain one."""
        return range(1, self.tier_count + 1)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "color": self.color,
            "x": self.x, "y": self.y, "w": self.w, "h": self.h,
            "tag_ids": list(self.tag_ids),
            "tier_count": self.tier_count,
        }

    @staticmethod
    def from_dict(raw):
        return Container(
            id=raw.get("id", new_id()),
            name=raw.get("name", "Untitled"),
            color=raw.get("color", "#f0a726"),
            x=raw.get("x", 0.0), y=raw.get("y", 0.0),
            w=raw.get("w", 80.0), h=raw.get("h", 60.0),
            tag_ids=list(raw.get("tag_ids", [])),
            # No key means a plain box, which is what every container was
            # before tiers existed.
            tier_count=max(int(raw.get("tier_count", 0)), 0),
        )


def closest_point_on_segment(ax, ay, bx, by, px, py):
    """The point on the line segment A-B nearest to P, and how far away it is.

    Used to work out which wall you clicked on when adding a corner. The math
    is a projection: how far along A-B does P land, clamped to the ends so the
    answer is always somewhere on the actual segment rather than out on the
    infinite line it sits on.
    """
    dx = bx - ax
    dy = by - ay

    if dx == 0 and dy == 0:
        return ax, ay, math.hypot(px - ax, py - ay)

    along = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    along = max(0.0, min(1.0, along))       # clamp to the segment

    cx = ax + along * dx
    cy = ay + along * dy
    return cx, cy, math.hypot(px - cx, py - cy)


# ---------------------------------------------------------------------------
# ROOM
# ---------------------------------------------------------------------------

@dataclass
class Room:
    """A polygon on a floor.

    `points` is a list of [x, y] pairs describing the outline, measured from
    the room's own origin. Three points is the minimum that encloses an area.

    Preset shapes (below) are just convenient ways to fill in `points` --
    once created, a circle is an ordinary polygon like any other and can be
    reshaped point by point.
    """
    id: str = field(default_factory=new_id)
    name: str = "New room"
    color: str = "#4f7cff"
    x: float = 0.0
    y: float = 0.0
    points: list = field(default_factory=list)
    tag_ids: list = field(default_factory=list)
    containers: list = field(default_factory=list)

    # "I am done arranging this one." A locked room cannot be dragged,
    # resized or reshaped, and shows no handles. Everything else still
    # works: rename it, recolor it, tag it, fill it with containers. The
    # lock is about the floor plan being settled, not about the room being
    # read-only.
    locked: bool = False

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "color": self.color,
            "x": self.x, "y": self.y,
            "points": [[px, py] for px, py in self.points],
            "tag_ids": list(self.tag_ids),
            "locked": self.locked,
            "containers": [c.to_dict() for c in self.containers],
        }

    @staticmethod
    def from_dict(raw):
        return Room(
            id=raw.get("id", new_id()),
            name=raw.get("name", "Untitled"),
            color=raw.get("color", "#4f7cff"),
            x=raw.get("x", 0.0), y=raw.get("y", 0.0),
            points=[list(p) for p in raw.get("points", [])],
            tag_ids=list(raw.get("tag_ids", [])),
            # Save files written before locks existed have no such key, and
            # an unlocked room is the right thing for them to become.
            locked=bool(raw.get("locked", False)),
            containers=[Container.from_dict(c) for c in raw.get("containers", [])],
        )

    def center(self):
        """The middle of the polygon, in room-local coordinates."""
        if not self.points:
            return (0.0, 0.0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)

    def bounds(self):
        """(left, top, width, height) of the polygon, in room-local units."""
        if not self.points:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def insert_point_on_nearest_edge(self, x, y):
        """Add a corner on whichever edge is closest to (x, y).

        The new corner is placed ON the edge rather than at the exact spot you
        clicked, so the outline does not change shape the instant you add it.
        You add a corner, then drag it where you want. Dropping it at the raw
        click point would put a dent in the wall before you had asked for one.

        Returns the index of the new point, so the caller can select it.
        """
        if len(self.points) < 2:
            return None

        best_index = 0
        best_distance = None
        best_point = None
        count = len(self.points)

        for index in range(count):
            ax, ay = self.points[index]
            bx, by = self.points[(index + 1) % count]
            cx, cy, distance = closest_point_on_segment(ax, ay, bx, by, x, y)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = index
                best_point = (cx, cy)

        self.points.insert(best_index + 1, [best_point[0], best_point[1]])
        return best_index + 1

    def remove_point(self, index):
        """Delete one corner. Refuses below three, which is the minimum that
        still encloses an area."""
        if len(self.points) <= 3:
            return False
        if not (0 <= index < len(self.points)):
            return False

        del self.points[index]
        return True

    def resize_to(self, new_width, new_height, anchor_left=None, anchor_top=None):
        """Stretch the whole room to a new width and height.

        Every point is moved in proportion, so the shape is preserved: stretch
        a circle and you get an oval, stretch an L and the notch stays where
        it should be. This is what the corner handles on a selected room do.

        `anchor_left` / `anchor_top` say where the new bounding box should
        start; leave them out to keep the current top-left corner still.
        """
        left, top, width, height = self.bounds()
        if width <= 0 or height <= 0:
            return

        if anchor_left is None:
            anchor_left = left
        if anchor_top is None:
            anchor_top = top

        scale_x = new_width / width
        scale_y = new_height / height

        for point in self.points:
            point[0] = anchor_left + (point[0] - left) * scale_x
            point[1] = anchor_top + (point[1] - top) * scale_y


# ---------------------------------------------------------------------------
# PRESET ROOM SHAPES
# ---------------------------------------------------------------------------
# Each returns a list of [x, y] points ready to use as Room.points, with the
# top-left corner of the shape at (0, 0).
#
# These are starting points, not permanent types. Once a room exists, every
# one of these is just a polygon, and you can drag any corner of it.

def rectangle_points(width, height):
    """A plain four-corner rectangle."""
    return [[0, 0], [width, 0], [width, height], [0, height]]


def square_points(size):
    return rectangle_points(size, size)


def triangle_points(width, height):
    """A triangle with its apex centered along the top edge."""
    return [[width / 2, 0], [width, height], [0, height]]


def circle_points(width, height, segments=20):
    """A circle (or oval) approximated by a many-sided polygon.

    A canvas polygon cannot be a true curve, so we walk all the way around
    once and place a point every few degrees. Twenty segments reads clearly as
    a circle on screen without leaving so many corner handles that the shape
    becomes fiddly to edit.

    math.tau is one full turn in radians (2 x pi) -- using it here means the
    loop reads as "this fraction of the way around", which is exactly what it
    is.
    """
    radius_x = width / 2
    radius_y = height / 2
    points = []

    for step in range(segments):
        angle = math.tau * step / segments
        # +radius shifts the circle so its bounding box starts at (0, 0),
        # matching every other preset.
        points.append([
            radius_x + radius_x * math.cos(angle),
            radius_y + radius_y * math.sin(angle),
        ])

    return points


def l_shape_points(width, height, notch_width=None, notch_height=None):
    """An L. The notch is cut out of the top-right by default."""
    if notch_width is None:
        notch_width = width * 0.45
    if notch_height is None:
        notch_height = height * 0.45

    return [
        [0, 0],
        [width - notch_width, 0],
        [width - notch_width, notch_height],
        [width, notch_height],
        [width, height],
        [0, height],
    ]


# Offered in the toolbar's shape menu. Each entry is (label, builder), where
# the builder takes a width and a height. Add your own here and it appears in
# the menu -- nothing else needs changing.
ROOM_PRESETS = [
    ("Rectangle", lambda w, h: rectangle_points(w, h)),
    ("Square", lambda w, h: square_points(min(w, h))),
    ("Circle", lambda w, h: circle_points(w, h)),
    ("Triangle", lambda w, h: triangle_points(w, h)),
    ("L-shape", lambda w, h: l_shape_points(w, h)),
]


# ---------------------------------------------------------------------------
# FLOOR
# ---------------------------------------------------------------------------

@dataclass
class Floor:
    """One level of a building. Holds the rooms drawn on it.

    A floor has no explicit "level number" -- its position in the profile's
    floors list IS its height. Index 0 is the lowest floor, and the last index
    is the highest. Adding a basement means inserting at position 0.
    """
    id: str = field(default_factory=new_id)
    name: str = "New floor"
    color: str = "#4f7cff"
    rooms: list = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "color": self.color,
            "rooms": [r.to_dict() for r in self.rooms],
        }

    @staticmethod
    def from_dict(raw):
        return Floor(
            id=raw.get("id", new_id()),
            name=raw.get("name", "Untitled"),
            color=raw.get("color", "#4f7cff"),
            rooms=[Room.from_dict(r) for r in raw.get("rooms", [])],
        )


# ---------------------------------------------------------------------------
# PROFILE
# ---------------------------------------------------------------------------

@dataclass
class Profile:
    """A whole separate inventory: its own floors, its own tags, its own items.

    Nothing is shared between profiles. "Home" and "Work Locker" can both have
    a tag called Tools and a room called Storage without interfering.
    """
    id: str = field(default_factory=new_id)
    name: str = "New profile"
    color: str = "#4f7cff"
    floors: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    items: list = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "color": self.color,
            "floors": [f.to_dict() for f in self.floors],
            "tags": [t.to_dict() for t in self.tags],
            "items": [i.to_dict() for i in self.items],
        }

    @staticmethod
    def from_dict(raw):
        return Profile(
            id=raw.get("id", new_id()),
            name=raw.get("name", "Untitled"),
            color=raw.get("color", "#4f7cff"),
            floors=[Floor.from_dict(f) for f in raw.get("floors", [])],
            tags=[Tag.from_dict(t) for t in raw.get("tags", [])],
            items=[Item.from_dict(i) for i in raw.get("items", [])],
        )

    # -- looking things up --------------------------------------------------
    # These exist so the screens never have to write their own nested loops.
    # If you find yourself writing "for floor in profile.floors: for room in
    # ..." inside a screen, there is probably a helper for it here already.

    def tag_by_id(self, tag_id):
        for tag in self.tags:
            if tag.id == tag_id:
                return tag
        return None

    def tags_for(self, tag_ids):
        """Turn a list of tag ids into a list of real Tag objects.

        Ids that no longer exist are skipped, so deleting a tag can never
        leave a room or item pointing at nothing.
        """
        found = []
        for tag_id in tag_ids:
            tag = self.tag_by_id(tag_id)
            if tag is not None:
                found.append(tag)
        return found

    def iter_containers(self):
        """Walk every container in the profile.

        Yields (floor, room, container) so callers know the full path without
        having to look it back up. `yield` hands back one result at a time
        instead of building a whole list first.
        """
        for floor in self.floors:
            for room in floor.rooms:
                for container in room.containers:
                    yield floor, room, container

    def find_container(self, container_id):
        """Return (floor, room, container), or (None, None, None) if missing."""
        for floor, room, container in self.iter_containers():
            if container.id == container_id:
                return floor, room, container
        return None, None, None

    def find_room(self, room_id):
        for floor in self.floors:
            for room in floor.rooms:
                if room.id == room_id:
                    return floor, room
        return None, None

    def container_path(self, container_id):
        """"Ground Floor / Kitchen / Top Drawer", or None if it's gone."""
        floor, room, container = self.find_container(container_id)
        if container is None:
            return None
        return f"{floor.name} / {room.name} / {container.name}"

    # -- where an item is ---------------------------------------------------

    def locations_of(self, item):
        """Every place this item is kept.

        Returns a list of (floor, room, container, quantity, tier). Placements
        whose container has been deleted are skipped, so this can be shorter
        than item.placements.
        """
        found = []
        for placement in item.placements:
            floor, room, container = self.find_container(placement.container_id)
            if container is not None:
                found.append((floor, room, container, placement.quantity,
                              placement.tier))
        return found

    def location_of(self, item):
        """A short, human-readable summary of where an item lives.

        One place gets the full path; several get a count, because listing
        three full paths on one row is unreadable. The Items screen expands to
        show the detail.
        """
        places = self.locations_of(item)
        if not places:
            return "Unfiled"
        if len(places) == 1:
            floor, room, container, _, tier = places[0]
            tail = f" · Tier {tier}" if tier else ""
            return f"{floor.name} / {room.name} / {container.name}{tail}"
        return f"{len(places)} places"

    def contents_of(self, container_id, tier=None):
        """What is in one container, as a list of (item, quantity, tier).

        One row per PLACEMENT, not per item, because an item can sit on two
        tiers of the same shelf and both are worth showing. Sorted by tier so
        anything loose in the container comes first, then tier 1 downward.

        `tier=None` asks for everything. Pass a number for one tier only,
        including 0 for the part of the container that has no tier.
        """
        found = []
        for item in self.items:
            for placement in item.placements_in(container_id):
                if tier is None or placement.tier == tier:
                    found.append((item, placement.quantity, placement.tier))
        found.sort(key=lambda row: (row[2], row[0].name.lower()))
        return found

    def item_count_in_container(self, container_id):
        """How many DIFFERENT items are in a container (not how many units).

        Counted by item, so a thing kept on two tiers of the same shelf is
        still one thing in that shelf.
        """
        return len({item.id for item, _, _ in self.contents_of(container_id)})

    def items_in_room(self, room):
        """Every distinct item with at least one placement in this room.

        An item kept in two drawers of the same room is counted once -- the
        question this answers is "what's in here", not "how many boxes".
        """
        container_ids = {c.id for c in room.containers}
        found = []
        for item in self.items:
            if any(p.container_id in container_ids for p in item.placements):
                found.append(item)
        return found

    def unfiled_items(self):
        return [i for i in self.items if i.is_unfiled()]

    def low_items(self):
        """Everything below its par level."""
        return [i for i in self.items if i.is_low()]

    def misfiled_items(self):
        """Items sitting somewhere their own tags say they shouldn't be.

        This is the payoff for tagging both items and rooms. A tag on an ITEM
        says what the thing is; the same tag on a ROOM says what belongs
        there. So if an item is tagged Tools, some room is tagged Tools, and
        the item is in NONE of those rooms -- it is probably in the wrong
        place.

        Two deliberate exclusions:

          - If no room carries the tag at all, there is no expectation to
            break, so there is nothing to report.
          - Unfiled items are not misfiled. They are not anywhere yet, which
            is a different problem with its own view.

        Returns a list of (item, tag, expected_rooms) so the screen can say
        exactly why each entry is listed.
        """
        reports = []

        for item in self.items:
            places = self.locations_of(item)
            if not places:
                continue

            rooms_it_is_in = [room for _, room, _, _, _ in places]

            for tag_id in item.tag_ids:
                expected = [room for _, room in self.rooms_with_tag(tag_id)]
                if not expected:
                    continue

                if not any(tag_id in room.tag_ids for room in rooms_it_is_in):
                    reports.append((item, self.tag_by_id(tag_id), expected))

        return reports

    def recent_items(self, limit=None):
        """Newest first. ISO timestamps sort correctly as plain strings."""
        ordered = sorted(self.items, key=lambda i: i.created_at, reverse=True)
        return ordered[:limit] if limit else ordered

    def items_with_tag(self, tag_id):
        return [i for i in self.items if tag_id in i.tag_ids]

    def rooms_with_tag(self, tag_id):
        """Which rooms carry this tag. Yields (floor, room) pairs.

        This is the other half of the tag idea: a tag on an ITEM says what the
        thing is, and the same tag on a ROOM says where things like that are
        supposed to live. Comparing the two is how you spot something filed in
        the wrong place.
        """
        for floor in self.floors:
            for room in floor.rooms:
                if tag_id in room.tag_ids:
                    yield floor, room

    # -- changing things ----------------------------------------------------

    def set_placement(self, item, container_id, quantity, tier=0):
        """Put (or update) a quantity of an item in a container, on a tier.

        A quantity of zero or less removes the placement, which is what makes
        "I've used them all up" the same gesture as "wrong drawer".

        Matches on container AND tier, so putting shoes on tier 3 does not
        overwrite the shoes already on tier 1.
        """
        existing = item.placement_in(container_id, tier)

        if quantity <= 0:
            if existing is not None:
                item.placements.remove(existing)
            return

        if existing is None:
            item.placements.append(Placement(container_id, quantity, tier))
        else:
            existing.quantity = quantity

    def move_to_tier(self, item, container_id, from_tier, to_tier, quantity):
        """Move some of an item from one tier of a container to another.

        Takes a quantity rather than moving the whole placement, because a
        shelf's whole point is that four of a thing can be on one level and two
        on another. Moving part of a stack leaves the rest where it was.

        The destination is added to, never replaced: if there are already two
        on tier 3 and you move two more there, tier 3 has four.
        """
        source = item.placement_in(container_id, from_tier)
        if source is None or to_tier == from_tier:
            return

        quantity = min(max(int(quantity), 0), source.quantity)
        if quantity <= 0:
            return

        source.quantity -= quantity
        if source.quantity <= 0:
            item.placements.remove(source)

        destination = item.placement_in(container_id, to_tier)
        if destination is None:
            item.placements.append(
                Placement(container_id, quantity, to_tier))
        else:
            destination.quantity += quantity

        item.touch()

    def set_tier_count(self, container, count):
        """Change how many tiers a container has.

        Removing tiers does not throw anything away. Items on a tier that no
        longer exists come back to the container itself, which is the honest
        answer: you still own them and they are still in that cupboard, you
        just stopped dividing it up.
        """
        count = max(int(count), 0)
        container.tier_count = count

        for item in self.items:
            for placement in item.placements_in(container.id):
                if placement.tier > count:
                    placement.tier = 0

    def delete_tag(self, tag_id):
        """Remove a tag, and strip it from everything that referenced it.

        Cleaning up references at the moment of deletion is what stops the
        save file slowly filling with ids pointing at things that no longer
        exist.
        """
        self.tags = [t for t in self.tags if t.id != tag_id]
        for item in self.items:
            if tag_id in item.tag_ids:
                item.tag_ids.remove(tag_id)
        for floor in self.floors:
            for room in floor.rooms:
                if tag_id in room.tag_ids:
                    room.tag_ids.remove(tag_id)
                for container in room.containers:
                    if tag_id in container.tag_ids:
                        container.tag_ids.remove(tag_id)

    def delete_container(self, container_id):
        """Remove a container. Items keep their other places.

        Deleting a drawer should not delete your record of the things that
        were in it -- you almost certainly still own them. An item kept only
        there simply becomes unfiled; one also kept elsewhere is untouched
        apart from losing that one placement.
        """
        for floor in self.floors:
            for room in floor.rooms:
                room.containers = [c for c in room.containers
                                   if c.id != container_id]

        for item in self.items:
            item.placements = [p for p in item.placements
                               if p.container_id != container_id]

    def delete_room(self, room_id):
        """Remove a room, and every placement inside its containers."""
        for floor in self.floors:
            for room in list(floor.rooms):
                if room.id == room_id:
                    for container in list(room.containers):
                        self.delete_container(container.id)
                    if room in floor.rooms:
                        floor.rooms.remove(room)

    def delete_floor(self, floor_id):
        for floor in list(self.floors):
            if floor.id == floor_id:
                for room in list(floor.rooms):
                    self.delete_room(room.id)
                self.floors.remove(floor)

    def floor_index(self, floor):
        """Where this floor sits in the stack. 0 is the lowest."""
        for index, candidate in enumerate(self.floors):
            if candidate.id == floor.id:
                return index
        return -1

"""
iso.py
======

The isometric projection, and everything that draws with it.

WHAT "3D" MEANS HERE
--------------------
Nothing in this app is really three dimensional. There is no 3D engine, no
camera, no depth buffer, and no extra dependency. There is one function:

    screen_x = (x - y) * cos(30)
    screen_y = (x + y) * sin(30) - z

Feed it a point on the floor and a height, and it hands back a point on the
screen. That is the whole illusion. Everything else in this file is either
drawing polygons through that function or working out what order to draw them
in.

The payoff is that it runs anywhere PySide6 runs, at the same cost as the flat
view, because it is the same kind of work: filling polygons with QPainter.

WHY THE MATH IS INVERTIBLE, AND WHY THAT MATTERS
------------------------------------------------
Drawing is only half of it. To let someone drag a container around in the 3D
view you have to go the other way: turn a point on the screen back into a
point on the floor. Two equations, two unknowns, so it solves exactly:

    x = (sx / cos(30) + sy / sin(30)) / 2
    y = (sy / sin(30) - sx / cos(30)) / 2

That is `floor_at` below. It assumes z = 0, which is true for anything sitting
on the floor, and containers always are. Without that assumption a screen
point would be ambiguous -- it could be a spot on the floor or a spot on top
of a box -- and dragging would need a real 3D pick.

DRAW ORDER
----------
Painter's algorithm: draw the far things first and let the near things paint
over them. For boxes standing on a floor, "far" is just x + y, because the
camera looks down the diagonal. This is only correct because nothing
interlocks. Two boxes that wrapped around each other would need real depth
sorting, but a drawer cannot wrap around another drawer.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPolygonF

import theme

COS30 = math.cos(math.radians(30))
SIN30 = math.sin(math.radians(30))

# How the three visible faces of a box are tinted. Positive mixes toward
# white, negative toward black. The top catching the most light is what makes
# a flat polygon read as a solid object; get rid of these and the whole
# picture collapses into a pattern. Light comes from the upper left, so the
# left face is the brighter of the two sides.
TOP_LIGHT = 0.26
LEFT_LIGHT = -0.16
RIGHT_LIGHT = -0.32

# Walls are drawn short on purpose. Full height walls stand taller than the
# furniture and hide the very thing you opened the room to look at.
WALL_HEIGHT = 34


def project(x, y, z=0.0):
    """A point on the floor, at height z, as a point on the screen."""
    return QPointF((x - y) * COS30, (x + y) * SIN30 - z)


def floor_at(point):
    """A point on the screen, back to the point on the floor under it.

    The inverse of project() with z fixed at 0. This is what makes dragging
    work: the mouse gives a screen position, and a container needs a floor
    position.
    """
    across = point.x() / COS30
    down = point.y() / SIN30
    return QPointF((across + down) / 2, (down - across) / 2)


def depth(x, y):
    """How far from the camera. Bigger is nearer, so sort ascending."""
    return x + y


def shade(hex_color, amount):
    """One face's color. Positive is lit, negative is in shadow."""
    if amount >= 0:
        return QColor(theme.mix(hex_color, "#ffffff", amount))
    return QColor(theme.mix(hex_color, "#000000", -amount))


# ---------------------------------------------------------------------------
# SHAPES
#
# Each of these returns a polygon in screen coordinates rather than drawing
# it. Keeping the shape and the painting apart means the same functions answer
# "where would this be drawn?", which is how hit testing works further down
# and in the 3D view itself.
# ---------------------------------------------------------------------------

def polygon(corners):
    """A list of (x, y, z) floor points as a screen polygon."""
    return QPolygonF([project(*corner) for corner in corners])


def top_face(x, y, w, d, height):
    return polygon([(x, y, height), (x + w, y, height),
                    (x + w, y + d, height), (x, y + d, height)])


# WHICH TWO SIDES YOU CAN ACTUALLY SEE
#
# Worth working out rather than guessing, because guessing wrong leaves a hole
# in the box that is easy to miss in a screenshot and obvious in use.
#
# A point is nearer the camera the bigger its x + y, so the nearest vertical
# edge of a box is the one at (x+w, y+d). The two faces you can see are the
# two that touch that edge:
#
#     the +y face (y = y+d, x varies)  lands on the LEFT of the screen
#     the +x face (x = x+w, y varies)  lands on the RIGHT
#
# The other two, at x and at y, face away and are never drawn. The names below
# say where a face APPEARS, not which axis it sits on, because where it appears
# is what you are looking at when something is wrong.

def left_face(x, y, w, d, height):
    """The side facing down and left on screen: the +y wall of the box."""
    return polygon([(x, y + d, 0), (x + w, y + d, 0),
                    (x + w, y + d, height), (x, y + d, height)])


def right_face(x, y, w, d, height):
    """The side facing down and right on screen: the +x wall of the box."""
    return polygon([(x + w, y + d, 0), (x + w, y, 0),
                    (x + w, y, height), (x + w, y + d, height)])


def box_outline(x, y, w, d, height):
    """The silhouette of a whole box: the six-sided shape you see on screen.

    Used for hit testing, and for drawing a halo around a selected container.
    The order walks the outside of the box, which is why the corners look
    arbitrary until you trace them on a drawing.
    """
    return polygon([
        (x, y + d, 0), (x + w, y + d, 0), (x + w, y, 0),
        (x + w, y, height), (x, y, height), (x, y + d, height),
    ]) if height > 0 else top_face(x, y, w, d, 0)


# How far the height handle floats CLEAR of the top face. The handle used to
# sit on the top face, and the top face is exactly where you reach to pick a
# box up and move it, so every attempt to drag a cabinet made it taller
# instead. A gizmo arm sticking out past the object is what Unity and Roblox
# do, for this reason.
HANDLE_CLEARANCE = 16


def handle_lift(w, d):
    """How much z to add so the handle clears the top face of a w by d box.

    The handle sits over the middle of the box, and the far corner of the top
    face draws (w + d) / 4 higher up the screen than that middle does. Work
    that out rather than picking a number: a fixed lift that looks generous on
    a small bin lands back inside the top face of a wide workbench, which is
    the bug this exists to avoid.
    """
    return (w + d) / 4 + HANDLE_CLEARANCE


def box_corners(x, y, w, d, height):
    """The four floor corners, and the height handle floating above the box.

    The resize handles hang off these, so they are named the same way the
    handles are: nw, ne, se, sw going clockwise from the far corner.
    """
    return {
        "nw": project(x, y, 0),
        "ne": project(x + w, y, 0),
        "se": project(x + w, y + d, 0),
        "sw": project(x, y + d, 0),
        "top": project(x + w / 2, y + d / 2, height + handle_lift(w, d)),
    }


# ---------------------------------------------------------------------------
# PAINTING
# ---------------------------------------------------------------------------

def fill(painter, shape, color, lift, outline=True):
    painter.setBrush(QBrush(shade(color, lift)))
    painter.setPen(QPen(shade(color, lift - 0.3), 1.2) if outline else Qt.NoPen)
    painter.drawPolygon(shape)


def draw_box(painter, x, y, w, d, height, color, tiers=0, selected=False):
    """One container as a solid box.

    Three faces, never six. From a fixed camera the back, the bottom and the
    far side can never be seen, so they are never drawn, and that is most of
    why this is cheap.
    """
    fill(painter, left_face(x, y, w, d, height), color, LEFT_LIGHT)
    fill(painter, right_face(x, y, w, d, height), color, RIGHT_LIGHT)
    fill(painter, top_face(x, y, w, d, height), color, TOP_LIGHT)

    # Tiers as shelf lines across the face you are looking at. The count is
    # already in the data, so this costs a few strokes and turns "3 tiers"
    # from a number in a panel into something you can see.
    if tiers > 1 and height > 20:
        painter.setPen(QPen(
            theme.qcolor(theme.mix(color, "#000000", 0.55), 0.7), 1.0))
        for tier in range(1, tiers):
            z = height * tier / tiers
            # One line per visible face, meeting at the near vertical edge, so
            # a shelf reads as going right round the corner of the box.
            painter.drawLine(project(x, y + d, z), project(x + w, y + d, z))
            painter.drawLine(project(x + w, y + d, z), project(x + w, y, z))

    if selected:
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(theme.ACCENT), 2.4))
        painter.drawPolygon(box_outline(x, y, w, d, height))


def winding(points):
    """+1 or -1 for which way round a polygon's corners were listed.

    Twice the signed area, reduced to its sign. Needed because the corners of
    a room are whatever order someone clicked them in, and every question of
    the form "which side of this edge is the inside?" flips with that order.
    """
    twice_area = sum(ax * by - bx * ay for (ax, ay), (bx, by)
                     in zip(points, points[1:] + points[:1]))
    return -1.0 if twice_area < 0 else 1.0


def outward_normal(ax, ay, bx, by, sense):
    """Which way an edge faces, pointing out of the room.

    For corners listed one way round the outward normal of A to B is
    (dy, -dx); listed the other way it is the opposite, which is what `sense`
    from winding() above is for. Not normalized: only the direction is ever
    asked about.
    """
    return (sense * (by - ay), sense * -(bx - ax))


def is_far_wall(ax, ay, bx, by, sense):
    """Does this wall face away from the camera, so you see its inside?

    Those are the ones to draw. A wall facing the camera would stand between
    you and the room, which is what the cutaway exists to avoid.

    The camera looks down the x + y diagonal, so "facing away" is just the
    normal's two components adding to less than zero.

    THIS USED TO COMPARE AGAINST THE MIDDLE OF THE ROOM, AND THAT WAS WRONG.
    The old test asked whether an edge's midpoint sat behind the room's
    centroid. For a rectangle that gives the right answer every time, so it
    survived a long while. For an L-shape it gets the notch exactly backwards:
    the inner wall, which faces the camera and should be cut away, sits behind
    the centroid and was drawn, while the back wall of the L's foot, which
    should be there, sits in front of it and was skipped.

    You could see both mistakes at once. A container standing against that
    inner wall was drawn over the top of it, because a wall that should not
    have been there cannot be behind anything. An edge knows which way it
    faces without being told where the middle of the room is, so now it is
    asked directly.
    """
    nx, ny = outward_normal(ax, ay, bx, by, sense)
    return nx + ny < 0


def far_walls(points):
    """The walls worth drawing: the ones facing away from the camera.

    Returned as ((ax, ay), (bx, by)) pairs so the caller can decide when each
    one is drawn, which matters because a wall is not always behind
    everything standing in the room. See draw_order below.
    """
    if len(points) < 3:
        return []
    sense = winding(points)
    return [(a, b) for a, b in zip(points, points[1:] + points[:1])
            if is_far_wall(a[0], a[1], b[0], b[1], sense)]


def draw_floor(painter, points, color):
    """The floor slab, under everything."""
    if len(points) < 3:
        return
    painter.setBrush(QBrush(QColor(theme.mix(color, theme.CANVAS_BG, 0.74))))
    painter.setPen(QPen(theme.qcolor(color, 0.9), 1.6))
    painter.drawPolygon(polygon([(px, py, 0.0) for px, py in points]))


def draw_wall(painter, a, b, color, wall_height=WALL_HEIGHT):
    (ax, ay), (bx, by) = a, b
    fill(painter, polygon([(ax, ay, 0), (bx, by, 0),
                           (bx, by, wall_height), (ax, ay, wall_height)]),
         color, -0.08)


def draw_room(painter, points, color, wall_height=WALL_HEIGHT):
    """The floor and every far wall, in one call.

    The simple version, for drawing an empty room. With containers in it the
    3D view interleaves the walls with the boxes instead, because a wall is
    not always behind them.
    """
    draw_floor(painter, points, color)
    for a, b in far_walls(points):
        draw_wall(painter, a, b, color, wall_height)


# ---------------------------------------------------------------------------
# WHERE A WALL GOES IN THE DRAW ORDER
# ---------------------------------------------------------------------------
#
# Boxes are drawn far to near by the depth of their far corner, which is the
# note at the top of this file. Walls have to go in the same ordering, and it
# is worth writing down why the same simple rule is enough for them, because
# it does not look like it should be.
#
# A wall runs the whole length of a side of a room. It is nearer the camera
# than some of what shares the room with it and further than the rest, so you
# cannot say "this wall is at depth N" and have that mean much.
#
# But the only orderings that MATTER are the ones where something is entirely
# in front of something else, because those are the ones you can see go
# wrong. And there the rule falls out:
#
#     if a wall is entirely in front of a box, then the wall's NEAR end is
#     beyond the box's near corner -- and the wall's FAR end is beyond the
#     box's far corner too, because a wall's far end is behind its near one.
#
# So sorting by the far end already puts that wall after that box. The same
# argument runs the other way for a box in front of a wall. Cases where the
# two interleave in depth have no correct answer with flat polygons anyway.
#
# Everything here describes a thing by its FOOTPRINT: the (x0, y0, x1, y1) it
# covers on the floor. A wall's footprint is flat, zero wide in one
# direction, which is fine because nothing divides by it.

def box_footprint(x, y, w, d):
    return (x, y, x + w, y + d)


def wall_footprint(wall):
    """Takes a wall the way far_walls hands them out: ((ax, ay), (bx, by))."""
    (ax, ay), (bx, by) = wall
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def footprint_depth(footprint):
    """How far the furthest corner of a footprint is from the camera."""
    return depth(footprint[0], footprint[1])


def label(painter, point, text, color, size, bold=True, width=200):
    """Text sits flat on the screen, never skewed into the projection.

    Slanting a label to match the floor looks clever in a screenshot and is
    unreadable in use, which is why isometric games keep their text upright
    too.
    """
    font = painter.font()
    font.setPixelSize(size)
    font.setBold(bold)
    painter.setFont(font)
    painter.setPen(QPen(QColor(color)))
    painter.drawText(
        QRectF(point.x() - width / 2, point.y() - size - 4, width, size + 6),
        Qt.AlignCenter, text)


# ---------------------------------------------------------------------------
# FITTING A ROOM ON SCREEN
# ---------------------------------------------------------------------------

def room_bounds(points, wall_height, tallest=0.0):
    """The screen rectangle a room and its contents occupy, unscaled.

    Needed before anything is drawn, to work out where to put the camera.
    Height matters here: a tall cabinet reaches further up the screen than
    the wall behind it, and leaving it out of the sum crops the top off it.
    """
    if not points:
        return QRectF()

    reach = max(wall_height, tallest)
    corners = []
    for px, py in points:
        corners.append(project(px, py, 0))
        corners.append(project(px, py, reach))

    xs = [c.x() for c in corners]
    ys = [c.y() for c in corners]
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

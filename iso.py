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


def draw_room(painter, points, color, wall_height=WALL_HEIGHT):
    """The floor slab, then the two walls furthest from the camera.

    Only the far walls, because the near ones would stand between you and
    everything in the room. This is the cutaway every isometric game does,
    and it is not a compromise: a room drawn with all four walls is a box you
    cannot see into.
    """
    if len(points) < 3:
        return

    floor = [(px, py, 0.0) for px, py in points]

    painter.setBrush(QBrush(QColor(theme.mix(color, theme.CANVAS_BG, 0.74))))
    painter.setPen(QPen(theme.qcolor(color, 0.9), 1.6))
    painter.drawPolygon(polygon(floor))

    middle_x = sum(px for px, _ in points) / len(points)
    middle_y = sum(py for _, py in points) / len(points)

    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        # An edge is far when its midpoint sits behind the middle of the room
        # along the camera's diagonal. The same test decides which wall to
        # draw for any shape, which is why an L-shaped room works without a
        # special case.
        toward_camera = (((ax + bx) / 2 - middle_x)
                         + ((ay + by) / 2 - middle_y))
        if toward_camera >= 0:
            continue
        fill(painter, polygon([(ax, ay, 0), (bx, by, 0),
                               (bx, by, wall_height), (ax, ay, wall_height)]),
             color, -0.08)


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

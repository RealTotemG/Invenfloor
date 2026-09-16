"""
floor_items.py
==============

The things that get drawn on the floor canvas: rooms, containers, and the
handles you drag to resize or reshape a room.

WHAT A QGraphicsItem IS
-----------------------
Qt has a scene/view system for canvases. A QGraphicsScene is a model of what
exists -- shapes, their positions, their sizes -- and a QGraphicsView is a
window looking at it. Panning and zooming happen in the view, so the scene
never has to care about them, and none of the code below deals with scroll
offsets or zoom levels. That is the main reason this app uses Qt rather than
drawing everything by hand.

Every shape in a scene is a QGraphicsItem. Qt gives you dragging, selection
and hit-testing for free; you supply two things:

    boundingRect()  - "everything I draw fits inside this rectangle"
    paint()         - actually draw me

COORDINATES
-----------
Each item has its own coordinate system, with (0, 0) at the item's own
position. Children are positioned relative to their parent.

That is doing a lot of quiet work here: containers are children of their room,
so when you drag a room across the floor, its containers follow automatically.
There is no code anywhere that moves containers when a room moves -- it simply
cannot get out of step.

THE TWO WAYS TO CHANGE A ROOM'S SHAPE
-------------------------------------
A selected room is in one of two edit modes, and they show different handles:

    Resize     square handles around the outside. Dragging one stretches the
               WHOLE room, keeping its shape -- an oval stays an oval, an L
               keeps its notch. This is what you want nine times out of ten.

    Edit shape round handles on every corner. Dragging one moves just that
               corner. This is for fixing the outline itself.

Splitting them up is deliberate. A circle is stored as a twenty-sided polygon,
and twenty round handles all over it would be unusable -- but four corner
handles to stretch it into an oval is exactly right.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsPolygonItem,
    QGraphicsRectItem,
)

import theme
from models import MIN_CONTAINER_SIZE, fit_in_room, short

# Flipped on by export.py while rendering a PDF. The room and container
# labels are near-white so they read on the dark canvas; on paper that is
# invisible, so print mode swaps them for a dark color. One flag beats
# threading a "printing" argument through every paint method.
PRINT_MODE = False

HANDLE_RADIUS = 5
SCALE_HANDLE_SIZE = 9
LABEL_MARGIN = 26        # extra room in boundingRect for text drawn above a shape
MIN_ROOM_SIZE = 40       # a room can't be squashed smaller than this

# MIN_CONTAINER_SIZE is imported from models.py, where the clamp that uses it
# lives. It is re-exported here because this is where callers expect to find
# it, and having two numbers that must agree is how they stop agreeing.

# The two edit modes described in the module docstring.
# What dragging a room MEANS right now. Exactly one of these is in force
# across the whole canvas, and every mode answers the question differently,
# which is the point of having three of them rather than a pile of flags.
#
#   Move      drag the body to reposition it. No handles.
#   Resize    square handles stretch it. The body does not move.
#   Vertices  round handles on each corner reshape it. The body does not
#             move either, so a drag across it reads as "I am working on
#             this outline" rather than "put this somewhere else".
#
# Move used to be folded into Resize, which meant one mode did two jobs and
# the other did one, and no label on screen could tell you that.
EDIT_MOVE = "move"
EDIT_RESIZE = "resize"
EDIT_VERTICES = "vertices"

# The eight resize handles, by compass point. "nw" is the top-left corner,
# "n" the middle of the top edge, and so on.
SCALE_ROLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"]

SCALE_CURSORS = {
    "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
    "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
    "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
    "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
}


def snap(value):
    """Round a coordinate to the nearest grid line.

    This is what makes rooms line up with each other instead of sitting a
    pixel or two off, the same way the Windows monitor arrangement screen
    clicks displays into place.
    """
    grid = theme.GRID_SIZE
    return round(value / grid) * grid


def snap_point(point):
    return QPointF(snap(point.x()), snap(point.y()))


def canvas_font(size, bold=False):
    font = QFont("Segoe UI")
    font.setPixelSize(size)
    font.setBold(bold)
    return font


# qcolor lives in theme.py now, next to the colors it is built from, but it
# is re-exported here because every drawing file in the project already
# reaches for floor_items.qcolor.
qcolor = theme.qcolor


# ---------------------------------------------------------------------------
# VERTEX HANDLE
# ---------------------------------------------------------------------------

class VertexHandle(QGraphicsEllipseItem):
    """One draggable corner of a room polygon.

    Handles are children of their room and appear only while that room is
    selected and in "Edit shape" mode. Each one remembers which point in
    room.points it represents, so dragging it edits that point and nothing
    else.
    """

    def __init__(self, room_item, index):
        super().__init__(-HANDLE_RADIUS, -HANDLE_RADIUS,
                         HANDLE_RADIUS * 2, HANDLE_RADIUS * 2, room_item)
        self.room_item = room_item
        self.index = index

        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(10)          # always on top of the room and containers
        self.setBrush(QBrush(QColor(theme.TEXT)))
        self.setPen(QPen(qcolor(room_item.room.color), 2))

        # Handles ignore the parent's dimming, so they stay visible and
        # grabbable even when the rest of the floor is faded back.
        self.setFlag(QGraphicsItem.ItemIgnoresParentOpacity, True)

    def itemChange(self, change, value):
        # Qt calls this whenever something about the item is about to change.
        # Returning a different value for a position change is how you modify
        # a drag while it is happening -- here, to snap it to the grid.
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            snapped = snap_point(value)

            # When the room repositions its own handles after a resize, it
            # sets this flag first. Without it we would treat the room's own
            # tidying-up as the user dragging, and the shape would slowly
            # corrupt itself every time it was resized.
            if not self.room_item.syncing:
                self.room_item.move_vertex(self.index, snapped)

            return snapped
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.room_item.commit_geometry()


# ---------------------------------------------------------------------------
# SCALE HANDLE
# ---------------------------------------------------------------------------

class ScaleHandle(QGraphicsRectItem):
    """One of the eight squares around a selected room, for resizing it.

    Unlike the vertex handles, these are NOT movable items. Qt moving them
    would fight with the room repositioning them as it resizes, so instead we
    take the mouse events ourselves, tell the room what the new edge position
    is, and let the room put every handle back where it belongs. One thing is
    in charge, which is what keeps it predictable.
    """

    def __init__(self, target, role):
        half = SCALE_HANDLE_SIZE / 2
        super().__init__(-half, -half, SCALE_HANDLE_SIZE, SCALE_HANDLE_SIZE,
                         target)
        # Whatever this handle resizes. A room or a container: both answer
        # drag_edge() and commit_geometry(), and this class does not need to
        # know which it has. One handle class, two shapes.
        self.target = target
        self.role = role

        self.setZValue(11)
        self.setCursor(SCALE_CURSORS[role])
        self.setBrush(QBrush(QColor(theme.TEXT)))
        self.setPen(QPen(qcolor(theme.ACCENT), 2))
        self.setFlag(QGraphicsItem.ItemIgnoresParentOpacity, True)
        self.setAcceptedMouseButtons(Qt.LeftButton)

    def mousePressEvent(self, event):
        # Accepting the press is what claims the mouse for this item. Without
        # it the click falls through to the room underneath and starts
        # dragging the whole room instead.
        event.accept()

    def mouseMoveEvent(self, event):
        # event.pos() is in the handle's own coordinates; mapToParent turns it
        # into the room's, which is what the room's bounds are measured in.
        point = snap_point(self.mapToParent(event.pos()))
        self.target.drag_edge(self.role, point)

    def mouseReleaseEvent(self, event):
        event.accept()
        self.target.commit_geometry()


# ---------------------------------------------------------------------------
# CONTAINER
# ---------------------------------------------------------------------------

class ContainerItem(QGraphicsRectItem):
    """A drawer, cabinet or shelf, drawn inside its room.

    Only draggable while its room is focused (double-clicked). That is what
    stops you nudging a drawer out of place while you are trying to move the
    whole room.
    """

    def __init__(self, container, room_item, profile):
        super().__init__(0, 0, container.w, container.h, room_item)
        self.container = container
        self.room_item = room_item
        self.profile = profile

        self.setPos(container.x, container.y)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(2)

        self.editable = False
        self.scale_handles = [ScaleHandle(self, role) for role in SCALE_ROLES]
        self._position_handles()

        self.set_editable(False)

        # Pulsed on and off by the view when you ask "where is this?" from the
        # Items screen. Selection alone is too quiet to catch the eye on a
        # busy floor.
        self.highlighted = False

    # -- what a drag means right now -----------------------------------------

    def set_editable(self, editable):
        """Told by the room whether we are working inside it."""
        self.editable = editable
        self.refresh_interaction()

    def refresh_interaction(self):
        """Decide in ONE place what this container responds to.

        Containers follow the same Move / Resize switch rooms do, so the same
        drag never means two things. Edit shape is about a room's outline and
        a container has no outline to edit, so it leaves containers alone.

        The two modes ask for different things, and it is worth being clear
        why they differ rather than looking inconsistent:

          Resize  works straight away, focused or not. Resize holds rooms
                  still anyway, so there is no drag on the floor plan for a
                  container to steal. Making you double-click into the room
                  first was pure ceremony: you could already type the numbers
                  into the inspector from anywhere.

          Move    still needs you working inside the room. Here a drag DOES
                  mean something else -- move the whole room -- and a drawer
                  quietly coming along for the ride is exactly the accident
                  focus mode exists to prevent.
        """
        mode = self.room_item.edit_mode
        can_move = self.editable and mode == EDIT_MOVE
        can_resize = mode == EDIT_RESIZE

        self.setFlag(QGraphicsItem.ItemIsMovable, can_move)
        self.setCursor(Qt.SizeAllCursor if can_move else Qt.ArrowCursor)
        self.setAcceptedMouseButtons(
            Qt.LeftButton if (can_move or can_resize) else Qt.NoButton)

        showing = can_resize and self.isSelected()
        for handle in self.scale_handles:
            handle.setVisible(showing)

    def _position_handles(self):
        """Put the eight handles back on the container's edges."""
        left, top = 0.0, 0.0
        right, bottom = self.container.w, self.container.h
        middle_x = (left + right) / 2
        middle_y = (top + bottom) / 2
        places = {
            "nw": (left, top), "n": (middle_x, top), "ne": (right, top),
            "e": (right, middle_y), "se": (right, bottom),
            "s": (middle_x, bottom), "sw": (left, bottom),
            "w": (left, middle_y),
        }
        for handle in self.scale_handles:
            handle.setPos(*places[handle.role])

    # -- resizing ------------------------------------------------------------

    def drag_edge(self, role, point):
        """A handle was dragged: move that edge and leave the rest alone.

        `point` arrives in this container's own coordinates, where the box
        always starts at (0, 0). The opposite edge stays put, which is what
        makes a corner handle pivot around the corner across from it.
        """
        left, top = 0.0, 0.0
        right, bottom = self.container.w, self.container.h

        if "w" in role:
            left = min(point.x(), right - MIN_CONTAINER_SIZE)
        if "e" in role:
            right = max(point.x(), left + MIN_CONTAINER_SIZE)
        if "n" in role:
            top = min(point.y(), bottom - MIN_CONTAINER_SIZE)
        if "s" in role:
            bottom = max(point.y(), top + MIN_CONTAINER_SIZE)

        self.resize_to(self.pos().x() + left, self.pos().y() + top,
                       right - left, bottom - top)

    def resize_to(self, x, y, width, height):
        """Move and resize in room coordinates, clamped inside the room.

        Used by the resize handles, the inspector's W and H boxes, and the
        Add container tool, so every route clamps through the one function in
        models.py and none of them can disagree about what fits.
        """
        x, y, width, height = fit_in_room(
            self.room_item.room, x, y, width, height,
            stay=(self.container.x, self.container.y,
                  self.container.w, self.container.h))

        self.container.x = x
        self.container.y = y
        self.container.w = width
        self.container.h = height

        self.prepareGeometryChange()
        self.setRect(0, 0, width, height)
        # setPos would come back through itemChange and clamp again, which is
        # harmless but does the work twice. The values above are already
        # inside the room.
        self.setPos(x, y)
        self._position_handles()
        self.update()

        self.room_item.editor.notify_container_resized(self.container)

    def commit_geometry(self):
        """Called when a resize handle is let go. The size is already in the
        model, so this just asks for a save."""
        self.room_item.editor.notify_changed()

    def sync_from_model(self):
        """Put this box back where its container says it is.

        The 3D view writes straight to the model, so this is how the flat
        canvas finds out. Position changes are applied with geometry
        notifications turned off: itemChange snaps to the grid and clamps,
        which is exactly right while someone is dragging and exactly wrong
        here, where the model is already the answer and re-snapping it would
        leave the two views a few units apart.
        """
        if (self.rect().width(), self.rect().height()) != (self.container.w,
                                                           self.container.h):
            self.prepareGeometryChange()
            self.setRect(0, 0, self.container.w, self.container.h)
            self._position_handles()

        if (self.pos().x(), self.pos().y()) != (self.container.x,
                                                self.container.y):
            self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
            self.setPos(self.container.x, self.container.y)
            self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedChange:
            # Qt has not applied the new value yet, so use what it is about
            # to become rather than what isSelected() still reports.
            showing = bool(value) and self.room_item.edit_mode == EDIT_RESIZE
            for handle in self.scale_handles:
                handle.setVisible(showing)

        if change == QGraphicsItem.ItemPositionChange and self.scene():
            # Snap to the grid first, then let the shared clamp decide where
            # that lands. Dragging is the fourth caller of fit_in_room and
            # gets the same answer as the other three.
            point = snap_point(value)
            # Where the item is right now, not where the model says it is.
            # The model is only written on release, so mid-drag it still
            # holds the position the drag started from -- and refusing back
            # to THAT would yank the box across the room on the first step
            # that does not fit. self.pos() is the last position that did.
            x, y, _, _ = fit_in_room(
                self.room_item.room, point.x(), point.y(),
                self.container.w, self.container.h,
                stay=(self.pos().x(), self.pos().y(),
                      self.container.w, self.container.h))
            return QPointF(x, y)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.container.x = self.pos().x()
        self.container.y = self.pos().y()
        self.room_item.editor.notify_changed()

    def boundingRect(self):
        return super().boundingRect().adjusted(-1, -1, 1, 1)

    def paint(self, painter, option, widget=None):
        """Draw the container: a soft filled rectangle with its name inside.

        We never call the base class's paint(), so Qt's default dashed
        selection box never appears -- selection is shown by drawing a
        brighter border instead, which looks a great deal tidier.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        color = self.container.color
        focused = self.room_item.focused
        selected = self.isSelected()

        fill_alpha = 0.42 if focused else 0.26
        if selected:
            fill_alpha = 0.55

        rect = QRectF(0, 0, self.container.w, self.container.h)
        path = QPainterPath()
        path.addRoundedRect(rect, 5, 5)

        painter.fillPath(path, QBrush(qcolor(color, fill_alpha)))

        pen = QPen(qcolor(color, 1.0 if (selected or focused) else 0.75))
        pen.setWidthF(2.0 if selected else 1.2)
        if self.highlighted:
            pen = QPen(QColor(theme.TEXT))
            pen.setWidthF(3.5)
        painter.setPen(pen)
        painter.drawPath(path)

        # Name, and how many items are inside, as one block centered in the
        # box. Centering matters more than it sounds: a tall cupboard with its
        # name pinned to the top and its count pinned to the bottom reads as
        # two unrelated labels rather than one thing.
        if self.container.w < 46 or self.container.h < 24:
            return      # too small to label without it turning to mush

        count = self.profile.item_count_in_container(self.container.id)
        has_room_for_count = self.container.h >= 40

        middle = rect.center().y()
        text_left = rect.left() + 3
        text_width = rect.width() - 6

        if has_room_for_count:
            name_rect = QRectF(text_left, middle - 15, text_width, 15)
            count_rect = QRectF(text_left, middle + 1, text_width, 13)
        else:
            name_rect = QRectF(text_left, middle - 8, text_width, 16)
            count_rect = None

        font = canvas_font(11, bold=True)
        painter.setFont(font)
        painter.setPen(QPen(qcolor(color, 1.0)))

        # Two cuts, and they catch different things. short() enforces the
        # app-wide 20 character rule, then elidedText fits whatever is left
        # into this particular box, which may be much narrower than 20
        # characters of this font. A small drawer needs both.
        name = QFontMetricsF(font).elidedText(
            short(self.container.name), Qt.ElideRight, name_rect.width())
        painter.drawText(name_rect, Qt.AlignCenter, name)

        if count_rect is not None:
            painter.setFont(canvas_font(10))
            muted = theme.BG_SIDEBAR if PRINT_MODE else theme.TEXT_MUTED
            painter.setPen(QPen(qcolor(muted, 0.95)))
            painter.drawText(count_rect, Qt.AlignCenter,
                             f"{count} item" + ("" if count == 1 else "s"))


# ---------------------------------------------------------------------------
# ROOM
# ---------------------------------------------------------------------------

class RoomItem(QGraphicsPolygonItem):
    """A room polygon, with its containers as children."""

    def __init__(self, room, profile, editor):
        super().__init__()
        self.room = room
        self.profile = profile
        self.editor = editor          # the FloorView, so we can report changes
        self.focused = False
        self.dimmed = False
        self.edit_mode = EDIT_MOVE
        self.syncing = False          # see VertexHandle.itemChange
        self.handles = []
        self.scale_handles = []
        self.container_items = []

        self.setPos(room.x, room.y)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(1)

        self.rebuild()

    # -- building -----------------------------------------------------------

    def rebuild(self):
        """Rebuild the polygon, the containers and the handles from the model.

        Called after anything structural changes. Throwing the child items
        away and remaking them is cheap at this scale, and it means the
        picture can never disagree with the data.
        """
        self._apply_polygon()
        self._rebuild_containers()
        self._rebuild_handles()
        self.set_focused(self.focused)      # also settles movability

    def _rebuild_containers(self):
        """Throw the container shapes away and make them again from the data."""
        for old in self.container_items:
            if old.scene():
                old.scene().removeItem(old)
            old.setParentItem(None)
        self.container_items = []

        for container in self.room.containers:
            self.container_items.append(
                ContainerItem(container, self, self.profile))

    def _apply_polygon(self):
        self.setPolygon(QPolygonF([QPointF(x, y) for x, y in self.room.points]))

    def sync_from_model(self):
        """Put the drawn shapes back in line with the data, whatever changed.

        Cheaper than rebuild() and it keeps selection, because where it can it
        moves the existing items rather than throwing them away.

        It does check whether the containers are still the same ones, though,
        and that check is not paranoia. The first version assumed the list was
        unchanged and left anything structural to rebuild(), which was fine
        until the 3D view started adding containers: a box drawn in 3D existed
        in the data and had no shape on the flat plan, so it simply was not
        there when you stepped back out. Comparing the list costs nothing and
        means no caller has to know which kind of change it just made.
        """
        if (self.pos().x(), self.pos().y()) != (self.room.x, self.room.y):
            self.setPos(self.room.x, self.room.y)

        if self.polygon() != QPolygonF([QPointF(x, y)
                                        for x, y in self.room.points]):
            self.prepareGeometryChange()
            self._apply_polygon()
            self._rebuild_handles()
            self.set_focused(self.focused)

        # By id and in order: a reorder changes what is drawn on top of what,
        # so it is a real difference and not just a set comparison.
        drawn = [item.container.id for item in self.container_items]
        if drawn != [c.id for c in self.room.containers]:
            self._rebuild_containers()
            self.set_focused(self.focused)
            self.update()
            return

        self.update()
        for container_item in self.container_items:
            container_item.sync_from_model()

    def _rebuild_handles(self):
        for old in self.handles + self.scale_handles:
            if old.scene():
                old.scene().removeItem(old)
            old.setParentItem(None)
        self.handles = []
        self.scale_handles = []

        for index in range(len(self.room.points)):
            self.handles.append(VertexHandle(self, index))

        for role in SCALE_ROLES:
            self.scale_handles.append(ScaleHandle(self, role))

        self.sync_handles()

    def sync_handles(self):
        """Put every handle where the current shape says it should be.

        `syncing` is raised while this runs so the vertex handles know these
        moves are housekeeping, not the user dragging them.
        """
        self.syncing = True
        try:
            for handle in self.handles:
                if handle.index < len(self.room.points):
                    x, y = self.room.points[handle.index]
                    handle.setPos(x, y)

            left, top, width, height = self.room.bounds()
            middle_x = left + width / 2
            middle_y = top + height / 2
            right = left + width
            bottom = top + height

            positions = {
                "nw": (left, top), "n": (middle_x, top), "ne": (right, top),
                "e": (right, middle_y), "se": (right, bottom),
                "s": (middle_x, bottom), "sw": (left, bottom),
                "w": (left, middle_y),
            }
            for handle in self.scale_handles:
                handle.setPos(*positions[handle.role])
        finally:
            self.syncing = False

        self._update_handle_visibility()

    def _apply_handle_visibility(self, selected):
        """Show the handles that match the current mode, and only those.

        Takes `selected` rather than asking isSelected(), because itemChange
        needs to run this with the value Qt is about to apply, which is not
        the one the item is reporting yet.
        """
        # A locked room shows nothing to grab. That is most of what makes
        # the lock legible: there is visibly no way in.
        active = selected and not self.focused and not self.room.locked
        for handle in self.handles:
            handle.setVisible(active and self.edit_mode == EDIT_VERTICES)
        for handle in self.scale_handles:
            handle.setVisible(active and self.edit_mode == EDIT_RESIZE)

    def _update_handle_visibility(self):
        self._apply_handle_visibility(self.isSelected())

    # -- state --------------------------------------------------------------

    def set_edit_mode(self, mode):
        self.edit_mode = mode
        self._update_movable()
        self._update_handle_visibility()
        # The containers inside follow the same switch, so they have to hear
        # about it too.
        for container_item in self.container_items:
            container_item.refresh_interaction()
        self.update()

    def set_locked(self, locked):
        """Freeze or release this room's geometry.

        Goes through the same two helpers everything else does, so a locked
        room cannot end up movable because some other code path set the flag
        after the lock did.
        """
        self.room.locked = bool(locked)
        self._update_movable()
        self._update_handle_visibility()
        self.update()

    def set_focused(self, focused):
        """Focused means "you are working inside this room".

        Containers become draggable, the room itself locks in place so you
        can't shove it by accident, and the handles hide to get out of the way.
        """
        self.focused = focused
        for container_item in self.container_items:
            container_item.set_editable(focused)   # also refreshes handles
        self._update_movable()
        self._update_handle_visibility()
        self.update()

    def _update_movable(self):
        """Decide in ONE place whether this room can be dragged around.

        Three separate things want the room held still, and having them each
        call setFlag independently is how you get a room that is stuck because
        one of them said no and the other never said yes again:

          - while it is focused, so you don't shove it while arranging drawers
          - while it is locked, which is the whole point of the lock
          - in any mode other than Move, because there a drag on the body
            means "I am working on this shape or size", not "move this"
        """
        can_move = (not self.focused
                    and not self.room.locked
                    and self.edit_mode == EDIT_MOVE)
        self.setFlag(QGraphicsItem.ItemIsMovable, can_move)
        self.setCursor(Qt.OpenHandCursor if can_move else Qt.ArrowCursor)

    def set_dimmed(self, dimmed):
        """Fade this room back because another room is focused."""
        self.dimmed = dimmed
        self.setOpacity(0.28 if dimmed else 1.0)
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            return snap_point(value)

        if change == QGraphicsItem.ItemSelectedChange:
            # Qt has not applied the new value yet, so pass it in rather than
            # asking isSelected(), which would still give the old answer.
            self._apply_handle_visibility(bool(value))

        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.commit_geometry()

    # -- geometry editing ----------------------------------------------------

    def move_vertex(self, index, point):
        """A vertex handle was dragged: update that one polygon point."""
        if index >= len(self.room.points):
            return
        self.room.points[index] = [point.x(), point.y()]
        self._apply_polygon()
        self.sync_handles()
        self.update()

    def add_vertex_near(self, local_point):
        """Put a new corner on whichever wall is nearest the given point.

        Comes from double-clicking an edge while in Edit shape mode. The
        handles have to be rebuilt rather than nudged, because every handle
        after the insertion point now represents a different corner.
        """
        index = self.room.insert_point_on_nearest_edge(
            local_point.x(), local_point.y())
        if index is None:
            return None

        # Snap the new corner to the grid so it lines up with everything else.
        x, y = self.room.points[index]
        self.room.points[index] = [snap(x), snap(y)]

        self._apply_polygon()
        self._rebuild_handles()
        self.update()
        self.editor.notify_changed()
        return index

    def remove_vertex(self, index):
        """Delete one corner. Refuses to go below three."""
        if not self.room.remove_point(index):
            return False

        self._apply_polygon()
        self._rebuild_handles()
        self.update()
        self.editor.notify_changed()
        return True

    def drag_edge(self, role, point):
        """A resize handle was dragged: move that edge and rescale the room.

        Work out the new bounding box first, then hand it to the model, which
        moves every point in proportion. Doing it in that order is what keeps
        the shape intact -- we never touch individual points here.
        """
        left, top, width, height = self.room.bounds()
        right = left + width
        bottom = top + height

        # Each compass letter in the role says which edge follows the mouse.
        # The opposite edge stays put, which is what makes a corner handle
        # pivot around the corner across from it.
        if "w" in role:
            left = min(point.x(), right - MIN_ROOM_SIZE)
        if "e" in role:
            right = max(point.x(), left + MIN_ROOM_SIZE)
        if "n" in role:
            top = min(point.y(), bottom - MIN_ROOM_SIZE)
        if "s" in role:
            bottom = max(point.y(), top + MIN_ROOM_SIZE)

        self.resize_room(right - left, bottom - top, left, top)

    def resize_room(self, width, height, left=None, top=None):
        """Stretch the room to an exact size. Also used by the inspector."""
        self.room.resize_to(max(width, MIN_ROOM_SIZE),
                            max(height, MIN_ROOM_SIZE), left, top)
        self._apply_polygon()
        self._clamp_containers()

        # Say so straight away rather than waiting for the mouse to come up.
        # This runs on every step of a drag, so the inspector's W and H count
        # along with the handle instead of showing a stale size until you
        # click somewhere else and back.
        self.editor.notify_resized(self.room)
        self.sync_handles()
        self.update()

    def _clamp_containers(self):
        """Pull containers back inside after the room has shrunk.

        Without this, squashing a room would leave its drawers hanging outside
        the walls -- visible, still selectable, and clearly wrong.
        """
        left, top, width, height = self.room.bounds()
        for container_item in self.container_items:
            container = container_item.container
            container.w = min(container.w, width)
            container.h = min(container.h, height)
            container.x = min(max(container.x, left), left + width - container.w)
            container.y = min(max(container.y, top), top + height - container.h)
            container_item.setRect(0, 0, container.w, container.h)
            container_item.setPos(container.x, container.y)

    def commit_geometry(self):
        """Copy the item's live position back into the saved data, then tell
        the editor so it can autosave."""
        self.room.x = self.pos().x()
        self.room.y = self.pos().y()
        self.editor.notify_changed()

    def add_container(self, container):
        self.room.containers.append(container)
        item = ContainerItem(container, self, self.profile)
        item.set_editable(self.focused)
        self.container_items.append(item)
        self.editor.notify_changed()
        return item

    # -- drawing --------------------------------------------------------------

    def boundingRect(self):
        # Extra headroom above the shape for the name label, which is drawn
        # outside the polygon itself, and a margin all round for the resize
        # handles that sit on the edge. If boundingRect is too small, Qt clips
        # them and leaves smears behind when the item moves.
        margin = SCALE_HANDLE_SIZE
        return super().boundingRect().adjusted(
            -margin, -LABEL_MARGIN, margin, margin)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        color = self.room.color
        selected = self.isSelected()

        fill_alpha = 0.10
        if selected:
            fill_alpha = 0.18
        if self.focused:
            fill_alpha = 0.16

        painter.setBrush(QBrush(qcolor(color, fill_alpha)))

        pen = QPen(qcolor(color, 0.95))
        pen.setWidthF(2.5 if (selected or self.focused) else 1.6)
        pen.setJoinStyle(Qt.RoundJoin)
        # A locked room is drawn with a dashed outline. Selecting one shows
        # no handles, and without a visible difference that just looks like
        # the app failing to respond to the click.
        if self.room.locked:
            pen.setStyle(Qt.DashLine)
        if self.focused:
            pen.setStyle(Qt.SolidLine)
            pen.setWidthF(3.0)
        painter.setPen(pen)
        painter.drawPolygon(self.polygon())

        # While resizing, outline the bounding box faintly so it is obvious
        # what the handles are moving.
        if (selected and not self.focused and not self.room.locked
                and self.edit_mode == EDIT_RESIZE):
            left, top, width, height = self.room.bounds()
            box_pen = QPen(qcolor(theme.ACCENT, 0.45))
            box_pen.setWidthF(1.0)
            box_pen.setStyle(Qt.DashLine)
            painter.setPen(box_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(left, top, width, height))

        self._paint_label(painter, color)

    def _paint_label(self, painter, color):
        """The room's name above it, with a summary line underneath.

        Sitting the label just above the polygon rather than in the middle
        keeps it clear of the containers, which is where the middle of a room
        usually is once you have filled it in.
        """
        left, top, width, height = self.room.bounds()
        if width <= 0:
            return

        name_rect = QRectF(left, top - LABEL_MARGIN + 2, width, 15)

        # The counts sit right-aligned in this same strip, so work out how
        # much room they need first and keep the name out of it. Otherwise a
        # long name runs straight through "3c · 12i" and both become unreadable.
        summary = ""
        summary_width = 0.0
        if width >= 90:
            container_count = len(self.room.containers)
            item_count = len(self.profile.items_in_room(self.room))
            summary = f"{container_count}c · {item_count}i"
            summary_width = QFontMetricsF(
                canvas_font(10)).horizontalAdvance(summary) + 8

        name_font = canvas_font(12, bold=True)
        painter.setFont(name_font)
        ink = theme.BG_APP if PRINT_MODE else theme.TEXT
        painter.setPen(QPen(qcolor(ink, 0.95)))

        # short() applies the app-wide character limit; elidedText then fits
        # the result to this room's actual width, which is the part that stops
        # a name hanging off the side of a narrow room.
        name = QFontMetricsF(name_font).elidedText(
            short(self.room.name), Qt.ElideRight,
            max(name_rect.width() - summary_width, 10))
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, name)

        if not summary:
            return

        painter.setFont(canvas_font(10))
        painter.setPen(QPen(qcolor(color, 0.85)))
        painter.drawText(name_rect, Qt.AlignRight | Qt.AlignVCenter, summary)


# ---------------------------------------------------------------------------
# DRAWING A FLOOR SOMEWHERE THAT ISN'T THE CANVAS
# ---------------------------------------------------------------------------
#
# The app has three places that show a floor plan: the canvas you edit on, the
# PDF export, and the preview beside the profile list. Only the first is a
# real FloorView. The other two want a picture, not an editor.
#
# Rather than write the drawing twice more, both build a throwaway scene, drop
# real RoomItems into it and ask the scene to render itself into a rectangle.
# Every one of them is then drawn by the same paint methods above, so a fix to
# how a room looks lands in all three at once and none can drift.

PLAN_MARGIN = 60        # scene units of breathing room around a rendered plan


class NoOpEditor:
    """A stand-in for the FloorView.

    RoomItem reports geometry changes back to its editor. Nothing is being
    dragged when we are drawing a picture, so this absorbs the call and does
    nothing. It saves giving RoomItem a special "no editor" mode.
    """

    def notify_changed(self):
        pass


def fit_inside(source, target):
    """The biggest rectangle with `source`'s shape that fits in `target`,
    centered.

    Qt's own KeepAspectRatio scales correctly but anchors the result to the
    top left, which on a wide panel leaves the whole plan pinned to one side
    with the spare room in a heap on the other. Working the destination out
    here and handing Qt a rectangle that already matches takes the question of
    who centers it off the table.
    """
    if source.width() <= 0 or source.height() <= 0:
        return QRectF(target)

    scale = min(target.width() / source.width(),
                target.height() / source.height())
    width = source.width() * scale
    height = source.height() * scale
    return QRectF(target.x() + (target.width() - width) / 2,
                  target.y() + (target.height() - height) / 2,
                  width, height)


def render_floor(painter, profile, floor, target, margin=PLAN_MARGIN):
    """Draw one floor's rooms into `target`, scaled to fit and centered.

    Returns False if the floor has no rooms to draw, so the caller can put its
    own message in the space instead. Qt would collect the scene eventually,
    but it is cleared here so a profile with twenty floors does not hold
    twenty of them at once.
    """
    if floor is None or not floor.rooms:
        return False

    # Imported here rather than at the top of the file: this is the only
    # function in the module that needs a scene, and importing QtWidgets
    # containers at module level pulls them in for everyone.
    from PySide6.QtWidgets import QGraphicsScene

    scene = QGraphicsScene()
    try:
        for room in floor.rooms:
            scene.addItem(RoomItem(room, profile, NoOpEditor()))

        source = scene.itemsBoundingRect().adjusted(
            -margin, -margin, margin, margin)
        # IgnoreAspectRatio on a destination that already has the right shape.
        # The fitting happened in fit_inside, where we can see it.
        scene.render(painter, fit_inside(source, QRectF(target)), source,
                     Qt.IgnoreAspectRatio)
    finally:
        scene.clear()

    return True

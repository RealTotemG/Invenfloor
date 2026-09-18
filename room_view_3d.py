"""
room_view_3d.py
===============

The room seen from the corner, in the style of an isometric game. Shown in
place of the flat canvas when you step inside a room and the 3D toggle is on.

WHY THIS IS A PLAIN WIDGET AND NOT A QGraphicsView
--------------------------------------------------
The flat canvas is a QGraphicsScene full of QGraphicsItems, and Qt does the
hit testing, dragging and selection for it. That machinery works in two
dimensions. You can shear a view's transform to make a scene look isometric,
but the moment a box needs HEIGHT the trick falls apart: "up" on an isometric
screen is not a direction in the scene, so a sheared scene can draw a
parallelogram and never a solid.

So this is a widget that paints, and the mouse handling below is written out
rather than inherited. It is more code, but all of it is readable arithmetic
instead of a fight with a framework that was not built for this.

WHAT IT TALKS TO
----------------
Nothing directly. It announces the same four things the flat canvas
announces, with the same names:

    itemSelected(container or None)
    dataChanged()
    containerResized(container)
    addItemRequested(container)

layout_section.py connects those to the inspector exactly as it connects the
canvas, which is why the inspector needs no idea this view exists.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu, QPushButton, QWidget

import iso
import theme
from models import (Container, MIN_CONTAINER_SIZE, MIN_HEIGHT, MAX_HEIGHT,
                    DEFAULT_HEIGHT, fit_in_room, room_contains_rect, short)

# How big a resize handle is on screen, and how close you have to click.
HANDLE_SIZE = 9
HANDLE_GRAB = 13

# What a click rather than a drag gets you from the Add container tool.
ADD_DEFAULT_SIZE = (100.0, 70.0)

# Where the way-out button sits. In theme.py because the flat canvas puts its
# own copy of the button in the same place, and the toggle can swap one canvas
# for the other at any moment: a button that jumps a few pixels when it does
# looks like a glitch.
EXIT_MARGIN = theme.CANVAS_EXIT_MARGIN

MIN_ZOOM = 0.2
MAX_ZOOM = 4.0
DRAG_THRESHOLD = 4       # move this far before a click counts as a drag
PADDING = 70             # screen margin left around the room when fitting


class RoomView3D(QWidget):
    """One room, drawn from the corner, with its containers standing in it."""

    itemSelected = Signal(object)         # a Container, or None
    dataChanged = Signal()                # something was edited; autosave
    containerResized = Signal(object)     # a Container, mid-drag as well
    addItemRequested = Signal(object)     # a Container
    renameRequested = Signal(object)      # a Container
    deleteRequested = Signal(object)      # a Container
    exitRequested = Signal()              # clicked away; step out of the room

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plain")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.profile = None
        self.room = None
        self.selected = None
        self.adding = False          # the Add container tool is armed

        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        # Whether the camera has been moved by hand. Resizing the window
        # refits the room, but only while nobody has zoomed in on a shelf --
        # refitting then would throw away exactly the view they set up.
        self._camera_moved = False

        # What the mouse is currently doing. One variable, the same way the
        # flat canvas keeps one mode, so there is only ever one answer to
        # "what does moving the mouse mean right now?".
        self._action = None          # None, "move", "resize", "add", "pan"
        self._grab_handle = None     # which handle, while resizing
        self._press_screen = None
        self._press_floor = None
        self._press_geometry = None  # (x, y, w, h, height) when the drag began
        self._add_origin = None
        self._add_rect = None
        self._hover = None

        # The way out, sitting in the corner of the canvas. Escape does the
        # same thing and so does double-clicking the floor, but neither of
        # those is visible, and being stuck inside a room with no obvious
        # door is a bad first five minutes.
        self._exit_button = QPushButton("←  Back to floor plan", self)
        self._exit_button.setObjectName("canvasExit")
        self._exit_button.setCursor(Qt.PointingHandCursor)
        self._exit_button.setToolTip("Step out of this room  (Esc)")
        self._exit_button.clicked.connect(self.exitRequested.emit)
        self._exit_button.move(EXIT_MARGIN, EXIT_MARGIN)

    # -- what it is showing ---------------------------------------------------

    def set_room(self, profile, room):
        """Point the view at a room. Passing None empties it."""
        self.profile = profile
        self.room = room
        self.selected = None
        self._action = None
        self._add_rect = None
        self._place_exit_button()
        self.fit()

    def _place_exit_button(self):
        """Size the way-out button and park it in the corner.

        adjustSize rather than a fixed width: the button is not in a layout,
        so nothing else will ever work out how much room its text needs, and
        a guessed width is how you end up with a clipped label on a machine
        whose interface font is wider than yours.
        """
        self._exit_button.setVisible(self.room is not None)
        self._exit_button.adjustSize()
        self._exit_button.move(EXIT_MARGIN, EXIT_MARGIN)

    def refresh(self):
        """Repaint, and let go of anything no longer in the room.

        Deleting a container leaves this view holding a reference to
        something that is not there any more, and the handles would go on
        being drawn around a box that is gone. Checking here rather than at
        every place a container can be deleted means it cannot be forgotten
        at a new call site later.
        """
        if (self.selected is not None and self.room is not None
                and self.selected not in self.room.containers):
            self.selected = None
        self.update()

    def select(self, container):
        """Select a container from outside, or None to clear."""
        if container is not self.selected:
            self.selected = container
            self.itemSelected.emit(container)
        self.update()

    def set_adding(self, armed):
        """Arm or disarm the Add container tool."""
        self.adding = bool(armed)
        self.setCursor(Qt.CrossCursor if armed else Qt.ArrowCursor)

    # -- the camera -----------------------------------------------------------

    def fit(self):
        """Zoom and center so the whole room fits with room to spare."""
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._camera_moved = False

        bounds = self._room_bounds()
        if bounds.isEmpty() or self.width() < 10 or self.height() < 10:
            # Too early: this page of the stack has not been given its real
            # size yet. resizeEvent will fit again the moment it has, which is
            # why _camera_moved is tracked separately from the zoom value.
            self.update()
            return

        self._zoom = min(
            (self.width() - PADDING * 2) / bounds.width(),
            (self.height() - PADDING * 2) / bounds.height())
        self._zoom = min(max(self._zoom, MIN_ZOOM), MAX_ZOOM)
        self.update()

    def reset_zoom(self):
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._camera_moved = False
        self.update()

    def _room_bounds(self):
        if self.room is None:
            return QRectF()
        tallest = max((c.height for c in self.room.containers), default=0.0)
        return iso.room_bounds(self.room.points, iso.WALL_HEIGHT, tallest)

    def _origin(self):
        """Where floor (0, 0) lands on the widget, before zoom.

        Kept as its own step so to_screen and to_floor below are exact
        mirrors of each other. Any drift between them shows up as a container
        jumping the moment you grab it.
        """
        bounds = self._room_bounds()
        return QPointF(self.width() / 2, self.height() / 2) + self._pan \
            - QPointF(bounds.center().x() * self._zoom,
                      bounds.center().y() * self._zoom)

    def to_screen(self, x, y, z=0.0):
        point = iso.project(x, y, z)
        origin = self._origin()
        return QPointF(origin.x() + point.x() * self._zoom,
                       origin.y() + point.y() * self._zoom)

    def to_floor(self, point):
        """A widget position back to a point on the room's floor."""
        origin = self._origin()
        return iso.floor_at(QPointF((point.x() - origin.x()) / self._zoom,
                                    (point.y() - origin.y()) / self._zoom))

    # -- painting -------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.CANVAS_BG))

        if self.room is None or len(self.room.points) < 3:
            iso.label(painter, QPointF(self.width() / 2, self.height() / 2),
                      "Step into a room to see it in 3D",
                      theme.TEXT_FAINT, theme.FONT_SIZE, bold=False,
                      width=self.width())
            painter.end()
            return

        # Everything is drawn through the same transform, so the painting
        # code below works in floor coordinates and never thinks about zoom.
        origin = self._origin()
        painter.translate(origin)
        painter.scale(self._zoom, self._zoom)

        points = [(px, py) for px, py in self.room.points]
        iso.draw_floor(painter, points, self.room.color)

        # Walls and containers go in ONE list and are ordered together.
        #
        # The walls used to all be drawn first, on the reasoning that a wall
        # is behind the room it encloses. That holds for a rectangle. It does
        # not hold for an L: the back wall of the L's foot stands in FRONT of
        # anything in the L's other arm, and drawing it first left a cabinet
        # sitting on top of a wall it was standing behind.
        # The second number is the tie-break, and walls win ties on purpose.
        # Equal depth means a container is pushed flush into the corner the
        # wall starts from, and a wall is always behind what stands against
        # it.
        pieces = (
            [(iso.footprint_depth(iso.wall_footprint(wall)), 0, "wall", wall)
             for wall in iso.far_walls(points)]
            + [(iso.depth(c.x, c.y), 1, "box", c)
               for c in self.room.containers])
        pieces.sort(key=lambda piece: (piece[0], piece[1]))

        for _, _, kind, thing in pieces:
            if kind == "wall":
                iso.draw_wall(painter, thing[0], thing[1], self.room.color)
                continue

            iso.draw_box(painter, thing.x, thing.y, thing.w, thing.h,
                         thing.height, thing.color,
                         tiers=thing.tier_count,
                         selected=thing is self.selected)
            self._draw_box_label(painter, thing)

        if self.selected is not None:
            self._draw_handles(painter)

        if self._add_rect is not None:
            self._draw_add_preview(painter)

        painter.end()

    def _draw_box_label(self, painter, container):
        """A container's name and count, floating clear above it.

        Clear above, not centered on the top face. Text laid over the lit top
        of a box is unreadable, and the highest corner on screen is always the
        far one, so that is what the label is lifted past.
        """
        # Sizes are divided by the zoom because the painter is scaled: this
        # keeps text the same size on screen whatever the camera is doing.
        scale = max(self._zoom, 0.25)
        name_size = max(int(13 / scale), 1)
        count_size = max(int(11 / scale), 1)
        width = int(260 / scale)

        highest = iso.project(container.x, container.y, container.height)
        middle_x = iso.project(container.x + container.w / 2,
                               container.y + container.h / 2,
                               container.height).x()

        top = highest.y()
        if container is self.selected:
            # A selected container has its height handle floating above it,
            # higher than the box itself, so the label has to clear the handle
            # instead or the two are drawn on top of each other.
            handle = iso.box_corners(container.x, container.y, container.w,
                                     container.h, container.height)["top"]
            top = min(top, handle.y() - HANDLE_SIZE / scale)

        count = 0
        if self.profile is not None:
            count = self.profile.item_count_in_container(container.id)

        bright = (container is self.selected or container is self._hover)

        base = QPointF(middle_x, top - 6 / scale)
        iso.label(painter, base,
                  f"{count} item" + ("" if count == 1 else "s"),
                  theme.TEXT_FAINT, count_size, bold=False, width=width)
        iso.label(painter, QPointF(base.x(), base.y() - count_size - 3 / scale),
                  short(container.name),
                  theme.TEXT if bright else theme.TEXT_MUTED,
                  name_size, bold=True, width=width)

    def _draw_handles(self, painter):
        """The resize handles on the selected container.

        Four on the floor corners for the footprint, one on the top face for
        the height, which is the same split a 3D editor gives you: drag the
        base to change where it sits and how much floor it covers, drag the
        top to change how tall it stands.
        """
        container = self.selected
        thin = 1 / max(self._zoom, 0.2)
        corners = iso.box_corners(container.x, container.y, container.w,
                                  container.h, container.height)

        # The footprint first: the patch of floor the container covers, drawn
        # dashed. Two of the four corner handles on a tall box fall inside its
        # own silhouette, and without this outline joining them they read as
        # buttons stuck on the front of the cabinet rather than as the corners
        # of a rectangle lying on the floor.
        # Outline only, no fill. The handles are drawn over everything so you
        # can always reach them, and a filled footprint drawn last washes over
        # whatever container happens to stand behind this one.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(theme.ACCENT), 1.4 * thin, Qt.DashLine))
        painter.drawPolygon(iso.top_face(container.x, container.y,
                                         container.w, container.h, 0))

        # Then the lever for the height. The handle floats clear above the
        # box (see iso.handle_lift), so the line is what connects it back to
        # the thing it lifts.
        painter.setPen(QPen(theme.qcolor(theme.SUCCESS, 0.6),
                            1.4 * thin, Qt.DashLine))
        painter.drawLine(corners["top"],
                         iso.project(container.x + container.w / 2,
                                     container.y + container.h / 2, 0))

        size = HANDLE_SIZE * thin
        for role, point in corners.items():
            # Square handles on the floor change the footprint, the round one
            # on top changes the height. Two shapes and two colors, so which
            # handle does what is clear before you touch it.
            on_top = (role == "top")
            painter.setBrush(QColor(theme.SUCCESS if on_top else theme.ACCENT))
            painter.setPen(QPen(QColor(theme.BG_APP), 1.6 * thin))
            if on_top:
                painter.drawEllipse(point, size * 0.75, size * 0.75)
            else:
                painter.drawRect(QRectF(point.x() - size / 2,
                                        point.y() - size / 2, size, size))

    def _draw_add_preview(self, painter):
        """The footprint being dragged out, blue if it fits and red if not.

        Red rather than silently snapping it somewhere legal: a box that
        jumps out from under the cursor as you draw it is far more confusing
        than one that tells you it will not go there.
        """
        rect = self._add_rect
        fits = self._add_fits()
        color = theme.ACCENT if fits else theme.DANGER
        painter.setBrush(theme.qcolor(color, 0.22))
        painter.setPen(QPen(QColor(color),
                            1.6 / max(self._zoom, 0.2), Qt.DashLine))
        painter.drawPolygon(iso.top_face(rect.x(), rect.y(),
                                         rect.width(), rect.height(), 0))

    def _add_fits(self):
        """Would the footprint being dragged out land inside the room?

        A click rather than a drag is judged on the default sized box it will
        actually become, not on the empty rectangle under the cursor, so the
        preview never says yes to something the release then refuses.
        """
        rect = self._add_rect
        if rect is None:
            return False
        width, height = rect.width(), rect.height()
        if width < MIN_CONTAINER_SIZE or height < MIN_CONTAINER_SIZE:
            width, height = ADD_DEFAULT_SIZE
        return room_contains_rect(self.room, rect.x(), rect.y(), width, height)

    # -- what is under the cursor ---------------------------------------------

    def container_at(self, point):
        """Which container is under a widget position, nearest first.

        Walked near to far, the opposite of the draw order, because the thing
        drawn last is the thing on top and so the thing you meant to click.
        """
        if self.room is None:
            return None

        for container in sorted(self.room.containers,
                                key=lambda c: iso.depth(c.x, c.y),
                                reverse=True):
            if self._silhouette(container).containsPoint(point,
                                                         Qt.OddEvenFill):
                return container
        return None

    def _silhouette(self, container):
        """The box's outline in widget coordinates."""
        shape = iso.box_outline(container.x, container.y, container.w,
                                container.h, container.height)
        return type(shape)([self._to_widget(p) for p in shape])

    def _to_widget(self, point):
        origin = self._origin()
        return QPointF(origin.x() + point.x() * self._zoom,
                       origin.y() + point.y() * self._zoom)

    def handle_at(self, point):
        """Which resize handle is under a widget position, if any."""
        if self.selected is None:
            return None

        corners = iso.box_corners(self.selected.x, self.selected.y,
                                  self.selected.w, self.selected.h,
                                  self.selected.height)
        for role, corner in corners.items():
            spot = self._to_widget(corner)
            if (abs(spot.x() - point.x()) <= HANDLE_GRAB
                    and abs(spot.y() - point.y()) <= HANDLE_GRAB):
                return role
        return None

    # -- mouse ----------------------------------------------------------------

    def mousePressEvent(self, event):
        if self.room is None:
            return

        point = event.position()

        if event.button() == Qt.MiddleButton:
            self._action = "pan"
            self._press_screen = point
            return

        if event.button() != Qt.LeftButton:
            return

        self._press_screen = point
        self._press_floor = self.to_floor(point)

        if self.adding:
            self._action = "add"
            self._add_origin = self._clamped_floor(point)
            self._add_rect = QRectF(self._add_origin, self._add_origin)
            self.update()
            return

        # A handle beats the container under it: the handles sit on the box,
        # so without this you could never grab one.
        grabbed = self.handle_at(point)
        if grabbed is not None:
            self._action = "resize"
            self._grab_handle = grabbed
            self._press_geometry = (self.selected.x, self.selected.y,
                                    self.selected.w, self.selected.h,
                                    self.selected.height)
            return

        hit = self.container_at(point)
        if hit is not None:
            self.select(hit)
            self._action = "move"
            self._press_geometry = (hit.x, hit.y, hit.w, hit.h, hit.height)
            return

        # Clicked the floor or the wall: drop the selection but stay in the
        # room. Stepping out is Escape, or the button in the inspector.
        self.select(None)
        self._action = None

    def mouseMoveEvent(self, event):
        point = event.position()

        if self._action is None:
            hovering = self.container_at(point)
            if hovering is not self._hover:
                self._hover = hovering
                self.update()
            if not self.adding:
                over_handle = self.handle_at(point) is not None
                self.setCursor(Qt.SizeAllCursor if over_handle
                               else (Qt.PointingHandCursor if hovering
                                     else Qt.ArrowCursor))
            return

        if self._action == "pan":
            self._pan += point - self._press_screen
            self._press_screen = point
            self._camera_moved = True
            self.update()
            return

        if self._action == "add":
            corner = self._clamped_floor(point)
            self._add_rect = QRectF(self._add_origin, corner).normalized()
            self.update()
            return

        if self._action == "move":
            self._drag_move(point)
            return

        if self._action == "resize":
            self._drag_resize(point)

    def mouseReleaseEvent(self, event):
        action, self._action = self._action, None
        self._grab_handle = None

        if action == "add" and self._add_rect is not None:
            self._finish_add()
            self._add_rect = None
            self.update()
            return

        if action in ("move", "resize"):
            # One save at the end of the drag rather than eighty on the way.
            self.dataChanged.emit()

    def mouseDoubleClickEvent(self, event):
        """Double-clicking a container opens the Add item dialog for it.

        Double-clicking the floor steps back out, matching the flat canvas
        where a second double-click leaves the room.
        """
        hit = self.container_at(event.position())
        if hit is not None:
            self.addItemRequested.emit(hit)
        else:
            self.exitRequested.emit()

    def wheelEvent(self, event):
        if self.room is None:
            return
        step = 1.0015 ** event.angleDelta().y()
        self._zoom = min(max(self._zoom * step, MIN_ZOOM), MAX_ZOOM)
        self._camera_moved = True
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.adding:
                self.set_adding(False)
            else:
                self.exitRequested.emit()
            return
        if event.key() == Qt.Key_Delete and self.selected is not None:
            self.deleteRequested.emit(self.selected)
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        hit = self.container_at(QPointF(event.pos()))
        if hit is None:
            return

        self.select(hit)
        menu = QMenu(self)
        menu.addAction("Add item here",
                       lambda: self.addItemRequested.emit(hit))
        menu.addAction("Rename", lambda: self.renameRequested.emit(hit))
        menu.addSeparator()
        menu.addAction("Delete container",
                       lambda: self.deleteRequested.emit(hit))
        menu.exec(event.globalPos())

    # -- the drags themselves -------------------------------------------------

    def _clamped_floor(self, point):
        """A widget position as a floor point, held inside the room's bounds.

        Everything the mouse does in this view goes through here first, so a
        drag that wanders off the floor still lands somewhere real.
        """
        floor = self.to_floor(point)
        left, top, width, height = self.room.bounds()
        return QPointF(min(max(floor.x(), left), left + width),
                       min(max(floor.y(), top), top + height))

    def _drag_move(self, point):
        """Slide a container across the floor.

        The mouse moved some distance on screen; that distance is converted
        to a distance on the floor and added to where the container started.
        Going through the starting position rather than the current one means
        the box does not creep away from the cursor over a long drag.
        """
        start_x, start_y, w, h, _ = self._press_geometry
        moved = self.to_floor(point) - self._press_floor

        # `stay` is where the box is at this instant, which is the last spot
        # that fitted. Hand fit_in_room that and a drag into the notch of an
        # L-shaped room slides along the wall instead of ending up standing
        # over nothing.
        x, y, w, h = fit_in_room(
            self.room, start_x + moved.x(), start_y + moved.y(), w, h,
            stay=(self.selected.x, self.selected.y, w, h))
        self.selected.x, self.selected.y = x, y
        self.update()

    def _drag_resize(self, point):
        """Drag a handle. The corners change the footprint, the top the height."""
        start_x, start_y, start_w, start_h, start_height = self._press_geometry

        if self._grab_handle == "top":
            # Height only. On screen, up is pure -y, so the vertical distance
            # the mouse travelled IS the height change once zoom is undone.
            lifted = (self._press_screen.y() - point.y()) / self._zoom
            height = min(max(start_height + lifted, MIN_HEIGHT), MAX_HEIGHT)
            self.selected.height = round(height)
            self.containerResized.emit(self.selected)
            self.update()
            return

        floor = self._clamped_floor(point)
        left = start_x
        top = start_y
        right = start_x + start_w
        bottom = start_y + start_h

        if "w" in self._grab_handle:
            left = min(floor.x(), right - MIN_CONTAINER_SIZE)
        if "e" in self._grab_handle:
            right = max(floor.x(), left + MIN_CONTAINER_SIZE)
        if "n" in self._grab_handle:
            top = min(floor.y(), bottom - MIN_CONTAINER_SIZE)
        if "s" in self._grab_handle:
            bottom = max(floor.y(), top + MIN_CONTAINER_SIZE)

        x, y, w, h = fit_in_room(
            self.room, left, top, right - left, bottom - top,
            stay=(self.selected.x, self.selected.y,
                  self.selected.w, self.selected.h))
        self.selected.x, self.selected.y = x, y
        self.selected.w, self.selected.h = w, h
        self.containerResized.emit(self.selected)
        self.update()

    def _finish_add(self):
        """Turn the dragged footprint into a real container.

        A click rather than a drag still makes one, at a default size, for the
        same reason the flat canvas does: demanding a precise drag to get a
        box is fussy when you can resize it a second later.

        A footprint that does not fit inside the room makes nothing, and
        leaves the tool armed so the next click is another attempt rather
        than a trip back to the toolbar.
        """
        if not self._add_fits():
            return

        rect = self._add_rect
        if rect.width() < MIN_CONTAINER_SIZE or rect.height() < MIN_CONTAINER_SIZE:
            rect = QRectF(rect.x(), rect.y(), *ADD_DEFAULT_SIZE)

        x, y, w, h = fit_in_room(self.room, rect.x(), rect.y(),
                                 rect.width(), rect.height())

        existing = len(self.room.containers)
        container = Container(
            name=f"Container {existing + 1}",
            color=theme.SWATCHES[(existing + 2) % len(theme.SWATCHES)],
            x=x, y=y, w=w, h=h, height=DEFAULT_HEIGHT,
        )
        self.room.containers.append(container)

        self.set_adding(False)
        self.select(container)
        self.dataChanged.emit()

    # -- keeping the camera sensible ------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_exit_button()
        if not self._camera_moved:
            self.fit()

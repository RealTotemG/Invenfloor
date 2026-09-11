"""
floor_view.py
=============

The canvas itself: the grid, panning and zooming, drawing new rooms, dropping
containers into them, and focusing a room to work inside it.

THE THREE TOOLS
---------------
The view is always in exactly one mode, and every mouse event asks which one
first. Keeping that as a single variable -- rather than a scatter of booleans
like `is_drawing` and `is_placing` -- is what stops canvas code turning into
an unreadable mess, because there is only ever one answer to "what does a
click mean right now?".

    SELECT     click to select, drag to move, drag a corner handle to reshape,
               double-click a room to focus it
    DRAW_ROOM  click to place each corner, click the first corner again (or
               press Enter) to close the shape
    ADD_BOX    drag a rectangle inside a room to create a container there

FOCUS
-----
Double-clicking a room focuses it: every other room fades back, the focused
room locks so you can't shove it by accident, and its containers become
draggable. Click empty space to come back out. It is the same idea as the
Sims dropping into a single room to furnish it.
"""

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsScene, QGraphicsView, QGraphicsRectItem,
)

import theme
from floor_items import (
    EDIT_RESIZE, ContainerItem, RoomItem, snap, snap_point, qcolor,
)
from models import Container, Room

# The modes. Plain strings keep them readable in the debugger and in the
# toolbar code.
MODE_SELECT = "select"
MODE_DRAW_ROOM = "draw_room"
MODE_ADD_BOX = "add_box"
MODE_ADD_SHAPE = "add_shape"     # dragging out a preset room shape

DEFAULT_SHAPE_SIZE = 160          # used when a preset is clicked, not dragged

SCENE_SIZE = 8000        # how far you can pan in any direction
MIN_ZOOM = 0.25
MAX_ZOOM = 4.0
CLOSE_DISTANCE = 18      # click this close to the first corner to close a shape


class FloorView(QGraphicsView):
    """The drawing surface for one floor."""

    # Announcements to the rest of the app. The view never touches the
    # inspector or the save file directly -- it just says what happened.
    itemSelected = Signal(object)    # a Room, a Container, or None
    dataChanged = Signal()           # something was edited; please autosave
    roomFocused = Signal(object)     # a Room, or None
    modeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None
        self.floor = None
        self.mode = MODE_SELECT
        self.focused_room_item = None
        self.room_items = []

        self._zoom = 1.0
        self._panning = False
        self._pan_start = None
        self._draft_points = []      # corners placed so far in DRAW_ROOM
        self._draft_item = None      # the dashed preview of that shape
        self._box_origin = None      # where an ADD_BOX drag started
        self._box_room_item = None
        self._box_preview = None
        self._shape_builder = None   # the preset being placed, if any
        self._shape_origin = None

        # Which handles a selected room shows. Kept on the view rather than
        # per room so the choice sticks as you click from room to room --
        # otherwise you would have to re-pick "Edit shape" every single time.
        self.room_edit_mode = EDIT_RESIZE

        # Used by reveal_container() to pulse a container on and off.
        self._flash_target = None
        self._flash_ticks = 0
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._on_flash_tick)

        scene = QGraphicsScene(self)
        scene.setSceneRect(-SCENE_SIZE / 2, -SCENE_SIZE / 2,
                           SCENE_SIZE, SCENE_SIZE)
        self.setScene(scene)
        scene.selectionChanged.connect(self._on_scene_selection_changed)

        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        # No scrollbars: the scene is deliberately enormous, so they would
        # always be visible and always nearly full-length, which tells you
        # nothing. Middle-drag panning still works -- turning the bars off
        # hides them without disabling the scrolling underneath.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # -- loading a floor ----------------------------------------------------

    def set_floor(self, profile, floor):
        """Show a different floor. Everything on screen is rebuilt."""
        self.profile = profile
        self.floor = floor
        self._stop_flash()
        self.cancel_draft()
        self.set_mode(MODE_SELECT)

        self.scene().clear()
        self.room_items = []
        self.focused_room_item = None

        if floor is not None:
            for room in floor.rooms:
                item = RoomItem(room, profile, self)
                item.set_edit_mode(self.room_edit_mode)
                self.scene().addItem(item)
                self.room_items.append(item)

        self.itemSelected.emit(None)
        self.roomFocused.emit(None)

    def set_room_edit_mode(self, mode):
        """Switch every room between resize handles and per-corner handles."""
        self.room_edit_mode = mode
        for room_item in self.room_items:
            room_item.set_edit_mode(mode)

    def refresh(self):
        """Redraw everything without rebuilding it.

        Used when data changed elsewhere -- a room was renamed in the
        inspector, or items moved between containers -- and the shapes just
        need to repaint with new text.
        """
        for room_item in self.room_items:
            room_item.update()
            for container_item in room_item.container_items:
                container_item.update()

    def rebuild_room(self, room):
        for room_item in self.room_items:
            if room_item.room.id == room.id:
                room_item.rebuild()
                return

    def resize_room(self, room, width, height):
        """Stretch a room to an exact size. Used by the inspector's W/H boxes."""
        for room_item in self.room_items:
            if room_item.room.id == room.id:
                room_item.resize_room(width, height)
                self.dataChanged.emit()
                return

    def reveal_container(self, container_id):
        """Select a container, centre the view on it, and make it blink.

        This is the other end of the Find button on the Items screen. Selecting
        alone is too subtle -- on a floor with twenty containers your eye has
        no idea where to land -- so it also pulses for about a second.
        """
        for room_item in self.room_items:
            for container_item in room_item.container_items:
                if container_item.container.id != container_id:
                    continue

                self.set_focused_room(None)
                self.scene().clearSelection()
                container_item.setSelected(True)
                self.centerOn(container_item)
                self._start_flash(container_item)
                return True

        return False

    def _start_flash(self, container_item):
        # Stop any flash already running, or two overlapping pulses would
        # leave the first one stuck on.
        self._stop_flash()
        self._flash_target = container_item
        self._flash_ticks = 0
        self._flash_timer.start(170)

    def _on_flash_tick(self):
        if self._flash_target is None:
            self._flash_timer.stop()
            return

        self._flash_ticks += 1
        self._flash_target.highlighted = (self._flash_ticks % 2 == 1)
        self._flash_target.update()

        if self._flash_ticks >= 6:
            self._stop_flash()

    def _stop_flash(self):
        self._flash_timer.stop()
        if self._flash_target is not None:
            self._flash_target.highlighted = False
            self._flash_target.update()
            self._flash_target = None

    def remove_room_item(self, room):
        for room_item in list(self.room_items):
            if room_item.room.id == room.id:
                if self.focused_room_item is room_item:
                    self.set_focused_room(None)
                self.scene().removeItem(room_item)
                self.room_items.remove(room_item)

    def notify_changed(self):
        """Called by the shapes when they are dragged. Triggers an autosave."""
        self.dataChanged.emit()

    # -- modes ---------------------------------------------------------------

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.cancel_draft()
        self.mode = mode

        # Rubber-band marquee selection only makes sense in select mode.
        self.setDragMode(QGraphicsView.RubberBandDrag if mode == MODE_SELECT
                         else QGraphicsView.NoDrag)
        self.setCursor(Qt.ArrowCursor if mode == MODE_SELECT
                       else Qt.CrossCursor)
        self.modeChanged.emit(mode)

    def set_shape_tool(self, builder):
        """Arm one of the preset shapes. `builder` takes a width and a height
        and returns polygon points (see ROOM_PRESETS in models.py).

        Written the long way because set_mode() returns early when the mode is
        already what you asked for -- which is right normally, but would mean
        picking a second preset while the first is armed silently did nothing.
        """
        self.cancel_draft()
        self._shape_builder = builder

        if self.mode == MODE_ADD_SHAPE:
            self.modeChanged.emit(MODE_ADD_SHAPE)
        else:
            self.set_mode(MODE_ADD_SHAPE)

    def cancel_draft(self):
        """Throw away a half-drawn room, container or preset shape."""
        self._draft_points = []
        if self._draft_item is not None:
            self.scene().removeItem(self._draft_item)
            self._draft_item = None
        if self._box_preview is not None:
            self.scene().removeItem(self._box_preview)
            self._box_preview = None
        self._box_origin = None
        self._box_room_item = None
        self._shape_origin = None

    # -- focus ----------------------------------------------------------------

    def set_focused_room(self, room_item):
        """Focus one room (or None to come back out to the whole floor)."""
        self.focused_room_item = room_item

        for candidate in self.room_items:
            is_focused = (candidate is room_item)
            candidate.set_focused(is_focused)
            candidate.set_dimmed(room_item is not None and not is_focused)

        self.roomFocused.emit(room_item.room if room_item else None)

    # -- selection -------------------------------------------------------------

    def _on_scene_selection_changed(self):
        """Work out what the user selected and announce it once.

        The scene reports "the selection changed"; the inspector wants to know
        "which room or container". Translating between the two is this
        method's whole job.
        """
        selected = self.scene().selectedItems()
        if not selected:
            self.itemSelected.emit(None)
            return

        # A container is the more specific thing, so it wins if both a room
        # and one of its containers somehow end up selected together.
        for item in selected:
            if isinstance(item, ContainerItem):
                self.itemSelected.emit(item.container)
                return
        for item in selected:
            if isinstance(item, RoomItem):
                self.itemSelected.emit(item.room)
                return

        self.itemSelected.emit(None)

    def select_room(self, room):
        self.scene().clearSelection()
        for room_item in self.room_items:
            if room_item.room.id == room.id:
                room_item.setSelected(True)
                return

    # -- finding things under the mouse ------------------------------------------

    def _room_item_at(self, scene_point):
        """Which room contains this point? Topmost wins.

        Asking the scene what is at a point would also hand back containers
        and drag handles, so instead we test the rooms directly, in reverse
        order so the one drawn on top is found first.
        """
        for room_item in reversed(self.room_items):
            local = room_item.mapFromScene(scene_point)
            if room_item.polygon().containsPoint(local, Qt.OddEvenFill):
                return room_item
        return None

    # -- mouse ---------------------------------------------------------------------

    def mousePressEvent(self, event):
        scene_point = self.mapToScene(event.position().toPoint())

        # Middle button always pans, whatever mode we are in.
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return

        if self.mode == MODE_DRAW_ROOM and event.button() == Qt.LeftButton:
            self._add_draft_point(scene_point)
            return

        if self.mode == MODE_ADD_BOX and event.button() == Qt.LeftButton:
            self._begin_box(scene_point)
            return

        if self.mode == MODE_ADD_SHAPE and event.button() == Qt.LeftButton:
            self._begin_shape(scene_point)
            return

        # Select mode: clicking bare canvas clears focus and selection.
        if self.mode == MODE_SELECT and event.button() == Qt.LeftButton:
            if self._room_item_at(scene_point) is None:
                if self.focused_room_item is not None:
                    self.set_focused_room(None)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            # Panning by moving the scrollbars keeps the scene coordinates
            # untouched, which matters -- nothing else in the app has to know
            # the view has been scrolled.
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            return

        scene_point = self.mapToScene(event.position().toPoint())

        if self.mode == MODE_DRAW_ROOM and self._draft_points:
            self._update_draft(scene_point)
            return

        if self.mode == MODE_ADD_BOX and self._box_origin is not None:
            self._update_box(scene_point)
            return

        if self.mode == MODE_ADD_SHAPE and self._shape_origin is not None:
            self._update_shape(scene_point)
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor if self.mode == MODE_SELECT
                           else Qt.CrossCursor)
            return

        if self.mode == MODE_ADD_BOX and event.button() == Qt.LeftButton:
            self._finish_box()
            return

        if self.mode == MODE_ADD_SHAPE and event.button() == Qt.LeftButton:
            self._finish_shape(self.mapToScene(event.position().toPoint()))
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        scene_point = self.mapToScene(event.position().toPoint())

        if self.mode == MODE_DRAW_ROOM:
            self._close_draft()
            return

        if self.mode == MODE_SELECT:
            room_item = self._room_item_at(scene_point)
            if room_item is not None:
                # Double-clicking the already-focused room steps back out.
                if room_item is self.focused_room_item:
                    self.set_focused_room(None)
                else:
                    self.set_focused_room(room_item)
                return
            self.set_focused_room(None)
            return

        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        """Scroll wheel zooms, anchored under the mouse pointer."""
        step = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = self._zoom * step

        if new_zoom < MIN_ZOOM or new_zoom > MAX_ZOOM:
            return

        self._zoom = new_zoom
        self.scale(step, step)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.mode != MODE_SELECT:
                self.set_mode(MODE_SELECT)
            elif self.focused_room_item is not None:
                self.set_focused_room(None)
            else:
                self.scene().clearSelection()
            return

        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.mode == MODE_DRAW_ROOM:
                self._close_draft()
                return

        if event.key() == Qt.Key_Delete:
            self.delete_selection()
            return

        super().keyPressEvent(event)

    # -- drawing a room ------------------------------------------------------------

    def _add_draft_point(self, scene_point):
        point = snap_point(scene_point)

        # Clicking back on the first corner closes the shape.
        if len(self._draft_points) >= 3:
            first = self._draft_points[0]
            distance = (point - first).manhattanLength()
            if distance <= CLOSE_DISTANCE:
                self._close_draft()
                return

        self._draft_points.append(point)
        self._update_draft(point)

    def _update_draft(self, cursor_point):
        """Redraw the dashed preview of the room being traced."""
        if self._draft_item is None:
            self._draft_item = QGraphicsPathItem()
            pen = QPen(qcolor(theme.ACCENT, 0.95))
            pen.setWidthF(2.0)
            pen.setStyle(Qt.DashLine)
            self._draft_item.setPen(pen)
            self._draft_item.setBrush(QBrush(qcolor(theme.ACCENT, 0.10)))
            self._draft_item.setZValue(50)
            self.scene().addItem(self._draft_item)

        path = QPainterPath()
        if self._draft_points:
            path.moveTo(self._draft_points[0])
            for point in self._draft_points[1:]:
                path.lineTo(point)
            path.lineTo(snap_point(cursor_point))
            if len(self._draft_points) >= 2:
                path.lineTo(self._draft_points[0])
        self._draft_item.setPath(path)

    def _close_draft(self):
        """Turn the traced corners into a real room."""
        if len(self._draft_points) < 3:
            # Fewer than three corners doesn't enclose anything.
            return

        # The polygon is stored relative to the room's own origin, so shift
        # every point by the top-left corner and use that as the position.
        xs = [p.x() for p in self._draft_points]
        ys = [p.y() for p in self._draft_points]
        origin_x, origin_y = min(xs), min(ys)
        points = [[p.x() - origin_x, p.y() - origin_y]
                  for p in self._draft_points]

        self.cancel_draft()
        self._create_room(points, origin_x, origin_y)

    def _create_room(self, points, origin_x, origin_y):
        """Add a room to the floor and put it on the canvas, selected.

        Both the freehand tool and the preset shapes end up here, so a room
        created either way behaves identically from this point on.
        """
        room = Room(
            name=f"Room {len(self.floor.rooms) + 1}",
            color=theme.SWATCHES[len(self.floor.rooms) % len(theme.SWATCHES)],
            x=origin_x, y=origin_y,
            points=points,
        )
        self.floor.rooms.append(room)

        item = RoomItem(room, self.profile, self)
        item.set_edit_mode(self.room_edit_mode)
        self.scene().addItem(item)
        self.room_items.append(item)

        self.set_mode(MODE_SELECT)
        self.scene().clearSelection()
        item.setSelected(True)
        self.dataChanged.emit()
        return item

    # -- preset shapes ---------------------------------------------------------

    def _begin_shape(self, scene_point):
        self._shape_origin = snap_point(scene_point)

        self._draft_item = QGraphicsPathItem()
        pen = QPen(qcolor(theme.ACCENT, 0.95))
        pen.setWidthF(2.0)
        pen.setStyle(Qt.DashLine)
        self._draft_item.setPen(pen)
        self._draft_item.setBrush(QBrush(qcolor(theme.ACCENT, 0.12)))
        self._draft_item.setZValue(50)
        self.scene().addItem(self._draft_item)

    def _update_shape(self, scene_point):
        """Preview the actual preset outline, not just a bounding box.

        Showing the real shape while you drag means you can see a circle is a
        circle before you commit to it, which is worth the few extra lines.
        """
        if self._draft_item is None or self._shape_builder is None:
            return

        rect = QRectF(self._shape_origin, snap_point(scene_point)).normalized()
        width = max(rect.width(), 1)
        height = max(rect.height(), 1)

        path = QPainterPath()
        points = self._shape_builder(width, height)
        path.moveTo(rect.left() + points[0][0], rect.top() + points[0][1])
        for x, y in points[1:]:
            path.lineTo(rect.left() + x, rect.top() + y)
        path.closeSubpath()

        self._draft_item.setPath(path)

    def _finish_shape(self, scene_point):
        if self._shape_origin is None or self._shape_builder is None:
            self.cancel_draft()
            return

        rect = QRectF(self._shape_origin, snap_point(scene_point)).normalized()
        builder = self._shape_builder
        self.cancel_draft()

        # A click rather than a drag still places the shape, at a sensible
        # default size. Requiring a precise drag just to get a rectangle would
        # be needlessly fussy -- you can resize it immediately afterwards.
        if rect.width() < theme.GRID_SIZE or rect.height() < theme.GRID_SIZE:
            rect = QRectF(rect.left(), rect.top(),
                          DEFAULT_SHAPE_SIZE, DEFAULT_SHAPE_SIZE)

        points = builder(rect.width(), rect.height())
        self._create_room(points, rect.left(), rect.top())

    # -- adding a container ---------------------------------------------------------

    def _begin_box(self, scene_point):
        room_item = self._room_item_at(scene_point)
        if room_item is None:
            return      # containers can only exist inside a room

        self._box_room_item = room_item
        self._box_origin = snap_point(scene_point)

        self._box_preview = QGraphicsRectItem()
        pen = QPen(qcolor(theme.ACCENT, 0.95))
        pen.setWidthF(1.6)
        pen.setStyle(Qt.DashLine)
        self._box_preview.setPen(pen)
        self._box_preview.setBrush(QBrush(qcolor(theme.ACCENT, 0.16)))
        self._box_preview.setZValue(50)
        self.scene().addItem(self._box_preview)

    def _update_box(self, scene_point):
        if self._box_preview is None:
            return
        current = snap_point(scene_point)
        rect = QRectF(self._box_origin, current).normalized()
        self._box_preview.setRect(rect)

    def _finish_box(self):
        if self._box_preview is None or self._box_room_item is None:
            self.cancel_draft()
            return

        rect = self._box_preview.rect()
        room_item = self._box_room_item
        self.cancel_draft()

        if rect.width() < 20 or rect.height() < 20:
            return      # too small to be a real drag; treat it as a stray click

        # Convert from scene coordinates into the room's own coordinates,
        # because that is how containers are stored.
        top_left = room_item.mapFromScene(rect.topLeft())

        room = room_item.room
        container = Container(
            name=f"Container {len(room.containers) + 1}",
            color=theme.SWATCHES[(len(room.containers) + 2) % len(theme.SWATCHES)],
            x=snap(top_left.x()), y=snap(top_left.y()),
            w=rect.width(), h=rect.height(),
        )
        item = room_item.add_container(container)

        self.set_mode(MODE_SELECT)
        self.scene().clearSelection()
        item.setSelected(True)

    # -- deleting -----------------------------------------------------------------

    def delete_selection(self):
        """Delete whatever is selected. Containers first, then rooms."""
        for item in list(self.scene().selectedItems()):
            if isinstance(item, ContainerItem):
                room_item = item.room_item
                self.profile.delete_container(item.container.id)
                room_item.rebuild()
                self.dataChanged.emit()
                self.itemSelected.emit(None)
                return

        for item in list(self.scene().selectedItems()):
            if isinstance(item, RoomItem):
                room = item.room
                self.profile.delete_room(room.id)
                self.remove_room_item(room)
                self.dataChanged.emit()
                self.itemSelected.emit(None)
                return

    # -- the grid -------------------------------------------------------------------

    def drawBackground(self, painter, rect):
        """Paint the graph-paper grid behind everything else.

        Qt calls this with `rect` set to just the part of the scene that needs
        repainting, so we only ever draw the lines actually on screen -- this
        stays fast however far you pan.
        """
        painter.fillRect(rect, QColor(theme.CANVAS_BG))

        grid = theme.GRID_SIZE
        # Below about 5 screen pixels apart, grid lines stop reading as a grid
        # and start looking like noise, so we drop them.
        if grid * self._zoom < 5:
            return

        left = int(rect.left()) - (int(rect.left()) % grid)
        top = int(rect.top()) - (int(rect.top()) % grid)

        minor_pen = QPen(QColor(theme.GRID_MINOR))
        minor_pen.setCosmetic(True)      # stays 1px wide however far you zoom
        major_pen = QPen(QColor(theme.GRID_MAJOR))
        major_pen.setCosmetic(True)
        origin_pen = QPen(QColor(theme.CANVAS_ORIGIN))
        origin_pen.setCosmetic(True)
        origin_pen.setWidth(2)

        major_every = theme.GRID_MAJOR_EVERY * grid

        x = left
        while x < rect.right():
            if x == 0:
                painter.setPen(origin_pen)
            elif x % major_every == 0:
                painter.setPen(major_pen)
            else:
                painter.setPen(minor_pen)
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += grid

        y = top
        while y < rect.bottom():
            if y == 0:
                painter.setPen(origin_pen)
            elif y % major_every == 0:
                painter.setPen(major_pen)
            else:
                painter.setPen(minor_pen)
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += grid

    # -- view helpers -----------------------------------------------------------------

    def fit_to_rooms(self):
        """Zoom and centre so the whole floor is visible."""
        if not self.room_items:
            self.reset_zoom()
            return

        bounds = QRectF()
        for room_item in self.room_items:
            rect = room_item.mapToScene(room_item.boundingRect()).boundingRect()
            bounds = rect if bounds.isNull() else bounds.united(rect)

        bounds = bounds.adjusted(-60, -60, 60, 60)
        self.fitInView(bounds, Qt.KeepAspectRatio)

        # fitInView changes the transform directly, so read the resulting
        # scale back out rather than trying to predict it.
        self._zoom = self.transform().m11()

    def reset_zoom(self):
        self.resetTransform()
        self._zoom = 1.0
        self.centerOn(0, 0)

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

    SELECT     click to select, then the room edit mode below decides what
               dragging does. Double-click a room to focus it.
    DRAW_ROOM  click to place each corner, click the first corner again (or
               press Enter) to close the shape
    ADD_BOX    drag a rectangle inside a room to create a container there

MOVE, RESIZE, EDIT SHAPE
------------------------
A second, separate setting, held in `room_edit_mode` and shared by every
room on the canvas. It answers "what does dragging a selected room do?":
move it, stretch it, or pull its corners about. Picking one sticks as you
click from room to room, which is why it lives on the view rather than on
each room.

A room can also be LOCKED, which overrules all three: no dragging, no
handles, and a dashed outline so you can see why.

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
    QGraphicsPathItem, QGraphicsScene, QGraphicsView, QGraphicsRectItem, QMenu,
)

import theme
from floor_items import (
    EDIT_MOVE, EDIT_RESIZE, EDIT_VERTICES, ContainerItem, RoomItem,
    VertexHandle, snap, snap_point, qcolor,
)
from models import Container, Room, ROOM_PRESETS, copy_name, duplicate

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
DRAG_THRESHOLD = 4       # move this far with the right button and it is a pan


class FloorView(QGraphicsView):
    """The drawing surface for one floor."""

    # Announcements to the rest of the app. The view never touches the
    # inspector or the save file directly -- it just says what happened.
    itemSelected = Signal(object)    # a Room, a Container, or None
    dataChanged = Signal()           # something was edited; please autosave
    roomFocused = Signal(object)     # a Room, or None
    modeChanged = Signal(str)
    renameRequested = Signal(object)     # a Room or a Container
    addItemRequested = Signal(object)    # a Container
    editModeChanged = Signal(str)        # which handles rooms are showing
    roomResized = Signal(object)         # a Room, mid-drag as well as after
    containerResized = Signal(object)    # a Container, mid-drag too

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
        # Right button state: where it went down, whether it has moved far
        # enough to count as a pan, and whether the menu that follows should
        # be swallowed because it has.
        self._right_press = None
        self._right_panned = False
        self._swallow_menu = False
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
        # Move is the first thing anyone does with a floor plan, so it
        # is where the canvas starts.
        self.room_edit_mode = EDIT_MOVE

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
        """Switch every room between Move, Resize and Edit shape.

        The view owns this setting. The inspector used to keep its own copy,
        which meant changing the mode from the canvas menu left the
        inspector's buttons showing the old one. Now the view announces the
        change and the inspector follows.
        """
        if mode == self.room_edit_mode:
            return

        self.room_edit_mode = mode
        for room_item in self.room_items:
            room_item.set_edit_mode(mode)

        self.editModeChanged.emit(mode)

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
        """Stretch a room to an exact size. Used by the inspector's W/H boxes.

        Refuses on a locked room. The inspector grays the boxes out anyway,
        but this is a public method and the lock should hold whoever calls it.
        """
        if room.locked:
            return
        for room_item in self.room_items:
            if room_item.room.id == room.id:
                room_item.resize_room(width, height)
                self.dataChanged.emit()
                return

    def reveal_container(self, container_id):
        """Select a container, center the view on it, and make it blink.

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

    # -- duplicating ---------------------------------------------------------

    def duplicate_selection(self):
        """Ctrl+D. Copy whatever is selected on the canvas.

        Containers are checked first. A container sits inside a room, so when
        one is selected the room usually is not, but if both somehow are then
        the smaller, more specific thing is what you meant.
        """
        for room_item in self.room_items:
            for container_item in room_item.container_items:
                if container_item.isSelected():
                    self.duplicate_container(container_item.container)
                    return

        for room_item in self.room_items:
            if room_item.isSelected():
                self.duplicate_room(room_item.room)
                return

    def duplicate_room(self, room):
        """Copy a room, its shape, its tags and its containers.

        The copy lands one grid square down and right so it is visibly a
        second thing rather than sitting exactly on top of the original, and
        it arrives selected so the next thing you do lands on the copy.
        """
        if self.floor is None:
            return

        made = duplicate(room, copy_name(
            room.name, [r.name for r in self.floor.rooms]))
        made.x = room.x + theme.GRID_SIZE
        made.y = room.y + theme.GRID_SIZE
        # A duplicate of a locked room is a new room you are still placing,
        # so it does not inherit the lock.
        made.locked = False

        self.floor.rooms.append(made)

        item = RoomItem(made, self.profile, self)
        item.set_edit_mode(self.room_edit_mode)
        self.scene().addItem(item)
        self.room_items.append(item)

        self.scene().clearSelection()
        item.setSelected(True)
        self.dataChanged.emit()

    def duplicate_container(self, container):
        """Copy a container inside the same room.

        Offset like a room copy, then clamped by resize_to, so duplicating a
        container already against the far wall puts the copy beside it rather
        than outside the room.
        """
        for room_item in self.room_items:
            if container not in room_item.room.containers:
                continue

            made = duplicate(container, copy_name(
                container.name, [c.name for c in room_item.room.containers]))
            item = room_item.add_container(made)
            item.resize_to(container.x + theme.GRID_SIZE,
                           container.y + theme.GRID_SIZE,
                           container.w, container.h)
            item.set_editable(room_item.focused)

            # No dataChanged here: add_container already asked for a save, and
            # the autosave is debounced, so the copy's final position is what
            # actually reaches the disk.
            self.scene().clearSelection()
            item.setSelected(True)
            return

    def set_room_locked(self, room_item, locked):
        """Lock or unlock one room, and save the change."""
        room_item.set_locked(locked)
        self.itemSelected.emit(room_item.room)   # redraw the inspector
        self.dataChanged.emit()

    def notify_container_resized(self, container):
        """Same idea as notify_resized, for a container being stretched."""
        self.containerResized.emit(container)

    def notify_resized(self, room):
        """Called by a room every time its size changes, including partway
        through a drag.

        Deliberately separate from notify_changed. This one fires on every
        mouse move while a handle is held, so it must not drag an autosave
        along with it -- that would write the file dozens of times crossing
        the floor. It only tells whoever is displaying the size to catch up.
        """
        self.roomResized.emit(room)

    # -- modes ---------------------------------------------------------------

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.cancel_draft()
        self.mode = mode

        # Reaching for a drawing tool means you are done with whatever was
        # selected. Leaving it selected left the inspector showing a room
        # you were no longer working on, with its handles still out, while
        # you drew a different one somewhere else.
        if mode != MODE_SELECT:
            self.scene().clearSelection()

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
        # Same reasoning as set_mode: arming a shape means you are drawing a
        # new room, not editing the old one. Needed here as well because the
        # early return below skips set_mode entirely.
        self.scene().clearSelection()

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

    def _pan_by(self, delta):
        """Scroll the view by a mouse delta.

        Panning by moving the scrollbars keeps the scene coordinates
        untouched, which matters: nothing else in the app has to know the view
        has been scrolled.
        """
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() - int(delta.x()))
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - int(delta.y()))

    def mousePressEvent(self, event):
        scene_point = self.mapToScene(event.position().toPoint())

        # Middle and right both pan, whatever mode we are in.
        #
        # Right needs one extra idea: a right click that does not move is
        # still a request for the context menu. So the press only ARMS a pan,
        # and the first mouse move past a few pixels turns it into a real one.
        # Release then decides which gesture it was.
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.RightButton:
            self._right_press = event.position()
            self._right_panned = False
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
        # An armed right button turns into a pan once it has actually moved.
        # Without the threshold the tiny wobble in a normal click would count
        # as a drag and swallow the menu.
        if self._right_press is not None and (event.buttons() & Qt.RightButton):
            travelled = event.position() - self._right_press
            if (not self._right_panned
                    and max(abs(travelled.x()),
                            abs(travelled.y())) < DRAG_THRESHOLD):
                return

            if not self._right_panned:
                self._right_panned = True
                self.setCursor(Qt.ClosedHandCursor)

            self._pan_by(event.position() - self._right_press)
            self._right_press = event.position()
            return

        if self._panning:
            # Panning by moving the scrollbars keeps the scene coordinates
            # untouched, which matters -- nothing else in the app has to know
            # the view has been scrolled.
            self._pan_by(event.position() - self._pan_start)
            self._pan_start = event.position()
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
        if event.button() == Qt.RightButton and self._right_press is not None:
            self._right_press = None
            if self._right_panned:
                # It was a pan, so the menu that Qt is about to ask for is not
                # what the person meant. contextMenuEvent checks this flag.
                self._swallow_menu = True
                self.setCursor(Qt.ArrowCursor if self.mode == MODE_SELECT
                               else Qt.CrossCursor)
            return

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

            # While editing an outline, a double-click on the room means "put
            # a corner here", not "go inside". You are working on the shape,
            # so that is the more useful reading of the gesture.
            if (room_item is not None
                    and room_item.isSelected()
                    and not room_item.focused
                    and self.room_edit_mode == EDIT_VERTICES):
                room_item.add_vertex_near(room_item.mapFromScene(scene_point))
                return

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
        # be needlessly fussy -- you can resize it immediately afterward.
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

    # -- right-click menus -------------------------------------------------------

    def contextMenuEvent(self, event):
        """Build a menu that depends on what you right-clicked.

        Four different things can be under the cursor, and each gets the
        actions that make sense for it. A menu offering "Delete room" when you
        clicked bare canvas is worse than no menu at all.
        """
        # A right drag just panned the view, so the menu the window system is
        # now offering is the tail end of a gesture that meant something else.
        if self._swallow_menu:
            self._swallow_menu = False
            return

        if self.profile is None or self.floor is None:
            return

        scene_point = self.mapToScene(event.pos())
        clicked = self.itemAt(event.pos())
        room_item = self._room_item_at(scene_point)

        # A container is drawn as a child of its room, so a click can land on
        # it rather than the room. Walk up the parents to find out.
        container_item = None
        node = clicked
        while node is not None:
            if isinstance(node, ContainerItem):
                container_item = node
                break
            node = node.parentItem()

        # Right-clicking something selects it first. Without this you could
        # pick "Edit shape handles" on a room that was never selected, set the
        # mode, and see nothing happen -- because handles only show on the
        # selected room. Acting on a thing you have not pointed at is not a
        # thing any other app does either.
        if container_item is not None and not container_item.isSelected():
            self.scene().clearSelection()
            container_item.setSelected(True)
        elif (room_item is not None
                and not isinstance(clicked, VertexHandle)
                and not room_item.isSelected()):
            self.scene().clearSelection()
            room_item.setSelected(True)

        menu = QMenu(self)

        if isinstance(clicked, VertexHandle):
            self._build_vertex_menu(menu, clicked)
        elif container_item is not None:
            self._build_container_menu(menu, container_item)
        elif room_item is not None:
            self._build_room_menu(menu, room_item, scene_point)
        else:
            self._build_canvas_menu(menu)

        if not menu.isEmpty():
            menu.exec(event.globalPos())

    def _add_room_submenu(self, menu):
        """The "Add room" branch, shared by the canvas and room menus."""
        add_room = menu.addMenu("Add room")
        add_room.addAction("Draw room…").triggered.connect(
            lambda: self.set_mode(MODE_DRAW_ROOM))

        presets = add_room.addMenu("Preset shape")
        for name, builder in ROOM_PRESETS:
            # Default argument again: without b=builder every entry would use
            # whichever shape happened to be last in the list.
            presets.addAction(name).triggered.connect(
                lambda checked=False, b=builder: self.set_shape_tool(b))

    def _build_canvas_menu(self, menu):
        self._add_room_submenu(menu)
        menu.addSeparator()
        menu.addAction("Fit floor to window").triggered.connect(
            self.fit_to_rooms)
        menu.addAction("Reset zoom").triggered.connect(self.reset_zoom)

    def _build_room_menu(self, menu, room_item, scene_point):
        menu.addAction("Add container here").triggered.connect(
            lambda: self._add_container_at(room_item, scene_point))
        menu.addSeparator()

        if room_item is self.focused_room_item:
            menu.addAction("Stop working in this room").triggered.connect(
                lambda: self.set_focused_room(None))
        else:
            menu.addAction("Work inside this room").triggered.connect(
                lambda: self.set_focused_room(room_item))

        # A checkable set, so the menu also tells you which mode you are in.
        # Disabled on a locked room, where none of them would do anything.
        locked = room_item.room.locked
        for text, mode in (("Move", EDIT_MOVE),
                           ("Resize", EDIT_RESIZE),
                           ("Edit shape", EDIT_VERTICES)):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(self.room_edit_mode == mode)
            action.setEnabled(not locked)
            action.triggered.connect(
                lambda checked=False, m=mode: self.set_room_edit_mode(m))

        menu.addSeparator()
        menu.addAction("Unlock room" if locked else "Lock room").triggered.connect(
            lambda: self.set_room_locked(room_item, not locked))

        menu.addSeparator()
        menu.addAction("Duplicate room   Ctrl+D").triggered.connect(
            lambda: self.duplicate_room(room_item.room))
        menu.addAction("Rename…").triggered.connect(
            lambda: self.renameRequested.emit(room_item.room))
        menu.addAction("Delete room").triggered.connect(
            lambda: self._delete_room_item(room_item))

        menu.addSeparator()
        self._add_room_submenu(menu)

    def _build_container_menu(self, menu, container_item):
        menu.addAction("Add item here…").triggered.connect(
            lambda: self.addItemRequested.emit(container_item.container))
        menu.addSeparator()
        menu.addAction("Duplicate container   Ctrl+D").triggered.connect(
            lambda: self.duplicate_container(container_item.container))
        menu.addAction("Rename…").triggered.connect(
            lambda: self.renameRequested.emit(container_item.container))
        menu.addAction("Delete container").triggered.connect(
            lambda: self._delete_container_item(container_item))

    def _build_vertex_menu(self, menu, handle):
        room = handle.room_item.room
        action = menu.addAction("Remove this corner")
        # Below three corners a polygon stops enclosing anything, so the model
        # refuses. Better to gray the option out than to offer it and fail.
        action.setEnabled(len(room.points) > 3)
        if not action.isEnabled():
            action.setText("Remove this corner (needs at least 3)")
        action.triggered.connect(
            lambda: handle.room_item.remove_vertex(handle.index))

    # -- actions the menus call --------------------------------------------------

    def _add_container_at(self, room_item, scene_point):
        """Drop a default-sized container where you right-clicked."""
        local = room_item.mapFromScene(scene_point)
        left, top, width, height = room_item.room.bounds()

        box_width = min(120.0, max(40.0, width * 0.4))
        box_height = min(90.0, max(40.0, height * 0.4))

        # Center it on the click, then pull it back inside the walls.
        x = snap(min(max(local.x() - box_width / 2, left),
                     left + width - box_width))
        y = snap(min(max(local.y() - box_height / 2, top),
                     top + height - box_height))

        existing = len(room_item.room.containers)
        container = Container(
            name=f"Container {existing + 1}",
            color=theme.SWATCHES[(existing + 2) % len(theme.SWATCHES)],
            x=x, y=y, w=box_width, h=box_height,
        )
        item = room_item.add_container(container)
        self.scene().clearSelection()
        item.setSelected(True)

    def _delete_room_item(self, room_item):
        room = room_item.room
        self.profile.delete_room(room.id)
        self.remove_room_item(room)
        self.itemSelected.emit(None)
        self.dataChanged.emit()

    def _delete_container_item(self, container_item):
        room_item = container_item.room_item
        self.profile.delete_container(container_item.container.id)
        room_item.rebuild()
        self.itemSelected.emit(None)
        self.dataChanged.emit()

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
        """Zoom and center so the whole floor is visible."""
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

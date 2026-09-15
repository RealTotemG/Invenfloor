"""
layout_section.py
=================

The "Layout" half of the app: the floor stack down the left, the toolbar
across the top, the canvas in the middle, and the inspector on the right.

This file is the wiring. The canvas knows how to draw, the inspector knows how
to edit, the floor strip knows how to list floors -- none of them know about
each other. This class connects their signals together and is the only place
that knows they all exist. When you want to change how a piece behaves, you
change that piece; when you want to change how they cooperate, you change
here.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QButtonGroup,
    QScrollArea, QMenu, QStackedWidget,
)

import theme
from floor_view import (
    FloorView, MODE_ADD_BOX, MODE_ADD_SHAPE, MODE_DRAW_ROOM, MODE_SELECT,
)
from inspector import Inspector
from room_view_3d import RoomView3D
from models import Floor, ROOM_PRESETS, copy_name, duplicate_floor, short
from widgets import (
    ElidingLabel, NameColorDialog, ToggleSwitch, button, confirm, divider,
    label,
)

STRIP_WIDTH = 190


class FloorStrip(QWidget):
    """The floor stack: highest floor at the top, like a building seen edge-on.

    The up and down arrows step through it. If you try to go up from the top
    floor, or down from the bottom, the app offers to create that floor rather
    than doing nothing -- which is usually exactly what you were about to ask
    for anyway.
    """

    floorSelected = Signal(int)          # index into profile.floors
    createRequested = Signal(str)        # "above" or "below"
    editRequested = Signal(int)
    deleteRequested = Signal(int)
    duplicateRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedWidth(STRIP_WIDTH)
        self.profile = None
        self.current_index = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                 theme.SPACE_MD, theme.SPACE_MD)
        outer.setSpacing(theme.SPACE_SM)

        outer.addWidget(label("FLOORS", "hint"))

        self._up = button("▲  Floor above", "ghost",
                          lambda: self._step(+1))
        outer.addWidget(self._up)

        # The list of floors scrolls, so a tall building still fits.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        outer.addWidget(self._scroll, 1)

        self._down = button("▼  Floor below", "ghost",
                            lambda: self._step(-1))
        outer.addWidget(self._down)

        outer.addWidget(divider())

        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_XS)
        rename = button("Edit", "ghost",
                        lambda: self.editRequested.emit(self.current_index))
        remove = button("Delete", "ghost",
                        lambda: self.deleteRequested.emit(self.current_index))
        actions.addWidget(rename)
        actions.addWidget(remove)
        outer.addLayout(actions)

    def set_profile(self, profile, current_index):
        self.profile = profile
        self.current_index = current_index
        self.rebuild()

    def _step(self, direction):
        """Move one floor up (+1) or down (-1).

        Off the end of the stack, ask to create a new floor there instead.
        """
        if self.profile is None:
            return

        target = self.current_index + direction
        if 0 <= target < len(self.profile.floors):
            self.floorSelected.emit(target)
        else:
            self.createRequested.emit("above" if direction > 0 else "below")

    def rebuild(self):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_XS)

        if self.profile is not None:
            # Highest floor first, so the list reads like a building looks.
            for index in reversed(range(len(self.profile.floors))):
                layout.addWidget(self._floor_row(index))

        layout.addStretch()
        self._scroll.setWidget(holder)

        has_floors = self.profile is not None and bool(self.profile.floors)
        self._up.setEnabled(has_floors)
        self._down.setEnabled(has_floors)

    def _floor_row(self, index):
        floor = self.profile.floors[index]
        selected = (index == self.current_index)

        row = QFrame()
        row.setCursor(Qt.PointingHandCursor)
        background = theme.ACCENT_SOFT if selected else theme.BG_CARD
        border = theme.ACCENT if selected else theme.BORDER
        row.setStyleSheet(f"""
            QFrame {{
                background-color: {background};
                border: 1px solid {border};
                border-radius: {theme.RADIUS_MD}px;
            }}
        """)

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(theme.SPACE_SM, 7, theme.SPACE_SM, 7)
        row_layout.setSpacing(theme.SPACE_SM)

        dot = QFrame()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background-color: {floor.color}; border-radius: 4px;")
        row_layout.addWidget(dot)

        text = QVBoxLayout()
        text.setSpacing(0)
        name = ElidingLabel(short(floor.name))
        if short(floor.name) != floor.name:
            name.setToolTip(floor.name)
        name.setStyleSheet(f"color: {theme.TEXT}; background: transparent; "
                           f"border: none;")
        text.addWidget(name)
        count = QLabel(f"{len(floor.rooms)} room"
                       + ("" if len(floor.rooms) == 1 else "s"))
        count.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px; "
            f"background: transparent; border: none;")
        text.addWidget(count)
        row_layout.addLayout(text, 1)

        # QFrame has no clicked signal, so we borrow its mouse event. Assigning
        # a function to an instance like this is a small Python trick that
        # saves writing a whole subclass for one line of behavior.
        def on_click(event, i=index):
            if event.button() == Qt.LeftButton:
                self.floorSelected.emit(i)

        def on_menu(event, i=index):
            self.row_menu(i, event.globalPos())

        row.mouseReleaseEvent = on_click
        row.contextMenuEvent = on_menu
        return row

    def row_menu(self, index, global_point):
        """The right-click menu on a floor row.

        The same actions as the buttons at the foot of the strip, but aimed at
        the floor you clicked rather than the one that happens to be selected.
        Right-clicking a floor is you pointing at it, so pointing is enough --
        you should not have to select it first.
        """
        menu = QMenu(self)
        menu.addAction("Duplicate floor",
                       lambda: self.duplicateRequested.emit(index))
        menu.addAction("Rename floor",
                       lambda: self.editRequested.emit(index))
        menu.addSeparator()
        menu.addAction("Delete floor",
                       lambda: self.deleteRequested.emit(index))
        menu.exec(global_point)


class LayoutSection(QWidget):
    """Floors, rooms and containers -- the visual half of the app."""

    dataChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None
        self.current_index = -1

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_toolbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.strip = FloorStrip()
        self.strip.floorSelected.connect(self.show_floor)
        self.strip.createRequested.connect(self._create_floor)
        self.strip.editRequested.connect(self._edit_floor)
        self.strip.deleteRequested.connect(self._delete_floor)
        self.strip.duplicateRequested.connect(self._duplicate_floor)
        body.addWidget(self.strip)

        self.view = FloorView()
        self.view.itemSelected.connect(self._on_item_selected)
        self.view.dataChanged.connect(self._on_data_changed)
        self.view.roomFocused.connect(self._on_room_focused)
        self.view.modeChanged.connect(self._on_mode_changed)
        self.view.renameRequested.connect(self._rename_subject)
        self.view.addItemRequested.connect(self._add_item_to_container)

        # The flat canvas and the 3D room view take turns in the same slot.
        # Only one is ever visible, and the 3D one only while you are inside a
        # room with the toggle on, so with 3D off this stack behaves exactly
        # as the plain canvas always did.
        self.room_3d = RoomView3D()
        self.room_3d.itemSelected.connect(self._on_item_selected)
        self.room_3d.dataChanged.connect(self._on_data_changed)
        self.room_3d.addItemRequested.connect(self._add_item_to_container)
        self.room_3d.renameRequested.connect(self._rename_subject)
        self.room_3d.deleteRequested.connect(self._delete_container)
        self.room_3d.exitRequested.connect(lambda: self.view.set_focused_room(None))

        self._canvas_stack = QStackedWidget()
        self._canvas_stack.addWidget(self.view)
        self._canvas_stack.addWidget(self.room_3d)
        body.addWidget(self._canvas_stack, 1)

        self.inspector = Inspector()
        self.inspector.dataChanged.connect(self._on_inspector_changed)
        self.inspector.focusRoomRequested.connect(self._focus_room)
        self.view.roomResized.connect(self.inspector.room_resized)
        self.inspector.resizeRoomRequested.connect(self._resize_room)
        self.inspector.lockChanged.connect(self._set_room_locked)
        self.inspector.resizeContainerRequested.connect(
            self._resize_container)
        self.inspector.tierCountChanged.connect(self._set_tier_count)
        self.inspector.heightChanged.connect(self._set_height)
        self.view.containerResized.connect(
            self.inspector.container_resized)
        self.room_3d.containerResized.connect(
            self.inspector.container_resized)
        self.inspector.editModeChanged.connect(self.view.set_room_edit_mode)
        self.inspector.deletedRoom.connect(self._delete_room)
        self.inspector.deletedContainer.connect(self._delete_container)

        # Connected here rather than up with the other view signals, because
        # the inspector does not exist yet at that point in this method.
        self.view.editModeChanged.connect(self.inspector.set_edit_mode)
        body.addWidget(self.inspector)

        outer.addLayout(body, 1)

        # Shown instead of the canvas when a profile has no floors yet.
        self._empty_notice = QLabel()
        self._empty_notice.hide()

    # -- toolbar -------------------------------------------------------------

    def _build_toolbar(self):
        bar = QFrame()
        bar.setObjectName("topBar")
        # A MINIMUM height, not a fixed one. A fixed height that turns out to
        # be a pixel or two short of what the buttons need is exactly how text
        # ends up with its top and bottom shaved off.
        bar.setMinimumHeight(54)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM,
                                  theme.SPACE_MD, theme.SPACE_SM)
        layout.setSpacing(theme.SPACE_SM)

        self._floor_label = QLabel("No floor")
        self._floor_label.setStyleSheet(
            f"font-size: {theme.FONT_SIZE_LG}px; font-weight: 600;")
        layout.addWidget(self._floor_label)

        layout.addSpacing(theme.SPACE_LG)

        # The three tools. A QButtonGroup makes them behave like radio
        # buttons: exactly one is pressed in at any time.
        self._tools = QButtonGroup(self)
        self._tools.setExclusive(True)

        self._select_button = self._tool_button("Select", MODE_SELECT)
        self._draw_button = self._tool_button("Draw room", MODE_DRAW_ROOM)
        self._box_button = self._tool_button("Add container", MODE_ADD_BOX)

        # Order matters here. Draw room and Shape both make a room, so they sit
        # together, and Add container comes after them because it is the next
        # thing you do rather than another way of doing the same thing.
        layout.addWidget(self._select_button)
        layout.addWidget(self._draw_button)
        layout.addWidget(self._build_shape_button())
        layout.addWidget(self._box_button)

        self._select_button.setChecked(True)

        layout.addSpacing(theme.SPACE_MD)

        self._hint = QLabel("")
        self._hint.setObjectName("hint")
        layout.addWidget(self._hint)

        layout.addStretch()

        # A switch rather than a pressed-in button. This is a setting that is
        # either on or off, and its effect shows up somewhere else entirely
        # (inside a room), so it has to say which way it is set without you
        # having to go and check.
        self._view_3d_button = ToggleSwitch("3D room")
        self._view_3d_button.setChecked(True)
        self._view_3d_button.setToolTip(
            "Show a room in 3D when you step inside it. "
            "Double-click a room to step in.")
        self._view_3d_button.clicked.connect(self._toggle_3d)
        layout.addWidget(self._view_3d_button)

        layout.addWidget(button("Fit", "ghost", self._fit,
                                "Zoom so everything is visible"))
        layout.addWidget(button("100%", "ghost", self._reset_zoom))

        return bar

    def _fit(self):
        """Fit whichever view is showing. One button, two views."""
        if self.showing_3d():
            self.room_3d.fit()
        else:
            self.view.fit_to_rooms()

    def _reset_zoom(self):
        if self.showing_3d():
            self.room_3d.reset_zoom()
        else:
            self.view.reset_zoom()

    def _tool_button(self, text, mode):
        tool = button(text, "ghost")
        tool.setCheckable(True)
        tool.clicked.connect(lambda: self.view.set_mode(mode))
        self._tools.addButton(tool)
        return tool

    def _build_shape_button(self):
        """The preset shapes dropdown.

        The menu is built from ROOM_PRESETS in models.py, so adding a new
        shape there makes it appear here with no changes to this file.

        It is checkable but deliberately NOT in the tool button group: a group
        insists one of its buttons is always pressed, and this one needs to be
        able to un-press when you go back to Select.
        """
        self._shape_button = button("Shape ▾", "ghost")
        self._shape_button.setCheckable(True)
        self._shape_button.setToolTip(
            "Drop in a ready-made room shape, then drag out its size")

        menu = QMenu(self._shape_button)
        for name, builder in ROOM_PRESETS:
            action = menu.addAction(name)
            # default argument again -- without b=builder every entry in the
            # menu would end up using the last shape in the list.
            action.triggered.connect(
                lambda checked=False, b=builder: self.view.set_shape_tool(b))

        self._shape_button.setMenu(menu)
        return self._shape_button

    def _on_mode_changed(self, mode):
        """Keep the toolbar and the hint text in step with the canvas."""
        buttons = {
            MODE_SELECT: self._select_button,
            MODE_DRAW_ROOM: self._draw_button,
            MODE_ADD_BOX: self._box_button,
        }

        # Turning exclusivity off for a moment is the only way to leave all
        # three unchecked, which is what we want while a shape tool is armed.
        self._tools.setExclusive(False)
        for tool in buttons.values():
            tool.setChecked(False)
        if mode in buttons:
            buttons[mode].setChecked(True)
        self._tools.setExclusive(True)

        self._shape_button.setChecked(mode == MODE_ADD_SHAPE)

        hints = {
            MODE_SELECT: "",
            MODE_DRAW_ROOM: "Click each corner · click the first corner "
                            "again or press Enter to finish · Esc cancels",
            MODE_ADD_BOX: "Drag a box inside a room · Esc cancels",
            MODE_ADD_SHAPE: "Drag out the shape, or click once for a default "
                            "size · Esc cancels",
        }
        self._hint.setText(hints[mode])

        # The 3D view has its own Add container drag, so the same toolbar
        # button arms whichever canvas is showing.
        self.room_3d.set_adding(self.showing_3d() and mode == MODE_ADD_BOX)

    # -- loading -------------------------------------------------------------

    def set_profile(self, profile):
        self.profile = profile
        self.inspector.set_profile(profile)

        # The toggle is a per-profile setting, so the button has to show what
        # THIS profile says rather than whatever the last one did.
        self._view_3d_button.blockSignals(True)
        self._view_3d_button.setChecked(profile.view_3d)
        self._view_3d_button.blockSignals(False)
        self._say_where_3d_is()

        if not profile.floors:
            # A profile with no floors is useless, so give it one rather than
            # showing an empty screen with nothing to click.
            profile.floors.append(Floor(name="Ground Floor",
                                        color=theme.SWATCHES[0]))
            self.dataChanged.emit()

        self.current_index = 0
        self.strip.set_profile(profile, self.current_index)
        self.show_floor(0)

    def show_floor(self, index):
        if self.profile is None or not self.profile.floors:
            return
        index = max(0, min(index, len(self.profile.floors) - 1))

        self.current_index = index
        floor = self.profile.floors[index]

        self._floor_label.setText(short(floor.name))
        self._floor_label.setToolTip(floor.name)
        self.view.set_floor(self.profile, floor)
        self.view.fit_to_rooms()
        self.strip.set_profile(self.profile, index)
        # set_floor drops the focused room, so the 3D view has nothing left to
        # show and the flat canvas comes back.
        self._update_canvas()

    def refresh_views(self):
        """Repaint both canvases, not just the one on screen.

        The toggle can swap them at any moment, and a canvas that was correct
        when it was hidden is not correct when it comes back. Keeping both in
        step costs a repaint of a hidden widget and removes a whole class of
        "it only goes wrong after you toggle" bugs.
        """
        self.view.refresh()
        self.room_3d.refresh()

    def refresh(self):
        """Repaint everything from the current data."""
        self.refresh_views()
        self.strip.rebuild()
        if self.profile and 0 <= self.current_index < len(self.profile.floors):
            self._floor_label.setText(
                self.profile.floors[self.current_index].name)

    # -- reacting to the canvas -----------------------------------------------

    def _on_item_selected(self, selection):
        self.inspector.show_selection(selection)

    def _on_data_changed(self):
        # BOTH canvases, not just the 3D one. This used to refresh only the 3D
        # view, on the reasoning that the flat canvas is the thing that
        # usually raised the change and so already knows. It is not: a drag in
        # the 3D view writes straight to the model, and the flat canvas sat
        # there showing the container where it used to be until something
        # rebuilt the room.
        self.strip.rebuild()
        self.refresh_views()
        self.dataChanged.emit()

    def _on_inspector_changed(self):
        # An edit in the panel changes labels and colors on the canvas, so
        # the canvas has to repaint even though nothing moved.
        self.refresh_views()
        self.strip.rebuild()
        self.dataChanged.emit()

    def _on_room_focused(self, room):
        # The inspector needs to know too, so its "Work inside this room"
        # button can say you are already in there.
        self.inspector.set_focused_room(room)

        if room is None:
            self._hint.setText("")
            self._say_where_3d_is()
        elif self.profile is not None and self.profile.view_3d:
            self._hint.setText(
                f"Inside {short(room.name)} in 3D · Esc to step out")
        else:
            self._hint.setText(
                f"Working inside {short(room.name)} · Esc to step out")

        self._update_canvas()

    # -- the two canvases ------------------------------------------------------

    def showing_3d(self):
        """Is the 3D room view the one on screen right now?"""
        return self._canvas_stack.currentWidget() is self.room_3d

    def _want_3d(self):
        """Should it be? Only inside a room, and only if the profile says so."""
        if self.profile is None or not self.profile.view_3d:
            return False
        return self.view.focused_room_item is not None

    def _update_canvas(self):
        """Put the right view in the slot, and keep it pointed at the room.

        Called on every focus change and every toggle, so there is one place
        that decides which canvas is showing rather than three places that
        have to agree.
        """
        room = (self.view.focused_room_item.room
                if self.view.focused_room_item is not None else None)

        if self._want_3d():
            self.room_3d.set_room(self.profile, room)
            self._canvas_stack.setCurrentWidget(self.room_3d)
            self.room_3d.setFocus()
            # Stepping into 3D with a drawing tool armed would leave a tool
            # selected that this view has no use for.
            if self.view.mode not in (MODE_SELECT, MODE_ADD_BOX):
                self.view.set_mode(MODE_SELECT)
            self.room_3d.set_adding(self.view.mode == MODE_ADD_BOX)
        else:
            self.room_3d.set_room(None, None)
            self._canvas_stack.setCurrentWidget(self.view)

    def _toggle_3d(self, checked):
        """The toolbar switch. Saved with the profile, so it is remembered."""
        if self.profile is not None:
            self.profile.view_3d = bool(checked)
            self.dataChanged.emit()
        self._update_canvas()
        self._say_where_3d_is()

    def _say_where_3d_is(self):
        """Explain the switch when pressing it appears to do nothing.

        3D only replaces the canvas once you are inside a room, so out on the
        floor overview the switch is a setting for later and pressing it
        changes nothing you can see. Saying so is the difference between a
        setting and a broken button.
        """
        if self.view.focused_room_item is not None:
            return

        if self.profile is not None and self.profile.view_3d:
            self._hint.setText(
                "3D is on · double-click a room to step inside and see it")
        else:
            self._hint.setText("3D is off · rooms stay flat")

    def _set_height(self, container, height):
        """The inspector's height dropdown."""
        container.height = float(height)
        self.refresh_views()
        self.dataChanged.emit()

    def _rename_subject(self, subject):
        """Rename a room or a container from the canvas right-click menu.

        One function for both because they are the same shape: a name and a
        color. The dialog does not care which it is looking at.
        """
        dialog = NameColorDialog(self, "Rename", subject.name, subject.color)
        if not dialog.exec():
            return

        name, color = dialog.result_values()
        if not name:
            return

        subject.name = name
        subject.color = color
        self.refresh_views()
        self.inspector.show_selection(self.inspector.selection)
        self.dataChanged.emit()

    def _add_item_to_container(self, container):
        self.inspector.add_item_to(container)

    def _focus_room(self, room):
        for room_item in self.view.room_items:
            if room_item.room.id == room.id:
                self.view.set_focused_room(room_item)
                return

    def duplicate_selection(self):
        """Ctrl+D. Copies whichever room or container is selected.

        Which canvas is showing decides what "selected" means, because the two
        keep their selections separately. Floors are deliberately not
        included: they are duplicated from their own right-click menu, where
        you can see which one you are pointing at.
        """
        if self.showing_3d():
            if self.room_3d.selected is not None:
                made = self.view.duplicate_container(self.room_3d.selected)
                self.refresh_views()
                if made is not None:
                    self.room_3d.select(made)
            return

        self.view.duplicate_selection()

    def reveal_container(self, container_id):
        """Jump to a container: switch floors if needed, then flash it.

        Called when you press Find on the Items screen. The container might be
        on a floor you are not currently looking at, which is why this lives
        here rather than on the canvas -- the canvas only knows about one
        floor at a time.
        """
        if self.profile is None:
            return False

        floor, room, container = self.profile.find_container(container_id)
        if container is None:
            return False

        index = self.profile.floor_index(floor)
        if index != self.current_index:
            self.show_floor(index)

        found = self.view.reveal_container(container_id)

        # reveal_container steps out to the whole floor, which is the right
        # answer flat: it shows you WHERE on the plan the thing is. In 3D the
        # useful answer is the opposite, so go back into the room that holds
        # it and pick it out there.
        if found and self.profile.view_3d and room is not None:
            self._focus_room(room)
            self.room_3d.select(container)

        return found

    def _resize_container(self, container, width, height):
        """The inspector's W/H boxes for a container.

        Goes through the canvas item rather than writing the numbers here, so
        the clamp that keeps a container inside its room runs either way.
        """
        for room_item in self.view.room_items:
            for container_item in room_item.container_items:
                if container_item.container.id == container.id:
                    container_item.resize_to(container.x, container.y,
                                             width, height)
                    self.room_3d.refresh()
                    self.dataChanged.emit()
                    return

    def _set_tier_count(self, container, count):
        """Add or remove a tier, then rebuild the panel to show it."""
        self.profile.set_tier_count(container, count)
        self.refresh_views()
        self.inspector.show_selection(container)
        self.dataChanged.emit()

    def _set_room_locked(self, room, locked):
        """Lock or unlock a room from the inspector.

        Goes through the view rather than setting room.locked here,
        because the shape on the canvas has to stop being draggable and
        drop its handles at the same moment. One route in means the two
        cannot disagree.
        """
        for room_item in self.view.room_items:
            if room_item.room.id == room.id:
                self.view.set_room_locked(room_item, locked)
                return

    def _resize_room(self, room, width, height):
        # Note we do NOT rebuild the inspector afterward. The W/H boxes the
        # user is currently typing in live there, and replacing them mid-edit
        # would steal the keyboard focus on every keystroke.
        self.view.resize_room(room, width, height)

    # -- floors ---------------------------------------------------------------

    def _create_floor(self, position):
        """Offer to add a floor above or below the current one.

        This is what happens when you press the up arrow on the top floor --
        rather than the button doing nothing, it offers you the thing you were
        clearly reaching for.
        """
        if self.profile is None:
            return

        above = (position == "above")
        default_name = (f"Floor {len(self.profile.floors) + 1}" if above
                        else "Basement")

        dialog = NameColorDialog(
            self,
            "Add floor above" if above else "Add floor below",
            default_name,
            theme.SWATCHES[len(self.profile.floors) % len(theme.SWATCHES)])
        if not dialog.exec():
            return

        name, color = dialog.result_values()
        if not name:
            return

        floor = Floor(name=name, color=color)
        insert_at = self.current_index + 1 if above else self.current_index
        self.profile.floors.insert(insert_at, floor)

        self.dataChanged.emit()
        self.show_floor(insert_at)

    def _edit_floor(self, index):
        if self.profile is None or not (0 <= index < len(self.profile.floors)):
            return
        floor = self.profile.floors[index]

        dialog = NameColorDialog(self, "Edit floor", floor.name, floor.color)
        if not dialog.exec():
            return
        name, color = dialog.result_values()
        if not name:
            return

        floor.name = name
        floor.color = color
        self.refresh()
        self.dataChanged.emit()

    def _duplicate_floor(self, index):
        """Copy a floor with its rooms and containers, but not their contents.

        Items live in the catalog and only point at containers, so a copied
        shelf arrives empty. That is on purpose: copying the contents would
        tell you that you own twice as many things as you actually do. The
        copy lands directly above the original and opens straight away, since
        you duplicated it to work on it.
        """
        if self.profile is None or not (0 <= index < len(self.profile.floors)):
            return

        floor = self.profile.floors[index]
        made = duplicate_floor(floor, copy_name(
            floor.name, [f.name for f in self.profile.floors]))
        self.profile.floors.insert(index + 1, made)

        self.dataChanged.emit()
        self.show_floor(index + 1)

    def _delete_floor(self, index):
        if self.profile is None or not (0 <= index < len(self.profile.floors)):
            return

        if len(self.profile.floors) == 1:
            confirm(self, "Can't delete",
                    "A profile needs at least one floor.", "OK")
            return

        floor = self.profile.floors[index]
        if not confirm(
            self, "Delete floor",
            f"Delete '{floor.name}'?\n\nIts {len(floor.rooms)} room"
            f"{'' if len(floor.rooms) == 1 else 's'} and their containers go "
            f"too. Items are kept, but become unfiled."
        ):
            return

        self.profile.delete_floor(floor.id)
        self.dataChanged.emit()
        self.show_floor(min(index, len(self.profile.floors) - 1))

    # -- deleting rooms and containers -----------------------------------------

    def _delete_room(self, room):
        self.profile.delete_room(room.id)
        self.view.remove_room_item(room)
        self.inspector.show_selection(None)
        self.strip.rebuild()
        self.dataChanged.emit()

    def _delete_container(self, container):
        floor, room, _ = self.profile.find_container(container.id)
        self.profile.delete_container(container.id)
        if room is not None:
            self.view.rebuild_room(room)
        # refresh_views drops the 3D view's hold on the container that has
        # just gone, so its handles do not go on being drawn around nothing.
        self.refresh_views()
        self.inspector.show_selection(None)
        self.dataChanged.emit()

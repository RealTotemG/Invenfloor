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
    QScrollArea, QMenu,
)

import theme
from floor_view import (
    FloorView, MODE_ADD_BOX, MODE_ADD_SHAPE, MODE_DRAW_ROOM, MODE_SELECT,
)
from inspector import Inspector
from models import Floor, ROOM_PRESETS
from widgets import NameColorDialog, button, confirm, divider, label

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
        name = QLabel(floor.name)
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
            self.floorSelected.emit(i)

        row.mouseReleaseEvent = on_click
        return row


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
        body.addWidget(self.strip)

        self.view = FloorView()
        self.view.itemSelected.connect(self._on_item_selected)
        self.view.dataChanged.connect(self._on_data_changed)
        self.view.roomFocused.connect(self._on_room_focused)
        self.view.modeChanged.connect(self._on_mode_changed)
        self.view.renameRequested.connect(self._rename_subject)
        self.view.addItemRequested.connect(self._add_item_to_container)
        body.addWidget(self.view, 1)

        self.inspector = Inspector()
        self.inspector.dataChanged.connect(self._on_inspector_changed)
        self.inspector.focusRoomRequested.connect(self._focus_room)
        self.inspector.resizeRoomRequested.connect(self._resize_room)
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
        for tool in (self._select_button, self._draw_button, self._box_button):
            layout.addWidget(tool)
        self._select_button.setChecked(True)

        layout.addWidget(self._build_shape_button())

        layout.addSpacing(theme.SPACE_MD)

        self._hint = QLabel("")
        self._hint.setObjectName("hint")
        layout.addWidget(self._hint)

        layout.addStretch()

        layout.addWidget(button("Fit", "ghost", lambda: self.view.fit_to_rooms(),
                                "Zoom so the whole floor is visible"))
        layout.addWidget(button("100%", "ghost", lambda: self.view.reset_zoom()))

        return bar

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

    # -- loading -------------------------------------------------------------

    def set_profile(self, profile):
        self.profile = profile
        self.inspector.set_profile(profile)

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

        self._floor_label.setText(floor.name)
        self.view.set_floor(self.profile, floor)
        self.view.fit_to_rooms()
        self.strip.set_profile(self.profile, index)

    def refresh(self):
        """Repaint everything from the current data."""
        self.view.refresh()
        self.strip.rebuild()
        if self.profile and 0 <= self.current_index < len(self.profile.floors):
            self._floor_label.setText(
                self.profile.floors[self.current_index].name)

    # -- reacting to the canvas -----------------------------------------------

    def _on_item_selected(self, selection):
        self.inspector.show_selection(selection)

    def _on_data_changed(self):
        self.strip.rebuild()
        self.dataChanged.emit()

    def _on_inspector_changed(self):
        # An edit in the panel changes labels and colors on the canvas, so
        # the canvas has to repaint even though nothing moved.
        self.view.refresh()
        self.strip.rebuild()
        self.dataChanged.emit()

    def _on_room_focused(self, room):
        # The inspector needs to know too, so its "Work inside this room"
        # button can say you are already in there.
        self.inspector.set_focused_room(room)

        if room is None:
            self._hint.setText("")
        else:
            self._hint.setText(f"Working inside {room.name} · Esc to step out")

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
        self.view.refresh()
        self.inspector.show_selection(self.inspector.selection)
        self.dataChanged.emit()

    def _add_item_to_container(self, container):
        self.inspector.add_item_to(container)

    def _focus_room(self, room):
        for room_item in self.view.room_items:
            if room_item.room.id == room.id:
                self.view.set_focused_room(room_item)
                return

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

        return self.view.reveal_container(container_id)

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
        self.inspector.show_selection(None)
        self.dataChanged.emit()

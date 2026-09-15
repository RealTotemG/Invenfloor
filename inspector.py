"""
inspector.py
============

The panel down the right-hand side of the layout screen. It shows whatever is
currently selected on the canvas -- a room, or a container -- and lets you
rename it, recolor it, resize it, tag it, and see what is inside it.

It follows one rule: the inspector never reaches into the canvas. It edits the
data or announces what it wants, and the layout screen does the rest. So the
panel has no idea the canvas exists, and you could put it somewhere else
entirely without touching this file.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel,
    QSpinBox, QButtonGroup,
)

import theme
from floor_items import EDIT_MOVE, EDIT_RESIZE, EDIT_VERTICES
from models import Container, Item, Room, short
from widgets import (
    ColorPicker, ItemDialog, MoveToTierDialog, TagChipRow, TagPickerDialog,
    button, confirm,
    WrappingRow, divider, empty_state, label, name_field, short_label,
    wrapped,
)

PANEL_WIDTH = 300


class Inspector(QWidget):
    """Shows and edits the current canvas selection."""

    dataChanged = Signal()
    focusRoomRequested = Signal(object)
    deletedRoom = Signal(object)
    deletedContainer = Signal(object)
    resizeRoomRequested = Signal(object, float, float)   # room, width, height
    lockChanged = Signal(object, bool)                   # room, locked
    resizeContainerRequested = Signal(object, float, float)  # container, w, h
    tierCountChanged = Signal(object, int)               # container, tiers
    editModeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspector")
        self.setFixedWidth(PANEL_WIDTH)
        self.profile = None
        self.selection = None
        self.edit_mode = EDIT_MOVE
        # The two size boxes, when a room is showing. See room_resized().
        self._width_field = None
        self._height_field = None
        self._sized_room = None
        self._sized_container = None
        # Which room the canvas is currently focused on, if any. The inspector
        # has no way to find this out for itself, so the layout screen tells it.
        self.focused_room_id = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # The panel is a fixed width, so there is nowhere sideways to
        # scroll TO. Left on, Qt puts a bar along the bottom the moment
        # one widget asks for a pixel more than the column has, which
        # reads as a bug rather than as an offer.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        self.show_selection(None)

    def resizeEvent(self, event):
        """Keep the panel's contents inside the panel.

        With no horizontal scrollbar, a QScrollArea hands its widget the
        LARGER of the viewport width and the widget's own minimum. So one
        child insisting on a few pixels more than the column has does not
        produce a scrollbar, it produces content quietly sliced off at the
        right edge, which is what this looked like on Windows where the UI
        font is wider than the one it was measured against.

        Capping the body here means the panel can never draw outside itself,
        whatever gets added to it later.
        """
        super().resizeEvent(event)
        body = self._scroll.widget()
        if body is not None:
            body.setMaximumWidth(self._scroll.viewport().width())

    def set_profile(self, profile):
        self.profile = profile
        self.focused_room_id = None
        self.show_selection(None)

    def set_focused_room(self, room):
        """Told by the layout screen when the canvas focuses or unfocuses.

        Only rebuilds when the change actually affects what is on screen,
        which avoids throwing away the panel every time you click around.
        """
        new_id = room.id if room is not None else None
        if new_id == self.focused_room_id:
            return

        self.focused_room_id = new_id

        if isinstance(self.selection, Room):
            self.show_selection(self.selection)

    def add_item_to(self, container):
        """Public entry point for the canvas's right-click "Add item here"."""
        self._add_item(container)

    # -- the top-level switch ------------------------------------------------

    def show_selection(self, selection):
        """Rebuild the panel for whatever is now selected.

        Rebuilding from scratch rather than updating individual fields means
        the panel can never show a stale name or the wrong color.
        """
        self.selection = selection
        # Dropped now, and set again by whichever size block runs below.
        self._width_field = None
        self._height_field = None
        self._sized_room = None
        self._sized_container = None

        body = QWidget()
        layout = QVBoxLayout(body)
        # A little more air on the sides than top and bottom. The right
        # margin is the one that shows: without it the buttons and boxes run
        # flush into the window edge and look cut off even when they fit.
        layout.setContentsMargins(theme.SPACE_LG, theme.SPACE_MD,
                                  theme.SPACE_LG, theme.SPACE_MD)
        # Tight by default, with the blocks below adding their own space
        # where a section actually changes. At SPACE_MD every single
        # widget sat 12px from the next, including a caption and the box
        # it labels, and the gaps added up to more than the content.
        layout.setSpacing(theme.SPACE_XS)

        if isinstance(selection, Room):
            self._build_room(layout, selection)
        elif isinstance(selection, Container):
            self._build_container(layout, selection)
        else:
            self._build_empty(layout)

        layout.addStretch()
        body.setMaximumWidth(self._scroll.viewport().width())
        self._scroll.setWidget(body)

    # -- nothing selected -----------------------------------------------------

    def _build_empty(self, layout):
        layout.addWidget(label("Inspector", "sectionTitle"))
        layout.addWidget(divider())
        layout.addSpacing(theme.SPACE_LG)
        layout.addWidget(empty_state(
            "Nothing selected",
            "Click a room or a container on the floor to edit it here."))
        layout.addSpacing(theme.SPACE_XL)

        tips = QLabel(
            "<b>Shape</b> &nbsp;pick a preset and drag it out, or click once "
            "for a default size<br><br>"
            "<b>Draw room</b> &nbsp;click each corner, then the first corner "
            "again to close<br><br>"
            "<b>Resize</b> &nbsp;select a room and drag the square handles "
            "around it<br><br>"
            "<b>Add container</b> &nbsp;drag a box inside a room<br><br>"
            "<b>Double-click</b> a room to work inside it<br><br>"
            "<b>Scroll</b> to zoom, <b>middle-drag</b> to pan<br><br>"
            "<b>Delete</b> removes the selected thing")
        wrapped(tips, grow=False)
        tips.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(tips)

    # -- shared building blocks -------------------------------------------------

    def _name_and_color(self, layout, kind, subject):
        """The name box and color picker, identical for rooms and containers."""
        layout.addWidget(label(kind.upper(), "hint"))

        # name_field() carries the length cap, so the box itself refuses
        # anything longer and `rename` below can store what it is given.
        name_box = name_field(subject.name, "Name")

        def rename(text):
            subject.name = text
            self.dataChanged.emit()

        # textEdited fires only for typing, not when we set the text in code,
        # so this can never loop back on itself.
        name_box.textEdited.connect(rename)
        layout.addWidget(name_box)

        layout.addSpacing(theme.SPACE_XS)
        layout.addWidget(label("Color", "caption"))
        picker = ColorPicker(subject.color)

        def recolor(color):
            subject.color = color
            self.dataChanged.emit()

        picker.colorChanged.connect(recolor)
        layout.addWidget(picker)

    def _tags_block(self, layout, subject, subject_name):
        layout.addSpacing(theme.SPACE_SM)
        layout.addWidget(label("Tags", "caption"))

        chips = TagChipRow("No tags")
        chips.set_tags(self.profile.tags_for(subject.tag_ids))
        layout.addWidget(chips)

        def edit_tags():
            dialog = TagPickerDialog(self, self.profile, subject.tag_ids,
                                     subject_name)
            accepted = dialog.exec()
            if accepted:
                subject.tag_ids = dialog.selected_ids()
                chips.set_tags(self.profile.tags_for(subject.tag_ids))
            # A tag invented in there exists now even if the assignment was
            # cancelled, so the save has to be queued either way.
            if accepted or dialog.created_tags:
                self.dataChanged.emit()

        layout.addWidget(button("Edit tags", "ghost", edit_tags, size="sm"))

    def _mini_row(self, color, title, subtitle, badge=None, on_click=None,
                  extra=None):
        """A compact colored row used for the contents lists."""
        row = QFrame()
        row.setObjectName("card")
        row.setStyleSheet(f"""
            QFrame#card {{
                background-color: {theme.BG_CARD};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
        """)
        row_layout = QHBoxLayout(row)
        # Tighter top and bottom than the sides. These rows stack, so
        # every pixel of vertical padding is paid for once per
        # container, and a long list is what pushes the panel into
        # scrolling.
        row_layout.setContentsMargins(theme.SPACE_SM, theme.SPACE_XS,
                                      theme.SPACE_SM, theme.SPACE_XS)
        row_layout.setSpacing(theme.SPACE_SM)

        dot = QFrame()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background-color: {color}; border-radius: 4px;")
        row_layout.addWidget(dot)

        text_column = QVBoxLayout()
        text_column.setSpacing(1)
        name = short_label(title)
        name.setStyleSheet(f"color: {theme.TEXT};")
        text_column.addWidget(name)
        if subtitle:
            # A plain label, deliberately not wrapped(). wrapped() asks for a
            # MinimumExpanding height, which means "I would like to grow", and
            # with only two containers in the list there was spare room in the
            # panel for these rows to grow into. Two drawers came out as two
            # fat cards. The subtitle here is always a short count line, so it
            # has nothing to wrap anyway.
            sub = QLabel(subtitle)
            sub.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;")
            text_column.addWidget(sub)
        row_layout.addLayout(text_column, 1)

        if badge:
            count = QLabel(badge)
            count.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;")
            row_layout.addWidget(count)

        if extra is not None:
            row_layout.addWidget(extra)

        if on_click is not None:
            row_layout.addWidget(button("Edit", "ghost", on_click, size="sm"))

        return row

    # -- room -------------------------------------------------------------------

    def _build_room(self, layout, room):
        self._name_and_color(layout, "Room", room)

        layout.addSpacing(theme.SPACE_SM)
        self._size_block(layout, room)
        self._shape_mode_block(layout, room)
        self._lock_block(layout, room)

        self._tags_block(layout, room, "room")

        layout.addSpacing(theme.SPACE_SM)
        layout.addWidget(divider())
        layout.addSpacing(theme.SPACE_XS)

        containers = room.containers
        layout.addWidget(label(f"Containers ({len(containers)})", "caption"))

        if not containers:
            hint = QLabel(
                "None yet. Pick <b>Add container</b> in the toolbar and drag a "
                "box inside this room.")
            wrapped(hint, grow=False)
            hint.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
            layout.addWidget(hint)
        else:
            for container in containers:
                count = self.profile.item_count_in_container(container.id)
                layout.addWidget(self._mini_row(
                    container.color, container.name,
                    f"{count} item" + ("" if count == 1 else "s")))

        layout.addSpacing(theme.SPACE_XS)
        layout.addWidget(self._focus_button(room))

        layout.addSpacing(theme.SPACE_MD)
        layout.addWidget(divider())
        layout.addSpacing(theme.SPACE_XS)

        total_items = len(self.profile.items_in_room(room))
        layout.addWidget(label(
            f"{total_items} item" + ("" if total_items == 1 else "s") +
            " across this room", "caption"))

        layout.addSpacing(theme.SPACE_SM)

        def delete_room():
            if not confirm(
                self, "Delete room",
                f"Delete '{room.name}'?\n\nIts containers go too. Items kept "
                f"there lose that location, but stay in your catalog."
            ):
                return
            self.deletedRoom.emit(room)

        layout.addWidget(button("Delete room", "danger", delete_room))

    def _focus_button(self, room):
        """Either an invitation to go into the room, or a statement that you
        are already in it.

        A button you can still press when it would do nothing is a small lie
        about what is going on, so while this room is focused it says so and
        stops being clickable.
        """
        if self.focused_room_id == room.id:
            here = button("Currently working in this room", "ghost",
                          size="sm")
            here.setEnabled(False)
            here.setToolTip("Press Escape, or double-click the room, to step "
                            "back out")
            return here

        return button(
            "Work inside this room", "ghost",
            lambda: self.focusRoomRequested.emit(room),
            "Same as double-clicking it: dims the other rooms and lets you "
            "drag containers around", size="sm")

    def _size_block(self, layout, room):
        """Exact width and height boxes.

        The handles on the canvas are quicker, but if you know a room is four
        meters across you want to type it, not nudge it.
        """
        _, _, width, height = room.bounds()

        layout.addWidget(label("Size", "caption"))

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_SM)

        width_field = QSpinBox()
        height_field = QSpinBox()

        # Kept on the inspector so room_resized() below can update them while
        # a handle is being dragged. They are rebuilt with the panel, so these
        # never point at a widget that has gone.
        self._width_field = width_field
        self._height_field = height_field
        self._sized_room = room

        for field, value in ((width_field, width), (height_field, height)):
            field.setRange(40, 4000)
            field.setEnabled(not room.locked)
            # A spin box asks for enough room to show its largest value plus
            # its arrows, and it will not go below that on its own. Two of
            # them side by side were the widest thing in the panel, and on a
            # system with a wider UI font they pushed the whole column past
            # its own edge. An explicit minimum overrides that hint and lets
            # the row compress instead.
            field.setMinimumWidth(60)
            field.setSingleStep(theme.GRID_SIZE)
            # Set the starting value with signals off, or simply building the
            # panel would look like the user asking for a resize.
            field.blockSignals(True)
            field.setValue(int(round(value)))
            field.blockSignals(False)

        def apply_size():
            self.resizeRoomRequested.emit(
                room, float(width_field.value()), float(height_field.value()))

        width_field.valueChanged.connect(apply_size)
        height_field.valueChanged.connect(apply_size)

        width_label = QLabel("W")
        width_label.setStyleSheet(f"color: {theme.TEXT_FAINT};")
        height_label = QLabel("H")
        height_label.setStyleSheet(f"color: {theme.TEXT_FAINT};")

        row.addWidget(width_label)
        row.addWidget(width_field, 1)
        row.addWidget(height_label)
        row.addWidget(height_field, 1)
        layout.addLayout(row)

    def room_resized(self, room):
        """The canvas resized a room. Catch the two boxes up.

        Called on every step of a handle drag, so it does the smallest thing
        that works: set two numbers. Rebuilding the panel here would throw
        away the widgets being interacted with, dozens of times a second.

        Signals are blocked while setting the values, because setValue fires
        valueChanged, which would come straight back as another resize
        request for the size we already have.
        """
        if room is not self._sized_room or self._width_field is None:
            return

        _, _, width, height = room.bounds()
        for field, value in ((self._width_field, width),
                             (self._height_field, height)):
            field.blockSignals(True)
            field.setValue(int(round(value)))
            field.blockSignals(False)

    def _container_size_block(self, layout, container):
        """Exact width and height for a container.

        The same idea as the room one above, and for the same reason: the
        handles are quicker, but when you know a shelf is 60 wide you want to
        type it. Clamped by the canvas, so a number too big for the room comes
        back as the biggest that fits rather than being refused.
        """
        layout.addWidget(label("Size", "caption"))

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_SM)

        width_field = QSpinBox()
        height_field = QSpinBox()

        self._width_field = width_field
        self._height_field = height_field
        self._sized_container = container

        for field, value in ((width_field, container.w),
                             (height_field, container.h)):
            field.setRange(20, 4000)
            field.setMinimumWidth(60)
            field.setSingleStep(theme.GRID_SIZE)
            field.blockSignals(True)
            field.setValue(int(round(value)))
            field.blockSignals(False)

        def apply_size():
            self.resizeContainerRequested.emit(
                container, float(width_field.value()),
                float(height_field.value()))

        width_field.valueChanged.connect(apply_size)
        height_field.valueChanged.connect(apply_size)

        width_label = QLabel("W")
        width_label.setStyleSheet(f"color: {theme.TEXT_FAINT};")
        height_label = QLabel("H")
        height_label.setStyleSheet(f"color: {theme.TEXT_FAINT};")

        row.addWidget(width_label)
        row.addWidget(width_field, 1)
        row.addWidget(height_label)
        row.addWidget(height_field, 1)
        layout.addLayout(row)

        hint = QLabel("Switch to Resize and drag the handles, or type here. "
                      "To move it instead, double-click the room to work "
                      "inside it.")
        wrapped(hint, grow=False)
        hint.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(hint)

    def container_resized(self, container):
        """The canvas resized a container. Catch the two boxes up.

        Same shape as room_resized: runs on every step of a drag, so it does
        the smallest thing that works and blocks signals while doing it.
        """
        if container is not self._sized_container or self._width_field is None:
            return

        for field, value in ((self._width_field, container.w),
                             (self._height_field, container.h)):
            field.blockSignals(True)
            field.setValue(int(round(value)))
            field.blockSignals(False)

    def _tiers_block(self, layout, container):
        """Add tier / Remove tier, and what the tiers mean.

        A count and two buttons. Tiers are not named or colored on purpose:
        a shelf's tiers do not have names, they have positions, and "Tier 2"
        already says everything there is to say.
        """
        layout.addSpacing(theme.SPACE_XS)
        layout.addWidget(label("Tiers", "caption"))

        if container.tier_count == 0:
            note = QLabel("No tiers. Add some for a shelf or a unit with "
                          "separate levels.")
        else:
            note = QLabel(f"{container.tier_count} tier"
                          + ("" if container.tier_count == 1 else "s")
                          + ". Items can sit on a tier, or loose in the "
                            "container itself.")
        wrapped(note, grow=False)
        note.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(note)

        row = WrappingRow()
        row.add(button("Add tier", "ghost", size="sm",
                       tooltip="Divide this container into one more level",
                       on_click=lambda: self.tierCountChanged.emit(
                           container, container.tier_count + 1)))

        if container.tier_count > 0:
            row.add(button(
                "Remove tier", "ghost", size="sm",
                tooltip="Drop the last tier. Anything on it comes back to "
                        "the container itself, nothing is lost.",
                on_click=lambda: self._remove_tier(container)))

        layout.addWidget(row)

    def _move_to_tier(self, item, container, quantity, tier):
        """Ask how many and where to, then move them."""
        dialog = MoveToTierDialog(self, item, container, quantity, tier)
        if not dialog.exec():
            return

        how_many, destination = dialog.result_values()
        self.profile.move_to_tier(item, container.id, tier, destination,
                                  how_many)
        self.dataChanged.emit()
        self.show_selection(container)

    def _remove_tier(self, container):
        """Drop the last tier, warning first if anything is on it."""
        on_last = self.profile.contents_of(container.id, container.tier_count)
        if on_last and not confirm(
                self, "Remove tier",
                f"Tier {container.tier_count} has {len(on_last)} item"
                f"{'' if len(on_last) == 1 else 's'} on it.\n\n"
                f"They stay in '{container.name}', they just stop being on a "
                f"tier.", danger_text="Remove tier"):
            return
        self.tierCountChanged.emit(container, container.tier_count - 1)

    def _shape_mode_block(self, layout, room):
        """The Move / Resize / Edit shape switch.

        Three named buttons rather than a checkbox, because it is a choice
        between three things, and each one gives a drag on the room a
        different meaning. Move used to be bundled into Resize, so the same
        drag did two jobs and nothing on screen said so.

        All three are disabled on a locked room: none of them could do
        anything, and a button that does nothing is worse than a grayed one.
        """
        layout.addSpacing(theme.SPACE_XS)
        layout.addWidget(label("Mode", "caption"))

        # A wrapping row, not a plain one. Three named buttons are wider than
        # this column on a system with a wide interface font, and "Edit shape"
        # dropping to a second line is much better than it being cut in half.
        row = WrappingRow()

        group = QButtonGroup(self)
        group.setExclusive(True)

        modes = (
            ("Move", EDIT_MOVE,
             "Drag the room itself to reposition it on the floor"),
            ("Resize", EDIT_RESIZE,
             "Drag the squares to stretch the whole room, keeping its shape"),
            ("Edit shape", EDIT_VERTICES,
             "Drag the round handles to move individual corners"),
        )

        for text, mode, tip in modes:
            candidate = button(text, "ghost", size="sm", tooltip=tip)
            candidate.setCheckable(True)
            candidate.setChecked(self.edit_mode == mode)
            candidate.setEnabled(not room.locked)
            group.addButton(candidate)
            candidate.clicked.connect(
                lambda checked=False, m=mode: self._set_edit_mode(m))
            row.add(candidate)

        layout.addWidget(row)

    def _lock_block(self, layout, room):
        """The lock toggle, and a line saying what it is doing.

        The explanation only appears while locked. Saying what a lock would
        do before you have used it is noise; saying why the handles vanished
        the moment they vanish is the useful half.
        """
        layout.addSpacing(theme.SPACE_XS)

        toggle = button(
            "Unlock room" if room.locked else "Lock room",
            "ghost", size="sm",
            tooltip="A locked room cannot be moved, resized or reshaped. "
                    "You can still rename it, tag it and fill it.")
        toggle.clicked.connect(
            lambda: self.lockChanged.emit(room, not room.locked))
        layout.addWidget(toggle)

        if room.locked:
            note = QLabel("Locked: position, size and shape are held. "
                          "Renaming, tags and containers still work.")
            wrapped(note, grow=False)
            note.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; "
                f"font-size: {theme.FONT_SIZE_SM}px;")
            layout.addWidget(note)

    def set_edit_mode(self, mode):
        """Told by the canvas which handles rooms are showing.

        The canvas is the single source of truth for this. Keeping a second
        copy here and hoping the two stayed in step is exactly how the
        buttons ended up showing a mode the canvas was not in.
        """
        if mode == self.edit_mode:
            return

        self.edit_mode = mode
        if isinstance(self.selection, Room):
            self.show_selection(self.selection)

    def _set_edit_mode(self, mode):
        # Announce it and let the canvas decide; it will tell us back through
        # set_edit_mode above, so there is only ever one place that decides.
        self.editModeChanged.emit(mode)

    # -- container ----------------------------------------------------------------

    def _build_container(self, layout, container):
        floor, room, _ = self.profile.find_container(container.id)

        self._name_and_color(layout, "Container", container)

        if room is not None:
            layout.addSpacing(theme.SPACE_XS)
            layout.addWidget(label(
                f"in {short(floor.name)} / {short(room.name)}", "hint"))

        layout.addSpacing(theme.SPACE_XS)
        self._container_size_block(layout, container)
        self._tiers_block(layout, container)

        self._tags_block(layout, container, "container")

        layout.addSpacing(theme.SPACE_SM)
        layout.addWidget(divider())
        layout.addSpacing(theme.SPACE_XS)

        contents = self.profile.contents_of(container.id)
        layout.addWidget(label(f"Items ({len(contents)})", "caption"))

        if not contents:
            hint = QLabel("Nothing in here yet.")
            hint.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
            layout.addWidget(hint)
        else:
            # Grouped by tier, loose things first. contents_of already sorts
            # that way, so this just puts a heading in when the tier changes.
            current_tier = None
            for item, quantity, tier in contents:
                if container.tier_count and tier != current_tier:
                    current_tier = tier
                    layout.addSpacing(theme.SPACE_XS)
                    layout.addWidget(label(
                        "Loose in the container" if tier == 0
                        else f"Tier {tier}", "hint"))

                # If the item is also kept elsewhere, say so -- otherwise the
                # quantity here looks like the total and it is easy to think
                # you own fewer than you do.
                elsewhere = len(self.profile.locations_of(item)) - 1
                subtitle = ""
                if elsewhere > 0:
                    subtitle = (f"also in {elsewhere} other place"
                                + ("" if elsewhere == 1 else "s")
                                + f" · {item.total_quantity()} in total")

                move = None
                if container.tier_count:
                    move = button(
                        "Move", "ghost", size="sm",
                        tooltip="Move some or all of these to another tier",
                        on_click=(lambda checked=False, i=item, q=quantity,
                                  t=tier: self._move_to_tier(
                                      i, container, q, t)))

                layout.addWidget(self._mini_row(
                    item.color, item.name, subtitle,
                    badge=f"×{quantity}",
                    on_click=lambda checked=False, i=item: self._edit_item(i),
                    extra=move))

        layout.addSpacing(theme.SPACE_XS)
        layout.addWidget(button(
            "+ Add item here", "primary",
            lambda: self._add_item(container)))

        layout.addSpacing(theme.SPACE_MD)
        layout.addWidget(divider())
        layout.addSpacing(theme.SPACE_XS)

        def delete_container():
            if not confirm(
                self, "Delete container",
                f"Delete '{container.name}'?\n\nThe {len(contents)} item"
                f"{'' if len(contents) == 1 else 's'} kept here stay in your "
                f"catalog -- they just lose this location."
            ):
                return
            self.deletedContainer.emit(container)

        layout.addWidget(button("Delete container", "danger", delete_container))

    # -- item editing --------------------------------------------------------------

    def _add_item(self, container):
        dialog = ItemDialog(self, self.profile, default_container_id=container.id)
        if not dialog.exec():
            return
        values = dialog.result_values()
        if not values["name"]:
            return

        self.profile.items.append(Item(**values))
        self.dataChanged.emit()
        self.show_selection(self.selection)     # redraw the contents list

    def _edit_item(self, item):
        dialog = ItemDialog(self, self.profile, item=item)
        if not dialog.exec():
            return
        values = dialog.result_values()
        if not values["name"]:
            return

        for key, value in values.items():
            setattr(item, key, value)
        self.dataChanged.emit()
        self.show_selection(self.selection)

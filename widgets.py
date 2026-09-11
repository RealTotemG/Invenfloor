"""
widgets.py
==========

Small user-interface pieces that more than one screen needs: the color
picker, the tag chips, the little "name and color" dialog, and so on.

Anything that appears on two different screens belongs in here. That is the
whole rule. It keeps the screen files about layout and behavior rather than
about re-inventing a color picker three times.

A NOTE ON SIGNALS
-----------------
Qt widgets talk to each other with signals. A widget announces that something
happened ("my color changed") and anyone interested connects a function to
that announcement:

    picker.colorChanged.connect(my_function)

The picker has no idea who is listening or what they will do -- it just
announces. That is what stops a big app turning into a knot, and it is the
single most important Qt idea to get comfortable with.
"""

import re

from PySide6.QtCore import Qt, Signal, QSize, QRect, QPoint
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QDialog, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLineEdit, QMessageBox, QLayout, QCheckBox,
    QScrollArea, QFrame, QSpinBox, QPlainTextEdit, QComboBox, QSizePolicy,
    QListWidget, QAbstractItemView,
)

import theme
from models import Item, Placement


# ---------------------------------------------------------------------------
# SMALL HELPERS
# ---------------------------------------------------------------------------

def button(text, kind=None, on_click=None, tooltip=None, size=None):
    """Create a styled button.

    `kind` is "primary", "danger", "ghost" or None. `size` is "sm", "icon" or
    None. Both set Qt properties that the stylesheet in theme.py watches for,
    so the actual colors and paddings stay in the theme file rather than
    being written here.

    Note what is NOT here: setFixedHeight. Forcing a height smaller than the
    font needs is what clips text, and it is easy to do by accident when a row
    looks slightly too tall. Use size="sm" instead -- it trims the padding and
    lets the text keep the room it actually needs.
    """
    result = QPushButton(text)
    result.setCursor(Qt.PointingHandCursor)
    if kind:
        result.setProperty("kind", kind)
    if size:
        result.setProperty("size", size)
    if on_click:
        result.clicked.connect(on_click)
    if tooltip:
        result.setToolTip(tooltip)
    return result


def label(text, style=None):
    """Create a QLabel, optionally with one of the named styles from theme.py
    ("screenTitle", "sectionTitle", "caption", "hint")."""
    result = QLabel(text)
    if style:
        result.setObjectName(style)
    return result


def wrapped(text_label):
    """Make a label wrap its text AND actually get the height to do it.

    setWordWrap(True) on its own is not enough, and this is a genuinely nasty
    trap. A layout only asks a widget "how tall are you at this width?" if the
    widget's size POLICY says it has an answer, and QLabel does not set that
    flag for you. So the layout reserves one line, the text wraps onto two, and
    the second line gets drawn outside the space reserved for it.

    On screen that looks like text being cut in half or overlapping whatever
    sits underneath, which sends you hunting for a font or styling problem when
    the real cause is three lines away in a layout.
    """
    text_label.setWordWrap(True)
    policy = text_label.sizePolicy()
    policy.setHeightForWidth(True)
    policy.setVerticalPolicy(QSizePolicy.MinimumExpanding)
    text_label.setSizePolicy(policy)
    return text_label


def card(*children, spacing=None, margins=None):
    """A rounded panel containing the given widgets, stacked vertically."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    pad = theme.SPACE_MD if margins is None else margins
    layout.setContentsMargins(pad, pad, pad, pad)
    layout.setSpacing(theme.SPACE_SM if spacing is None else spacing)
    for child in children:
        layout.addWidget(child)
    return frame


def divider():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
    return line


def confirm(parent, title, message, danger_text="Delete"):
    """Ask a yes/no question. Returns True if the user agreed.

    Used before anything destructive. The confirming button is labeled with
    the actual verb ("Delete") rather than "OK", because a button that says
    what it does is much harder to click by accident.
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.NoIcon)
    yes = box.addButton(danger_text, QMessageBox.AcceptRole)
    yes.setProperty("kind", "danger")
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is yes


def empty_state(message, hint=""):
    """The friendly placeholder shown where a list has nothing in it yet.

    Note there is no setAlignment(Qt.AlignCenter) on the layout. Centering a
    layout makes it hand each child exactly its sizeHint, and when the hint is
    wrong -- which it is for a wrapping label -- the children end up on top of
    each other. Padding and centered text gets the same look without the trap.
    """
    holder = QWidget()
    holder.setObjectName("plain")

    layout = QVBoxLayout(holder)
    layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_LG,
                              theme.SPACE_MD, theme.SPACE_LG)
    layout.setSpacing(theme.SPACE_SM)

    main = QLabel(message)
    main.setAlignment(Qt.AlignCenter)
    main.setStyleSheet(
        f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE}px;")
    layout.addWidget(main)

    if hint:
        sub = QLabel(hint)
        sub.setAlignment(Qt.AlignCenter)
        wrapped(sub)
        sub.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(sub)

    return holder


# ---------------------------------------------------------------------------
# FLOW LAYOUT
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    """A layout that places widgets left to right and wraps onto a new line
    when it runs out of room -- like words in a paragraph.

    Qt does not ship one, and tag chips need it: you never know how many tags
    something has or how long their names are.

    You do not need to follow the math in here to use the app. The one method
    that matters is _do_layout(), which walks the widgets keeping track of the
    current x position, and drops to the next line when the next widget would
    overflow the right edge.
    """

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    # Qt calls these five to manage the widgets we hold.
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    # Telling Qt "my height depends on how wide you make me" is what allows
    # wrapping to work at all.
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        """Place every widget, and return the total height used.

        When test_only is True nothing is actually moved -- Qt is only asking
        how tall we would be at that width.
        """
        x = rect.x()
        y = rect.y()
        line_height = 0
        gap = self.spacing()

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + gap

            # Would this widget run off the right edge? If so, wrap.
            if next_x - gap > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + gap
                next_x = x + hint.width() + gap
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))

            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y()


# ---------------------------------------------------------------------------
# COLOR PICKER
# ---------------------------------------------------------------------------

class ColorPicker(QWidget):
    """A grid of color swatches. The chosen one gets a ring around it.

    Emits colorChanged(hex_string) whenever the user picks a different one.
    """

    colorChanged = Signal(str)

    def __init__(self, color=None, columns=6, size=24, parent=None):
        super().__init__(parent)
        self._color = color or theme.SWATCHES[0]
        self._size = size
        self._buttons = {}

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(theme.SPACE_SM)

        for index, swatch in enumerate(theme.SWATCHES):
            dot = QPushButton()
            dot.setFixedSize(size, size)
            dot.setCursor(Qt.PointingHandCursor)
            # A lambda with a default argument captures the value NOW rather
            # than looking it up later. Without "s=swatch" every button would
            # end up reporting the last color in the list -- a classic and
            # very confusing Python loop bug.
            dot.clicked.connect(lambda checked=False, s=swatch: self.set_color(s))
            self._buttons[swatch] = dot
            grid.addWidget(dot, index // columns, index % columns)

        self._refresh()

    def color(self):
        return self._color

    def set_color(self, color, announce=True):
        self._color = color
        self._refresh()
        if announce:
            self.colorChanged.emit(color)

    def _refresh(self):
        """Repaint every swatch, ringing whichever one is selected."""
        for swatch, dot in self._buttons.items():
            selected = (swatch == self._color)
            border = f"2px solid {theme.TEXT}" if selected else \
                     f"1px solid {theme.BORDER_LIGHT}"
            dot.setStyleSheet(f"""
                QPushButton {{
                    background-color: {swatch};
                    border: {border};
                    border-radius: {self._size // 2}px;
                }}
                QPushButton:hover {{
                    border: 2px solid {theme.TEXT_MUTED};
                }}
            """)


# ---------------------------------------------------------------------------
# TAG CHIPS
# ---------------------------------------------------------------------------

def tag_chip(tag, small=False):
    """A pill showing a tag's name in the tag's own color.

    Read-only -- it is how a tag looks anywhere it is displayed. Assigning
    tags is done through TagPickerDialog below.
    """
    chip = QLabel(tag.name)
    size = theme.FONT_SIZE_SM if small else theme.FONT_SIZE
    # 4px of vertical padding rather than 2: at 2px the descenders on letters
    # like g and y sat right on the border and looked shaved off.
    chip.setStyleSheet(f"""
        QLabel {{
            background-color: {theme.with_alpha(tag.color, 0.18)};
            color: {tag.color};
            border: 1px solid {theme.with_alpha(tag.color, 0.45)};
            border-radius: 10px;
            padding: 4px 10px;
            font-size: {size}px;
        }}
    """)
    return chip


class TagChipRow(QWidget):
    """A wrapping row of tag chips, with an optional "no tags" placeholder.

    The three methods at the bottom are what stop a second row of chips being
    cut off. By default a widget reports one height, and a layout believes it.
    But a wrapping row's height DEPENDS on its width -- narrow it and the
    chips wrap onto more lines and it needs to be taller.

    Qt has a protocol for exactly this, and it takes two halves to work:
    the widget answers heightForWidth(), AND its size policy has to declare
    that it does. Miss the second half and Qt never asks the question. That
    was the bug: chips on the second row were being drawn outside the space
    reserved for them, so they looked chopped in half.
    """

    def __init__(self, placeholder="No tags", parent=None):
        super().__init__(parent)
        self._layout = FlowLayout(self, spacing=theme.SPACE_XS)
        self._placeholder = placeholder

        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout.heightForWidth(width)

    def sizeHint(self):
        width = self.width() if self.width() > 0 else 200
        return QSize(width, self.heightForWidth(width))

    def set_tags(self, tags):
        # Clear out the old chips first. takeAt(0) repeatedly is the standard
        # way to empty a Qt layout; deleteLater() lets Qt free each widget
        # safely once it has finished whatever it was doing.
        while self._layout.count():
            old = self._layout.takeAt(0)
            if old.widget():
                old.widget().deleteLater()

        if not tags:
            hint = QLabel(self._placeholder)
            hint.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
            self._layout.addWidget(hint)
            return

        for tag in tags:
            self._layout.addWidget(tag_chip(tag, small=True))

        # Tell Qt the height may have changed, so whatever contains us is
        # asked to re-measure. Without this the row keeps whatever height it
        # had when it was first shown.
        self.updateGeometry()


# ---------------------------------------------------------------------------
# DIALOGS
# ---------------------------------------------------------------------------

class NameColorDialog(QDialog):
    """Ask for a name and a color. Used for profiles, floors, rooms,
    containers, items and tags -- everything in the app is name-and-color, so
    everything shares this one dialog.

    Use it like this:

        dialog = NameColorDialog(self, "New floor", "Ground Floor")
        if dialog.exec():
            name, color = dialog.result_values()
    """

    def __init__(self, parent, title, name="", color=None, name_label="Name"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL,
                                  theme.SPACE_XL, theme.SPACE_XL)
        layout.setSpacing(theme.SPACE_MD)

        layout.addWidget(label(title, "sectionTitle"))

        layout.addWidget(label(name_label, "caption"))
        self._name_field = QLineEdit(name)
        self._name_field.setPlaceholderText("Give it a name")
        self._name_field.selectAll()
        layout.addWidget(self._name_field)

        layout.addWidget(label("Color", "caption"))
        self._picker = ColorPicker(color or theme.SWATCHES[0])
        layout.addWidget(self._picker)

        layout.addSpacing(theme.SPACE_SM)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Cancel", "ghost", self.reject))
        save = button("Save", "primary", self.accept)
        save.setDefault(True)   # pressing Enter triggers this one
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def result_values(self):
        """The name (trimmed) and color the user chose."""
        return self._name_field.text().strip(), self._picker.color()


class TagPickerDialog(QDialog):
    """Tick which tags apply to something.

    Works for items, rooms and containers alike -- they all just hold a list
    of tag ids, so one dialog covers all three.
    """

    def __init__(self, parent, profile, selected_ids, subject="item"):
        super().__init__(parent)
        self.setWindowTitle("Assign tags")
        self.setMinimumWidth(320)
        self.setMinimumHeight(360)
        self._profile = profile
        self._boxes = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL,
                                  theme.SPACE_XL, theme.SPACE_XL)
        layout.setSpacing(theme.SPACE_MD)

        layout.addWidget(label("Assign tags", "sectionTitle"))
        layout.addWidget(label(f"Tick every tag that applies to this {subject}.",
                               "caption"))

        # The tag list can get long, so it goes in a scroll area. The contents
        # are built in _rebuild() rather than here, because creating a tag
        # from inside this dialog needs to build them all over again.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        layout.addWidget(self._scroll, 1)
        self._rebuild(selected_ids)

        buttons = QHBoxLayout()
        # Being able to invent a tag without abandoning what you were doing
        # matters: otherwise tagging something with a tag you have not created
        # yet means canceling, going to the Items screen, and starting over.
        buttons.addWidget(button("+ New tag", "ghost", self._create_tag,
                                 size="sm"))
        buttons.addStretch()
        buttons.addWidget(button("Cancel", "ghost", self.reject))
        save = button("Save", "primary", self.accept)
        save.setDefault(True)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _rebuild(self, selected_ids):
        """Draw a checkbox row for every tag, ticking the ones given."""
        self._boxes = {}

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(theme.SPACE_SM)

        if not self._profile.tags:
            inner_layout.addWidget(empty_state(
                "No tags yet",
                "Use + New tag below to make your first one."))
        else:
            for tag in self._profile.tags:
                row = QWidget()
                row.setObjectName("plain")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(theme.SPACE_SM)

                box = QCheckBox()
                box.setChecked(tag.id in selected_ids)
                self._boxes[tag.id] = box

                row_layout.addWidget(box)
                row_layout.addWidget(tag_chip(tag))
                row_layout.addStretch()
                inner_layout.addWidget(row)

        inner_layout.addStretch()
        self._scroll.setWidget(inner)

    def _create_tag(self):
        from models import Tag        # imported here to avoid a circular import

        dialog = NameColorDialog(
            self, "New tag", "",
            theme.SWATCHES[len(self._profile.tags) % len(theme.SWATCHES)])
        if not dialog.exec():
            return

        name, color = dialog.result_values()
        if not name:
            return

        tag = Tag(name=name, color=color)
        self._profile.tags.append(tag)

        # Remember what was already ticked, then rebuild with the new tag
        # ticked as well -- you almost certainly made it to use it right now.
        keep = self.selected_ids() + [tag.id]
        self._rebuild(keep)

    def selected_ids(self):
        return [tag_id for tag_id, box in self._boxes.items() if box.isChecked()]




class PlaceRow(QWidget):
    """One line of the Places editor: which container, and how many are there.

    A row is not tied to a particular container -- the dropdown can be changed
    at any time. It just reports what it currently says, and the dialog
    collects the answers when you press Save.
    """

    removed = Signal(object)

    def __init__(self, profile, container_id=None, quantity=1, parent=None):
        super().__init__(parent)

        self.setObjectName("plain")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_SM)

        self.container_field = QComboBox()
        for floor, room, container in profile.iter_containers():
            self.container_field.addItem(
                f"{floor.name} / {room.name} / {container.name}", container.id)
            if container.id == container_id:
                self.container_field.setCurrentIndex(
                    self.container_field.count() - 1)
        layout.addWidget(self.container_field, 1)

        self.quantity_field = QSpinBox()
        self.quantity_field.setRange(0, 999999)
        self.quantity_field.setValue(quantity)
        self.quantity_field.setToolTip("How many are kept here. Zero removes "
                                       "this place.")
        self.quantity_field.setFixedWidth(78)
        layout.addWidget(self.quantity_field)

        remove = button("✕", "ghost", lambda: self.removed.emit(self),
                        "Remove this place", size="icon")
        layout.addWidget(remove)

    def values(self):
        """(container_id, quantity) as the row currently stands."""
        return self.container_field.currentData(), self.quantity_field.value()


class ItemDialog(QDialog):
    """Create or edit an item: name, color, tags, notes, and where it lives.

    THE PLACES LIST
    ---------------
    An item can be kept in more than one container, in different numbers --
    towels in the kitchen and the bathroom, say. So instead of one "location"
    dropdown there is a list of places, each with its own quantity, and the
    total is worked out for you.

    Every row is a real container. There is deliberately no way to file
    something directly into a room or a floor: a room is a place, a container
    is a thing you open.

    An item with no rows at all is "Unfiled" -- you own it, but you have not
    said where it is yet.
    """

    def __init__(self, parent, profile, item=None, default_container_id=None):
        super().__init__(parent)
        self.setWindowTitle("Item")
        self.setMinimumWidth(460)
        self._profile = profile
        self._tag_ids = list(item.tag_ids) if item else []
        self._rows = []

        self._has_containers = any(True for _ in profile.iter_containers())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL,
                                  theme.SPACE_XL, theme.SPACE_XL)
        layout.setSpacing(theme.SPACE_MD)

        layout.addWidget(label("Edit item" if item else "New item",
                               "sectionTitle"))

        layout.addWidget(label("Name", "caption"))
        self._name_field = QLineEdit(item.name if item else "")
        self._name_field.setPlaceholderText("What is it?")
        layout.addWidget(self._name_field)

        layout.addWidget(label("Color", "caption"))
        self._picker = ColorPicker(item.color if item else theme.SWATCHES[-1])
        layout.addWidget(self._picker)

        # -- places ---------------------------------------------------------
        layout.addSpacing(theme.SPACE_XS)
        places_header = QHBoxLayout()
        places_header.addWidget(label("Places", "caption"))
        places_header.addStretch()
        self._total_label = QLabel("")
        self._total_label.setObjectName("hint")
        places_header.addWidget(self._total_label)
        layout.addLayout(places_header)

        self._places_holder = QWidget()
        self._places_holder.setObjectName("plain")
        self._places_layout = QVBoxLayout(self._places_holder)
        self._places_layout.setContentsMargins(0, 0, 0, 0)
        self._places_layout.setSpacing(theme.SPACE_XS)
        layout.addWidget(self._places_holder)

        self._empty_note = QLabel()
        wrapped(self._empty_note)
        self._empty_note.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(self._empty_note)

        # Shown only while the item has no places. Without it you could not
        # write down how many of something you own until you had drawn a room
        # and a container to put it in, which is the wrong way round when you
        # are stood over a box trying to catalog it.
        self._unfiled_row = QWidget()
        self._unfiled_row.setObjectName("plain")
        unfiled_layout = QHBoxLayout(self._unfiled_row)
        unfiled_layout.setContentsMargins(0, 0, 0, 0)
        unfiled_layout.setSpacing(theme.SPACE_SM)
        unfiled_layout.addWidget(label("How many", "caption"))
        self._unfiled_field = QSpinBox()
        self._unfiled_field.setRange(0, 999999)
        self._unfiled_field.setValue(item.unfiled_quantity if item else 1)
        self._unfiled_field.setFixedWidth(90)
        unfiled_layout.addWidget(self._unfiled_field)
        unfiled_layout.addStretch()
        layout.addWidget(self._unfiled_row)

        self._add_place_button = button("+ Add a place", "ghost",
                                        self._add_empty_row, size="sm")
        self._add_place_button.setEnabled(self._has_containers)
        layout.addWidget(self._add_place_button)

        # -- par level -------------------------------------------------------
        # Zero means "don't warn me", which is why the box goes down to 0 and
        # the label says so. A checkbox plus a number would be two controls
        # for one decision.
        par_row = QHBoxLayout()
        par_row.setSpacing(theme.SPACE_SM)
        par_row.addWidget(label("Tell me when the total drops below",
                                "caption"))
        self._min_field = QSpinBox()
        self._min_field.setRange(0, 999999)
        self._min_field.setValue(item.min_quantity if item else 0)
        self._min_field.setFixedWidth(90)
        self._min_field.setToolTip("0 means never warn me")
        par_row.addWidget(self._min_field)
        par_row.addWidget(label("(0 = never)", "hint"))
        par_row.addStretch()
        layout.addLayout(par_row)

        # Fill in the starting rows.
        if item is not None:
            for placement in item.placements:
                self._add_row(placement.container_id, placement.quantity)
        elif default_container_id is not None:
            self._add_row(default_container_id, 1)

        self._refresh_places()

        # -- tags and notes ---------------------------------------------------
        layout.addSpacing(theme.SPACE_XS)
        layout.addWidget(label("Tags", "caption"))
        tag_row = QHBoxLayout()
        tag_row.setSpacing(theme.SPACE_SM)
        self._chips = TagChipRow("No tags yet")
        self._chips.set_tags(profile.tags_for(self._tag_ids))
        tag_row.addWidget(self._chips, 1)
        tag_row.addWidget(button("Edit tags", "ghost", self._edit_tags,
                                 size="sm"))
        layout.addLayout(tag_row)

        layout.addWidget(label("Notes", "caption"))
        self._notes_field = QPlainTextEdit(item.notes if item else "")
        self._notes_field.setMinimumHeight(60)
        self._notes_field.setMaximumHeight(90)
        self._notes_field.setPlaceholderText("Anything worth remembering")
        layout.addWidget(self._notes_field)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Cancel", "ghost", self.reject))
        save = button("Save", "primary", self.accept)
        save.setDefault(True)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    # -- the places list ------------------------------------------------------

    def _add_empty_row(self):
        self._add_row(None, 1)
        self._refresh_places()

    def _add_row(self, container_id, quantity):
        row = PlaceRow(self._profile, container_id, quantity)
        row.removed.connect(self._remove_row)
        row.quantity_field.valueChanged.connect(self._update_total)
        self._rows.append(row)
        self._places_layout.addWidget(row)

    def _remove_row(self, row):
        self._rows.remove(row)
        self._places_layout.removeWidget(row)
        row.deleteLater()
        self._refresh_places()

    def _refresh_places(self):
        """Show the right hint depending on what's there."""
        if not self._has_containers:
            self._empty_note.setText(
                "There are no containers yet. Draw a room in the Layout view "
                "and add a container to it, then you can say where this "
                "lives. For now it will be saved as unfiled.")
            self._empty_note.show()
        elif not self._rows:
            self._empty_note.setText(
                "Not filed anywhere yet. Add a place to say where it lives.")
            self._empty_note.show()
        else:
            self._empty_note.hide()

        # The plain quantity box matters only while there are no places. Once
        # there are, each place carries its own number and a single total
        # would just contradict them.
        self._unfiled_row.setVisible(not self._rows)

        self._update_total()

    def _update_total(self):
        if not self._rows:
            self._total_label.setText("")
            return
        total = sum(row.quantity_field.value() for row in self._rows)
        places = len(self._rows)
        self._total_label.setText(
            f"{total} in total across {places} place"
            + ("" if places == 1 else "s"))

    # -- tags -------------------------------------------------------------------

    def _edit_tags(self):
        dialog = TagPickerDialog(self, self._profile, self._tag_ids, "item")
        if dialog.exec():
            self._tag_ids = dialog.selected_ids()
            self._chips.set_tags(self._profile.tags_for(self._tag_ids))

    # -- results -----------------------------------------------------------------

    def result_values(self):
        """Everything the user entered, as a plain dictionary.

        Rows with a quantity of zero are dropped, and two rows pointing at the
        same container are added together rather than saved twice -- so the
        data stays tidy no matter how the form was filled in.
        """
        totals = {}
        order = []

        for row in self._rows:
            container_id, quantity = row.values()
            if container_id is None or quantity <= 0:
                continue
            if container_id not in totals:
                totals[container_id] = 0
                order.append(container_id)
            totals[container_id] += quantity

        placements = [Placement(container_id, totals[container_id])
                      for container_id in order]

        return {
            "name": self._name_field.text().strip(),
            "color": self._picker.color(),
            "placements": placements,
            "unfiled_quantity": self._unfiled_field.value(),
            "tag_ids": list(self._tag_ids),
            "notes": self._notes_field.toPlainText().strip(),
            "min_quantity": self._min_field.value(),
        }


# ---------------------------------------------------------------------------
# BULK ENTRY
# ---------------------------------------------------------------------------

# "Hammer x3", "Hammer ×3", "Hammer * 3" -- all mean three hammers.
QUANTITY_PATTERN = re.compile(r"^(.*?)\s*[x×*]\s*(\d+)$", re.IGNORECASE)

# The top row of the "put them all in" dropdown. Its data is None, which is
# the same thing an item with no placements means everywhere else in the app,
# so nothing downstream needs a special case for it.
UNFILED_CHOICE = "Nowhere yet (just add them to the item list)"


def parse_bulk_line(text):
    """Split a typed line into (name, quantity).

    A line with no quantity on the end is just one of that thing. Supporting
    the "x3" shorthand means you never have to reach for the mouse mid-flow,
    which is the entire point of this screen.

    Returns (None, 0) for a line with no usable name.
    """
    text = text.strip()
    if not text:
        return None, 0

    match = QUANTITY_PATTERN.match(text)
    if match:
        name = match.group(1).strip()
        quantity = int(match.group(2))
        if name and quantity > 0:
            return name, quantity
        # "x3" on its own, or "Hammer x0" -- fall through and treat the whole
        # thing as a name rather than silently dropping it.

    return text, 1


class BulkAddDialog(QDialog):
    """Add a lot of items quickly, without touching the mouse.

    WHY THIS EXISTS
    ---------------
    The thing that kills an inventory app is the first two hundred items. If
    each one costs a dialog, six fields and two clicks, you stop after twenty
    and the app becomes a half-finished list you do not trust.

    So this screen asks for the container ONCE, and then gets out of the way:
    type a name, press Enter, type the next. The text box never loses focus
    and the queue builds up underneath. Nothing is saved until you press Add,
    so a mistyped line can just be removed from the list.
    """

    def __init__(self, parent, profile, default_container_id=None):
        super().__init__(parent)
        self.setWindowTitle("Add many items")
        self.setMinimumWidth(480)
        self.setMinimumHeight(520)
        self._profile = profile
        self._tag_ids = []
        self._queued = []           # list of (name, quantity)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL,
                                  theme.SPACE_XL, theme.SPACE_XL)
        layout.setSpacing(theme.SPACE_MD)

        layout.addWidget(label("Add many items", "sectionTitle"))
        intro = label(
            "Type a name and press Enter. Repeat. Nothing is saved until you "
            "press Add at the bottom.", "caption")
        # Without wrapping, a narrow window silently chops the end off the
        # sentence rather than running it onto a second line.
        wrapped(intro)
        layout.addWidget(intro)

        # -- where they all go ------------------------------------------------
        self._where_caption = label("Put them all in", "caption")
        layout.addWidget(self._where_caption)

        self._container_field = QComboBox()

        # "Nowhere yet" is a real answer, and it sits at the top because it is
        # the only one that is always available. Cataloging and placing are
        # two different jobs: you write down a boxful of things while they are
        # in your hands, and work out which drawer they live in later. Forcing
        # a container here meant the only way to list something you had not
        # placed yet was to place it somewhere wrong first.
        self._container_field.addItem(UNFILED_CHOICE, None)

        for floor, room, container in profile.iter_containers():
            self._container_field.addItem(
                f"{floor.name} / {room.name} / {container.name}", container.id)

        # Index 0 is the unfiled row, so anything past it is a real container.
        has_containers = self._container_field.count() > 1

        # Default to a real place when there is one, because most of the time
        # you are standing in front of the drawer you are filling. Unfiled is
        # one row up the list for the times you are not.
        if has_containers:
            chosen = self._container_field.findData(default_container_id)
            self._container_field.setCurrentIndex(chosen if chosen > 0 else 1)

        self._container_field.currentIndexChanged.connect(self._refresh_target)

        # Using the dropdown leaves focus sitting on it, and the next thing
        # anyone does on this screen is type a name. "activated" only fires
        # when a person picks something, so it cannot go off while the dialog
        # is still being built and the text box does not exist yet.
        self._container_field.activated.connect(self._container_chosen)

        layout.addWidget(self._container_field)

        # One label covering both reasons the batch might end up unfiled: you
        # asked for it, or there is nowhere to put anything yet.
        self._target_note = QLabel()
        wrapped(self._target_note)
        layout.addWidget(self._target_note)

        # A dropdown with one row in it is just a decoration.
        self._container_field.setVisible(has_containers)
        self._where_caption.setVisible(has_containers)
        self._refresh_target()

        # -- tags for the whole batch -----------------------------------------
        layout.addWidget(label("Tag them all with", "caption"))
        tag_row = QHBoxLayout()
        tag_row.setSpacing(theme.SPACE_SM)
        self._chips = TagChipRow("No tags")
        # Draw the placeholder straight away; an empty row with no explanation
        # just looks like something failed to load.
        self._chips.set_tags([])
        tag_row.addWidget(self._chips, 1)
        tag_row.addWidget(button("Edit tags", "ghost", self._edit_tags,
                                 size="sm"))
        layout.addLayout(tag_row)

        # -- the typing line ----------------------------------------------------
        layout.addWidget(label("Item name", "caption"))
        self._entry = QLineEdit()
        self._entry.setPlaceholderText("e.g. Phillips screwdriver   ·   "
                                       "Zip ties x50")
        self._entry.returnPressed.connect(self._add_line)
        layout.addWidget(self._entry)

        hint = QLabel("Put <b>x3</b> on the end for a quantity. "
                      "Press Enter to add each one.")
        hint.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(hint)

        # -- the queue ----------------------------------------------------------
        queue_header = QHBoxLayout()
        self._queue_label = QLabel("Nothing queued yet")
        self._queue_label.setObjectName("caption")
        queue_header.addWidget(self._queue_label)
        queue_header.addStretch()
        self._remove_button = button("Remove selected", "ghost",
                                     self._remove_selected, size="sm",
                                     tooltip="Click rows in the list to "
                                             "select them; click again to "
                                             "let go")
        self._remove_button.setEnabled(False)
        queue_header.addWidget(self._remove_button)
        layout.addLayout(queue_header)

        self._list = QListWidget()

        # Clicking toggles, so clicking a selected row lets go of it again.
        # With plain single selection there is no way to end up with nothing
        # selected once you have clicked something, which is maddening.
        self._list.setSelectionMode(QAbstractItemView.MultiSelection)

        # The list never takes keyboard focus. This is the important one.
        # Clicking a row used to move focus off the text box, so everything you
        # typed afterward went into the list's type-ahead search instead of
        # the box, and Enter went somewhere else entirely. Now a click selects
        # the row and your typing carries straight on.
        self._list.setFocusPolicy(Qt.NoFocus)

        self._list.itemSelectionChanged.connect(self._refresh_counts)
        layout.addWidget(self._list, 1)

        # -- buttons -------------------------------------------------------------
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Cancel", "ghost", self.reject))
        self._save_button = button("Add", "primary", self.accept)
        self._save_button.setEnabled(False)
        buttons.addWidget(self._save_button)
        layout.addLayout(buttons)

        # Every button in a QDialog is an "auto default" button, meaning Qt
        # will fire one of them when you press Enter and the focus is not on a
        # button itself. In this dialog that is completely wrong: Enter means
        # "add the line I just typed", and nothing else. Left alone, Qt picked
        # Remove selected, so typing a name and pressing Enter silently
        # DELETED a queued row instead of adding a new one.
        for candidate in self.findChildren(QPushButton):
            candidate.setAutoDefault(False)
            candidate.setDefault(False)

        self._entry.setFocus()

    # -- where the batch is going ----------------------------------------------

    def _container_chosen(self, _index):
        self._entry.setFocus()

    def _refresh_target(self):
        """Say what will happen to the batch, but only when it needs saying.

        Picking a container is self-explanatory, so that case gets no note at
        all. The two unfiled cases do need one, and they are different: one is
        a choice and one is a limitation, so they do not get the same color.
        """
        no_containers = self._container_field.count() <= 1
        unfiled = self._container_field.currentData() is None

        if no_containers:
            self._target_note.setText(
                "There are no containers yet, so these will be added unfiled. "
                "Draw a room and add a container first if you want them "
                "placed.")
            color = theme.WARNING
        elif unfiled:
            self._target_note.setText(
                "These go straight into the item list with no place of their "
                "own. You will find them under Unfiled, ready to file "
                "whenever you like.")
            color = theme.TEXT_FAINT
        else:
            self._target_note.setVisible(False)
            return

        self._target_note.setStyleSheet(
            f"color: {color}; font-size: {theme.FONT_SIZE_SM}px;")
        self._target_note.setVisible(True)

    # -- queue management ------------------------------------------------------

    def _add_line(self):
        name, quantity = parse_bulk_line(self._entry.text())
        if not name:
            return

        self._queued.append((name, quantity))
        self._list.addItem(name if quantity == 1 else f"{name}   ×{quantity}")

        # Clear and stay put, so the next name can be typed immediately. The
        # scroll keeps the newest line in view.
        self._entry.clear()
        self._list.scrollToBottom()
        self._refresh_counts()

    def _remove_selected(self):
        """Drop every selected row.

        Reads selectedIndexes() rather than currentRow(). The "current" row is
        a different idea from the selected one: it survives clearing the
        selection, so the old version happily deleted a row while nothing
        appeared to be selected at all.

        Deleting from the bottom up, because removing row 1 would renumber
        everything below it and the next index would point at the wrong thing.
        """
        rows = sorted((index.row() for index in self._list.selectedIndexes()),
                      reverse=True)
        if not rows:
            return

        for row in rows:
            self._list.takeItem(row)
            del self._queued[row]

        self._refresh_counts()
        self._entry.setFocus()

    def _refresh_counts(self):
        count = len(self._queued)
        total = sum(quantity for _, quantity in self._queued)

        if count == 0:
            self._queue_label.setText("Nothing queued yet")
        else:
            self._queue_label.setText(
                f"{count} item" + ("" if count == 1 else "s")
                + f" queued · {total} unit" + ("" if total == 1 else "s"))

        self._save_button.setEnabled(count > 0)
        self._save_button.setText("Add" if count == 0 else f"Add {count}")

        # Grayed out when there is nothing to remove, so the button's state
        # always matches what the list looks like.
        selected = len(self._list.selectedIndexes())
        self._remove_button.setEnabled(selected > 0)
        self._remove_button.setText(
            "Remove selected" if selected < 2 else f"Remove {selected}")

    def _edit_tags(self):
        dialog = TagPickerDialog(self, self._profile, self._tag_ids, "batch")
        if dialog.exec():
            self._tag_ids = dialog.selected_ids()
            self._chips.set_tags(self._profile.tags_for(self._tag_ids))
        self._entry.setFocus()

    # -- results ----------------------------------------------------------------

    def result_items(self):
        """Build real Item objects from the queue.

        Everything shares the chosen container and tags; only the name and
        quantity differ per line.

        With "Nowhere yet" picked the container id is None, and an item with
        no placements is exactly what Unfiled means, so there is nothing
        special to do beyond skipping the placement. The quantity goes into
        `unfiled_quantity` either way: for a placed item it is ignored while
        it has somewhere to live, and it is there as a sensible number to fall
        back on if you later take it out of every container.
        """
        container_id = self._container_field.currentData()
        created = []

        for name, quantity in self._queued:
            placements = ([Placement(container_id, quantity)]
                          if container_id else [])
            created.append(Item(
                name=name,
                color=theme.SWATCHES[-1],
                placements=placements,
                unfiled_quantity=quantity,
                tag_ids=list(self._tag_ids),
            ))

        return created

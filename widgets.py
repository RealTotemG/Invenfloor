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

import math
import re

from PySide6.QtCore import (
    Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect,
    QRectF, QSize, Qt, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QFontMetricsF, QImage, QPainter,
    QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QDialog, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLineEdit, QMessageBox, QLayout, QCheckBox,
    QScrollArea, QFrame, QSpinBox, QPlainTextEdit, QComboBox, QSizePolicy,
    QListWidget, QAbstractItemView, QAbstractButton, QSlider,
)

import theme
from models import NAME_MAX_LENGTH, Item, Placement, clean_name, short


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


def name_field(text="", placeholder="Give it a name"):
    """A box for typing a name, with the length cap already on it.

    Every name in the app is typed into one of these. Putting the cap here
    instead of at each call site means a new name box cannot be added that
    quietly forgets it, which is exactly how the old runaway names happened.
    """
    field = QLineEdit(text)
    field.setPlaceholderText(placeholder)
    field.setMaxLength(NAME_MAX_LENGTH)
    return field


class ElidingLabel(QLabel):
    """A label that shortens its own text to whatever width it ends up with.

    The 20 character rule gets a name most of the way there, but characters
    are not all the same width and a narrow panel can still run out of room.
    Twenty capital Ws are a lot wider than twenty i's. This does the last step
    at the moment the width is actually known, which is the only point it can
    be done properly.

    The whole string is kept in fullText(), so nothing is really lost.
    """

    # Never squeeze narrower than this, or a chip in a tight row can end
    # up as nothing but an ellipsis.
    MIN_WIDTH = 48

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self._apply()

    def setText(self, text):
        self._full = text
        self._apply()

    def fullText(self):
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def minimumSizeHint(self):
        """Say that this label is allowed to be squeezed.

        A plain QLabel tells its layout it needs room for every character, so
        the layout widens the panel rather than narrowing the label, and the
        eliding above never gets a chance to run. That is what put a sideways
        scrollbar under the tag list. MIN_WIDTH stops it disappearing
        altogether.
        """
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self.MIN_WIDTH))
        return hint

    def _apply(self):
        width = self.contentsRect().width()
        if width <= 0:
            fitted = self._full         # no width yet, so nothing to fit to
        else:
            fitted = self.fontMetrics().elidedText(
                self._full, Qt.ElideRight, width)

        # Only touch the label when the result actually changed. setText asks
        # the layout to reconsider, which can come back round as another
        # resize, and without this guard that is a loop.
        if fitted != super().text():
            super().setText(fitted)


def fill_container_choices(combo, profile, selected=None):
    """Put every container in a dropdown, one row per tier.

    A tiered shelf gets a row for the shelf itself and a row for each of its
    tiers, so choosing a place is still one decision made in one control.
    Each row's data is the pair (container_id, tier), and tier 0 means the
    container itself.

    `selected` is that same pair. Returns the number of rows added.
    """
    for floor, room, container in profile.iter_containers():
        places = [0] + list(container.tiers())
        for tier in places:
            text = short_path(floor, room, container)
            complete = full_path(floor, room, container)
            if tier:
                text += f" · Tier {tier}"
                complete += f" · Tier {tier}"
            combo.addItem(text, (container.id, tier))
            combo.setItemData(combo.count() - 1, complete, Qt.ToolTipRole)
            if selected is not None and (container.id, tier) == tuple(selected):
                combo.setCurrentIndex(combo.count() - 1)
    return combo.count()


def short_path(floor, room, container):
    """A "Floor / Room / Container" line with every part shortened.

    Each name gets the same 20 character allowance it would get on its own,
    so one long room name cannot swallow the whole line.
    """
    return " / ".join(short(part.name) for part in (floor, room, container))


def full_path(floor, room, container):
    """The same line with nothing cut. For tooltips and anywhere exact."""
    return " / ".join(part.name for part in (floor, room, container))


def tier_suffix(tier):
    """" · Tier 2", or nothing at all for something not on a tier.

    One function so every screen says it the same way, and so the day this
    wording changes it changes everywhere at once.
    """
    return f" · Tier {tier}" if tier else ""


def path_label(floor, room, container, style=None):
    """A label for a container's full location, shortened, with a hover."""
    display = short_path(floor, room, container)
    complete = full_path(floor, room, container)
    result = QLabel(display)
    if style:
        result.setObjectName(style)
    if display != complete:
        result.setToolTip(complete)
    return result


def short_label(text, style=None, limit=None):
    """A label showing a shortened name, with the full one as its tooltip.

    Nothing is ever lost, it just moves to the hover. Only sets a tooltip when
    the text was actually cut, so hovering a name that fits shows nothing --
    a tooltip repeating what is already on screen is just noise.
    """
    display = short(text) if limit is None else short(text, limit)
    # An ElidingLabel rather than a plain one, so a name that passes the
    # character limit but still will not fit its panel gives way too.
    result = ElidingLabel(display)
    if style:
        result.setObjectName(style)
    if display != text:
        result.setToolTip(text)
    return result


def wrapped(text_label, grow=True):
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

    # MinimumExpanding by default, Minimum when the caller says not to grow.
    #
    # Both allow the label to be as tall as its wrapped text needs, which is
    # the half that stops text being sliced. The difference is what happens
    # when there is space going spare. Expanding says "and I would LIKE more",
    # so in a panel with a stretch at the bottom these labels swell to double
    # their height and leave strange gaps between the blocks around them.
    #
    # It cannot simply be Minimum everywhere, though. In a layout with no
    # stretch of its own -- the empty state inside a dialog is the one that
    # caught this -- Minimum leaves the label with a single line's height and
    # the second line gets painted outside it. So the default stays as it was,
    # and the places that sit above a stretch opt out.
    policy.setVerticalPolicy(QSizePolicy.MinimumExpanding if grow
                             else QSizePolicy.Minimum)
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

# 96 is the size the rest of the panel can afford. The inspector is one
# scrolling column and everything in it competes for the same pixels, so the
# wheel was measured against the list of containers below it rather than
# picked by eye: smaller than this and it gets fiddly to aim at, larger and a
# room with five containers starts the column scrolling.
WHEEL_SIZE = 96         # the hue and saturation disc, in pixels
WHEEL_MARGIN = 3        # room for the marker ring to sit on the rim


class ColorWheel(QWidget):
    """Hue around the rim, saturation toward the middle. Pick anywhere.

    HOW THE DISC IS DRAWN
    ---------------------
    Pixel by pixel into a QImage, once, and then blitted. Working out a color
    per pixel is far too slow to do inside paintEvent, which runs whenever
    anything at all redraws, but doing it once per size is nothing.

    Brightness is NOT baked into that image. It is a black rectangle painted
    over the top at (1 - brightness) opacity, which is not an approximation:
    in HSV, lowering the value scales all three channels by the same factor,
    and that is exactly what compositing black does. So the slider is free --
    no repainting 13,000 pixels while it is being dragged.
    """

    colorChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WHEEL_SIZE, WHEEL_SIZE)
        self.setCursor(Qt.CrossCursor)
        self._hue = 0.0          # 0 to 1
        self._saturation = 0.0   # 0 to 1, from the middle outward
        self._value = 1.0        # 0 to 1, set by the slider beside it
        self._disc = None

    # -- what it is showing --------------------------------------------------

    def set_hsv(self, hue, saturation, value):
        self._hue, self._saturation, self._value = hue, saturation, value
        self.update()

    def hsv(self):
        return self._hue, self._saturation, self._value

    # -- drawing --------------------------------------------------------------

    def _build_disc(self):
        """The hue and saturation wheel at full brightness, as an image."""
        size = WHEEL_SIZE
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)

        middle = (size - 1) / 2.0
        radius = middle - WHEEL_MARGIN

        for y in range(size):
            for x in range(size):
                dx = (x - middle) / radius
                dy = (y - middle) / radius
                distance = math.hypot(dx, dy)
                if distance > 1.0:
                    continue
                # atan2 of -dy because screen y grows downward and a color
                # wheel reads anticlockwise from the right, like an angle.
                hue = (math.degrees(math.atan2(-dy, dx)) % 360.0) / 360.0
                color = QColor.fromHsvF(hue, min(distance, 1.0), 1.0)
                # Fade the last pixel of the rim into transparency, or the
                # edge of the disc is a staircase.
                if distance > 0.97:
                    color.setAlphaF(max(0.0, (1.0 - distance) / 0.03))
                image.setPixelColor(x, y, color)

        return image

    def paintEvent(self, event):
        if self._disc is None:
            self._disc = self._build_disc()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawImage(0, 0, self._disc)

        middle = (WHEEL_SIZE - 1) / 2.0
        radius = middle - WHEEL_MARGIN

        # Brightness, as black over the top. See the note in the class.
        if self._value < 1.0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0,
                                           int((1.0 - self._value) * 255))))
            painter.drawEllipse(QRectF(middle - radius, middle - radius,
                                       radius * 2, radius * 2))

        # The marker. Two rings, dark under light, so it stays visible on a
        # pale yellow and on a deep blue alike.
        angle = self._hue * 2 * math.pi
        spot_x = middle + math.cos(angle) * self._saturation * radius
        spot_y = middle - math.sin(angle) * self._saturation * radius

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 160), 3))
        painter.drawEllipse(QPointF(spot_x, spot_y), 5.5, 5.5)
        painter.setPen(QPen(QColor(255, 255, 255), 1.6))
        painter.drawEllipse(QPointF(spot_x, spot_y), 5.5, 5.5)
        painter.end()

    # -- the mouse ------------------------------------------------------------

    def _pick(self, position):
        middle = (WHEEL_SIZE - 1) / 2.0
        radius = middle - WHEEL_MARGIN
        dx = (position.x() - middle) / radius
        dy = (position.y() - middle) / radius

        distance = math.hypot(dx, dy)
        self._hue = (math.degrees(math.atan2(-dy, dx)) % 360.0) / 360.0
        # Clamped rather than ignored: dragging off the edge should hold the
        # most saturated color at that angle, not stop responding.
        self._saturation = min(distance, 1.0)
        self.update()
        self.colorChanged.emit(
            QColor.fromHsvF(self._hue, self._saturation, self._value).name())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.position())


class ColorPicker(QWidget):
    """A color wheel, a brightness slider, a hex box and the house palette.

    Emits colorChanged(hex_string) whenever the color changes, including
    while the wheel is being dragged, so whatever is being colored follows
    along live.

    WHY BOTH A WHEEL AND SWATCHES
    -----------------------------
    The wheel is there because your kitchen cabinets are a particular green
    and no fixed palette has it. The swatches are there because most of the
    time you want "a different one from the last", and picking that off a row
    is one click where a wheel is a drag and a squint. They also keep a
    profile looking like one profile: the presets were chosen to read well
    against the dark canvas, which is not true of every color the wheel can
    reach.
    """

    colorChanged = Signal(str)

    def __init__(self, color=None, columns=6, size=18, parent=None):
        """columns and size shape the swatch grid: how many dots per row, and
        how big each dot is. Six across puts the twelve presets in two rows,
        which keeps the whole block no taller than the wheel beside it."""
        super().__init__(parent)
        self._color = color or theme.SWATCHES[0]
        self._buttons = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.SPACE_SM)

        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_SM)

        self._wheel = ColorWheel()
        self._wheel.colorChanged.connect(self._from_wheel)
        top.addWidget(self._wheel)

        beside = QVBoxLayout()
        beside.setSpacing(theme.SPACE_SM)

        self._brightness = QSlider(Qt.Vertical)
        self._brightness.setRange(8, 100)
        self._brightness.setToolTip("Brightness")
        self._brightness.valueChanged.connect(self._from_brightness)
        beside.addWidget(self._brightness, 1, Qt.AlignHCenter)

        top.addLayout(beside)

        # The hex box and the house palette stack up BESIDE the wheel rather
        # than under it. A wheel is tall and the column next to it was empty,
        # and the inspector is one scrolling column: every pixel this block
        # spends is a pixel the list of containers below it does not get.
        # Put this way, the whole thing is as tall as the wheel and no more.
        side = QVBoxLayout()
        side.setSpacing(theme.SPACE_SM)

        self._hex = QLineEdit()
        self._hex.setMaxLength(7)
        self._hex.setFixedWidth(90)
        self._hex.setToolTip("Type a hex color, like #33d6a0")
        self._hex.editingFinished.connect(self._from_hex)
        side.addWidget(self._hex)

        swatches = QGridLayout()
        swatches.setSpacing(theme.SPACE_XS)
        dot_size = size
        for index, swatch in enumerate(theme.SWATCHES):
            dot = QPushButton()
            dot.setFixedSize(dot_size, dot_size)
            dot.setCursor(Qt.PointingHandCursor)
            dot.setToolTip(swatch)
            # A lambda with a default argument captures the value NOW rather
            # than looking it up later. Without "s=swatch" every button would
            # end up reporting the last color in the list -- a classic and
            # very confusing Python loop bug.
            dot.clicked.connect(lambda checked=False, s=swatch:
                                self.set_color(s))
            self._buttons[swatch] = dot
            swatches.addWidget(dot, index // columns, index % columns)
        self._dot_size = dot_size
        side.addLayout(swatches)
        side.addStretch()

        top.addLayout(side)
        top.addStretch()
        outer.addLayout(top)

        self.set_color(self._color, announce=False)

    # -- the color it is on ---------------------------------------------------

    def color(self):
        return self._color

    def set_color(self, color, announce=True):
        """Move every control onto this color. The one entry point."""
        self._color = color
        made = QColor(color)
        if made.isValid():
            hue, saturation, value, _ = made.getHsvF()
            # A gray has no hue at all and getHsvF reports -1 for it. Keeping
            # the hue the wheel already had means dragging the brightness
            # slider down to black and back up returns the color you started
            # from rather than red.
            if hue < 0:
                hue = self._wheel.hsv()[0]
            self._wheel.set_hsv(hue, saturation, value)
            self._brightness.blockSignals(True)
            self._brightness.setValue(int(round(value * 100)))
            self._brightness.blockSignals(False)

        if self._hex.text().lower() != color.lower():
            self._hex.blockSignals(True)
            self._hex.setText(color)
            self._hex.blockSignals(False)

        self._refresh()
        if announce:
            self.colorChanged.emit(color)

    # -- where changes come from ----------------------------------------------

    def _from_wheel(self, color):
        self.set_color(color)

    def _from_brightness(self, level):
        hue, saturation, _ = self._wheel.hsv()
        value = level / 100.0
        self._wheel.set_hsv(hue, saturation, value)
        self.set_color(QColor.fromHsvF(hue, saturation, value).name())

    def _from_hex(self):
        """Accept a typed color, or put the old one back if it is nonsense."""
        typed = self._hex.text().strip()
        if not typed.startswith("#"):
            typed = "#" + typed
        if QColor(typed).isValid() and re.fullmatch(r"#[0-9a-fA-F]{6}", typed):
            self.set_color(typed.lower())
        else:
            self._hex.setText(self._color)

    def _refresh(self):
        """Repaint every swatch, ringing whichever one is selected."""
        for swatch, dot in self._buttons.items():
            selected = (swatch.lower() == self._color.lower())
            border = f"2px solid {theme.TEXT}" if selected else \
                     f"1px solid {theme.BORDER_LIGHT}"
            dot.setStyleSheet(f"""
                QPushButton {{
                    background-color: {swatch};
                    border: {border};
                    border-radius: {self._dot_size // 2}px;
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
    # Chips sit in a wrapping row, so a long tag name pushes every other chip
    # onto its own line. Shortened here, full name on hover.
    chip = short_label(tag.name)
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


class WrappingRow(QWidget):
    """A row of widgets that drops onto a second line rather than overflowing.

    Same trick as TagChipRow below, and for the same reason: a fixed-width
    panel has no way to grow, so a row that insists on more space than the
    panel has does not scroll, it gets sliced off at the edge. Three buttons
    named Move, Resize and Edit shape fit comfortably in the inspector here,
    but on a system with a wider interface font they would not, and a button
    you cannot read the name of is the one thing this row must never produce.

    Both halves of the heightForWidth protocol are needed. The widget answers
    the question AND its size policy declares that it can, otherwise Qt never
    asks and the second line is drawn outside the space reserved for it.
    """

    def __init__(self, spacing=None, parent=None):
        super().__init__(parent)
        self.setObjectName("plain")
        self._layout = FlowLayout(
            self, spacing=theme.SPACE_XS if spacing is None else spacing)

        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def add(self, widget):
        self._layout.addWidget(widget)
        return widget

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout.heightForWidth(width)


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
        self._name_field = name_field(name)
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
        """The name (tidied and capped) and color the user chose.

        Returns an empty name for an empty box rather than inventing one, so
        callers can still refuse to rename something to nothing.
        """
        typed = self._name_field.text()
        return (clean_name(typed, fallback="") if typed.strip() else "",
                self._picker.color())


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

        # Making a tag in here changes the profile the moment you press Save
        # on the little name box, whatever happens to THIS dialog afterwards.
        # Cancelling out of assigning tags does not un-create the tag, so the
        # caller has to be told either way: otherwise the new tag sits in
        # memory unsaved, and vanishes the next time the file is loaded.
        self.created_tags = False

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
        self.created_tags = True

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

    def __init__(self, profile, container_id=None, quantity=1, tier=0,
                 parent=None):
        super().__init__(parent)

        self.setObjectName("plain")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_SM)

        self.container_field = QComboBox()
        fill_container_choices(
            self.container_field, profile,
            None if container_id is None else (container_id, tier))
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
        """((container_id, tier), quantity) as the row currently stands."""
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
        self._name_field = name_field(item.name if item else "", "What is it?")
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
                self._add_row(placement.container_id, placement.quantity,
                              placement.tier)
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

    def _add_row(self, container_id, quantity, tier=0):
        row = PlaceRow(self._profile, container_id, quantity, tier)
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
        accepted = dialog.exec()
        # Recorded whether or not the assignment was accepted, because the tag
        # itself was created regardless. See TagPickerDialog.created_tags.
        self.created_tags = self.created_tags or dialog.created_tags
        if accepted:
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
            place, quantity = row.values()
            if place is None or quantity <= 0:
                continue
            # Keyed by (container, tier), so the same shelf on two different
            # tiers stays two rows, while the same tier twice gets added up.
            place = tuple(place)
            if place not in totals:
                totals[place] = 0
                order.append(place)
            totals[place] += quantity

        placements = [Placement(container_id, totals[(container_id, tier)],
                                tier)
                      for container_id, tier in order]

        return {
            "name": clean_name(self._name_field.text(), fallback=""),
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
        name = clean_name(match.group(1), fallback="")
        quantity = int(match.group(2))
        if name and quantity > 0:
            return name, quantity
        # "x3" on its own, or "Hammer x0" -- fall through and treat the whole
        # thing as a name rather than silently dropping it.

    return clean_name(text, fallback="") or None, 1


class MoveToTierDialog(QDialog):
    """Move some or all of an item onto a different tier of one container.

    WHY A QUANTITY
    --------------
    "Which tier are the shoes on" often has more than one answer. Four pairs on
    tier 1 and two on tier 3 is a normal thing for a shelf to be, so this asks
    how many to move rather than assuming the whole pile goes together. Move
    twice and you have split them.

    The destination list deliberately includes where they already are, greyed
    out in wording rather than removed, so the list always reads the same way
    and you can see the layout of the container while deciding.
    """

    def __init__(self, parent, item, container, quantity, tier):
        super().__init__(parent)
        self.setWindowTitle("Move to tier")
        self.setMinimumWidth(380)
        self._item = item
        self._container = container
        self._from_tier = tier

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL,
                                  theme.SPACE_XL, theme.SPACE_XL)
        layout.setSpacing(theme.SPACE_MD)

        layout.addWidget(label("Move to tier", "sectionTitle"))

        where = ("loose in " + short(container.name)) if tier == 0 \
            else f"on tier {tier} of {short(container.name)}"
        intro = label(f"{short(item.name)} · {quantity} {where}.", "caption")
        wrapped(intro)
        layout.addWidget(intro)

        layout.addWidget(label("How many", "caption"))
        self._quantity_field = QSpinBox()
        self._quantity_field.setRange(1, quantity)
        self._quantity_field.setValue(quantity)
        self._quantity_field.setToolTip(
            "Leave it at the full amount to move the lot, or lower it to "
            "split them across tiers.")
        layout.addWidget(self._quantity_field)

        layout.addWidget(label("Where to", "caption"))
        self._tier_field = QComboBox()
        for destination in [0] + list(container.tiers()):
            text = ("Loose in the container" if destination == 0
                    else f"Tier {destination}")
            if destination == tier:
                text += "   (where it is now)"
            self._tier_field.addItem(text, destination)
        # Land on the first destination that is not where it already is, so
        # pressing straight through actually moves something.
        for index in range(self._tier_field.count()):
            if self._tier_field.itemData(index) != tier:
                self._tier_field.setCurrentIndex(index)
                break
        layout.addWidget(self._tier_field)

        note = QLabel("Anything already on the destination tier is added to, "
                      "not replaced.")
        wrapped(note)
        note.setStyleSheet(
            f"color: {theme.TEXT_FAINT}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(note)

        layout.addSpacing(theme.SPACE_SM)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Cancel", "ghost", self.reject))
        save = button("Move", "primary", self.accept)
        save.setDefault(True)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def result_values(self):
        """(how many, which tier). The tier can be 0 for loose."""
        return self._quantity_field.value(), self._tier_field.currentData()


class TagManagerDialog(QDialog):
    """Every tag in the profile, in one place.

    WHY THIS EXISTS
    ---------------
    Tags could already be made and edited from the panel down the left of the
    Items screen, but only one at a time and only while that panel is what you
    are looking at. Tidying up a whole vocabulary -- renaming three, recoloring
    two, deleting the one you created by accident -- is its own job, and it
    wants its own window.

    It does not implement adding, editing or deleting itself. Those already
    exist on the Items screen and are handed in as callbacks, so there is one
    implementation of each rather than two that can drift apart.
    """

    def __init__(self, parent, profile, on_add, on_edit, on_delete):
        super().__init__(parent)
        self.setWindowTitle("Edit tags")
        self.setMinimumWidth(460)
        self.setMinimumHeight(420)
        self._profile = profile
        self._on_add = on_add
        self._on_edit = on_edit
        self._on_delete = on_delete

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL,
                                  theme.SPACE_XL, theme.SPACE_XL)
        layout.setSpacing(theme.SPACE_MD)

        layout.addWidget(label("Edit tags", "sectionTitle"))
        intro = label(
            "Tags group things across rooms. Put one on an item to say what "
            "it is, and the same one on a room to say what belongs there.",
            "caption")
        wrapped(intro)
        layout.addWidget(intro)

        header = QHBoxLayout()
        self._count_label = QLabel("")
        self._count_label.setObjectName("caption")
        header.addWidget(self._count_label)
        header.addStretch()
        header.addWidget(button("+ New tag", "primary", self._add, size="sm"))
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self._scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(button("Done", "primary", self.accept))
        layout.addLayout(buttons)

        self._rebuild()

    # -- the list --------------------------------------------------------------

    def _rebuild(self):
        body = QWidget()
        body.setObjectName("plain")
        inner = QVBoxLayout(body)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(theme.SPACE_XS)

        tags = self._profile.tags
        count = len(tags)
        self._count_label.setText(
            "No tags yet" if not count
            else f"{count} tag" + ("" if count == 1 else "s"))

        if not tags:
            inner.addWidget(empty_state(
                "No tags yet",
                "Make one for anything you would want to find across several "
                "rooms: Tools, Christmas, Fragile."))
        else:
            for tag in tags:
                inner.addWidget(self._row(tag))

        inner.addStretch()
        self._scroll.setWidget(body)

    def _row(self, tag):
        row = QFrame()
        row.setObjectName("card")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(theme.SPACE_SM, theme.SPACE_XS,
                                  theme.SPACE_SM, theme.SPACE_XS)
        layout.setSpacing(theme.SPACE_SM)

        layout.addWidget(tag_chip(tag))

        items = len(self._profile.items_with_tag(tag.id))
        rooms = len(list(self._profile.rooms_with_tag(tag.id)))
        usage = QLabel(f"{items} item" + ("" if items == 1 else "s")
                       + f" · {rooms} room" + ("" if rooms == 1 else "s"))
        usage.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(usage)

        layout.addStretch()
        layout.addWidget(button("Edit", "ghost",
                                lambda checked=False, t=tag: self._edit(t),
                                size="sm"))
        delete = button("Delete", "ghost",
                        lambda checked=False, t=tag: self._delete(t), size="sm")
        delete.setProperty("kind", "danger")
        layout.addWidget(delete)
        return row

    # -- the three actions, each handed in by the Items screen -----------------

    def _add(self):
        self._on_add()
        self._rebuild()

    def _edit(self, tag):
        self._on_edit(tag)
        self._rebuild()

    def _delete(self, tag):
        self._on_delete(tag)
        self._rebuild()


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
        self.created_tags = False
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

        # fill_container_choices selects the match itself. findData cannot be
        # used here: the data is a (container, tier) tuple, and Qt does not
        # compare those the way Python does.
        fill_container_choices(
            self._container_field, profile,
            None if default_container_id is None else (default_container_id, 0))

        # Index 0 is the unfiled row, so anything past it is a real container.
        has_containers = self._container_field.count() > 1

        # Default to a real place when there is one, because most of the time
        # you are standing in front of the drawer you are filling. Unfiled is
        # one row up the list for the times you are not. Index 0 still showing
        # means nothing matched, so fall back to the first real container.
        if has_containers and self._container_field.currentIndex() == 0:
            self._container_field.setCurrentIndex(1)

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

        # A little longer than a plain name, because the line can carry a
        # quantity on the end too. The name itself is still capped when the
        # line is parsed.
        self._entry.setMaxLength(NAME_MAX_LENGTH + 6)
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
        accepted = dialog.exec()
        self.created_tags = self.created_tags or dialog.created_tags
        if accepted:
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
        place = self._container_field.currentData()
        container_id, tier = place if place else (None, 0)
        created = []

        for name, quantity in self._queued:
            placements = ([Placement(container_id, quantity, tier)]
                          if container_id else [])
            created.append(Item(
                name=name,
                color=theme.SWATCHES[-1],
                placements=placements,
                unfiled_quantity=quantity,
                tag_ids=list(self._tag_ids),
            ))

        return created


# ---------------------------------------------------------------------------
# TOGGLE SWITCH
# ---------------------------------------------------------------------------

class ToggleSwitch(QAbstractButton):
    """An on/off switch: a pill with a knob that slides across.

    A checkable QPushButton works, but it tells you its state only by looking
    very slightly darker, and "slightly darker" is not a state you can read
    across a room or notice out of the corner of your eye. A switch says which
    way it is set from its shape, before you have read the label.

    The knob's position is a real Qt property so it can be animated. That is
    not decoration: the movement is what tells you the click registered, which
    matters most for a setting whose effect is somewhere else on screen.
    """

    KNOB_MARGIN = 3

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setText(text)

        self._track = QSize(40, 22)
        self._slide = 0.0        # 0 is off, 1 is fully across

        self._motion = QPropertyAnimation(self, b"slide", self)
        self._motion.setDuration(130)
        self._motion.setEasingCurve(QEasingCurve.OutCubic)

        self.toggled.connect(self._on_toggled)

    # -- the animated property ------------------------------------------------

    def get_slide(self):
        return self._slide

    def set_slide(self, value):
        self._slide = value
        self.update()

    slide = Property(float, get_slide, set_slide)

    def _on_toggled(self, checked):
        self._motion.stop()
        self._motion.setStartValue(self._slide)
        self._motion.setEndValue(1.0 if checked else 0.0)
        self._motion.start()

    def setChecked(self, checked):
        """Jump straight to the end when set in code rather than clicked.

        Setting a profile's saved state should not look like someone flicked
        the switch, and an animation left half-run by a rebuild would.
        """
        super().setChecked(checked)
        self._motion.stop()
        self.set_slide(1.0 if checked else 0.0)

    # -- size ------------------------------------------------------------------

    def sizeHint(self):
        metrics = QFontMetricsF(self.font())
        width = self._track.width() + theme.SPACE_SM
        if self.text():
            width += metrics.horizontalAdvance(self.text()) + 2
        return QSize(int(width), max(self._track.height(), 24))

    def minimumSizeHint(self):
        return self.sizeHint()

    # -- painting --------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        track = QRectF(0, (self.height() - self._track.height()) / 2,
                       self._track.width(), self._track.height())
        radius = track.height() / 2

        # The track carries the color, so on and off differ in hue as well as
        # in knob position. Two signals for one state beats one.
        painter.setBrush(QColor(theme.mix(
            theme.BG_ACTIVE, theme.SUCCESS, self._slide)))
        painter.setPen(QPen(theme.qcolor(
            theme.SUCCESS if self._slide > 0.5 else theme.BORDER_LIGHT,
            0.9), 1.2))
        painter.drawRoundedRect(track, radius, radius)

        travel = track.width() - track.height()
        knob_size = track.height() - self.KNOB_MARGIN * 2
        knob = QRectF(track.x() + self.KNOB_MARGIN + travel * self._slide,
                      track.y() + self.KNOB_MARGIN, knob_size, knob_size)
        painter.setBrush(QColor(theme.TEXT if self._slide > 0.5
                                else theme.TEXT_MUTED))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(knob)

        if self.text():
            painter.setPen(QPen(QColor(
                theme.TEXT if self.isChecked() else theme.TEXT_MUTED)))
            painter.drawText(
                QRectF(track.right() + theme.SPACE_SM, 0,
                       self.width() - track.right() - theme.SPACE_SM,
                       self.height()),
                Qt.AlignVCenter | Qt.AlignLeft, self.text())

        painter.end()

"""
profile_screen.py
=================

The launcher: the first thing you see. A list of profile cards down the left,
and a preview of whichever one you are pointing at on the right.

Each profile is a completely separate inventory -- its own floors, rooms,
containers, items and tags. Nothing crosses between them.

This screen announces one thing to the rest of the app:

    profileOpened(profile)

main.py listens for that and swaps the window over to the workspace. The
screen itself has no idea what happens next, which is what lets you rearrange
the app later without rewriting this file.

WHY THE CARDS SAY SO MUCH
-------------------------
A launcher that lists nothing but names makes you open a profile to remember
what is in it. So each card carries the counts, when you last touched it, and
a warning when something inside wants attention. The point is to answer
"which one did I mean?" without opening anything.

WHY THERE IS A PREVIEW
----------------------
The counts tell you how much is in a profile. They cannot tell you which one
it is. A floor plan can: you recognize your own house at a glance, long before
you have read a single number. So pointing at a card draws its ground floor
full size on the right, and you can see the room you are about to click.

It costs nothing to keep honest, because the preview does not have its own
drawing code. It hands the floor to floor_items.render_floor, which is the
same function the PDF export uses and the same RoomItems the canvas draws. A
room that looks one way on the canvas looks that way here.
"""

from datetime import datetime

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QScrollArea, QMenu, QSizePolicy,
)

import floor_items
import storage
import theme
from models import Profile, short
from widgets import (
    NameColorDialog, button, confirm, divider, label, short_label, wrapped,
)

CARD_WIDTH = 300
CARD_HEIGHT = 190
SIDE_MARGIN = theme.SPACE_XL * 2
SCROLLBAR_ALLOWANCE = 16       # kept clear so cards don't shuffle when one appears

# The list column is the card plus room for its scrollbar. Everything left
# over goes to the preview, which is the half that benefits from being big.
LIST_WIDTH = CARD_WIDTH + SCROLLBAR_ALLOWANCE + theme.SPACE_SM


def when_text(timestamp, today=None):
    """"Updated today", "Updated 4 days ago", then a plain date.

    Days rather than hours, because an inventory is something you come back to
    across weeks, not minutes. Past a fortnight it switches to a real date --
    "Updated 71 days ago" is a number you have to do arithmetic on before it
    means anything.
    """
    if timestamp is None:
        return "Never saved"

    when = datetime.fromtimestamp(timestamp)
    today = today or datetime.now().date()
    days = (today - when.date()).days

    if days <= 0:
        return "Updated today"
    if days == 1:
        return "Updated yesterday"
    if days < 14:
        return f"Updated {days} days ago"
    # %d pads to two digits on every platform; %-d does not exist on Windows.
    return "Updated " + when.strftime("%d %b %Y").lstrip("0")


def plural(count, word):
    return f"{count} {word}" + ("" if count == 1 else "s")


def _text(content, color, size, weight=400):
    """A plain label in a card. Cards set their own background, so the label
    must not paint one of its own on top."""
    made = QLabel(content)
    made.setStyleSheet(f"color: {color}; font-size: {size}px; "
                       f"font-weight: {weight}; background: transparent;")
    return made


def _stat(value, caption):
    """One number with its word underneath: the unit a card's middle is made
    of. Four of these side by side read faster than one run-on sentence."""
    holder = QWidget()
    holder.setObjectName("plain")
    holder.setAttribute(Qt.WA_TransparentForMouseEvents)

    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(_text(str(value), theme.TEXT, theme.FONT_SIZE_LG, 600))
    layout.addWidget(_text(caption, theme.TEXT_FAINT, theme.FONT_SIZE_SM))
    return holder


class ProfileCard(QFrame):
    """One profile, drawn as a clickable card.

    Clicking anywhere on the card opens it. The two small buttons along the
    bottom edit and delete it -- Qt does not pass a click on a child button up
    to the parent, so those don't accidentally open the profile too. The same
    three actions are on the right-click menu, for anyone who reaches for one.
    """

    opened = Signal(object)
    editRequested = Signal(object)
    deleteRequested = Signal(object)
    hovered = Signal(object)         # the preview on the right listens to this

    def __init__(self, profile, modified=None, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style(hovered=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_LG, theme.SPACE_LG,
                                  theme.SPACE_LG, theme.SPACE_MD)
        layout.setSpacing(0)

        layout.addLayout(self._header(profile, modified))
        layout.addSpacing(theme.SPACE_LG)
        layout.addLayout(self._stats(profile))
        layout.addStretch()
        layout.addWidget(divider())
        layout.addSpacing(theme.SPACE_SM)
        layout.addWidget(self._footer(profile))

    # -- the three bands of the card -----------------------------------------

    def _header(self, profile, modified):
        """A dot in the profile's color, its name, and when you last saved it."""
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_SM)
        row.setContentsMargins(0, 0, 0, 0)

        dot = QFrame()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(
            f"background-color: {profile.color}; border-radius: 5px; "
            f"border: none;")
        # Sit the dot on the first line of text rather than the middle of a
        # two-line block, which would leave it floating between them.
        column = QVBoxLayout()
        column.setContentsMargins(0, 4, 0, 0)
        column.addWidget(dot)
        column.addStretch()
        row.addLayout(column)

        text = QVBoxLayout()
        text.setSpacing(1)
        name = short_label(profile.name)
        name.setStyleSheet(
            f"font-size: {theme.FONT_SIZE_LG}px; font-weight: 600; "
            f"color: {theme.TEXT}; background: transparent;")
        text.addWidget(name)
        text.addWidget(_text(when_text(modified), theme.TEXT_FAINT,
                             theme.FONT_SIZE_SM))
        row.addLayout(text, 1)

        return row

    def _stats(self, profile):
        """Four counts across the middle: floors, rooms, containers, items."""
        rooms = sum(len(f.rooms) for f in profile.floors)
        containers = sum(len(r.containers)
                         for f in profile.floors for r in f.rooms)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_SM)
        for value, caption in ((len(profile.floors), "floors"),
                               (rooms, "rooms"),
                               (containers, "containers"),
                               (len(profile.items), "items")):
            row.addWidget(_stat(value, caption), 1)
        return row

    def _footer(self, profile):
        """What needs attention on the left, the two actions on the right.

        The warning is the reason this band exists. Unfiled items are the one
        thing that quietly piles up, and seeing "3 unfiled" from the launcher
        is what stops it becoming thirty.
        """
        holder = QWidget()
        holder.setObjectName("plain")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_SM)

        note = self._attention_text(profile)
        color = theme.WARNING if self._needs_attention(profile) else theme.TEXT_MUTED
        row.addWidget(_text(note, color, theme.FONT_SIZE_SM))
        row.addStretch()

        row.addWidget(button("Edit", "ghost",
                             lambda: self.editRequested.emit(self.profile),
                             size="sm"))
        row.addWidget(button("Delete", "ghost",
                             lambda: self.deleteRequested.emit(self.profile),
                             size="sm"))
        return holder

    def _needs_attention(self, profile):
        return bool(profile.unfiled_items() or profile.low_items())

    def _attention_text(self, profile):
        """The one line most worth reading, or the tag count if all is well.

        Only one thing is ever shown. A card is a glance, and a glance that
        lists three problems is a card you stop reading.
        """
        unfiled = len(profile.unfiled_items())
        if unfiled:
            return f"{unfiled} unfiled"

        low = len(profile.low_items())
        if low:
            return f"{low} running low"

        if not profile.items:
            return "Empty"

        return plural(len(profile.tags), "tag")

    # -- appearance ----------------------------------------------------------

    def _apply_style(self, hovered):
        """Cards tint toward their own color on hover.

        Written here rather than in theme.py's stylesheet because the color
        depends on the individual profile, which the global sheet can't know.
        """
        background = theme.BG_HOVER if hovered else theme.BG_CARD
        border = self.profile.color if hovered else theme.BORDER
        self.setStyleSheet(f"""
            ProfileCard {{
                background-color: {background};
                border: 1px solid {border};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """)

    # Qt calls these automatically as the mouse comes and goes.
    def enterEvent(self, event):
        self._apply_style(hovered=True)
        self.hovered.emit(self.profile)
        super().enterEvent(event)

    def leaveEvent(self, event):
        # Only the tint is dropped here, not the preview. Moving from one card
        # to the next crosses the gap between them, and clearing the preview on
        # the way would make it flicker. The list as a whole says when nothing
        # is being pointed at.
        self._apply_style(hovered=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.opened.emit(self.profile)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.opened.emit(self.profile))
        menu.addAction("Rename", lambda: self.editRequested.emit(self.profile))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self.deleteRequested.emit(self.profile))
        menu.exec(event.globalPos())


NEW_CARD_HEIGHT = 84


class NewProfileCard(QFrame):
    """The dashed "+" card that sits after the real ones.

    Shorter than a profile card on purpose. It has nothing to say, and down a
    single column a full-height dashed box would read as an empty profile.
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CARD_WIDTH, NEW_CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style(hovered=False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(2)

        plus = _text("+", theme.TEXT_MUTED, 26)
        plus.setAlignment(Qt.AlignCenter)
        layout.addWidget(plus)

        caption = _text("New profile", theme.TEXT_MUTED, theme.FONT_SIZE)
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(caption)

    def _apply_style(self, hovered):
        color = theme.ACCENT if hovered else theme.BORDER_LIGHT
        self.setStyleSheet(f"""
            NewProfileCard {{
                background-color: transparent;
                border: 1px dashed {color};
                border-radius: {theme.RADIUS_LG}px;
            }}
        """)

    def enterEvent(self, event):
        self._apply_style(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(hovered=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


PREVIEW_PADDING = theme.SPACE_XL
PREVIEW_MIN_WIDTH = 360


class FloorPreview(QFrame):
    """The right half: the ground floor of whichever card you are pointing at.

    Draws nothing of its own. The plan comes from floor_items.render_floor,
    the same function the PDF export calls, built from the same RoomItems the
    canvas uses. This widget only decides where on itself the picture goes and
    what to say when there is no picture to draw.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(PREVIEW_MIN_WIDTH)
        self.profile = None

        # The last plan we drew, and what it was drawn from. See _plan().
        self._plan_cache = None
        self._drawn_profile = None
        self._drawn_size = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(PREVIEW_PADDING, PREVIEW_PADDING,
                                  PREVIEW_PADDING, PREVIEW_PADDING)
        layout.setSpacing(2)

        self._title = _text("", theme.TEXT, theme.FONT_SIZE_LG, 600)
        layout.addWidget(self._title)
        self._subtitle = _text("", theme.TEXT_FAINT, theme.FONT_SIZE_SM)
        layout.addWidget(self._subtitle)

        # The plan is drawn over everything below the heading. Nothing is put
        # in this space as a widget, so a stretch is all it takes to reserve
        # it -- paintEvent works out the rectangle from the same numbers.
        layout.addStretch(1)

    def show_profile(self, profile):
        """Point the preview at a profile, or at None for the idle message."""
        if profile is self.profile:
            return

        self.profile = profile
        if profile is None:
            self._title.setText("")
            self._subtitle.setText("")
        else:
            floor = self.base_floor()
            self._title.setText(short(profile.name))
            self._subtitle.setText(
                f"{floor.name} · {plural(len(floor.rooms), 'room')}"
                if floor is not None else "No floors yet")

        # Repaint even when only the plan changed: the labels above redraw
        # themselves, the plan below is ours to ask for.
        self.update()

    def base_floor(self):
        """The bottom floor -- the one you would walk in on.

        floors[0] rather than a search, because the list is kept in building
        order: index 0 is the lowest, and adding a basement inserts at 0. The
        floor strip in the workspace relies on the same ordering.
        """
        if self.profile is None or not self.profile.floors:
            return None
        return self.profile.floors[0]

    def plan_rect(self):
        """Where the floor plan goes: everything under the two heading lines."""
        top = PREVIEW_PADDING + self._title.height() + self._subtitle.height() \
            + theme.SPACE_MD
        return QRectF(
            PREVIEW_PADDING, top,
            max(self.width() - PREVIEW_PADDING * 2, 1),
            max(self.height() - top - PREVIEW_PADDING, 1))

    def paintEvent(self, event):
        # The frame's own background and border are drawn by the stylesheet,
        # which happens in the base class. Ours goes on top of that.
        super().paintEvent(event)

        painter = QPainter(self)
        plan = self._plan()

        if plan is not None:
            painter.drawPixmap(0, 0, plan)
        else:
            painter.setPen(theme.TEXT_FAINT)
            painter.drawText(self.plan_rect(), Qt.AlignCenter,
                             self._idle_message())
        painter.end()

    def _plan(self):
        """The drawn plan, kept from last time unless something has changed.

        render_floor builds a scene of real RoomItems every time it runs. That
        is fine once and far too slow inside a paintEvent, which fires on
        every frame of a window drag: measured at 12ms for a five-room floor
        and 265ms for sixty rooms, which would be a drag you can feel.

        So the drawing happens when the profile or the size changes, and every
        other repaint is a blit of what came out. There is nothing to
        invalidate by hand -- the two things that can change the picture are
        both in the check below.
        """
        if (self._plan_cache is not None
                and self._drawn_profile is self.profile
                and self._drawn_size == self.size()):
            return self._plan_cache

        self._plan_cache = None
        self._drawn_profile = self.profile
        self._drawn_size = self.size()

        if self.width() < 1 or self.height() < 1:
            return None

        # Drawn at the screen's pixel density, or the plan is soft on a
        # high-resolution display. setDevicePixelRatio is what tells Qt the
        # bigger pixmap still covers the same widget.
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(self.size() * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)

        into = QPainter(pixmap)
        into.setRenderHint(QPainter.Antialiasing)
        drew = floor_items.render_floor(into, self.profile, self.base_floor(),
                                        self.plan_rect())
        into.end()

        # A floor with no rooms leaves the cache empty, so the check above
        # falls through and we come back here next paint. That costs nothing:
        # render_floor returns before building anything when there is nothing
        # to build, and the message below is a single drawText.
        if drew:
            self._plan_cache = pixmap
        return self._plan_cache

    def _idle_message(self):
        if self.profile is None:
            return "Point at a profile to see its floor plan"
        if self.base_floor() is None:
            return "This profile has no floors yet"
        return "Nothing drawn on this floor yet"


EMPTY_WIDTH = 560
EMPTY_PADDING = theme.SPACE_XL * 2


class EmptyLauncher(QFrame):
    """What you see the very first time, before any profile exists.

    A lone dashed card on an empty screen tells a new user nothing about what
    they are about to make. This says what a profile is and gives them one
    obvious thing to press.
    """

    createRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(EMPTY_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(EMPTY_PADDING, EMPTY_PADDING,
                                  EMPTY_PADDING, EMPTY_PADDING)
        layout.setSpacing(theme.SPACE_SM)

        layout.addWidget(_text("Start with a profile", theme.TEXT,
                               theme.FONT_SIZE_LG, 600))

        layout.addWidget(self._paragraph(
            "A profile is one place you keep things: a house, a workshop, a "
            "storage unit. Inside it you draw the floors and rooms, put "
            "containers in them, and fill those with items."))
        layout.addWidget(self._paragraph(
            "Most people only ever need one. You can always add more later."))

        layout.addSpacing(theme.SPACE_MD)

        start = QHBoxLayout()
        start.addWidget(button("Create a profile", "primary",
                               self.createRequested.emit))
        start.addStretch()
        layout.addLayout(start)

    def _paragraph(self, content):
        """A wrapping paragraph, with its height nailed down.

        The panel is a fixed width, so the height each paragraph needs can be
        worked out here and set as a floor. Belt and braces rather than the
        fix itself -- the thing that was actually squeezing these onto one
        line was an alignment flag over in ProfileScreen -- but this is the
        trap that has caught this app more than any other, and a minimum
        height is the one thing no layout can argue with.

        grow=False for the opposite reason: with the height already pinned, a
        paragraph that ALSO asks for spare room swells and leaves a hole
        between the two of them.
        """
        inner = EMPTY_WIDTH - (EMPTY_PADDING * 2)
        made = wrapped(_text(content, theme.TEXT_MUTED, theme.FONT_SIZE),
                       grow=False)
        made.setFixedWidth(inner)
        made.setMinimumHeight(made.heightForWidth(inner))
        return made


class ProfileScreen(QWidget):
    """The whole launcher screen."""

    profileOpened = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SIDE_MARGIN, theme.SPACE_XL,
                                 SIDE_MARGIN, theme.SPACE_XL)
        outer.setSpacing(0)

        outer.addLayout(self._build_header())
        outer.addSpacing(theme.SPACE_XL)

        self._split = QHBoxLayout()
        self._split.setContentsMargins(0, 0, 0, 0)
        self._split.setSpacing(theme.SPACE_XL)

        # -- left: the cards, in one column that scrolls
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setFixedWidth(LIST_WIDTH)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # The mouse leaving this is what puts the preview back to its prompt.
        # Asked of the whole list rather than each card, so crossing the gap
        # between two cards is not mistaken for pointing at nothing.
        self._scroll.leaveEvent = self._list_left
        self._list_holder = QWidget()
        self._list_holder.setObjectName("plain")
        self._list = QVBoxLayout(self._list_holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(theme.SPACE_MD)
        self._scroll.setWidget(self._list_holder)
        self._split.addWidget(self._scroll)

        # -- right: the plan of whatever is being pointed at
        self._preview = FloorPreview()
        self._split.addWidget(self._preview, 1)

        outer.addLayout(self._split, 1)

        # A stretch beside it rather than Qt.AlignLeft. An alignment flag makes
        # the layout hand a widget exactly its sizeHint and no more, and a
        # sizeHint that contains wrapped text is always short -- measured at
        # six pixels here, which is enough to squeeze three lines of
        # explanation into two and paint the third over the heading.
        self._empty = EmptyLauncher()
        self._empty.createRequested.connect(self._create_profile)
        self._empty.hide()
        beside = QHBoxLayout()
        beside.setContentsMargins(0, 0, 0, 0)
        beside.addWidget(self._empty)
        beside.addStretch(1)
        outer.addLayout(beside)
        outer.addStretch()

        self.reload()

    def _list_left(self, event):
        self._preview.show_profile(None)

    # -- the top of the screen ------------------------------------------------

    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_MD)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label("Inventory", "screenTitle"))
        self._subtitle = label("", "caption")
        text.addWidget(self._subtitle)
        row.addLayout(text, 1)

        # A real button up here as well as the dashed card below, because the
        # card moves: with nine profiles it is off at the bottom of the grid,
        # and this one never is.
        self._new_button = button("New profile", "primary", self._create_profile)
        self._new_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row.addWidget(self._new_button, 0, Qt.AlignTop)

        return row

    def _subtitle_text(self):
        """A one-line census of everything, across all profiles."""
        if not self.profiles:
            return ("Each profile keeps its own floors, rooms, containers, "
                    "items and tags.")

        items = sum(len(p.items) for p in self.profiles)
        rooms = sum(len(f.rooms) for p in self.profiles for f in p.floors)
        return (f"{plural(len(self.profiles), 'profile')} · "
                f"{plural(rooms, 'room')} · {plural(items, 'item')}")

    # -- building the grid --------------------------------------------------

    def reload(self):
        """Re-read the save folder and rebuild the card list from scratch.

        Rebuilding everything after any change is more work than surgically
        updating one card, but it is far harder to get wrong -- the screen can
        never drift out of step with what is on disk.
        """
        self.profiles = storage.load_profiles()
        self._rebuild_list()

    def _rebuild_list(self):
        while self._list.count():
            old = self._list.takeAt(0)
            if old.widget():
                old.widget().deleteLater()

        self._subtitle.setText(self._subtitle_text())

        # The preview is pointed at a profile that is about to be deleted, so
        # let go of it before the cards holding it are thrown away.
        self._preview.show_profile(None)

        # With nothing saved yet, the split gives way to a proper welcome.
        showing_cards = bool(self.profiles)
        self._scroll.setVisible(showing_cards)
        self._preview.setVisible(showing_cards)
        self._empty.setVisible(not showing_cards)
        self._new_button.setVisible(showing_cards)
        if not showing_cards:
            return

        for profile in self.profiles:
            card = ProfileCard(profile, storage.profile_modified(profile.id))
            card.opened.connect(self.profileOpened.emit)
            card.editRequested.connect(self._edit_profile)
            card.deleteRequested.connect(self._delete_profile)
            card.hovered.connect(self._preview.show_profile)
            self._list.addWidget(card)

        new_card = NewProfileCard()
        new_card.clicked.connect(self._create_profile)
        self._list.addWidget(new_card)

        self._list.addStretch()

    # -- actions ------------------------------------------------------------

    def _create_profile(self):
        dialog = NameColorDialog(self, "New profile", "", theme.SWATCHES[0])
        if not dialog.exec():
            return
        name, color = dialog.result_values()
        if not name:
            return

        profile = Profile(name=name, color=color)
        storage.save_profile(profile)
        self.reload()

    def _edit_profile(self, profile):
        dialog = NameColorDialog(self, "Edit profile", profile.name, profile.color)
        if not dialog.exec():
            return
        name, color = dialog.result_values()
        if not name:
            return

        profile.name = name
        profile.color = color
        storage.save_profile(profile)
        self.reload()

    def _delete_profile(self, profile):
        if not confirm(
            self, "Delete profile",
            f"Delete '{profile.name}'?\n\n"
            f"Every floor, room, container and item inside it will be removed. "
            f"This cannot be undone."
        ):
            return

        storage.delete_profile(profile.id)
        self.reload()

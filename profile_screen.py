"""
profile_screen.py
=================

The launcher: the first thing you see. A grid of profile cards, plus a card
for making a new one.

Each profile is a completely separate inventory -- its own floors, rooms,
containers, items and tags. Nothing crosses between them.

This screen announces one thing to the rest of the app:

    profileOpened(profile)

main.py listens for that and swaps the window over to the workspace. The
screen itself has no idea what happens next, which is what lets you rearrange
the app later without rewriting this file.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel,
    QScrollArea,
)

import storage
import theme
from models import Profile
from widgets import NameColorDialog, button, label, confirm, short_label

CARD_WIDTH = 260
CARD_HEIGHT = 150
COLUMNS = 3


class ProfileCard(QFrame):
    """One profile, drawn as a clickable card.

    Clicking anywhere on the card opens it. The two small buttons along the
    bottom edit and delete it -- Qt does not pass a click on a child button up
    to the parent, so those don't accidentally open the profile too.
    """

    opened = Signal(object)
    editRequested = Signal(object)
    deleteRequested = Signal(object)

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        # Fixed width keeps the grid tidy; the height is a minimum so a
        # long profile name can wrap without being clipped.
        self.setFixedWidth(CARD_WIDTH)
        self.setMinimumHeight(CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style(hovered=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_LG, theme.SPACE_MD,
                                  theme.SPACE_LG, theme.SPACE_MD)
        layout.setSpacing(theme.SPACE_XS)

        # A short bar in the profile's color, so the grid is scannable by
        # color before you have read a single word.
        stripe = QFrame()
        stripe.setFixedHeight(4)
        stripe.setFixedWidth(42)
        stripe.setStyleSheet(
            f"background-color: {profile.color}; border-radius: 2px;")
        layout.addWidget(stripe)
        layout.addSpacing(theme.SPACE_SM)

        name = short_label(profile.name)
        name.setStyleSheet(
            f"font-size: {theme.FONT_SIZE_LG}px; font-weight: 600; "
            f"color: {theme.TEXT}; background: transparent;")
        layout.addWidget(name)

        summary = QLabel(self._summary_text())
        summary.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px; "
            f"background: transparent;")
        layout.addWidget(summary)

        layout.addStretch()

        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_XS)
        actions.addStretch()

        edit = button("Edit", "ghost",
                      lambda: self.editRequested.emit(self.profile),
                      size="sm")
        delete = button("Delete", "ghost",
                        lambda: self.deleteRequested.emit(self.profile),
                        size="sm")
        actions.addWidget(edit)
        actions.addWidget(delete)
        layout.addLayout(actions)

    def _summary_text(self):
        """"2 floors · 7 rooms · 43 items" -- but pluralised properly."""
        floors = len(self.profile.floors)
        rooms = sum(len(f.rooms) for f in self.profile.floors)
        items = len(self.profile.items)

        def plural(count, word):
            return f"{count} {word}" + ("" if count == 1 else "s")

        return " · ".join([
            plural(floors, "floor"),
            plural(rooms, "room"),
            plural(items, "item"),
        ])

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
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(hovered=False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.opened.emit(self.profile)
        super().mouseReleaseEvent(event)


class NewProfileCard(QFrame):
    """The dashed "+" card that sits after the real ones."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(CARD_WIDTH)
        self.setMinimumHeight(CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style(hovered=False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(2)

        plus = QLabel("+")
        plus.setAlignment(Qt.AlignCenter)
        plus.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 26px; background: transparent;")
        layout.addWidget(plus)

        caption = QLabel("New profile")
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE}px; "
            f"background: transparent;")
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


class ProfileScreen(QWidget):
    """The whole launcher screen."""

    profileOpened = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_XL * 2, theme.SPACE_XL * 2,
                                 theme.SPACE_XL * 2, theme.SPACE_XL)
        outer.setSpacing(theme.SPACE_XS)

        outer.addWidget(label("Inventory", "screenTitle"))
        outer.addWidget(label(
            "Choose a profile to open, or create a new one. Each profile keeps "
            "its own floors, rooms, containers, items and tags.", "caption"))
        outer.addSpacing(theme.SPACE_XL)

        # The card grid scrolls, so a long list of profiles still works.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._grid_holder = QWidget()
        self._grid = QGridLayout(self._grid_holder)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(theme.SPACE_LG)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(self._grid_holder)
        outer.addWidget(scroll, 1)

        self.reload()

    # -- building the grid --------------------------------------------------

    def reload(self):
        """Re-read the save folder and rebuild the card grid from scratch.

        Rebuilding everything after any change is more work than surgically
        updating one card, but it is far harder to get wrong -- the screen can
        never drift out of step with what is on disk.
        """
        self.profiles = storage.load_profiles()

        while self._grid.count():
            old = self._grid.takeAt(0)
            if old.widget():
                old.widget().deleteLater()

        position = 0
        for profile in self.profiles:
            card = ProfileCard(profile)
            card.opened.connect(self.profileOpened.emit)
            card.editRequested.connect(self._edit_profile)
            card.deleteRequested.connect(self._delete_profile)
            self._grid.addWidget(card, position // COLUMNS, position % COLUMNS)
            position += 1

        new_card = NewProfileCard()
        new_card.clicked.connect(self._create_profile)
        self._grid.addWidget(new_card, position // COLUMNS, position % COLUMNS)

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

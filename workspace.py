"""
workspace.py
============

The window you get after opening a profile: a narrow sidebar on the left, and
one of the two big sections filling the rest.

    Layout  the floors, rooms and containers -- where things are
    Items   the catalog and its tags       -- what things are

Both edit the same Profile object in memory, so a container you draw in Layout
shows up instantly in the "lives in" dropdown over in Items. There is only one
copy of the data and both sections point at it.

SAVING
------
There is no Save button, and that is on purpose -- an app you use while
standing in a garage holding a box should not be able to lose your work
because you forgot to press something.

Instead, any change schedules a save 500 milliseconds from now. If more
changes arrive in the meantime the timer restarts, so dragging a room across
the floor writes one file at the end rather than a hundred on the way. This
pattern is called debouncing and it is worth knowing -- the same trick works
for search boxes, window resizing, and anything else that fires far more often
than you want to react to it.
"""

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QFrame, QLabel,
    QButtonGroup, QMenu, QFileDialog, QMessageBox,
)

import export
import storage
import theme
from items_section import ItemsSection
from layout_section import LayoutSection
from models import short
from widgets import ElidingLabel, button, divider

SIDEBAR_WIDTH = 188
SAVE_DELAY_MS = 500


class Workspace(QWidget):
    """One open profile, with its two sections."""

    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None

        # Set up before anything can ask for a save.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_now)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(
            lambda: self._status.setText(""))

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()

        self.layout_section = LayoutSection()
        self.layout_section.dataChanged.connect(self.schedule_save)
        self._stack.addWidget(self.layout_section)

        self.items_section = ItemsSection()
        self.items_section.dataChanged.connect(self.schedule_save)
        self.items_section.locateRequested.connect(self.locate_container)
        self._stack.addWidget(self.items_section)

        outer.addWidget(self._stack, 1)

        self._install_shortcuts()

    # -- keyboard ---------------------------------------------------------------

    def _install_shortcuts(self):
        """Every shortcut lives here rather than being scattered per screen.

        One place to look means you can answer "what does Ctrl+B do?" without
        hunting, and it lets a shortcut switch sections on the way -- Ctrl+F
        works from the Layout screen by jumping to Items first, which is what
        you actually meant by pressing it.
        """
        bindings = [
            ("Ctrl+1", lambda: self._go(0)),
            ("Ctrl+2", lambda: self._go(1)),
            ("Ctrl+F", lambda: self._in_items(self.items_section.focus_search)),
            ("Ctrl+N", lambda: self._in_items(self.items_section.new_item)),
            ("Ctrl+B", lambda: self._in_items(self.items_section.bulk_add)),
            ("Ctrl+D", lambda: self._in_layout(
                self.layout_section.duplicate_selection)),
        ]

        for keys, action in bindings:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(action)

    def _go(self, index):
        self._show_section(index)
        (self._layout_button if index == 0 else self._items_button).setChecked(True)

    def _in_items(self, action):
        """Switch to the Items screen, then do something there."""
        self._go(1)
        action()

    def _in_layout(self, action):
        """Do something on the Layout screen, but only while you are on it.

        The opposite of _in_items on purpose. Ctrl+F means "let me search",
        so jumping to the screen that can search is helpful. Ctrl+D means
        "copy what I picked", and nothing is picked on a screen you are not
        looking at -- so on the Items screen it should do nothing at all
        rather than yank you somewhere else.
        """
        if self._stack.currentIndex() == 0:
            action()

    # -- finding things -----------------------------------------------------------

    def locate_container(self, container_id):
        """Show a container on the floor plan. Comes from the Items screen."""
        self._go(0)
        self.layout_section.reveal_container(container_id)

    # -- sidebar --------------------------------------------------------------

    def _build_sidebar(self):
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(bar)
        layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                  theme.SPACE_MD, theme.SPACE_MD)
        layout.setSpacing(theme.SPACE_SM)

        # Profile name with its color dot.
        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_SM)
        self._profile_dot = QFrame()
        self._profile_dot.setFixedSize(10, 10)
        header.addWidget(self._profile_dot)

        # The sidebar is only 188px wide, so this one needs the pixel
        # fit on top of the character limit.
        self._profile_name = ElidingLabel("")
        self._profile_name.setStyleSheet(
            f"font-size: {theme.FONT_SIZE_LG}px; font-weight: 600;")
        header.addWidget(self._profile_name, 1)
        layout.addLayout(header)

        layout.addSpacing(theme.SPACE_MD)

        # Section navigation. Exactly one is pressed in at a time.
        self._nav = QButtonGroup(self)
        self._nav.setExclusive(True)

        self._layout_button = self._nav_button("Layout", 0)
        self._items_button = self._nav_button("Items", 1)
        layout.addWidget(self._layout_button)
        layout.addWidget(self._items_button)
        self._layout_button.setChecked(True)

        layout.addStretch()

        self._status = QLabel("")
        self._status.setObjectName("hint")
        self._status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status)

        layout.addWidget(self._build_export_button())
        layout.addWidget(divider())
        layout.addWidget(button("← All profiles", "ghost",
                                self._go_back))

        return bar

    def _build_export_button(self):
        export_button = button("Export ▾", "ghost")
        export_button.setToolTip("Get your data out in a format other "
                                 "programs can read")

        menu = QMenu(export_button)
        menu.addAction("Items as CSV…").triggered.connect(self._export_csv)
        menu.addAction("Floor plans as PDF…").triggered.connect(self._export_pdf)
        export_button.setMenu(menu)

        return export_button

    def _export_csv(self):
        self._run_export(
            "Save item list", "CSV files (*.csv)", ".csv",
            export.export_items_csv,
            lambda count: f"{count} items written to")

    def _export_pdf(self):
        self._run_export(
            "Save floor plans", "PDF files (*.pdf)", ".pdf",
            export.export_floors_pdf,
            lambda count: f"{count} page" + ("" if count == 1 else "s")
                          + " written to")

    def _run_export(self, title, file_filter, extension, writer, describe):
        """Ask where to save, write the file, say what happened.

        The two exports differ only in their file type and their writer
        function, so the picking, the error handling and the confirmation are
        shared rather than written twice.
        """
        if self.profile is None:
            return

        # A sensible default name beats making them invent one every time.
        safe_name = "".join(c for c in self.profile.name
                            if c.isalnum() or c in " -_").strip() or "inventory"
        suggested = os.path.join(os.path.expanduser("~"),
                                 f"{safe_name}{extension}")

        path, _ = QFileDialog.getSaveFileName(self, title, suggested,
                                              file_filter)
        if not path:
            return

        if not path.lower().endswith(extension):
            path += extension

        try:
            result = writer(self.profile, path)
        except OSError as error:
            # Almost always the file being open in Excel, or a folder you
            # cannot write to. Say which, rather than just failing.
            QMessageBox.warning(
                self, "Could not save",
                f"{error}\n\nIf the file is open in another program, close "
                f"it and try again.")
            return

        QMessageBox.information(self, "Exported",
                                f"{describe(result)}\n{path}")

    def _nav_button(self, text, index):
        nav = button(text, "ghost")
        nav.setCheckable(True)
        nav.setMinimumHeight(34)
        nav.clicked.connect(lambda: self._show_section(index))
        self._nav.addButton(nav)
        return nav

    def _show_section(self, index):
        # Coming back to Items may need a refresh: containers can have been
        # renamed, added or deleted over in Layout while we were away.
        if index == 1:
            self.items_section.reload()
        else:
            self.layout_section.refresh()
        self._stack.setCurrentIndex(index)

    # -- opening a profile -----------------------------------------------------

    def open_profile(self, profile):
        self.profile = profile

        self._profile_name.setText(short(profile.name))
        self._profile_name.setToolTip(profile.name)
        self._profile_dot.setStyleSheet(
            f"background-color: {profile.color}; border-radius: 5px;")

        self.layout_section.set_profile(profile)
        self.items_section.set_profile(profile)

        self._layout_button.setChecked(True)
        self._stack.setCurrentIndex(0)

    def _go_back(self):
        # Never leave an edit sitting in the timer when the screen changes.
        self.flush_save()
        self.backRequested.emit()

    # -- saving -------------------------------------------------------------------

    def schedule_save(self):
        """Ask for a save shortly. Restarts the clock if one is already
        pending, so a burst of changes results in a single write."""
        if self.profile is None:
            return
        self._save_timer.start(SAVE_DELAY_MS)

    def flush_save(self):
        """Save right now if anything is pending. Called when leaving the
        profile or closing the window."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()

    def _save_now(self):
        if self.profile is None:
            return
        storage.save_profile(self.profile)

        self._status.setText("Saved")
        self._status_timer.start(1400)

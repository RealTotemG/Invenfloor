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

import json
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QFrame, QLabel,
    QButtonGroup, QMenu, QFileDialog, QMessageBox, QLineEdit, QPlainTextEdit,
    QTextEdit,
)

import export
import storage
import theme
from items_section import ItemsSection
from layout_section import LayoutSection
from models import Profile, short
from undo import History
from widgets import ElidingLabel, button, divider

SIDEBAR_WIDTH = 188
SAVE_DELAY_MS = 500

SECTION_LAYOUT = 0
SECTION_ITEMS = 1


class Workspace(QWidget):
    """One open profile, with its two sections."""

    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None

        # Undo for this session. See undo.py for why it keeps whole copies.
        self.history = History()
        # True only while a snapshot is being put back, so that putting one
        # back is not itself recorded as a change to undo.
        self._restoring = False

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
            ("Ctrl+Z", self._undo_shortcut),
            ("Ctrl+Y", self.redo),
            # The other redo binding. Which one is "right" depends on which
            # program someone learned it in, and supporting both costs a line.
            ("Ctrl+Shift+Z", self.redo),
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

    def _undo_shortcut(self):
        """Ctrl+Z, deciding first whether the text box you are in wants it.

        Every text field in every program undoes your typing on Ctrl+Z, and
        taking that away to revert a whole container move instead would be a
        nasty surprise mid-word. So while the cursor is in a text box, the
        text box gets it; everywhere else, the app does.
        """
        focused = self.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit)):
            focused.undo()
            return
        self.undo()

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

        layout.addLayout(self._build_undo_row())
        layout.addWidget(self._build_export_button())
        layout.addWidget(divider())
        layout.addWidget(button("← All profiles", "ghost",
                                self._go_back))

        return bar

    def _build_undo_row(self):
        """Undo and redo, side by side in the sidebar.

        In the sidebar rather than a toolbar because undo is not a Layout
        thing or an Items thing, it is a program thing, and it should be in
        the same place whichever screen you are on. Deleting a pile of items
        is exactly the moment you want to see an undo button, and the Items
        screen is where that happens.

        A bare layout rather than a QWidget holding one. A wrapper widget
        would take the stylesheet's background and draw a panel-colored band
        across the sidebar, which looks like a mistake because it is one.
        """
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(theme.SPACE_XS)

        # size through the helper rather than setProperty afterwards: the
        # stylesheet is matched when the widget is created, and a property set
        # later needs the style re-polished before anything looks different.
        self._undo_button = button("↶ Undo", "ghost", self.undo, size="sm")
        self._redo_button = button("↷ Redo", "ghost", self.redo, size="sm")

        line.addWidget(self._undo_button, 1)
        line.addWidget(self._redo_button, 1)

        self._refresh_undo_buttons()
        return line

    def _refresh_undo_buttons(self):
        """Gray out whichever direction has nowhere to go.

        A disabled button is an honest answer to "can I undo this?" and it
        costs nothing to keep right. The tooltips say how many steps are
        left, which is the one number a person actually wants here.
        """
        back, forward = self.history.depth()

        self._undo_button.setEnabled(back > 0)
        self._redo_button.setEnabled(forward > 0)

        self._undo_button.setToolTip(
            f"Undo the last change  (Ctrl+Z)\n{back} step"
            + ("" if back == 1 else "s") + " back"
            if back else "Nothing to undo yet  (Ctrl+Z)")
        self._redo_button.setToolTip(
            f"Redo  (Ctrl+Y)\n{forward} step"
            + ("" if forward == 1 else "s") + " forward"
            if forward else "Nothing to redo  (Ctrl+Y)")

    # -- undo -------------------------------------------------------------------

    def snapshot(self):
        """The profile as JSON text: one entry in the undo history."""
        if self.profile is None:
            return None
        return json.dumps(self.profile.to_dict(), separators=(",", ":"))

    def undo(self):
        self._go_to(self.history.undo(), "Undone", "Nothing to undo")

    def redo(self):
        self._go_to(self.history.redo(), "Redone", "Nothing to redo")

    def _go_to(self, step, done_message, empty_message):
        if step is None:
            self._flash(empty_message)
            return
        self._restore(step)
        self._flash(done_message)

    def _restore(self, step):
        """Put a remembered state back on screen.

        Three things happen in an order that matters. The view state is read
        BEFORE the profile is replaced, because it is read off the things that
        are about to be thrown away. The screen is switched BEFORE the rebuild,
        so the section being rebuilt is the visible one and lays out at its
        real size. And the save happens directly rather than through the
        timer, because going through the timer would come back round as a
        change to record and undo would undo itself.
        """
        self._save_timer.stop()
        self._restoring = True
        try:
            if step.section != self._stack.currentIndex():
                self._go(step.section)

            layout_state = self.layout_section.view_state()

            self.profile = Profile.from_dict(json.loads(step.snapshot))
            self.layout_section.rebind_profile(self.profile, layout_state)
            self.items_section.rebind_profile(self.profile)

            storage.save_profile(self.profile)
        finally:
            self._restoring = False

        self._refresh_undo_buttons()

    def _flash(self, message):
        self._status.setText(message)
        self._status_timer.start(1400)

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

        # After the sections are set up, not before. set_profile can itself
        # change the data -- a profile with no floors gets given one -- and
        # starting the history here means that arrives as part of where you
        # began rather than as a change you can undo away.
        self.history.start(self.snapshot())
        self._refresh_undo_buttons()

    def _go_back(self):
        # Never leave an edit sitting in the timer when the screen changes.
        self.flush_save()
        # The history belongs to the profile that was open, so it goes with
        # it. Undoing your way from one profile into another is not a thing
        # anyone wants, and leaving the stack lying around is how it happens.
        self.history.clear()
        self._refresh_undo_buttons()
        self.backRequested.emit()

    # -- saving -------------------------------------------------------------------

    def schedule_save(self):
        """Ask for a save shortly. Restarts the clock if one is already
        pending, so a burst of changes results in a single write."""
        if self.profile is None:
            return
        if self._restoring:
            # Rebuilding the screens around a restored profile makes widgets
            # report changes -- a selection cleared, a list refilled -- and
            # none of them are edits. The restore has already written the file
            # itself, so the honest answer to all of it is "no thank you".
            # Without this, undo could hand itself a step to undo.
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

        # An undo step per save, which is a better unit than it sounds. The
        # save is already debounced by half a second, so a drag across the
        # floor is one save and one step, and a burst of typing is one save
        # and one step, rather than one per mouse move and one per letter.
        if not self._restoring:
            if self.history.record(self.snapshot(), self._stack.currentIndex()):
                self._refresh_undo_buttons()

        self._flash("Saved")

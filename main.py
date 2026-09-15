"""
main.py
=======

Start the app with:   python main.py

This file is deliberately tiny. It creates the application, applies the theme,
and swaps between the two top-level screens:

    ProfileScreen   pick or create a profile
    Workspace       one open profile (Layout and Items)

A QStackedWidget holds both and shows one at a time -- think of it as a deck of
cards where only the top one is visible. Nothing is destroyed when you switch,
so going back to the launcher and opening a profile again is instant.

WHERE TO LOOK FOR THINGS
------------------------
    theme.py            every color, size and font -- start here to restyle
    models.py           what a profile, floor, room, container, item and tag are
    storage.py          loading and saving; also the packaging-safe save path
    widgets.py          shared pieces: color picker, tag chips, dialogs
    profile_screen.py   the launcher
    workspace.py        the sidebar shell and the autosave timer
    layout_section.py   floors, toolbar, and the wiring for the canvas
    floor_view.py       the canvas: grid, zoom, pan, drawing tools
    floor_items.py      how a room and a container draw and drag themselves
    inspector.py        the right-hand edit panel
    items_section.py    the item catalog and the tag manager
"""

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

import theme
from profile_screen import ProfileScreen
from workspace import Workspace


class MainWindow(QMainWindow):
    """The single application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inventory")
        # The size to fall back to, not the size you start at -- main() opens
        # the window maximized. This is what you get when you un-maximize it,
        # so it wants to be a comfortable working size rather than a token one.
        self.resize(1400, 880)
        self.setMinimumSize(1080, 680)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self.profile_screen = ProfileScreen()
        self.profile_screen.profileOpened.connect(self._open_profile)
        self._stack.addWidget(self.profile_screen)

        self.workspace = Workspace()
        self.workspace.backRequested.connect(self._show_launcher)
        self._stack.addWidget(self.workspace)

        self._stack.setCurrentWidget(self.profile_screen)

    def _open_profile(self, profile):
        self.workspace.open_profile(profile)
        self._stack.setCurrentWidget(self.workspace)

    def _show_launcher(self):
        # Re-read from disk so the cards show updated room and item counts.
        self.profile_screen.reload()
        self._stack.setCurrentWidget(self.profile_screen)

    def closeEvent(self, event):
        """Qt calls this when the window is closing.

        Any edit still sitting in the autosave timer gets written now, so
        closing the app immediately after a change never loses it.
        """
        self.workspace.flush_save()
        super().closeEvent(event)


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("Inventory")

    # One font for the whole app. Segoe UI is the Windows system font; on
    # other platforms Qt quietly substitutes the closest match.
    font = QFont("Segoe UI")
    font.setPixelSize(theme.FONT_SIZE)
    application.setFont(font)

    # One stylesheet for the whole app, straight out of theme.py.
    application.setStyleSheet(theme.stylesheet())

    window = MainWindow()

    # Maximized, not fullscreen. Fullscreen hides the title bar and the
    # taskbar, which is right for a game and wrong for something you keep
    # open beside other windows. Maximized fills the screen you have and
    # still lets you drag the window down or alt-tab away.
    window.showMaximized()

    # exec() runs until the last window closes. sys.exit passes the result on
    # as the process exit code.
    sys.exit(application.exec())


# This guard means the app only starts when you RUN this file, not when
# another file imports it. Standard Python practice, and it is what lets the
# test script import main.py without launching a window.
if __name__ == "__main__":
    main()

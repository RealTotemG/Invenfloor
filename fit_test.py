"""
fit_test.py
===========

Does the text fit in the space the layout gave it.

THE BUG THIS EXISTS FOR
-----------------------
setWordWrap(True) on its own is not enough. A layout only asks a widget "how
tall are you at this width?" if the widget's size policy says it has an
answer, and QLabel does not set that flag for you. So the layout reserves one
line, the text wraps onto two, and the second line is drawn outside the space
reserved for it. On screen that reads as text sliced in half or sitting on top
of whatever is underneath, and it sends you hunting for a font problem when
the cause is three lines away in a layout.

widgets.wrapped() is the fix, and the trouble with a fix like that is
remembering to use it. The one that got missed was the message line of
empty_state: almost every message there is three words, and one of them is
not. The Items screen puts whatever somebody typed into it, as

    Nothing matches "stainless steel hex socket set 3/8 drive"

centered and unwrapped, which runs off BOTH ends at once. The one thing on
that screen worth reading is the part they cannot read.

So this does not check that one label. It walks every empty state in the app,
and the panels around them, at a width narrow enough to force the question,
and asks every label whether it fits. Measuring rather than looking, because
this is exactly the bug that looks fine in the window you happened to test in.

    python fit_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt, qInstallMessageHandler
from PySide6.QtWidgets import (
    QApplication, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

# Showing a widget on the offscreen platform prints "This plugin does not
# support propagateSizeHints()" every single time, which buries the results
# under a hundred lines of something nobody can act on. Anything else Qt has
# to say still comes through.
qInstallMessageHandler(
    lambda kind, context, message:
    None if "propagateSizeHints" in message else print(message, file=sys.stderr))

import inspector
import items_section
import models
import theme
import widgets


PASSED = []
FAILED = []


def check(label, ok, why=""):
    (PASSED if ok else FAILED).append(label)
    print(f"{'  ok  ' if ok else ' FAIL '} {label}")
    if not ok and why:
        print(f"        {why}")


def overflowing(root):
    """Every visible label in `root` whose text will not fit its box.

    Two ways to not fit, and they show up differently on screen:

      too NARROW, on a label that does not wrap: the ends are cut off, or with
      centered text, both ends at once.

      too SHORT: the text wraps to more lines than the layout reserved room
      for, and the extra lines are painted over whatever is below.
    """
    problems = []
    for found in root.findChildren(QLabel):
        text = found.text()
        if not text or not found.isVisible():
            continue
        if found.width() <= 1 or found.height() <= 1:
            continue

        # An eliding label shortens its own text on purpose, so "wider than
        # the box" is what it is for rather than a fault.
        if isinstance(found, widgets.ElidingLabel):
            continue

        wide = found.fontMetrics().horizontalAdvance(text)

        # Measured off the font, not asked of the label, and that distinction
        # is the whole thing. sizeHint() on a wrapping label with no
        # heightForWidth reports the height of ONE line, because without the
        # policy flag the label has no idea it will be asked to wrap. The
        # layout then hands it exactly that, so comparing the two always
        # agrees, and a check written that way can never fail. Ask the font
        # how tall this text really is at this width instead.
        if found.wordWrap():
            tall = found.fontMetrics().boundingRect(
                QRect(0, 0, found.width(), 0),
                int(Qt.TextWordWrap) | int(found.alignment()), text).height()
        else:
            tall = found.fontMetrics().height()

        if not found.wordWrap() and wide > found.width() + 1:
            problems.append(f"{text[:44]!r} needs {wide}px across a "
                            f"{found.width()}px box and does not wrap")
        elif tall > found.height():
            problems.append(f"{text[:44]!r} wraps to {tall}px of text in a "
                            f"{found.height()}px box "
                            f"(heightForWidth={found.hasHeightForWidth()})")
    return problems


def in_a_panel(widget, width=300, height=260):
    """Put a widget in something exactly as wide as a real side panel.

    Fixed width on purpose. Left to itself a widget grows until its contents
    fit, which is the thing being tested, so the test would always pass.
    """
    holder = QWidget()
    holder.setObjectName("plain")
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)
    layout.addStretch()
    holder.setFixedWidth(width)
    holder.resize(width, height)
    holder.show()
    QApplication.processEvents()
    QApplication.processEvents()
    return holder


def a_profile(with_tags=True, with_items=True):
    profile = models.Profile(id="p1", name="Check")
    floor = models.Floor(id="f1", name="Ground")
    room = models.Room(id="r1", name="Garage",
                       points=models.rectangle_points(400, 300))
    room.containers = [models.Container(id="c1", name="Racking", x=10, y=10,
                                        w=100, h=50, tier_count=3)]
    floor.rooms = [room]
    profile.floors = [floor]
    if with_tags:
        profile.tags = [models.Tag(id="t1", name="Tools")]
    if with_items:
        profile.items = [models.Item(id="i1", name="Sockets")]
    return profile


def main():
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(theme.stylesheet())

    # -- the one that was wrong ---------------------------------------------
    # A real search term, not a short one. This is the case that put the fix
    # in, so it is the case named out loud rather than folded into the sweep.
    typed = "stainless steel hex socket set 3/8 drive"
    panel = in_a_panel(widgets.empty_state(
        f'Nothing matches "{typed}"', "Use the Create button up top to add it."))
    problems = overflowing(panel)
    check("a long search term fits inside the empty state",
          not problems, "; ".join(problems))

    # And the part that makes it worth fixing rather than truncating: the
    # whole term is still there to read, on as many lines as it takes.
    shown = [found.text() for found in panel.findChildren(QLabel)]
    check("and the whole term is still on screen, not cut off",
          any(typed in text for text in shown), str(shown))

    # -- every empty state in the app, at panel width -----------------------
    # Lifted from where they are written, so a new one added there without a
    # thought for wrapping gets caught here too.
    states = [
        ("nothing selected", "Nothing selected",
         "Click a room or a container on the floor to edit it here."),
        ("no tags, in the manager", "No tags yet",
         "Make one for anything you would want to find across several rooms: "
         "Tools, Christmas, Fragile."),
        ("no tags, in the picker", "No tags yet",
         "Use + New tag below to make your first one."),
        ("no tags, on the items screen", "No tags yet",
         "Tags let you group items across rooms: 'Tools', 'Christmas', "
         "'Fragile'."),
        ("nothing running low", "Nothing is running low",
         "Set a level on an item to be told when it is."),
        ("everything filed", "Everything has a home",
         "Nothing is waiting to be put away."),
        ("nothing misfiled", "Nothing looks out of place",
         "Every tagged item is in a room that expects that tag."),
        ("no items at all", "No items to show",
         "Add one with the button up in the corner, or from a container in "
         "the Layout view."),
    ]
    for name, message, hint in states:
        for width in (300, 260, 220):
            panel = in_a_panel(widgets.empty_state(message, hint), width=width)
            problems = overflowing(panel)
            if problems:
                check(f"{name}, at {width}px", False, "; ".join(problems))
                break
        else:
            check(f"{name} fits at 300, 260 and 220px wide", True)

    # -- and the real dialogs, built the way the app builds them ------------
    for name, make in [
        ("the Assign tags dialog with no tags",
         lambda: widgets.TagPickerDialog(None, a_profile(with_tags=False),
                                         set(), subject="container")),
        ("the Assign tags dialog with tags in it",
         lambda: widgets.TagPickerDialog(None, a_profile(), set(),
                                         subject="item")),
    ]:
        dialog = make()
        dialog.resize(dialog.minimumWidth(), dialog.minimumHeight())
        dialog.show()
        QApplication.processEvents()
        QApplication.processEvents()
        problems = overflowing(dialog)
        check(f"{name} fits at its own minimum size",
              not problems, "; ".join(problems))

    # -- the inspector, which is the panel all of this is really about ------
    try:
        panel = inspector.Inspector()
    except TypeError:
        panel = None
    if panel is not None:
        panel.setFixedWidth(300)
        panel.resize(300, 600)
        panel.show()
        QApplication.processEvents()
        QApplication.processEvents()
        problems = overflowing(panel)
        check("the inspector fits with nothing selected",
              not problems, "; ".join(problems))

    # -- the guard itself ---------------------------------------------------
    # A test that can only pass is not a test, so here is a label that really
    # does get cut, to prove the sweep above would say so.
    #
    # Getting this wrong took a couple of tries and the reason is worth
    # writing down. setWordWrap(True) on its own turns out to be FINE in this
    # version of Qt: the label reports heightForWidth by itself and an
    # ordinary layout honors it. What still cuts text is the vertical size
    # policy. Fixed means "this height and no other", the layout stops asking,
    # and the second and third lines are painted outside the box. That is what
    # widgets.wrapped() is really protecting against, and an earlier version
    # of this check reached for setWordWrap alone and passed no matter what,
    # which is the same failure as having no check at all.
    long_enough = ("A sentence quite long enough to need three lines in a "
                   "narrow panel, which is the whole point of this one, and "
                   "then some more besides.")

    wrong = QLabel(long_enough)
    wrong.setWordWrap(True)
    wrong.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    holder = in_a_panel(wrong, width=200)
    check("the check can actually fail, on a label pinned to one height",
          bool(overflowing(holder)),
          "nothing was reported for a label that is definitely cut off, so "
          "this file is not measuring what it claims to measure")

    right = widgets.wrapped(QLabel(long_enough))
    right.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    widgets.wrapped(right)                     # wrapped() sets the policy back
    holder = in_a_panel(right, width=200)
    check("and passes once that same label goes through wrapped()",
          not overflowing(holder), "; ".join(overflowing(holder)))

    print()
    if FAILED:
        print(f"{len(FAILED)} of {len(PASSED) + len(FAILED)} FAILED")
        return 1
    print(f"all {len(PASSED)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

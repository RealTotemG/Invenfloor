"""
focus_test.py
=============

What the "Work inside this room" button says, and when it does nothing.

WHY THIS IS WORTH PINNING DOWN
------------------------------
A button you can still press when it would do nothing is a small lie about
what is going on. So while you are already inside a room, that button reads
"Currently working in this room" and stops being clickable.

Keeping that true is not a one-line job, and that is the point of this file.
The state lives in three places at once: the canvas knows which room is
focused, the panel holds a copy so it can draw the right button, and the
screen in the middle wires the two together. Any of those three wires can be
cut without anything crashing. What you get instead is a button that offers to
take you somewhere you already are, which is the kind of wrong that nobody
files a bug about and everybody quietly learns to ignore.

The case that would go first is the one with two rooms in it: focus one,
select the other. Nothing in a single-room test would ever notice.

    python focus_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QPushButton

import inspector
import layout_section
import models
import theme

qInstallMessageHandler(
    lambda kind, context, message:
    None if "propagateSizeHints" in message else print(message, file=sys.stderr))


PASSED = []
FAILED = []


def check(label, ok, why=""):
    (PASSED if ok else FAILED).append(label)
    print(f"{'  ok  ' if ok else ' FAIL '} {label}")
    if not ok and why:
        print(f"        {why}")


def a_profile():
    profile = models.Profile(id="p1", name="Check")
    floor = models.Floor(id="f1", name="Ground")
    # Side by side rather than stacked, so neither sits on top of the other
    # and "which room is this" is never ambiguous.
    for n, (name, left) in enumerate([("Garage", 0), ("Workshop", 400)],
                                     start=1):
        corners = [[x + left, y]
                   for x, y in models.rectangle_points(300, 200)]
        room = models.Room(id=f"r{n}", name=name, points=corners)
        room.containers = [models.Container(id=f"c{n}", name=f"Shelf {n}",
                                            x=left + 10, y=10, w=80, h=40)]
        floor.rooms.append(room)
    profile.floors = [floor]
    return profile


def the_button(section):
    """The focus button in the panel, whichever of its two forms is showing."""
    for found in section.inspector.findChildren(QPushButton):
        if "Work inside this room" in found.text():
            return found, "invitation"
        if "Currently working in this room" in found.text():
            return found, "statement"
    return None, "missing"


def main():
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(theme.stylesheet())

    profile = a_profile()
    garage, workshop = profile.floors[0].rooms

    section = layout_section.LayoutSection()
    section.set_profile(profile)
    section.resize(1200, 760)
    section.show()
    application.processEvents()
    application.processEvents()

    def settle():
        application.processEvents()
        application.processEvents()

    # -- selected, but not inside it ----------------------------------------
    section.inspector.show_selection(garage)
    settle()
    found, kind = the_button(section)
    check("selecting a room offers to take you into it",
          kind == "invitation" and found.isEnabled(),
          f"{kind}, enabled={found.isEnabled() if found else None}")

    # -- inside it ----------------------------------------------------------
    section._focus_room(garage)
    settle()
    found, kind = the_button(section)
    check("once you are inside, it says so instead",
          kind == "statement", kind)
    check("and it cannot be pressed",
          found is not None and not found.isEnabled())
    check("it says how to get back out, since the button no longer does it",
          found is not None and found.toolTip().strip() != "",
          repr(found.toolTip()) if found else "")

    # -- the case a one-room test would never catch -------------------------
    # Standing in the Garage, select the Workshop. The panel is now describing
    # a room you are NOT in, so the button has to go back to being an offer.
    # Getting this wrong needs only a comparison against "is anything focused"
    # rather than against which room.
    section.inspector.show_selection(workshop)
    settle()
    found, kind = the_button(section)
    check("standing in one room and selecting another offers the other one",
          kind == "invitation" and found.isEnabled(),
          f"{kind}, enabled={found.isEnabled() if found else None}")

    check("and the panel still believes it is the first room you are in",
          section.inspector.focused_room_id == garage.id,
          str(section.inspector.focused_room_id))

    # -- and pressing it actually moves you ---------------------------------
    found.click()
    settle()
    check("pressing it walks you into the room the panel is describing",
          section.inspector.focused_room_id == workshop.id,
          str(section.inspector.focused_room_id))
    found, kind = the_button(section)
    check("so the button turns into the statement",
          kind == "statement" and not found.isEnabled(), kind)

    # -- stepping out -------------------------------------------------------
    section.view.set_focused_room(None)
    settle()
    found, kind = the_button(section)
    check("stepping back out turns it into an offer again",
          kind == "invitation" and found.isEnabled(), kind)
    check("and nothing is focused any more",
          section.inspector.focused_room_id is None,
          str(section.inspector.focused_room_id))

    # -- opening a different profile must not leave the old room focused ----
    # Otherwise the panel carries a room id from a profile that is no longer
    # open, and the first room of the new one with a matching id gets the
    # disabled button for no reason anybody could work out.
    section._focus_room(workshop)
    settle()
    section.set_profile(a_profile())
    settle()
    check("opening another profile forgets which room you were in",
          section.inspector.focused_room_id is None,
          str(section.inspector.focused_room_id))

    # The same thing again, asked of the panel on its own. Above, the screen
    # clears the canvas first and the panel hears about it that way, so the
    # panel's own line doing it is never reached and could be deleted without
    # anything going red. It is the backstop for the day somebody rewires the
    # screen, which is exactly the day nobody is thinking about this button.
    alone = inspector.Inspector()
    alone.set_profile(profile)
    alone.focused_room_id = garage.id
    alone.set_profile(a_profile())
    check("and the panel clears it by itself, without being told",
          alone.focused_room_id is None, str(alone.focused_room_id))

    # -- where a room sits, and when it is on top of another ----------------
    # Size without position was the trap: type a room's real measurements and
    # it grows from its top-left into its neighbour, with dragging the only
    # way back. These check the boxes exist and that the warning can tell a
    # neighbour from a collision, which is the part that decides whether
    # anybody reads it.
    from PySide6.QtWidgets import QLabel, QSpinBox
    import models as M

    fresh = a_profile()
    ground = fresh.floors[0]
    garage, workshop = ground.rooms

    section.set_profile(fresh)
    settle()
    section.inspector.show_selection(workshop)
    settle()

    captions = [found.text() for found in section.inspector.findChildren(QLabel)
                if found.text() in ("Size", "Position", "L", "W", "X", "Y")]
    check("a room has boxes for where it is as well as how big it is",
          captions == ["Size", "L", "W", "Position", "X", "Y"], str(captions))
    check("and there are four of them to type in",
          len(section.inspector.findChildren(QSpinBox)) == 4,
          f"{len(section.inspector.findChildren(QSpinBox))} boxes")

    def panel_says(phrase):
        return any(phrase in found.text()
                   for found in section.inspector.findChildren(QLabel))

    check("two rooms side by side are not called an overlap",
          not panel_says("sitting on top"),
          "it warns about rooms that only share a wall, which is what "
          "neighbouring rooms do")

    # a_profile bakes the 400 of separation into the Workshop's own points
    # rather than its x, so x is 0 to start with and moving it LEFT is what
    # brings it back over the Garage.
    workshop.x = -300                     # now half on top of the Garage
    section.inspector.show_selection(workshop)
    settle()
    check("but a room moved on top of another one is",
          panel_says("sitting on top"))
    check("and the warning names which one",
          any("Garage" in found.text() and "sitting on top" in found.text()
              for found in section.inspector.findChildren(QLabel)))

    workshop.x = 0                        # and back to where it was
    section.inspector.show_selection(workshop)
    settle()
    check("moving it off again clears the warning",
          not panel_says("sitting on top"))

    # The rule itself, on the arrangements two rooms can actually be in.
    def placed(name, points, x=0, y=0):
        made = M.Room(id=name, name=name, points=[list(p) for p in points])
        made.x = x
        made.y = y
        return made

    square = M.rectangle_points(100, 100)
    for label_, first, second, expected in [
        ("half on top", placed("a", square), placed("b", square, 50), True),
        ("well apart", placed("a", square), placed("b", square, 200), False),
        ("one inside the other", placed("a", square),
         placed("b", M.rectangle_points(20, 20), 10, 10), True),
        ("sharing a wall", placed("a", square), placed("b", square, 100), False),
        ("touching at one corner", placed("a", square),
         placed("b", square, 100, 100), False),
        ("exactly on top", placed("a", square), placed("b", square), True),
        ("a square in an L's notch", placed("a", M.l_shape_points(200, 200)),
         placed("b", M.rectangle_points(60, 60), 130, 10), False),
    ]:
        check(f"overlap, {label_}",
              M.rooms_overlap(first, second) is expected
              and M.rooms_overlap(second, first) is expected,
              f"{M.rooms_overlap(first, second)} one way, "
              f"{M.rooms_overlap(second, first)} the other")

    print()
    if FAILED:
        print(f"{len(FAILED)} of {len(PASSED) + len(FAILED)} FAILED")
        return 1
    print(f"all {len(PASSED)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

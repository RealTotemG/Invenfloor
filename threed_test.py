"""
threed_test.py
==============

The 3D room: when it opens by itself, and what Escape does.

WHAT THIS IS ABOUT
------------------
3D is a setting, not a trip. With it on, stepping into any room shows that
room in 3D, and the setting is kept with the profile so it survives closing
the app. A warehouse of identical racking is easier flat; a house is easier in
3D, and two profiles are allowed to disagree.

Escape is a ladder, one rung per press:

    let go of the shelf you have selected
    show this room flat, still standing in it
    step out of the room
    clear the selection

The middle rung is the one worth writing a file about. Escape used to throw
you out of the room from anywhere, so pressing it to let go of a shelf took
the whole room with it, and there was no way to glance at the flat plan of the
room you were standing in without leaving.

The rung has to be a note about ONE room rather than a change to the setting.
If Escape turned 3D off, the next room you walked into would be flat too, and
the setting would quietly switch itself off every time somebody pressed a key.
If the note never expired, you could never get back into 3D. So it is held by
room id and dropped the moment you step out, and the checks below are mostly
about those two edges.

    QT_QPA_PLATFORM=offscreen python threed_test.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

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
    profile = models.Profile(id="p1", name="Shop")
    floor = models.Floor(id="f1", name="Ground")
    for n, (name, left) in enumerate([("Garage", 0), ("Workshop", 400)],
                                     start=1):
        corners = [[x + left, y]
                   for x, y in models.rectangle_points(300, 200)]
        room = models.Room(id=f"r{n}", name=name, points=corners)
        room.containers = [models.Container(id=f"c{n}", name=f"Shelf {n}",
                                            x=left + 10, y=10, w=80, h=40,
                                            tier_count=3)]
        floor.rooms.append(room)
    profile.floors = [floor]
    return profile


def main():
    application = QApplication.instance() or QApplication([])
    application.setStyleSheet(theme.stylesheet())

    profile = a_profile()
    garage, workshop = profile.floors[0].rooms

    section = layout_section.LayoutSection()
    section.set_profile(profile)
    section.resize(1200, 760)
    section.show()

    def settle():
        application.processEvents()
        application.processEvents()

    def escape():
        section.room_3d.keyPressEvent(
            QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        settle()

    def inside():
        here = section.view.focused_room_item
        return here.room if here is not None else None

    settle()

    check("the setting starts on, and is kept with the profile",
          profile.view_3d is True)

    # -- it opens by itself -------------------------------------------------
    section._focus_room(garage)
    settle()
    check("stepping into a room opens it in 3D without being asked",
          section.showing_3d(), "the flat canvas is showing")
    check("and the room is the one you stepped into",
          inside() is garage, str(inside()))

    # -- the ladder ---------------------------------------------------------
    section.room_3d.select(garage.containers[0])
    settle()
    escape()
    check("Escape lets go of the shelf before it does anything else",
          section.room_3d.selected is None and section.showing_3d(),
          f"selected={section.room_3d.selected}, 3D={section.showing_3d()}")

    escape()
    check("Escape again shows the room flat",
          not section.showing_3d(), "still in 3D")
    check("and you are still standing in it",
          inside() is garage, str(inside()))
    check("without the setting having been touched",
          profile.view_3d is True, str(profile.view_3d))

    check("nothing pulls it straight back into 3D",
          not section.showing_3d() and inside() is garage)

    # -- and the note expires -----------------------------------------------
    section._focus_room(workshop)
    settle()
    check("a different room still opens in 3D",
          section.showing_3d() and inside() is workshop,
          f"3D={section.showing_3d()}, inside={inside()}")

    section._focus_room(garage)
    settle()
    check("and so does the same room, once you have left and come back",
          section.showing_3d() and inside() is garage,
          f"3D={section.showing_3d()}, inside={inside()}")

    # -- the switch ---------------------------------------------------------
    escape()
    check("back to flat for this room", not section.showing_3d())

    section._toggle_3d(False)
    settle()
    check("pressing the switch from there means give me 3D back",
          section.showing_3d(), "still flat")
    check("and it does NOT turn the setting off, which was already on",
          profile.view_3d is True, str(profile.view_3d))

    section._toggle_3d(False)
    settle()
    check("pressing it again turns the setting off properly",
          profile.view_3d is False and not section.showing_3d(),
          f"setting={profile.view_3d}, 3D={section.showing_3d()}")

    section._focus_room(workshop)
    settle()
    check("with it off, stepping into a room stays flat",
          not section.showing_3d() and inside() is workshop,
          f"3D={section.showing_3d()}, inside={inside()}")

    section._toggle_3d(True)
    settle()
    check("turning it back on shows the room you are in, in 3D",
          section.showing_3d() and profile.view_3d is True,
          f"3D={section.showing_3d()}, setting={profile.view_3d}")

    # -- and it is saved ----------------------------------------------------
    profile.view_3d = False
    again = models.Profile.from_dict(profile.to_dict())
    check("the setting survives a save and a load",
          again.view_3d is False, str(again.view_3d))
    check("and a save file that predates it comes back with 3D on",
          models.Profile.from_dict(
              {"id": "x", "floors": [], "name": "Old"}).view_3d is True)

    print()
    if FAILED:
        print(f"{len(FAILED)} of {len(PASSED) + len(FAILED)} FAILED")
        return 1
    print(f"all {len(PASSED)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

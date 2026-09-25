"""
make_icon.py
============

Draws the application icon. Run it when you want to change the icon:

    python make_icon.py

It writes `invenfloor.ico`, which `Invenfloor.spec` hands to PyInstaller, and
`invenfloor.png` for anywhere that wants a plain image (a README, a web page,
a desktop entry on Linux).

WHY THIS IS A SCRIPT AND NOT JUST A FILE
----------------------------------------
Because the icon is drawn by the same projection code the 3D room view uses.
`iso.draw_box` puts the box on screen here exactly as it does inside a room,
with the same three faces and the same lighting, so the icon cannot drift away
from what the app actually looks like. Change `TOP_LIGHT` in iso.py and the
icon changes with it the next time this runs.

A committed .ico nobody can regenerate is a small mystery in a repository.
This is twenty lines and removes it.

WHY EACH SIZE IS DRAWN RATHER THAN SCALED DOWN
----------------------------------------------
A 16 pixel icon made by shrinking a 256 pixel one is mud, because the outlines
land between pixels and average themselves into grey. Drawing at each size
means the shape is laid out for the pixels it actually has. It costs nothing
here: there are seven sizes and each is one box.
"""

import os
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

import iso
import theme

# The sizes Windows actually asks for. 16 in the title bar and the small
# taskbar, 32 on the desktop, 48 in Explorer's medium view, 256 for the big
# preview. The ones between are there so Windows never has to scale.
SIZES = [16, 24, 32, 48, 64, 128, 256]

BOX_COLOR = theme.WARNING        # the same amber a container is drawn in
PLATE_COLOR = "#141821"          # a shade darker than the canvas, so the
                                 # icon has an edge against a dark taskbar


def draw(size):
    """One square image of the icon at this exact pixel size."""
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    # A rounded plate behind the box. Without it the shape floats, and a bare
    # isometric box on a transparent background disappears against anything
    # dark, which is where a taskbar icon spends its whole life.
    plate = QPainterPath()
    inset = size * 0.02
    plate.addRoundedRect(QRectF(inset, inset, size - inset * 2,
                                size - inset * 2),
                         size * 0.22, size * 0.22)
    painter.fillPath(plate, QColor(PLATE_COLOR))

    # iso.project puts the origin at the top corner of the floor and measures
    # in room units, so the box has to be moved under the middle of the image
    # and scaled to fit. The numbers below are the box in room units; the
    # transform is what makes it land in the square.
    width = depth = 30.0
    height = 26.0

    # How tall the drawn box is on screen, in room units: the two halves of
    # the diamond plus the vertical rise.
    drawn_height = (width + depth) * iso.SIN30 + height
    drawn_width = (width + depth) * iso.COS30
    scale = size * 0.62 / max(drawn_width, drawn_height)

    painter.translate(size / 2.0, size / 2.0)
    painter.scale(scale, scale)
    # project(0,0,0) is the near-left corner of a box at the origin, so the
    # box is shifted back by half its footprint to sit on its own middle, and
    # up by half its height so the solid mass is centered rather than the
    # floor it stands on.
    painter.translate(0, (height - (width + depth) * iso.SIN30) / 2.0)
    painter.translate(-iso.project(width / 2, depth / 2).x(),
                      -iso.project(width / 2, depth / 2).y())

    # Shelves only at the sizes with room for them. Below about 48 pixels the
    # lines are thinner than a pixel and turn the top face muddy, which reads
    # worse than a plain box.
    tiers = 3 if size >= 48 else 0
    iso.draw_box(painter, 0, 0, width, depth, height, BOX_COLOR, tiers=tiers)

    painter.end()
    return image


def main():
    application = QApplication(sys.argv)          # QPainter needs one to exist
    here = os.path.dirname(os.path.abspath(__file__))

    from PIL import Image

    frames = []
    for size in SIZES:
        path = os.path.join(here, f"_icon_{size}.png")
        draw(size).save(path)
        frames.append(Image.open(path).convert("RGBA"))

    largest = frames[-1]
    largest.save(os.path.join(here, "invenfloor.ico"), format="ICO",
                 sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    largest.save(os.path.join(here, "invenfloor.png"))

    for size in SIZES:                            # tidy up the working files
        os.remove(os.path.join(here, f"_icon_{size}.png"))

    print(f"wrote invenfloor.ico ({len(SIZES)} sizes) and invenfloor.png")
    application.quit()


if __name__ == "__main__":
    main()

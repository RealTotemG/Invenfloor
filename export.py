"""
export.py
=========

Getting your inventory out of the app: a CSV of everything you own, and a PDF
of the floor plans.

Both matter more than they sound. An app that can only show you your data is
an app you have to trust; one that can hand it back in a format anything else
can read is one you can leave. The CSV opens in Excel, the PDF prints -- and
if you ever stop using this program, nothing is trapped inside it.

Nothing here touches the screen. It takes a Profile and a file path, and
writes a file.
"""

import csv
from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter

import floor_items
import theme

PDF_RESOLUTION = 150        # dots per inch


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def export_items_csv(profile, path):
    """Write every item to a spreadsheet-readable file.

    One row per item, with its places collapsed into a single cell. That keeps
    the file readable by eye and by Excel -- one row per PLACE would be more
    "correct" in a database sense, but it makes the same item appear several
    times, which is exactly the confusion the app exists to avoid.

    Returns how many rows were written.
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        # utf-8-sig writes a byte-order mark. Excel on Windows needs it to
        # realize the file is UTF-8; without it, accented characters and the
        # × sign come out as mojibake.
        writer = csv.writer(handle)

        writer.writerow([
            "Name", "Total", "Par level", "Low?", "Tags", "Places",
            "Notes", "Added", "Last changed",
        ])

        for item in sorted(profile.items, key=lambda i: i.name.lower()):
            places = profile.locations_of(item)
            place_text = "; ".join(
                f"{floor.name} / {room.name} / {container.name}"
                + (f" Tier {tier}" if tier else "")
                + f" x{quantity}"
                for floor, room, container, quantity, tier in places
            ) or "Unfiled"

            tag_text = ", ".join(t.name for t in profile.tags_for(item.tag_ids))

            writer.writerow([
                item.name,
                item.total_quantity(),
                item.min_quantity or "",
                "LOW" if item.is_low() else "",
                tag_text,
                place_text,
                item.notes,
                item.created_at,
                item.updated_at,
            ])

    return len(profile.items)


# ---------------------------------------------------------------------------
# PDF FLOOR PLANS
# ---------------------------------------------------------------------------

def export_floors_pdf(profile, path):
    """Render every floor as one landscape page.

    The rooms are drawn by exactly the same code that draws them on screen.
    floor_items.render_floor builds a throwaway scene of real RoomItems and
    renders it into a rectangle, and the canvas, this, and the preview on the
    launcher all go through it. So the printout can never drift out of step
    with the app: fix a drawing bug once and all three are fixed.

    Returns the number of pages written.
    """
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageOrientation(QPageLayout.Landscape)
    writer.setResolution(PDF_RESOLUTION)
    writer.setTitle(f"{profile.name} floor plans")

    painter = QPainter(writer)

    # Room names are near-white so they read on the dark canvas. On paper that
    # would be invisible, so ask floor_items to use dark ink instead, and put
    # it back afterward even if something goes wrong on the way.
    floor_items.PRINT_MODE = True

    try:
        pages = 0
        for index, floor in enumerate(profile.floors):
            if index > 0:
                writer.newPage()
            _draw_floor_page(painter, writer, profile, floor)
            pages += 1

        if pages == 0:
            _draw_message(painter, writer, "This profile has no floors yet.")
            pages = 1
    finally:
        floor_items.PRINT_MODE = False
        painter.end()

    return pages


def _page_rect(writer):
    return QRectF(0, 0, writer.width(), writer.height())


def _draw_floor_page(painter, writer, profile, floor):
    page = _page_rect(writer)
    margin = PDF_RESOLUTION // 2        # half an inch

    _draw_header(painter, page, margin, profile, floor)

    target = QRectF(
        margin,
        margin * 2,
        page.width() - margin * 2,
        page.height() - margin * 3.2,
    )

    if not floor_items.render_floor(painter, profile, floor, target):
        painter.setFont(_font(11))
        painter.setPen(QColor(theme.TEXT_FAINT))
        painter.drawText(page, Qt.AlignCenter, "No rooms on this floor yet.")
        return

    _draw_footer(painter, page, margin, profile, floor)


def _draw_header(painter, page, margin, profile, floor):
    painter.setFont(_font(18, bold=True))
    painter.setPen(QColor(theme.BG_APP))
    painter.drawText(
        QRectF(margin, margin * 0.6, page.width() - margin * 2, margin),
        Qt.AlignLeft | Qt.AlignVCenter, floor.name)

    painter.setFont(_font(10))
    painter.setPen(QColor(theme.TEXT_FAINT))
    painter.drawText(
        QRectF(margin, margin * 0.6, page.width() - margin * 2, margin),
        Qt.AlignRight | Qt.AlignVCenter, profile.name)


def _draw_footer(painter, page, margin, profile, floor):
    rooms = len(floor.rooms)
    containers = sum(len(room.containers) for room in floor.rooms)
    items = sum(len(profile.items_in_room(room)) for room in floor.rooms)

    summary = (f"{rooms} rooms · {containers} containers · {items} items"
               f"          Printed {datetime.now():%d %b %Y}")

    painter.setFont(_font(9))
    painter.setPen(QColor(theme.TEXT_FAINT))
    painter.drawText(
        QRectF(margin, page.height() - margin, page.width() - margin * 2,
               margin * 0.6),
        Qt.AlignLeft | Qt.AlignVCenter, summary)


def _draw_message(painter, writer, text):
    painter.setFont(_font(12))
    painter.setPen(QColor(theme.TEXT_FAINT))
    painter.drawText(_page_rect(writer), Qt.AlignCenter, text)


def _font(point_size, bold=False):
    """A font sized in POINTS rather than pixels.

    Everywhere else in the app uses pixels, because screens are measured that
    way. Paper is not -- a 12-pixel font on a 150 dpi page would come out
    microscopic. Points are a physical size, so they print correctly whatever
    resolution the PDF is written at.
    """
    font = QFont("Segoe UI")
    font.setPointSize(point_size)
    font.setBold(bold)
    return font

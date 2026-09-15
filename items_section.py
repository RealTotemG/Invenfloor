"""
items_section.py
================

The "Items" half of the app: the catalog of everything in this profile, the
tags that describe it, and a few saved views over the top.

ONE ROW PER ITEM
----------------
An item can be kept in several containers at once -- towels in the kitchen and
the bathroom -- but it still gets exactly ONE row here. The row shows the
total, and you expand it to see the split.

That is the point of the catalog: it is a list of things you own, not a list
of piles. If "Towels" appeared twice you would have to rename it twice, retag
it twice, and eventually the two copies would disagree with each other.

THE FOUR VIEWS
--------------
Above the tags on the left are four saved questions:

    All items   everything
    Low stock   below the par level you set on the item
    Unfiled     you own it but haven't said where it is
    Misfiled    its own tags say it belongs somewhere it isn't

That last one is the interesting one, and it is only possible because tags go
on rooms as well as items. A tag on an ITEM says what the thing is; the same
tag on a ROOM says what belongs there. Compare the two and "this is in the
wrong place" falls out of the design rather than needing a feature of its own.
The logic lives in Profile.misfiled_items().
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QLineEdit, QScrollArea,
    QComboBox, QCheckBox,
)

import theme
from models import NAME_MAX_LENGTH, Item, Tag, clean_name, short
from widgets import (
    BulkAddDialog, ItemDialog, NameColorDialog, TagChipRow,
    TagManagerDialog, TagPickerDialog, button, confirm,
    empty_state, full_path, label, path_label, short_label, short_path,
    tag_chip, tier_suffix, wrapped,
)

TAG_PANEL_WIDTH = 270

# The widest the item list is allowed to get, whatever the window does. On a
# maximized screen a row left to fill 1900 pixels puts the name at one edge
# and the buttons at the other, with half a metre of nothing between them and
# your eyes travelling the whole way. Past about this width a list stops
# getting easier to read and starts getting harder.
LIST_MAX_WIDTH = 1100

# The saved views. Plain strings so they read clearly in the debugger.
VIEW_ALL = "all"
VIEW_LOW = "low"
VIEW_UNFILED = "unfiled"
VIEW_MISFILED = "misfiled"

SORT_NAME = "name"
SORT_ADDED = "added"
SORT_UPDATED = "updated"


class ItemsSection(QWidget):
    """Everything you own, and the tag vocabulary that describes it."""

    dataChanged = Signal()
    locateRequested = Signal(str)     # a container id to reveal on the map

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None
        self.active_view = VIEW_ALL
        self.active_tag_id = None      # None means "not filtering by tag"
        self.search_text = ""
        self.sort_mode = SORT_NAME
        # Which rows are showing their per-place breakdown. Kept by id rather
        # than by object so it survives the list being rebuilt.
        self.expanded_ids = set()
        # Which rows are ticked for a bulk action. Also by id, and for the
        # same reason: the list is thrown away and rebuilt constantly.
        self.selected_ids = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_toolbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._build_tag_panel())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_selection_bar())

        self._items_scroll = QScrollArea()
        self._items_scroll.setWidgetResizable(True)
        right.addWidget(self._items_scroll, 1)

        body.addLayout(right, 1)

        outer.addLayout(body, 1)

    # -- toolbar --------------------------------------------------------------

    def _build_toolbar(self):
        bar = QFrame()
        bar.setObjectName("topBar")
        # Minimum, not fixed -- see the note in layout_section.py.
        bar.setMinimumHeight(54)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM,
                                  theme.SPACE_MD, theme.SPACE_SM)
        layout.setSpacing(theme.SPACE_SM)

        title = QLabel("Items")
        title.setStyleSheet(
            f"font-size: {theme.FONT_SIZE_LG}px; font-weight: 600;")
        layout.addWidget(title)

        self._count_label = QLabel("")
        self._count_label.setObjectName("caption")
        layout.addWidget(self._count_label)

        layout.addSpacing(theme.SPACE_LG)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search items…   (Ctrl+F)")
        self._search.setFixedWidth(250)
        # Capped like a name box, because the Create button turns
        # whatever is in here into an item name.
        self._search.setMaxLength(NAME_MAX_LENGTH)
        # textChanged fires on every keystroke, which is what makes the list
        # filter as you type rather than when you press Enter.
        self._search.textChanged.connect(self._on_search)
        # Pressing Enter with no match is the same as clicking Create.
        self._search.returnPressed.connect(self._create_from_search)
        layout.addWidget(self._search)

        # Appears only when what you typed doesn't exist yet. Hidden the rest
        # of the time rather than disabled, so it never draws the eye when
        # there is nothing to do with it.
        self._create_button = button("", "primary", self._create_from_search,
                                     size="sm")
        self._create_button.hide()
        layout.addWidget(self._create_button)

        layout.addSpacing(theme.SPACE_MD)

        sort_label = QLabel("Sort")
        sort_label.setObjectName("hint")
        layout.addWidget(sort_label)

        self._sort_field = QComboBox()
        self._sort_field.addItem("Name", SORT_NAME)
        self._sort_field.addItem("Recently added", SORT_ADDED)
        self._sort_field.addItem("Recently changed", SORT_UPDATED)
        self._sort_field.currentIndexChanged.connect(self._on_sort_changed)
        layout.addWidget(self._sort_field)

        layout.addStretch()

        layout.addWidget(button("Edit tags", "ghost", self.edit_tags,
                                "Manage every tag in this profile"))
        layout.addWidget(button("Add many", "ghost", self.bulk_add,
                                "Add a lot of items quickly  (Ctrl+B)"))
        layout.addWidget(button("+ New item", "primary", self.new_item,
                                "Add one item  (Ctrl+N)"))

        return bar

    # -- picking several at once --------------------------------------------

    def _build_selection_bar(self):
        """The strip that appears once something is ticked.

        Hidden entirely when nothing is selected rather than sitting there
        greyed out. An empty toolbar for a thing you are not doing is just a
        row of noise above the list you ARE looking at.
        """
        self._selection_bar = QFrame()
        self._selection_bar.setObjectName("topBar")
        self._selection_bar.hide()

        layout = QHBoxLayout(self._selection_bar)
        layout.setContentsMargins(theme.SPACE_LG, theme.SPACE_SM,
                                  theme.SPACE_LG, theme.SPACE_SM)
        layout.setSpacing(theme.SPACE_SM)

        self._selection_label = QLabel("")
        self._selection_label.setStyleSheet(f"color: {theme.TEXT};")
        layout.addWidget(self._selection_label)

        layout.addStretch()

        layout.addWidget(button("Add tags", "ghost", self._tag_selected, size="sm",
                                tooltip="Put tags on everything ticked"))
        layout.addWidget(button("Remove tags", "ghost", self._untag_selected,
                                size="sm",
                                tooltip="Take tags off everything ticked"))
        layout.addWidget(button("Clear", "ghost", self._clear_selection,
                                size="sm"))

        delete = button("Delete", "ghost", self._delete_selected, size="sm")
        delete.setProperty("kind", "danger")
        layout.addWidget(delete)

        return self._selection_bar

    def _set_selected(self, item, selected):
        if selected:
            self.selected_ids.add(item.id)
        else:
            self.selected_ids.discard(item.id)
        self._refresh_selection_bar()

    def _refresh_selection_bar(self):
        count = len(self.selected_ids)
        self._selection_bar.setVisible(count > 0)
        self._selection_label.setText(
            f"{count} item" + ("" if count == 1 else "s") + " selected")

    def _clear_selection(self):
        self.selected_ids.clear()
        self._rebuild_items()

    def _selected_items(self):
        """The ticked items, in the order the catalog holds them."""
        return [i for i in self.profile.items if i.id in self.selected_ids]

    def _tag_selected(self):
        """Add tags to everything ticked.

        The dialog opens with nothing ticked on purpose, because this is "put
        these tags on" rather than "make the tags be exactly this". Showing
        the tags one of the items already has would invite you to untick one
        and expect it removed, which is what the other button is for.
        """
        chosen = self._pick_tags("Tag these items")
        if chosen is None:
            return

        for item in self._selected_items():
            for tag_id in chosen:
                if tag_id not in item.tag_ids:
                    item.tag_ids.append(tag_id)
            item.touch()

        self.dataChanged.emit()
        self.reload()

    def _untag_selected(self):
        """Take tags off everything ticked, leaving their other tags alone."""
        chosen = self._pick_tags("Remove these tags")
        if chosen is None:
            return

        for item in self._selected_items():
            kept = [t for t in item.tag_ids if t not in chosen]
            if kept != item.tag_ids:
                item.tag_ids = kept
                item.touch()

        self.dataChanged.emit()
        self.reload()

    def _pick_tags(self, subject):
        """Open the tag picker and return the ticked ids, or None if cancelled.

        A tag created in there is absorbed either way, the same as everywhere
        else that opens this dialog.
        """
        dialog = TagPickerDialog(self, self.profile, [], subject)
        accepted = dialog.exec()
        if not accepted:
            self._absorb_new_tags(dialog)
            return None

        chosen = dialog.selected_ids()
        if dialog.created_tags:
            self.dataChanged.emit()
        return chosen or None

    def _delete_selected(self):
        items = self._selected_items()
        if not items:
            return

        if not confirm(
            self, "Delete items",
            f"Delete {len(items)} item" + ("" if len(items) == 1 else "s")
            + "?\n\nThey are removed from every container they were in. "
              "The containers and rooms stay.",
            danger_text=f"Delete {len(items)}"
        ):
            return

        gone = {i.id for i in items}
        self.profile.items = [i for i in self.profile.items
                              if i.id not in gone]
        self.selected_ids.clear()
        self.dataChanged.emit()
        self.reload()

    def _on_search(self, text):
        self.search_text = text.strip().lower()
        self._refresh_create_button()
        self._rebuild_items()

    def _on_sort_changed(self):
        self.sort_mode = self._sort_field.currentData()
        self._rebuild_items()

    def _refresh_create_button(self):
        """Show "Create ..." only when what you typed isn't already an item.

        The comparison is on the exact name, case-insensitively. Searching for
        "screw" while you own a "Screwdriver" should still offer to create
        "screw", because they are different things -- a partial match is not
        the same as already having it.
        """
        typed = self._search.text().strip()

        if not typed or self.profile is None:
            self._create_button.hide()
            return

        exists = any(i.name.strip().lower() == typed.lower()
                     for i in self.profile.items)
        if exists:
            self._create_button.hide()
            return

        self._create_button.setText(f'Create "{short(typed)}"')
        self._create_button.show()

    def _create_from_search(self):
        """Make the item you just searched for.

        It arrives pre-named, and pre-tagged with whatever tag you are
        filtering by -- if you are looking at Tools and type "Hammer", a
        hammer is obviously a tool, and making you tick that box yourself
        would be the app not paying attention.
        """
        typed = self._search.text().strip()
        if not typed or self.profile is None:
            return
        if any(i.name.strip().lower() == typed.lower()
               for i in self.profile.items):
            return

        item = Item(name=clean_name(typed), color=theme.SWATCHES[-1])
        if self.active_tag_id:
            item.tag_ids = [self.active_tag_id]

        dialog = ItemDialog(self, self.profile, item=item)
        if not dialog.exec():
            return

        values = dialog.result_values()
        if not values["name"]:
            return

        for key, value in values.items():
            setattr(item, key, value)

        self.profile.items.append(item)
        self._search.clear()          # the thing you searched for now exists
        self.dataChanged.emit()
        self.reload()

    # -- public actions, also reachable by keyboard ----------------------------

    def focus_search(self):
        self._search.setFocus()
        self._search.selectAll()

    def new_item(self):
        dialog = ItemDialog(self, self.profile)
        if not dialog.exec():
            self._absorb_new_tags(dialog)
            return
        values = dialog.result_values()
        if not values["name"]:
            return

        self.profile.items.append(Item(**values))
        self.dataChanged.emit()
        self.reload()

    def bulk_add(self):
        dialog = BulkAddDialog(self, self.profile)
        if not dialog.exec():
            self._absorb_new_tags(dialog)
            return

        created = dialog.result_items()
        if not created:
            return

        self.profile.items.extend(created)
        # Jump to newest-first so you can see what you just added.
        self.sort_mode = SORT_ADDED
        self._sort_field.setCurrentIndex(1)
        self.dataChanged.emit()
        self.reload()

    # -- tag panel -------------------------------------------------------------

    def _build_tag_panel(self):
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setFixedWidth(TAG_PANEL_WIDTH)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                  theme.SPACE_MD, theme.SPACE_MD)
        layout.setSpacing(theme.SPACE_SM)

        self._views_holder = QWidget()
        self._views_holder.setObjectName("plain")
        self._views_layout = QVBoxLayout(self._views_holder)
        self._views_layout.setContentsMargins(0, 0, 0, 0)
        self._views_layout.setSpacing(theme.SPACE_XS)
        layout.addWidget(self._views_holder)

        header = QHBoxLayout()
        header.addWidget(label("TAGS", "hint"))
        header.addStretch()
        header.addWidget(button("+ New", "ghost", self._add_tag, size="sm"))
        layout.addLayout(header)

        self._tag_scroll = QScrollArea()
        self._tag_scroll.setWidgetResizable(True)
        layout.addWidget(self._tag_scroll, 1)

        return panel

    def _row_style(self, selected, color):
        background = theme.ACCENT_SOFT if selected else theme.BG_CARD
        border = color if selected else theme.BORDER
        return f"""
            QFrame {{
                background-color: {background};
                border: 1px solid {border};
                border-radius: {theme.RADIUS_MD}px;
            }}
        """

    def _rebuild_views(self):
        """The four saved views above the tag list."""
        while self._views_layout.count():
            old = self._views_layout.takeAt(0)
            if old.widget():
                old.widget().deleteLater()

        counts = [
            (VIEW_ALL, "All items", len(self.profile.items), theme.ACCENT),
            (VIEW_LOW, "Low stock", len(self.profile.low_items()),
             theme.WARNING),
            (VIEW_UNFILED, "Unfiled", len(self.profile.unfiled_items()),
             theme.WARNING),
            (VIEW_MISFILED, "Misfiled",
             len(self.profile.misfiled_items()), theme.DANGER),
        ]

        for view, name, count, color in counts:
            self._views_layout.addWidget(
                self._view_row(view, name, count, color))

    def _view_row(self, view, name, count, color):
        selected = (self.active_view == view and self.active_tag_id is None)

        row = QFrame()
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(self._row_style(selected, color))

        layout = QHBoxLayout(row)
        layout.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM,
                                  theme.SPACE_SM, theme.SPACE_SM)

        text = QLabel(name)
        # A view with nothing in it is dimmed rather than hidden, so the set of
        # questions you can ask stays the same from one day to the next.
        interesting = count > 0 and view != VIEW_ALL
        text.setStyleSheet(
            f"color: {color if interesting else theme.TEXT}; border: none;"
            if interesting else f"color: {theme.TEXT}; border: none;")
        layout.addWidget(text)
        layout.addStretch()

        badge = QLabel(str(count))
        badge.setStyleSheet(
            f"color: {color if interesting else theme.TEXT_MUTED}; "
            f"border: none;")
        layout.addWidget(badge)

        def on_click(event, v=view):
            self.active_view = v
            self.active_tag_id = None
            self.reload()

        row.mouseReleaseEvent = on_click
        return row

    def _rebuild_tags(self):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_XS)

        if not self.profile.tags:
            layout.addWidget(empty_state(
                "No tags yet",
                "Tags let you group items across rooms: 'Tools', "
                "'Christmas', 'Fragile'."))
        else:
            for tag in self.profile.tags:
                layout.addWidget(self._tag_row(tag))

        layout.addStretch()
        self._tag_scroll.setWidget(holder)

    def _tag_row(self, tag):
        selected = (self.active_tag_id == tag.id)
        row = QFrame()
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(self._row_style(selected, tag.color))

        layout = QHBoxLayout(row)
        layout.setContentsMargins(theme.SPACE_SM, theme.SPACE_XS,
                                  theme.SPACE_SM, theme.SPACE_XS)
        layout.setSpacing(theme.SPACE_XS)

        layout.addWidget(tag_chip(tag, small=True))
        layout.addStretch()

        item_count = len(self.profile.items_with_tag(tag.id))
        room_count = len(list(self.profile.rooms_with_tag(tag.id)))
        counts = QLabel(f"{item_count}i · {room_count}r")
        counts.setToolTip(f"{item_count} items · {room_count} rooms")
        counts.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px; "
            f"border: none;")
        layout.addWidget(counts)

        # Plain words rather than a pencil glyph: the symbol fonts available
        # vary by machine, and a character with no glyph renders as a blank
        # box. Not worth the risk for two buttons.
        layout.addWidget(button("Edit", "ghost", lambda: self._edit_tag(tag),
                                "Rename or recolor", size="sm"))
        layout.addWidget(button("✕", "ghost", lambda: self._delete_tag(tag),
                                "Delete tag", size="icon"))

        def on_click(event, t=tag):
            self.active_tag_id = t.id
            self.active_view = VIEW_ALL
            self.reload()

        row.mouseReleaseEvent = on_click
        return row

    # -- item list ---------------------------------------------------------------

    def _visible_items(self):
        """Apply the view, the tag filter and the search box, then sort."""
        if self.active_view == VIEW_LOW:
            items = self.profile.low_items()
        elif self.active_view == VIEW_UNFILED:
            items = self.profile.unfiled_items()
        elif self.active_view == VIEW_MISFILED:
            # One item can be reported for two different tags, so strip the
            # duplicates rather than showing the same row twice.
            seen = []
            for item, _, _ in self.profile.misfiled_items():
                if item not in seen:
                    seen.append(item)
            items = seen
        else:
            items = list(self.profile.items)

        if self.active_tag_id is not None:
            items = [i for i in items if self.active_tag_id in i.tag_ids]

        if self.search_text:
            items = [i for i in items
                     if self.search_text in i.name.lower()
                     or self.search_text in i.notes.lower()]

        if self.sort_mode == SORT_ADDED:
            return sorted(items, key=lambda i: i.created_at, reverse=True)
        if self.sort_mode == SORT_UPDATED:
            return sorted(items, key=lambda i: i.updated_at, reverse=True)
        return sorted(items, key=lambda i: i.name.lower())

    def _misfiled_reasons(self):
        """item id -> "Tools items usually live in Garage"."""
        reasons = {}
        for item, tag, expected in self.profile.misfiled_items():
            if tag is None:
                continue
            where = ", ".join(room.name for room in expected)
            reasons[item.id] = f"{tag.name} usually lives in {where}"
        return reasons

    def _rebuild_items(self):
        holder = QWidget()
        holder.setObjectName("plain")

        # The rows go in a column of their own, capped and centered, rather
        # than straight into the holder. A stretch on each side rather than an
        # alignment flag: an alignment flag makes the layout hand the column
        # exactly its sizeHint, which is always short for anything containing
        # wrapped text -- and the empty states below all wrap.
        frame = QHBoxLayout(holder)
        frame.setContentsMargins(theme.SPACE_LG, theme.SPACE_LG,
                                 theme.SPACE_LG, theme.SPACE_LG)
        frame.setSpacing(0)
        frame.addStretch(1)

        column = QWidget()
        column.setObjectName("plain")
        column.setMaximumWidth(LIST_MAX_WIDTH)
        self._items_column = column
        # A large stretch against two small ones, so the column always takes
        # everything it is allowed to and the spacers only get what is left
        # over. Equal stretches would split the room three ways and leave the
        # list narrower than its cap on a window wide enough to reach it.
        frame.addWidget(column, 100)
        frame.addStretch(1)

        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_SM)

        unfiled = len(self.profile.unfiled_items())
        low = len(self.profile.low_items())
        summary = f"{len(self.profile.items)} total"
        if unfiled:
            summary += f" · {unfiled} unfiled"
        if low:
            summary += f" · {low} low"
        self._count_label.setText(summary)

        if self.active_tag_id is not None:
            layout.addWidget(self._tag_summary())
        elif self.active_view == VIEW_MISFILED:
            layout.addWidget(self._misfiled_explainer())

        reasons = (self._misfiled_reasons()
                   if self.active_view == VIEW_MISFILED else {})

        items = self._visible_items()

        # Drop ticks for anything that no longer exists, so a deleted item
        # cannot linger in the selection and make the count lie.
        alive = {i.id for i in self.profile.items}
        self.selected_ids &= alive
        self._refresh_selection_bar()

        if not items:
            layout.addWidget(self._empty_for_view())
        else:
            for item in items:
                layout.addWidget(self._item_row(item, reasons.get(item.id)))

        layout.addStretch()
        self._items_scroll.setWidget(holder)

    def _empty_for_view(self):
        """A message that fits whichever question was asked."""
        if self.search_text:
            return empty_state(
                f'Nothing matches "{self._search.text().strip()}"',
                "Use the Create button up top to add it.")
        if self.active_view == VIEW_LOW:
            return empty_state("Nothing is running low",
                               "Set a level on an item to be told when it is.")
        if self.active_view == VIEW_UNFILED:
            return empty_state("Everything has a home",
                               "Nothing is waiting to be put away.")
        if self.active_view == VIEW_MISFILED:
            return empty_state("Nothing looks out of place",
                               "Every tagged item is in a room that expects "
                               "that tag.")
        return empty_state(
            "No items to show",
            "Add one with the button up in the corner, or from a container "
            "in the Layout view.")

    def _misfiled_explainer(self):
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                  theme.SPACE_MD, theme.SPACE_MD)
        layout.setSpacing(theme.SPACE_XS)

        heading = QLabel("Probably in the wrong place")
        heading.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        layout.addWidget(heading)

        note = QLabel(
            "These items carry a tag that some room claims, but they are not "
            "in any of those rooms. Either move the item, or tag the room "
            "it's actually in.")
        wrapped(note)
        note.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(note)

        return panel

    def _tag_summary(self):
        tag = self.profile.tag_by_id(self.active_tag_id)
        rooms = list(self.profile.rooms_with_tag(self.active_tag_id))

        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                  theme.SPACE_MD, theme.SPACE_MD)
        layout.setSpacing(theme.SPACE_XS)

        heading = QHBoxLayout()
        heading.setSpacing(theme.SPACE_SM)
        heading.addWidget(QLabel("Rooms tagged"))
        heading.addWidget(tag_chip(tag, small=True))
        heading.addStretch()
        layout.addLayout(heading)

        if not rooms:
            note = QLabel(
                "No room carries this tag yet. Tag a room in the Layout view "
                "to say that this is where these things belong.")
        else:
            note = QLabel(", ".join(f"{short(floor.name)} / {short(room.name)}"
                                    for floor, room in rooms))
        wrapped(note)
        note.setStyleSheet(
            f"color: {theme.TEXT_MUTED if rooms else theme.TEXT_FAINT}; "
            f"font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(note)

        return panel

    def _item_row(self, item, misfiled_reason=None):
        """One item: name, total, where it is, its tags, and the expander."""
        row = QFrame()
        row.setObjectName("card")

        outer = QHBoxLayout(row)
        outer.setContentsMargins(theme.SPACE_MD, theme.SPACE_SM,
                                 theme.SPACE_MD, theme.SPACE_SM)
        outer.setSpacing(theme.SPACE_MD)

        tick = QCheckBox()
        tick.setChecked(item.id in self.selected_ids)
        tick.setToolTip("Pick several, then tag or delete them together")
        tick.toggled.connect(
            lambda on, i=item: self._set_selected(i, on))
        outer.addWidget(tick)

        stripe = QFrame()
        stripe.setFixedWidth(3)
        stripe.setStyleSheet(
            f"background-color: {item.color}; border-radius: 2px;")
        outer.addWidget(stripe)

        middle = QVBoxLayout()
        middle.setSpacing(3)

        # -- title line
        title_row = QHBoxLayout()
        title_row.setSpacing(theme.SPACE_SM)
        name = short_label(item.name)
        name.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        title_row.addWidget(name)

        total = item.total_quantity()
        if total != 1:
            quantity = QLabel(f"×{total}")
            quantity.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            quantity.setToolTip("Total across every place")
            title_row.addWidget(quantity)

        if item.is_low():
            low = QLabel(f"LOW · want {item.min_quantity}")
            low.setStyleSheet(
                f"background-color: {theme.with_alpha(theme.WARNING, 0.18)}; "
                f"color: {theme.WARNING}; border-radius: 9px; "
                f"padding: 2px 8px; font-size: {theme.FONT_SIZE_SM}px;")
            title_row.addWidget(low)

        title_row.addStretch()
        middle.addLayout(title_row)

        if misfiled_reason:
            reason = QLabel(misfiled_reason)
            reason.setStyleSheet(
                f"color: {theme.DANGER}; font-size: {theme.FONT_SIZE_SM}px;")
            middle.addWidget(reason)

        # -- location line
        places = self.profile.locations_of(item)
        middle.addWidget(self._location_line(item, places))

        # -- the per-place breakdown, when expanded
        if len(places) > 1 and item.id in self.expanded_ids:
            for floor, room, container, quantity, tier in places:
                middle.addWidget(self._place_line(
                    floor, room, container, quantity, tier))

        tags = self.profile.tags_for(item.tag_ids)
        if tags:
            chips = TagChipRow()
            chips.set_tags(tags)
            middle.addWidget(chips)

        outer.addLayout(middle, 1)

        if places:
            outer.addWidget(button(
                "Find", "ghost",
                lambda: self.locateRequested.emit(places[0][2].id),
                "Show it on the floor plan", size="sm"))

        outer.addWidget(button("Edit", "ghost",
                               lambda: self._edit_item(item), size="sm"))
        outer.addWidget(button("Delete", "ghost",
                               lambda: self._delete_item(item), size="sm"))

        return row

    def _place_line(self, floor, room, container, quantity, tier=0):
        """One line of an expanded breakdown, with its own Find button."""
        line = QWidget()
        line.setObjectName("plain")
        layout = QHBoxLayout(line)
        layout.setContentsMargins(theme.SPACE_MD, 0, 0, 0)
        layout.setSpacing(theme.SPACE_SM)

        text = QLabel(f"{short_path(floor, room, container)}"
                      f"{tier_suffix(tier)}   ×{quantity}")
        text.setToolTip(full_path(floor, room, container) + tier_suffix(tier))
        text.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;")
        layout.addWidget(text)

        # Each place gets its own button, because "find it" means something
        # different for each one when a thing is kept in two rooms.
        layout.addWidget(button(
            "Find", "ghost",
            lambda: self.locateRequested.emit(container.id),
            f"Show {short(container.name)} on the floor plan", size="sm"))
        layout.addStretch()

        return line

    def _location_line(self, item, places):
        """The "where is it" line, which doubles as the expander when there
        is more than one place."""
        if not places:
            unfiled = QLabel("Unfiled")
            unfiled.setStyleSheet(
                f"color: {theme.WARNING}; font-size: {theme.FONT_SIZE_SM}px;")
            return unfiled

        if len(places) == 1:
            floor, room, container, _, tier = places[0]
            single = path_label(floor, room, container)
            if tier:
                single.setText(single.text() + tier_suffix(tier))
                single.setToolTip(full_path(floor, room, container)
                                  + tier_suffix(tier))
            single.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: {theme.FONT_SIZE_SM}px;")
            return single

        expanded = item.id in self.expanded_ids
        arrow = "▾" if expanded else "▸"
        multiple = QLabel(f"{arrow} in {len(places)} places")
        multiple.setCursor(Qt.PointingHandCursor)
        multiple.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: {theme.FONT_SIZE_SM}px;")
        multiple.setToolTip("Click to show where")

        def toggle(event, i=item):
            if i.id in self.expanded_ids:
                self.expanded_ids.discard(i.id)
            else:
                self.expanded_ids.add(i.id)
            self._rebuild_items()

        multiple.mouseReleaseEvent = toggle
        return multiple

    # -- loading ----------------------------------------------------------------

    def set_profile(self, profile):
        self.profile = profile
        self.active_view = VIEW_ALL
        self.active_tag_id = None
        self.search_text = ""
        self.expanded_ids = set()
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._create_button.hide()
        self.reload()

    def reload(self):
        if self.profile is None:
            return
        self._rebuild_views()
        self._rebuild_tags()
        self._refresh_create_button()
        self._rebuild_items()

    # -- actions ------------------------------------------------------------------

    def _edit_item(self, item):
        dialog = ItemDialog(self, self.profile, item=item)
        if not dialog.exec():
            # Cancelled, but a tag made along the way is still a real tag.
            self._absorb_new_tags(dialog)
            return
        values = dialog.result_values()
        if not values["name"]:
            return

        for key, value in values.items():
            setattr(item, key, value)
        item.touch()
        self.dataChanged.emit()
        self.reload()

    def _delete_item(self, item):
        places = len(self.profile.locations_of(item))
        message = f"Delete '{item.name}'?"
        if places > 1:
            message += (f"\n\nThis removes it from all {places} places it is "
                        f"kept in.")

        if not confirm(self, "Delete item", message):
            return

        self.profile.items.remove(item)
        self.expanded_ids.discard(item.id)
        self.dataChanged.emit()
        self.reload()

    def edit_tags(self):
        """Open the whole tag vocabulary in one window.

        The left panel can already do all three things one at a time, so this
        hands those same methods to the dialog rather than writing them again.
        One implementation, two ways in.
        """
        dialog = TagManagerDialog(self, self.profile,
                                  on_add=self._add_tag,
                                  on_edit=self._edit_tag,
                                  on_delete=self._delete_tag)
        dialog.exec()
        self.reload()

    def _absorb_new_tags(self, dialog):
        """Save and redraw if a dialog invented a tag before being cancelled.

        Creating a tag from inside Assign tags adds it to the profile there
        and then. Pressing Cancel on the dialog you were in does not undo
        that, so without this the tag sits in memory: on screen until the next
        rebuild, and never written to the file at all.
        """
        if getattr(dialog, "created_tags", False):
            self.dataChanged.emit()
            self.reload()

    def _add_tag(self):
        dialog = NameColorDialog(self, "New tag", "",
                                 theme.SWATCHES[len(self.profile.tags)
                                                % len(theme.SWATCHES)])
        if not dialog.exec():
            return
        name, color = dialog.result_values()
        if not name:
            return

        self.profile.tags.append(Tag(name=name, color=color))
        self.dataChanged.emit()
        self.reload()

    def _edit_tag(self, tag):
        dialog = NameColorDialog(self, "Edit tag", tag.name, tag.color)
        if not dialog.exec():
            return
        name, color = dialog.result_values()
        if not name:
            return

        tag.name = name
        tag.color = color
        self.dataChanged.emit()
        self.reload()

    def _delete_tag(self, tag):
        item_count = len(self.profile.items_with_tag(tag.id))
        room_count = len(list(self.profile.rooms_with_tag(tag.id)))

        if not confirm(
            self, "Delete tag",
            f"Delete the tag '{tag.name}'?\n\nIt will be removed from "
            f"{item_count} item{'' if item_count == 1 else 's'} and "
            f"{room_count} room{'' if room_count == 1 else 's'}. "
            f"Nothing else is deleted."
        ):
            return

        self.profile.delete_tag(tag.id)
        if self.active_tag_id == tag.id:
            self.active_tag_id = None
        self.dataChanged.emit()
        self.reload()

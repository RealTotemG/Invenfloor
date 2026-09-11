# Invenfloor

An inventory app where you draw your actual floor plan, put containers in the
rooms, and put your stuff in the containers. Then you can find it again.

I manage inventory for a living, and every home inventory app I tried was just
a list. A list doesn't help when the question is "which drawer did I put that
in?" So this one is built around a map.

Python and PySide6 (Qt).

## Getting it running

```
pip install -r requirements.txt
python main.py
```

You only need the pip line once. If Windows doesn't recognise `python`, try
`py main.py` instead.

## How the data is organised

Everything hangs off one structure. Once this makes sense the rest of the app
does too, because every screen is just a window onto one level of it.

```
Profile                "Home", "Work Locker". A completely separate inventory.
 |- floors[]           ordered bottom to top, so index 0 is the lowest
 |    |- rooms[]       the polygons you draw
 |         |- containers[]   drawers, cabinets, shelves
 |- tags[]             the tag vocabulary for this profile
 |- items[]            a flat list. Each item says where its copies are.
```

Three things about that are worth explaining, because they're the decisions I'd
want to defend if someone asked.

### Items are a flat list, not nested in containers

If items lived inside their containers, then listing everything in a profile
would mean four nested loops every single time you searched. Keeping them flat
makes it one loop. Databases make the same trade for the same reason.

### One item can be in more than one place

Towels live in the bathroom and the kitchen, in different numbers. So an item
doesn't have a location and a quantity. It has a list of placements:

```python
Item("Towels", placements=[
    Placement(container_id="kitchen drawer", quantity=6),
    Placement(container_id="bathroom shelf", quantity=8),
])
```

There's still only one "Towels" in the catalogue. One name, one color, one set
of tags, with its 14 towels split across two places. If I'd let you create it
twice instead, you'd have to rename it twice and retag it twice, and sooner or
later the two copies would disagree with each other.

An item with no placements is *Unfiled*. You own it, you just haven't said
where it is yet. It keeps an `unfiled_quantity` so you can write down "24 tent
pegs" while you're standing over the box, before you've drawn a single room.
As soon as it has places, the per-place numbers take over.

### Items go in containers, and only containers

There's no way to file something straight into a room or a floor. A room is a
place. A container is a thing you open.

> Save files from the older one-location version still load. The conversion
> happens in `Item.from_dict` and nowhere else, so the rest of the app never
> has to know two formats existed.

## The files

| File | What's in it |
|---|---|
| `theme.py` | Every color, size and font in the app. Start here to restyle. |
| `models.py` | What a profile, floor, room, container, item and tag are |
| `storage.py` | Loading and saving. One JSON file per profile. |
| `widgets.py` | Shared UI pieces: color picker, tag chips, dialogs |
| `profile_screen.py` | The launcher, with the grid of profile cards |
| `workspace.py` | The sidebar shell, the autosave timer, keyboard shortcuts |
| `layout_section.py` | Floors, toolbar, and the wiring between canvas and inspector |
| `floor_view.py` | The canvas: grid, zoom, pan, drawing tools |
| `floor_items.py` | How a room and a container draw and drag themselves |
| `inspector.py` | The edit panel down the right |
| `items_section.py` | The item catalogue, the saved views, the tag manager |
| `export.py` | Writing CSV and PDF. Doesn't touch any screens. |
| `main.py` | Starts the app and swaps between launcher and workspace |

Roughly: `models` and `storage` are the data, `theme` and `widgets` are the
look, everything else is a screen.

## Using it

**Drawing rooms.** Two ways. The Shape menu gives you rectangle, square,
circle, triangle and L-shape: pick one and drag out the size, or just click
once for a default. Or pick Draw room and click each corner yourself, closing
the shape by clicking the first corner again or pressing Enter.

Corners snap to the grid, which is what stops rooms sitting a pixel or two out
of line with each other.

Presets are only starting shapes. Once a room exists a circle is an ordinary
polygon like any other, and you can drag its corners about.

**Resizing.** Select a room and you get square handles around the outside.
Dragging one stretches the whole room but keeps its shape, so an oval stays an
oval and an L keeps its notch. Containers get pulled back inside if you shrink
the room past them. There are W and H boxes in the inspector if you'd rather
type an exact size.

Switch to "Edit shape" and you get round handles on every corner instead, for
changing the outline itself. I kept those separate deliberately. A circle is
stored as a twenty-sided polygon, and twenty round handles scattered over it is
unusable, but four corner handles to stretch it into an oval works fine.

**Containers.** Pick Add container and drag a box inside a room. You can't drag
one on empty canvas, on purpose.

**Working inside a room.** Double-click it. Everything else fades back, the
room itself locks so you can't shove it by mistake, and its containers become
draggable. Escape or another double-click steps back out.

**Floors.** The stack is down the left, highest at the top, with arrows to step
through. Press the up arrow on the top floor and it offers to create a new
floor above rather than just doing nothing. Same going down, which is how you
add a basement.

**Finding things.** Press Find on any item and the app jumps to Layout, changes
to the right floor, selects the container and flashes it for a second. An item
kept in two places gets a Find on each line of its breakdown, because "find it"
means something different for each one.

**Adding a lot at once.** Add many (Ctrl+B) asks which container once, then
gets out of your way. Type a name, press Enter, type the next. Stick `x3` on
the end for a quantity, like `Zip ties x50`. Nothing saves until you press Add,
so a typo is just a line to delete.

This one matters more than it looks. The thing that kills an inventory app is
the first two hundred items. If every one costs you a dialog and six fields,
you give up around twenty.

**Create from search.** Search for something you don't own yet and a Create
button appears next to the box. The new item comes pre-named, and pre-tagged
with whatever tag you're filtering by, so searching Tools for "Hammer" gives
you a hammer that's already a tool.

**The four views**, above the tags on the left:

- All items
- Low stock, meaning below the level you set on the item
- Unfiled, meaning you own it but haven't placed it
- Misfiled, meaning its own tags say it belongs somewhere it isn't

The last one is the one I'm most pleased with, and it only works because tags
go on rooms as well as items. A tag on an item says what the thing is. The same
tag on a room says what belongs there. Compare the two and "this is in the
wrong drawer" just falls out, without needing to be a feature.

It tries not to cry wolf, too. Unfiled items aren't counted as misfiled, since
they're not anywhere yet. And a tag that no room claims creates no expectation
to break, so nothing gets reported against it.

**Par levels.** Set "tell me when the total drops below" on an item and it gets
a LOW badge and turns up in the Low stock view. Zero means never warn me.

**Exporting.** Export at the bottom of the sidebar writes a CSV of everything
you own, or a PDF of your floor plans with one page per floor. The plans are
drawn by the same code that draws them on screen, so the printout can't drift
out of step with the app.

**Keyboard:**

| | |
|---|---|
| `Ctrl+1` / `Ctrl+2` | Layout / Items |
| `Ctrl+F` | search |
| `Ctrl+N` | new item |
| `Ctrl+B` | add many |
| `Esc` | cancel a tool, step out of a room |
| `Delete` | remove whatever's selected on the canvas |

All the shortcuts are defined in one place in `workspace.py`, and each one
switches to the screen it needs on the way. Pressing Ctrl+F from the Layout
view jumps to Items first, because that's obviously what you meant.

**Saving.** There's no save button. Any change schedules a save half a second
later, and more changes restart the clock, so dragging a room across the floor
writes one file at the end instead of a hundred on the way. It also saves when
you leave a profile or close the window.

Your data sits in a `data` folder next to the code, one JSON file per profile.
You can open one in a text editor and read it, which was genuinely useful while
I was building this.

## Things I worked out along the way

Mostly Qt, and mostly the kind of thing that isn't obvious until it bites you.

**Signals.** Widgets announce that something happened, and whoever cares
connects a function to the announcement:

```python
picker.colorChanged.connect(my_function)
```

The picker has no idea who's listening. That's why the canvas never touches the
inspector and the inspector never touches the canvas. They both just announce,
and `layout_section.py` wires them together. It's the thing that stops a big
app turning into a knot.

**Scene and view.** A `QGraphicsScene` holds what exists, and a
`QGraphicsView` is a window looking at it. Panning and zooming happen in the
view, so nothing in `floor_items.py` deals with scroll offsets or zoom levels
at all. That's the main reason I used Qt instead of drawing everything by hand.

**Parent and child coordinates.** Containers are children of their room, so
their positions are measured from the room's origin. Drag a room across the
floor and its containers come with it. There's no code anywhere that moves
them, which means it can't get out of step.

**QSS**, which is Qt's version of CSS. One stylesheet in `theme.py` applies to
the whole app, so every button and text box gets styled without being touched
individually. Buttons pick their variant through a Qt property:

```python
button.setProperty("kind", "danger")   # theme.py handles the rest
```

**One mode variable.** The canvas is always in exactly one mode, kept in a
single variable, and every mouse event checks it first. I nearly used separate
booleans like `is_drawing` and `is_placing`, and I'm glad I didn't. With one
variable there's only ever one answer to "what does a click mean right now?"

**Never set a fixed height on anything with words in it.** This one actually
bit me. A height a pixel short of what the font needs shaves the tops and
bottoms off the letters, and it looks like a font problem rather than a layout
one, so you go looking in completely the wrong place. Use `setMinimumHeight`
instead.

## Changing things

Colors and sizes are all in `theme.py`, and no color code appears anywhere
else in the project. If you ever find one somewhere else, it belongs in
`theme.py`. Change `SWATCHES` to change the palette you get when color-coding
things, and `GRID_SIZE` to change both the visible grid and what things snap
to.

Room presets live in `ROOM_PRESETS` in `models.py`. Each one is a name and a
function that takes a width and a height. Add an entry and it shows up in the
Shape menu on its own, no other files involved.

Adding a field to something means three small edits in `models.py`: the
dataclass, `to_dict` and `from_dict`. Then show it wherever it belongs in
`inspector.py`. Old save files keep working because `from_dict` uses `.get()`
with a default for every field.

## Making it an .exe

`storage.py` already handles the bit that's easy to get wrong. When the app is
packaged it saves to AppData instead of next to the code, because a one-file
PyInstaller build unpacks itself into a temp folder that Windows deletes on
exit, which would take your whole inventory with it.

```
pip install pyinstaller
pyinstaller --onedir --windowed --name "Invenfloor" main.py
```

`--windowed` stops a console window opening behind the app. `--onedir` gives
you a folder rather than a single file, which starts faster and gets flagged by
antivirus far less often than `--onefile`.

## Ideas for later

- **Photos on items.** Add a `photo_path` to `Item`. The dialog and the
  container inspector are the only places that need to show it.
- **Count sessions.** Pick a room, walk it, confirm or correct each container's
  quantities, get a summary of what changed at the end.
- **Undo.** Needs a proper design, either a stack of operations or snapshots of
  the profile. Worth doing deliberately rather than bolting on.
- **Container shapes.** Containers are rectangles right now. They could use the
  same polygon code rooms use.

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

You only need the pip line once. If Windows doesn't recognize `python`, try
`py main.py` instead.

## How the data is organized

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

There's still only one "Towels" in the catalog. One name, one color, one set
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
| `items_section.py` | The item catalog, the saved views, the tag manager |
| `export.py` | Writing CSV and PDF. Doesn't touch any screens. |
| `main.py` | Starts the app and swaps between launcher and workspace |

Roughly: `models` and `storage` are the data, `theme` and `widgets` are the
look, everything else is a screen.

## Using it

**Drawing rooms.** Two ways. The Shape menu gives you rectangle, square,
circle, triangle and L-shape: pick one and drag out the size, or just click
once for a default. Or pick Draw room and click each corner yourself, closing
the shape by clicking the first corner again or pressing Enter.

Picking any drawing tool drops whatever was selected. Reaching for one means
you're done with the room you were on, and leaving it selected left the
inspector showing it, handles and all, while you drew a different one.

Corners snap to the grid, which is what stops rooms sitting a pixel or two out
of line with each other.

Presets are only starting shapes. Once a room exists a circle is an ordinary
polygon like any other, and you can drag its corners about.

**Resizing.** Select a room and you get square handles around the outside.
Dragging one stretches the whole room but keeps its shape, so an oval stays an
oval and an L keeps its notch. Containers get pulled back inside if you shrink
the room past them. There are W and H boxes in the inspector if you'd rather
type an exact size, and they count along with the handle while you drag, so
you can watch the numbers rather than guessing and checking.

That live update goes through its own signal rather than the one that triggers
an autosave. It fires on every mouse move, and dragging a room across the floor
should write the file once at the end, not eighty times on the way.

**Three modes.** A selected room does something different depending on which
mode you're in, and the three buttons in the inspector say which:

| | |
|---|---|
| `Move` | drag the room itself to reposition it. No handles. |
| `Resize` | square handles stretch it, keeping its shape. The body stays put. |
| `Edit shape` | round handles on every corner. The body stays put. |

Move used to be folded into Resize, so one mode quietly did two jobs and
nothing on screen told you that. Splitting them means a drag always means one
thing, and you can't shove a room across the floor while reaching for a handle.

Edit shape also lets you change how many corners there are. Double-click a wall
to add one, right-click a corner to delete it. That's how you turn a plain
rectangle into an L without redrawing it.

The new corner lands on the wall you clicked rather than exactly where your
mouse was, so the shape doesn't suddenly dent before you've asked it to. You
add the corner, then drag it where you want.

The first version had two modes that only swapped which handles showed, and on
a rectangle that's almost invisible, because all four corner handles sit on
exactly the same spots as the four resize handles. It looked broken even though
it worked. Holding the body still, adding corner editing, and eventually giving
Move its own name is what turned them into modes you can tell apart.

**Locking a room.** Once a room is where you want it, lock it from the
inspector or the right-click menu. A locked room can't be dragged, resized or
reshaped, shows no handles at all, and is drawn with a dashed outline so you
can see which rooms are settled. Everything else still works: rename it,
recolor it, tag it, and fill it with containers.

That split is deliberate. The lock is about the floor plan being finished, not
about the room being read-only, and you carry on filling a room long after you
stop moving it.

**Containers.** Pick Add container and drag a box inside a room. You can't drag
one on empty canvas, on purpose.

Double-click into a room to work inside it and containers wake up. They follow
the same Move and Resize switch rooms do: drag the body in Move, drag the edge
handles in Resize. There are W and H boxes in the inspector too, and they track
a drag the same way a room's do. A container is clamped to its room, so you
can't stretch a drawer out through a wall.

Edit shape leaves containers alone. A container is a rectangle and has no
outline to edit, so that mode is about the room it sits in.

**Tiers.** A container can be divided into tiers, for a shelf with levels. Add
tier in the container panel, as many as you need, and items can then say which
tier they're on: tier 1 shoes, tier 2 chargers, all still in the one shelf in
the one room. The Items screen reads `Hallway / Shoe shelf, Tier 2`.

**Moving things between tiers.** Every item row in a tiered container has a
Move button. It asks how many and which tier, so six pairs of shoes can go four
on tier 1 and two on tier 3 in two moves. Moving onto a tier that already has
some adds to it rather than replacing it, and moving to "loose in the
container" takes something back off its tier.

The quantity is the reason this isn't drag and drop. Dragging a row somewhere
says *move this*, and it has no way to say *move two of these*, which is the
thing you actually want on a shelf. It's also a 300px panel that scrolls, so
dragging to a heading that's scrolled off screen would be a fight.

Four decisions worth defending:

Tiers are a count, not a list of named things. A shelf's tiers don't have
names, they have positions, and "Tier 2" already says everything there is to
say. No naming, no color coding, nothing to maintain.

Items can still sit loose in a tiered container. Adding tiers moves nothing,
and anything not on a tier shows as just the container name. You file things
into tiers when you feel like it rather than being made to.

Removing a tier doesn't throw anything away. Items on the tier that goes come
back to the container itself, because you still own them and they're still in
that cupboard. You just stopped dividing it up.

The same item can be on two tiers of one shelf. Shoes on tier 1 and shoes on
tier 3 are two honest facts, and a placement is keyed by container AND tier, so
both are recordable.

**Right-click anywhere on the canvas** and you get a menu for whatever is under
the cursor. On empty space it offers Add room, with Draw room and Preset shape
underneath it. On a room you get Add container here, the work-inside toggle,
the three modes, lock, rename and delete. On a container, add an item or delete it.
On a corner, remove that corner.

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

**Adding a lot at once.** Add many (Ctrl+B) asks where they go once, then gets
out of your way. Type a name, press Enter, type the next. Stick `x3` on the end
for a quantity, like `Zip ties x50`. Nothing saves until you press Add, so a
typo is just a line to delete.

The top of that dropdown is "Nowhere yet", which adds everything straight to
the item list with no place of its own. Cataloging and placing are two
different jobs. You write things down while they're in your hands and work out
which drawer they live in later, so the batch lands under Unfiled and waits for
you. Without that option the only way to list something you hadn't placed yet
was to put it somewhere wrong first.

This one matters more than it looks. The thing that kills an inventory app is
the first two hundred items. If every one costs you a dialog and six fields,
you give up around twenty.

**Editing tags.** The panel down the left of the Items screen handles one tag
at a time, which is right when you're adding one. Tidying up a whole vocabulary
is a different job, so Edit tags in the toolbar opens all of them at once with
new, rename, recolor and delete in one window, and a count of what each tag is
actually on.

That dialog doesn't implement any of those three. They already exist on the
Items screen and get handed in as callbacks, so there's one implementation
rather than two that can drift apart.

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

**Name lengths.** Two different limits, because they answer two different
questions. You can type up to 40 characters, which stops a name running on
forever. On screen a name shows at most 20 characters and then an ellipsis,
because a room label is not 40 characters wide. The full name is still in the
box you edit it in, on hover, and in the exports.

Characters are not all the same width, though, so 20 of them can still be too
many for a narrow drawer or the sidebar. Those places fit the text to the
actual space on top of the character limit, which is why there's an
`ElidingLabel` in `widgets.py` and a `QFontMetricsF` in the canvas painting.
The character rule is predictable, the pixel fit is correct, and you want both.

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

**A panel with no horizontal scrollbar can silently slice its own contents.**
A `QScrollArea` hands its widget the LARGER of the viewport width and the
widget's own minimum. So one child asking for a few pixels more than the column
has does not produce a scrollbar you can drag, it produces content cut off at
the edge with nothing to tell you. Turning the scrollbar off fixes the ugly
version of this and hides the real one.

It showed up on Windows and not in testing, because the interface font there is
wider, and every minimum width in a layout is measured in whatever font is
actually installed. Two spin boxes side by side were the widest thing in the
inspector and they would not shrink, because a spin box asks for room to show
its largest value plus its arrows.

Three things fix it properly: give anything that can be squeezed an explicit
minimum so it will squeeze, let a crowded row of buttons wrap instead of
overflowing, and cap the body's width to the viewport so the panel structurally
cannot draw outside itself. The test for it widens the font on purpose, because
that is the only way to catch it on a machine where it fits.

**Wrapping text needs two things, not one.** `setWordWrap(True)` only tells the
label it's allowed to wrap. A layout won't ask "how tall are you at this width?"
unless the widget's size *policy* says it has an answer, and QLabel doesn't set
that flag for you. So the layout reserves one line, the text wraps onto two, and
the second line gets painted outside the space reserved for it. On screen that
looks like text cut in half or overlapping whatever's underneath.

There's a `wrapped()` helper in `widgets.py` that does both halves. Use it
instead of `setWordWrap`. I got this wrong in nine places before I noticed, and
in every one of them the symptom pointed somewhere other than the cause.

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

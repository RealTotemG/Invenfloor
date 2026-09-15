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
| `profile_screen.py` | The launcher: the profile list and its floor plan preview |
| `workspace.py` | The sidebar shell, the autosave timer, keyboard shortcuts |
| `layout_section.py` | Floors, toolbar, and the wiring between canvas and inspector |
| `floor_view.py` | The canvas: grid, zoom, pan, drawing tools |
| `floor_items.py` | How a room and a container draw and drag themselves, and how a floor is rendered anywhere else |
| `iso.py` | The isometric projection and the shapes drawn through it |
| `room_view_3d.py` | The 3D room view: painting, picking, dragging, resizing |
| `inspector.py` | The edit panel down the right |
| `items_section.py` | The item catalog, the saved views, the tag manager |
| `export.py` | Writing CSV and PDF. Doesn't touch any screens. |
| `main.py` | Starts the app and swaps between launcher and workspace |

Roughly: `models` and `storage` are the data, `theme` and `widgets` are the
look, everything else is a screen.

## Using it

**The launcher.** The app opens maximized, split in two: your profiles down
the left, and a preview of whichever one you're pointing at on the right.

Each card carries the counts (floors, rooms, containers, items), when you last
saved it, and the one thing most worth knowing: how many items are unfiled, or
running low, in amber. A launcher that lists nothing but names makes you open
a profile to remember what's in it.

Only one warning per card, on purpose. A card is a glance, and a glance that
lists three problems is a card you stop reading. Right-click one for open,
rename and delete. With nothing saved yet you get a proper welcome panel
explaining what a profile is instead of a lone dashed square.

**The preview.** Point at a card and its ground floor is drawn full size on
the right, so you can see the room you're about to click before you click it.
The counts tell you how much is in a profile; they can't tell you which one it
is. A floor plan can, because you recognize your own house long before you've
read a number.

It's the ground floor and only the ground floor. Floors are kept in building
order with the lowest at index 0, so the preview is `floors[0]` rather than a
search, and it's the floor you'd walk in on.

Pointing at a different card swaps it over. Moving off the list puts the panel
back to "Point at a profile to see its floor plan". Leaving a *card* doesn't
clear anything, only leaving the whole list does, because the gap between two
cards is a place your mouse passes through and not a decision to stop looking.

The preview has no drawing code of its own. It calls the same
`floor_items.render_floor` the PDF export calls, which builds real RoomItems
and renders them into a rectangle, so all three views of a floor plan are the
same code. Fix how a room looks once and you've fixed it everywhere.

One thing worth knowing if you touch it: building that scene takes about 12ms
for a five-room floor and 265ms for a sixty-room one. That's fine once and far
too slow in a `paintEvent`, which fires on every frame of a window drag. So
the result is kept as a pixmap and only redrawn when the profile or the panel
size changes. Everything else is a blit.

Maximized rather than fullscreen. Fullscreen hides the title bar and the
taskbar, which is right for a game and wrong for something you keep open
beside other windows.

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

Containers follow the same Move and Resize switch rooms do, with one
difference between the two modes that's worth spelling out.

**Resize works straight away.** Switch to Resize, click a container, drag its
handles. Resize holds rooms still anyway, so there's no drag on the floor plan
for a container to steal, and making you double-click into the room first was
pure ceremony. You could already type the numbers into the inspector from
anywhere, so the handles had no business being harder to reach than the boxes.

**Move still needs you inside the room.** Double-click the room first. Here a
drag genuinely does mean something else, move the whole room, and a drawer
quietly coming along for the ride is exactly the accident that focus mode
exists to prevent.

There are W and H boxes in the inspector either way, and they track a drag the
same way a room's do. A container is clamped to its room, so you can't stretch
a drawer out through a wall or shrink one below 20.

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

**Getting around.** Scroll to zoom. Middle-drag or right-drag to pan. Right
drag is the one worth knowing: it's the same button that opens the menu, so the
press only arms a pan and the first few pixels of movement decide which gesture
you meant. Move and it pans, stay still and you get the menu. The window system
sends the menu request after the button comes up either way, so the view
swallows that one when it knows a pan just happened.

**Right-click anywhere on the canvas** and you get a menu for whatever is under
the cursor. On empty space it offers Add room, with Draw room and Preset shape
underneath it. On a room you get Add container here, the work-inside toggle,
the three modes, lock, rename and delete. On a container, add an item or delete it.
On a corner, remove that corner.

**Working inside a room.** Double-click it. Everything else fades back, the
room itself locks so you can't shove it by mistake, and its containers become
draggable. Escape or another double-click steps back out.

**The 3D room view.** Step inside a room and it's drawn from the corner, like
an isometric game, filling the whole canvas. Click a container and the
inspector fills in exactly as it does on the flat plan: name, color, size,
height, tiers, tags, what's in it. Drag one across the floor, drag its corner
handles to change its footprint, drag the round handle floating above it to
change how tall it stands. Add container works the same way, dragging out a
footprint. The toggle is up in the toolbar, it's on by default, and it's
remembered per profile, so a warehouse of identical racking can stay flat
while a house doesn't.

The height handle floats on an arm above the box on purpose. It used to sit on
the top face, which is exactly where you reach to pick a box up, so every
attempt to move a cabinet made it taller instead. How far it floats is
`iso.handle_lift`, worked out from the footprint rather than fixed, because a
lift that looks generous on a small bin lands back inside the top face of a
wide workbench.

Turn it off and the program is exactly what it was. The 3D view is a second
widget that takes the canvas's place in a stack; with the toggle off it is
never shown and never asked anything.

**Getting back out.** There's a "Back to floor plan" button in the top left
corner of the canvas whenever you're inside a room, in 3D and on the flat plan
both. Escape does the same thing, and so does double-clicking the floor, but
neither of those is something you can see, and being stuck inside a room with
no visible door is a bad first five minutes. Both canvases read the corner
offset from `theme.CANVAS_EXIT_MARGIN`, so the button doesn't shift when the
toggle swaps one for the other.

None of it is really 3D. There's no engine and no extra dependency, just a
projection in `iso.py`:

```
screen_x = (x - y) * cos(30)
screen_y = (x + y) * sin(30) - height
```

Two lines, and the whole illusion comes out of them. A box is three polygons,
because from a fixed camera you can never see the other three faces. Draw
order is `x + y`, far to near, which is always right here because a drawer
can't wrap around another drawer.

Which three is worth working out rather than guessing, and I guessed wrong the
first time. A point is nearer the camera the bigger its `x + y`, so the
nearest vertical edge of a box is at `(x+w, y+d)`, and the two sides you can
see are the two that touch it: the `y+d` wall, which lands on the LEFT of the
screen, and the `x+w` wall, which lands on the RIGHT. Draw the wrong pair and
the box has a hole in one side. `solid_test.py` renders a box and counts
background pixels inside its own silhouette, because that hole is obvious in
use and easy to miss reading the code.

The same math run backwards is what makes dragging work. Two equations, two
unknowns, so it solves exactly, and a point on screen becomes the point on the
floor under it. That assumes height zero, which is true of anything standing
on the floor, and containers always are.

**Container heights.** Four presets in the inspector: Low, Medium, Tall, Full
height. Medium is the default, and every container in a save file written
before this existed becomes Medium, so an old profile looks like a room the
first time you open it in 3D rather than a car park. The 3D handle can put a
container anywhere between the presets, and the dropdown then shows the
nearest one so it's never blank.

The numbers behind those names are deliberately modest: Medium is about the
height of the drawn wall, and Full height is roughly twice it. The first set
was picked against an empty room, where anything looks reasonable, and they
were absurd the moment there was a wall to compare them to.

**Save file versions.** Most format changes need no special handling, because
`from_dict` reads every field with `.get(key, default)` and an old file just
takes the default. That covers ADDING things.

It does not cover changing what a number MEANS. Halving the height presets
turned a stored 60 from "medium" into "tall", and no default can tell those
apart. So a profile carries a `schema` number, and `migrate()` in `models.py`
brings older files up to date on load.

Two details there are load bearing. It works on the raw dictionary rather than
on loaded objects, because once a `Container` exists a missing height has
already been filled in with today's default and there's no way left to tell
"the user chose 30" from "this file predates heights". And it halves before
clamping, because the limits moved with the scale: clamping an old, legal 150
first would squash it to today's maximum and halve that instead.

Note that a container's `h` is its DEPTH on the floor plan, and `height` is
how tall it stands. They were never going to get the same name; `h` predates
the 3D view and renaming it would break every save file.

**Containers stay in their room.** Whatever you do to one, it ends up inside
the walls: drag a new one out through a wall and it stops at the wall, type an
absurd size into the inspector and it gets cut down, drag one across the floor
and it stops at the edge. Every route goes through `fit_in_room` in
`models.py`. One clamp with six callers, rather than six clamps that drift
apart, which is exactly how the bug below happened.

Inside the room means inside its OUTLINE, not inside the rectangle you could
draw around it. That distinction only matters for a room with a notch in it,
which is to say an L-shape, and for a long time the clamp did not make it: the
notch counted as floor, so a drawer could be parked in the missing corner. On
a flat plan that looks like ordinary empty canvas and nobody notices. In the
3D view the box stands over nothing at all, which is how it finally got
reported.

A bounding rectangle is easy to clamp to because you can take a minimum. An
outline with a notch has no such answer, and the honest one is "then it does
not go there". So `fit_in_room` takes a `stay` argument: where the container
is right now. If the new position does not fit, it slides as far along one
axis as does fit, and failing that it stays put. That is a wall, and a wall is
something anyone can predict without reading this paragraph.

Drawing a new container is the one case with nothing to stay at, so instead
the dashed preview turns red the moment the footprint leaves the room, and
letting go makes nothing. The tool stays armed so the next drag is another
attempt rather than a trip back to the toolbar. Right-clicking to drop one in
tries a smaller box instead of refusing, because you named the spot and a
smaller container there beats none at all.

A container already stranded outside is never trapped by any of this: if where
it sits is not inside either, the move goes through, because the alternative
is a box that can never be rescued. Loading a save file repairs those anyway,
nudging each one to the nearest spot that fits (`nearest_fit`), which for a
room made of straight walls is a handful of candidates to try and lands where
a person would have put it.

**Floors.** The stack is down the left, highest at the top, with arrows to step
through. Press the up arrow on the top floor and it offers to create a new
floor above rather than just doing nothing. Same going down, which is how you
add a basement. Right-click any floor in the stack for duplicate, rename and
delete, aimed at the floor you clicked rather than the one that's selected.

**Duplicating.** Ctrl+D copies the selected room or container, or use the
right-click menu. Floors are duplicated from their own menu in the stack. A
copy lands one grid square down and to the right, named "Kitchen copy", then
"Kitchen copy 2", and arrives selected so you can drag it where it goes. A
copied room comes back unlocked even if the original was locked, because it's
a new room you're still placing.

What a copy carries is structure, not contents. The rooms, their shapes, the
containers, their sizes and tiers, all come across; the items do not. Items
live in the catalog and point at a container by id, so a duplicated shelf
arrives empty. That's deliberate. Copying the contents too would tell you that
you own twice as many hammers as you do, and an inventory that lies about
quantities is worse than no inventory.

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

**Doing several items at once.** Every row on the Items screen has a tick box.
Tick a few and a bar appears with Add tags, Remove tags and Delete. Add and
Remove are two buttons rather than one "set the tags to this", because items in
a selection rarely have the same tags to begin with, and "put Fragile on all of
these" should not quietly strip the tags they already had.

The ticks are kept by item id, not by row, so they survive the list being
rebuilt as you search and filter. Anything deleted is dropped from the
selection on the next rebuild, so the count can't lie.

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
| `Ctrl+D` | duplicate the selected room or container |
| `Esc` in 3D | cancel the tool, or step out of the room |
| `Esc` | cancel a tool, step out of a room |
| `Delete` | remove whatever's selected on the canvas |

All the shortcuts are defined in one place in `workspace.py`, and each one
switches to the screen it needs on the way. Pressing Ctrl+F from the Layout
view jumps to Items first, because that's obviously what you meant.

Ctrl+D is the exception that proves the rule: it does nothing from the Items
screen rather than jumping. "Search" is a thing you want wherever you are.
"Copy what I picked" is not, because nothing is picked on a screen you aren't
looking at.

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

**A dialog that changes data can't rely on being accepted.** Assign tags has a
New tag button in it, and that tag joins the profile the moment you name it.
Press Cancel on the item you were editing and the tag is still there, but the
code path that saves and redraws never ran. The tag then lived in memory only:
on screen until the next rebuild, and never written to the file at all.

Anything that mutates shared data mid-dialog has to report that separately from
its accept or reject. `TagPickerDialog.created_tags` is that report, and every
caller acts on it either way.

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

**An alignment flag can undo all of that.** `layout.addWidget(panel, 0,
Qt.AlignLeft)` looks like it only says where to put something. It also tells
the layout to give it exactly its `sizeHint` and not a pixel more, and a
sizeHint that contains wrapped text is always short, because the hint is
worked out before anyone knows how wide the thing will be. I measured it at
six pixels on the welcome panel, which was enough to squeeze three lines of
text into two and paint the third over the heading above.

So it looked like the wrapping bug again, and `wrapped()` was already on every
label in there. The fix was to drop the alignment flag and put a stretch
beside the panel instead, which pushes it left the same way while leaving the
layout free to give it the height it asks for. If text is overlapping and
`wrapped()` is already in use, go and look at how the parent was added.

**A fixed-width column beats a maximized window.** Once the app started
opening maximized, the item rows stretched to nineteen hundred pixels with the
name at one end and the buttons at the other. The list now sits in a column
capped at `LIST_MAX_WIDTH` with a stretch either side. The stretch on the
column is 100 against 1: with equal weights the three of them split the room
evenly and the list ends up narrower than its own cap.

**KeepAspectRatio scales but doesn't center.** `scene.render(painter, target,
source, Qt.KeepAspectRatio)` reads like "fit this in there", and the scaling
half is right. The placing half isn't: the result is anchored to the top left,
so on a panel wider than the plan the whole thing sits against one edge with
all the spare room piled up on the other. Measured at 38 pixels on one side
and 876 on the other.

`fit_inside` in `floor_items.py` works out the destination rectangle first and
hands Qt one that already has the right shape, with `IgnoreAspectRatio`. The
fitting then happens in eight lines you can read instead of inside a flag.

**Five clamps and a gap.** A container could be dragged out through a wall
and left there, and once it was out there you couldn't do anything with it
except delete it. Two separate mistakes stacked on top of each other, and the
second one is the interesting half.

The first: four of the five ways to set a container's geometry clamped it to
the room, and the fifth, the Add container drag, didn't clamp at all. Nobody
writes five clamps on purpose. They accumulate, each one added next to the
code that needed it, and the fifth path gets written later by someone who
assumes the clamping already happened somewhere. There is one now, in
`models.py`, and every path calls it.

The second: clicking the stranded container did nothing, and it took
reproducing it to see why. Clicking bare canvas steps you out of the room
you're working inside. The test for "bare canvas" was "no room polygon
contains this point" - and a container sitting outside its room is, by that
test, bare canvas. So the click dropped the room focus, dropping focus makes
every container in the room stop accepting the mouse, and the thing you were
reaching for stopped accepting the mouse before it could be picked up.
Clicking it was what made it unclickable.

Both are fixed, but only the second one makes it impossible to get stuck
again. The clamp stops containers ending up outside; the focus fix means that
if one ever does, by a route nobody thought of, you can still grab it and drag
it back. A save file that already has one repairs itself on load.

**Two views of the same data means two things to keep in step.** Adding the
3D room view meant every place that said "repaint the canvas" was now only
half right, and the half it missed was the one not on screen. Deleting a
container refreshed the flat canvas, so the 3D view went on drawing resize
handles around a box that no longer existed. Adding a tier or typing a new
size updated the data and repainted nothing you could see.

There is one `refresh_views()` now and both canvases go through it, including
the hidden one. Repainting a widget nobody is looking at costs nothing and
removes a whole class of "it only goes wrong after you toggle" bugs.

The other half of that fix is that the 3D view drops a selection that is no
longer in the room, in `refresh()` rather than at each place a container can
be deleted. Put the check where it cannot be forgotten, not at every call
site that has to remember it.

**A repaint is not a refresh, in a QGraphicsScene.** That same pair of views
produced a second, subtler version of the same bug. `FloorView.refresh()`
called `update()` on every shape, which is exactly right when only the text
changed. But the 3D view edits the model directly, and a QGraphicsItem holds
its own position: told to repaint, it dutifully repaints itself where it
already was. Move a cabinet in 3D, step back out to the floor plan, and it was
still in its old spot until something happened to rebuild the room. The data
was right the whole time, which is what made it look so strange.

Refresh now means reading the positions back out of the model
(`sync_from_model`), not just repainting. Two details there are load bearing.
It moves the existing items rather than rebuilding them, so selection
survives. And it turns geometry notifications off while it does, because
`itemChange` snaps to the grid and clamps to the room, which is right while
someone is dragging and wrong here, where the model is already the answer.

The wiring mattered too. `_on_data_changed` refreshed only the 3D view, on the
reasoning that the flat canvas is usually what raised the change and so
already knows. Usually is not always, and "usually" is where these live.

**QColor cannot read the string with_alpha gives you.** `with_alpha` returns
`"rgba(79, 124, 255, 0.16)"`, which is what a Qt STYLESHEET wants. Hand that
to `QColor` and it does not complain, it does not raise, it just gives you
opaque black. A faded highlight turns into a solid slab and you go hunting
through your drawing code for a bug that is one constructor away.

Use `theme.qcolor(hex, alpha)` for a QColor and `with_alpha` only in
stylesheets. They now live next to each other so the difference is visible.

**Anything expensive in a paintEvent will be felt.** `paintEvent` is not a
"when the data changes" hook. It runs when the window is resized, uncovered,
or scrolled past, which during a drag is every frame. The preview's first
version rebuilt a whole QGraphicsScene in there. Fine on a five-room floor,
a quarter of a second on a sixty-room one, which is a window you can watch
lag behind your mouse. Do the work when the inputs change, keep the picture,
and let paintEvent copy it.

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

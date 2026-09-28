# Invenfloor in the browser

The same app, running anywhere. This folder is the beginning of it.

`index.html` is the app. It opens the profiles saved in this browser, draws
floor plans, and steps inside a room to show it in 3D with containers you can
pick up and move.

Everything the desktop app does with a floor plan is here: drawing a room
corner by corner, the five preset shapes, moving and stretching rooms, pulling
their corners about, adding and removing corners, locking one so it cannot be
shoved by accident, dragging containers out inside a room and resizing them,
tiers, heights, colors, duplicate, delete, and undo. A profile can start from
nothing here now; it no longer has to come from the desktop app.

There is an items screen too: everything in the catalog, searchable, saying
where each thing lives and which shelf it is on, with tabs for the things that
are not filed anywhere and the things that have dropped below the level you
want to keep.

What is not here yet is tags, which the model has and no screen shows.

## Running it

**`index.html` is the app.** **`dev.html` next door is the workbench**: a page
that checks the model and the saving work in this browser, reads a save file
from the desktop app, and lets you watch a profile survive a reload.

**Do not double-click either of them.** Opening a page from Explorer gives the
browser a `file://` address, and browsers refuse to load JavaScript modules
over `file://`. The error mentions "CORS policy" and looks like broken code
when it is not. Everyone hits this once.

In VS Code: Extensions in the left bar, search **Live Server**, install it.
Then right-click `index.html` and choose **Open with Live Server**. It opens on
`http://127.0.0.1:5500/` and reloads whenever you save, which is most of what
makes this pleasant.

**F12** opens the browser's developer tools. The **Console** tab is where
JavaScript errors show up. When a page goes blank or a button does nothing,
the answer is almost always the first red line in there.

**Node.js** is only needed for the two harnesses below, not for viewing pages.
`node --version` in a terminal says whether you have it.

## Putting it somewhere other people can open

GitHub Pages hosts this for nothing, and the reason it fits so well is the
thing that also decides everything else in this folder: there is no server
side. No accounts, no database, no request that leaves the page. Pages serves
files and that is all this needs. Free, and there is no bill that can grow
later because there is nothing running.

Two files at the root of the repo make it work, and they are already there:

- **`index.html`** at the root, which is the front door. Pages will serve the
  root of a branch or a `/docs` folder and nothing else, and the app lives in
  `web/`, which is neither, so something at the root has to point at it. It is
  a page rather than three lines of redirect because of who follows the link:
  somebody who knows nothing, probably on a phone, from a message that said
  "have a look at this". A paragraph telling them what it is and that nothing
  leaves their device costs nothing and is the difference between them trying
  it and closing the tab.
- **`.nojekyll`**, an empty file that tells Pages not to run the whole repo
  through Jekyll first. Nothing here needs it, and without the file Pages
  quietly ignores any folder whose name starts with an underscore, which is a
  bad surprise to have waiting.

Then, once:

1. Push everything to `main`.
2. On GitHub: **Settings**, then **Pages** in the left column.
3. **Source**: Deploy from a branch. **Branch**: `main`, folder `/ (root)`.
4. Save. The first build takes a minute or two.

The address is **https://realtotemg.github.io/Invenfloor/**, and it is a
different repo from `realtotemg.github.io`, so the portfolio site is untouched
by any of this. Every push to `main` from then on republishes within a minute,
so getting a fix to a tester is `git push` and nothing else.

Serving from the root does mean the `.py` files are served too. They are
already public in the repo, so nothing is revealed that was not, and nobody
will ever ask for them.

### Checking it before anybody else does

Open the address on a phone, not just on the machine that pushed it. Phones
are where this gets used and where a browser is most likely to be old.

The app has to be reached from a real web address rather than a file on a
disk, which is the same `file://` rule as above. If the page comes up empty,
it says so after a few seconds instead of sitting blank, and `index.html` in
this folder explains why in a comment.

### When it should stop being Pages

When somebody asks for their inventory on their phone AND their laptop. That
is sync, sync needs somewhere to sync to, and that is the first thing here
that genuinely needs a server. Until somebody asks, a server would cost money
to run, put other people's inventories on a machine you are then responsible
for backing up, and buy nothing they can see.

## Why the model came first

`models.py` is the part of the desktop app that took the most thinking and
carries the most tests: which walls face away from you, whether a container
is really inside an L-shaped room, what a stored 60 meant before the height
presets were halved. None of that is about Qt, and none of it should be
worked out a second time because the drawing moved to a canvas.

It is also the part every screen depends on. Porting it first means the rest
is a drawing exercise rather than a drawing exercise sitting on top of an
untested model.

## The save file is the same file

`toDict` and `fromDict` produce and accept exactly what the Python does,
field for field, including the schema number and the migration. A profile
exported from the desktop app opens here, and one written here opens there.

That is worth keeping. The day this replaces the desktop app should not be a
day that needs a converter.

## Checking the port

Not by writing tests for it. The same misunderstanding that produces the code
produces the test, so a port that passes tests written for it afterwards has
proved nothing much.

Instead both implementations answer the same questions and the answers are
compared:

```
python web/parity_cases.py > web/parity_cases.json
node web/parity.mjs
```

`parity_cases.py` builds a few thousand cases, every room preset plus a
fireplace divot, a narrow spike, a sliver, a room at negative coordinates and
some random polygons, crossed with rectangles both sensible and absurd. It
answers each one with `models.py` and `iso.py` and writes the answers out.
`parity.mjs` answers the same cases with `model.js` and `iso.js` and compares.

It covers the projection too, which matters more than it sounds: getting a
sign wrong in there does not throw, it draws a room inside out, and that is
the kind of mistake that survives a review and turns up in a screenshot a week
later. The palette goes through it as well, so `theme.js` and `theme.py`
cannot quietly drift into slightly different shades of the same app.

Currently 6,285 cases, all agreeing.

Run it after any change to either file. A divergence is a bug in one of them,
and the harness does not care which.

### It has already earned its keep

Six disagreements turned up, and the last one was a bug in the Python rather
than in the port.

`clamp_height("nan")` returned nan, which reached a container, which wrote
`"height": NaN` into the save file. Python's `json` module accepts that as an
extension of the format and reloads it happily. It is not valid JSON, so
every other reader in the world rejects the file, including this one. A save
that only opens in the app that wrote it is the worst shape of broken:
invisible until something else tries to read it.

Both now treat not-a-number as unreadable and fall back to the default, the
same as `None` or `"oops"`.

The other five were the port's, all in one place: JavaScript's `Number()` and
Python's `float()` disagree at the edges in both directions. `float(True)` is
1.0 where `parseFloat(true)` is NaN; `float("0x10")` raises where
`Number("0x10")` is 16; `float("1_0")` is 10.0 where `Number("1_0")` is NaN.
`asNumber` in `model.js` now does what `float()` does and says why.

## Saving

`storage.js` is the twin of `storage.py`, same names in the same order. One
record per profile, the previous save kept, a snapshot at the start of each of
the last ten days you used the app, and a load that falls back through all of
it and says what it had to do.

It goes in IndexedDB, which every browser has had for a decade, on phones as
well as desktops. Three things about it are worth knowing before building on
it.

**It belongs to one browser on one device.** Profiles made in Chrome on the
desktop are not the profiles Safari shows on a phone. Nothing in the browser
can change that, because there is no server. The interface has to say so out
loud rather than letting someone go looking for a profile that was never going
to be there.

**The browser can throw it away.** Storage is evicted when a disk fills, and
Safari clears script storage after seven days of not visiting a site.
`requestPersistence()` asks the browser not to and the browser is allowed to
say no. So export is not a nicety here the way it is on the desktop. It is the
backup that outlives the browser, and the app should push people towards it.

**It is stronger than the desktop in exactly one place.** `storage.py` writes
to a temporary file, flushes it to the disk and renames it, and there is a
sliver of time between its two renames where the live file does not exist.
That is covered rather than merely small, but it is there. An IndexedDB
transaction commits whole or not at all, so the same three steps here have no
gap between them at all.

## The passphrase

`vault.js` can put a lock over all of it. With one set up, what sits in
IndexedDB is ciphertext, and there is no way to read it without the passphrase
or the recovery code.

Be clear about what that is and is not. It is a lock on data at rest in one
browser, and it stops somebody who sits down at an unlocked laptop or copies
the browser profile off a disk. **It is not a login.** Nothing checks who you
are, because there is nobody to check against. The passphrase is not sent
anywhere and is not compared to anything: it either derives a key that opens
the data or it does not. And it is no protection at all against something that
controls the machine or the page, which sees the profiles after they are
unlocked exactly as you do.

### Why now, when nobody is using it

Because it is free today and never will be again. Adding encryption to a save
format people already have data in means a migration, tested against every
shape of old file, getting it right the first time on machines you cannot see.
Adding it before anyone has a profile costs nothing.

### How it is put together

A random 256-bit content key encrypts every record. That key never comes from
the passphrase. The passphrase derives a second key, and that second key wraps
the content key, which is stored wrapped.

The indirection earns its place three times. Changing the passphrase rewraps 32
bytes instead of re-encrypting every profile, backup and snapshot, and a change
that can half-finish is a change that can lose data. The recovery code is just
a second wrap of the same key rather than a second copy of everything. And a
server-held wrap, the day there is a server, is a third entry in the same list,
with the profiles still unreadable to that server.

Key derivation is PBKDF2-HMAC-SHA256 at 600,000 iterations, which is what
[OWASP's password storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
calls for. Argon2id would be better and is not in the Web Crypto API, so having
it would mean a WebAssembly build, a build step and a dependency, to protect a
local database. Not worth it here. Worth revisiting the day a server is holding
everybody's.

Records are AES-GCM with a fresh random IV every single write, and the profile
id goes in as additional authenticated data so a record cannot be slid into
another profile's slot.

### What is still in the clear

Profile ids, because they are the keys records are filed under and you cannot
look up what you cannot name. How many profiles there are. When each was last
saved and which days have snapshots. Somebody reading the raw database learns
that you have four profiles and used the app on the 12th. They do not learn a
single room, container or item.

Exports are plain JSON too, deliberately, even with a lock on. That file is
what opens in the desktop app and it is the backup that outlives the browser,
and an export nobody else can read is not a backup, it is a second thing to
lose the key to. It does mean an export is as safe as wherever it is put, which
the interface has to say at the moment somebody presses the button.

### There is no password reset

There cannot be. A reset means somebody, somewhere, can get in without the
password, and the entire point is that nobody can. Lose the passphrase and the
recovery code and the data is gone.

Which is why setting a lock hands back a recovery code, once, and why the
interface has to make people write it down rather than mentioning it politely.

## Checking it

```
node --import fake-indexeddb/auto web/storage_run.mjs
```

The first time, `npm install --no-save fake-indexeddb` puts the stand-in in
place. Nothing the app ships depends on it, `node_modules` is ignored by git,
and deleting it costs one command to get back.

267 checks: the model, the lock, the saving twice over, the floor plan and
the items screen, once plain and once
with a passphrase across the database. Not two sets of checks, the same set,
because that is the claim encryption has to earn. Backups still happen daily, a
wrecked record is still rescued from the same places in the same order, the
launcher still sorts the same way. If any of the fifty behaved differently with
a lock on, the lock would be in the wrong place.

A stand-in is not the real thing, so the same checks run in `dev.html` against
the real IndexedDB, and that is the run that counts. They live in one file,
`storage_checks.js`, so there is no second copy to keep in step. The databases
they use are wiped before and after, so running them can never touch real
profiles.

Running them in a real browser has already paid for itself. Two of the vault
checks passed in node and failed in Chrome, because Web Crypto rejects with an
exception whose message is an empty string there and a full sentence in node.
The code was right and the check was asking the wrong question.

These are ordinary tests rather than a parity harness, and that is worth being
honest about: I wrote the code and I wrote the tests, so a misunderstanding in
one can live happily in the other. What they are good for is the thing that
actually goes wrong in a file like this, which is not arithmetic. It is order.
Was the snapshot taken before the write or after it. Did the broken record
move out of the way before the next save, or did the next save bury the backup
it was rescued from. Every one of those is a sequence of writes with a wrong
answer at the end, and that is exactly what a test can pin down.

They were then checked by breaking `storage.js` and `vault.js` on purpose,
twenty-four different ways, and making sure the checks noticed. A check that
passes on broken code is not a check. Two of the twenty-four earned their keep
immediately: one found dead code, and one found a real bug, where taking a
passphrase back off would have written null over any record that would not
decrypt. Unreadable is not the same as worthless, and those records are the
only copy of something somebody may still want picked apart by hand.

### One gap, on the desktop side

Saves can now travel, and the desktop app has no way to open one. It reads
whatever is in its `data\` folder and there is no Import button.

So a profile downloaded from the browser goes over by renaming it to just its
id, `a3f9c1d2.json`, and dropping it in `data\`. That works today and it is a
silly thing to ask of anybody. An Import button on the profile screen is a
small job and should happen before this is shown to anyone.

## No build step

Plain ES modules. Open the page and it runs. A bundler is a thing that breaks
and needs maintaining, and nothing here needs one.

## Saying what a button does

A toolbar can only tell you what a button is CALLED. "Draw room" is not
obvious until you have used it once, and neither is the difference between
Resize and Reshape.

So three things, and the third is the one that matters.

Every tool has a **picture and a word**, not one or the other. The word is what
tells you the first time; the picture is what you find it by every time after.
And a tooltip on each, for a mouse.

The tools are **grouped and labelled**. "Tool" over Select, Draw room and Add
container. "Or start from a shape" over the five presets. Laid out identically,
as they were, the presets read as five more tools rather than five ways to
start the same one.

And a **line under the toolbar that says what to do next**. Not what the button
is called: what happens when you press the canvas, right now, with the tool you
have picked. "Press to place each corner. Press the ringed first corner, or
Enter, to close the room." "Drag a rectangle inside a room to make a container
there." It changes with the tool, with the selection, and with how far through
a shape you are, and it is the only thing on the screen that can answer the
question somebody actually has.

### Getting out of a half-drawn room

Escape has always worked and a phone has no Escape. So while a room is being
drawn the hint line carries two buttons: **Take back a corner**, which removes
the last one, and **Cancel**, which throws the shape away. The line also counts
the corners as they go down, so there is never a question of how far through
you are, and the first corner grows a ring the moment there are enough to close
the shape.

## Tiers, and putting things on them

A container can be divided into tiers, and a pile of something sits either on
one of them or loose in the container itself. That is tier 0, and it is not a
missing value: a bin with no shelves has everything loose in it, and so does
the floor of a cupboard with three shelves above it.

Tiers are not named or colored, on purpose. A shelf's levels do not have names,
they have positions, and "Tier 2" already says everything there is to say.

The panel for a container groups what is in it under a heading per tier, and
every pile gets a dropdown to move it to another one. Moving a pile onto a tier
that already has some of the same thing ADDS to it rather than replacing it,
which is the difference between a shelf and a slot.

Add tier and Remove tier are there too. Removing one throws nothing away:
whatever was on it comes back loose in the container, because you still own it
and it is still in that cupboard, you just stopped dividing the cupboard up.

**And the 3D view draws them.** Each tier shows a block of color per thing
sitting on it, in that thing's own color, along the face you are looking at.
That is the whole reason tiers are worth having: a number in a panel saying
"4 tiers" tells you the shelf is divided up, and seeing the sockets on the
second one tells you where to reach.

## Two fingers are the camera

The desktop app pans with the right mouse button, which a phone does not have.
So: one finger is the tool, two fingers are the camera, pinching to zoom and
sliding to pan. That is what every drawing app on a phone does, which means it
is what hands already expect. On a desktop the wheel zooms, the middle button
or the space bar pans, and the left button is the tool, which is what hands
expect there.

A second finger arriving in the middle of a drag takes over, and whatever the
first one was doing is abandoned rather than finished wherever the second
finger happens to leave it.

## Checking the screens

`items_checks.js` drives the contents panel and the items screen the way a hand
does: find the button, press it, then look at the profile. Thirty-seven checks,
and the thing being checked is always the profile rather than the markup. What
matters is that pressing + put one more sock on tier 3, not that the row has a
particular class on it.

Both are functions that fill an element, which is what makes them this easy to
ask questions of. Sixteen deliberate breakages, all caught, after one gap was
closed: the "put one somewhere" check used an item that was nowhere, so adding
to a pile and replacing it looked identical.

## Checking a canvas

`floor_checks.js` drives the floor plan through the same pointer events a hand
produces. Fifty-four checks: selecting, moving, stretching from each of the
eight grips, dragging corners, adding and removing them, all five presets,
drawing a room corner by corner, adding containers, pinching, and the rules
that stop a room being turned inside out or a container being dragged through
a wall.

The first version of these pressed at fractions of the real app's canvas and
hoped a handle was there. It found two real bugs and then spent longer failing
for reasons that were the test's fault than the code's, because a resize handle
is nine pixels wide and "about two thirds across" is not an address. These ask
the view where a handle actually is and press exactly there.

They earned their keep immediately. **Every handle drag silently did nothing
on any retina screen.** A drag has to travel a few pixels before it counts, so
a tap does not nudge what it lands on, and a handle drag skipped that with a
made-up distance of five, against a threshold of four times the pixel ratio,
which is eight on the machines most people have. It worked on the one display
that could not show the bug.

Then `floor.js` was broken on purpose ten different ways to make sure the
checks noticed. They caught nine. The tenth, a stretch that stopped anchoring
the far side of the room, went through because the check dragged the
south-east handle, where anchoring the far side and anchoring nothing look
identical. There is a check on the north-west handle now.

## The room view, and one thing it does better than the desktop

`iso.js` is the projection ported from `iso.py`, and `room.js` draws with it.
Most of it is the same file in another language. One part is not, and it is
worth knowing about because the same fix belongs in the Python.

**Walls kept being drawn over the containers standing in front of them.** The
desktop app sorts everything by a depth number, `x + y` of a corner, and draws
in that order. That has now failed three different ways:

- Sorting by the FAR corner breaks on walls. A wall runs the whole length of a
  side of a room, so it is nearer than some of what shares the room and
  further than the rest, and no single number says where it belongs.
- Cutting the wall into short pieces so each gets its own number, which is
  what the portfolio demo does, swaps one failure for another: a piece three
  quarters along the back wall now has a big number, and a container in the
  far corner has a small one, so the wall is drawn over the container it
  stands behind.
- Sorting by the NEAR corner breaks on wide objects. A shelf 400 long against
  the back wall has a nearer near-corner than a small bin in front of it, so
  the shelf covers the bin.

All three were tried. Each drew a correct picture in the room it was tested in
and a wrong one in the next.

The answer is that "behind" is not a number, it is a relation between two
things, and for footprints on a floor seen down the diagonal it is exact:

> A is behind B if A ends before B starts in x, or in y.

One axis is enough. That relation is a graph, and the drawing order is a
topological sort of it, which sounds heavier than it is: a room has a handful
of walls and a handful of containers, so it is a few hundred comparisons for a
whole frame, and it is right rather than right-so-far. `iso.paintOrder`.

`room_view_3d.py` still sorts by a number and still has the bug. It is the
same twenty-five lines.

## What is next

1. **Tags.** The model carries them, `misfiledItems` uses them to work out
   what is in the wrong room, and no screen here shows or edits one yet.
2. **The draw order fix, back in the Python**, per the section above.
3. **An Import button on the desktop app**, per the gap above.

Rough sizes, from the Python: about 2,000 lines of model and storage, and
somewhere north of 8,000 of interface. The part underneath is now done.

## And the thing after that, which is a decision rather than a task

There is still no server, so there are still no accounts. One browser, one
device, one set of profiles, and the only way to move them is a file.

That is fine for one person and it is not fine for a business with three staff
and a tablet at the counter, which is what a POS integration implies. Real
accounts mean a server, a database, password hashing, sessions, email
verification, a bill, and somebody responsible for the whole thing when it
breaks at 9pm on a Saturday. That is a bigger step than anything in this folder
so far, and it is worth taking deliberately rather than drifting into.

What was built here does not go to waste when that day comes. The wrapping
design already has room for a third key holder, so the sync-everything version
can hold ciphertext it cannot read. That is a good position to be in, and it is
much easier to keep than to retrofit.

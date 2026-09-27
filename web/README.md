# Invenfloor in the browser

The same app, running anywhere. This folder is the beginning of it.

Nothing here draws anything yet. What exists is the part underneath: the
records, the save format and the geometry, ported from `models.py` and checked
against it case by case, and the saving, which keeps the same backups and the
same rescues as the desktop app.

## Running it

Open `dev.html` and you get a page that checks the model works in a browser,
reads a save file from the desktop app, checks the saving, and lets you keep a
profile in the browser and watch it survive a reload.

**Do not double-click it.** Opening it from Explorer gives the browser a
`file://` address, and browsers refuse to load JavaScript modules over
`file://`. The error mentions "CORS policy" and looks like broken code when
it is not. Everyone hits this once.

In VS Code: Extensions in the left bar, search **Live Server**, install it.
Then right-click `dev.html` and choose **Open with Live Server**. It opens on
`http://127.0.0.1:5500/` and reloads whenever you save, which is most of what
makes this pleasant.

**F12** opens the browser's developer tools. The **Console** tab is where
JavaScript errors show up. When a page goes blank or a button does nothing,
the answer is almost always the first red line in there.

**Node.js** is only needed for the two harnesses below, not for viewing pages.
`node --version` in a terminal says whether you have it.

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
answers each one with `models.py` and writes the answers out.
`parity.mjs` answers the same cases with `model.js` and compares.

Currently 3,844 cases, all agreeing.

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

### Checking it

```
node --import fake-indexeddb/auto web/storage_run.mjs
```

The first time, `npm install --no-save fake-indexeddb` puts the stand-in in
place. Nothing the app ships depends on it, `node_modules` is ignored by git,
and deleting it costs one command to get back.

A stand-in is not the real thing, so the same checks run in `dev.html` against
the real IndexedDB, and that is the run that counts. They live in one file,
`storage_checks.js`, so there is no second copy to keep in step. The database
they use is called `invenfloor-checks` and is wiped before and after, so
running them can never touch real profiles.

These are ordinary tests rather than a parity harness, and that is worth being
honest about: I wrote the code and I wrote the tests, so a misunderstanding in
one can live happily in the other. What they are good for is the thing that
actually goes wrong in a file like this, which is not arithmetic. It is order.
Was the snapshot taken before the write or after it. Did the broken record
move out of the way before the next save, or did the next save bury the backup
it was rescued from. Every one of those is a sequence of writes with a wrong
answer at the end, and that is exactly what a test can pin down.

Each of the fifty was then checked by breaking `storage.js` on purpose,
fourteen different ways, and making sure the checks noticed. A check that
passes on broken code is not a check.

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

## What is next

1. **The room view**, which mostly exists already. The demo on the portfolio
   site is the projection, the wall culling and the containment test running
   in a canvas. It needs to read this model instead of its own flattened one.
2. **The floor plan canvas**, which is the larger piece and has no head start.
3. **The items screen.**
4. **An Import button on the desktop app**, per the gap above.

Rough sizes, from the Python: about 2,000 lines of model and storage, and
somewhere north of 8,000 of interface. The part underneath is now done.

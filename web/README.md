# Invenfloor in the browser

The same app, running anywhere. This folder is the beginning of it.

Nothing here draws anything yet. What exists is the part underneath: the
records, the save format, and the geometry, ported from `models.py` and
checked against it case by case.

## Running it

Open `dev.html` and you get a page that checks the model works in a browser
and reads a save file from the desktop app.

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

**Node.js** is only needed for the parity harness below, not for viewing
pages. `node --version` in a terminal says whether you have it.

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

## No build step

Plain ES modules. Open the page and it runs. A bundler is a thing that breaks
and needs maintaining, and nothing here needs one.

## What is next

1. **Storage behind an interface.** IndexedDB first, because it works on
   every device today, shaped like `storage.py` so the server version later
   is one module swapped rather than a rewrite. Plus export and import of the
   same JSON, which is what makes browser storage survivable: it is per
   device and Safari clears it after a week of not visiting.
2. **The room view**, which mostly exists already. The demo on the portfolio
   site is the projection, the wall culling and the containment test running
   in a canvas. It needs to read this model instead of its own flattened one.
3. **The floor plan canvas**, which is the larger piece and has no head start.
4. **The items screen.**

Rough sizes, from the Python: about 2,000 lines of model and storage, and
somewhere north of 8,000 of interface. The model is the part that is done.

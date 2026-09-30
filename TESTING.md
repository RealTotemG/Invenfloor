# Testing Invenfloor

Thanks for doing this. Below is where it lives, what I would most like you to
try, what I already know about, and how to tell me when something breaks.

You do not have to work through all of it. Half an hour of somebody using it
like they mean it is worth more than a full pass done dutifully.

## Where it is

    https://realtotemg.github.io/Invenfloor/

No account, no install, no upload. It is a web page that keeps everything in
your own browser. Chrome, Edge, Firefox and Safari all work, and so do phones
and tablets.

**On a phone,** open that address and use your browser's "Add to Home Screen".
You get an icon and a full screen window with no browser bars, which is the way
you would actually use it: standing in the room, counting, one thumb.

**Have a look first without committing to anything.** The first screen has
"Open a made-up house" at the bottom. That is a small pretend house with rooms,
shelves and items already in it, and nothing is saved unless you press Keep.
Break it as hard as you like.

## The idea, in three lines

Most inventory software gives you a list and expects you to remember the rest.
This one asks where things are. You draw the floor plan, put containers in the
rooms, and file items onto their shelves, so "where are the spare filters" has
an answer you can point at.

## The five I would most like tried

These are the parts most likely to be wrong, so this is where your time is
worth the most.

1. **Draw a room that is not a rectangle.** Use the L shape, or draw your own
   with corners. Then try to put a shelf into the notch of the L, and along
   each wall, and right into a corner. It should refuse the notch and accept
   the corner.

2. **Sketch rooms roughly, then type the real numbers in.** Select a room and
   put its actual width and depth in the boxes, then its X and Y. Do that for
   three rooms next to each other. I want to know whether you end up with a
   floor plan or a pile.

3. **Step inside a room and work in 3D.** Press a room twice to go in. Add a
   container while you are in there. Press Escape. Press the 3D button. Go to
   Items and come back. At every point, the app should still know which room
   you are in, and Escape should never dump you somewhere you did not ask for.

4. **Use tags to find something out of place.** Tag a room with what belongs in
   it, for example Tools on the garage. Tag some items the same way. Then open
   Items and press "In the wrong room". Then tick several items at once and put
   a tag on all of them from the bar that appears.

5. **Undo, a lot, from inside a room.** Select a shelf, change its tiers, move
   it, rename it, then press Undo six times and Redo six times. You should end
   up where you started and still be standing in the same room.

## If you have more time

- Put a passphrase on a profile, close the tab, come back the next day.
- Press Download to get a file, then open that file in a different browser.
- Fill a four tier shelf and then cut it to two tiers.
- Put a shelf in a room and then shrink the room around it.
- Add ten items back to back from the Items screen without stopping.
- Do a real count of one shelf, on your phone, standing in front of it.
- Leave it a week and come back.

## Known already, so do not spend your evening on these

- **One drag can make wildly different sized rooms** depending on how far you
  are zoomed in, and nothing on the canvas says what one grid square is. The
  first room you draw ends up setting the scale for everything after it, by
  accident.
- **Shrinking a room shrinks the shelf inside it** to fit. Better than leaving
  the shelf stranded outside the wall, but it is still a surprise.
- **The number floating at a room's far corner** is how many containers are in
  that room. It reads like a rendering fault until somebody tells you.
- **Undo history does not survive a page reload.** Your data does; the list of
  what you can undo does not.
- **The desktop version is not where the work is going.** If you have it, the
  browser one is the current app and the one worth testing.

## Not bugs, even though they look like it

- **Duplicating a loaded shelf gives you an empty one.** You duplicate a shelf
  to get a second shelf, not to double your stock.
- **Deleting a room does not delete its items.** They stay in the catalog and
  turn up under "Not filed".
- **Cutting a shelf's tiers does not throw anything away.** Whatever was on the
  tiers that went comes back loose in the same container, quantities intact.
- **Nothing syncs between devices.** That is the trade for nothing ever
  leaving your machine. Download the file and open it on the other one.
- **There is no password reset.** If you put a passphrase on a profile, there
  is a recovery code and that is the whole of it. There is nobody to ask,
  because there is no server.
- **The made-up house disappears when you close the tab** unless you pressed
  Keep.

## Telling me something broke

At the bottom of the first screen there is a button that says **Something
wrong?**. Press it and the app writes the report for you: which version, which
browser, which screen size, whether it was able to save anything at all, and
the last error it hit. Copy that text and send it with your note.

If you are in the middle of something, press **Profiles** at the top left to
get back to that screen. A profile you have kept is saved on the way, and the
last error is still remembered when you arrive, so you do not have to make the
bug happen a second time to write it down.

The made-up house is the exception, because it was never saved: going back to
Profiles ends it. So if you hit something interesting while testing on it,
press **Download** first. That gives you the whole thing as a file, and a file
is the most useful thing you can possibly send me, because I can open it and be
looking at exactly what you were looking at.

Send the file for the made-up house, or for anything you do not mind me seeing.
Do not send one of your real inventory unless you are happy for me to read it,
and never feel you have to: the report text plus a description is enough to
work with.

It contains nothing about what is in your inventory. No profile names, no room
names, no item names, no counts. Just how many profiles exist and nothing else.
The whole point of the app is that your data stays on your machine, and a
diagnostics button that quietly walked it out of that promise would be worse
than no diagnostics button.

Send it as a GitHub issue:

    https://github.com/RealTotemG/Invenfloor/issues

or just send it to me however you normally would.

## What makes a report I can act on

Four lines beats four paragraphs:

    What I was doing:  drew an L shaped garage, dragged a shelf toward the notch
    What I expected:   it would refuse to go in the notch
    What happened:     it went in, and half the shelf is through the wall
    Then:              [paste the Something wrong? text]

"It didn't work" is not your fault, it is all you can see from where you are
standing. The report text covers most of what I would otherwise have to ask.
What it cannot tell me is what you were trying to do at the time, so that one
line is the one that matters.

A screenshot is worth a lot, especially for anything that looks wrong rather
than behaves wrong. On a phone, so is telling me which phone.

## If it will not start at all

Two things cause that almost every time: a browser more than a few years old,
or the page opened from a file on disk instead of from a web address. Try the
address above in an up to date Chrome, Firefox, Safari or Edge.

If the first screen says it cannot save anything, you are in a private window
or site data is switched off for that browser. You can still use it and open
files, but nothing will be kept.

"""
undo.py
=======

Undo and redo for the current session.

WHY SNAPSHOTS AND NOT OPERATIONS
--------------------------------
There are two ways to build undo. The clever one gives every action an
opposite: "moved container from A to B" undoes by moving it from B to A. It is
efficient, and it is a trap, because it needs a correct opposite for every
single action in the program, forever. Get one wrong -- forget that deleting a
room also orphaned the items inside it -- and undo quietly corrupts the data
instead of restoring it. Every new feature is a new chance to get one wrong.

The blunt one keeps copies. Before a change, write the whole profile down;
to undo, read it back. There is nothing to get wrong, because there is no
per-action reasoning at all. A new feature is undoable the day it is written
and nobody has to remember to make it so.

The blunt one costs memory. So: how much? A profile saves as JSON, and a
real one -- a house, a few dozen containers, a few hundred items -- is a few
kilobytes. A hundred of those is well under a megabyte. The clever version
would save maybe half a megabyte of RAM in exchange for a whole category of
bug that only ever shows up in the data. That is a bad trade, so this file
takes the blunt one.

WHAT A SNAPSHOT IS
------------------
The JSON text of the profile: exactly what storage.py writes to disk. Text
rather than a dictionary, on purpose, for two reasons.

It cannot be shared by accident. A dictionary handed to two places is one
dictionary, and an edit through one of them changes what the other sees, which
in an undo stack means the history quietly rewriting itself. Text cannot do
that.

And two snapshots can be compared with ==. That is what stops a change that
changed nothing from taking up an undo step: press a color swatch that is
already selected and the history correctly does nothing, rather than making
you press undo for a move that never happened.

WHY IT DOES NOT SURVIVE CLOSING THE APP
---------------------------------------
Because it is a list in memory, and that is deliberate. Undo is for "that was
not what I meant", which is a feeling that lasts about ten seconds. A history
that outlived the program would be a different feature with different
questions to answer, like what happens when you undo past a change made on
your other computer. Saved files are the long-term safety net; this is the
short-term one.
"""


# How many steps back you can go. A hundred is more than anyone reaches for in
# one sitting, and at a few kilobytes each it is not worth being cleverer.
DEFAULT_LIMIT = 100


class Step:
    """One remembered state, and which screen the change happened on.

    The screen is carried along so undo can take you to what it is about to
    change. Reverting something on a screen you cannot see is how undo loses
    people's trust: the safest thing it can do is happen in front of you.
    """

    def __init__(self, snapshot, section):
        self.snapshot = snapshot
        self.section = section


class History:
    """The undo and redo stacks for one open profile.

    Knows nothing about widgets or files. It is handed snapshots and hands
    them back, which is what makes it testable without starting a window.

    `current` is the state as of the last recorded change. It is the hinge the
    whole thing turns on: when a new change arrives, `current` is by definition
    what things looked like BEFORE it, so that is what gets pushed.
    """

    def __init__(self, limit=DEFAULT_LIMIT):
        self.limit = limit
        self.current = None
        self._undo = []
        self._redo = []

    # -- setting up ---------------------------------------------------------

    def start(self, snapshot):
        """Begin a fresh history at this state. Throws away anything before.

        Called when a profile is opened. Each profile gets its own history and
        no profile can be undone into another one.
        """
        self.current = snapshot
        self._undo = []
        self._redo = []

    def clear(self):
        self.start(None)

    # -- recording ----------------------------------------------------------

    def record(self, snapshot, section):
        """Something changed. Remember what things looked like before it.

        Returns True if a step was actually added. Nothing is added when the
        snapshot is identical to the current one, which happens more than you
        would think: repainting, reselecting, and setting a value to what it
        already was all report a change without making one.
        """
        if self.current is None:
            self.current = snapshot
            return False

        if snapshot == self.current:
            return False

        self._undo.append(Step(self.current, section))
        self.current = snapshot

        # A new change makes the redo branch unreachable. This is the standard
        # behavior everywhere and it is worth being clear why: after going back
        # three steps and then editing, "forward" no longer has one meaning.
        self._redo = []

        # Drop the oldest, not the newest. Running out of history should cost
        # you the changes you have stopped thinking about.
        while len(self._undo) > self.limit:
            self._undo.pop(0)

        return True

    # -- going back and forward ---------------------------------------------

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        """Step back. Returns the Step to restore, or None if there is none.

        The Step's `section` is where the change being undone happened, which
        is where the caller should be looking when it lands.
        """
        if not self._undo:
            return None

        step = self._undo.pop()
        self._redo.append(Step(self.current, step.section))
        self.current = step.snapshot
        return step

    def redo(self):
        """Step forward again. The exact mirror of undo."""
        if not self._redo:
            return None

        step = self._redo.pop()
        self._undo.append(Step(self.current, step.section))
        self.current = step.snapshot
        return step

    # -- for the buttons ----------------------------------------------------

    def depth(self):
        """(steps back available, steps forward available)."""
        return (len(self._undo), len(self._redo))

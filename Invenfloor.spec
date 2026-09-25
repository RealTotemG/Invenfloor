# -*- mode: python ; coding: utf-8 -*-
"""
Invenfloor.spec
===============

The build recipe. Run it with:

    pyinstaller Invenfloor.spec

or double-click build.bat, which does that plus the tidying up around it.

This file is committed on purpose. PyInstaller can guess a build from a bare
`pyinstaller main.py`, but then every decision below lives in somebody's
command history instead of in the repository, and the next build is a
different build. Written once, it means releasing is one command forever.

WHAT COMES OUT
--------------
A folder, `dist/Invenfloor/`, with `Invenfloor.exe` in it. Zip the folder and
that is the release.

A folder rather than a single file, for two reasons. A one-file build unpacks
its whole self into a temp directory on every launch, which is a two or three
second wait before anything appears, every single time. And when something
does go wrong, a folder can be looked inside.

WHERE THE SAVE FILES GO
-----------------------
Not in here. `storage.data_folder()` notices `sys.frozen` and switches to
%APPDATA%\\InventoryApp\\data, so the inventory lives with the user's other
application data rather than next to the executable. That matters: a folder
under Program Files is not writable, and a one-file build's own folder is
deleted on exit. Either would lose the lot.
"""

import os

import PySide6

# --- which Qt to carry -------------------------------------------------------
# The app imports three Qt modules. PySide6 ships around sixty, including a
# whole web browser engine, a 3D renderer and a multimedia stack, none of
# which this app has ever heard of. Carrying them is the difference between a
# folder you can attach to an email and one you cannot.
#
# This is worked out from the installed PySide6 rather than written as a list
# by hand, so a PySide6 update that adds modules does not quietly start
# shipping them.
KEEP = {"QtCore", "QtGui", "QtWidgets"}

_pyside = os.path.dirname(PySide6.__file__)
_shipped = {name.split(".")[0] for name in os.listdir(_pyside)
            if name.startswith("Qt")
            and name.endswith((".pyi", ".pyd", ".so", ".abi3.so"))}
EXCLUDED_QT = sorted(f"PySide6.{name}" for name in _shipped - KEEP)

# Things a normal Python install has that a desktop app does not need. Left
# in, they add tens of megabytes and, in tkinter's case, a second GUI toolkit
# sitting unused beside the one actually being used.
EXCLUDED_PYTHON = ["tkinter", "unittest", "pydoc", "doctest", "test",
                   "lib2to3", "pdb", "setuptools", "pip"]

# ON THE SIZE THIS STILL COMES TO
# -------------------------------
# Around 160MB. Most of what is left is Qt itself and cannot be dropped from
# up here: the excludes above remove Python modules, and PyInstaller then
# stops carrying the Qt libraries that only those modules used. A few large
# Qt libraries survive anyway because something still links them.
#
# They CAN be filtered out by hand afterwards, by walking a.binaries and
# dropping entries by name. That is deliberately not done here. Qt loads some
# of its own libraries at runtime rather than linking them, so a library that
# looks unused can turn out to be the one the file dialog wanted, and the
# failure shows up as a crash on somebody else's machine rather than as a
# build error on yours. If the size ever genuinely matters, that is the thread
# to pull, and it needs testing on the machine the build is for.


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # No data files. Every color, size and font in this app is in theme.py as
    # Python, and there are no images, no .qss and no fonts to carry, which is
    # a packaging benefit of a decision made for other reasons entirely.
    datas=[],
    # Nothing is imported dynamically anywhere in the app, so PyInstaller's
    # own scan finds all of it. If that ever changes, the module that gets
    # imported by name goes here or the build will start fine and then fail
    # at the moment somebody opens that screen.
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_QT + EXCLUDED_PYTHON,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Invenfloor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is off deliberately, and this is not a size decision.
    # Compressed executables look exactly like the packing that actual malware
    # uses to hide itself, so turning UPX on measurably increases how often
    # Windows Defender and the scanners on VirusTotal flag the build. An
    # unsigned PyInstaller executable already has enough of that problem.
    upx=False,
    # False means no console window. Leave it True and a black terminal opens
    # behind the app on every launch and sits there until it is closed, which
    # looks broken to anyone who did not write it.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="invenfloor.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Invenfloor",
)

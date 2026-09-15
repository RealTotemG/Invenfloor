"""
storage.py
==========

Reading and writing save files. Nothing in here knows anything about windows
or widgets, and nothing outside this file opens a file.

ONE FILE PER PROFILE
--------------------
Each profile is saved as its own JSON file named after its id:

    data/
        a3f9c1d2.json      <- "Home"
        7b21e0aa.json      <- "Work Locker"

That's deliberate. Deleting a profile is deleting one file, backing one up is
copying one file, and a corrupted save takes only that profile down instead of
everything you own. To list the profiles we simply read every .json in the
folder -- there is no separate index to keep in sync, and therefore no way for
an index to get out of sync.

WHERE THE FOLDER LIVES
----------------------
This is the packaging problem worth knowing about now rather than later.

While you run from source, the data folder sits next to the code, which is
convenient -- you can open the JSON in VS Code and read it.

But once this is built into a .exe, that stops being right. A one-file
PyInstaller build unpacks itself into a temporary folder on every launch, so
"next to the code" becomes a temp directory that Windows deletes on exit --
the user's entire inventory would silently vanish. And even a folder-style
build can't write next to itself if it's installed under Program Files.

So `data_folder()` below checks whether we are running packaged, and if we
are, saves to the user's AppData folder instead. That check costs nothing now
and means you never have to think about it again later.
"""

import json
import os
import sys

from models import Profile

APP_FOLDER_NAME = "InventoryApp"


def data_folder():
    """The folder where profile files are kept. Created if it doesn't exist."""
    if getattr(sys, "frozen", False):
        # sys.frozen is set by PyInstaller, and only exists when packaged.
        # APPDATA is a Windows environment variable pointing at the current
        # user's roaming data folder; it always exists and is always writable.
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, APP_FOLDER_NAME, "data")
    else:
        # Running from source: keep the data beside the code so it's easy to
        # find, inspect and delete while developing.
        here = os.path.dirname(os.path.abspath(__file__))
        folder = os.path.join(here, "data")

    # exist_ok=True means "don't complain if it's already there", which saves
    # writing an if-statement around every call.
    os.makedirs(folder, exist_ok=True)
    return folder


def profile_path(profile_id):
    return os.path.join(data_folder(), f"{profile_id}.json")


def profile_modified(profile_id):
    """When this profile was last written, as a timestamp, or None.

    Taken from the save file itself rather than stored inside the profile,
    because the file system is already keeping this for us and a field in the
    JSON could drift out of step with the file it lives in.
    """
    try:
        return os.path.getmtime(profile_path(profile_id))
    except OSError:
        return None


def load_profiles():
    """Read every profile file and return them as Profile objects.

    A file that fails to parse is skipped rather than crashing the whole app,
    and the reason is printed to the terminal so you can go and look at it.
    """
    profiles = []
    folder = data_folder()

    for filename in sorted(os.listdir(folder)):
        if not filename.endswith(".json"):
            continue
        full_path = os.path.join(folder, filename)
        try:
            with open(full_path, "r", encoding="utf-8") as file:
                profiles.append(Profile.from_dict(json.load(file)))
        except (json.JSONDecodeError, OSError) as error:
            print(f"[storage] Skipped unreadable save file {filename}: {error}")

    # Sort by name so the launcher screen shows a stable, predictable order
    # rather than whatever order the filesystem happened to hand back.
    profiles.sort(key=lambda p: p.name.lower())
    return profiles


def save_profile(profile):
    """Write one profile to disk, replacing whatever was there.

    Writes to a temporary file first and then renames it over the real one.
    That rename is atomic on every OS worth caring about, which means a crash
    or power cut halfway through leaves the previous save intact instead of a
    half-written file. Since this runs on every edit, that safety is worth the
    three extra lines.
    """
    target = profile_path(profile.id)
    temporary = target + ".tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(profile.to_dict(), file, indent=2)

    os.replace(temporary, target)


def delete_profile(profile_id):
    """Delete a profile's save file. Silently fine if it was already gone."""
    try:
        os.remove(profile_path(profile_id))
    except FileNotFoundError:
        pass

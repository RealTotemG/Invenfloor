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

WHAT SURVIVES A BAD DAY
-----------------------
Undo only lasts as long as the program is open, which is what was asked for.
That leaves a gap: close the app and yesterday's mistake is permanent. Three
things fill it, and they answer three different questions.

*The save itself cannot be caught half-finished.* Every write goes to a
temporary file, is flushed all the way down to the disk, and is then renamed
over the real one. A rename is atomic, so there is no instant at which the
real file holds half a profile. A crash leaves you either the old file or the
new one, never a blend.

*The previous save is kept as a .bak.* That is the "I just did something
stupid and closed the window" file. It costs nothing, because it is a rename
of a file we were about to overwrite anyway rather than a copy.

*The state at the start of each of the last ten days you used the app is kept
under backups/.* That is the "I deleted a floor last week" file.

That last one is per DAY rather than per save on purpose, and the reason is
worth spelling out. Saves are debounced at half a second, so a ten-deep
per-save history would cover about five seconds and would cheerfully fill
itself with ten copies of the very mistake you are trying to walk back. A day
is the unit that matches how people actually notice something is missing.

Loading knows about all of this. A profile file that will not parse is moved
aside rather than deleted, the newest backup that does parse takes its place,
and the caller is told what happened so it can say so out loud instead of a
profile quietly going missing from the launcher.
"""

import datetime
import glob
import json
import os
import shutil
import sys
from dataclasses import dataclass

from models import Profile

APP_FOLDER_NAME = "InventoryApp"
BACKUPS_FOLDER_NAME = "backups"

# How many daily snapshots to keep per profile. Ten days of use, not ten
# calendar days: a fortnight away from the app doesn't cost you any history.
DAYS_KEPT = 10


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


def backups_folder():
    """Where the dated snapshots live. A subfolder, so listing the data folder
    for profiles never trips over them."""
    folder = os.path.join(data_folder(), BACKUPS_FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    return folder


def profile_path(profile_id):
    return os.path.join(data_folder(), f"{profile_id}.json")


def previous_path(profile_id):
    """The save before the current one."""
    return profile_path(profile_id) + ".bak"


def daily_path(profile_id, day):
    """A dated snapshot. The date goes in the name in ISO order (2026-09-20)
    so that sorting the names alphabetically also sorts them by date."""
    return os.path.join(backups_folder(), f"{profile_id}-{day}.json")


def today():
    """Today, as a string. Its own function so a test can stand somewhere
    else in time without waiting a day to find out if this works."""
    return datetime.date.today().isoformat()


def daily_backups(profile_id):
    """Every dated snapshot for this profile, newest first."""
    pattern = os.path.join(backups_folder(), f"{profile_id}-*.json")
    return sorted(glob.glob(pattern), reverse=True)


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


# ---------------------------------------------------------------------------
# WRITING
# ---------------------------------------------------------------------------

def save_profile(profile):
    """Write one profile to disk, keeping what was there before.

    The order of the three steps matters and is not the obvious one:

    1. Take today's snapshot FIRST, while the old file is still the live one.
       A snapshot taken after the write would hold the new state, which is not
       a backup of anything.
    2. Write the new content to a temporary file and flush it all the way to
       the disk before going near the real one.
    3. Rename the old file to .bak, then rename the temporary file into its
       place. Both renames are atomic.

    There is a sliver of time between those last two renames where the real
    file does not exist. A crash landing exactly there leaves the content
    safe in .bak, and loading looks there, so the window is covered rather
    than merely small.
    """
    target = profile_path(profile.id)
    temporary = target + ".tmp"

    _keep_todays_snapshot(profile.id)

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(profile.to_dict(), file, indent=2)
        # Without these two lines the rename below can land while the contents
        # are still sitting in a buffer, and a power cut then leaves a
        # perfectly named, perfectly empty save file. Atomic is not the same
        # thing as durable, and this is the difference.
        file.flush()
        os.fsync(file.fileno())

    if os.path.exists(target):
        os.replace(target, previous_path(profile.id))

    os.replace(temporary, target)


def _keep_todays_snapshot(profile_id):
    """Copy the live file into backups/ once per day, then prune old ones.

    Called before every save and does nothing on all but the first save of a
    day, so the cost is one os.path.exists on the other few thousand.
    """
    live = profile_path(profile_id)
    if not os.path.exists(live):
        return                      # nothing saved yet, nothing to preserve

    kept = daily_path(profile_id, today())
    if os.path.exists(kept):
        return                      # already have today's

    # copy2 rather than copy so the snapshot carries the modification time of
    # the save it came from, which is the useful thing to see in a file
    # listing when you are deciding which one to go back to.
    shutil.copy2(live, kept)
    _prune_snapshots(profile_id)


def _prune_snapshots(profile_id):
    """Keep the newest DAYS_KEPT snapshots for this profile, drop the rest."""
    for stale in daily_backups(profile_id)[DAYS_KEPT:]:
        try:
            os.remove(stale)
        except OSError:
            # A backup we cannot delete is untidy, not dangerous. Never let
            # housekeeping be the thing that stops a save from finishing.
            pass


# ---------------------------------------------------------------------------
# READING
# ---------------------------------------------------------------------------

@dataclass
class Recovery:
    """A profile that would not load from its own file, and what we did."""
    profile_name: str
    came_from: str          # a phrase for a human: "the previous save"
    broken_file: str        # where the unreadable one was put, so it can be seen


def load_profiles():
    """Read every profile file and return them as Profile objects.

    What almost every caller wants. If you also need to know whether anything
    had to be rescued on the way in, call load_profiles_and_recoveries.
    """
    profiles, _ = load_profiles_and_recoveries()
    return profiles


def load_profiles_and_recoveries():
    """Every profile, plus a Recovery for each one that needed rescuing."""
    profiles = []
    recoveries = []
    folder = data_folder()

    for filename in sorted(os.listdir(folder)):
        # .bak and .tmp files end in those, not in .json, so this one test
        # already keeps them out. So does the backups/ subfolder.
        if not filename.endswith(".json"):
            continue

        profile_id = filename[:-len(".json")]
        profile, recovery = _load_one(profile_id)
        if profile is None:
            continue
        profiles.append(profile)
        if recovery is not None:
            recovery.profile_name = profile.name
            recoveries.append(recovery)

    # Sort by name so the launcher screen shows a stable, predictable order
    # rather than whatever order the filesystem happened to hand back.
    profiles.sort(key=lambda p: p.name.lower())
    return profiles, recoveries


def _load_one(profile_id):
    """Read one profile, falling back through its backups.

    Returns (profile, recovery). The profile is None if nothing at all could
    be read. The recovery is None in the ordinary case where the file was
    fine, which is almost always.
    """
    live = profile_path(profile_id)

    profile = _read(live)
    if profile is not None:
        return profile, None

    for path, description in _fallbacks(profile_id):
        profile = _read(path)
        if profile is None:
            continue

        # The broken file has to move out of the way, and this is not just
        # tidiness. Leaving it in place would mean the next save renames the
        # CORRUPT file over .bak, destroying the very backup we just read
        # from. Setting it aside keeps it as evidence and breaks that chain.
        broken = _set_aside(live)
        shutil.copy2(path, live)
        return profile, Recovery(profile_name="", came_from=description,
                                 broken_file=broken)

    return None, None


def _fallbacks(profile_id):
    """Everywhere worth looking when the real file is unreadable, best first.

    The previous save comes before the dated snapshots because it is newer
    than all of them: a snapshot is the state at the START of a day, and .bak
    is one save ago.
    """
    places = [(previous_path(profile_id), "the previous save")]
    for path in daily_backups(profile_id):
        # "<id>-2026-09-20.json" -> "2026-09-20"
        day = os.path.basename(path)[len(profile_id) + 1:-len(".json")]
        places.append((path, f"the backup from {day}"))
    return places


def _read(path):
    """Load a Profile from one file, or None if that file is no good.

    The catch is deliberately wide. A save file is not trusted input in the
    security sense, but it is a file on a disk that can be truncated by a
    power cut, edited by a curious owner in VS Code, or synced badly by
    OneDrive, and every one of those produces a different exception. The
    alternative to catching them all here is the program failing to start,
    which is a worse answer to every one of those situations.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, ValueError) as error:
        print(f"[storage] Could not read {os.path.basename(path)}: {error}")
        return None

    if not _looks_like_a_profile(raw):
        print(f"[storage] {os.path.basename(path)} is not a profile file")
        return None

    try:
        return Profile.from_dict(raw)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        print(f"[storage] Could not read {os.path.basename(path)}: {error}")
        return None


def _looks_like_a_profile(raw):
    """Is this parsed JSON something we wrote?

    This test is on the raw dictionary rather than on the Profile that comes
    out of from_dict, and that distinction is the whole point.

    from_dict is forgiving by design: every field is read with a default so
    that adding a field never breaks an older save. Carried to its end that
    means from_dict will happily turn {"hello": "world"} into a profile named
    "Untitled" with a freshly minted id -- a blank that looks real enough to
    pass any test applied to the object afterwards. Ask it to read a grocery
    list and it hands you an empty inventory rather than an error.

    Which would be merely odd, except for what happens next: a blank that
    loads is a blank that never triggers recovery, so a garbled file would
    quietly replace a real profile in the launcher and the backup sitting
    right beside it would never be opened.

    So the gate belongs here, before from_dict, and it asks the one question
    from_dict cannot: did the file itself carry these fields, or are we
    looking at defaults? Every profile this program has ever written has both
    an id and a floors list, including the very first version of the format.
    """
    return (isinstance(raw, dict)
            and isinstance(raw.get("id"), str) and raw["id"]
            and isinstance(raw.get("floors"), list))


def _set_aside(path):
    """Move an unreadable file somewhere harmless and return where it went.

    Never deleted. If a save has gone wrong the broken file is the only
    record of what was in it, and someone who knows JSON can often pick the
    contents back out of it by hand.
    """
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    aside = f"{path}.broken-{stamp}"
    try:
        os.replace(path, aside)
        return aside
    except OSError:
        return path


# ---------------------------------------------------------------------------
# DELETING
# ---------------------------------------------------------------------------

def delete_profile(profile_id):
    """Delete a profile's save file and its .bak. Silently fine if gone.

    The dated snapshots under backups/ are deliberately left alone. Deleting
    the wrong profile is exactly the accident this whole file exists for, and
    a snapshot that outlives its profile costs a few kilobytes.
    """
    for path in (profile_path(profile_id), previous_path(profile_id)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

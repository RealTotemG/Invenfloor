"""
import_test.py
==============

Bringing a profile file in from somewhere else.

WHAT THIS IS GUARDING
---------------------
One thing above all: nothing already on this machine is ever written over.

That sounds like an obvious thing to get right, and it is the easy thing to
get wrong, because of how the feature actually gets used. Somebody exports a
profile on their desktop and imports it on their laptop. The laptop already
has that profile, under the same id, a few edits apart. The naive import
writes the file to <id>.json, which is to say straight over the copy that was
already there, and the laptop's last week of work is gone without a prompt, at
the exact moment its owner thought they were ADDING something.

So the import gives a taken id a fresh one and leaves both profiles on the
launcher. The checks below are mostly about that, and about the cases where
the file should not come in at all: a file from a newer version, a file that
is not a profile, a file that is not even JSON.

    python import_test.py
"""
import json
import os
import shutil
import sys
import tempfile

import models
import storage


PASSED = []
FAILED = []


def check(label, ok, why=""):
    (PASSED if ok else FAILED).append(label)
    print(f"{'  ok  ' if ok else ' FAIL '} {label}")
    if not ok and why:
        print(f"        {why}")


class InTempFolder:
    """Point storage at an empty folder for the duration of one check."""

    def __enter__(self):
        self.folder = tempfile.mkdtemp(prefix="invenfloor-import-")
        self.elsewhere = tempfile.mkdtemp(prefix="invenfloor-elsewhere-")
        self.original = storage.data_folder
        storage.data_folder = lambda: self.folder
        os.makedirs(os.path.join(self.folder, storage.BACKUPS_FOLDER_NAME),
                    exist_ok=True)
        return self

    def __exit__(self, *rest):
        storage.data_folder = self.original
        shutil.rmtree(self.folder, ignore_errors=True)
        shutil.rmtree(self.elsewhere, ignore_errors=True)

    def incoming(self, profile, filename="incoming.json", **extra):
        """Write a profile file OUTSIDE the save folder, the way a real one
        arrives: off a USB stick, out of a download, synced from another
        machine."""
        raw = profile.to_dict()
        raw.update(extra)
        path = os.path.join(self.elsewhere, filename)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(raw, file, indent=2)
        return path

    def junk(self, text, filename="junk.json"):
        path = os.path.join(self.elsewhere, filename)
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)
        return path


def a_profile(profile_id="aaaa0001", name="Home", room_name="Garage"):
    profile = models.Profile(id=profile_id, name=name)
    floor = models.Floor(id="f1", name="Ground")
    room = models.Room(id="r1", name=room_name,
                       points=models.rectangle_points(400, 300))
    room.containers = [models.Container(id="c1", name="Racking", x=10, y=10,
                                        w=100, h=50, tier_count=3)]
    floor.rooms = [room]
    profile.floors = [floor]
    profile.items = [models.Item(id="i1", name="Sockets")]
    return profile


def refused(work):
    """Run something that should refuse, and give back the reason it gave."""
    try:
        work()
    except storage.CannotImport as problem:
        return str(problem)
    return None


def main():
    # -- the case the whole thing exists for --------------------------------
    # The same profile, from another machine, a few edits apart. Same id.
    with InTempFolder() as temp:
        here = a_profile(name="Home", room_name="Garage")
        storage.save_profile(here)
        mine = json.load(open(storage.profile_path("aaaa0001"),
                              encoding="utf-8"))

        theirs = a_profile(name="Home", room_name="Workshop")
        theirs.items.append(models.Item(id="i2", name="Drill bits"))
        arriving = temp.incoming(theirs)

        added = storage.import_profile(arriving, storage.load_profiles())

        check("a profile arriving under a taken id is given a new one",
              added.id != "aaaa0001", added.id)
        check("and the profile that was already here is untouched",
              json.load(open(storage.profile_path("aaaa0001"),
                             encoding="utf-8")) == mine)
        check("both are on the launcher afterwards",
              len(storage.load_profiles()) == 2,
              str([p.name for p in storage.load_profiles()]))
        check("and they can be told apart by name",
              sorted(p.name for p in storage.load_profiles())
              == ["Home", "Home (imported)"],
              str(sorted(p.name for p in storage.load_profiles())))
        check("the imported one kept its own contents, not the other one's",
              [r.name for f in added.floors for r in f.rooms] == ["Workshop"]
              and len(added.items) == 2,
              str([r.name for f in added.floors for r in f.rooms]))
        check("and the file it came from was not moved or changed",
              os.path.exists(arriving)
              and json.load(open(arriving, encoding="utf-8"))["id"]
              == "aaaa0001")

    # -- a file whose id is free keeps it -----------------------------------
    with InTempFolder() as temp:
        storage.save_profile(a_profile("aaaa0001", "Home"))
        arriving = temp.incoming(a_profile("bbbb0002", "Shop"))

        added = storage.import_profile(arriving, storage.load_profiles())
        check("an id nobody is using is kept rather than replaced",
              added.id == "bbbb0002", added.id)
        check("and a name nobody is using is kept too",
              added.name == "Shop", added.name)

    # -- the id that is taken by a file the app REFUSED to open -------------
    # This is the nasty one. A profile from a newer version sits there
    # unopened, so it is not in the list of profiles, so anything checking
    # that list thinks its id is free. Overwriting the one file the program
    # already said it would not touch would be a poor way to end.
    with InTempFolder() as temp:
        raw = a_profile("cccc0003", "From the future").to_dict()
        raw["schema"] = models.SCHEMA + 1
        raw["lighting"] = "warm"
        with open(storage.profile_path("cccc0003"), "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)
        before = open(storage.profile_path("cccc0003"), encoding="utf-8").read()

        profiles, _, refusals = storage.load_profiles_and_problems()
        check("the future file is there and was refused, so its id looks free",
              not profiles and len(refusals) == 1)

        arriving = temp.incoming(a_profile("cccc0003", "Mine"))
        added = storage.import_profile(arriving, profiles)
        check("importing over a refused file does not touch it",
              open(storage.profile_path("cccc0003"),
                   encoding="utf-8").read() == before)
        check("and the import went somewhere else entirely",
              added.id != "cccc0003", added.id)

    # -- the same file twice, which people do ------------------------------
    with InTempFolder() as temp:
        arriving = temp.incoming(a_profile("dddd0004", "Store"))
        first = storage.import_profile(arriving, storage.load_profiles())
        second = storage.import_profile(arriving, storage.load_profiles())
        third = storage.import_profile(arriving, storage.load_profiles())

        check("importing the same file three times makes three profiles",
              len({first.id, second.id, third.id}) == 3)
        # Sorted as a set, because sorting these as text puts "(imported 2)"
        # in front of "(imported)": a space sorts before a bracket, and that
        # has nothing to do with what is being checked here.
        check("and all three have names that can be told apart",
              {p.name for p in storage.load_profiles()}
              == {"Store", "Store (imported)", "Store (imported 2)"},
              str(sorted(p.name for p in storage.load_profiles())))

    # -- what should not come in at all -------------------------------------
    with InTempFolder() as temp:
        future = temp.incoming(a_profile("eeee0005", "Newer"),
                               schema=models.SCHEMA + 1, lighting="warm")
        why = refused(lambda: storage.import_profile(future, []))
        check("a file from a newer version is refused",
              why is not None and "newer version" in why, str(why))
        check("and nothing was written to the save folder",
              [n for n in os.listdir(temp.folder)
               if n != storage.BACKUPS_FOLDER_NAME] == [],
              str(os.listdir(temp.folder)))

        why = refused(lambda: storage.import_profile(
            temp.junk("{ not json at all"), []))
        check("a file that is not JSON is refused, and said to be",
              why is not None and "JSON" in why, str(why))

        why = refused(lambda: storage.import_profile(
            temp.junk('{"shopping": ["milk", "bread"]}', "list.json"), []))
        check("JSON that is not a profile is refused, and said to be",
              why is not None and "not an Invenfloor profile" in why, str(why))

        why = refused(lambda: storage.import_profile(
            os.path.join(temp.elsewhere, "nothing-here.json"), []))
        check("a file that is not there is refused without crashing",
              why is not None and "could not be opened" in why, str(why))

        check("and after all of that the save folder is still empty",
              [n for n in os.listdir(temp.folder)
               if n != storage.BACKUPS_FOLDER_NAME] == [],
              str(os.listdir(temp.folder)))

    # -- an older file is migrated on the way in, like any other load -------
    with InTempFolder() as temp:
        old = a_profile("ffff0006", "Ancient").to_dict()
        old["schema"] = 1
        path = os.path.join(temp.elsewhere, "old.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(old, file)

        added = storage.import_profile(path, [])
        check("an older file comes in and is written back at this format",
              json.load(open(storage.profile_path(added.id),
                             encoding="utf-8")).get("schema") == models.SCHEMA)
        check("and it loads afterwards like anything else",
              [p.name for p in storage.load_profiles()] == ["Ancient"],
              str([p.name for p in storage.load_profiles()]))

    # -- a long name does not grow past the cap on the way in ---------------
    with InTempFolder() as temp:
        at_the_limit = "N" * models.NAME_MAX_LENGTH
        storage.save_profile(a_profile("aaaa0001", at_the_limit))
        arriving = temp.incoming(a_profile("bbbb0002", at_the_limit))

        added = storage.import_profile(arriving, storage.load_profiles())
        check("a name already at the length cap is renamed without exceeding it",
              len(added.name) <= models.NAME_MAX_LENGTH
              and added.name != at_the_limit,
              f"{len(added.name)} characters: {added.name}")
        # And it still SAYS imported. Trimming the suffix instead of the name
        # would also come in under the cap and also differ from the original,
        # while losing the one word the rename was for.
        check("and it still says which one is the import",
              "(imported)" in added.name, added.name)

    # -- the naming rule itself, both users of it ---------------------------
    # copy_name and imported_name share their trimming, so a change to one
    # reaches the other. Both get checked here, because the import is what
    # made them share it.
    check("a duplicate counts up rather than repeating itself",
          models.copy_name("Kitchen", ["Kitchen", "Kitchen copy"])
          == "Kitchen copy 2",
          models.copy_name("Kitchen", ["Kitchen", "Kitchen copy"]))
    check("and so does an import",
          models.imported_name("Home", ["Home", "Home (imported)"])
          == "Home (imported 2)",
          models.imported_name("Home", ["Home", "Home (imported)"]))
    check("a copy and an import do not get the same name",
          models.copy_name("Home", ["Home"])
          != models.imported_name("Home", ["Home"]))

    # Duplicating the same room over and over should keep counting, not give
    # up after a couple and start inventing names. Somebody making five
    # shelves from one wants "copy 5", not six random characters.
    taken = ["Shelf"]
    for _ in range(8):
        taken.append(models.copy_name("Shelf", taken))
    check("counting keeps going for as long as anyone would actually go",
          taken[-1] == "Shelf copy 8", str(taken[-3:]))

    at_the_limit = "N" * models.NAME_MAX_LENGTH
    for label, renamed in (("a copy", models.copy_name(at_the_limit, [at_the_limit])),
                           ("an import", models.imported_name(at_the_limit,
                                                              [at_the_limit]))):
        check(f"{label} of a name at the cap keeps the suffix and loses the "
              f"end of the name instead",
              renamed.endswith("copy") or renamed.endswith("(imported)"),
              renamed)
        check(f"{label} of a name at the cap is still within the cap",
              len(renamed) == models.NAME_MAX_LENGTH,
              f"{len(renamed)} characters")

    # The loop that picks these has one way out, finding a free name, so it
    # is worth knowing it cannot be made to spin. A thousand taken names is
    # past where the counting gives up.
    crowded = {f"Kitchen copy {n}" for n in range(1, 1200)} | {"Kitchen copy"}
    fallback = models.copy_name("Kitchen", crowded)
    check("with every counted name taken it still returns, and returns a free one",
          fallback.lower() not in {name.lower() for name in crowded}
          and len(fallback) <= models.NAME_MAX_LENGTH,
          fallback)

    print()
    if FAILED:
        print(f"{len(FAILED)} of {len(PASSED) + len(FAILED)} FAILED")
        return 1
    print(f"all {len(PASSED)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

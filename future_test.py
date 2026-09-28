"""
future_test.py
==============

What happens to a save file written by a newer version of Invenfloor.

THE BUG THIS EXISTS FOR
-----------------------
migrate() only ever moves a file forward, so a file from the future passes
through it untouched. Profile.from_dict then reads the fields it knows and
drops the rest, because from_dict is forgiving on purpose: that is what lets
an older file load at all.

Nothing has gone wrong yet. What goes wrong is the NEXT SAVE, which writes
that flattened profile back over the real one, and now the newer version's
work is gone for good. Silent, permanent, and it only happens on whichever
machine is one update behind, which is the machine nobody is looking at.

The round trip is the whole test. Loading a future file and finding it
slightly wrong is not the failure; loading it, saving it, and finding the file
on disk has lost something is.

    python future_test.py
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
    mark = "  ok  " if ok else " FAIL "
    print(f"{mark} {label}")
    if not ok and why:
        print(f"        {why}")


class InTempFolder:
    """Point storage at an empty folder for the duration of one check.

    storage.data_folder() is the one piece of global state in the whole
    module, so swapping it is all it takes to keep a test away from real
    profiles.
    """

    def __enter__(self):
        self.folder = tempfile.mkdtemp(prefix="invenfloor-check-")
        self.original = storage.data_folder
        storage.data_folder = lambda: self.folder
        os.makedirs(os.path.join(self.folder, storage.BACKUPS_FOLDER_NAME),
                    exist_ok=True)
        return self.folder

    def __exit__(self, *rest):
        storage.data_folder = self.original
        shutil.rmtree(self.folder, ignore_errors=True)


def a_profile(profile_id="aaaa0001", name="Home"):
    profile = models.Profile(id=profile_id, name=name)
    floor = models.Floor(id="f1", name="Ground")
    room = models.Room(id="r1", name="Garage",
                       points=models.rectangle_points(400, 300))
    room.containers = [models.Container(id="c1", name="Racking", x=10, y=10,
                                        w=100, h=50, tier_count=3)]
    floor.rooms = [room]
    profile.floors = [floor]
    profile.items = [models.Item(id="i1", name="Sockets")]
    return profile


def from_the_future(folder, profile_id="aaaa0001"):
    """Write a save file that claims a format this build has never seen.

    Given extra fields at every level, the way a real newer version would:
    one on the profile, one on a room, one on a container, and a whole item
    property. Every one of them is something from_dict would quietly drop.
    """
    raw = a_profile(profile_id).to_dict()
    raw["schema"] = models.SCHEMA + 1
    raw["lighting"] = "warm"
    raw["floors"][0]["rooms"][0]["ceiling_height"] = 240
    raw["floors"][0]["rooms"][0]["containers"][0]["locked_shelves"] = [1, 2]
    raw["items"][0]["barcode"] = "5012345678900"

    path = os.path.join(folder, f"{profile_id}.json")
    with open(path, "w", encoding="utf-8") as file:
        json.dump(raw, file, indent=2)
    return path, raw


def main():
    # -- the bug itself -----------------------------------------------------
    with InTempFolder() as folder:
        path, written = from_the_future(folder)
        before = open(path, encoding="utf-8").read()

        profiles, recoveries, refusals = storage.load_profiles_and_problems()

        check("a profile from the future is not opened",
              not profiles, f"{len(profiles)} profiles came back")
        check("and it is reported rather than silently missing",
              len(refusals) == 1, f"{len(refusals)} refusals")
        check("the report says which profile",
              refusals and refusals[0].profile_name == "Home",
              refusals[0].profile_name if refusals else "")
        check("and says why, in words somebody could act on",
              refusals and "newer version" in refusals[0].why
              and str(models.SCHEMA + 1) in refusals[0].why,
              refusals[0].why if refusals else "")
        check("nothing was rescued, because nothing was broken",
              not recoveries)

        check("the file on disk is untouched",
              open(path, encoding="utf-8").read() == before)
        check("and no backup, .bak or set-aside copy was made of it",
              sorted(os.listdir(folder)) == [f"aaaa0001.json",
                                             storage.BACKUPS_FOLDER_NAME],
              str(sorted(os.listdir(folder))))

    # -- the round trip, which is the part that used to lose the data -------
    with InTempFolder() as folder:
        path, written = from_the_future(folder)

        # What the old code did: load it, then save it again, the way the app
        # does after any edit at all.
        loaded = storage._read(path)
        check("the forgiving loader can still be made to read it, which is "
              "why the check above has to be in front of it",
              loaded is not None)

        if loaded is not None:
            storage.save_profile(loaded)
            after = json.load(open(path, encoding="utf-8"))
            lost = [key for key in ["lighting"] if key not in after]
            check("saving a future profile WOULD have dropped its new fields",
                  bool(lost),
                  "if this ever passes, from_dict has stopped being forgiving "
                  "and the guard may no longer be needed")

        # And now the same thing through the real front door, which refuses.
        with open(path, "w", encoding="utf-8") as file:
            json.dump(written, file, indent=2)
        profiles, _, _ = storage.load_profiles_and_problems()
        for profile in profiles:
            storage.save_profile(profile)
        after = json.load(open(path, encoding="utf-8"))
        check("going in the front door, every new field is still there",
              after.get("lighting") == "warm"
              and after["floors"][0]["rooms"][0].get("ceiling_height") == 240
              and after["floors"][0]["rooms"][0]["containers"][0]
                       .get("locked_shelves") == [1, 2]
              and after["items"][0].get("barcode") == "5012345678900",
              json.dumps(after)[:200])
        check("and the format number was not rewritten either",
              after.get("schema") == models.SCHEMA + 1,
              str(after.get("schema")))

    # -- a future profile does not poison the ones beside it ----------------
    with InTempFolder() as folder:
        from_the_future(folder, "aaaa0001")
        storage.save_profile(a_profile("bbbb0002", "Work"))

        profiles, _, refusals = storage.load_profiles_and_problems()
        check("the other profiles still load",
              [p.name for p in profiles] == ["Work"],
              str([p.name for p in profiles]))
        check("and the refusal is still reported alongside them",
              len(refusals) == 1)

    # -- and the ordinary cases still behave --------------------------------
    with InTempFolder() as folder:
        storage.save_profile(a_profile("cccc0003", "Fine"))
        profiles, recoveries, refusals = storage.load_profiles_and_problems()
        check("an ordinary profile loads with nothing to report",
              [p.name for p in profiles] == ["Fine"]
              and not recoveries and not refusals)

    with InTempFolder() as folder:
        profile = a_profile("dddd0004", "Wrecked")
        storage.save_profile(profile)
        profile.name = "Wrecked later"
        storage.save_profile(profile)          # now there is a .bak
        with open(storage.profile_path("dddd0004"), "w", encoding="utf-8") as f:
            f.write("{ this is not json")

        profiles, recoveries, refusals = storage.load_profiles_and_problems()
        check("a genuinely broken file is still rescued from its backup",
              [p.name for p in profiles] == ["Wrecked"]
              and len(recoveries) == 1
              and recoveries[0].came_from == "the previous save",
              str([p.name for p in profiles]))
        check("and a rescue is not reported as a refusal", not refusals)
        check("the broken file is kept, not thrown away",
              any(".broken-" in name for name in os.listdir(folder)),
              str(sorted(os.listdir(folder))))

        # The part that is easy to leave out. If the corrupt file is still
        # sitting at the live path, the next save renames IT over .bak, and
        # the backup we just rescued from is gone. So save once and look at
        # what .bak holds afterwards.
        storage.save_profile(profiles[0])
        again, _, _ = storage.load_profiles_and_problems()
        check("and one more save does not destroy the backup it came from",
              json.load(open(storage.previous_path("dddd0004"),
                             encoding="utf-8")).get("name") == "Wrecked",
              open(storage.previous_path("dddd0004"), encoding="utf-8")
                  .read()[:80])
        check("so the profile still loads cleanly the next time round",
              [p.name for p in again] == ["Wrecked"],
              str([p.name for p in again]))

    # -- a broken file whose BACKUP is the one from the future --------------
    # The live file is wrecked and the .bak is the newer version's work. This
    # is the case where getting it wrong writes rather than just reads: the
    # rescue copies the flattened backup straight over the live file.
    with InTempFolder() as folder:
        _, written = from_the_future(folder, "ffff0006")
        shutil.copy2(storage.profile_path("ffff0006"),
                     storage.previous_path("ffff0006"))
        with open(storage.profile_path("ffff0006"), "w", encoding="utf-8") as f:
            f.write("{ wrecked")
        bak_before = open(storage.previous_path("ffff0006"),
                          encoding="utf-8").read()

        profiles, recoveries, refusals = storage.load_profiles_and_problems()
        check("a backup from the future is not used as a rescue",
              not profiles and not recoveries and len(refusals) == 1,
              f"{len(profiles)} profiles, {len(recoveries)} recoveries, "
              f"{len(refusals)} refusals")
        check("the refusal names the backup as the newer one",
              refusals and "previous save" in refusals[0].why
              and "newer version" in refusals[0].why,
              refusals[0].why if refusals else "")
        check("and the future backup is still sitting there unchanged",
              open(storage.previous_path("ffff0006"),
                   encoding="utf-8").read() == bak_before)

    # -- and an older backup is not a way around it -------------------------
    # The trap: .bak is from the future, but a dated snapshot from before the
    # update still reads fine. Recovering from that one looks like a success,
    # and then the very next save renames the live file over the future .bak.
    with InTempFolder() as folder:
        snapshot = os.path.join(folder, storage.BACKUPS_FOLDER_NAME,
                                "gggg0007-2026-01-01.json")
        with open(snapshot, "w", encoding="utf-8") as file:
            json.dump(a_profile("gggg0007", "Older").to_dict(), file)

        _, written = from_the_future(folder, "gggg0007")
        shutil.copy2(storage.profile_path("gggg0007"),
                     storage.previous_path("gggg0007"))
        with open(storage.profile_path("gggg0007"), "w", encoding="utf-8") as f:
            f.write("{ wrecked")

        profiles, recoveries, refusals = storage.load_profiles_and_problems()
        check("an older readable backup is not used to step around it",
              not profiles and not recoveries and len(refusals) == 1,
              f"recovered {[p.name for p in profiles]}")
        check("and the future backup survived that too",
              json.load(open(storage.previous_path("gggg0007"),
                             encoding="utf-8")).get("lighting") == "warm")

    with InTempFolder() as folder:
        with open(os.path.join(folder, "eeee0005.json"), "w",
                  encoding="utf-8") as file:
            file.write("{ this is not json either")
        profiles, recoveries, refusals = storage.load_profiles_and_problems()
        check("a broken file with no backup at all is reported, not skipped",
              not profiles and not recoveries and len(refusals) == 1,
              f"{len(refusals)} refusals")
        check("and says the file was left where it was",
              refusals and "left exactly as it was" in refusals[0].why,
              refusals[0].why if refusals else "")

    print()
    if FAILED:
        print(f"{len(FAILED)} of {len(PASSED) + len(FAILED)} FAILED")
        return 1
    print(f"all {len(PASSED)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

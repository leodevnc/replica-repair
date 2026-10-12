"""Deterministic offline partition/recovery demonstration."""

import argparse
import json

from . import Replica, MerkleTree, repair


def demo():
    east, west = Replica("east"), Replica("west")
    for index in range(256):
        east.put(f"document-{index}", f"unchanged fixture {index}")
    east.put("release-note", "initial")
    east.put("retired-note", "obsolete")
    repair(east, west)
    stale = Replica.restore(west.snapshot())

    # Partition: both sides accept edits without seeing the other's changes.
    east.put("release-note", "reviewed by east")
    west.put("release-note", "reviewed by west")
    east.delete("retired-note")
    stats = repair(east, west)
    conflict = east.read("release-note")

    # Replaying a pre-deletion snapshot must not resurrect retired data.
    west.receive(stale.records())
    after_stale = west.read("retired-note")
    east.put("release-note", "combined after reviewing both siblings")
    resolution = repair(east, west)
    repeated = repair(east, west)
    return {"scenario": "synthetic partition, repair, stale replay, explicit resolution",
            "repair": stats, "concurrent_edit": conflict, "stale_replay": after_stale,
            "resolution": resolution, "resolved_value": west.read("release-note"),
            "repeat_repair": repeated, "root": MerkleTree(east).root}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo"], nargs="?", default="demo")
    parser.parse_args()
    print(json.dumps(demo(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

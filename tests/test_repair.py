import itertools
import json
import random
import subprocess
import sys
import unittest

from replica_repair import Replica, Version, MerkleTree, repair, packet, apply_packet, merge_versions
from replica_repair.core import MAX_COUNTER
from replica_repair.merkle import bucket, leaf_digest


class CausalTests(unittest.TestCase):
    def test_initial_read_and_empty_string(self):
        node = Replica("a")
        self.assertEqual(node.read("x")["status"], "missing")
        node.put("x", "")
        self.assertEqual(node.read("x")["status"], "value")

    def test_sequential_write_dominates(self):
        node = Replica("a")
        old = node.put("x", "old")
        new = node.put("x", "new")
        self.assertEqual(merge_versions((old,), (new,)), (new,))

    def test_concurrent_values_survive_until_explicit_resolution(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "left")
        b.put("x", "right")
        repair(a, b)
        self.assertEqual(a.read("x")["status"], "conflict")
        a.put("x", "combined")
        repair(a, b)
        self.assertEqual(b.read("x")["siblings"][0]["value"], "combined")
        self.assertEqual(len(b.siblings("x")), 1)

    def test_delete_dominates_stale_replay(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "old")
        repair(a, b)
        old = b.records()
        a.delete("x")
        repair(a, b)
        b.receive(old)
        self.assertEqual(b.read("x")["status"], "deleted")

    def test_concurrent_delete_edit_is_a_conflict(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "old")
        repair(a, b)
        a.delete("x")
        b.put("x", "new")
        repair(a, b)
        self.assertEqual({v.value for v in a.siblings("x")}, {None, "new"})
        self.assertEqual(b.read("x")["status"], "conflict")

    def test_recreate_after_observed_delete(self):
        a, b = Replica("a"), Replica("b")
        a.delete("x")
        repair(a, b)
        b.put("x", "intentional recreation")
        repair(a, b)
        self.assertEqual(a.read("x")["status"], "value")

    def test_absence_is_not_deletion(self):
        a = Replica("a")
        a.put("x", "retained")
        a.receive({})
        self.assertEqual(a.read("x")["status"], "value")

    def test_same_clock_different_payload_rejected_atomically(self):
        a = Replica("a")
        a.put("x", "original")
        before = a.snapshot()
        with self.assertRaises(ValueError):
            a.receive({"new": [{"clock": {"b": 1}, "value": "valid"}],
                       "x": [{"clock": {"a": 1}, "value": "forged"}]})
        self.assertEqual(a.snapshot(), before)

    def test_merge_laws_on_reachable_histories(self):
        nodes = [Replica(name) for name in ("a", "b", "c")]
        for i, node in enumerate(nodes):
            node.put("x", str(i))
        nodes[0].receive(nodes[1].records())
        nodes[0].put("x", "a after seeing b")
        x, y, z = [node.siblings("x") for node in nodes]
        self.assertEqual(merge_versions(x, x), x)
        self.assertEqual(merge_versions(x, y), merge_versions(y, x))
        self.assertEqual(merge_versions(merge_versions(x, y), z),
                         merge_versions(x, merge_versions(y, z)))

    def test_merge_all_delivery_orders_and_duplicates(self):
        versions = [Replica(name).put("x", name) for name in ("a", "b", "c")]
        roots = set()
        for order in itertools.permutations(versions):
            node = Replica("receiver")
            for v in (*order, *reversed(order)):
                node.receive({"x": [v.as_dict()]})
            roots.add(MerkleTree(node).root)
        self.assertEqual(len(roots), 1)

    def test_snapshot_roundtrip_preserves_counter(self):
        a = Replica("a")
        a.put("x", "1")
        a.delete("x")
        restored = Replica.restore(json.loads(json.dumps(a.snapshot())))
        self.assertEqual(a.snapshot(), restored.snapshot())
        self.assertEqual(dict(restored.put("y", "2").clock)["a"], 3)

    def test_restore_rejects_rolled_back_sequence(self):
        node = Replica("a")
        node.put("x", "1")
        data = node.snapshot()
        data["sequence"] = 0
        with self.assertRaises(ValueError):
            Replica.restore(data)

    def test_counter_exhaustion_leaves_state_unchanged(self):
        node = Replica("a")
        node.sequence = MAX_COUNTER
        before = node.snapshot()
        with self.assertRaises(ValueError):
            node.put("x", "no")
        self.assertEqual(node.snapshot(), before)

    def test_input_validation(self):
        for bad in (True, -1, 0, 1.5, MAX_COUNTER + 1):
            with self.subTest(counter=bad), self.assertRaises(ValueError):
                Version((("a", bad),), "v")
        for bad in ({}, {"clock": {"a": 1}, "value": "v", "extra": 1},
                    {"clock": {"a": 1}, "value": []}, {"clock": {"a": 1}, "value": "x"*4097}):
            with self.subTest(record=repr(bad)[:80]), self.assertRaises(ValueError):
                Version.parse(bad)
        for bad in ("", "with space", 7):
            with self.assertRaises(ValueError):
                Replica(bad)

    def test_key_capacity_is_atomic(self):
        a = Replica("a")
        a.receive({str(i): [{"clock": {"b": 1}, "value": ""}] for i in range(2048)})
        before = a.snapshot()
        with self.assertRaises(ValueError):
            a.put("overflow", "no")
        self.assertEqual(a.snapshot(), before)

    def test_clock_capacity_does_not_silently_trim(self):
        a = Replica("new")
        clock = {f"n{i}": 1 for i in range(32)}
        a.receive({"x": [{"clock": clock, "value": "v"}]})
        before = a.snapshot()
        with self.assertRaises(ValueError):
            a.put("x", "no")
        self.assertEqual(a.snapshot(), before)

    def test_sibling_capacity_preserves_existing_state(self):
        a = Replica("a")
        a.receive({"x": [{"clock": {f"n{i}": 1}, "value": str(i)} for i in range(64)]})
        before = a.snapshot()
        with self.assertRaises(ValueError):
            a.receive({"x": [{"clock": {"another": 1}, "value": "overflow"}]})
        self.assertEqual(a.snapshot(), before)


class MerkleTests(unittest.TestCase):
    def test_equal_roots_compare_once_and_transfer_nothing(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "v")
        repair(a, b)
        stats = repair(a, b)
        self.assertEqual(stats["hash_pairs_compared"], 1)
        self.assertEqual(stats["records_transferred"], 0)
        self.assertEqual(stats["packet_bytes"], 0)

    def test_small_difference_prunes_equal_subtrees(self):
        a, b = Replica("a"), Replica("b")
        for i in range(256):
            a.put(str(i), "base")
        repair(a, b)
        a.put("0", "changed")
        stats = repair(a, b)
        self.assertEqual(stats["different_buckets"], [bucket("0")])
        self.assertEqual(stats["hash_pairs_compared"], 9)
        self.assertLess(stats["records_transferred"], 512)
        self.assertTrue(stats["converged"])

    def test_empty_sided_repair_converges(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "v")
        stats = repair(a, b)
        self.assertTrue(stats["converged"])
        self.assertEqual(stats["full_state_record_count"], 1)
        self.assertEqual(a.records(), b.records())

    def test_hash_includes_tombstone_and_clock(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "same")
        b.put("x", "same")
        self.assertNotEqual(MerkleTree(a).root, MerkleTree(b).root)
        a.delete("x")
        empty = Replica("empty")
        self.assertNotEqual(MerkleTree(a).root, MerkleTree(empty).root)

    def test_partial_delivery_and_replay_converge(self):
        a, b = Replica("a"), Replica("b")
        for i in range(30):
            a.put(str(i), str(i))
        tree = MerkleTree(a)
        packets = [packet(tree, i) for i in range(16)]
        for p in packets[:5]:
            apply_packet(b, p)
        # Interrupted exchange resumes with duplicated, out-of-order packets.
        for p in reversed(packets + packets[:5]):
            apply_packet(b, p)
        self.assertEqual(a.records(), b.records())

    def test_packet_corruption_is_rejected_without_mutation(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "real")
        p = packet(MerkleTree(a), bucket("x"))
        p["records"]["x"][0]["value"] = "changed"
        before = b.snapshot()
        with self.assertRaises(ValueError):
            apply_packet(b, p)
        self.assertEqual(before, b.snapshot())

    def test_wrong_bucket_rejected_even_with_matching_digest(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "v")
        p = packet(MerkleTree(a), bucket("x"))
        p["bucket"] = (p["bucket"] + 1) % 16
        p["digest"] = leaf_digest(p["bucket"], p["records"])
        with self.assertRaises(ValueError):
            apply_packet(b, p)

    def test_packet_is_detached_from_tree(self):
        a = Replica("a")
        a.put("x", "v")
        tree = MerkleTree(a)
        p = packet(tree, bucket("x"))
        p["records"]["x"][0]["clock"]["a"] = 200
        self.assertEqual(packet(tree, bucket("x"))["records"]["x"][0]["clock"]["a"], 1)

    def test_old_packet_cannot_replace_newer_local_edit(self):
        a, b = Replica("a"), Replica("b")
        a.put("x", "base")
        repair(a, b)
        old = packet(MerkleTree(a), bucket("x"))
        b.put("x", "newer")
        apply_packet(b, old)
        self.assertEqual([v.value for v in b.siblings("x")], ["newer"])

    def test_canonical_root_is_independent_of_record_order(self):
        a, b = Replica("a"), Replica("b")
        a.receive({"y": [{"clock": {"b": 1, "a": 2}, "value": "v"}],
                   "x": [{"clock": {"c": 1}, "value": None}]})
        b.receive({"x": [{"clock": {"c": 1}, "value": None}],
                   "y": [{"clock": {"a": 2, "b": 1}, "value": "v"}]})
        self.assertEqual(MerkleTree(a).root, MerkleTree(b).root)

    def test_malformed_packet_is_rejected(self):
        node = Replica("a")
        for data in ({}, {"schema": True, "bucket": 0, "digest": "", "records": {}},
                     {"schema": 1, "bucket": True, "digest": "", "records": {}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                apply_packet(node, data)

    def test_identical_writer_ids_rejected(self):
        with self.assertRaises(ValueError):
            repair(Replica("same"), Replica("same"))

    def test_seeded_partition_histories_converge(self):
        for seed in range(40):
            rng = random.Random(seed)
            nodes = [Replica("a"), Replica("b"), Replica("c")]
            for _ in range(70):
                node = rng.choice(nodes)
                if rng.random() < .3:
                    other = rng.choice([n for n in nodes if n is not node])
                    node.receive(other.records())
                else:
                    key = str(rng.randrange(5))
                    node.put(key, None if rng.random() < .2 else str(rng.randrange(99)))
            expected = Replica("expected")
            for node in nodes:
                expected.receive(node.records())
            # Connected exchanges after writes stop.
            for left, right in [(0, 1), (1, 2), (2, 0), (0, 1)]:
                repair(nodes[left], nodes[right])
            for node in nodes:
                self.assertEqual(node.records(), expected.records(), f"seed {seed}")

    def test_cli_demo_reports_real_mechanism_results(self):
        result = subprocess.run([sys.executable, "-m", "replica_repair", "demo"],
                                capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        self.assertTrue(data["repair"]["converged"])
        self.assertEqual(data["concurrent_edit"]["status"], "conflict")
        self.assertEqual(data["stale_replay"]["status"], "deleted")
        self.assertEqual(data["repeat_repair"]["packet_bytes"], 0)


if __name__ == "__main__":
    unittest.main()

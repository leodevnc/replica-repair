"""Fixed 16-bucket Merkle reconciliation of causal register states."""

from hashlib import sha256

from .core import Replica, canonical, key_name, parse_records


def digest(value):
    return sha256(canonical(value).encode("ascii")).hexdigest()


def bucket(key):
    key_name(key)
    return int(sha256(key.encode("utf-8", errors="surrogatepass")).hexdigest()[0], 16)


def leaf_digest(index, records):
    return digest(["leaf-v1", index, records])


class MerkleTree:
    def __init__(self, replica):
        records = replica.records()
        self.buckets = [{k: v for k, v in records.items() if bucket(k) == index} for index in range(16)]
        self.nodes = [""] * 32
        for index, records in enumerate(self.buckets):
            self.nodes[16 + index] = leaf_digest(index, records)
        for index in range(15, 0, -1):
            self.nodes[index] = digest(["branch-v1", self.nodes[2 * index], self.nodes[2 * index + 1]])
        self.root = self.nodes[1]

    def differences(self, other):
        leaves, compared = [], 0

        def visit(index):
            nonlocal compared
            compared += 1
            if self.nodes[index] == other.nodes[index]:
                return
            if index >= 16:
                leaves.append(index - 16)
            else:
                visit(index * 2)
                visit(index * 2 + 1)

        visit(1)
        return leaves, compared


def packet(tree, index):
    if type(index) is not int or not 0 <= index < 16:
        raise ValueError("Bucket must be 0-15")
    # Independent data: mutating a returned packet cannot mutate the tree snapshot.
    records = {k: [dict(clock=dict(v["clock"]), value=v["value"]) for v in values]
               for k, values in tree.buckets[index].items()}
    return {"schema": 1, "bucket": index, "digest": tree.nodes[16 + index], "records": records}


def apply_packet(replica, data):
    if type(data) is not dict or set(data) != {"schema", "bucket", "digest", "records"}:
        raise ValueError("Invalid repair packet")
    if type(data["schema"]) is not int or data["schema"] != 1:
        raise ValueError("Unsupported repair schema")
    index = data["bucket"]
    if type(index) is not int or not 0 <= index < 16:
        raise ValueError("Invalid repair bucket")
    parse_records(data["records"])
    if any(bucket(key) != index for key in data["records"]):
        raise ValueError("Key belongs to a different bucket")
    if data["digest"] != leaf_digest(index, data["records"]):
        raise ValueError("Repair packet digest mismatch")
    replica.receive(data["records"])  # Absence in the packet is not deletion.


def repair(left: Replica, right: Replica):
    if left.replica_id == right.replica_id:
        raise ValueError("Repair requires distinct replica identities")
    a, b = MerkleTree(left), MerkleTree(right)
    different, compared = a.differences(b)
    packets = [(packet(a, index), packet(b, index)) for index in different]
    for to_right, to_left in packets:
        apply_packet(right, to_right)
        apply_packet(left, to_left)
    return {
        "different_buckets": different,
        "hash_pairs_compared": compared,
        "records_transferred": sum(len(p["records"]) for pair in packets for p in pair),
        "packet_bytes": sum(len(canonical(p).encode("ascii")) for pair in packets for p in pair),
        "full_state_record_count": sum(len(group) for group in a.buckets + b.buckets),
        "converged": MerkleTree(left).root == MerkleTree(right).root,
    }

# Replica Repair

A small, offline replica-reconciliation engine. Two copies can accept updates while disconnected,
preserve concurrent versions, and repair divergent state without copying every record.

The difficult question is not just **"are these copies different?"** It is **"which differences
are causally newer, which are concurrent, and which represent a deletion?"**

## Run

Python 3.11+; no runtime dependencies, model calls, network service, or cloud account.

```bash
git clone https://github.com/leodevnc/replica-repair.git
cd replica-repair
python3 -m replica_repair demo
python3 -m unittest discover -s tests -v
```

The CLI runs a synthetic partition-and-repair scenario and prints JSON. Nothing is written to disk
and no network request is made. It exercises the actual merge and reconciliation implementation,
not prerecorded results.

## Experiment

1. Seed two replicas with 258 identical records.
2. Disconnect them logically; edit the same note differently and delete another note on one side.
3. Compare Merkle roots, descend only mismatching branches, and exchange the affected buckets.
4. Replay a snapshot taken before deletion.
5. Explicitly resolve the concurrent note, then synchronize again.

Observed deterministic output:

| Check | Result |
| --- | --- |
| Initial divergent buckets | 2 of 16 |
| Hash pairs compared | 11 |
| Records transferred in both directions | 72 versus 516 for two full input states |
| Encoded repair packet bytes | 5,509 |
| Concurrent edit | Two siblings retained, status `conflict` |
| Pre-deletion replay | Status remains `deleted` |
| Explicit resolution | One causally newer value |
| Repeat repair | One root comparison, zero record/packet bytes |

Packet bytes exclude hypothetical network headers and hash exchange. These are fixture counts,
not a network benchmark. Trees are rebuilt by scanning local state; fewer transferred records
does not imply sublinear local CPU cost.

## Use the library

```python
from replica_repair import Replica, repair

east, west = Replica("east"), Replica("west")
east.put("note", "first")
repair(east, west)

east.put("note", "edited while disconnected")
west.delete("note")
repair(east, west)
assert east.read("note")["status"] == "conflict"

# A deliberate application decision replaces all siblings observed here.
east.put("note", "combined after reviewing the conflict")
repair(east, west)
assert len(west.siblings("note")) == 1
```

`put` observes all versions of that key currently held at its replica. It is not a stale-client
compare-and-set API. Reads return `missing`, `value`, `deleted`, or `conflict`; they never quietly
select one concurrent value. Empty text is a value; Python `None` is a tombstone.

## Implemented boundaries

- Per-key version vectors; unique writer IDs and monotonic local sequence numbers.
- Merge retains causally maximal versions and rejects equal-clock/different-payload reuse when
  both versions are available for comparison.
- Tombstones participate in hashes and merges. They are not garbage-collected.
- Sixteen SHA-256 key buckets and a fixed binary Merkle tree.
- Detached, versioned repair packets with bucket and checksum validation.
- Atomic in-memory batch validation/merge; duplicate and reordered delivery are supported.
- JSON-compatible snapshots preserve writer counters and unresolved siblings.
- Bounded key, sibling, actor, counter and value sizes; excess state is rejected, never silently
  truncated.

## Study record

- [Architecture and invariants](docs/architecture.md)
- [Design decisions](docs/decisions.md)
- [Evidence and reproducibility](docs/test-evidence.md)
- [Learning notes and topic distinction](docs/learning-notes.md)
- [Roadmap](docs/roadmap.md)

The primary reference is the original
[Dynamo paper, sections 4.4 and 4.7](https://www.allthingsdistributed.com/2007/10/amazons_dynamo.html).
Its discussion of version vectors and Merkle anti-entropy informs this experiment; this repository
is not a Dynamo implementation or an AWS integration.

## Limits

This is a **single-process, single-threaded algorithm prototype**, not a distributed database.
There is no transport, persistence service, process-crash durability, quorum, authentication,
membership protocol, or multi-key transaction. A checksum detects accidental corruption, not a
malicious peer that recomputes it. Replicas must be trusted.

Do not run multiple writers under one ID or resume an old snapshot while another incarnation is
active. Counter rollback beyond the information in a snapshot cannot be detected. Cross-key
causality is not modeled. Snapshot export is a caller-managed value, not a durable commit.

Per batch: at most 2,048 keys, 64 siblings per key, 32 actors per version, 128 characters per key
and 4,096 per text value. Limits trade availability for explicit failure. A two-way repair can be
partially applied if a later packet fails; replay joins state safely. There is no atomic transaction
across replicas. Eventual convergence assumes writes stop, all required exchanges eventually occur,
valid unique identities, sufficient capacity, and no hash collision.

## License

MIT

# Architecture and invariants

```text
Replica A state                         Replica B state
  key -> causal siblings                  key -> causal siblings
          |                                       |
   canonical buckets                       canonical buckets
          |                                       |
      Merkle root -------- compare -------- Merkle root
                              |
                  descend mismatching branches
                              |
                  exchange complete dirty buckets
                              |
               validate packet, then merge siblings
                              |
                explicit application conflict resolution
```

## The register

A version is an immutable sorted tuple of actor/counter pairs plus a string or tombstone.
Vector A strictly dominates B when every component of A is at least B and the vectors differ.
Absent components mean zero. Neither wall time nor lexicographic actor order decides a winner.

The merge operation unions versions, deduplicates equal clocks with equal payloads, rejects
same-clock payload disagreement, and retains the causal maxima. For valid reachable histories,
this join is associative, commutative and idempotent. Canonical sorting is only for deterministic
encoding, not conflict selection.

An explicit put takes the component-wise maximum of all siblings currently observed for that key,
then advances the local actor using a replica-wide sequence number. Sequence numbers avoid reuse
across local updates, but the vectors record only per-key causal context. Independent keys are
not a transaction or a global causal history.

## Deletion

Deletion creates a normal causally versioned record whose value is null. A stale ancestor cannot
dominate it. A concurrent write remains a conflict, including the tombstone sibling; it is not
automatically erased or automatically revived. A write that observes the tombstone can intentionally
recreate the key.

Removing a tombstone would lose the evidence needed to reject an offline replica's old value.
This implementation does not have the membership and acknowledgement machinery necessary to prove
safe removal, so it does not expose tombstone garbage collection.

## Merkle comparison

SHA-256 of the key selects one of sixteen fixed buckets. Each leaf hashes a domain marker, its
bucket number and canonical records, including all sibling clocks and tombstones. Each parent
hashes a different domain marker and its ordered child digests.

Equal roots end comparison immediately. Otherwise recursive comparison visits unequal subtrees.
Only dirty leaf buckets produce packets. Whole buckets, not individual changed keys, are exchanged;
unchanged neighbors in a dirty bucket travel too.

The tree is a local snapshot. Packets are detached copies. A receiver validates schema, record
shape, bucket membership and the leaf checksum, then merges against its **current** state rather
than replacing it. A newer local edit therefore survives a stale repair packet. The checksum is
not a signature or proof against a hostile sender. Snapshots and packets are in-memory Python
objects; there is no untrusted byte-stream parser or network protocol here.

## Atomicity and identity

A receive validates the whole batch and builds a candidate state before committing the in-memory
dictionary and sequence. Failure changes neither. One repair call consists of multiple such
receives and is not atomic across replicas. Interrupted/duplicated delivery can be resumed.

Snapshot restoration validates schema, counters and records. Its sequence must be at least any
local-actor component in the restored data. This catches an internally inconsistent snapshot, not
an externally rolled-back incarnation. Unique active writer identity and safe snapshot handling
remain caller obligations.

## Costs and bounds

Tree construction scans all local records. There are 31 hash nodes and at most 31 compared hash
pairs. One differing leaf requires nine comparisons in this fixed tree. Merge is quadratic in
the candidate sibling count per key. Input limits keep experiments bounded, but no throughput,
memory ceiling, wire-size or latency guarantee is claimed.

The full-state comparison count measures records present on the two inputs **before** repair.
Transferred records count each key once per outgoing bucket; a record may contain multiple siblings.
Packet bytes count canonical ASCII JSON envelopes only.

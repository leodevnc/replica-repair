# Design decisions

## ADR 001: Preserve concurrent siblings

**Question:** Should repair choose a winner to simplify reads?

**Decision:** Preserve all causal maxima and expose conflict status. No wall-clock last-write-wins
rule is used.

**Consequence:** Reads can require an application decision and sibling counts can grow. Capacity
failure is explicit. The system does not silently throw away a concurrent edit.

## ADR 002: Keep tombstones without a time-to-live

**Question:** When can a delete marker be removed?

**Decision:** Never in this milestone. Safe reclamation needs knowledge of peers and their progress,
which this engine does not maintain.

**Consequence:** Old replicas cannot resurrect an observed deletion, but metadata grows. A
concurrent delete/write is still a conflict; deletion is not automatically dominant.

## ADR 003: Reconcile fixed buckets, not individual records

**Question:** How much indexing machinery is necessary to study anti-entropy?

**Decision:** A 16-leaf tree rebuilt from state. Dirty buckets transfer all contained records.

**Consequence:** The implementation exposes pruning and payload accounting clearly. It does not
provide incremental hashing, balanced dynamic ranges, streaming, or production-scale indexing.

## ADR 004: Separate repair from transport and durability

**Question:** Must a first experiment introduce sockets and a database?

**Decision:** Keep the merge engine in memory, make packets explicit, and make snapshots
JSON-compatible. Tests can drop, repeat, corrupt and reorder packets deterministically.

**Consequence:** Network partitions are simulated by withholding delivery. No claim of real
multi-process crash recovery or database durability is made. A later independent experiment can
study a persistence boundary without hiding algorithm mistakes behind infrastructure.

## ADR 005: Reject malformed state before mutation

**Decision:** Validate packet fields, counters, namespace sizes, clock reuse and capacity, then
commit a batch in memory. Checksums detect accidental changes only.

**Consequence:** A bad batch is atomic, but a multi-packet repair may stop after partial progress.
Retries merge rather than replace. Trusted writer IDs are an assumption, not an authentication
mechanism.

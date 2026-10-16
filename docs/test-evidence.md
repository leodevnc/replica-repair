# Testing and repair experiments

The local tests use Python's standard library and synthetic replica histories; no cloud resources
are required.

## Test coverage

```bash
python3 -m unittest discover -s tests -v
```

Coverage includes sequential and concurrent writes, concurrent delete/edit, stale replay,
intentional recreation, explicit resolution, merge algebra examples, all six delivery permutations
of three siblings with duplicate replay, partial/reordered bucket delivery, stale packets, checksum
corruption, wrong buckets, detached packet data, canonical hash ordering, input/capacity validation,
snapshot roundtrip, and monotonic sequence checks.

The seeded history test runs 40 deterministic seeds with 70 operations per seed across three
replicas: 2,800 generated operations before final repair. Final states are compared with a
full-state causal merge oracle after writes stop and connected exchanges complete. This is
empirical coverage, not a formal proof.

## CLI fixture

`python3 -m replica_repair demo` independently executes a 258-key synthetic dataset.

- First divergent repair: buckets 9 and 10, 11 hash comparisons, 72 records, 5,509 packet bytes.
- Full-state input count for comparison: 516 records across both replicas.
- Concurrent edits remain a conflict.
- Replaying the pre-deletion snapshot leaves the other key deleted.
- Explicit resolution converges to one value.
- A repeated repair performs one hash comparison and transfers zero records and packet bytes.
- Final root: `666750c8f708a0d113b960cfd46fc833e96b046c44d12913f82705554d34078c`.

Counts are based on canonical envelopes and do not include transport framing, hash exchange or a
network stack. No speedup or network throughput was measured.

## Package checks

Build a wheel with `python3 -m pip wheel --no-build-isolation --no-deps .`. Validate it from an
isolated process outside the source checkout: imports should resolve from the installed package,
and the demo should preserve convergence and deletion behavior.

## Limits of validation

No real network partitions, concurrent threads, process crashes, disk failures, malicious peers,
or production-scale workloads were tested. The identity model assumes unique active writers.
Checksums do not authenticate data. No hosted CI run is claimed. The implementation never claims
that convergence removes the need for application-level conflict resolution.

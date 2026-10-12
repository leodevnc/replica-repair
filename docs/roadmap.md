# Roadmap

## Initial milestone

- [x] Immutable causal versions and conflict-preserving merge
- [x] Explicit tombstones and intentional recreation
- [x] Fixed-bucket Merkle comparison and packet accounting
- [x] Packet schema, checksum and bucket validation
- [x] JSON-compatible snapshot/restore with counter validation
- [x] Synthetic partition, stale replay and conflict-resolution CLI
- [x] Algebraic examples, delivery permutations and seeded history tests
- [x] Document assumptions, measured evidence and unsupported guarantees

## Open questions

- How should a client supply an explicit read context instead of implicitly observing all local siblings?
- Which peer progress and membership evidence would justify tombstone reclamation?
- How much CPU and payload change when tree depth and bucket size vary?
- How should concurrent repair reads coordinate with writes in a multi-threaded implementation?

## Possible independent next study

A write-ahead log with checksummed records, crash-point injection and recovery from a torn final
record would explore the persistence boundary intentionally absent here. It should remain a
separate experiment rather than being confused with convergence.

# Learning notes

## Why this is a separate topic

Existing public studies were inspected before choosing this scope:

| Existing project | Its central concern | Distinction here |
| --- | --- | --- |
| agent-tool-runtime | Controlled execution, retries and idempotency | Replicated data merge, not tool invocation |
| bess-event-delivery-lab | Outbox/inbox delivery and per-asset ordering | Concurrent peer histories without a single sequence |
| forecast-cache-lab | Freshness and cached origin reads | Neither replica is designated the source of truth |
| snapshot-search-lab | Immutable search generations and citations | Mutable peer state and causal reconciliation |
| runledger | Workflow durability and side-effect-safe replay | Register convergence, not workflow replay |
| quota-gate-lab | Atomic hierarchical admission | No admission or request-rate policy |
| context-planner, tracegrade, llm-os | Context, evaluation, execution environment | No model, context budgeting or agent loop |

The wider repository list and README summaries were also checked. No existing repository identified
in that inspection centered on causal multi-value registers with Merkle anti-entropy.

## Observations from the implementation

- Equality detection and conflict resolution solve different problems. A hash says two states
  differ; it cannot tell which version is causally newer.
- Absence is not evidence of deletion. A delete must carry causal information into reconciliation.
- A packet can be valid but stale. Joining it with current state is different from replacing a
  bucket with the sender's old snapshot.
- Convergence does not imply agreement on one value. Both replicas can converge on the same set
  of unresolved siblings.
- A no-op second repair tests a different property from eventual convergence: equal roots should
  avoid transfer entirely.
- Sibling, actor and key limits are observable availability tradeoffs. Dropping metadata to stay
  within a limit would quietly change the consistency semantics.
- Fewer transferred records does not establish lower total cost. This version still rebuilds the
  tree from all local records.
- Identity reuse can break causal assumptions even when serialization and checksum validation
  pass. The engine does not pretend to solve membership or writer fencing.

## Reference

The original [Dynamo paper](https://www.allthingsdistributed.com/2007/10/amazons_dynamo.html),
especially sections 4.4 and 4.7, separates object versioning from background replica synchronization.
This project isolates that distinction; it does not implement Dynamo's full architecture.

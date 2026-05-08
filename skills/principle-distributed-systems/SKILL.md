---
name: principle-distributed-systems
description: Distributed systems principles — CAP, PACELC, consistency models (linearizable, causal, eventual, read-your-writes), consensus (Paxos, Raft), quorum, leader election, split-brain, replication, partitioning, gossip, logical clocks (Lamport, vector, hybrid), clock skew, delivery semantics (at-most-once, at-least-once, exactly-once effects), idempotency across nodes, two-generals problem, fallacies of distributed computing. Auto-load when reasoning about CAP/PACELC trade-offs, choosing a consistency model, designing consensus or leader election, sizing quorums, ordering events with logical clocks, distinguishing exactly-once delivery from exactly-once effects, designing replication or partitioning strategy, or assessing distributed failure modes.
---

# Distributed Systems

Multi-node systems fail partially and non-deterministically. Every design decision spans a space of consistency, availability, and latency trade-offs — name them explicitly.

## CAP and PACELC

**CAP**: under a network **P**artition, choose **C**onsistency or **A**vailability — you cannot guarantee both.

**PACELC** extends this to normal operation: even without a partition, every request trades **L**atency for **C**onsistency. Always name both axes: "This is AP/EL — available under partition, latency-favoured otherwise."

Common placements: Cassandra (AP/EL), HBase (CP/EC), Spanner (CP/EC via TrueTime), DynamoDB (AP/EL by default, tunable).

## Consistency Models

Ordered strongest → weakest:

| Model | Promise |
|-------|---------|
| **Linearizable** | Reads always see the most recent committed write; operations appear atomic. Requires consensus. |
| **Sequential** | All nodes observe operations in the same order, not necessarily wall-clock order. |
| **Causal** | Causally related writes are observed in order; concurrent writes may diverge. |
| **Read-your-writes** | A client always reads its own most recent write (single-session). |
| **Monotonic reads** | A client never reads a value older than one it already read. |
| **Eventual** | All replicas converge given sufficient time and no new writes. |

Choose the weakest model that satisfies correctness. Most user-facing apps need only read-your-writes + monotonic reads; linearizability is expensive.

## Time, Clocks, and Ordering

Physical clocks drift — never use wall-clock timestamps to order events across nodes.

- **Lamport timestamps**: logical counter incremented on send/receive. Establishes causal order; cannot detect concurrency.
- **Vector clocks**: per-node counters. Detect both causality (`a → b`) and concurrency (`a ∥ b`). Used by Riak.
- **Hybrid Logical Clocks (HLC)**: monotonically increasing, stays close to physical time. Used by CockroachDB.
- **TrueTime** (Spanner): GPS + atomic clocks with bounded uncertainty interval; enables external consistency.

When ordering matters for correctness (deduplication windows, optimistic concurrency), prefer a coordinator or consensus over clock-based ordering.

## Consensus and Leader Election

**FLP impossibility**: in an asynchronous network with one faulty node, no deterministic algorithm always reaches consensus. Practical systems use timeouts (Raft) or randomised backoff to achieve probabilistic liveness.

- **Raft**: single strong leader, log replication, randomised election timeouts. Easier to audit than Paxos.
- **Quorum**: `N/2 + 1` nodes must acknowledge a write. Prevents split-brain — two partitions cannot each form quorum.
- **Fencing tokens**: monotonically increasing token issued per leader election. Storage nodes reject stale tokens, preventing split-brain writes.

Prefer off-the-shelf coordinators (**etcd**, **ZooKeeper**, **consul**) over hand-rolled consensus — Raft bugs emerge only under gray failure.

## Replication and Partitioning

**Replication strategies:**

| Strategy | Trade-off |
|----------|-----------|
| Single-leader | Simple ordered writes; leader bottleneck, failover lag |
| Multi-leader | Lower write latency across regions; conflict resolution required |
| Leaderless (quorum reads/writes) | No single point of failure; read-repair complexity, stale reads |

**Async replication lag**: replicas may trail by seconds — avoid reading from a replica immediately after a write without read-your-writes guarantees.

**Partitioning**: hash partitioning gives uniform distribution; range partitioning enables range scans but risks hotspots on monotonic keys. Cross-ref `principle-data-modeling#Hot keys and hot partitions`.

**Gossip / anti-entropy**: nodes exchange state periodically to converge without a central coordinator (Cassandra, DynamoDB).

## Delivery Semantics: At-Most-Once, At-Least-Once, Exactly-Once

| Semantic | Behaviour on failure |
|----------|---------------------|
| At-most-once | Message may be lost; never duplicated (fire and forget) |
| At-least-once | Message retried until acknowledged; duplicates possible |
| Exactly-once delivery | Impossible over an unreliable network (two-generals problem) |
| Exactly-once *effects* | Achievable: idempotent consumer + dedup + atomic commit |

"Exactly-once delivery" is a myth. What's achievable is exactly-once *effects*: process at least once, but make the effect idempotent so duplicates are harmless. Cross-ref `principle-event-driven#Idempotent Handlers and the Outbox Pattern`.

## Idempotency Across the Network

- **Idempotency keys**: client-supplied UUID attached to a request; server deduplicates within a time window.
- **Dedup windows**: must be ≥ max retry duration — a shorter window creates correctness holes under slow retries.
- **Natural vs. designed idempotency**: `PUT /resource/{id}` is naturally idempotent; `POST /charge` is not — wrap with an idempotency key.

Cross-ref `principle-api-design#Idempotency` and `principle-error-handling#Retries and Backoff`.

## Distributed Failure Modes

**Eight fallacies of distributed computing** (Deutsch et al.) — treat as a pre-design checklist:
1. The network is reliable. 2. Latency is zero. 3. Bandwidth is infinite. 4. The network is secure.
5. Topology doesn't change. 6. There is one administrator. 7. Transport cost is zero. 8. The network is homogeneous.

**Gray failures**: partial packet loss or high tail latency — harder to detect than clean crashes; often masked by timeouts.

**Split-brain**: two partitions each believe they are authoritative. Prevented by quorum + fencing tokens.

**Two-generals problem**: no protocol over an unreliable channel can guarantee both parties agree to act — the formal basis for exactly-once delivery impossibility.

Cross-ref `principle-resiliency#Failure Domains` for blast-radius and bulkhead containment.

## When Distributed Systems Thinking is Overkill

- Single-process service with a single database: use transactions, not quorums.
- Batch jobs reading immutable snapshots: clock skew and ordering are irrelevant.
- Prototypes and MVPs: don't introduce CAP gymnastics where `BEGIN TRANSACTION` suffices.
- Internal tools where one team owns both ends of every dependency.

## Red Flags

| Flag | Problem |
|------|---------|
| "We'll use eventual consistency everywhere" | Reads after writes will surface stale data without at least read-your-writes |
| "The network is reliable in our data centre" | Fallacy #1 — design for packet loss and reordering |
| "We built our own leader election" | Hand-rolled consensus fails under gray failures; use etcd or ZooKeeper |
| "Timestamps establish global event order" | Physical clocks drift; use Lamport, vector, or HLC clocks instead |
| "We retry until success, so it's exactly-once" | Retries produce duplicates without idempotency; exactly-once delivery is impossible |
| "More replicas improve both reads and consistency" | More replicas increase replication lag; quorum reads add latency |

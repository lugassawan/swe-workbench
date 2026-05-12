---
name: principle-cost-awareness
description: Cost awareness principles — FinOps mindset, egress and data-movement charges, right-sizing, scale-to-zero, cost-per-request model, storage tier selection, observability cost, cardinality explosion, log volume. Auto-load when reasoning about cloud costs, egress topology, right-sizing instances, scale-to-zero trade-offs, storage tier selection, log sampling, or FinOps budget constraints.
---

# Cost Awareness

Cost bugs are design bugs. They are cheapest to fix before the first dollar is spent. This skill teaches design-time discipline — choosing the right tier, topology, and access pattern — not post-billing cost reduction tactics.

## FinOps Mindset

Cost is a feature requirement, not an afterthought. Treat budget the same way you treat latency and availability SLOs.
- Name a cost budget alongside the performance budget at design time. "Under $X/month at N req/s" is a testable acceptance criterion.
- Cloud bills are emergent: small per-request charges multiply by request volume, retention windows, and replica count in ways that are invisible in local testing.
- Assign cost ownership to the team that controls the resource. Shared cost pools obscure accountability and slow optimization.
- Unit economics clarify decisions: cost-per-request, cost-per-GB-stored, cost-per-active-user. Derive these early; revisit when scale changes by 10×.

## Egress and Data Movement

Egress is the most common billing surprise — data that moves costs more than data that sits still.
- Intra-AZ traffic is typically free; cross-AZ traffic carries per-GB charges; cross-region is more expensive; egress out of a cloud to another cloud is most expensive (inbound/ingress is typically free on most providers). Map outbound data flows against this hierarchy at design time.
- Chatty microservice calls that exchange large payloads inflate egress costs non-linearly as request rates grow. Prefer coarse-grained APIs at zone boundaries.
- Naive replication — e.g., syncing every write to a second region — multiplies egress by replica count. Use asynchronous replication with tunable lag tolerance where strong consistency is not required.
- Read replicas in a different AZ or region pay egress on every read result. Profile read-result payload sizes before assuming replica reads are cheap.
- Cross-ref `principle-distributed-systems#Replication and Partitioning` for replication strategy semantics.

## Right-Sizing and Auto-Scaling

Over-provisioning for p99 load wastes the entire baseline; under-provisioning for bursts causes latency failure.
- Establish a provisioning floor (minimum always-on capacity) and a ceiling (max burst capacity) explicitly. The gap between them is your cost-elasticity window.
- Scale-to-zero eliminates idle cost but introduces cold-start latency. State the acceptable cold-start budget before choosing this trade-off — it is not free.
- Vertical scaling (larger instance) is faster to deliver and easier to reason about than horizontal scaling but has a hard ceiling. Exhaust vertical options first for stateful workloads.
- Use p95–p99 traffic as the auto-scaling trigger metric, not CPU average — average metrics smooth over bursts that cause user-visible latency spikes.
- Scheduled scaling (pre-warm before known traffic peaks) costs less than reactive scaling that over-shoots and then slowly drains.

## Cost-Per-Request

Every API call has a price. Design service interactions with that price on the whiteboard.
- Count the downstream calls triggered by a single user request. Each hop (database query, cache miss, external API, message publish) adds latency *and* cost.
- Chatty service interactions — many small calls instead of one batched call — inflate both request count and per-unit overhead (TLS handshakes, authentication, serialization).
- Batch and cache are cost levers, not just latency levers. A cache hit that avoids a downstream API call eliminates its cost entirely, not just its latency.
- Pagination and streaming reduce peak memory and egress per response slice; choose page sizes that balance round-trip count against payload cost.
- Cross-ref `principle-performance#N+1 and the Database Boundary` — N+1 queries are also N+1 billed units.

## Storage Tier Selection

Tier choice drives storage cost more than any single optimization. Match access frequency to tier before writing data.
- **Hot tier** (SSD, in-region object storage standard): high throughput, high cost. Use for data accessed daily or in the critical path.
- **Warm tier** (infrequent-access, nearline): lower storage cost, higher retrieval cost. Use for data accessed monthly.
- **Cold / archive tier** (Glacier, Coldline, archive): lowest storage cost, high retrieval latency and cost. Use for compliance retention and disaster-recovery snapshots.
- Lifecycle policies automate tier transitions. Define them at schema design time — retrofitting lifecycle rules onto an existing bucket is error-prone and easily missed.
- Query frequency drives tier choice, not data age alone. A two-year-old audit log queried daily belongs in hot tier; a one-week-old backup never queried belongs in cold.
- Cross-ref `principle-data-modeling#Retention and archival` for schema-level retention controls.

## Logging and Observability Cost

Log volume is a second bill hiding inside the observability budget.
- Logging every request at DEBUG verbosity in production is a common cost multiplier. Default to INFO; reserve DEBUG for targeted troubleshooting windows.
- High-cardinality log fields (user IDs, request IDs, session tokens) generate unique index entries in managed log services and drive cost non-linearly. Emit cardinality in structured fields only when you will query them.
- Sampling strategies (head-based, tail-based, error-only) reduce ingestion volume without losing signal for error investigation. Define a sampling rate at design time; "log everything" is a choice with a cost.
- Retention windows are cost controls. 90-day retention at full volume costs 3× a 30-day window. Align retention to the operational use case, not to "more is safer".
- Cross-ref `principle-observability#Cardinality` for metric label cardinality explosion; log-index cardinality in managed log services follows the same pattern but is a billing concern specific to logging infrastructure.

## When Cost Thinking is Overkill

- Prototypes and proof-of-concepts: correctness and speed-to-feedback outweigh cost optimization.
- Single-tenant internal tools with fixed, low-volume workloads where the bill is bounded and negligible.
- Pre-product-market-fit experiments: optimizing cost before validating demand is premature.
- Fixed-cost workloads (reserved instances, on-premise hardware): compute cost per request is near-zero; egress charges and storage tier selection still apply.
- Development and staging environments: short-lived and low-traffic; apply cost controls at the account boundary (budget alerts, TTL automation) rather than per-resource.

## Red Flags

| Flag | Problem |
|------|---------|
| No cost budget at design time | Cost grows silently; first signal is the monthly invoice |
| Cross-region replication on every write | Egress multiplied by write rate and replica count |
| Chatty service boundary with small payloads | High request count × per-call overhead inflates cost non-linearly |
| Scale-to-zero without a cold-start budget | Latency SLO violated on burst; cold-start latency not modeled |
| All data in hot-tier storage | Storing compliance archives in standard S3/GCS with no lifecycle policy |
| DEBUG logging in production | Log volume 10–100× INFO; ingestion and retention costs explode |
| High-cardinality log fields unsampled | Unique values per field blow up managed-log index cost |
| "We'll optimize cost later" | Cost patterns set at design solidify in infrastructure-as-code and are expensive to retrofit |

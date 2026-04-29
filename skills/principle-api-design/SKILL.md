---
name: principle-api-design
description: API design principles — contract-first thinking, semantic versioning, idempotency keys, pagination (offset vs cursor), error shape consistency, evolvability and backward compatibility, REST vs RPC vs event-driven trade-offs, hypermedia, resource modeling, deprecation strategy. Auto-load when designing an API, choosing REST or RPC or events, adding api versioning, designing idempotent endpoints, adding pagination, shaping error responses, deprecating an endpoint, or evolving a public contract.
---

# API Design

An API is a contract. Breaking it breaks callers. Design for evolvability from day one.

## Contract-First

Design the interface before the implementation. Write the schema or proto before any code.
- Contracts force clarity on resource modeling, field names, and error cases early.
- If the design is painful to describe, the implementation will be painful to use.
- API review at design time is cheap; API review after clients exist is very expensive.

## Versioning

Every breaking change requires a new version. Communicate it, window it, enforce the schedule.
- **Breaking:** removing a field, changing a field type, changing semantics of a status code, renaming a resource.
- **Additive (non-breaking):** new optional fields, new endpoints, new enum values in response.
- **URL-path versioning** (`/v1/orders`) — visible, cacheable, easy to route; good for major versions.
- **Header versioning** (`API-Version: 2024-01-01`) — cleaner URLs; common for date-based schemes.
- Set a deprecation window (minimum 6 months for external APIs) and enforce it; sunset headers signal the date.

## Idempotency

Operations must be safe to retry. Network failures happen; callers will retry.
- **Safe** (GET, HEAD, OPTIONS) — no side effects.
- **Idempotent** (PUT, DELETE) — repeating produces the same result.
- **Non-idempotent** (POST) — accept an idempotency key header; server deduplicates by key.
- Key scope: client-generated UUID, tied to the logical operation, expires after a defined window.
- Return the same response for a duplicate key — do not create twice, do not error.

## Pagination

Never return unbounded collections. Choose the model based on query patterns.
- **Offset pagination** — simple; breaks when records insert or delete during traversal; fine for small, stable sets.
- **Cursor pagination** — stable under concurrent writes; opaque cursor encodes position; cannot jump to page N.
- Always cap page size server-side; document the default and maximum.
- Return a `next_cursor` or `next_page` token — do not expose the underlying query offset or row ID.

## Error Shapes

Consistent error envelopes let callers handle errors generically.
- Every error response: `code` (machine-readable), `message` (human-readable), `details` (optional array), `request_id`.
- HTTP status discipline: 400 bad input, 401 unauthenticated, 403 unauthorized, 404 not found, 409 conflict, 422 semantic error, 429 rate limited, 500 server fault.
- Problem+JSON (RFC 7807) as a standard envelope for REST APIs.
- Never return 200 OK with `"error": true` in the body — callers cannot detect errors without body parsing.

## Evolvability

Design for forward and backward compatibility from the start.
- **Additive only** — add fields, never remove or rename in-place.
- **Tolerate unknown fields** — clients must ignore keys they do not recognize (Postel's law on reading).
- **Default-on-omit** — if a field is absent, apply a safe default; do not error.
- Never reuse a retired field name with a different type or semantic.
- Serialize enums as strings, not integers — new values are additive; integer reordering is breaking.

## REST vs RPC vs Event-Driven

**REST**
- **Use when:** resource-oriented CRUD, public APIs, cache-friendly reads, diverse client ecosystem.
- **Costs:** round trips for complex operations; HTTP overhead; no native streaming.
- **Don't use when:** low-latency internal services, server-push streaming, or highly procedural workflows.

**RPC (gRPC / Thrift / Twirp)**
- **Use when:** internal service-to-service, schema-first contracts, strong typing required, streaming needed.
- **Costs:** less human-readable; requires code generation; harder to debug with standard HTTP tools.
- **Don't use when:** public APIs consumed by browsers or third parties that lack generated client support.

**Event-Driven**
- **Use when:** decoupled producers and consumers, eventual consistency acceptable, audit log or replay required.
- **Costs:** ordering guarantees complex; debugging harder; silent consumer drift possible.
- **Don't use when:** synchronous response is required, or consumer must confirm processing before producer continues.

## When Strict API Discipline is Overkill

- Internal-only APIs with a single consumer owned by the same team.
- Short-lived prototypes (under two weeks) with no external consumers.
- Scripts or migrations that call an API once and are immediately discarded.

## Red Flags

| Flag | Problem |
|------|---------|
| `/v1/`, `/v1.1/`, `/v2/`, `/v2-new/` in one codebase | Version creep — no deprecation discipline enforced |
| Breaking field removed in a patch release | Breaking change shipped without a version bump |
| Response fields map directly to DB column names | Schema leak — any migration breaks clients |
| `200 OK` with `{"error": true}` in body | Generic error handling impossible for callers |
| GET endpoint that creates or modifies state | Violates HTTP safety; CDNs and browsers will cache the write |
| No `request_id` in error responses | Cannot correlate support reports to server logs |

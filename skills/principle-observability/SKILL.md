---
name: principle-observability
description: Observability principles — logs vs metrics vs traces, structured logging, span/trace context, cardinality control, OpenTelemetry, SLI/SLO/SLA, RED method, USE method, alerting on symptoms vs causes. Auto-load when adding logging, choosing a metric, instrumenting traces, debating cardinality, defining SLIs/SLOs, designing alerts, or discussing observability budgets.
---

# Observability

Three signals, each with a distinct job. Use the right one for the right question.

## The Three Pillars

**Logs** — discrete events with context. Right for: debugging specific incidents, audit trails, free-text search.
- Emit at decision points and error boundaries, not in loops.
- Use structured key-value format; never interpolate variables into free-form strings.
- Include a correlation ID on every line — trace parent ID if a trace exists.

**Metrics** — numeric aggregations over time. Right for: dashboards, SLOs, alerting thresholds.
- Pre-aggregate; do not stream raw events into a metrics backend.
- Label only stable, low-cardinality dimensions (region, status_code, service) — never user ID, request ID, or email.

**Traces** — causal chain of operations across services. Right for: latency attribution, dependency mapping.
- A span represents one unit of work; parent/child links form the trace.
- Propagate context headers at every service boundary — OpenTelemetry W3C trace context.
- Put high-cardinality attributes (user ID, document ID) in span attributes, not metric labels.

## Structured Logging

Emit events as key-value pairs. The log processor should never parse a free-form string.
- Correlation ID ties log lines to a trace and to a business operation.
- Log level discipline: DEBUG (local dev), INFO (normal flow), WARN (recoverable anomaly), ERROR (action required).
- No `log.debug("entering function X")` in hot paths — cost without signal.

## Cardinality

High-cardinality labels explode time-series count and kill metrics backends.
- **Safe:** `status_code`, `method`, `region`, `environment` — bounded sets.
- **Unsafe:** `user_id`, `request_id`, `session_token` — unbounded.
- Move high-cardinality context to span attributes or structured log fields.
- Rule of thumb: if a label's value count exceeds 1 000, it does not belong in a metric.

## SLI / SLO / Error Budget

Define SLIs around user-visible behavior, not internal mechanics.
- **SLI** — the measurement: request success rate, p99 latency, data freshness.
- **SLO** — the target: 99.9% success rate over a rolling 28-day window.
- **Error budget** — 1 − SLO; spend it on risk, protect it by slowing releases.
- Track error budgets as a team policy, not as an on-call metric.
- Never use CPU utilization or memory as SLIs — users do not feel CPU.

## RED Method (request-driven services)

Three questions for every service:
- **Rate** — how many requests per second?
- **Errors** — what fraction are failing?
- **Duration** — how long are they taking? (histogram, not average)

## USE Method (resource-driven services)

Three questions per resource (CPU, memory, disk, network):
- **Utilization** — how busy is the resource?
- **Saturation** — how much demand is queued?
- **Errors** — is the resource reporting errors?

## Alert on Symptoms, Not Causes

Page humans for user-visible pain. Let dashboards explain why.
- **Page-worthy:** error rate exceeds SLO budget burn rate; p99 latency exceeds user threshold.
- **Not page-worthy:** CPU > 80%, heap > 70% — correlate these in post-mortems.
- Symptom alerts reduce alert fatigue; cause alerts create it.

## When Observability is Overkill

- Internal scripts, batch jobs, one-off migrations — structured logs suffice.
- Single-process services owned by one developer — standard library logging, no tracing.
- Prototypes: instrument later; premature instrumentation shapes API decisions before the design is stable.

## Red Flags

| Flag | Problem |
|------|---------|
| Alerts fire on CPU or memory thresholds | Cause alert — pages without confirmed user impact |
| `log.debug("value: " + obj.toString())` | String interpolation breaks log parsing; expensive in hot paths |
| Metric labels include user ID or request ID | High-cardinality explosion; will saturate the metrics backend |
| Dashboard added for every new feature | Dashboards-as-product; nobody reads them; builds false confidence |
| On-call only reacts when paged | No error-budget tracking; SLO erosion invisible until breach |

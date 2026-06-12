---
name: workflow-performance-investigation
description: Profile-first performance investigation runbook — reproduce and baseline a metric, pick a profiler from the ecosystem tooling matrix (Go/Python/JVM/Node/Rust/Ruby/.NET/native), capture CPU + alloc profiles under load, hand the profile to the performance-tuner agent for ranked hotspot read, classify by bottleneck taxonomy (CPU/memory-GC/I-O/lock-contention), form one hypothesis, make one isolated change, before/after measurement, regression guard. Keywords: profile flame graph hotspot bottleneck slow endpoint investigation benchmark.
---

# workflow-performance-investigation

Profile-first runbook: baseline → profile → ranked hotspots → hypothesize → isolate → measure → regression guard.

**Announce at start:** "I'm using the workflow-performance-investigation skill to structure this performance investigation."

## When to invoke

- An endpoint, job, or service is slow and the bottleneck is unknown.
- "Profile this and confirm the fix works before/after."
- You have a hypothesis but no profile to validate it.

## When NOT to invoke

- Design-time hot-path review (Big-O, allocation choices, N+1 avoidance) → use `swe-workbench:principle-performance` directly.
- You already have a profile and only need the ranked hotspot read → invoke the `performance-tuner` agent directly.
- Reviewing a PR diff for perf regressions → `/swe-workbench:review --mode perf`.

## Composition

- **`swe-workbench:principle-performance`** — design-time discipline (Big-O, allocation, N+1, data locality). Run inline or hand off; never skip the discipline layer.
- **`performance-tuner` agent** — ranked hotspot analysis given a captured profile. Hand the profile artifact at Phase 3; do not invoke before a profile exists.

## Phases

### Phase 1 — Frame & baseline

1. Reproduce the slowness reliably under a controlled load (script or benchmark).
2. Pick **one metric**: p99 latency, allocation rate, or throughput.
3. Record the baseline number before touching any code.

### Phase 2 — Profile

1. Select the profiler from the tooling matrix below for the target ecosystem.
2. Capture a **CPU profile** and an **alloc/heap profile** under the same load as Phase 1.
3. Save the profile artifact (pprof file, flamegraph SVG, etc.) for Phase 3.

### Phase 3 — Rank hotspots

1. Hand the profile artifact to the **`performance-tuner` agent** for ranked hotspot read.
2. Classify each hotspot by bottleneck taxonomy: CPU-bound · memory/GC · I/O · lock-contention.
3. Surface the top 3 ranked hotspots with their taxonomy label before hypothesizing.

### Phase 4 — Hypothesize & isolate

1. Pick the #1 hotspot. Form **one hypothesis** (e.g., "this allocates per-request; pool it").
2. Make **one isolated change**. No bundled edits — mixed changes make before/after ambiguous.

### Phase 5 — Measure before/after

1. Re-run the **same profile + same metric** from Phase 1 under identical load.
2. Keep the change only if it moves the baseline number in the right direction.
3. If no improvement: revert, revisit Phase 4 with the next hotspot.

### Phase 6 — Verify & regression guard

1. Lock the win behind a **benchmark or perf regression test** (e.g., `go test -bench`, criterion, k6).
2. Confirm no regressions in adjacent paths by re-running the full benchmark suite.
3. Document the before/after numbers in the PR description.

## Profiling tooling matrix

| Ecosystem | CPU profiler | Alloc/heap | Flame graph |
|-----------|-------------|------------|-------------|
| Go | `go tool pprof` | `pprof` heap profile | `pprof -http` or `FlameGraph` |
| Python | `py-spy` | `memray` | `py-spy record --format=flamegraph` |
| JVM | `async-profiler`, JFR | YourKit / async-profiler heap | `async-profiler -f flamegraph.html` |
| Node/TS | `node --prof`, `clinic` | `clinic heapdump`, `0x` | `0x` or `clinic flame` |
| Rust | `perf`, `pprof-rs` | `dhat`, `valgrind massif` | `flamegraph` crate / `cargo flamegraph` |
| Ruby | `stackprof` | `memory_profiler` | `stackprof --format=html` |
| .NET | `dotnet-trace` | `dotnet-gcdump` | SpeedScope / PerfView |
| Native | `perf`, `valgrind` | `heaptrack`, `massif` | `FlameGraph` scripts |

## Common mistakes

| Mistake | Why it matters |
|---------|----------------|
| Optimizing without a profile | Misses real hotspot; wastes effort on cold paths |
| Changing >1 thing at once | Makes before/after measurement uninterpretable |
| No recorded baseline | Cannot quantify the improvement |
| Micro-benchmark not reflecting prod load | Win in bench, no win in prod |
| No regression guard | Optimization silently reverted by future refactor |

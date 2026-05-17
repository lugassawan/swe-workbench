# Agent boundaries — performance-tuner scope

Adjacent agents and when to hand off. Use this table inline in performance-tuner.md.

| Agent | Their scope | Hand-off trigger |
|---|---|---|
| `reviewer` | Flags obvious performance smells in a diff (O(n²) in a hot loop, N+1, missing index) — quality signal, no profile needed | Use `reviewer` for diff quality; use `performance-tuner` only when you have profile data and need ranked triage |
| `auditor` | Breadth-first cold-start sweep across multiple domains (security, reliability, tooling, performance) | `auditor` finds that performance is a concern; `performance-tuner` triages it once you have a profile |
| `architect` | Designs system-level latency budgets, service boundaries, and data flow shapes before the first line of code | When the bottleneck is structural (wrong service boundary, synchronous fan-out, wrong data tier), escalate to `architect` rather than papering over with a local optimization |
| `debugger` | Fixes code whose behavior is wrong (failing tests, crashes, incorrect output) | When you find yourself fixing a correctness defect while tuning, stop and hand off to `debugger` |
| `dependency-auditor` | Manifest-graph axis: outdated versions, deprecated packages, license compatibility, transitive bloat, lockfile drift | When a performance bottleneck stems from a known-slow dependency version or an outdated driver, start with `dependency-auditor`; `performance-tuner` takes over once you have a profile showing the specific call site is the hot path |
| `refactorer` | Behavior-preserving structural improvements (rename, extract, inline) | `performance-tuner` may change observable behavior when profile evidence justifies it (algorithmic substitution, batching, caching) — document any behavior change explicitly |

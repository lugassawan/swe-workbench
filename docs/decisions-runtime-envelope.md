# Plugin platform decisions — runtime result envelope

Rejected alternatives behind the standard runtime result envelope
(`shared/docs/runtime-result-contract.md`) that structured `bin/` producers emit.
Recorded here so they don't have to be re-litigated. Sibling rulings live in the other `docs/decisions-*.md` files (indexed in
`docs/README.md`).

## 1. Runtime result envelope — rejected alternatives

A `bin/` script with a genuinely structured result (a list of records, per-item failure
detail, real partial-success semantics) emits one standard JSON envelope
(`shared/docs/runtime-result-contract.md`) instead of `KEY=VALUE` lines for `eval`.
Several designs were considered and rejected while shaping that contract.

**Semver-range compatibility — considered, not adopted.** `schema` looked at first like
a natural home for a `major.minor.patch` version, with a consumer accepting any
compatible minor/patch bump. Rejected: `bin/` and every `skills/`/`commands/` consumer
of it ship together as one plugin release — there is no supported skew window where an
older consumer talks to a newer producer, or vice versa. A range check would silently
accept a `data` shape the consumer was never written against, deferring a real
incompatibility to a `jq` field-miss at read time instead of a loud failure at the
checker. `schema` compatibility is exact string equality instead — a mismatch is a
corrupted or partially-updated install, not a negotiable version difference.

**Dual-emit (old shape + new envelope, one flag apart) — considered, not adopted.**
Dual-emit exists to solve exactly the skew scenario the previous paragraph rejected: two
independently-versioned artifacts that need to interoperate during a rollout window.
That scenario cannot occur here, so a dual-emit flag would be permanent complexity
(two code paths to keep in sync, forever) bought to solve a problem this plugin's own
release model doesn't have. Every producer migration replaces its old output shape
outright, in the same PR as every consumer that reads it.

**A KEY=VALUE-emitting reader (translate the envelope back to `eval`-able shell
variables) — considered, not adopted.** This would have let existing `eval "$(...)"`
call sites keep their shape unchanged, touching only the producer. Rejected for the
same reason the envelope exists in the first place: a `[{path, reason}]` array (the
actual capability gain a migration like `swe-workbench-sweep-residuals`'s unlocks) has
no faithful `KEY=VALUE` representation — flattening it back into shell variables would
either lose the per-item detail again or require inventing an ad hoc shell-array
encoding, reintroducing the exact quoting/injection risk the envelope replaces. The
checker (`swe-workbench-result-check`) validates and passes the envelope through
unchanged instead; a consuming `SKILL.md` reads it with `jq`, never `eval`.

**Grandfathering an already-JSON producer's pre-envelope shape — considered, not
adopted.** `swe-workbench-preflight-commit` already emitted a flat JSON object before
the standard envelope existed, and no consumer depended on the flat shape surviving
(verified — its one consumer reads three named fields, cheap to update). Leaving it
un-wrapped "since it's already JSON" would have made the "standard" envelope contract
self-contradicting on day one — a producer visibly not following its own contract,
with no compatibility cost to justify the exception. Wrapped under `data` like every
other migrated producer instead.

**Fully migrating a Tier-Q producer to the envelope "for consistency" — considered,
not adopted.** `swe-workbench-preflight-pr` emits several `printf %q`-quoted scalars,
already safe for `eval`, with its one free-text channel (title/body) already routed
around `eval` entirely through a side-channel JSON file. Migrating it would have cost
real lines at every call site for zero capability gain — nothing about its result
needs a list, nested records, or a partial-status distinction a bare exit code can't
already express. Hardened with a golden-literal ratchet test pinning its exact 6-field
contract instead of migrating it — the S/Q/J decision test in
`shared/docs/runtime-result-contract.md` generalizes this call for any future producer.

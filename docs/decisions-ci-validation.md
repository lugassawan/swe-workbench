# Plugin platform decisions — CI validation stays open-world

Rulings on what `scripts/validate.py` (and CI generally) may assert about plugin
metadata: positive, closed-form invariants this repo owns and controls — never an
external schema or allowlist. Recorded here so they don't have to be re-litigated.
Sibling rulings live in the other `docs/decisions-*.md` files (indexed in
`docs/README.md`).

## 1. No `claude plugin validate` in CI, and no frontmatter allowlist validator

CI's `scripts/validate.py` gate is deliberately **open-world**: `check_agents()` and friends
assert *positive, closed-form* invariants this repo owns and controls (frontmatter fields
present, references resolve, line caps respected) rather than validating against an external
schema.

Two things were considered and rejected for the same reason:

- **Running `claude plugin validate` (or equivalent) in CI** — this validates against a schema
  the CLI ships, not one this repo version-controls. An upstream schema change would turn any
  unrelated PR into a red build, with no maintainer able to fix it locally (the fix lives in a
  different repository entirely).
- **A frontmatter-key allowlist validator** — same failure mode: a new frontmatter key the
  platform adds would fail closed-world validation here until this repo's allowlist catches up,
  even though the key is valid and harmless.

Prefer assertions the repo can always satisfy by editing its own files.

**Sanctioned open-world alternative:** when a coupling genuinely needs a closed-form contract
(e.g. the Pi frontmatter boundary), express it as a golden inventory ratchet — a
module-level dict/set literal asserted equal to what's on disk — not a schema. It fails only
when *this repo* writes a new value into a file, never on an upstream addition it hasn't
adopted yet. `tests/test_agent_model_tiers.py` is the reference implementation;
`tests/test_pi_contract.py`'s `FRONTMATTER_KEYS`/`TOOL_TOKENS`/`SKILL_IDS` follow the same
shape.

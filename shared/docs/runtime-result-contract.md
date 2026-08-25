# Runtime result contract: the standard JSON envelope

A `bin/` script that needs to hand a structured result back to the calling `SKILL.md`'s
bash — anything beyond a handful of trusted scalars — emits one JSON envelope on stdout
instead of `KEY=VALUE` lines for `eval`. This page is the normative spec; every migrated
producer's `bin/README.md` row links here instead of repeating the explanation.

## Not every script needs this

This is **not** a mandate to rewrite every `bin/` script. A producer whose entire output
is a handful of trusted scalars (an owner login, a SHA, a boolean) has nothing to gain
from a JSON envelope and stays exactly as it is — see "Deciding whether to migrate"
below.

## The envelope shape

```json
{
  "schema": "swb.<command>/<major>",
  "status": "ok" | "partial" | "failed",
  "data": { "...": "command-specific typed fields" },
  "warnings": [ { "code": "...", "message": "...", "subject": "optional" } ]
}
```

- **`schema`** fuses the producer's command name and a major version — e.g.
  `swb.sweep-residuals/1`. It is not a semver string; there is no minor/patch component
  and none is planned.
- **`status`** is exactly these three values, never anything else. Command-specific
  detail (which paths, why, how many) lives in `data`, not encoded into `status`.
- **`data`** is a JSON object whose fields are specific to the producer. Every migrated
  producer's fields are documented in its own `bin/README.md` row and enforced by
  `bin/swe-workbench-result-check`'s schema registry.
- **`warnings`** is always present, always an array — **never `null`, never omitted**,
  even when empty. A consumer piping the envelope through `jq '.warnings[]'` must never
  need a null-guard.

## Versioning: exact match, not a range

`bin/` and `skills/` ship together as one plugin release — there is no supported skew
window where an older `skills/` consumer talks to a newer `bin/` producer or vice versa.
Compatibility is **exact string equality** on `schema`, not a semver range check. A
mismatch is a corrupted or partially-updated install, not a negotiable version
difference, so it fails loud and actionable: "reinstall or update the swe-workbench
plugin" — the same phrasing `bin/README.md`'s `command -v` preflight already uses for a
missing script.

A backward-incompatible change to a producer's `data` shape bumps the major
(`swb.foo/1` → `swb.foo/2`) and updates every consumer in the same PR. There is no
dual-emit period — see "No dual-emit" below.

## Exit code and `status` are orthogonal

- **Exit 0** means "stdout holds a valid envelope — trust it, parse it."
- **Non-zero exit** means "stdout is empty or untrustworthy — do not parse it," full
  stop, regardless of what `status` a partially-written stdout might otherwise have
  claimed.

This lets a producer that must never abort a caller's cleanup chain (e.g.
`swe-workbench-sweep-residuals`, invoked as `eval "$(...)"` today and
`RESULT=$(... | swe-workbench-result-check ...)` after migration) keep an unconditional
`exit 0` while still expressing a genuine partial failure through `status: "partial"`
and per-item detail in `data` — instead of overloading the exit code to mean two
different things.

## Consuming an envelope: the checker, not `eval`

`bin/swe-workbench-result-check <schema>` reads an envelope on stdin, validates it
against an internal schema registry (required `data` fields, their types, and an exact
`schema` match), and re-emits the envelope unchanged on success (exit 0) or emits
nothing with a diagnostic on stderr (exit 1). This makes it a drop-in replacement for
`eval "$(producer ...)"`:

```bash
RESULT=$(swe-workbench-sweep-residuals "$PR" | swe-workbench-result-check swb.sweep-residuals/1) || exit 1
```

No `eval` ever runs over producer output again for a migrated command — the checker's
own exit code is the only thing a caller branches on; `$RESULT` is a JSON string,
consumed with `jq`, never re-interpreted as shell.

### Two-tier field handling

Once `$RESULT` holds a validated envelope, split field access by how the field is used:

- **Report-only fields** (surfaced to the user, never branched on) — read with `jq` at
  the point the report is written, no shell variable:
  ```bash
  printf '%s' "$RESULT" | jq -r '.data.posted_inline'
  ```
- **Fields that gate a branch or feed a later command** — extract once, right after the
  checker call, with a single `jq -r` line each:
  ```bash
  BLOCKED_BY_UNRESOLVED=$(printf '%s' "$RESULT" | jq -r '.data.blocked_by_unresolved')
  ```

This keeps the line-count delta near zero even in a tightly-budgeted `SKILL.md`.

### Always herestring, never `echo | jq`

```bash
printf '%s' "$RESULT" | jq '.data'      # correct
jq '.data' <<<"$RESULT"                 # also correct
echo "$RESULT" | jq '.data'             # WRONG — see below
```

`echo` on a JSON-bearing variable is the same corruption hazard
[`shared/docs/shell-echo-vs-printf.md`](shell-echo-vs-printf.md) already documents for
hand-assembled JSON — a login-shell `echo` (zsh on macOS) expands `\n` inside a JSON
string into a raw newline byte, producing invalid JSON one step removed from where the
break is visible. The envelope contract does not add a new hazard here; it multiplies
the number of JSON-in-a-variable call sites where the existing one applies.

## Deciding whether to migrate: the S/Q/J test

Three producer shapes exist side by side in `bin/`, and the presence of the envelope
contract does not mean every producer should adopt it:

| Tier | When | Example |
|---|---|---|
| **S — bare scalar** | Output is a single trusted value with no structure to lose. | `swe-workbench-new-run-dir` prints a bare path — `RUN_DIR=$(swe-workbench-new-run-dir ...)`, no `eval`, nothing to validate. |
| **Q — quoted scalars, kept** | Multiple trusted scalars, already `printf %q`-quoted for safe `eval`, with any free-text channel already routed around `eval` entirely (a side-channel JSON file, read with `jq`). | `swe-workbench-preflight-pr` emits 6 `%q`-quoted fields; `title`/`body` go through `$OUT_JSON`, never through `eval`. Migrating buys nothing a golden-literal ratchet test doesn't already guard. |
| **J — envelope** | The result has real structure to lose — a list of records, per-item failure detail, or genuine partial-success semantics that a bare exit code can't express. | `swe-workbench-sweep-residuals`'s retained/failed worktrees as `[{path, reason}]`, not a count. |

Ask, in order:

1. **Does anything actually consume this output?** No consumer anywhere in the repo →
   out of scope, don't touch it (verify with a repo-wide grep, not a guess).
2. **Is every emitted value already a safe, `eval`-safe scalar, with any free-text
   routed around `eval`?** Yes → Tier Q. Harden with a golden-literal ratchet test
   instead of migrating; the migration cost buys nothing the ratchet doesn't already
   guard, and it isn't free — every call site's `SKILL.md` prose has to change too.
3. **Does the result need a list, nested records, or a real partial/failed state a
   bare exit code can't express?** Yes → Tier J, envelope.
4. **Otherwise, is it a single value?** Tier S, bare scalar — no `eval`, no envelope,
   just `VAR=$(producer ...)`.

Migrating a Tier Q producer to an envelope "for consistency" is not a goal in itself —
it costs real lines at every call site for no capability gain. Only migrate when the
answer to question 3 is genuinely yes.

## No dual-emit

Some migrations need a producer to emit both an old and a new shape for a transition
window — when two artifacts (a client and a server, say) can be on different versions
at once and need to interoperate mid-rollout. That scenario does not exist here: `bin/`
and `skills/` ship as one plugin release, so a producer migration and every one of its
consumers land in the same PR. There is no intermediate state where an old consumer
must still parse a producer's old output, so there is nothing for a dual-emit flag to
solve — one deliberate migration, not a flag that outlives its transition window and
becomes permanent complexity.

## Where this is enforced

- `bin/swe-workbench-result-check`'s `REGISTRY` — the schema inventory, checked against
  a golden literal in `tests/test_result_check_script.py`.
- `tests/test_bin_scripts.py`'s `SCRIPTS` dict — existence, executability, shebang, and
  sibling-resolution coverage for the checker itself, same as every other `bin/` script.

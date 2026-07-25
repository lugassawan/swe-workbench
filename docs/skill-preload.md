# Skill preload via frontmatter

Some agents open with a step that always fires — "load heuristics before reading the diff" is not conditional on what the diff contains. For those, invoking the skill via the `Skill` tool costs a full tool round-trip that buys nothing: the outcome was never in doubt. Claude Code's agent `skills:` frontmatter lets the harness inject that skill's content at dispatch time instead, before the agent's first turn.

## Which agents preload what

| Agent | Preloaded skill | Frontmatter |
|---|---|---|
| `reviewer` | `principle-code-review` | `skills:\n  - swe-workbench:principle-code-review` |
| `test-writer` | `principle-tdd` | `skills:\n  - swe-workbench:principle-tdd` |
| `refactorer` | `principle-refactoring` | `skills:\n  - swe-workbench:principle-refactoring` |

Each of these agents invokes its listed skill unconditionally on every dispatch — now preloaded via frontmatter; the body bullet is a fallback, not the primary load path. See `agents/reviewer.md`, `agents/test-writer.md`, and `agents/refactorer.md`.

## Why the body bullet stays

Preloading a skill does **not** remove its backticked `` `swe-workbench:<id>` `` reference from the agent's body. Two independent reasons:

1. `scripts/validate.py`'s `check_unwired_principle_skills` keys on that exact backticked needle to confirm every `principle-*` skill is wired into at least one agent. A YAML list entry under `skills:` is unbackticked and does not satisfy that scan — removing the body bullet would make the skill read as unwired.
2. The bullet is the fallback path. If a name is wrong or the namespace is dropped, the agent still calls the skill explicitly during its run — degraded (one extra round-trip), not silently broken.

`check_preloaded_skills` (added alongside this feature) enforces retention: an agent that preloads a skill via frontmatter but drops the backticked body reference fails validation.

## The silent-failure trap

Namespacing is not cosmetic. `swe-workbench:principle-code-review` in `skills:` frontmatter loads the skill's content at dispatch. The bare form, `principle-code-review`, silently no-ops — the agent starts with nothing preloaded and no error.

The trap: the harness's `[Agent: X] Preloaded skill '…'` debug line prints **identically** whether the namespaced or bare form was used. Seeing that line in a debug log is not evidence of successful injection — it fires regardless of whether the skill actually loaded. This was confirmed by direct spike during issue #558's investigation, and it's why `check_preloaded_skills` hard-fails any non-namespaced entry rather than warning.

## Manual verification runbook

There is no automated dispatch harness in this repo (no `claude -p` / `--debug-file` / API-credential plumbing exists across the test suite), so confirming a preload actually injected requires one manual check per changed agent:

1. Dispatch the agent (e.g. `swe-workbench:reviewer` via the `Agent` tool).
2. Ask it to report any `preload-canary` HTML comment token present in its context, verbatim.
3. Compare the reported token against the target skill's canary — e.g. `SWB-PRELOAD-PRINCIPLE-CODE-REVIEW` for `principle-code-review`.

Seeing the exact token back confirms real injection. Silence, a different token, or a refusal to find one means the preload did not take — recheck the frontmatter's namespacing before trusting the debug log.

**Caveat recorded during this feature's own PR:** dispatching `swe-workbench:reviewer` via the in-session `Agent` tool and asking it to report the canary returned no token — and a follow-up check for skill-body-unique phrases (`Five-Axis Review Lens`, `Confidence-Based Filtering`, present only inside `principle-code-review`'s body) also came back negative. That reads like a contradiction of issue #558's Spike 1, which recorded the namespaced form working — but Spike 1 dispatched via a separate OS process (`claude -p ... --debug-file`), not the in-session `Agent` tool used here. Those are plausibly two different dispatch code paths, and there's no evidence the in-session `Agent` tool honors agent-level `skills:` frontmatter the same way an out-of-process `claude -p` invocation does. This was not resolved before shipping — see the PR/issue discussion for the maintainer's call. Treat "the `Agent` tool shows no injection" as inconclusive on this mechanism's real-world behavior, not as proof it's broken; if you need a definitive answer, re-run Spike 1's exact method (`claude -p ... --debug-file`, checking the *response content* for injected skill text, not just the debug log line) rather than the in-session `Agent` tool.

Each `principle-*` skill preloaded this way carries its own canary comment immediately after the closing frontmatter `---`, e.g.:

```markdown
---
name: principle-code-review
description: …
---
<!-- preload-canary: SWB-PRELOAD-PRINCIPLE-CODE-REVIEW -->
```

The rule is mechanical: `SWB-PRELOAD-` followed by the skill id, uppercased.

## Deliberately not preloaded

- **`language-*` skills** — which language applies is unknown until the diff is read; there's nothing to preload before that.
- **The conditional `## Principle consultation` catalogs** — most entries there (`principle-security`, `principle-performance`, etc.) fire only when the diff surfaces a concern in their domain. Preloading them would load content most dispatches never use.
- **`security-auditor`'s `principle-security`** — its use is conditional by design, unlike the three agents above where the same skill fires on every single dispatch.
- **A live-dispatch CI canary** — acceptance criterion #2 from issue #558 called for a CI-enforced dispatch check. No agent-dispatch harness exists in this repo, and building one would cost more than the three-line frontmatter change it would guard. The manual runbook above is the intentionally-downgraded substitute.

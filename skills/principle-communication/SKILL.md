---
name: principle-communication
description: Caveman output mode — ultra-terse brief replies with fewer tokens. Strips filler, hedging, pleasantries. Three levels — caveman lite (default), caveman full, ultra caveman / max caveman (maximum compression). Persists until normal mode. Activate with: caveman mode, /caveman, be brief, less tokens, use fewer tokens, talk like caveman, full caveman, ultra caveman, /caveman ultra.
---

## When to invoke

Activate when the user says any of the following (case-insensitive):

| Phrase | Level activated |
|---|---|
| "caveman mode" / "talk like caveman" / "use caveman" / `/caveman` | **lite** (default) |
| "be brief" / "less tokens" / "use fewer tokens" | **lite** |
| "full caveman" | **full** |
| "ultra caveman" / "max caveman" / `/caveman ultra` | **ultra** |
| "stop caveman" / "normal mode" | off |

## Intensity ladder

### lite (default)
Drop filler and hedging. Keep articles and full sentences. Professional but tight.

Drop: pleasantries (`sure/certainly/of course/happy to`), hedging (`basically/actually/simply/just/really`), throat-clearing preambles.

Keep: `a/an/the`, complete sentences, all technical terms verbatim.

**Example — "Why does this React component re-render?"**
> Your component re-renders because you create a new object reference each render. Wrap the object in `useMemo`.

### full
Drop articles. Fragments OK. Short synonyms over verbose ones.

Drop: `a/an/the`, conjunctions where meaning holds, filler phrases. Use short synonyms: `big` not `extensive`, `fix` not `"implement a solution for"`, `use` not `utilize`.

**Example — "Why does this React component re-render?"**
> New object ref each render. Inline object prop = new ref = re-render. Wrap in `useMemo`.

### ultra
Abbreviate common prose words. Strip conjunctions. Arrows for causality. One word when one word suffices.

Abbreviate in prose: `DB`, `auth`, `config`, `req`, `res`, `fn`, `impl`, `arg`, `msg`, `ctx`. Use `→` for causality. Drop all conjunctions and prepositions where meaning is clear. Never abbreviate identifiers inside code blocks or inline backtick spans.

**Example — "Why does this React component re-render?"**
> Inline obj prop → new ref → re-render. `useMemo`.

## Rules at every level

- Code symbols, function names, API names, code blocks, and error strings are **never** abbreviated or altered.
- Maintain chosen level across all turns — no drift back to verbose prose over time.
- Level persists until the user explicitly turns it off with "stop caveman" or "normal mode".

## Persistence

Once activated, caveman mode is **active every response**. It does not revert after many turns. It remains active if you are unsure whether it still applies. It is off only when the user says "stop caveman" or "normal mode".

## Auto-clarity carve-out

Temporarily drop caveman and render full prose for:

- Security warnings
- Irreversible or destructive action confirmations (e.g. `DROP TABLE`, force-push, `rm -rf`)
- Multi-step sequences where fragment order or omitted conjunctions risk misread
- Cases where compression itself creates technical ambiguity (e.g. omitting a step from an ordered procedure)
- User asks to clarify or repeats a question

Extend this to swe-workbench destructive workflows: `swe-workbench:migrate`, `workflow-cleanup-merged`, `workflow-address-feedback` — render confirmation steps in full prose.

Resume the chosen caveman level immediately after the clear part is done.

**Example — destructive operation at any level:**

> **Warning:** This will permanently delete all rows in the `users` table and cannot be undone.
>
> ```sql
> DROP TABLE users;
> ```

_(Auto-clarity ends here — caveman level resumes.)_

Backup verified? Run it.

## Subagent scope

Caveman governs the orchestrator's user-facing output only. Subagents keep their own output style. When relaying subagent results to the user, the orchestrator renders the relay at the active caveman level.

---

Adapted from [`mattpocock/skills` caveman](https://github.com/mattpocock/skills/blob/main/skills/productivity/caveman/SKILL.md).

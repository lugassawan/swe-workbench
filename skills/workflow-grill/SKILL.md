---
name: workflow-grill
description: "Grill-me interrogation mode: relentlessly walk the decision tree one question at a time, interrogate requirements, self-answer from the codebase, exit on shared understanding or proceed — hands a Resolved-decisions block to the command's artifact step. Activated by /capture /design /implement /architect /extend /debug. Not a from-scratch design flow; produces no design doc."
orchestrator: true
---

# workflow-grill — Relentless Interrogation Mode

## What this mode is

`workflow-grill` runs in the **orchestrator** (main conversation thread), inside a command's clarify
step, **before** any subagent is delegated to. It is not a standalone workflow — it is a mode
gate activated by the interrogation prelude in the six interactive commands.

It produces one output: a `## Resolved decisions` block that the command threads into its normal
artifact/delegation step (the same way a ticket-context summary is prepended).

Because `AskUserQuestion` is a main-thread tool, this entire loop must stay in the orchestrator.
Never embed it in a shared subagent — it would leak the mode gate into flows that don't use it
(e.g. `product-manager` is shared with `/report-issue`; `senior-engineer` is consulted by
`/implement`).

## Procedure

### Step 1 — Build the decision tree

From `$ARGUMENTS` and any prepended ticket-context summary, enumerate the decisions that must be
resolved before the artifact step can produce a correct result. A decision belongs on the tree if:

- getting it wrong would require rework of the artifact, **or**
- it implies a constraint the subagent needs to know (scope, persona, tech stack, tone, reversibility).

Order decisions by dependency: decisions whose answers unblock others come first. Two-way-door
decisions (easily reversed, low blast radius) go last and may be deferred.

### Step 2 — Walk the tree, one decision at a time

For each decision in dependency order:

1. **Try the codebase first.** Search for relevant files, conventions, or patterns. If the repo
   answers the question unambiguously, resolve it immediately — state the answer and cite
   `file:line` evidence. Do **not** ask the user.

2. **Ask only when the codebase is silent or intent is the deciding factor.** Phrase the question
   as a single focused sentence. Always provide a recommended answer with brief rationale.
   - **Discrete choices** (≤4 options): use `AskUserQuestion` with the recommended option listed
     first.
   - **Open-ended** (free text, multi-factor): ask as prose and wait for a prose reply.

3. **Record the resolution** (user answer, codebase evidence, or assumed default).

4. **Recurse** — re-evaluate remaining decisions in light of what was just resolved; drop any that
   are now settled, add any that were unlocked.

Never batch questions. One question per turn.

### Step 3 — Exit conditions

Stop interrogating when **any** of the following is true:

| Condition | Action |
|-----------|--------|
| Decision tree is exhausted | Proceed to handback |
| User says "proceed", "go", "that's enough", or equivalent | Take recommended defaults for all remaining non-trivial decisions; list assumed defaults in the handback block |
| All remaining decisions are two-way doors with clear defaults | Resolve them from defaults; proceed to handback |

### Step 4 — Handback

Emit exactly one fenced block:

```
## Resolved decisions

- <decision label>: <resolved value> — source: <user | codebase file:line | assumed default>
- <decision label>: <resolved value> — source: <user | codebase file:line | assumed default>
…
```

Then return control to the command. The command threads this block into its artifact/delegation
step (prepended to the subagent context or plan). The subagent must **not** re-ask questions
already resolved here.

## Codebase-self-answer rule

Before surfacing any question, run a targeted search: grep for relevant symbols, patterns, or
config keys. If the answer is unambiguous, resolve silently with a one-line citation. Only ask
when:

- The search returns nothing relevant, **or**
- The intent behind the choice is the deciding factor (e.g. "which persona should this serve?")
  and the repo cannot answer that.

Cite evidence precisely: `path/to/file:42`, not "I found it in the codebase."

## Boundary — workflow-grill vs superpowers:brainstorming

| Dimension | `workflow-grill` | `superpowers:brainstorming` |
|-----------|------------------|-----------------------------|
| Entry point | Inside a scoped command's clarify step | From-scratch idea → design-doc flow |
| Trigger | `--grill` flag or "grill me" in a command invocation | Before entering plan mode on a new idea |
| Output | `## Resolved decisions` block handed back to the command | Approved design doc on disk |
| Hard gate | None — hands off, does not block | Blocks implementation until design doc approved |
| Produces design doc | No | Yes |
| Runs in orchestrator | Yes (AskUserQuestion required) | Yes |

If a user invokes a command with `--grill` on a genuinely under-specified from-scratch idea,
complete the grill loop first, then note in the handback that a full brainstorm may be warranted —
but do not block on it.

---

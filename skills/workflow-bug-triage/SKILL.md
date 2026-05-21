---
name: workflow-bug-triage
description: Use when investigating a bug to root-cause and FILE a GitHub issue rather than fixing immediately — counterpart to /swe-workbench:debug (which patches). Enforces the Iron Law (no patches without root cause), runs a 4-phase loop (Investigation, Pattern Analysis, Hypothesis, File issue), and produces a structured issue with code-path table and impact assessment.
orchestrator: true
---

# Workflow: Bug Triage (investigate + file issue)

**Announce at start:** "I'm using the workflow-bug-triage skill to investigate the root cause and file a GitHub issue."

## When to invoke

- The user describes a bug, defect, or unexpected behaviour and wants it documented (not fixed in-session).
- Phrases: "investigate this bug", "find the root cause", "file an issue for this bug", "triage this".
- The bug is in code the user does not own, or fix-planning needs to happen separately.
- The investigation needs to produce a shareable artifact (an issue) other people will act on.

## When NOT to invoke

- The user wants a fix **now** → use `/swe-workbench:debug` (counterpart skill that ends in code change + regression test).
- The root cause is already known and only the fix is needed → use `/swe-workbench:debug`.
- The user is capturing a feature request, idea, or improvement (not a bug) → use the `/capture` command directly.
- The user is reviewing already-merged code for retroactive issues → use `/swe-workbench:review` first.

## Iron Law

**NO FIXES WITHOUT ROOT CAUSE FIRST.**

If the user proposes a fix before the root cause is established, refuse politely:

> "I'd like to find the root cause before suggesting a fix — otherwise we risk piling band-aids on a deeper issue. Can I run the investigation first?"

Red flags that mean STOP investigating-by-fixing and return to Phase 1:
- "Quick fix for now…"
- "Just try changing X…"
- "It's probably X, let me patch it."
- "Let me just patch this and move on."
- "Looks like a typo, just fix it."
- "We can fix it later, just suppress the warning."

A symptom is not a cause. A patch that hides a symptom is a regression hiding behind a green test.

## Composition

For the inner investigation loop (read-before-guessing, reproduce-before-theorizing, falsify-before-fixing), defer to `superpowers:systematic-debugging` via the `Skill` tool — same delegation pattern as `agents/debugger.md`.

If `superpowers:systematic-debugging` is unavailable, run the same loop inline — never skip it.

## Checkpoint behavior

After entering each phase, write the workflow state file so the investigation can survive auto-compaction (see `docs/workflow-state.md` for the schema and path). After Phase 4 (issue filed), delete the state file.

## 4-phase flow

### Phase 1 — Investigation

Goal: gather enough context to form testable hypotheses.

1. **Read errors carefully.** Quote the exact error/log line, including stack frames. Don't paraphrase.
2. **Reproduce reliably.** If you cannot reproduce, ask the user for one of: minimal repro steps, environment details, or a video/log dump. **Do not hypothesize without a repro.** A hypothesis without a repro is a guess.
3. **`git log -- <files>` blame the suspect lines.** Recent changes are the most likely cause.
4. **Trace data flow.** Walk the input from the entry point to the failure site. Use `Grep` to find callers. Use `Glob` to find sibling modules.
5. **List symptoms.** All of them — "the form silently submits empty, AND the success toast still fires, AND the API returns 200" is one bug; "the form doesn't validate" is incomplete framing.

### Phase 2 — Pattern Analysis

Goal: find the contrast between what works and what doesn't.

1. **Find a working analogue in this codebase.** Not from training data — a sibling handler, a parallel test, a previous version of the same function. Cite the path.
2. **Read the working example completely.** Not skimmed — every branch, every guard, every comment.
3. **List every difference between the working and broken code paths.** Path differences. Type differences. Order-of-operations differences. Missing-call differences.
4. **The contrast IS the diagnosis.** The unique difference is your root-cause candidate. If there are multiple differences, rank by likelihood of mattering.

### Phase 3 — Single hypothesis

Goal: state one testable hypothesis that explains every symptom.

Format:
> "Root cause is **X** because evidence **Y** shows **Z**, which would cause symptoms A, B, and C."

Constraints:
- **Single hypothesis.** Not "either X or Y". If you have two candidates, run an experiment to falsify one.
- **Explains ALL symptoms.** If your hypothesis explains 4 of 5 symptoms, it is **wrong about #5**. Refine, don't bandage.
- **Falsifiable.** State the test that would prove it wrong: "If I change line 88 to `throw` instead of `return null`, the form should reject the empty payload."

If the hypothesis fails to explain one symptom, return to Phase 1 with that symptom as the new entry point. **Do not** add a second hypothesis on top of the first.

### Phase 4 — File issue

Goal: produce a structured GitHub issue that documents the diagnosis.

1. **Discover the issue template.** Read `.github/ISSUE_TEMPLATE/bug_report.md` if it exists. If not, use the default body shape below.

   **Discover labels.** Run `gh label list --json name -q '.[].name'`. Bug-triage defaults to `bug`. If `bug` exists in the repo label list, use it. If not, pick the first label whose name case-insensitively contains "bug" (e.g. `bug-report`, `kind/bug`). If still no match, omit `--label` and warn in the preview ("No bug-like label found; filing without label"). Surface the chosen label (or absence) in the preview so the user can change it before replying `confirm`.
2. **Augment the template** by prepending the Root-Cause / Pattern-Analysis / Impact sections. **Do NOT use `gh issue create --template`** — that gives the user no in-skill editing. Use `--body-file` instead, mirroring `agents/product-manager.md`.
3. **Render the body** using the schema below.
4. **Preview-gate-then-confirm.** Print the body, the title, the target repo, and the `gh issue create` command. Wait for user to reply `confirm`. **Do NOT** run `gh issue create` until the user replies.
5. **On `confirm`**, run the **exact** `gh issue create` command as printed in the preview above — do not regenerate or rephrase it. Return the issue URL.

## Output: issue body schema

```markdown
## Problem Description
<2–3 sentences in user-pain language; not "the foo() function returns null" but
"users clicking 'submit' on an empty form see no error and assume it worked.">

## Reproduction
<exact steps, env, version>

## Root Cause Analysis

**Hypothesis:** <single sentence>

**Code path:**
| Path:Line | Role |
|-----------|------|
| `path/to/handler.ts:42` | entry — receives the empty payload |
| `path/to/validator.ts:88` | branch — silently returns `null` instead of throwing |
| `path/to/api.ts:117` | exit — treats `null` as "success" |

**Evidence:** <log line, stack frame, or test output that confirms the path>

## Pattern Analysis

Working example in this codebase: `path/to/working-handler.ts`. Differences:
- <bullet 1 — concrete difference>
- <bullet 2 — concrete difference>

## Recommended Fix
<2–4 bullets — recommendation, not patch. The fix is a separate `/swe-workbench:debug`
or `/swe-workbench:implement` invocation.>

## Impact Assessment

| Field | Value |
|-------|-------|
| Severity | Critical / High / Medium / Low |
| Affected flows | <user-visible flows> |
| Risk of fix | Low / Medium / High |
| Backward-compatible | Yes / No |
```

## Issue-filing command

```bash
gh issue create \
  --title "[bug] <short subject>" \
  --body-file /tmp/swe-workbench-bug-triage-<repo-slug>-<unix-ts>.md \
  --label "bug"
```

Omit `--label` when no `bug`-like label exists in the repo.

Always preview-gate-then-confirm (mirrors `commands/capture.md`). The skill MUST:
1. Run `gh repo view --json nameWithOwner -q '.nameWithOwner'` to confirm target repo.
2. Print: filing target, title, **chosen label** (or "none — no matching label"), body (code-fenced), and the exact command. Tell the user they may change the label before replying `confirm`.
3. Wait for `confirm`. Reject any other reply (re-prompt).
4. On `confirm`, run the command and return the issue URL.

## Boundary vs `/debug`

| Aspect | `/swe-workbench:debug` | `workflow-bug-triage` |
|--------|------------------------|------------------------|
| Terminal artifact | Code change + regression test (in-session) | GitHub issue (filed, not fixed) |
| Has `Edit` tool | Yes (debugger agent) | No (skill orchestrates investigation only) |
| Use when | Bug is yours, fix-now is the goal | Bug needs documentation, fix-planning is separate |
| Composes | `superpowers:systematic-debugging` | `superpowers:systematic-debugging` |

If you start in `/debug` and realize the fix is bigger than the session allows, finish the investigation, surface the recommendation, and tell the user: "This bug deserves a separate issue and PR — want me to file it via `workflow-bug-triage`?"

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Hypothesise without a repro | Stop. Ask the user for repro steps or env details. A hypothesis without a repro is guessing. |
| Pile fixes on top of a partial hypothesis | Refine the hypothesis until it explains every symptom. Don't bandage. |
| Skip Pattern Analysis ("I already know the bug") | Always find the working analogue. The contrast is the diagnosis — your gut feel is not. |
| File the issue without preview-gate | Always print the body and wait for `confirm`. Issues are public artifacts. |
| Use `gh issue create --template` | Use `--body-file` so the skill controls the full body (Root Cause + Pattern Analysis + Impact). |
| Quote training-data examples as the working analogue | Always cite paths IN THIS CODEBASE. Training-data examples are not evidence. |

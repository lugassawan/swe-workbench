---
description: Capture an idea, improvement, or bug as a well-framed GitHub issue (works in any repo)
argument-hint: <one-line thought>
---

The user wants to capture: $ARGUMENTS

Delegate to the `product-manager` subagent. Its response must deliver all of the following before any issue is filed:

1. **Auth + repo detection.** Run `gh auth status`, then `gh repo view --json nameWithOwner -q '.nameWithOwner'`. Surface the detected repo in the preview as `Filing into: <owner>/<repo>`. If either command fails, bail with a clear single-line message ("Repo detection failed: <reason>. Run `gh repo view` to diagnose.") and stop.

2. **Restatement.** One sentence in the user's domain language confirming the thought. If the thought is ambiguous, ask exactly one clarifying question before continuing.

3. **Product framing** — four lenses applied with brevity:
   - **Problem.** User pain or constraint, stated as the user's pain — not the feature.
   - **Value.** Who benefits and how. One "so-what" sentence.
   - **Acceptance criteria.** 2–4 bullets (Given/When/Then or simple bullets).
   - **Impact / Effort (RICE-lite).** `Impact: S/M/L` and `Effort: S/M/L`, one sentence each.

4. **Template discovery.** List `.github/ISSUE_TEMPLATE/` filtered to `*.md`, skipping `config.yml`. Read each template's frontmatter and first ~20 body lines. Classify the thought into the closest-fit template with a one-sentence reason, or note "No issue templates found; using default body shape" when none exist.

5. **Label discovery.** Run `gh label list --json name -q '.[].name'` to get the repo's available labels. If the command fails or returns empty output, treat the label list as empty and proceed directly to step d (no match → omit `--label`). Otherwise select a label using this chain:

   a. **Template frontmatter:** if the chosen template has a `labels:` field and that value exists verbatim in the repo's label list, use it.
   b. **Fallback — substring match (case-insensitive):** if the frontmatter label is not present verbatim, pick the first repo label whose name case-insensitively contains (or is contained by) the template's value.
   c. **No template chosen:** map by commit-tag — `[feat]` → `enhancement`, `[bug]` → `bug`, `[chore]` → `documentation` — then apply the same chain against the repo's label list. If no commit-tag is recognisable in the user's input, proceed directly to step d.
   d. **No match found:** omit `--label`; record this so the preview can warn the user ("No matching label found; filing without label").

6. **Duplicate scan.** `gh issue list --search "<2-3 keywords>" --state open --limit 5`. Surface matches. Ask before drafting if any look duplicative.

7. **Draft.** With a template: fill its sections, prepend `## Product framing`. Without a template: use `## Problem` / `## Value` / `## Acceptance criteria` / `## Impact / Effort` / `## Additional context`.

8. **Preview gate.** Obtain a Unix timestamp once (`date +%s`) and reuse it — never re-derive or re-glob. Write the body to `/tmp/capture-<repo-slug>-<unix-timestamp>.md` using the `Write` tool (not a Bash heredoc). Also write a one-line command to `/tmp/capture-<repo-slug>-<unix-timestamp>.cmd` using the `Write` tool: when a label was matched, write `gh issue create --title "..." --body-file <path> --label "<matched-label>"`; when no label was matched, write `gh issue create --title "..." --body-file <path>` (no `--label` segment). Then print:
   ```
   Filing into: <owner>/<repo>
   Template: <chosen template> | none — default body
   Title: <drafted title>
   Label: <chosen label> | none — no matching label found
   Possibly related: <#N list, or "none">

   Body:
   <code-fenced body>

   Command: gh issue create --title "<title>" --body-file <path> --label "<chosen-label>"

   Reply 'confirm' to file, or edit any of the above (including the label) and I'll redraft.
   ```
   When no label was matched, drop the `--label "<chosen-label>"` segment from the `Command:` line. **Wait for the user to reply `confirm`. Do NOT run `gh issue create` on this turn.**

9. **File on confirm.** Only when the user replies `confirm`, read the command from the `.cmd` sidecar written in step 8 and run it exactly as written — do not regenerate the title or path. Return the issue URL.

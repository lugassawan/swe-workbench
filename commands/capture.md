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

5. **Duplicate scan.** `gh issue list --search "<2-3 keywords>" --state open --limit 5`. Surface matches. Ask before drafting if any look duplicative.

6. **Draft.** With a template: fill its sections, prepend `## Product framing`. Without a template: use `## Problem` / `## Value` / `## Acceptance criteria` / `## Impact / Effort` / `## Additional context`.

7. **Preview gate.** Write the body to `/tmp/capture-<repo-slug>-<timestamp>.md`, then print:
   ```
   Filing into: <owner>/<repo>
   Template: <chosen template> | none — default body
   Title: <drafted title>
   Possibly related: <#N list, or "none">

   Body:
   <code-fenced body>

   Command: gh issue create --title "<title>" --body-file <path>

   Reply 'confirm' to file, or edit any of the above and I'll redraft.
   ```
   **Wait for the user to reply `confirm`. Do NOT run `gh issue create` on this turn.**

8. **File on confirm.** Only when the user replies `confirm`, run the exact printed command and return the issue URL.

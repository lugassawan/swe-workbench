---
description: Capture an idea, improvement, or bug as a well-framed GitHub issue (works in any repo)
argument-hint: <one-line thought> [--grill | --standard]
---

<!-- swb-phase: plan -->

The user wants to capture: $ARGUMENTS

**Interrogation mode.** Before producing anything, resolve the mode:

- **Explicit signal in the invocation is honored without asking.** grill-me = `--grill`, "grill me", or "grill-me mode". standard = `--standard`, "standard", or "quick". Strip the signal from $ARGUMENTS and record the resolved mode.
- **No explicit signal:** ask via `AskUserQuestion` — one question, header "Mode", options **Standard** (recommended, listed first) and **Grill me**. Standard description: "Lightweight clarify — a restatement and at most one question, then proceed." Grill-me description: "Relentlessly walk the decision tree one question at a time, each with a recommended answer, self-answering from the codebase where possible." Use the user's choice.

**Standard mode:** proceed with the command's existing lightweight clarify (a restatement and at most one clarifying question) — do not ask the mode question again.

**Grill-me mode:** activate `swe-workbench:workflow-grill` and run its interrogation loop to completion (exit on shared understanding or when the user says "proceed"). Then thread the emitted `## Resolved decisions` block into the command's normal artifact/delegation step below — the same way a ticket-context summary is prepended — and continue as in standard mode.

Delegate to the `swe-workbench:product-manager` subagent. Its response must deliver all of the following before any issue is filed:

1. **Auth + repo detection.** Run `gh auth status`, then `gh repo view --json nameWithOwner,visibility`. Surface the detected `nameWithOwner` in the preview as `Filing into: <owner>/<repo>`. Record the `visibility`: the redactor (step 6) runs on every draft **unless visibility is affirmatively `PRIVATE` or `INTERNAL`**, so a `PUBLIC` repo, a missing field and any other or unknown value all redact. If `gh` rejects the `visibility` field (an older `gh`), retry with `--json nameWithOwner` and treat the visibility as unknown. If either command otherwise fails, bail with a clear single-line message ("Repo detection failed: <reason>. Run `gh repo view` to diagnose.") and stop.

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

6. **Draft.** With a template: fill its sections, prepend `## Product framing`. Without a template: use `## Problem` / `## Value` / `## Acceptance criteria` / `## Impact / Effort` / `## Additional context`. Write the title as one line. Obtain a Unix timestamp once (`date +%s`) and reuse it for every file below — never re-derive or re-glob. The files that get filed are `<title-path>` = `/tmp/capture-<repo-slug>-<unix-timestamp>.title` and `<body-path>` = `/tmp/capture-<repo-slug>-<unix-timestamp>.md`.

   **Redaction pass (privacy guard).** A public issue is public text, so a deterministic script sanitizes it — never redact by eye. Skip this pass only when step 1 found the repo affirmatively `PRIVATE` or `INTERNAL`; then write the title straight to `<title-path>` and the body to `<body-path>` (below) with the `Write` tool and go on to step 7. Otherwise, with the `Write` tool (not a Bash heredoc), write the title to `/tmp/capture-<repo-slug>-<unix-timestamp>.title.draft` and the body to `/tmp/capture-<repo-slug>-<unix-timestamp>.draft.md`. The script never overwrites a draft, so an edit can always re-run from it. Only when the user explicitly says that some wording must stay verbatim in the public text (typing the thought is not enough), also write that wording — one span per line — to `/tmp/capture-<repo-slug>-<unix-timestamp>.preserve`; otherwise write no `.preserve` file. A preserved span never exempts local paths, IPs or the local username. Also write a `….deny` file — one `CATEGORY=TERM` per line, `CATEGORY` being one of `org`, `repo`, `service`, `memory`, `user`, `host`, `ticket` — naming every private organisation, product, customer, team, service or tracker key you used while drafting that the environment cannot reveal (a company named in the conversation, an internal project name). The script cannot redact a name it is never told, so this list is how your knowledge of what is private reaches it; skip the file when there is nothing to list. Then:
   ```bash
   command -v swe-workbench-redact >/dev/null 2>&1 || {
     echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
     exit 1
   }
   REDACTED=$(swe-workbench-redact --target-repo <nameWithOwner> \
     --preserve-file <preserve-path> \
     --deny-file <deny-path> \
     --field title <title-draft-path> <title-path> --field body <body-draft-path> <body-path> \
     | swe-workbench-result-check swb.redact/1) || exit 1
   ```
   Drop `--preserve-file` when no `.preserve` file was written, and `--deny-file` when no `.deny` file was written. The redactor writes the sanitized `<title-path>` and `<body-path>`. A non-zero exit means nothing was written: report the failure and stop — never file an unsanitized draft. Read `.data.summary` with `printf '%s' "$REDACTED" | jq -r '.data.summary'` and print each `.warnings[]` as a one-line warning. The script keeps the target repo's own URLs and `#N` references, this plugin's names and public documentation domains; it replaces credentials, emails, other URLs and hosts, IPs, local paths, memory references, service ids, other org/repo names, tracker keys and the local username, using the placeholders `[redacted-token]`, `[internal-email]`, `[internal-host]`, `[internal-ip]`, `[local-path]`, `[memory-ref]`, `[internal-service]`, `[internal-repo]`, `[internal-org]`, `[internal-ticket]` and `[local-user]`. Wording the user said must stay verbatim is protected by `--preserve-file` — except credentials, local paths, IPs and the local username, which are always replaced.

7. **Duplicate scan.** Extract 2–3 keywords: from the **sanitized title** (`<title-path>`) when the redactor ran — never the raw thought or the draft, because the keywords are sent to GitHub — and from the drafted title otherwise. Skip any word that belongs to a `[placeholder]`. Strip each keyword to `[a-zA-Z0-9_-]` only (drop shell metacharacters, quotes, and flags) and single-quote them when building the search string. Then run `gh issue list --search '<sanitized keywords>' --state open --limit 5`. Surface matches. Ask before previewing if any look duplicative.

8. **Preview gate.** Reuse the timestamp from step 6. Write a one-line command to `/tmp/capture-<repo-slug>-<unix-timestamp>.cmd` using the `Write` tool: when a label was matched, write `gh issue create --title "$(cat <title-path>)" --body-file <body-path> --label "<matched-label>"`; when no label was matched, write `gh issue create --title "$(cat <title-path>)" --body-file <body-path>` (no `--label` segment). The title is read back from its file, so a sanitized title is never re-typed. Then print:
   ```
   Filing into: <owner>/<repo>
   Template: <chosen template> | none — default body
   Title: <sanitized title>
   Label: <chosen label> | none — no matching label found
   Redacted: <data.summary — categories and counts only, never the removed values> | skipped — private repository
   Possibly related: <#N list, or "none">

   Body:
   <code-fenced sanitized body>

   Command: gh issue create --title "$(cat <title-path>)" --body-file <body-path> --label "<chosen-label>"

   Reply 'confirm' to file, or edit any of the above (including the label) and I'll redraft.
   ```
   When no label was matched, drop the `--label "<chosen-label>"` segment from the `Command:` line. **Wait for the user to reply `confirm`. Do NOT run `gh issue create` on this turn.**

   **Edit loop.** Any edit — a user change to the title or body, `restore X`, or an agent redraft — is applied to the *draft* files (`.title.draft` / `.draft.md`; on a private repo, the `<title-path>` / `<body-path>` files directly). When the redactor ran, the agent then re-runs the redactor with the step 6 command and re-renders this preview; every edit requires a fresh `confirm`, never file immediately after one. `restore X` names a placeholder or the text it replaced (resolve it from the draft; never print a removed value into the preview), and the term goes back to the redactor as `--allow <term>`, carrying forward every earlier `--allow` term of this draft. A label edit also rewrites the `.cmd` sidecar, or filing would use the old label. Credentials can never be restored.

9. **File on confirm.** Only when the user replies `confirm` after the last edit, read the command from the `.cmd` sidecar written in step 8 and run it exactly as written — do not regenerate the title or path. Return the issue URL. After a successful `gh issue create`, delete the temp files: `swe-workbench-clean-state-files "/tmp/capture-<repo-slug>-<unix-timestamp>.md" "/tmp/capture-<repo-slug>-<unix-timestamp>.title" "/tmp/capture-<repo-slug>-<unix-timestamp>.draft.md" "/tmp/capture-<repo-slug>-<unix-timestamp>.title.draft" "/tmp/capture-<repo-slug>-<unix-timestamp>.preserve" "/tmp/capture-<repo-slug>-<unix-timestamp>.deny" "/tmp/capture-<repo-slug>-<unix-timestamp>.cmd" 2>/dev/null` (substituting the actual paths; a file that was never written is fine). On failure, leave the files for retry.

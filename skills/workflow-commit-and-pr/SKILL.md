---
name: workflow-commit-and-pr
description: Use when the user wants to commit staged changes or create a PR — enforces trigger-phrase discipline (preview vs commit vs ship), the [type] commit format, branch-naming check, [no ci] auto-appended on docs-only commits, draft-vs-ready PR prompt, and PR template detection. Pre-merge counterpart to workflow-cleanup-merged.
orchestrator: true
---

# Workflow: Commit and PR (pre-merge orchestration)

**Announce at start:** "I'm using the workflow-commit-and-pr skill to {commit / draft a PR / ship this branch}."

## When to invoke

- The user wants to commit staged changes ("commit this", "make a commit").
- The user wants to create a PR ("open a PR", "ship this", "create a pull request").
- The user announces feature completion ("I'm done", "I finished the feature", "feature is complete") — preview-only mode.
- The user references a ticket key (`[A-Z]+-\d+`, atlassian/Confluence/GitHub URL) AND wants to commit/PR — chains `swe-workbench:ticket-context` first.

## When NOT to invoke

- The PR is already merged → use `swe-workbench:workflow-cleanup-merged` for post-merge cleanup.
- The user wants to amend or rebase an existing commit → out of scope; do not amend or force-push.
- The user is staging files only (`git add`) with no commit intent → no skill needed.
- `workflow-development` Phase 5 is currently driving the flow → that path invokes `swe-workbench:workflow-commit-and-pr` directly (do not interpose).

## Trigger-phrase discipline

The user's exact phrasing determines what action you take. **Never escalate without explicit user words.**

| Phrase class | Examples | Action |
|---|---|---|
| **Preview only** | "I finished the feature", "I'm done", "feature is complete", "ready to commit" | Show: diff summary, drafted commit message, current branch name, doc-only `[no ci]` check. **Do NOT commit.** Wait for user to escalate to "commit this" or "ship this". |
| **Commit only** | "commit this", "make a commit", "commit these changes" | Run `git commit` with the drafted message. **Stop.** Do NOT push. Do NOT create a PR. Tell the user: "Committed. Reply `push` to push, or `ship` to push and open a PR." |
| **One-shot ship** | "commit and create a PR", "ship this", "ship it", "ship this branch" | Run commit → push → `gh pr create`. No intermediate pause. Run draft-vs-ready prompt before `gh pr create`. |

Ambiguous wording: **default to preview-only** and ask the user to escalate.

## Codified commit format

**Detect commit format.** Probe the host repo before authoring any commit message:

1. If `.githooks/commit-msg` exists (or `.git/hooks/commit-msg` symlinked from `core.hooksPath`), read it and **quote the regex verbatim** from the hook file — do not re-derive. Examples of conventions you may detect:
   - `[type] Subject` (swe-workbench plugin style) — enforced by the regex below
   - `type(scope): subject` (Conventional Commits)
   - `JIRA-123: subject` (JIRA-prefix style)
   Apply whichever convention the hook enforces for this host repo.
2. If no commit-msg hook exists, infer convention from `git log --oneline -10`. Default to Conventional Commits if no pattern dominates.
3. If both fail (new repo, empty history), ask the user which convention to follow.

**When the host repo uses the swe-workbench plugin's `[type] Subject` convention**, the enforcing regex is (load-bearing — quote, do not re-derive):

```
^\[(feat|fix|refactor|test|ci|docs|perf|chore|polish|breaking)\] .+
```

| Type | Use for |
|------|---------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Behaviour-preserving code change |
| `test` | Test-only change |
| `ci` | CI / GitHub Actions change |
| `docs` | Documentation-only change (markdown, README, etc.) |
| `perf` | Performance improvement |
| `chore` | Tooling, deps, housekeeping |
| `polish` | Small cleanup, cosmetic |
| `breaking` | Breaking change |

**Subject rules** (sync with `.githooks/commit-msg` if the regex tightens):
- Imperative mood: "Add foo" not "Added foo" or "Adds foo".
- ≤50 characters (soft limit; hard wrap on body at 72).
- No trailing period.
- Optional scope as a colon-prefix inside subject: `[chore] cleanup-merged: sync local main first`.

**Sync source:** `.githooks/commit-msg` is canonical. If a commit fails the hook, re-read the hook (don't guess).

## Branch-naming check

Convention: `<type>/<kebab-description>` where `<type>` is the same set as commit types.

Behaviour:
- If current branch is `main` or `master` → **warn** the user (`.githooks/pre-commit` will block the commit anyway): "You're on `main`. Switch to a feature branch first: `git checkout -b feat/<topic>`."
- If branch doesn't match `<type>/<kebab>` → **warn-only** (don't auto-rename): "Branch `<name>` doesn't match the `<type>/<kebab>` convention. Continue anyway? Reply `yes` or rename first."
- If branch matches → silent.

## Pre-commit gate: suspicious staged files

Before the commit preview (or before running `git commit`), scan the staged
file set for filenames that commonly hold secrets. This is a commit-layer
twin of the PreToolUse Write/Edit hook: that hook catches secrets the agent
introduces at authoring time; this gate catches secrets staged by anyone (a
human running `git add`, an IDE that auto-stages, or any other tool) before
commit.

The scan is a filename heuristic, not a content scan — it cannot catch a
secret pasted inside an otherwise innocuous `config.yaml`. False negatives
are expected; treat a clean scan as "no obvious filename red flags", not
"safe to commit".

**Scan command** (run before `[no ci]` is computed):

```bash
SUSPICIOUS=$(git diff --staged --name-only \
  | grep -iE '(^|/)([^/]*\.env(\.|$)|.+\.pem$|.+\.key$|credentials\.json$|secrets?\.[a-z]+$)' \
  | grep -ivE '\.(example|sample|template|dist)$' \
  || true)
```

The exclusion pass (`*.example`, `*.sample`, `*.template`, `*.dist`)
prevents false-positives on `.env` template variants (e.g. `.env.example`,
`.env.sample`). Files like `secrets.example.yaml` are already excluded by
the positive pattern (which requires a single trailing extension), so the
exclusion pass is not their gate.

**On no matches** → silent; continue to `## Doc-only [no ci] rule`.

**On match**, print the file list verbatim to the user, then call
`AskUserQuestion`:

```json
{
  "questions": [{
    "question": "Staged files have names that commonly contain secrets. Commit anyway, or cancel?",
    "header": "Suspicious",
    "multiSelect": false,
    "options": [
      { "label": "Commit anyway", "description": "Files were reviewed and are intentional — proceed to the commit preview." },
      { "label": "Cancel",        "description": "Abort. No commit is made. Staging is NOT touched — unstaging is the user's call." }
    ]
  }]
}
```

- **`Commit anyway`** → continue to `## Doc-only [no ci] rule` and the
  normal commit flow.
- **`Cancel`** → abort the flow. **Do NOT run `git restore --staged`** or
  otherwise alter the index. The user inspects and unstages on their own.
  If the user re-invokes the skill after staging changes, the scan re-runs
  cleanly — no state machine.

## Doc-only `[no ci]` rule

When ALL staged paths match doc-only patterns, append ` [no ci]` to the commit subject:

```
Doc-only patterns:
  - *.md AND NOT under commands/, skills/, agents/      (e.g. README.md, root-level *.md)
  - docs/**
  - .github/*.md  (direct children of .github/ only — not subdirs like ISSUE_TEMPLATE/)
```

**Exclusion is load-bearing.** Markdown under `commands/`, `skills/`, `agents/` is plugin behaviour — changing those files changes the plugin's runtime, even though the file extension is `.md`. Never apply `[no ci]` to those.

How to test the staged set:
```bash
TOTAL=$(git diff --staged --name-only | wc -l)
MATCHED=$(git diff --staged --name-only | grep -Ev '^(commands|skills|agents)/' | grep -E '\.md$|^docs/|^\.github/[^/]*\.md$' | wc -l)
[ "$MATCHED" -eq "$TOTAL" ] && echo "[no ci] applies" || echo "[no ci] does NOT apply"
```

If every staged path matches (`MATCHED == TOTAL`), append ` [no ci]`. Otherwise, do not.

**Detect `[no ci]` behaviour.** Whether per-PR `[no ci]` is honoured depends on the host repo's CI configuration:

- If `.github/workflows/` exists, grep each PR-triggering workflow for `[no ci]` / `skip-ci` / `ci-skip` markers in `if:` conditions. If none honour the marker, warn the user: "Per-PR `[no ci]` will not skip CI — the marker is per-commit only. If all commits in a docs-only PR have `[no ci]`, the CI still runs on the PR."
- If the host uses GitLab CI, note that the equivalent marker is `[ci skip]` or `[skip ci]` in the commit message.
- If the host uses Bitbucket Pipelines or other CI, check its docs for the skip marker.

**Note for the swe-workbench plugin repo specifically:** `.github/workflows/pr.yml` has no `[no ci]` guard at the PR level. The marker is per-commit only in that repo.

## Project Detection

Run during activation to populate workflow with project-specific values.

**Detection markers** used by this skill:
- `pr-template-path` — absolute path of the detected PR template.

```bash
# PR template — check common locations
for cand in .github/PULL_REQUEST_TEMPLATE.md .github/pull_request_template.md docs/pull_request_template.md; do
  [ -f "$cand" ] && echo "$(pwd)/$cand" && break
done
```

If no template is found, use a heredoc fallback.

## Pre-check: existing PR for this branch

Before running `gh pr create`, check whether an OPEN PR already exists for this branch:

```bash
PR_INFO=$(gh pr view --json url,state -q '.state + "\t" + .url' 2>/dev/null || true)
PR_STATE=$(echo "$PR_INFO" | cut -f1)
PR_URL=$(echo "$PR_INFO"   | cut -f2)
```

Filter: act only when `PR_STATE == "OPEN"`. Ignore `CLOSED` or `MERGED` PRs — those do not block new-PR creation.

If an OPEN PR is found, call `AskUserQuestion` with:

```json
{
  "questions": [{
    "question": "An open PR already exists for this branch. Update it or cancel?",
    "header": "Existing PR",
    "multiSelect": false,
    "options": [
      { "label": "Update existing PR", "description": "New commits are already on the branch — skip gh pr create and use the existing PR URL." },
      { "label": "Cancel",             "description": "Abort the flow. No PR is created or modified." }
    ]
  }]
}
```

- **`Update existing PR`** → skip `gh pr create`. Use the existing PR URL in all output. Run the Post-create CTA (offer `/review`) against the existing PR number.
- **`Cancel`** → abort. Print the existing PR URL for reference.

If no OPEN PR is found → proceed to the `## Draft vs ready prompt` step normally.

## Draft vs ready prompt

Before running `gh pr create`, call the `AskUserQuestion` tool with:

```json
{
  "questions": [{
    "question": "Open this PR as draft or ready for review?",
    "header": "PR mode",
    "multiSelect": false,
    "options": [
      { "label": "Ready for review", "description": "Default; runs `gh pr create`" },
      { "label": "Draft",            "description": "Adds `--draft` flag; hides from reviewers" }
    ]
  }]
}
```

Map the `Draft` answer → append `--draft` to `gh pr create`. Any other
answer (including `Ready for review` and the free-text `Other` channel) →
no flag. If the user supplies an `Other` reply that signals abort/cancel,
stop and re-confirm before running `gh pr create`.

## Ticket-context chain

If the prompt OR current branch name OR last-5 commit messages mention a ticket reference, invoke `swe-workbench:ticket-context` BEFORE drafting the PR title/body. Recognised refs:
- Jira keys: `[A-Z]+-\d+`
- Atlassian URLs: `*.atlassian.net/...`
- Confluence URLs: `*.atlassian.net/wiki/...`
- GitHub: `github.com/<owner>/<repo>/issues/\d+`, `github.com/<owner>/<repo>/pull/\d+`, `#\d+`

Prepend the ticket-context summary to the PR body so the reviewer has the full spec.

## Post-create CTA

After `gh pr create` succeeds and prints the PR URL, append:

> "Want me to run `/review` on this PR? Reply `yes` to proceed."

If user replies `yes` → invoke `/swe-workbench:review <N>` with the new PR number.

## Failure modes

| Failure | Signal | Action |
|---|---|---|
| No staged changes | `git diff --staged` empty | Abort. Tell user to `git add` first. |
| Commit hook fails (bad subject) | Non-zero exit on `git commit` | Re-read `.githooks/commit-msg`, refine subject, re-attempt. **Do NOT use `--no-verify`.** |
| Branch is `main`/`master` | `git rev-parse --abbrev-ref HEAD` | Abort. Pre-commit hook will block; tell user to checkout a feature branch. |
| `gh auth status` fails | Non-zero exit | Abort. Print fix hint: `gh auth login`. |
| `gh pr create` fails on PR-template body validation | CI rejects empty `Closes #` | Re-read `.github/PULL_REQUEST_TEMPLATE.md` instructions; substitute `Closes #<issue>` or standalone `Issue: N/A — <reason>`; re-attempt. |
| `git push` rejected (non-FF) | Non-zero exit | Abort. Tell user to `git pull --rebase`; do NOT force-push. |
| Doc-only `[no ci]` rule mis-triggers (ambiguous case) | User disagrees | Skip `[no ci]` and warn. The doc-only rule is conservative — when in doubt, run CI. |
| Duplicate PR (already exists) | `gh pr view` returns `state == "OPEN"` before `gh pr create` | Surface URL via `AskUserQuestion` (see Pre-check section). On `Update existing PR`, skip `gh pr create`. **Never** re-run `gh pr create` to recover. |
| Staged files look like secrets | `grep` matches against curated pattern set | Print file list. `AskUserQuestion` → on `Cancel`, abort with no `git restore --staged` and no commit. Never auto-unstage. |

## Common mistakes

| Mistake | Fix |
|---|---|
| Auto-escalate "I'm done" to a full ship | Always preview-only on completion phrases. Wait for the user's explicit "commit" or "ship". |
| Use `--no-verify` to bypass a failing hook | Never. Re-read the hook, fix the cause, re-commit. The hook is the contract. |
| Force-push to recover from a hook failure | Never. Hook failures don't create commits — there's nothing to force-push. |
| Use `(scope):` in commit subject when the detected hook enforces `[type]` | Quote the regex from the detected commit-msg hook (see Detect commit format step). If the host repo enforces Conventional Commits instead, `(scope):` is correct — ignore this row. |
| Append `[no ci]` to a commit touching `commands/foo.md` | The exclusion of `commands/`, `skills/`, `agents/` is load-bearing. |
| Use `gh pr create --fill` | Use `--body-file <PR template path>` so the `Closes #` line is filled correctly. |
| Pass both `--body-file` and `--body` to `gh pr create` | `gh` silently uses `--body-file` and discards `--body`. Write the filled body to a temp file and pass `--body-file <tmp>` only — never both flags together. Pattern: `TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT; <fill template> > "$TMP"; gh pr create --body-file "$TMP"` (trap ensures cleanup on failure too). |
| Auto-`gh pr create --draft` without asking | Always use `AskUserQuestion` to present `Draft` vs `Ready for review` — never ask via free-form prose. Drafts hide the PR from `assignees` and reviewers. |
| Re-run `gh pr create` after a "pull request already exists" failure | The pre-check section detects this before it happens. After push, an existing OPEN PR is already updated — `gh pr create` has nothing left to do. Use the `Update existing PR` path instead. |
| Auto-`git restore --staged` after a `Cancel` answer | Never. Leave staging untouched — the scan is advisory, not authoritative. The user may have reviewed the file and explicitly staged it. |

## Quick reference

| User says | Phase | Action |
|---|---|---|
| "I finished the feature" | Preview | Show diff + drafted commit msg. Do NOT commit. |
| "Commit this" | Commit | `git commit -m "[type] …"`. Stop. No push. |
| "Push it" | Push | `git push -u origin <branch>`. Stop. No PR. |
| "Ship this" | Ship | Commit → push → existing-PR check → draft/ready prompt → `gh pr create`. |
| "Ship this" (existing OPEN PR found) | Ship | Commit → push → existing-PR check surfaces URL → `AskUserQuestion` → skip `gh pr create`. |
| "Open a PR for what I just pushed" | PR-only | Skip commit. Run existing-PR check → draft/ready prompt → `gh pr create`. |

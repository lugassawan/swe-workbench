---
name: workflow-audit-emit-issues
description: After a codebase audit, groups audit findings by subsystem (path prefix) and emits them as context-rich GitHub issues with template discovery, label selection, and a batch preview-confirm gate before filing. Keywords: audit findings grouped github issues subsystem emit.
orchestrator: true
---

# workflow-audit-emit-issues

Files codebase audit findings as grouped GitHub issues — one issue per subsystem, sub-sectioned by domain.

## When to invoke

After a codebase audit has produced a ranked findings table and the user accepts the
"File as issues?" offer emitted by the `audit-codebase` command. Requires ≥1 finding
in the orchestrator's context.

## When NOT to invoke

- Zero findings — the audit ends at the rendered table; no offer is made.
- Without a preceding audit — this skill consumes in-context finding data only.
- To re-run the audit itself — see `workflow-codebase-audit` (read-only; no back-edge here).

## Composition

This skill is the filing counterpart to (not a caller of) `workflow-codebase-audit`.
Filing logic mirrors `workflow-bug-triage` Phase 4 precedent: `--body-file`, `.cmd`
sidecar, preview-gate-then-confirm. Template and label discovery follows the same
chain used by `agents/product-manager.md`.

## Input

Findings already in the orchestrator's context from the audit render. Each finding
carries: `file_line`, `domain`, `severity`, `confidence`, `effort`, `symptom`,
`root_cause`, `reasoning_chain`, `counter_evidence_considered`, `suggested_fix`.

## Phases

### Phase 1 — Group by subsystem

For each finding derive a **subsystem** from `file_line`:

1. Take the directory portion of the path (strip the filename).
2. Use up to the first 2 path segments as the grouping key.
3. Display label = last segment of that key:
   - `src/auth/handler.ts` → key `src/auth` → label **`auth`**
   - `commands/audit-codebase.md` → key `commands` → label **`commands`**
   - `scripts/validate.py` → key `scripts` → label **`scripts`**
4. Root-level file (directory portion is empty, e.g. `README.md`) → subsystem **`root`**.
5. No path (tool-level or unknown finding) → subsystem **`misc`**.

Within each subsystem, sub-group findings by `domain` (security, perf, reliability,
tooling, testing) to form sections within the issue body.

Report: "N findings across M subsystems."

### Phase 2 — Discover templates + labels

**Template discovery:**
```
ls .github/ISSUE_TEMPLATE/*.md 2>/dev/null
```
Skip `config.yml`. Read frontmatter of the first `.md` match. If none, use the
default body schema below.

**Label discovery:**
```
gh label list --json name -q '.[].name'
```
If `gh` is unauthenticated or returns an error, treat the list as empty, warn in
the preview, and retain the `.cmd` sidecar so the user can run it manually.

**Seed label per subsystem** from the dominant `domain` of its findings:

| Domain | Preferred label (case-insensitive substring match) |
|--------|---------------------------------------------------|
| security | "security" or "bug" |
| perf | "performance" |
| reliability | "bug" |
| tooling | "chore" or "tooling" |
| testing | "test" |

**Dominant domain** = the domain with the most findings in that subsystem.
Tie-break: prefer the higher-severity domain (security > reliability > perf > tooling > testing);
break further ties alphabetically.

Chain: template-frontmatter label → substring match → omit `--label` entirely.
Always surface the chosen label (or "none") in the preview so the user can change
it before replying `confirm`.

### Phase 3 — Render bodies + batch preview

Derive `<repo-slug>` first:
```
gh repo view --json nameWithOwner -q '.nameWithOwner' | tr '/' '-'
```
Fallback (offline): `basename $(git rev-parse --show-toplevel)`.

1. Build one issue body per subsystem using the schema in **Output** below.
2. Write each to a temp file via the **Write tool**:
   `/tmp/audit-emit-<repo-slug>-<unix-ts>-<n>.md`
3. Write a `.cmd` sidecar holding all `gh issue create` lines (one per subsystem).
4. Print the batch preview:

```
Target repo: <owner>/<repo>

[1] [audit] auth — label: security — 3 findings
[2] [audit] commands — label: bug — 1 finding
[3] [audit] misc — label: none — 2 findings

<fenced body for each group>

⚠ Re-running re-files duplicates. Confirm only once.

Reply `confirm` to file all · `drop N` to remove group N · `edit N` to revise group N
```

### Phase 4 — File on confirm

| Reply | Action |
|-------|--------|
| `confirm` (literal) | Run each sidecar `gh issue create` line; return issue URLs. After all issues are filed successfully, delete the temp files: `bash "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/runtime/clean-state-files.sh" /tmp/audit-emit-<repo-slug>-<unix-ts>-1.md … /tmp/audit-emit-<repo-slug>-<unix-ts>-N.md /tmp/audit-emit-<repo-slug>-<unix-ts>.cmd 2>/dev/null` — use the actual paths written in Phase 3 (pattern: `/tmp/audit-emit-<repo-slug>-<unix-ts>-<n>.md` and `.cmd`). |
| `drop N` | Remove group N from the batch; rewrite temp files and sidecar; re-print preview. |
| `edit N` | Show group N's body; accept revised text; rewrite temp file; re-print preview. |
| anything else | Re-prompt; do **not** file. |

On `gh issue create` failure: surface the error, print the URLs of successfully-filed
issues so far, and rewrite the `.cmd` sidecar to contain only the remaining (unfiled)
lines. Print the updated sidecar path for manual retry — do NOT surface the original
sidecar, as retrying it would duplicate already-filed issues.

## Output: grouped issue body schema

```markdown
## Audit findings — <subsystem>

> Scope: `<dominant-domain(s)>` · Severity range: `<highest>–<lowest>`
> Source: codebase audit

### <domain-section-1>

| Severity | File:Line | Symptom | Suggested fix |
|----------|-----------|---------|---------------|
| High | `path/to/file.ts:42` | Short symptom | Short fix |

**Root cause:** …

**Reasoning chain:** …

**Counter-evidence considered:** …

---

*(repeat for each domain section)*

## Provenance

Filed by `workflow-audit-emit-issues` from an in-session codebase audit.
Re-running re-files — check for duplicates before confirming.
```

## Issue-filing command (per subsystem)

```bash
gh issue create \
  --title "[audit] <subsystem>: <dominant-domain> findings" \
  --body-file /tmp/audit-emit-<repo-slug>-<unix-ts>-<n>.md \
  --label "<chosen-label>"
```

Omit `--label` when no matching label was found.

## Absolute rules

1. **Never run `gh issue create` before `confirm`.** Render the preview and wait.
2. **`--body-file` always.** Never pass `--body` inline; never use the `--template` flag on `gh issue create`.
3. **`workflow-codebase-audit` is read-only** (see its invariant). This skill does not
   re-invoke it — it only consumes findings already in context.
4. **Single batch gate.** One preview → one `confirm` → all issues filed.
5. **Zero findings → no offer.** The calling command guards this; this skill assumes ≥1 finding.
6. **Subsystem = path prefix.** Always derive from `file_line`; never from `domain` alone.

## Edge cases

| Scenario | Behaviour |
|----------|-----------|
| Single-finding subsystem | Still its own issue |
| All findings have no path | One issue with subsystem `misc` |
| No label match | Omit `--label`; show "none" in preview |
| No `.github/ISSUE_TEMPLATE/` | Use default body schema |
| `gh` unauthenticated | Warn in preview; surface `.cmd` sidecar path |
| Long body | `--body-file` handles it |

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Running `gh issue create` before `confirm` | Wait for the literal reply |
| Using `--template` flag | Use `--body-file` with the temp file path |
| Re-invoking the audit to refresh data | Consume in-context findings only |
| Omitting label feedback in preview | Always show "none" explicitly if no label matched |
| One giant issue for all findings | One issue per subsystem, sub-sectioned by domain |

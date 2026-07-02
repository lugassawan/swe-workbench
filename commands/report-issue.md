---
description: File a plugin bug or feature request directly into lugassawan/swe-workbench from any directory
argument-hint: "[<one-line thought> — omit to draft from conversation/memory]"
---

> **Override (this command only):** The `product-manager` agent's default rules "Does not pass `--repo` explicitly to `gh issue create`" (Decision boundaries) and "Never pass `--repo`" (Mutation rules) are **suspended** for `/swe-workbench:report-issue`. You MUST pass `--repo lugassawan/swe-workbench` on every `gh` invocation in this flow. No other rule is changed.

The user wants to file a plugin issue: $ARGUMENTS

**Target repo (hardcoded):** `repo="lugassawan/swe-workbench"`

---

## Step 0 — Blank-argument routing

If `$ARGUMENTS` is **empty**, do NOT error. Instead:

### Step 0a — Mode selector

Ask the user to choose a mode, then wait for the reply:
```
How would you like to find a plugin-related thought to report?

1. Quick pick — up to 3 raw candidates from this session/memory
2. Synthesize — aggregate all memory into ranked, themed enhancement insights

Reply with 1 (quick pick) or 2 (synthesize).
```
Reply `1` → **Branch A — Quick pick**. Reply `2` → **Branch B — Synthesize**.

### Branch A — Quick pick

1. **Scan the current conversation** for actionable plugin-related thoughts: frustrations, lessons learned, complaints about plugin behaviour, feature ideas, or pain points. Collect up to 3 candidates with a one-line framing each.

2. If conversation yields fewer than 3, **scan memory** at `~/.claude/projects/<project-slug>/memory/MEMORY.md` (where `<project-slug>` is derived from the current working directory path by replacing each `/` with `-`, then stripping any resulting leading `-`; e.g. `/Users/foo/bar` → `Users-foo-bar`). Follow symlinks to `feedback_*.md` and `project_*.md` entries referenced there. Collect additional candidates until you have up to 3, prioritising entries that mention the plugin, commands, agents, or skills by name.

3. Present candidates numbered 1–N (max 3) with a one-line framing each:
   ```
   I found a few plugin-related thoughts from this session/memory. Pick one or type your own:

   1. <one-line framing>
   2. <one-line framing>
   3. <one-line framing>

   Reply with 1/2/3 or type your own thought.
   ```
   Wait for the user's reply. The selected or typed thought becomes `$ARGUMENTS` and flow continues at the **Auth + repo check** step below.

4. If neither conversation nor memory yields anything plugin-related, exit cleanly:
   > No plugin-related thought found in conversation or memory. Try `/swe-workbench:report-issue <your thought>`.

---

### Branch B — Synthesize

**Granularity:** exactly one issue per selected insight — never bundle multiple insights into a single issue.

1. **Load all memory.** Use the same path recipe as Branch A: `~/.claude/projects/<project-slug>/memory/`. Read `MEMORY.md`, then follow its links to every `feedback_*.md` and `project_*.md` entry it points at. Capture each entry's `name`, `description`, body, and its `type` value (older entries carry a top-level `type:`; newer entries nest it under `metadata:` — read whichever is present). Preserve `MEMORY.md`'s listed order — it is the only recency signal available (no date frontmatter exists on memory entries).

2. **Harvest conversation signal.** Separately note which plugin-related themes the current conversation itself touches. Keep this as its own set — it feeds the recency boost in step 4, it is not merged into the memory set.

3. **Cluster into emergent themes.** Group the loaded entries by the semantic theme carried in their `description`/body — clusters emerge from the content itself. This is NOT a fixed taxonomy and not a path-prefix grouping (memory entries have no paths); invent a short theme label per cluster rather than picking from a predefined list. Each cluster becomes one candidate insight.

4. **Rank.** Order candidate insights by **prevalence** (cluster size) first; break ties by **recency** — an entry's position in `MEMORY.md` order — with a boost for any cluster the conversation also touches per step 2. Keep the top **5–7** insights. If fewer than 5 emergent clusters exist, present all available clusters — do not pad to reach the 5–7 range.

5. **Draft one preview body per insight**, using the Synthesis issue body shape below. Run the **Version capture** once, and the **Redaction pass** (delegation step 7) once over every drafted body — both before any display.

6. **Turn 1 — ranked digest.** Print insights numbered 1..N, most-prevalent first; each entry shows its theme label, a one-line rationale, the memory entries cited (`name` + `type`), its drafted `Title:`, and its fenced preview body. End with:
   ```
   Reply with the numbers to file (e.g. `1,3`), or `none`.
   ```
   **Write no temp files and run no `gh` command this turn.** An out-of-range number or `none` re-prompts once, then exits without filing.

7. **Turn 2 — final preview of picks.** Parse the reply into the set of picked digest numbers. If, after the one re-prompt from step 6, the picked set is still empty, exit cleanly with "No insights remain to file" instead of proceeding. Run delegation step 1 (auth + repo check) once. Branch B never runs delegation step 4 (template discovery) and never adopts a repo template's body shape — every picked insight always uses the fixed Synthesis issue body shape below. Per pick, run: label discovery seeded directly at delegation step 5c's commit-tag mapping (the title always starts with `[feat]`, mapping to `enhancement`, then the verbatim/substring match chain against the repo's label list — no match found still omits `--label`, same as delegation step 5d), and delegation step 6 (duplicate scan). Capture one shared `date +%s` timestamp. For each pick `<n>` (its digest number), write its body via the **Write** tool to `/tmp/report-issue-lugassawan-swe-workbench-<ts>-<n>.md`. Write ONE shared `.cmd` sidecar at `/tmp/report-issue-lugassawan-swe-workbench-<ts>.cmd`, containing one `gh issue create --repo lugassawan/swe-workbench --title "..." --body-file <path-n> [--label "enhancement"]` line per pick — one enhancement issue per pick, never bundled. Print each selected body with its `Title:` / `Filing into:` / `Redacted:` / `Label:` / `Possibly related:` lines, then:
   ```
   Reply 'confirm' to file all, or `drop N` / `edit N`.
   ```
   **Wait for `confirm`. Do NOT run `gh issue create` on this turn.** After `drop N` or `edit N`, re-print the updated preview and wait for `confirm` again — never file immediately after an edit. If `drop N` empties the pick set, exit cleanly with "No insights remain to file" instead of re-prompting for `confirm`.

8. **File on confirm.** Only on a literal `confirm` reply, read the `.cmd` sidecar and run each line verbatim, returning each issue URL. `drop N` removes that pick's temp file and rewrites the sidecar to drop its line; `edit N` rewrites that pick's temp file and re-prints only that pick's preview. On full success, reap every `-<n>.md` temp file plus the shared `.cmd` sidecar via `runtime/clean-state-files.sh`. On partial failure, reap the `-<n>.md` temp file for each pick that filed successfully, rewrite the sidecar to contain only the unfiled lines, and leave the still-unfiled picks' temp files in place for retry.

**Edge cases:**
- **No memory found, or the memory directory is missing:** fall back to the conversation-only signal from step 2; if that is also empty, exit cleanly exactly like Branch A step 4 ("No plugin-related thought found…").
- **1–2 entries — too few entries to synthesize themes:** skip clustering and present each entry directly as its own insight; fewer than 5 is fine here — don't pad the digest to reach a minimum.
- **Conversation-only signal:** if memory is empty but the conversation touches plugin themes, build insights from the conversation signal alone.
- **`gh` unauthenticated:** print the same token-scope warning as delegation step 1, still render the digest and the final preview, and keep the `.cmd` sidecar on disk for a manual run.
- **Out-of-range number or `none`:** re-prompt once; file nothing.

**Synthesis issue body** (per insight — always this fixed shape, never a repo template's; redaction, the version footer, label discovery, and the duplicate scan from the delegation block still apply unchanged):
- **Title:** `[feat] <theme>: <concise enhancement>` — the `[feat]` tag drives label discovery to `enhancement` via delegation step 5c.
- **Sections:** `## Problem` (the recurring user pain) · `## Value` · `## Themed evidence` (bullets citing the memory entries feeding this theme, by `name` + `type`) · `## Acceptance criteria` (2–4 bullets) · `## Impact / Effort` (S/M/L each).
- **Footer:** the same `_Reported via ... plugin v<version>, Claude Code <cli-version>._` footer, version captured once and shared across all picked insights.

---

Delegate to the `product-manager` subagent. Its response must deliver all of the following before any issue is filed:

1. **Auth + repo check.** Set `repo="lugassawan/swe-workbench"`. Run `gh auth status` to check permissions — if the output indicates the token lacks repo/issue write scope, print a one-line warning:
   > Warning: your gh token may lack issue-write scope on `lugassawan/swe-workbench`; filing may fail at confirm time.
   …and continue. Then run `gh repo view --repo "$repo" --json nameWithOwner`. Surface the result in the preview as `Filing into: lugassawan/swe-workbench`. If `gh repo view` fails, bail with: "Repo access check failed: <reason>. Run `gh repo view --repo lugassawan/swe-workbench` to diagnose."

2. **Restatement.** One sentence in the user's domain language confirming the thought. If the thought is ambiguous, ask exactly one clarifying question before continuing.

3. **Product framing** — four lenses applied with brevity:
   - **Problem.** User pain or constraint, stated as the user's pain — not the feature.
   - **Value.** Who benefits and how. One "so-what" sentence.
   - **Acceptance criteria.** 2–4 bullets (Given/When/Then or simple bullets).
   - **Impact / Effort (RICE-lite).** `Impact: S/M/L` and `Effort: S/M/L`, one sentence each.

4. **Template discovery.** Fetch templates via `gh api repos/lugassawan/swe-workbench/contents/.github/ISSUE_TEMPLATE --repo lugassawan/swe-workbench --jq '.[].name'` to list template file names (skip `config.yml`). For each `.md` template, fetch its body with `gh api repos/lugassawan/swe-workbench/contents/.github/ISSUE_TEMPLATE/<name> --repo lugassawan/swe-workbench --jq '.content' | python3 -c "import base64,sys; print(base64.b64decode(sys.stdin.read().strip()).decode())"`. Read the frontmatter and first ~20 body lines. Classify the thought into the closest-fit template with a one-sentence reason, or note "No issue templates found; using default body shape" when none exist.

5. **Label discovery.** Run `gh label list --repo lugassawan/swe-workbench --json name -q '.[].name'`. If the command fails or returns empty output, treat the label list as empty and proceed directly to step d (no match → omit `--label`). Otherwise select a label using this chain:

   a. **Template frontmatter:** if the chosen template has a `labels:` field and that value exists verbatim in the repo's label list, use it.
   b. **Fallback — substring match (case-insensitive):** if the frontmatter label is not present verbatim, pick the first repo label whose name case-insensitively contains (or is contained by) the template's value.
   c. **No template chosen:** map by commit-tag — `[feat]` → `enhancement`, `[bug]` → `bug`, `[chore]` → `documentation` — then apply the same chain against the repo's label list. If no commit-tag is recognisable in the user's input, proceed directly to step d.
   d. **No match found:** omit `--label`; record this so the preview can warn the user ("No matching label found; filing without label").

6. **Duplicate scan.** Extract 2–3 keywords from the thought. Strip each to `[a-zA-Z0-9_-]` only (drop shell metacharacters, quotes, and flags) and single-quote them when building the search string. Then run `gh issue list --repo lugassawan/swe-workbench --search '<sanitized keywords>' --state open --limit 5`. Surface matches. Ask before drafting if any look duplicative.

7. **Draft.** With a template: fill its sections, prepend `## Product framing`. Without a template: use `## Problem` / `## Value` / `## Acceptance criteria` / `## Impact / Effort` / `## Additional context`.

   Append the following footer to the body's last free-text section (or as a final `---` block):

   ```markdown
   ---
   _Reported via `/swe-workbench:report-issue` — plugin v<version>, Claude Code <cli-version>._
   ```

   **Version capture (run once, before drafting):**
   - **Plugin version:** list `~/.claude/plugins/cache/swe-workbench/swe-workbench/` version directories, sort semantically (`sort -V`), take the highest with `tail -1`, then read `plugin.json` from it: `ls ~/.claude/plugins/cache/swe-workbench/swe-workbench/ 2>/dev/null | sort -V | tail -1 | xargs -I{} python3 -c "import json; print(json.load(open('$HOME/.claude/plugins/cache/swe-workbench/swe-workbench/{}/.claude-plugin/plugin.json'))['version'])"`. If this returns no output (not installed from cache), fall back to: `gh api repos/lugassawan/swe-workbench/contents/.claude-plugin/plugin.json --repo lugassawan/swe-workbench --jq '.content' | python3 -c "import base64,sys,json; print(json.loads(base64.b64decode(sys.stdin.read().strip()))['version'])"`.  
   - **CLI version:** `claude --version` — strip the leading `Claude Code ` prefix to get the bare semver.

   **Redaction pass (privacy guard).** Before writing the body in step 8, scan the drafted body for confidential identifiers pulled from conversation context and replace each with a generic placeholder. Prefer over-redaction — the user restores false positives at the preview gate.

   - **Allowlist — NEVER redact** (these are the legitimate subject of the issue): the target repo `lugassawan/swe-workbench` and the bare string `swe-workbench`; this plugin's command/skill/agent names (e.g. `report-issue`, `capture`, `product-manager`, `workflow-*`, `principle-*`, `language-*`); plugin-internal file paths (e.g. `commands/report-issue.md`); the repo owner handle `lugassawan`; and the following public tech names and their canonical domains: GitHub (`github.com`, `api.github.com`), Claude Code, the `gh` CLI, Python, pytest, Node, npm, pip. When uncertain whether a name is public, prefer to redact it.
   - **Redact when NOT allowlisted** (handle camelCase / snake_case / kebab-case variants):
     - Email addresses → `[internal-email]`
     - URLs, hostnames, internal domains (e.g. `*.corp`, `*.internal`, company domains) → `[internal-host]`
     - IP addresses → `[internal-ip]`
     - API keys, tokens, and credential strings matching common patterns (e.g. `sk-…`, `ghp_…`, `AKIA…`, `Bearer <token>`) → `[redacted-token]`. Do NOT redact bare UUIDs without surrounding context that identifies them as secrets (e.g., a UUID in a JSON field named `secret`, `key`, or `token`).
     - Internal service identifiers (`*-api`, `*-service`, `*-svc`, `*-worker`, `*-gateway`) that are not plugin names → `an internal service`
     - Apparent company / product / org names, and other-repo or monorepo slugs surfaced from conversation → `a downstream consumer` / `the monorepo` / `an internal repository` as fits.
   - Never redact text the user explicitly typed as their own thought intending it to be public.
   - Count the replacements made; carry the count into the step 8 preview.

8. **Preview gate.** Obtain a Unix timestamp once (`date +%s`) and reuse it. Write the body to `/tmp/report-issue-lugassawan-swe-workbench-<unix-timestamp>.md` using the `Write` tool (not a Bash heredoc). Also write a one-line command to `/tmp/report-issue-lugassawan-swe-workbench-<unix-timestamp>.cmd` using the `Write` tool: when a label was matched, write `gh issue create --repo lugassawan/swe-workbench --title "..." --body-file <path> --label "<matched-label>"`; when no label was matched, write `gh issue create --repo lugassawan/swe-workbench --title "..." --body-file <path>` (no `--label` segment). Then print:
   ```
   Filing into: lugassawan/swe-workbench
   Template: <chosen template> | none — default body
   Title: <drafted title>
   Label: <chosen label> | none — no matching label found
   Redacted: <N internal identifier(s) → placeholders | none detected>
   Possibly related: <#N list, or "none">

   Body:
   <code-fenced body>

   Command: gh issue create --repo lugassawan/swe-workbench --title "<title>" --body-file <path> [--label "<chosen-label>" when matched]

   Reply 'confirm' to file, or edit any of the above (including the label) and I'll redraft.
   ```
   When a label was matched, render `Command:` with `--label "<chosen-label>"`. When no label was matched, omit the `--label` segment entirely. **Wait for the user to reply `confirm`. Do NOT run `gh issue create` on this turn.**

9. **File on confirm.** Only when the user replies `confirm`, read the command from the `.cmd` sidecar written in step 8 and run it exactly as written — do not regenerate the title or path. Return the issue URL. After a successful `gh issue create`, delete the temp files: `bash "${CLAUDE_PLUGIN_ROOT:-$(git rev-parse --show-toplevel)}/runtime/clean-state-files.sh" "/tmp/report-issue-lugassawan-swe-workbench-<unix-timestamp>.md" "/tmp/report-issue-lugassawan-swe-workbench-<unix-timestamp>.cmd" 2>/dev/null` (substituting the actual paths from step 8). On failure, leave the files for retry.

---
description: Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude, python3) plus gh auth status and .claude/cache/ repo hygiene. Prints a green/red table; never modifies state. Exit 0 regardless of findings; exits 1 only if the swe-workbench-doctor command is not on PATH.
---

Run the preflight diagnostic and print the results verbatim:

```
command -v swe-workbench-doctor >/dev/null 2>&1 || {
  echo "swe-workbench runtime commands not on PATH — reinstall or update the swe-workbench plugin." >&2
  exit 1
}
swe-workbench-doctor
```

Print the full stdout output exactly as produced — do not summarise, truncate, or reformat it.

The script probes six runtime dependencies: `gh`, `git`, `jq`, `rimba`, `claude`, and `python3`. It also checks `gh auth status` and appends the result to the `gh` row. Each tool is marked ✓ (present) or ✗ (missing). When a tool is missing the row includes an install hint. The dependency summary line reports the count of missing dependencies or confirms all are present.

Inside a git repository, a separate **Repo hygiene** section follows: it checks whether `.claude/cache/` (the plugin's workflow-state and skill-usage sidecar directory) is gitignored, and whether any file under it is already tracked. Each issue is reported as a warning with a remediation hint — the check never writes to `.gitignore` or runs `git rm` itself. Outside a git repository the section is omitted entirely. This section has its own warning count, independent of the dependency summary.

This command takes no arguments and makes no changes to state.

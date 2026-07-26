---
description: Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude) plus gh auth status. Prints a green/red table; never modifies state. Exit 0 regardless of dependency findings; exits 1 only if the swe-workbench-doctor command is not on PATH.
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

The script probes five runtime dependencies: `gh`, `git`, `jq`, `rimba`, and `claude`. It also checks `gh auth status` and appends the result to the `gh` row. Each tool is marked ✓ (present) or ✗ (missing). When a tool is missing the row includes an install hint. The final summary line reports the count of missing dependencies or confirms all are present.

This command takes no arguments and makes no changes to state.

---
description: Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude) plus gh auth status. Prints a green/red table; never modifies state. Exit 0 regardless of dependency findings; exits 1 only if CLAUDE_PLUGIN_ROOT cannot be resolved.
---

Run the preflight diagnostic and print the results verbatim:

```
_RT="${CLAUDE_PLUGIN_ROOT:-}"
[ -n "$_RT" ] || {
  echo "CLAUDE_PLUGIN_ROOT not set; cannot locate runtime scripts (see swe-workbench runtime/README.md)" >&2
  exit 1
}
bash "$_RT/runtime/doctor.sh"
```

Print the full stdout output exactly as produced — do not summarise, truncate, or reformat it.

The script probes five runtime dependencies: `gh`, `git`, `jq`, `rimba`, and `claude`. It also checks `gh auth status` and appends the result to the `gh` row. Each tool is marked ✓ (present) or ✗ (missing). When a tool is missing the row includes an install hint. The final summary line reports the count of missing dependencies or confirms all are present.

This command takes no arguments and makes no changes to state.

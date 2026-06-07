---
description: Read-only preflight check of runtime dependencies (gh, git, jq, rimba, claude) plus gh auth status. Prints a green/red table; never modifies state. Exit 0 regardless of findings.
---

> **Pi port note:** This prompt is adapted from the Claude Code SWE Workbench command. In pi, when the original command says to invoke a Claude subagent, load the corresponding packaged `agent-*` skill (for example, `reviewer` → `agent-reviewer`). When it says to invoke `swe-workbench:<skill>`, load the packaged skill with that basename. Use pi's available tools instead of Claude-only tool names.
Run the preflight diagnostic and print the results verbatim:

```
bash "$CLAUDE_PLUGIN_ROOT/scripts/doctor.sh"
```

Print the full stdout output exactly as produced — do not summarise, truncate, or reformat it.

The script probes five runtime dependencies: `gh`, `git`, `jq`, `rimba`, and `claude`. It also checks `gh auth status` and appends the result to the `gh` row. Each tool is marked ✓ (present) or ✗ (missing). When a tool is missing the row includes an install hint. The final summary line reports the count of missing dependencies or confirms all are present.

This command takes no arguments and makes no changes to state.

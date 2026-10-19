# Plan Evidence Section Template

Render this `## Evidence` section **above** `## Workflow`. Substitute each `[[evidence:KEY]]` placeholder from the JSON envelope printed by `swe-workbench-plan-evidence`:

| Placeholder | Envelope field | Rendering |
|---|---|---|
| `[[evidence:head]]` | `data.head` | the full sha |
| `[[evidence:dirty]]` | `data.dirty` | the word `dirty` or `clean` |
| `[[evidence:target]]` | `data.target` | the branch name |
| `[[evidence:target-sha]]` | `data.remote_target_sha` | the sha; when empty, write `unavailable` |
| `[[evidence:drift]]` | `data.drift` | `none`, `changed`, `overlap` or `unknown` |
| `[[evidence:worktrees]]` | `data.worktrees` | one `branch @ path` per entry with a non-empty `overlapping_paths`, else `none overlap` |

The prose rows (sources, negative findings, introduced identifiers, open assumptions) come from agent outputs and the orchestrator's own reads, not from the script.

---

````markdown
## Evidence

- **Inspected revision:** [[evidence:head]] ([[evidence:dirty]]). Target: [[evidence:target]] @ [[evidence:target-sha]].
- **Drift vs target:** [[evidence:drift]]. On `overlap`, list each overlapping path with the line "re-read: yes / plan amended: <how>". On `unknown`, state the open assumption using the envelope's warning `code` and `message` (for example "target not fetched; implementation Phase 1 rechecks").
- **Worktree inventory:** [[evidence:worktrees]]. The script sees committed and uncommitted changes to cited files in sibling worktrees; it cannot see unsaved editor buffers.
- **Searched scope and primary sources:** each material claim → `file:line`, or a URL for external facts.
- **Negative findings:** "not found in `<scope>` via `<Grep pattern | Glob | navigation>`". Never write "does not exist" unless absence was proven, for example by an exhaustive listing.
- **Introduced identifiers:** omit this row when the plan adds none. Otherwise list each new public identifier (command, skill, bin script, flag, env var), new or re-pinned dependency, or new integration or migration:

  | Identifier | Kind | Collision check | Prior-art check | Version source |
  |---|---|---|---|---|
  | `<name>` | `<kind>` | `<scoped negative or hit>` | `<scoped negative or hit>` | `<registry URL>` or "open assumption" |

- **Open assumptions:** every claim that could not be verified, stated explicitly. None is written "none".
````

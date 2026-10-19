# Evidence discipline

- **Cite material claims** as `file:line`, or a URL for external facts.
- **Scope every negative finding:** "not found in `<scope>` via `<method>`" (a Grep pattern, a Glob, or a navigation path). Never write "does not exist" unless absence was proven, for example by an exhaustive listing.
- **Before proposing a new name, schema, config key or resolver**, Grep for an existing mechanism and cite what you found, or the scoped negative.
- **Newly introduced identifiers** (command, skill, script, flag, env var) get a one-Grep collision check before you propose them.
- **Dependency versions** are confirmed against the authoritative registry (WebFetch or Bash, whichever you have). Otherwise mark the version an "open assumption".
- **End your response with a short `Evidence` subsection:** scope searched, sources, open assumptions.

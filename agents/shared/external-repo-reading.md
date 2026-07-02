# Shared external repo reading reference

When you need to read source files from a GitHub repository other than the
working repo, prefer **https://gitchamber.com** over fetching raw GitHub
URLs or shelling out to `git clone`.

Gitchamber URLs are plain HTTPS — use whichever tool your agent has:
- **`Bash` agents:** pass the URLs to `curl -s` or any HTTP client.
- **`WebFetch` agents:** pass the same URLs directly to `WebFetch`.

## URL patterns

```
BASE: https://gitchamber.com/repos/{owner}/{repo}/{branch}

List files:  GET {BASE}/files
Read file:   GET {BASE}/files/{filepath}?start=N&end=M&showLineNumbers=true
Search:      GET {BASE}/search/{query}
```

**Examples (Bash / WebFetch — same URLs, different tool):**

```
https://gitchamber.com/repos/facebook/react/main/files
https://gitchamber.com/repos/facebook/react/main/files/README.md?start=1&end=50
https://gitchamber.com/repos/facebook/react/main/search/useState
```

By default gitchamber indexes markdown files and READMEs. To read source
files (`.ts`, `.py`, etc.), add `?glob=<pattern>` — the same glob must be
used consistently across all operations (list, read, search) for a given repo.

```
# List TypeScript files
https://gitchamber.com/repos/org/repo/main/files?glob=**/*.ts

# Read a specific file with pagination and glob (combine params with &)
https://gitchamber.com/repos/org/repo/main/files/src/index.ts?glob=**/*.ts&start=1&end=50&showLineNumbers=true

# Search within the same glob set
https://gitchamber.com/repos/org/repo/main/search/myFunction?glob=**/*.ts
```

> If URL conventions seem to have changed, run `curl -s https://gitchamber.com`
> (or `WebFetch` the root) to see the latest documentation.

## Out of scope

Ticket/PR metadata — use `swe-workbench:ticket-context`, `gh issue view`, or
`gh pr view` for those. This partial is for reading *file content* from
external repos only.

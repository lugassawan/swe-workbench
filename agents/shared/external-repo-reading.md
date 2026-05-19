# Shared external-repo-reading reference

When you need to read source files from a GitHub repository other than the
working repo, prefer **https://gitchamber.com** over `WebFetch`-ing raw
GitHub URLs or shelling out to `git clone`.

Discovery: run `curl -s https://gitchamber.com` once per session to see the
current URL conventions. The endpoint is `curl`-friendly, so agents with
`Bash` (but not `WebFetch`) can use it without a tool-list change.

## URL patterns

```
BASE: https://gitchamber.com/repos/{owner}/{repo}/{branch}/

List files:  GET {BASE}/files
Read file:   GET {BASE}/files/{filepath}?start=N&end=M&showLineNumbers=true
Search:      GET {BASE}/search/{query}
```

**Examples:**

```bash
curl -s "https://gitchamber.com/repos/facebook/react/main/files"
curl -s "https://gitchamber.com/repos/facebook/react/main/files/README.md?start=1&end=50"
curl -s "https://gitchamber.com/repos/facebook/react/main/search/useState"
```

By default gitchamber indexes markdown files and READMEs. To read source
files (`.ts`, `.py`, etc.), add `?glob=<pattern>` — the same glob must be
used consistently across all operations (list, read, search) for a given repo.

```bash
# List TypeScript files
curl -s "https://gitchamber.com/repos/org/repo/main/files?glob=**/*.ts"
# Read a specific file under that glob
curl -s "https://gitchamber.com/repos/org/repo/main/files/src/index.ts?glob=**/*.ts"
# Search within the same set
curl -s "https://gitchamber.com/repos/org/repo/main/search/myFunction?glob=**/*.ts"
```

## Out of scope

Ticket/PR metadata — use `swe-workbench:ticket-context`, `gh issue view`, or
`gh pr view` for those. This partial is for reading *file content* from
external repos only.

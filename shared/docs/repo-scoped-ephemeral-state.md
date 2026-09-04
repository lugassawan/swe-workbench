# Repo-scoped ephemeral state

How `/tmp/swe-workbench-*` ephemeral artifacts are scoped by repository, so
same-numbered PRs in different repositories never collide and cleanup never deletes another
repository's artifacts.

## The problem

Previously, every ephemeral artifact was keyed only by PR number and flow tag:
`/tmp/swe-workbench-pr-review/<N>*.json`, `/tmp/swe-workbench-address-feedback/<N>*.json`,
`/tmp/swe-workbench-run/<prefix>-<N>-<rand>/`, and the git-fallback worktree dirs
`/tmp/swe-workbench-pr-review/<N>` (plus `-followup` / `<mode>-<N>` variants). Two repos can
legitimately both have PR `<N>` — cleanup could only guess ownership, foreign artifacts
lingered, and concurrent same-`<N>` reviews raced on identical filenames.

## The slug

`owner/repo` → `owner-repo`, with every literal hyphen inside `owner` and inside `repo` doubled
*before* the join (`owner.replace('-', '--') + '-' + repo.replace('-', '--')`). Plain `tr '/' '-'`
— the pre-existing convention from `swe-workbench:workflow-audit-emit-issues`
(`gh repo view --json nameWithOwner -q .nameWithOwner | tr '/' '-'`) — is **not** injective: two
distinct pairs that split the hyphen boundary differently collide (`acme-app/foo` and
`acme/app-foo` both produce `acme-app-foo`), which breaks the "never remove artifacts belonging to
a different repository" guarantee this whole scheme exists to provide. Doubling makes every
hyphen run wholly inside an escaped half even-length, so the separator — the one hyphen not part
of a doubled pair — is always locatable and the join stays injective (e.g. `acme-app/foo` →
`acme--app-foo`, `acme/app-foo` → `acme-app--foo`). GitHub owner/repo names are `[A-Za-z0-9._-]`
and start alphanumeric, so the escaping stays filename-safe. `bin/swe-workbench-repo-scope` is the
single resolver (Tier S bare scalar on stdout; exit 1 + empty output = unresolvable):

| Resolution step | Source |
|---|---|
| 1. `--repo owner/repo` | Explicit, from the caller — the PR record in hand when the invocation carried a full PR URL |
| 2. `--pr-json <file>` | The fetched PR JSON's own `.url` field (every current preflight state file carries it) |
| 3. *(no args)* | `git remote get-url origin` of the cwd (https / `git@` / `ssh://` forms) |
| *(all fail)* | Empty slug ⇒ **legacy un-scoped naming** — byte-for-byte legacy behavior, never a flow failure |

Fork checkouts: `origin` is the fork, so the checkout-derived slug differs from the PR's base
repo. Callers that know the PR URL (or hold the PR JSON) should always pass the explicit scope —
step 1 exists precisely so the PR record outranks the checkout.

## Name shapes

| Artifact class | Scoped shape | Legacy shape |
|---|---|---|
| Run dir | `/tmp/swe-workbench-run/<tag>-<slug>-<N>-<rand>/` | `<tag>-<N>-<rand>` |
| Preflight state files | `/tmp/swe-workbench-pr-review/<slug>-<N>.json`, `<slug>-<N>-followup.json`, `<slug>-<N>-review-<mode>.json` | `<N>.json`, `<N>-followup.json`, `<N>-review-<mode>.json` |
| Post cache | `/tmp/swe-workbench-pr-review/<slug>-<N>-post-threads-*.json` | `<N>-post-threads-*.json` |
| Address-feedback state | `/tmp/swe-workbench-address-feedback/<slug>-<N>*.json` (incl. `-threads`, `-pr-comments`, `-triage`, `-worktree` receipt) | `<N>*.json` |
| Git-fallback worktree dirs | `/tmp/swe-workbench-pr-review/<slug>-<N>`, `<slug>-<N>-followup`, `<slug>-<mode>-<N>` | `<N>`, `<N>-followup`, `<mode>-<N>` |
| Rimba task/branch labels | **unchanged** (`pr-review-<N>`, …) — per-repo git objects, already scoped | — |

Rules of thumb:

- The slug sits directly before `<N>` (`-<slug>-<N>-`), so prefix allowlists stay prefix-anchored
  and the `mktemp` template keeps `XXXXXX` terminal.
- Match slugs with **literal globs** (`case` / `[[ == ]]` / glob patterns), never ERE — the slug
  charset includes `.` and `_`, which regex would treat specially or over-match.
- The reap/new-run-dir basename allowlists accept both shapes via an optional middle segment
  `(-[A-Za-z0-9._-]+)?`. Overlap with `review-*` tags is acceptable: those allowlists are
  recognition gates, not deletion decisions (safety = depth-1 + `[ -O ]` + no-`.git`).
- Empty slug ⇒ legacy shapes, everywhere, including `swe-workbench-pr-review-worktree` fallbacks
  and the `names` contract (`fallback_path` == `legacy_fallback_path`).

## Writers and readers

- `swe-workbench-new-run-dir <prefix> <id> [--repo owner/repo]` — embeds the slug (ladder above).
- `swe-workbench-preflight-pr` — default field set includes `url`, so every new state file
  self-attributes on disk.
- `swe-workbench-address-feedback-fetch [--repo owner/repo]` — slugs all four state paths;
  `resume_available` dual-reads the legacy triage path only when a same-numbered legacy
  preflight JSON also attributes it to this repo (the triage file itself carries no owner/repo
  field to check directly).
- `swe-workbench-address-feedback-worktree [acquire|release] … [--repo owner/repo]` — slugged
  `<slug>-<N>-worktree.json` receipt, dual-read of the legacy receipt on release.
- `swe-workbench-pr-review-worktree {acquire,release,names} … [--repo owner/repo]` — slugged
  fallback dirs; `names` emits both `fallback_path` (scoped) and `legacy_fallback_path`.

## Legacy attribution (sweep-time)

`swe-workbench-sweep-residuals <N> [--repo owner/repo] [--head-sha <sha>]` — scoped mode sweeps
slugged names unconditionally (ours by construction) and legacy names only when attributed:

| Legacy artifact | Attribution rule |
|---|---|
| Preflight JSONs (`<N>.json`, `<N>-followup.json`, `<N>-review-<mode>.json`) | `.url` present ⇒ owner/repo match; elif `.headRefOid` present and `--head-sha` given ⇒ fingerprint match; else **retain** (`not attributable`) |
| `<N>-threads.json`, `<N>-post-threads-*.json` | Set-paired with the sibling `<N>.json`: swept iff the sibling was swept or is absent |
| `<N>-pr-comments.json` | `.[0].repository_url` ends with the scoped `owner/repo`; empty/unparseable ⇒ retain |
| `<N>-triage.json` | **Always retained** — user decisions, unrecoverable; a spent resume point ages out with `/tmp` |
| `<N>-worktree.json` receipt | Receipt `.path`'s own `git remote get-url origin` == scope; missing path ⇒ retain |
| Legacy fallback worktree dirs | Dir's own git origin == scope; else retain |
| Legacy run dirs | Never swept here — `new-run-dir`'s 24h age-gated orphan reaper owns them (that reaper is deliberately shape-wide — any repo's stale run dir, `mtime`-gated — pre-existing GC semantics, not repo-scoped) |

Unattributable/retained items land in `data.retained_state_files` / `data.retained_worktrees`
as `{path, reason}` and flip the envelope to `status: "partial"`. An explicitly **invalid
`--repo`** fails closed to retain-only (nothing legacy swept, run dirs not globbed) — a typo
must never widen into an unconditional sweep. **Unscoped mode** (no slug resolved — origin
absent, not malformed) keeps legacy sweep semantics for legacy names after the caller proved
the PR MERGED, plus one deliberate addition: the legacy `<N>-worktree.json` receipt, newly
covered (legacy sweeps never touched it). Block C matches run dirs with **exact-tag anchored
globs** (`<tag>-<slug>-<N>-??????` per allowlisted tag, legacy `<tag>-<N>-??????` unscoped) —
an unanchored `*` could absorb a longer foreign slug ending in `-<slug>`.

## Mid-upgrade (dual-read)

A pre-upgrade acquire and a post-upgrade release must still meet: release paths, the worktree
receipt read, and the triage resume check all fall back to the legacy spelling when the scoped
one is absent (see the three writers above), and every legacy-fallback adoption is
attribution-gated — the worktree receipt by its own recorded path's git origin, the triage resume
check by a same-numbered legacy preflight JSON's `.url` (the triage file itself has no
owner/repo field of its own to check). Prose that hardcoded literal paths now
reaps via the envelope-provided variables (`$JSON`, `$TRIAGE_PATH`, `$RESUME_TRIAGE_PATH`, …)
so both spellings flow through one name. Known inherited edges (documented, retention-bounded):
a fork checkout's origin-derived artifacts won't match a base-repo sweep's explicit scope —
they are retained, never deleted, until `/tmp` cleanup; the 24h age-gated run-dir reaper is
shape-wide across repos by design.

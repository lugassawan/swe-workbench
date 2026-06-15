---
name: workflow-dependency-upgrade
description: "Use when walking the dependency-upgrade lifecycle — routine sweep, Dependabot/Renovate PR triage, CVE patch, or major-version migration. Structured runbook: triage+batch → bump regen lockfile → build/test → breakage-triage → PR hygiene. Per-ecosystem command matrix; composes principle-security. Keywords: dependency upgrade bump lockfile Dependabot Renovate semver CVE supply-chain breakage"
---

# workflow-dependency-upgrade

Structured runbook for the full upgrade lifecycle: triage → bump → test → triage breakage → PR hygiene.

**Announce at start:** "I'm using the workflow-dependency-upgrade skill to structure this dependency upgrade."

## When to invoke

- Routine dependency sweep (scheduled or prompted by CI/tooling alerts).
- Triage and merge a batch of Dependabot or Renovate PRs safely.
- A CVE has been flagged in a dependency — need to patch and verify closure.
- Major-version migration with expected API breakage.

## When NOT to invoke

- Design-time dep-graph minimization or supply-chain posture review → `swe-workbench:principle-security`.
- Release/version-bump mechanics (semver discipline, changelog, pre-release gate) → `swe-workbench:principle-release-engineering`.
- A full feature build that happens to bump a dep → `/swe-workbench:implement`.

## Composition

- **`swe-workbench:principle-security`** — supply-chain integrity, CVE triage, SBOM, lockfile pinning, frozen installs.
- **`security-auditor` agent** — CVE confirmation and dependency-graph risk read.
- **`reviewer` agent** — breakage diff read for ambiguous API/type changes.

> **Sub-skill:** `swe-workbench:workflow-commit-and-pr` — used at Phase 5 for commit format enforcement and PR filing.

## Phases

### Phase 1 — Triage & batch

1. Classify each pending upgrade as **patch**, **minor**, or **major**.
2. **Batch** low-risk patch/minor upgrades together in one PR.
3. **Pin/isolate** majors and security-critical bumps — one per PR.
4. Prefer automated tools (Dependabot/Renovate) for routine patch/minor; manual sweeps for majors.

### Phase 2 — Bump & regenerate lockfile

1. Use the ecosystem command matrix below to bump the manifest.
2. Regenerate the lockfile immediately after — never commit a stale lockfile.
3. Commit lockfile churn as a **separate atomic commit** from any code fixes.

### Phase 3 — Build & test

1. Run full build + test + typecheck + lint.
2. Run the ecosystem **audit** command to confirm a patched CVE is actually closed.
3. If the audit still flags the CVE: a transitive pin may still reference the old version — inspect and force-resolve.

### Phase 4 — Triage breakage

| Class | Typical cause | Action |
|-------|--------------|--------|
| Type / compile errors | API renamed or signature changed | Update call sites; consult `reviewer` for large diffs |
| Behavioral test failures | Semantic change in dep behavior | Read changelog/release notes; update assertions |
| Transitive / peer conflicts | Two deps require incompatible sub-dep | Force-resolve or isolate in its own PR |
| CVE still flagged post-bump | Transitive pin to old version | Override transitive dep version explicitly |

**Abort path:** if a major upgrade won't reconcile cleanly, **pin to last-good version and file an issue** rather than ship a half-migration.

### Phase 5 — PR hygiene & deliver

1. PR body must include: per-dep rationale, before/after versions, what broke and how fixed, audit/CVE evidence.
2. Keep lockfile changes and code fixes in **separate reviewable commits**.
3. Hand off to **`swe-workbench:workflow-commit-and-pr`**.

## Ecosystem command matrix

| Ecosystem | Bump | Regen lockfile | Audit |
|-----------|------|----------------|-------|
| npm | `npm update <pkg>` / `npx npm-check-updates -u` | `npm install` (auto) | `npm audit` |
| pnpm | `pnpm update <pkg>` | `pnpm install` (auto) | `pnpm audit` |
| yarn | `yarn upgrade <pkg>` | `yarn install` (auto) | `yarn npm audit` |
| cargo | `cargo update -p <crate>` | `cargo update` (auto) | `cargo audit` |
| pip/uv | `uv add <pkg>@latest` | `uv lock` | `pip-audit` |
| poetry | `poetry add <pkg>@latest` | `poetry lock --no-update` | `poetry audit` (plugin) |
| go | `go get <mod>@latest` | `go mod tidy` | `govulncheck ./...` |
| bundler | `bundle update <gem>` | `bundle install` (auto) | `bundler-audit check` |
| maven | `mvn versions:use-latest-releases` | auto | `mvn dependency-check:check` |
| gradle | edit version in build file | `./gradlew dependencies` | `./gradlew dependencyCheckAnalyze` |

## Common mistakes

| Mistake | Why it matters |
|---------|----------------|
| Batching a major with patches | Obscures API breakage risk; hard to revert one piece |
| Editing manifest without regenerating lockfile | Produces a stale lockfile that diverges from what CI installs |
| Skipping the audit re-check | CVE may persist through a transitive pin — bump alone is not enough |
| Shipping a half-done major migration | Leaves the codebase in an inconsistent compatibility state |
| Mixing lockfile + logic in one commit | Makes the diff unreadable and code review impractical |

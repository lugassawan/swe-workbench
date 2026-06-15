---
name: principle-release-engineering
description: "Release engineering: semver discipline, tag identity, rollout strategy, rollback planning, expand-contract for breaking changes, kill-switch, feature flag, release notes audience, idempotent release automation, post-release verification. Auto-load when cutting a release, planning a breaking API change, writing release notes, choosing a version bump, designing a rollback plan, using a feature flag as a kill-switch, or building release automation scripts."
---

# Release Engineering

A release is a promise: a specific artifact, at a specific version, reachable at a specific address, forever. Every discipline here protects that promise.

## Semver discipline

`MAJOR.MINOR.PATCH` — each level communicates an intent to callers.

| Bump | Meaning | Example |
|------|---------|---------|
| PATCH | Backward-compatible bug fix only | `1.2.3 → 1.2.4` |
| MINOR | New capability, backward-compatible | `1.2.3 → 1.3.0` |
| MAJOR | Breaking change — callers must adapt | `1.2.3 → 2.0.0` |

Never skip levels to signal "importance" (`1.0.0 → 3.0.0`). Pre-1.0 (`0.x.y`) still communicates intent: MINOR adds capability, PATCH fixes bugs, and a MAJOR bump to `1.0.0` signals API stability. If you're unsure between MINOR and MAJOR, default to MAJOR — over-caution is safe, under-caution breaks callers.

## Expand-contract for breaking changes

Never atomically break a public contract. Ship in three independent deployments:

1. **Expand** — add the new interface alongside the old one. Both work.
2. **Migrate** — update all callers to the new interface. Old interface idle.
3. **Contract** — remove the old interface once callers are migrated.

Each phase ships and bakes before the next begins. A rollback at any phase is safe because the old path still exists. For *schema* expand-contract mechanics — column backfills, dual-write windows, index swaps — defer to `swe-workbench:principle-data-modeling` and the `swe-workbench:migrator` agent.

## Idempotent automation

Release scripts must detect-and-resume rather than fail-fast. Re-running after a partial failure must not double-tag, double-publish, or double-bump.

- Check whether the tag already exists before creating it.
- Check whether the version is already in the registry before publishing.
- Check whether the changelog entry is already present before inserting.
- Each step is independently re-entrant: fix the failure, re-run, the completed steps are skipped.

A script that requires manual surgery to re-run has shifted the failure cost from automation to humans, at the worst possible moment.

## Pre-release gate

Every release must clear all gates before the tag is created:

- [ ] Changelog / release notes written and reviewed
- [ ] Version bumped in all manifests (`package.json`, `Cargo.toml`, `pyproject.toml`, …)
- [ ] All tests green on the release commit
- [ ] Working tree clean (no uncommitted changes)
- [ ] Tag is signed or carries provenance
- [ ] No draft state — release is explicitly published

Automate what you can. Gate what you cannot. A partial release (tag exists, package not published) is worse than no release.

## Post-release verification

CI green ≠ release successful. Confirm the artifact is actually reachable after publishing:

- Pull the published package from the registry in a clean environment.
- Smoke-test the published artifact (not the local build).
- Verify the tag points to the expected commit (`git show <tag>`).
- Confirm the release page / changelog is visible to external users.

If verification fails, yank or retract before users hit the broken artifact. A broken release discovered via user report is a support incident; one caught in verification is a near-miss.

## Rollback planning

Every release must have a documented rollback path *before* shipping — not discovered at incident time.

| Scenario | Rollback mechanism |
|----------|--------------------|
| Bug in new version | Hotfix release (PATCH bump) or yank + re-publish previous |
| Breaking change escaped | Revert via expand-contract Phase 1 (old interface was never removed) |
| Infrastructure regression | Feature-flag disable or blue-green flip to previous slot |
| Data corruption | Point-in-time restore + dual-write replay (see `migrator` agent) |

A **kill-switch** is a feature flag that disables a feature in production without a redeploy. Gate high-risk features behind a flag before release so the rollback is a config change, not a hotfix deploy. Plan the flag's removal cadence upfront — a kill-switch left in permanently becomes an untested code path and an operational liability.

"We'll figure it out" is not a rollback plan. Write the rollback steps in the release PR before merging.

## Release notes audience

Release notes are for users, not maintainers. Write for someone who has never seen your commit log.

- **No**: "Various improvements and bug fixes." **Yes**: "Fixed a crash when the config file is missing on first launch."
- **No**: "Merged PR #247 (sha: d4f3a1c)." **Yes**: "API responses now include a `request-id` header for correlation."
- **No**: Internal jargon, team nicknames, sprint references.
- **Yes**: What changed for the user, why it matters, and any action required on their side (migration steps, deprecation timeline).

Group by impact: breaking changes first (with migration guidance), then new features, then bug fixes.

## When release ceremony is overkill

- Solo experimental repos with no downstream consumers.
- Internal tools with a single operator who deploys from HEAD.
- Libraries in active spike (`0.0.x`) before the first stable API.

Even then: **tag identity** costs nothing and must never be skipped. One tag = one immutable commit. Re-pointing a published tag to a different commit silently changes what every consumer gets on a clean fetch — it is the highest-severity release mistake.

## Red Flags

| Flag | Problem |
|------|---------|
| Re-pointing a published tag | Silently changes the artifact for all consumers; breaks reproducibility |
| Force-pushing a release branch | Consumers who pinned the pre-push SHA now reference a phantom commit; a release tag may point to a ghost commit — for general branch force-push discipline see `swe-workbench:principle-version-control` |
| "fix bump version" follow-up commit after a tag | Tag and published artifact now diverge; `v1.2.3` is a lie |
| Rollback plan discovered at incident time | Means time-to-restore measured in hours, not minutes |
| Changelog written from `git log` without translation | User-facing notes become commit-message archaeology |
| Partial-failure script requiring manual surgery to re-run | Automation defeats itself; re-entry cost borne by humans under pressure |
| "CI is green, we're good" without artifact verification | Published package could be missing, corrupt, or pointing to the wrong build |

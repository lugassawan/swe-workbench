# swe-workbench tests

## Running

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements.txt
pytest tests/ -v
```

## What is covered

| File | Covers |
|---|---|
| `test_validate.py` | Every `check_*` function in `scripts/validate.py` (positive + negative) |
| `test_hooks.py` | All 3 regex blockers in `hooks/hooks.json` (block + allow cases) |
| `test_secret_guard.py` | `hooks/secret_guard.py` — 7 units: plumbing/fail-open, HIGH patterns, NEEDS-CONTEXT patterns, `# nosecret` suppression, filename allowlist, Edit routing, hooks.json wiring |
| `test_skill_triggers.py` | BM25 top-1 ranking harness across all 22 skills × their `triggers.txt` fixtures; deliberate-vague acceptance test |

Tests are hermetic: `conftest.py` redirects `validate.ROOT` to a `tmp_path` so
no test reads or writes outside of pytest's temporary directory.

## Test fixtures

### `_CLEAN_ENV` (from `conftest.py`)

`swe-workbench` is a bare git repository (`core.bare = true`). When tests run
inside a git hook (e.g. a `pre-push` hook), Git exports `GIT_DIR` pointing at
the bare repo. Any subprocess that calls `git` inherits `GIT_DIR` and Git
mistakenly treats the temp test directory as a bare repo too — causing
hard-to-diagnose test failures.

`_CLEAN_ENV` strips every `GIT_*` environment variable and re-adds
`GIT_CONFIG_NOSYSTEM=1` for system-gitconfig hermeticity. Use it whenever a
test spawns a subprocess that runs `git` or a shell script that calls `git`:

```python
# Pass the clean env directly:
subprocess.run(["git", "init", str(tmp_path)], env=_CLEAN_ENV, check=True)

# Extend it with extra vars (PATH stub, CLAUDE_PROJECT_DIR, etc.):
subprocess.run(cmd, env={**_CLEAN_ENV, "MY_VAR": "value"}, check=True)
```

Do **not** pass `env=os.environ` (or omit `env=`) for subprocess sites that
call `git` — the hook-context `GIT_DIR` will leak through and target the
wrong repository.

## Deliberate-break proof (required by issue #76)

To verify that a bug in `validate.py` causes at least one test to fail:

1. Open `scripts/validate.py` and comment out the `fail(...)` call on the line
   that handles a missing `description` field in `check_skills` (around line 127):

   ```python
   # fail(skill_md.relative_to(ROOT), "frontmatter missing required field: 'description'")
   ```

2. Run the targeted test:

   ```bash
   pytest tests/test_validate.py -k "missing_description" -v
   ```

   `TestCheckSkills::test_missing_description_fails` will **fail** because the
   validator no longer records the expected failure.

3. Revert the comment to restore the validator.

To verify `check_template_placeholders` is tested:

1. Open `scripts/validate.py` and comment out the `fail(...)` call inside
   `check_template_placeholders`:

   ```python
   # fail(
   #     template.relative_to(ROOT),
   #     f"undocumented marker '[[detect:{key}]]' — add `{key}` to "
   #     f"'## Project Detection' in {skill_md.relative_to(ROOT)}",
   # )
   ```

2. Run the targeted test:

   ```bash
   pytest tests/test_validate.py -k "orphan_marker" -v
   ```

   `TestCheckTemplatePlaceholders::test_orphan_marker_fails` will **fail** because
   the validator no longer records the expected failure.

3. Revert the comment to restore the validator.

To verify the missing-file path in `check_skill_trigger_fixtures` is tested:

1. Open `scripts/validate.py` and comment out the `fail(...)` call inside
   `check_skill_trigger_fixtures` for the missing-file case:

   ```python
   # fail(
   #     triggers.relative_to(ROOT),
   #     "missing — every skill needs ≥2 trigger fixtures ...",
   # )
   ```

2. Run the targeted test:

   ```bash
   pytest tests/test_validate.py -k "missing_triggers" -v
   ```

   `TestCheckSkillTriggerFixtures::test_missing_triggers_file_fails` will **fail**
   because the validator no longer records the expected failure.

3. Revert the comment to restore the validator.

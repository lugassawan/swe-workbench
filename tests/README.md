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

Tests are hermetic: `conftest.py` redirects `validate.ROOT` to a `tmp_path` so
no test reads or writes outside of pytest's temporary directory.

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

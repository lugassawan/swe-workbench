import os
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

# _CLEAN_ENV: subprocess-safe environment for tests that spawn git or bash.
#
# swe-workbench is a bare git repo (core.bare=true). When tests run inside a
# git hook (e.g. pre-push), GIT_DIR is exported and inherited by subprocess
# children — Git then treats temp test repos as bare too, causing failures.
# We strip every GIT_* var, then re-add GIT_CONFIG_NOSYSTEM=1 to ignore the
# system gitconfig for hermeticity.
#
# Snapshot: built once from os.environ at pytest collection time. Session-scoped
# fixtures that mutate GIT_* vars after import will not be reflected here.
#
# Usage:
#   subprocess.run([...], env=_CLEAN_ENV, ...)
#   subprocess.run([...], env={**_CLEAN_ENV, "KEY": "val"}, ...)
_CLEAN_ENV: Final[MappingProxyType[str, str]] = MappingProxyType(
    {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    | {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@t.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@t.com",
    }
)

# Ensure scripts/ and tests/ are importable from any working directory.
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "scripts"))
import validate  # noqa: E402


@pytest.fixture(autouse=True)
def reset_validate(monkeypatch, tmp_path):
    """Clear FAILURES and redirect ROOT to a temp directory before each test."""
    validate.FAILURES.clear()
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    yield tmp_path

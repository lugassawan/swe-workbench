import os
import subprocess
from types import MappingProxyType
from typing import Final

import pytest

# _CLEAN_ENV: subprocess-safe environment for tests that spawn git or bash.
#
# When tests run inside a git hook (e.g. pre-push), GIT_DIR is exported and
# inherited by subprocess children — Git then treats temp test repos as if
# they share the host repo's git context, causing failures.
# We strip every GIT_* var, then re-add GIT_CONFIG_NOSYSTEM=1 to ignore the
# system gitconfig for hermeticity. GIT_CONFIG_COUNT/KEY/VALUE_0 additionally
# suppresses commit.gpgsign so tests don't fail on machines with GPG signing
# enabled in ~/.gitconfig (which GIT_CONFIG_NOSYSTEM does not cover).
#
# GITHUB_STEP_SUMMARY is also stripped: GitHub Actions sets it for every step
# of a job, not just steps that opt in. Without stripping it, tests that spawn
# scripts writing to that path (e.g. check-lockfile-additions.sh) would leak
# fabricated content into the real pytest job's Job Summary when this suite
# runs in CI. Tests that want to exercise that write path opt back in via
# env={**_CLEAN_ENV, "GITHUB_STEP_SUMMARY": str(tmp_file)}.
#
# Snapshot: built once from os.environ at pytest collection time. Session-scoped
# fixtures that mutate GIT_* vars after import will not be reflected here.
#
# Usage:
#   subprocess.run([...], env=_CLEAN_ENV, ...)
#   subprocess.run([...], env={**_CLEAN_ENV, "KEY": "val"}, ...)
_CLEAN_ENV: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and k != "GITHUB_STEP_SUMMARY"
    }
    | {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@t.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@t.com",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "commit.gpgsign",
        "GIT_CONFIG_VALUE_0": "false",
    }
)

_GIT_DIR_GUARD_SENTINEL: Final[str] = "__pytest_git_dir_sentinel__"


@pytest.fixture(autouse=True, scope="session")
def _git_dir_leak_guard():
    """Fail loudly if any subprocess.run receives GIT_DIR in its env.
    Injects a sentinel GIT_DIR so the guard fires standalone (not just under the hook).
    See tests/README.md for the _CLEAN_ENV pattern.
    Coverage note: patching subprocess.run also covers subprocess.check_output (which
    delegates to run on CPython — implementation detail, not guaranteed by the stdlib spec).
    subprocess.call / check_call go directly to Popen and are NOT covered — avoid them in tests."""
    _orig_run = subprocess.run

    def _guarded_run(*args, **kwargs):
        if "env" in kwargs and kwargs["env"] is not None:
            effective = kwargs["env"]
        else:
            effective = os.environ
        if "GIT_DIR" in effective:
            raise AssertionError(
                "subprocess.run was called with GIT_DIR in its environment. "
                "This leaks the bare repo's git context into git children. "
                "Use env=dict(_CLEAN_ENV) or env={**_CLEAN_ENV, ...}. "
                "See tests/README.md."
            )
        return _orig_run(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GIT_DIR", _GIT_DIR_GUARD_SENTINEL)
        mp.setattr(subprocess, "run", _guarded_run)
        yield


# scripts/ and tests/ are on sys.path via pyproject.toml [tool.pytest.ini_options] pythonpath.
import validate  # noqa: E402  (available via pyproject.toml pythonpath)


@pytest.fixture(autouse=True)
def reset_validate(monkeypatch, tmp_path):
    """Clear FAILURES and redirect ROOT to a temp directory before each test.

    Both setup and teardown clear FAILURES so the fixture is safe under
    pytest-xdist: each worker process gets its own copy of the validate module
    (xdist is process-based, not thread-based), but within a worker the fixture
    still prevents cross-test contamination regardless of execution order.
    """
    validate.FAILURES.clear()
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    yield tmp_path
    validate.FAILURES.clear()

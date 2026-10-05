"""Behavioral tests for scripts/sync-peer-deps.sh.

Each case builds a hermetic temp copy of the script alongside a minimal
package.json/package-lock.json pair (ROOT resolves relative to the script's
own location, same convention as scripts/bump-version.sh), then runs it via
subprocess and asserts exit code + file contents.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "sync-peer-deps.sh"

_SYNCED_PKG = {
    "devDependencies": {
        "@earendil-works/pi-coding-agent": "0.84.4",
        "@earendil-works/pi-tui": "0.84.4",
    },
    "peerDependencies": {
        "@earendil-works/pi-coding-agent": ">=0.84.4 <1",
        "@earendil-works/pi-tui": ">=0.84.4 <1",
    },
}

_DRIFTED_PKG = {
    "devDependencies": {
        "@earendil-works/pi-coding-agent": "0.84.4",
        "@earendil-works/pi-tui": "0.84.4",
    },
    "peerDependencies": {
        "@earendil-works/pi-coding-agent": ">=0.84.3 <1",
        "@earendil-works/pi-tui": ">=0.84.3 <1",
    },
}

_LOCK_TEMPLATE = {
    "lockfileVersion": 3,
    "packages": {
        "": {
            "peerDependencies": {
                "@earendil-works/pi-coding-agent": ">=0.84.3 <1",
                "@earendil-works/pi-tui": ">=0.84.3 <1",
            }
        }
    },
}


def _scaffold(
    tmp_path: Path, pkg: dict, lock_range: str, lock_tui_range: str | None = None
) -> Path:
    """Copy the script into tmp_path/scripts and write matching manifests."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(SCRIPT, scripts_dir / SCRIPT.name)

    (tmp_path / "package.json").write_text(json.dumps(pkg, indent=2) + "\n")

    lock = json.loads(json.dumps(_LOCK_TEMPLATE))
    lock["packages"][""]["peerDependencies"]["@earendil-works/pi-coding-agent"] = lock_range
    lock["packages"][""]["peerDependencies"]["@earendil-works/pi-tui"] = lock_tui_range or lock_range
    (tmp_path / "package-lock.json").write_text(json.dumps(lock, indent=2) + "\n")

    return scripts_dir / SCRIPT.name


def _run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
    )


class TestSyncPeerDepsCheck:
    def test_check_passes_when_already_synced(self, tmp_path):
        script = _scaffold(tmp_path, _SYNCED_PKG, ">=0.84.4 <1")
        result = _run(script, "--check", cwd=tmp_path)
        assert result.returncode == 0
        assert "already in sync" in result.stdout

    def test_check_fails_when_drifted(self, tmp_path):
        script = _scaffold(tmp_path, _DRIFTED_PKG, ">=0.84.3 <1")
        result = _run(script, "--check", cwd=tmp_path)
        assert result.returncode == 1
        assert "out of sync" in result.stderr

    def test_check_makes_no_changes_on_drift(self, tmp_path):
        script = _scaffold(tmp_path, _DRIFTED_PKG, ">=0.84.3 <1")
        before = (tmp_path / "package.json").read_text()
        _run(script, "--check", cwd=tmp_path)
        after = (tmp_path / "package.json").read_text()
        assert before == after, "--check must never write to package.json"


class TestSyncPeerDepsApply:
    def test_apply_fixes_package_json(self, tmp_path):
        script = _scaffold(tmp_path, _DRIFTED_PKG, ">=0.84.3 <1")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 0

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert pkg["peerDependencies"]["@earendil-works/pi-coding-agent"] == ">=0.84.4 <1"
        assert pkg["peerDependencies"]["@earendil-works/pi-tui"] == ">=0.84.4 <1"

    def test_apply_fixes_package_lock_json(self, tmp_path):
        script = _scaffold(tmp_path, _DRIFTED_PKG, ">=0.84.3 <1")
        _run(script, cwd=tmp_path)

        lock = json.loads((tmp_path / "package-lock.json").read_text())
        peers = lock["packages"][""]["peerDependencies"]
        assert peers["@earendil-works/pi-coding-agent"] == ">=0.84.4 <1"
        assert peers["@earendil-works/pi-tui"] == ">=0.84.4 <1"

    def test_apply_is_idempotent(self, tmp_path):
        script = _scaffold(tmp_path, _DRIFTED_PKG, ">=0.84.3 <1")
        _run(script, cwd=tmp_path)
        second = _run(script, cwd=tmp_path)
        assert second.returncode == 0
        assert "already in sync" in second.stdout

    def test_apply_on_already_synced_files_is_a_noop(self, tmp_path):
        script = _scaffold(tmp_path, _SYNCED_PKG, ">=0.84.4 <1")
        before_pkg = (tmp_path / "package.json").read_text()
        before_lock = (tmp_path / "package-lock.json").read_text()
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 0
        assert (tmp_path / "package.json").read_text() == before_pkg
        assert (tmp_path / "package-lock.json").read_text() == before_lock

    def test_missing_devdependencies_pin_errors(self, tmp_path):
        pkg = {"devDependencies": {}, "peerDependencies": {
            "@earendil-works/pi-coding-agent": ">=0.84.3 <1",
        }}
        script = _scaffold(tmp_path, pkg, ">=0.84.3 <1")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 2
        assert "could not read" in result.stderr

    def test_mismatched_devdependencies_pins_errors(self, tmp_path):
        """pi-coding-agent and pi-tui bump as two SEPARATE dependabot PRs (dependabot.yml has
        no npm `groups:`), so the first PR of every such pair always lands here — this must
        be a hard error (exit 2), distinct from actionable range drift (exit 1), so
        .github/workflows/dependabot-peer-sync.yml treats it as a clean no-op rather than
        attempting (and failing) an apply it can't complete."""
        pkg = json.loads(json.dumps(_SYNCED_PKG))
        pkg["devDependencies"]["@earendil-works/pi-tui"] = "0.84.3"
        script = _scaffold(tmp_path, pkg, ">=0.84.4 <1")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 2
        assert "out of lockstep" in result.stderr

    def test_mismatched_devdependencies_pins_errors_in_check_mode(self, tmp_path):
        pkg = json.loads(json.dumps(_SYNCED_PKG))
        pkg["devDependencies"]["@earendil-works/pi-tui"] = "0.84.3"
        script = _scaffold(tmp_path, pkg, ">=0.84.4 <1")
        result = _run(script, "--check", cwd=tmp_path)
        assert result.returncode == 2
        assert "out of lockstep" in result.stderr

    def test_missing_peerdependencies_key_errors(self, tmp_path):
        pkg = {
            "devDependencies": {
                "@earendil-works/pi-coding-agent": "0.84.4",
                "@earendil-works/pi-tui": "0.84.4",
            },
            "peerDependencies": {},
        }
        script = _scaffold(tmp_path, pkg, ">=0.84.4 <1")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 2
        assert "could not read peerDependencies" in result.stderr


def _pkg(pin: str, agent_range: str, tui_range: str | None = None) -> dict:
    return {
        "devDependencies": {
            "@earendil-works/pi-coding-agent": pin,
            "@earendil-works/pi-tui": pin,
        },
        "peerDependencies": {
            "@earendil-works/pi-coding-agent": agent_range,
            "@earendil-works/pi-tui": tui_range or agent_range,
        },
    }


class TestSyncPeerDepsCeiling:
    """The ceiling is derived from the pin's major (`<{major+1}`), not hardcoded, so a 0.x
    pin keeps `<1` while a 1.x pin yields `<2` instead of the unsatisfiable `>=1.0.3 <1`."""

    def test_check_flags_ceiling_only_drift(self, tmp_path):
        script = _scaffold(tmp_path, _pkg("1.0.3", ">=1.0.3 <1"), ">=1.0.3 <1")
        result = _run(script, "--check", cwd=tmp_path)
        assert result.returncode == 1
        assert "out of sync" in result.stderr
        assert "expected >=1.0.3 <2" in result.stderr

    def test_apply_crossing_to_next_major_writes_new_ceiling_everywhere(self, tmp_path):
        script = _scaffold(tmp_path, _pkg("1.0.3", ">=0.99.2 <1"), ">=0.99.2 <1")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 0

        pkg = json.loads((tmp_path / "package.json").read_text())
        lock = json.loads((tmp_path / "package-lock.json").read_text())
        for peers in (pkg["peerDependencies"], lock["packages"][""]["peerDependencies"]):
            assert peers["@earendil-works/pi-coding-agent"] == ">=1.0.3 <2"
            assert peers["@earendil-works/pi-tui"] == ">=1.0.3 <2"

    def test_zero_major_pin_keeps_ceiling_below_one(self, tmp_path):
        script = _scaffold(tmp_path, _pkg("0.99.2", ">=0.84.3 <1"), ">=0.84.3 <1")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 0
        assert "::warning::" not in result.stdout

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert pkg["peerDependencies"]["@earendil-works/pi-coding-agent"] == ">=0.99.2 <1"

    def test_apply_warns_when_ceiling_widens(self, tmp_path):
        script = _scaffold(tmp_path, _pkg("1.0.3", ">=0.99.2 <1"), ">=0.99.2 <1")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 0
        assert "::warning::peerDependencies ceiling changed from <1 to <2" in result.stdout

    def test_apply_with_unchanged_ceiling_does_not_warn(self, tmp_path):
        script = _scaffold(tmp_path, _pkg("1.0.4", ">=1.0.3 <2"), ">=1.0.3 <2")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 0
        assert "::warning::" not in result.stdout


class TestSyncPeerDepsAllSites:
    """--check must cover every write site: both packages x (package.json, lock)."""

    _SYNCED = ">=0.84.4 <1"
    _STALE = ">=0.84.3 <1"

    # Each case drifts exactly one site, so dropping any single site from the script's
    # check leaves its case failing.
    _SITE_CASES = {
        "package.json pi-coding-agent": dict(pkg_agent=_STALE),
        "package.json pi-tui": dict(pkg_tui=_STALE),
        "package-lock.json pi-coding-agent": dict(lock_agent=_STALE),
        "package-lock.json pi-tui": dict(lock_tui=_STALE),
    }

    @staticmethod
    def _scaffold_one_site(tmp_path, pkg_agent=_SYNCED, pkg_tui=_SYNCED,
                           lock_agent=_SYNCED, lock_tui=_SYNCED):
        pkg = _pkg("0.84.4", pkg_agent, tui_range=pkg_tui)
        return _scaffold(tmp_path, pkg, lock_agent, lock_tui_range=lock_tui)

    @pytest.mark.parametrize("site", _SITE_CASES)
    def test_check_flags_single_site_drift(self, tmp_path, site):
        script = self._scaffold_one_site(tmp_path, **self._SITE_CASES[site])
        result = _run(script, "--check", cwd=tmp_path)
        assert result.returncode == 1
        assert site in result.stderr

    @pytest.mark.parametrize("site", _SITE_CASES)
    def test_apply_repairs_single_site_drift(self, tmp_path, site):
        script = self._scaffold_one_site(tmp_path, **self._SITE_CASES[site])
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 0
        for manifest in (
            json.loads((tmp_path / "package.json").read_text())["peerDependencies"],
            json.loads((tmp_path / "package-lock.json").read_text())["packages"][""][
                "peerDependencies"
            ],
        ):
            assert manifest["@earendil-works/pi-coding-agent"] == self._SYNCED
            assert manifest["@earendil-works/pi-tui"] == self._SYNCED

    def test_unreadable_lockfile_is_a_hard_error_not_drift(self, tmp_path):
        script = _scaffold(tmp_path, _pkg("0.84.4", ">=0.84.4 <1"), ">=0.84.4 <1")
        (tmp_path / "package-lock.json").unlink()
        result = _run(script, "--check", cwd=tmp_path)
        assert result.returncode == 2
        assert "could not read" in result.stderr


class TestSyncPeerDepsPinValidation:
    @pytest.mark.parametrize(
        "pin", ["^1.0.3", "~1.0.3", "1.0.3-beta.1", "1.0", "v1.0.3", "08.0.1", "1.0.03"]
    )
    def test_malformed_pin_errors(self, tmp_path, pin):
        script = _scaffold(tmp_path, _pkg(pin, ">=1.0.3 <2"), ">=1.0.3 <2")
        for args in (("--check",), ()):
            result = _run(script, *args, cwd=tmp_path)
            assert result.returncode == 2
            assert "exact X.Y.Z" in result.stderr


class TestSyncPeerDepsCeilingWarning:
    def test_missing_ceiling_is_reported_as_none(self, tmp_path):
        script = _scaffold(tmp_path, _pkg("0.84.4", ">=0.84.4"), ">=0.84.4")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 0
        assert "::warning::peerDependencies ceiling changed from none to <1" in result.stdout

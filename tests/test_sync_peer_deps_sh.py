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


def _scaffold(tmp_path: Path, pkg: dict, lock_floor: str) -> Path:
    """Copy the script into tmp_path/scripts and write matching manifests."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(SCRIPT, scripts_dir / SCRIPT.name)

    (tmp_path / "package.json").write_text(json.dumps(pkg, indent=2) + "\n")

    lock = json.loads(json.dumps(_LOCK_TEMPLATE))
    lock["packages"][""]["peerDependencies"]["@earendil-works/pi-coding-agent"] = lock_floor
    lock["packages"][""]["peerDependencies"]["@earendil-works/pi-tui"] = lock_floor
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
        assert result.returncode == 1
        assert "could not read" in result.stderr

    def test_mismatched_devdependencies_pins_errors(self, tmp_path):
        """pi-coding-agent and pi-tui are published lockstep — a partial bump that moves
        only one of the two pins must fail loudly rather than silently deriving the
        expected floor from whichever pin happened to be read."""
        pkg = json.loads(json.dumps(_SYNCED_PKG))
        pkg["devDependencies"]["@earendil-works/pi-tui"] = "0.84.3"
        script = _scaffold(tmp_path, pkg, ">=0.84.4 <1")
        result = _run(script, cwd=tmp_path)
        assert result.returncode == 1
        assert "out of lockstep" in result.stderr

    def test_mismatched_devdependencies_pins_errors_in_check_mode(self, tmp_path):
        pkg = json.loads(json.dumps(_SYNCED_PKG))
        pkg["devDependencies"]["@earendil-works/pi-tui"] = "0.84.3"
        script = _scaffold(tmp_path, pkg, ">=0.84.4 <1")
        result = _run(script, "--check", cwd=tmp_path)
        assert result.returncode == 1
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
        assert result.returncode == 1
        assert "could not read peerDependencies" in result.stderr

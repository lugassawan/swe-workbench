"""Static guards for the hashed pip-tools bootstrap (finding #7).

These tests are intentionally static (no subprocess) so they run fast
in CI without needing Python 3.12 in the test environment.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOCK_SCRIPT = ROOT / "scripts" / "lock-pip-requirements.sh"
BUILD_REQ_TXT = ROOT / "tests" / "build-requirements.txt"
BUILD_REQ_LOCK = ROOT / "tests" / "build-requirements.lock"


class TestBuildRequirementsSource:
    def test_build_requirements_txt_exists(self):
        assert BUILD_REQ_TXT.exists(), "tests/build-requirements.txt is missing"

    def test_build_requirements_txt_pins_pip_tools(self):
        content = BUILD_REQ_TXT.read_text()
        assert re.search(r"pip-tools==\d+\.\d+\.\d+", content), (
            "tests/build-requirements.txt must pin pip-tools to an exact version"
        )


class TestBuildRequirementsLock:
    def test_build_requirements_lock_exists(self):
        assert BUILD_REQ_LOCK.exists(), (
            "tests/build-requirements.lock is missing — run scripts/lock-pip-requirements.sh"
        )

    def test_build_requirements_lock_has_hash_lines(self):
        content = BUILD_REQ_LOCK.read_text()
        assert "--hash=sha256:" in content, (
            "tests/build-requirements.lock must contain hash lines (--hash=sha256:...)"
        )

    def test_build_requirements_lock_contains_pip_tools(self):
        content = BUILD_REQ_LOCK.read_text()
        assert re.search(r"pip-tools==\d+\.\d+\.\d+", content), (
            "tests/build-requirements.lock must list pip-tools"
        )


class TestBootstrapUsesRequireHashes:
    def test_lock_script_bootstraps_with_require_hashes(self):
        """Bootstrap step must use --require-hashes to consume build-requirements.lock."""
        content = LOCK_SCRIPT.read_text()
        assert "--require-hashes" in content, (
            "lock-pip-requirements.sh must bootstrap pip-tools with --require-hashes"
        )

    def test_lock_script_references_build_requirements_lock(self):
        content = LOCK_SCRIPT.read_text()
        assert "build-requirements.lock" in content, (
            "lock-pip-requirements.sh must reference tests/build-requirements.lock"
        )

    def test_lock_script_compiles_build_requirements(self):
        """The script must compile build-requirements.txt → .lock so --check refreshes it."""
        content = LOCK_SCRIPT.read_text()
        assert re.search(r"compile\s+tests/build-requirements\.txt\s+tests/build-requirements\.lock", content), (
            "lock-pip-requirements.sh must include a compile call for build-requirements"
        )

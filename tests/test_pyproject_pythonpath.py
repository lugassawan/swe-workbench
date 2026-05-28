"""Structural guard: pyproject.toml must declare pythonpath; conftest.py must not
use sys.path.insert (the pyproject.toml setting replaces it).
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CONFTEST = ROOT / "tests" / "conftest.py"


class TestPyprojectPythonpath:
    def test_pyproject_toml_exists(self):
        assert PYPROJECT.exists(), "pyproject.toml is missing"

    def test_pyproject_declares_pythonpath(self):
        content = PYPROJECT.read_text()
        assert "pythonpath" in content, (
            "pyproject.toml must declare [tool.pytest.ini_options] pythonpath"
        )

    def test_pyproject_pythonpath_includes_tests(self):
        content = PYPROJECT.read_text()
        assert '"tests"' in content or "'tests'" in content, (
            "pyproject.toml pythonpath must include 'tests'"
        )

    def test_pyproject_pythonpath_includes_scripts(self):
        content = PYPROJECT.read_text()
        assert '"scripts"' in content or "'scripts'" in content, (
            "pyproject.toml pythonpath must include 'scripts'"
        )


class TestConftestNoPatch:
    def test_conftest_does_not_call_sys_path_insert(self):
        """sys.path.insert is replaced by pyproject.toml pythonpath — must be absent."""
        content = CONFTEST.read_text()
        assert "sys.path.insert" not in content, (
            "conftest.py must not call sys.path.insert; "
            "use pyproject.toml [tool.pytest.ini_options] pythonpath instead"
        )

    def test_conftest_does_not_import_sys(self):
        """sys is no longer needed after removing sys.path.insert."""
        content = CONFTEST.read_text()
        # Allow 'sys' as part of other identifiers, but not as a standalone import
        assert not re.search(r"^import sys\b", content, re.MULTILINE), (
            "conftest.py should not import sys (sys.path.insert removed)"
        )

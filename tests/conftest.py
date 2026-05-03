import sys
from pathlib import Path

import pytest

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

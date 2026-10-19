"""Ratchet: no test module may call `tempfile.mkdtemp`.

`mkdtemp` hands back a directory nobody removes, so every suite run leaks one into the
system temp dir, outside pytest's `tmp_path` retention. Use `tmp_path` /
`tmp_path_factory`, or `tempfile.TemporaryDirectory` when a test needs a directory
mid-helper.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent


def _mkdtemp_uses(source: str) -> list[int]:
    """Line numbers of every reference to `mkdtemp`, called or aliased away."""
    lines = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == "mkdtemp":
            lines.add(node.lineno)
        elif isinstance(node, ast.Name) and node.id == "mkdtemp":
            lines.add(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "tempfile":
            if any(alias.name in ("mkdtemp", "*") for alias in node.names):
                lines.add(node.lineno)
    return sorted(lines)


@pytest.mark.parametrize(
    "source",
    [
        "import tempfile\nd = tempfile.mkdtemp()\n",
        "import tempfile\nd = tempfile.mkdtemp(prefix='x-')\n",
        "from tempfile import mkdtemp\nd = mkdtemp()\n",
        "from tempfile import mkdtemp as md\n",
        "import tempfile as tf\nd = tf.mkdtemp()\n",
        "from tempfile import *\nd = mkdtemp()\n",
        "import tempfile\nf = tempfile.mkdtemp\n",
    ],
)
def test_detector_flags_mkdtemp(source):
    assert _mkdtemp_uses(source)


@pytest.mark.parametrize(
    "source",
    [
        "import tempfile\nwith tempfile.TemporaryDirectory() as d:\n    pass\n",
        "from tempfile import TemporaryDirectory\n",
        "d = tmp_path_factory.mktemp('x')\n",
        "s = 'tempfile.mkdtemp()'\n",
        "# tempfile.mkdtemp() leaks\n",
    ],
)
def test_detector_ignores_safe_code(source):
    assert _mkdtemp_uses(source) == []


def test_detector_reports_line_numbers():
    assert _mkdtemp_uses("import tempfile\n\nd = tempfile.mkdtemp()\n") == [3]


def test_no_test_module_uses_mkdtemp():
    paths = sorted(TESTS_DIR.rglob("*.py"))
    assert paths, f"no test modules found under {TESTS_DIR}"
    hits = []
    for path in paths:
        for line in _mkdtemp_uses(path.read_text(encoding="utf-8")):
            hits.append(f"{path.relative_to(TESTS_DIR)}:{line}")
    assert not hits, (
        "mkdtemp leaks a directory per run (use tmp_path / tmp_path_factory, "
        f"or tempfile.TemporaryDirectory): {', '.join(hits)}"
    )

"""Tests for scripts/preload-probe.mjs.

This is a new shared file across several C-track tasks (issue #681). This task (Task 2) covers
only the `cache --dry-run` surface — the ONLY path exercised here. The live dispatch path (which
actually spawns `pi` twice and reads real provider-billed usage) is explicitly out of scope for
automated tests: it requires `pi auth` configured for a provider and costs real money. It is
exercised by a human, once, outside this test suite — see the "Operational constraint" section of
this task's brief.

Node-version gating mirrors tests/test_pi_extension.py's `_node_major_version` / `_NODE_TOO_OLD` /
`requires_node` pattern (duplicated here rather than imported — this repo already duplicates this
small helper across more than one test file).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "scripts" / "preload-probe.mjs"


def _node_major_version():
    node = shutil.which("node")
    if node is None:
        return None
    result = subprocess.run(
        [node, "--version"], capture_output=True, text=True, env=_CLEAN_ENV, timeout=10
    )
    # "v22.6.0\n" -> 22
    return int(result.stdout.strip().lstrip("v").split(".")[0])


_NODE_MAJOR = _node_major_version()
_NODE_TOO_OLD = _NODE_MAJOR is None or _NODE_MAJOR < 22

requires_node = pytest.mark.skipif(
    _NODE_TOO_OLD,
    reason="preload-probe.mjs behavioural tests require Node >= 22 (--experimental-strip-types)",
)


def _run_probe(args, **kwargs):
    node = shutil.which("node")
    assert node is not None
    return subprocess.run(
        [node, "--experimental-strip-types", str(PROBE), *args],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=30,
        **kwargs,
    )


@pytest.fixture(scope="module")
def real_agent_id():
    """A real agents/*.md id, verified against listAgentNames rather than hardcoded — the brief
    warns against assuming a specific id exists."""
    agents_dir = ROOT / "agents"
    names = sorted(p.stem for p in agents_dir.glob("*.md"))
    assert names, "expected at least one agents/*.md file"
    assert "reviewer" in names, "expected 'reviewer' agent to exist (used as the test fixture id)"
    return "reviewer"


@requires_node
def test_cache_dry_run_prints_expected_argv_shape(real_agent_id):
    result = _run_probe(["cache", "--agent", real_agent_id, "--dry-run"])
    assert result.returncode == 0, f"probe failed: {result.stderr}"

    argv = json.loads(result.stdout)
    assert isinstance(argv, list)
    for expected in ("-p", "--append-system-prompt", "--no-session", "--mode", "json"):
        assert expected in argv, f"expected {expected!r} in dry-run argv: {argv}"

    # Simplifications versus subagent.ts must actually be taken, not silently expanded.
    assert "--tools" not in argv
    assert "--model" not in argv


@requires_node
def test_cache_dry_run_unknown_agent_fails_with_not_found_message():
    result = _run_probe(["cache", "--agent", "totally-not-a-real-agent", "--dry-run"])
    assert result.returncode != 0
    assert "totally-not-a-real-agent" in result.stderr
    assert "not" in result.stderr.lower() or "unknown" in result.stderr.lower()


@requires_node
def test_cache_without_agent_flag_fails_with_usage_error():
    result = _run_probe(["cache", "--dry-run"])
    assert result.returncode != 0
    assert "--agent" in result.stderr


@requires_node
def test_unknown_subcommand_fails():
    result = _run_probe(["ablate", "--agent", "reviewer", "--dry-run"])
    assert result.returncode != 0
    assert "cache" in result.stderr

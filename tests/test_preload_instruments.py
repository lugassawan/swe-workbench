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
FLUSH_SH = ROOT / "hooks" / "skill_usage_flush.sh"


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


_PRELOAD_CANARY_BEGIN = "<!-- BEGIN shared/agents/preload-canary-citation.md -->"
_PRELOAD_CANARY_END = "<!-- END shared/agents/preload-canary-citation.md -->"


def test_all_agents_carry_the_preload_canary_citation_block():
    """Task 4 (C2 emit) inlines shared/agents/preload-canary-citation.md into every agents/*.md
    file via the sentinel-block mechanism. No Node/`pi` involvement needed here — this is a plain
    text-shape assertion over the static agent files, so it does not need `requires_node`."""
    agents_dir = ROOT / "agents"
    agent_files = sorted(agents_dir.glob("*.md"))
    assert len(agent_files) == 22, f"expected 22 agents/*.md files, found {len(agent_files)}"

    for path in agent_files:
        text = path.read_text()
        assert _PRELOAD_CANARY_BEGIN in text, f"{path.name} missing BEGIN sentinel"
        assert _PRELOAD_CANARY_END in text, f"{path.name} missing END sentinel"

        begin_idx = text.index(_PRELOAD_CANARY_BEGIN) + len(_PRELOAD_CANARY_BEGIN)
        end_idx = text.index(_PRELOAD_CANARY_END)
        assert begin_idx < end_idx, f"{path.name} has END before BEGIN"

        inner = text[begin_idx:end_idx].strip()
        assert inner, f"{path.name} has an empty preload-canary-citation block (sync not run?)"


# ---------------------------------------------------------------------------
# Task 5 (C2 harvest) — hooks/skill_usage_flush.sh reads back
# SWB-CANARIES-APPLIED and appends canary-citations.jsonl.
#
# Fixture/subprocess pattern mirrors tests/test_skill_usage_telemetry.py
# (same hook, same env wiring), duplicated here rather than imported since
# that file's fixtures are function-scoped and private to its module.
# ---------------------------------------------------------------------------


@pytest.fixture()
def canary_plugin_root(tmp_path: Path) -> Path:
    """Minimal plugin dir with an agents/reviewer.md (no opt-out)."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "reviewer.md").write_text(
        "---\nname: reviewer\nmodel: sonnet\n---\nReviewer body.\n"
    )
    return tmp_path


@pytest.fixture()
def canary_cache_dir(tmp_path: Path) -> Path:
    """Isolated cache directory; CLAUDE_PROJECT_DIR points here."""
    d = tmp_path / "project"
    d.mkdir()
    return d


def _canary_env(plugin_root: Path, cache_dir: Path) -> dict:
    env = dict(_CLEAN_ENV)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    env["CLAUDE_PROJECT_DIR"] = str(cache_dir)
    return env


def _run_flush_for_canary(
    stdin_json: dict, plugin_root: Path, cache_dir: Path
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(FLUSH_SH)],
        input=json.dumps(stdin_json),
        capture_output=True,
        text=True,
        env=_canary_env(plugin_root, cache_dir),
    )


def _citations_file(cache_dir: Path) -> Path:
    return cache_dir / ".claude" / "cache" / "skill-usage" / "canary-citations.jsonl"


def _read_citation_records(cache_dir: Path) -> list[dict]:
    path = _citations_file(cache_dir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestCanaryCitationHarvest:
    def test_citation_marker_appends_jsonl_record(self, canary_plugin_root, canary_cache_dir):
        """A last_assistant_message ending in the marker line appends a JSONL
        record with the parsed, namespaced skill ids."""
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-001",
                "agent_type": "reviewer",
                "last_assistant_message": (
                    "Some analysis here.\n"
                    "SWB-CANARIES-APPLIED: swe-workbench:principle-ddd, "
                    "swe-workbench:principle-tdd"
                ),
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["agent_type"] == "reviewer"
        assert records[0]["agent_id"] == "cite-001"
        assert records[0]["cited_skills"] == [
            "swe-workbench:principle-ddd",
            "swe-workbench:principle-tdd",
        ]

    def test_citation_marker_none_appends_empty_list(self, canary_plugin_root, canary_cache_dir):
        """SWB-CANARIES-APPLIED: NONE → a record with an empty cited_skills array."""
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-002",
                "agent_type": "reviewer",
                "last_assistant_message": "Nothing applied.\nSWB-CANARIES-APPLIED: NONE",
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["cited_skills"] == []

    def test_missing_last_assistant_message_is_silent_noop(
        self, canary_plugin_root, canary_cache_dir
    ):
        """No last_assistant_message field at all → exits 0, emits the same {}
        the existing skill-usage flush emits for an agent with no buffer, and
        never creates canary-citations.jsonl."""
        result = _run_flush_for_canary(
            {"agent_id": "cite-003", "agent_type": "reviewer"},
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {}
        assert not _citations_file(canary_cache_dir).exists()

    def test_message_without_marker_line_is_noop(self, canary_plugin_root, canary_cache_dir):
        """last_assistant_message present but no SWB-CANARIES-APPLIED line →
        no citation record written, hook still exits 0."""
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-004",
                "agent_type": "reviewer",
                "last_assistant_message": "Just an ordinary response with no marker.",
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        assert _read_citation_records(canary_cache_dir) == []

    def test_citation_harvest_does_not_disturb_existing_buffer_flush(
        self, canary_plugin_root, canary_cache_dir
    ):
        """Regression: when both a citation marker AND a skill-usage buffer
        file are present, the pre-existing buffer-flush systemMessage
        behaviour is unaffected by the new citation-harvest logic."""
        skill_cache = canary_cache_dir / ".claude" / "cache" / "skill-usage"
        skill_cache.mkdir(parents=True)
        today = __import__("datetime").date.today().strftime("%Y%m%d")
        buf = skill_cache / f"{today}-cite-005.txt"
        buf.write_text("swe-workbench:principle-clean-code\n")

        result = _run_flush_for_canary(
            {
                "agent_id": "cite-005",
                "agent_type": "reviewer",
                "last_assistant_message": (
                    "Body.\nSWB-CANARIES-APPLIED: swe-workbench:principle-clean-code"
                ),
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert "systemMessage" in out
        assert "Skills used by reviewer" in out["systemMessage"]
        assert "swe-workbench:principle-clean-code" in out["systemMessage"]
        assert not buf.exists(), "buffer should still be deleted after flush"

        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["cited_skills"] == ["swe-workbench:principle-clean-code"]

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
import sys
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "scripts" / "preload-probe.mjs"
FLUSH_SH = ROOT / "hooks" / "skill_usage_flush.sh"
TELEMETRY = ROOT / "scripts" / "preload-telemetry.py"


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


def _run_probe(args, env=None, **kwargs):
    node = shutil.which("node")
    assert node is not None
    return subprocess.run(
        [node, "--experimental-strip-types", str(PROBE), *args],
        capture_output=True,
        text=True,
        env=env if env is not None else _CLEAN_ENV,
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

    def test_stray_commas_do_not_leak_empty_string_entries(
        self, canary_plugin_root, canary_cache_dir
    ):
        """A malformed marker with a stray double-comma and trailing comma +
        whitespace must not produce empty-string entries in cited_skills."""
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-006",
                "agent_type": "reviewer",
                "last_assistant_message": (
                    "SWB-CANARIES-APPLIED: swe-workbench:principle-ddd,,"
                    "swe-workbench:principle-tdd,  "
                ),
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["cited_skills"] == [
            "swe-workbench:principle-ddd",
            "swe-workbench:principle-tdd",
        ]
        assert "" not in records[0]["cited_skills"]

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


# ---------------------------------------------------------------------------
# Task 6 (C2/C4 reporter) — Part A: preload-probe.mjs cache --dry-run must
# remain side-effect free even with the new live-path cache-runs.jsonl append
# added by this task. Part B: scripts/preload-telemetry.py's canary and cache
# subcommands.
# ---------------------------------------------------------------------------


@requires_node
def test_cache_dry_run_writes_no_cache_runs_file(tmp_path: Path, real_agent_id):
    """--dry-run must exit before any file I/O beyond argv construction — this is the one new
    behavioural assertion Task 6 needs for Part A (the live-append path itself cannot be
    exercised without a real `pi` dispatch, out of scope here as it was for Task 2)."""
    env = {**_CLEAN_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    result = _run_probe(["cache", "--agent", real_agent_id, "--dry-run"], env=env)
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert not (tmp_path / ".claude" / "cache" / "dispatch-probes").exists()
    assert not (tmp_path / ".claude" / "cache" / "dispatch-probes" / "cache-runs.jsonl").exists()


def _run_telemetry(args, project_dir=None):
    env = dict(_CLEAN_ENV)
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(TELEMETRY), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class TestPreloadTelemetryCanary:
    def _citations_file(self, project_dir: Path) -> Path:
        path = project_dir / ".claude" / "cache" / "skill-usage" / "canary-citations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def test_citation_rate_and_zero_citation_row(self, tmp_path: Path):
        """Hand-constructed scenario against the real 'reviewer' agent's real preloaded skills
        (agents/*.md discovery is fixed to this repo's own tree, not redirectable — only the
        citations JSONL data directory is redirected via CLAUDE_PROJECT_DIR).

        reviewer preloads (among others) swe-workbench:principle-code-review and
        swe-workbench:principle-clean-code. 4 synthetic dispatches: principle-code-review cited
        in 2 of them (hand calc: 2/4 = 50.0%), principle-clean-code cited in 0 of them (must
        still get its own 0/4 row, not be omitted).
        """
        lines = [
            {
                "agent_type": "reviewer",
                "cited_skills": [
                    "swe-workbench:principle-code-review",
                    "swe-workbench:principle-solid",
                ],
                "agent_id": "r1",
            },
            {
                "agent_type": "reviewer",
                "cited_skills": ["swe-workbench:principle-code-review"],
                "agent_id": "r2",
            },
            {"agent_type": "reviewer", "cited_skills": [], "agent_id": "r3"},
            {
                "agent_type": "reviewer",
                "cited_skills": ["swe-workbench:principle-solid"],
                "agent_id": "r4",
            },
        ]
        path = self._citations_file(tmp_path)
        path.write_text("\n".join(json.dumps(rec) for rec in lines) + "\n")

        result = _run_telemetry(["canary", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        out = result.stdout

        assert "reviewer" in out and "4 dispatch(es) recorded" in out
        assert "swe-workbench:principle-code-review: 2/4 (50.0%)" in out
        assert "swe-workbench:principle-clean-code: 0/4 (0.0%)" in out
        # The caveat must be present unconditionally, not just for low rates.
        assert "CAVEAT:" in out
        assert "SubagentStop" in out

    def test_missing_citations_file_exits_zero_with_message(self, tmp_path: Path):
        result = _run_telemetry(["canary", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "no citation data collected yet" in result.stdout
        # A skill with no data yet still gets its own distinct 0/0 row, not omitted.
        assert "swe-workbench:principle-code-review: 0/0" in result.stdout
        assert "CAVEAT:" in result.stdout

    def test_corrupted_line_is_skipped_not_fatal(self, tmp_path: Path):
        path = self._citations_file(tmp_path)
        good = {
            "agent_type": "reviewer",
            "cited_skills": ["swe-workbench:principle-code-review"],
            "agent_id": "r1",
        }
        path.write_text(json.dumps(good) + "\n" + "not valid json {\n")

        result = _run_telemetry(["canary", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "skipped 1 malformed line" in result.stdout
        # The rest of the file is still processed and reported.
        assert "swe-workbench:principle-code-review: 1/1 (100.0%)" in result.stdout


class TestPreloadTelemetryCache:
    def _cache_runs_file(self, project_dir: Path) -> Path:
        path = project_dir / ".claude" / "cache" / "dispatch-probes" / "cache-runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def test_pairing_and_cache_read_fraction_reporting(self, tmp_path: Path):
        run1 = {
            "agent": "reviewer",
            "run": 1,
            "usage": {
                "input": 1000,
                "output": 50,
                "cacheRead": 0,
                "cacheWrite": 900,
                "cost": {"input": 0.01, "output": 0.002, "cacheRead": 0.0, "cacheWrite": 0.015, "total": 0.027},
            },
            "cacheReadFraction": 0.0,
            "ts": "2026-01-01T00:00:00.000Z",
        }
        run2 = {
            "agent": "reviewer",
            "run": 2,
            "usage": {
                "input": 100,
                "output": 50,
                "cacheRead": 900,
                "cacheWrite": 0,
                "cost": {"input": 0.001, "output": 0.002, "cacheRead": 0.0009, "cacheWrite": 0.0, "total": 0.0039},
            },
            "cacheReadFraction": 0.9,
            "ts": "2026-01-01T00:00:05.000Z",
        }
        path = self._cache_runs_file(tmp_path)
        path.write_text(json.dumps(run1) + "\n" + json.dumps(run2) + "\n")

        result = _run_telemetry(["cache", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        out = result.stdout

        assert "agent: reviewer" in out
        assert "cacheRead=0" in out
        assert "cacheRead=900" in out
        assert "cacheReadFraction=0.0" in out
        assert "cacheReadFraction=0.9" in out
        assert "cache: YES — run 2 showed cache-read activity (cacheRead > 0)" in out

    def test_missing_cache_runs_file_exits_zero_pointing_at_probe_command(self, tmp_path: Path):
        result = _run_telemetry(["cache"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "no cache-probe run data collected yet" in result.stdout
        assert "preload-probe.mjs cache --agent" in result.stdout


def test_telemetry_no_subcommand_exits_nonzero_with_usage():
    result = _run_telemetry([])
    assert result.returncode != 0
    assert "canary" in result.stderr and "cache" in result.stderr


def test_telemetry_unknown_subcommand_exits_nonzero():
    result = _run_telemetry(["bogus"])
    assert result.returncode != 0
    assert "invalid choice" in result.stderr

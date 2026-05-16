"""Tests for hooks/skill_usage_record.sh and hooks/skill_usage_flush.sh.

Subprocess-driven so they exercise real POSIX sh logic.  Each test gets an
isolated cache dir via tmp_path + CLAUDE_PROJECT_DIR, and a minimal agents/
tree via CLAUDE_PLUGIN_ROOT.
"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
RECORD_SH = ROOT / "hooks" / "skill_usage_record.sh"
FLUSH_SH = ROOT / "hooks" / "skill_usage_flush.sh"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"

# Strip GIT_* vars so hook-context env doesn't leak into ephemeral test paths.
_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def plugin_root(tmp_path: Path) -> Path:
    """Minimal plugin dir with an agents/reviewer.md (no opt-out)."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "reviewer.md").write_text(
        "---\nname: reviewer\nmodel: sonnet\n---\nReviewer body.\n"
    )
    return tmp_path


@pytest.fixture()
def optout_plugin_root(tmp_path: Path) -> Path:
    """Minimal plugin dir with an agent that has skill_telemetry: false."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "reviewer.md").write_text(
        "---\nname: reviewer\nskill_telemetry: false\nmodel: sonnet\n---\nReviewer body.\n"
    )
    return tmp_path


@pytest.fixture()
def cache_dir(tmp_path: Path) -> Path:
    """Isolated cache directory; CLAUDE_PROJECT_DIR points here."""
    d = tmp_path / "project"
    d.mkdir()
    return d


def _env(plugin_root: Path, cache_dir: Path) -> dict:
    env = dict(_CLEAN_ENV)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    env["CLAUDE_PROJECT_DIR"] = str(cache_dir)
    return env


def _run_record(stdin_json: dict, plugin_root: Path, cache_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(RECORD_SH)],
        input=json.dumps(stdin_json),
        capture_output=True,
        text=True,
        env=_env(plugin_root, cache_dir),
    )


def _run_flush(stdin_json: dict, plugin_root: Path, cache_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(FLUSH_SH)],
        input=json.dumps(stdin_json),
        capture_output=True,
        text=True,
        env=_env(plugin_root, cache_dir),
    )


def _skill_cache(cache_dir: Path) -> Path:
    return cache_dir / ".claude" / "cache" / "skill-usage"


def _buffer_files(cache_dir: Path) -> list[Path]:
    d = _skill_cache(cache_dir)
    if not d.exists():
        return []
    return sorted(d.glob("*-*.txt"))


# ---------------------------------------------------------------------------
# record hook — tests 1–6
# ---------------------------------------------------------------------------


class TestRecordHook:
    def test_top_level_is_noop(self, plugin_root, cache_dir):
        """No agent_id in stdin → exit 0, no buffer written."""
        result = _run_record(
            {"tool_input": {"skill": "swe-workbench:principle-code-review"}},
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        assert _buffer_files(cache_dir) == []

    def test_subagent_writes_buffer(self, plugin_root, cache_dir):
        """Subagent invocation writes the skill name to a buffer file."""
        result = _run_record(
            {
                "agent_id": "abc-123",
                "agent_type": "reviewer",
                "tool_input": {"skill": "swe-workbench:principle-code-review"},
            },
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        buffers = _buffer_files(cache_dir)
        assert len(buffers) == 1
        assert buffers[0].name.endswith("-abc-123.txt")
        assert "swe-workbench:principle-code-review" in buffers[0].read_text()

    def test_unknown_agent_type_is_noop(self, plugin_root, cache_dir):
        """agent_type with no matching agent file → no buffer written."""
        result = _run_record(
            {
                "agent_id": "abc-123",
                "agent_type": "NotARealAgent",
                "tool_input": {"skill": "swe-workbench:principle-code-review"},
            },
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        assert _buffer_files(cache_dir) == []

    def test_opted_out_agent_is_noop(self, optout_plugin_root, cache_dir):
        """agent with skill_telemetry: false → no buffer written."""
        result = _run_record(
            {
                "agent_id": "abc-123",
                "agent_type": "reviewer",
                "tool_input": {"skill": "swe-workbench:principle-code-review"},
            },
            optout_plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        assert _buffer_files(cache_dir) == []

    def test_path_traversal_agent_type_is_noop(self, plugin_root, cache_dir):
        """agent_type with path-traversal chars must be rejected — no buffer, no file probe."""
        for malicious in ["../../etc/passwd", "../sensitive", "foo/bar", "foo bar"]:
            result = _run_record(
                {
                    "agent_id": "abc-123",
                    "agent_type": malicious,
                    "tool_input": {"skill": "swe-workbench:principle-code-review"},
                },
                plugin_root,
                cache_dir,
            )
            assert result.returncode == 0, f"Expected exit 0 for agent_type={malicious!r}"
            assert _buffer_files(cache_dir) == [], f"Expected no buffer for agent_type={malicious!r}"

    def test_path_traversal_agent_id_is_noop(self, plugin_root, cache_dir):
        """agent_id with path-traversal chars must be rejected — no buffer written."""
        for malicious in ["../../evil", "../sensitive", "foo/bar", "foo bar"]:
            result = _run_record(
                {
                    "agent_id": malicious,
                    "agent_type": "reviewer",
                    "tool_input": {"skill": "swe-workbench:principle-code-review"},
                },
                plugin_root,
                cache_dir,
            )
            assert result.returncode == 0, f"Expected exit 0 for agent_id={malicious!r}"
            assert _buffer_files(cache_dir) == [], f"Expected no buffer for agent_id={malicious!r}"

    def test_missing_skill_is_noop(self, plugin_root, cache_dir):
        """tool_input.skill absent → exit 0, no buffer."""
        result = _run_record(
            {
                "agent_id": "abc-123",
                "agent_type": "reviewer",
                "tool_input": {},
            },
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        assert _buffer_files(cache_dir) == []

    def test_sweep_removes_old_buffers(self, plugin_root, cache_dir):
        """Files older than 24h are swept on each hook invocation."""
        skill_cache = _skill_cache(cache_dir)
        skill_cache.mkdir(parents=True)
        old_file = skill_cache / "20240101-old-agent.txt"
        old_file.write_text("old-skill\n")
        # Set mtime to 48h ago
        old_mtime = time.time() - 48 * 3600
        os.utime(old_file, (old_mtime, old_mtime))

        _run_record(
            {
                "agent_id": "new-123",
                "agent_type": "reviewer",
                "tool_input": {"skill": "swe-workbench:principle-code-review"},
            },
            plugin_root,
            cache_dir,
        )
        assert not old_file.exists(), "Old buffer should have been swept"


# ---------------------------------------------------------------------------
# flush hook — tests 7–11
# ---------------------------------------------------------------------------


class TestFlushHook:
    def test_emits_formatted_system_message(self, plugin_root, cache_dir):
        """Buffer with three entries (one duplicate) → deduped, first-seen order."""
        skill_cache = _skill_cache(cache_dir)
        skill_cache.mkdir(parents=True)
        today = __import__("datetime").date.today().strftime("%Y%m%d")
        buf = skill_cache / f"{today}-flush-001.txt"
        buf.write_text("skill-a\nskill-b\nskill-a\nskill-c\n")

        result = _run_flush(
            {"agent_id": "flush-001", "agent_type": "reviewer"},
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert "systemMessage" in out
        msg = out["systemMessage"]
        assert msg.startswith("Skills used by reviewer:")
        assert "skill-a" in msg
        assert "skill-b" in msg
        assert "skill-c" in msg
        # Dedup: skill-a must appear exactly once
        assert msg.count("skill-a") == 1
        # Order: skill-a before skill-b before skill-c
        assert msg.index("skill-a") < msg.index("skill-b") < msg.index("skill-c")
        # suppressOutput present
        assert out.get("suppressOutput") is True

    def test_deletes_buffer_after_emit(self, plugin_root, cache_dir):
        """Buffer file is removed after successful flush."""
        skill_cache = _skill_cache(cache_dir)
        skill_cache.mkdir(parents=True)
        today = __import__("datetime").date.today().strftime("%Y%m%d")
        buf = skill_cache / f"{today}-flush-002.txt"
        buf.write_text("skill-a\n")

        _run_flush(
            {"agent_id": "flush-002", "agent_type": "reviewer"},
            plugin_root,
            cache_dir,
        )
        assert not buf.exists(), "Buffer should be deleted after flush"

    def test_missing_buffer_is_noop(self, plugin_root, cache_dir):
        """No buffer for agent_id → stdout is {}, exit 0."""
        result = _run_flush(
            {"agent_id": "no-such-agent", "agent_type": "reviewer"},
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {}

    def test_opted_out_agent_is_noop_even_with_buffer(self, optout_plugin_root, cache_dir):
        """Opted-out agent: flush emits {}, buffer left untouched."""
        skill_cache = _skill_cache(cache_dir)
        skill_cache.mkdir(parents=True)
        today = __import__("datetime").date.today().strftime("%Y%m%d")
        buf = skill_cache / f"{today}-flush-003.txt"
        buf.write_text("skill-a\n")

        result = _run_flush(
            {"agent_id": "flush-003", "agent_type": "reviewer"},
            optout_plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {}
        assert buf.exists(), "Buffer should remain when agent is opted out"

    def test_path_traversal_agent_type_is_noop(self, plugin_root, cache_dir):
        """Flush rejects agent_type values with path-traversal characters."""
        for malicious in ["../../etc/passwd", "../sensitive", "foo/bar"]:
            result = _run_flush(
                {"agent_id": "trav-001", "agent_type": malicious},
                plugin_root,
                cache_dir,
            )
            assert result.returncode == 0, f"Expected exit 0 for agent_type={malicious!r}"
            assert json.loads(result.stdout) == {}, f"Expected {{}} for agent_type={malicious!r}"

    def test_midnight_straddle(self, plugin_root, cache_dir):
        """Buffers from both today and yesterday contribute to the flush line."""
        import datetime

        skill_cache = _skill_cache(cache_dir)
        skill_cache.mkdir(parents=True)
        today = datetime.date.today().strftime("%Y%m%d")
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y%m%d")
        buf_today = skill_cache / f"{today}-straddle-99.txt"
        buf_yesterday = skill_cache / f"{yesterday}-straddle-99.txt"
        buf_today.write_text("skill-today\n")
        buf_yesterday.write_text("skill-yesterday\n")

        result = _run_flush(
            {"agent_id": "straddle-99", "agent_type": "reviewer"},
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        msg = out.get("systemMessage", "")
        assert "skill-today" in msg
        assert "skill-yesterday" in msg
        # Both buffers cleaned up
        assert not buf_today.exists()
        assert not buf_yesterday.exists()


# ---------------------------------------------------------------------------
# hooks.json schema — tests 12–13
# ---------------------------------------------------------------------------


class TestHooksJson:
    def test_schema_valid(self):
        """validate.py must exit 0 with the updated hooks.json."""
        result = subprocess.run(
            ["python", str(ROOT / "scripts" / "validate.py")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_rm_rf_blocker_still_present(self):
        """Regression: the Bash guard command must still block rm -rf /."""
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        bash_hooks = [
            entry
            for entry in data["hooks"]["PreToolUse"]
            if entry.get("matcher") == "Bash"
        ]
        assert bash_hooks, "Bash PreToolUse entry missing"
        cmd = bash_hooks[0]["hooks"][0]["command"]
        # The guard pattern for destructive rm must be present verbatim
        assert "rm" in cmd and "exit 2" in cmd


# ---------------------------------------------------------------------------
# Integration — record → flush pipeline (end-to-end acceptance criterion)
# ---------------------------------------------------------------------------


class TestRecordFlushIntegration:
    def test_record_then_flush_emits_skill_line(self, plugin_root, cache_dir):
        """Sequential record→flush with matching agent_id produces the telemetry line."""
        _run_record(
            {
                "agent_id": "integ-001",
                "agent_type": "reviewer",
                "tool_input": {"skill": "swe-workbench:principle-code-review"},
            },
            plugin_root,
            cache_dir,
        )
        # Buffer should exist after record
        assert len(_buffer_files(cache_dir)) == 1

        result = _run_flush(
            {"agent_id": "integ-001", "agent_type": "reviewer"},
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert "systemMessage" in out
        assert "Skills used by reviewer" in out["systemMessage"]
        assert "swe-workbench:principle-code-review" in out["systemMessage"]
        # Buffer cleaned up
        assert _buffer_files(cache_dir) == []

    def test_record_multiple_skills_then_flush_dedupes(self, plugin_root, cache_dir):
        """Multiple record calls with a duplicate produce a single deduped line."""
        for skill in [
            "swe-workbench:principle-tdd",
            "swe-workbench:principle-clean-code",
            "swe-workbench:principle-tdd",  # duplicate
        ]:
            _run_record(
                {
                    "agent_id": "integ-002",
                    "agent_type": "reviewer",
                    "tool_input": {"skill": skill},
                },
                plugin_root,
                cache_dir,
            )

        result = _run_flush(
            {"agent_id": "integ-002", "agent_type": "reviewer"},
            plugin_root,
            cache_dir,
        )
        assert result.returncode == 0
        msg = json.loads(result.stdout)["systemMessage"]
        # Dedup: tdd appears exactly once
        assert msg.count("principle-tdd") == 1
        # First-seen order preserved
        assert msg.index("principle-tdd") < msg.index("principle-clean-code")

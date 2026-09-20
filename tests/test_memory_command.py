"""Prose-pinning tests for the /swe-workbench:memory command."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
MEMORY_MD = ROOT / "commands" / "memory.md"


def _text() -> str:
    return MEMORY_MD.read_text(encoding="utf-8")


def test_command_carries_runtime_preflight():
    text = _text()
    assert "command -v swe-workbench-memory" in text, (
        "commands/memory.md must preflight the runtime once before invoking it"
    )
    assert "reinstall or update the swe-workbench plugin" in text


def test_command_detects_harness_via_session_env_not_path():
    text = _text()
    assert "PI_SESSION_ID" in text, (
        "harness detection must use the session env var, not a PATH probe"
    )
    assert "record --as" in text and '"$HARNESS"' in text


def test_command_records_through_envelope_checker():
    text = _text()
    assert "swe-workbench-memory record" in text
    assert "swe-workbench-result-check swb.memory/1" in text, (
        "the record result must be validated through the envelope checker, never eval'd"
    )
    assert "eval" not in text.replace("never eval'd", "")


def test_command_routes_body_through_temp_file_not_shell_variable():
    text = _text()
    assert "--body-file" in text, "free-text body must reach the runtime via a file"
    assert "mktemp" in text
    assert "Write tool" in text, (
        "body is written with the Write tool, never echoed into a variable"
    )


def test_command_never_writes_the_other_store():
    text = _text()
    assert "--store" not in text or "never write" in text.lower()
    assert "read-only" in text


def test_command_mentions_fail_closed_caps():
    text = _text()
    assert "12 000 bytes" in text or "12000" in text, (
        "the body cap must be stated so the caller shortens before refusing"
    )
    assert "retry" in text.lower()

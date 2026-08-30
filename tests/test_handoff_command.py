"""Content assertions for the shared handoff command (commands/handoff.md)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
COMMAND = ROOT / "commands" / "handoff.md"


def _text() -> str:
    assert COMMAND.is_file(), "commands/handoff.md must exist"
    return COMMAND.read_text(encoding="utf-8")


def test_frontmatter_carries_a_description():
    text = _text()
    assert text.startswith("---\n")
    frontmatter = text.split("\n---\n", 1)[0]
    assert "description:" in frontmatter


def test_preflights_the_runtime_command_once():
    text = _text()
    assert "command -v swe-workbench-handoff >/dev/null 2>&1" in text


def test_validates_every_runtime_envelope_through_result_check():
    text = _text()
    assert text.count("swe-workbench-result-check swb.handoff/1") >= 3


def test_semantic_payload_reaches_create_via_redirected_temp_file():
    text = _text()
    assert "mktemp" in text
    assert 'swe-workbench-handoff create < "$HANDOFF_INPUT"' in text
    assert 'rm -f "$HANDOFF_INPUT"' in text
    # The semantic JSON must never round-trip through a shell variable or echo.
    assert "echo \"$SEMANTIC" not in text
    assert "printf '%s' \"$SEMANTIC" not in text


def test_planned_handoff_prints_the_stop_invariant_and_exact_resume_commands():
    text = _text()
    assert "STOP:" in text
    assert "/handoff resume" in text
    assert "/swe-workbench:handoff resume" in text


def test_resume_binds_a_receiver_session_from_the_harness_environment():
    text = _text()
    assert "--receiver-session" in text
    assert "${PI_SESSION_ID:?" in text
    assert "${CLAUDE_CODE_SESSION_ID:?" in text
    assert "CLAUDE_SESSION_ID" not in text


def test_verification_example_matches_the_bounded_runtime_schema():
    text = _text()
    for field in ('"command"', '"label"', '"exit_status"', '"timestamp"', '"result"'):
        assert field in text


def test_command_does_not_advertise_a_nonexistent_status_subcommand():
    text = _text()
    assert "swe-workbench-handoff status" not in text
    assert "- `status`" not in text


def test_recovery_route_gates_on_source_stopped_and_acknowledgement():
    text = _text()
    assert "--source-stopped" in text
    assert "--acknowledge-degraded" in text
    assert "recover" in text


def test_lifecycle_routes_use_guard_allowlisted_single_pipelines():
    text = _text()
    assert 'swe-workbench-handoff resume "<checkpoint-id>"' in text
    assert 'swe-workbench-handoff recover --from "<source-harness>" --source-stopped' in text
    assert 'swe-workbench-handoff close "<checkpoint-id>"' in text


def test_close_authenticates_the_current_harness_and_session():
    text = _text()
    close_section = text.split("## Close", 1)[1]
    assert "--as" in close_section
    assert "--session-ref" in close_section
    assert "CLAUDE_CODE_SESSION_ID" in close_section
    assert "PI_SESSION_ID" in close_section


def test_command_never_imports_native_transcripts():
    text = _text()
    assert "/export" not in text
    assert "--input-file" not in text

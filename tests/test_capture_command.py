"""Tests for /swe-workbench:capture command (issue #428 state-file cleanup)."""

import re
from pathlib import Path

import validate

ROOT = Path(__file__).parent.parent
CAPTURE_MD = ROOT / "commands" / "capture.md"


def test_capture_has_required_frontmatter():
    """commands/capture.md must have description: and argument-hint: frontmatter."""
    text = CAPTURE_MD.read_text()
    fm = validate.parse_frontmatter(CAPTURE_MD, text=text)
    assert fm is not None, "commands/capture.md must have valid frontmatter"
    assert "description" in fm, (
        "commands/capture.md must include a 'description:' frontmatter field"
    )
    assert "argument-hint" in fm, (
        "commands/capture.md must include an 'argument-hint:' frontmatter field"
    )


def test_capture_step9_deletes_temp_files():
    """commands/capture.md step 9 must invoke swe-workbench-clean-state-files on success."""
    text = CAPTURE_MD.read_text()
    assert "swe-workbench-clean-state-files" in text, (
        "commands/capture.md step 9 must call swe-workbench-clean-state-files "
        "to delete the temp .md and .cmd files after successful issue creation"
    )
    assert "/tmp/capture-" in text, (
        "commands/capture.md must reference the /tmp/capture-<repo-slug>-<ts>* "
        "file pattern in the swe-workbench-clean-state-files call"
    )


def test_capture_step9_cleanup_on_success_only():
    """commands/capture.md must specify that temp files are left on failure (for retry)."""
    text = CAPTURE_MD.read_text()
    assert "failure" in text.lower() or "retry" in text.lower(), (
        "commands/capture.md must state that temp files are left intact on failure (for retry)"
    )


def test_capture_delegates_to_product_manager():
    """commands/capture.md must delegate to the product-manager subagent."""
    text = CAPTURE_MD.read_text()
    assert "product-manager" in text, (
        "commands/capture.md must reference the product-manager subagent"
    )


# --- Public-repo redaction assertions ---

def _joined(text):
    """Fold shell line continuations so a multi-line command can be matched as one."""
    return re.sub(r"\\\n\s*", " ", text)


def _step(text, number, next_number):
    start = text.find(f"{number}. **")
    end = text.find(f"{next_number}. **", start)
    assert start != -1 and end != -1, f"commands/capture.md must keep steps {number} and {next_number}"
    return text[start:end]


def test_capture_step1_reads_repo_visibility():
    step1 = _step(CAPTURE_MD.read_text(), 1, 2)
    assert "gh repo view --json nameWithOwner,visibility" in step1, (
        "step 1 must read the repository visibility alongside its name"
    )
    assert "PRIVATE" in step1 and "INTERNAL" in step1, (
        "only an affirmatively PRIVATE or INTERNAL repository skips the redactor"
    )
    assert "unknown" in step1.lower(), (
        "an unknown or failed visibility lookup must redact, not skip"
    )


def test_capture_runs_the_redactor_for_non_private_repos():
    text = CAPTURE_MD.read_text()
    step6 = _joined(_step(text, 6, 7))
    assert "command -v swe-workbench-redact" in step6
    assert "swe-workbench-redact --target-repo <nameWithOwner>" in step6
    assert "| swe-workbench-result-check swb.redact/1" in step6
    assert "--field title " in step6 and "--field body " in step6
    for suffix in (".title.draft", ".draft.md"):
        assert suffix in step6, f"step 6 must write the {suffix} draft for the redactor"


def test_capture_redactor_bash_uses_placeholder_paths():
    """Literal /tmp paths in a bash block trip the unenumerated-tmp-write gate."""
    blocks = re.findall(r"```bash\n(.*?)```", CAPTURE_MD.read_text(), re.DOTALL)
    redact_blocks = [b for b in blocks if "swe-workbench-redact" in b]
    assert redact_blocks, "the redactor invocation must sit in a bash block"
    assert all("/tmp/" not in b for b in redact_blocks)


def test_capture_duplicate_scan_follows_redaction():
    text = CAPTURE_MD.read_text()
    redaction_pos = text.find("**Redaction pass")
    scan_pos = text.find("**Duplicate scan.**")
    assert redaction_pos != -1 and scan_pos != -1
    assert redaction_pos < scan_pos, (
        "on a public repo the scan keywords leave the machine, so the redactor runs first"
    )
    scan = text[scan_pos:text.find("**Preview gate.**", scan_pos)]
    assert "sanitized title" in scan


def test_capture_preview_reports_redaction_or_the_private_skip():
    step8 = _step(CAPTURE_MD.read_text(), 8, 9)
    assert "Redacted: <data.summary" in step8
    assert "skipped — private repository" in step8
    reply_pos = step8.find("Reply 'confirm'")
    assert step8.find("Redacted:") < reply_pos, "the Redacted: line sits above the confirm gate"


def test_capture_cmd_sidecar_reads_the_title_from_its_file():
    step8 = _step(CAPTURE_MD.read_text(), 8, 9)
    assert '--title "$(cat ' in step8
    assert '--title "..."' not in step8 and '--title "<title>"' not in step8


def test_capture_edits_rerun_the_redactor_and_need_a_fresh_confirm():
    text = CAPTURE_MD.read_text()
    assert "fresh `confirm`" in text
    assert "re-runs the redactor" in text
    assert "credentials can never be restored" in text.lower()
    assert "--allow" in text


def test_capture_step9_reaps_the_draft_and_title_files():
    step9 = CAPTURE_MD.read_text()[CAPTURE_MD.read_text().find("9. **File on confirm.**"):]
    for suffix in (".draft.md", ".title.draft", ".title", ".cmd"):
        assert suffix in step9, f"step 9 must reap the {suffix} file"

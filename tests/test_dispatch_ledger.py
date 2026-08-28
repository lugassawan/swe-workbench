"""Tests for scripts/dispatch-ledger.mjs (issue #681, Task 3 / C1).

Node-version gating mirrors tests/test_pi_extension.py's `_node_major_version` / `_NODE_TOO_OLD` /
`requires_node` pattern (duplicated here rather than imported — this repo already duplicates this
small helper across more than one test file, e.g. tests/test_preload_instruments.py).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "dispatch-ledger.mjs"
LEDGER = ROOT / "docs" / "dispatch-ledger.md"


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
    reason="dispatch-ledger.mjs behavioural tests require Node >= 22 (--experimental-strip-types)",
)


def _run_ledger(args, **kwargs):
    node = shutil.which("node")
    assert node is not None
    return subprocess.run(
        [node, "--experimental-strip-types", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=30,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Reuse assertion (source scan) — always-on, no Node required.
# ---------------------------------------------------------------------------


def test_script_reuses_composesystemprompt_rather_than_reimplementing():
    """Guards against a future edit silently reimplementing prompt assembly instead of calling
    agent-spec.ts's real composeSystemPrompt — the whole point of this ledger is that it cannot
    drift from what a real dispatch actually sends, because it calls the same function."""
    text = SCRIPT.read_text(encoding="utf-8")

    assert "agent-spec.ts" in text, "expected the script to reference agent-spec.ts by name"
    assert re.search(r"\{\s*[^}]*\bcomposeSystemPrompt\b[^}]*\}\s*=\s*agentSpecModule", text), (
        "expected dispatch-ledger.mjs to destructure composeSystemPrompt from the dynamically "
        "imported agent-spec.ts module"
    )
    assert "function composeSystemPrompt" not in text, (
        "dispatch-ledger.mjs must not define its own composeSystemPrompt — reuse agent-spec.ts's "
        "real implementation instead"
    )


# ---------------------------------------------------------------------------
# Behavioural equality against a synthetic agent tree.
# ---------------------------------------------------------------------------

ALPHA_BODY = "Alpha body line one.\nAlpha body line two."
BETA_BODY = "Beta body only, no skills."
WIDGET_BODY = "Widget skill body content.\nMore widget details here."

ALPHA_MD = f"""---
name: alpha
description: Alpha test agent
model: sonnet
effort: low
tools: Read
skills:
  - swe-workbench:widget
---
{ALPHA_BODY}
"""

BETA_MD = f"""---
name: beta
description: Beta test agent, no skills
model: haiku
effort: low
tools: Read
---
{BETA_BODY}
"""

WIDGET_SKILL_MD = f"""---
name: widget
description: Widget skill for testing
---
{WIDGET_BODY}
"""


def _build_synthetic_root(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "alpha.md").write_text(ALPHA_MD, encoding="utf-8")
    (tmp_path / "agents" / "beta.md").write_text(BETA_MD, encoding="utf-8")
    (tmp_path / "skills" / "widget").mkdir(parents=True)
    (tmp_path / "skills" / "widget" / "SKILL.md").write_text(WIDGET_SKILL_MD, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    return tmp_path


_ROW_RE_TEMPLATE = (
    r"^\|\s*{agent}\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|$"
)


def _parse_agent_row(content, agent_id):
    """Parses the "Per-agent totals" table row for `agent_id` into
    (agent_body_chars, preload_chars, preload_share_pct, skill_count, body_tokens, preload_tokens).
    """
    pattern = re.compile(_ROW_RE_TEMPLATE.format(agent=re.escape(agent_id)), re.MULTILINE)
    match = pattern.search(content)
    assert match, f"no per-agent table row found for {agent_id!r} in:\n{content}"
    body_chars, preload_chars, share_pct, skill_count, body_tokens, preload_tokens = match.groups()
    return {
        "agent_body_chars": int(body_chars),
        "preload_chars": int(preload_chars),
        "preload_share_pct": float(share_pct),
        "skill_count": int(skill_count),
        "agent_body_tokens": int(body_tokens),
        "preload_tokens": int(preload_tokens),
    }


def _expected_preload_chars(agent_body, skills, root):
    """Hand-computed expected preload-chars value, independently reproducing
    composeSystemPrompt's documented format (pi/extensions/agent-spec.ts) rather than calling it —
    this is what would catch a subtle off-by-one in dispatch-ledger.mjs's own
    `composed.length - agentBodyChars` arithmetic, which the source-scan reuse test above cannot
    catch."""
    sections = [agent_body.strip()]
    for skill_id, skill_body, skill_dir in skills:
        sections.append(
            f"## Preloaded skill: {skill_id}\n"
            f"(relative paths this skill's body mentions, e.g. `examples/...`, resolve against: {skill_dir})\n\n"
            f"{skill_body.strip()}"
        )
    composed = "\n\n---\n\n".join(sections)
    normalized_composed = composed.replace(str(root), "<PLUGIN_ROOT>")
    normalized_body = agent_body.strip().replace(str(root), "<PLUGIN_ROOT>")
    return len(normalized_composed) - len(normalized_body)


@requires_node
def test_synthetic_tree_preload_chars_match_hand_computed_value(tmp_path):
    root = _build_synthetic_root(tmp_path)

    result = _run_ledger(["--write", "--root", str(root)])
    assert result.returncode == 0, f"--write failed: {result.stderr}"

    content = (root / "docs" / "dispatch-ledger.md").read_text(encoding="utf-8")

    widget_dir = str(root / "skills" / "widget")
    alpha_row = _parse_agent_row(content, "alpha")
    expected_alpha_preload = _expected_preload_chars(
        ALPHA_BODY, [("swe-workbench:widget", WIDGET_BODY, widget_dir)], root
    )
    assert alpha_row["preload_chars"] == expected_alpha_preload
    assert alpha_row["agent_body_chars"] == len(ALPHA_BODY.strip())
    assert alpha_row["skill_count"] == 1

    beta_row = _parse_agent_row(content, "beta")
    expected_beta_preload = _expected_preload_chars(BETA_BODY, [], root)
    assert expected_beta_preload == 0, "sanity check: an agent with no skills has zero preload chars"
    assert beta_row["preload_chars"] == 0
    assert beta_row["agent_body_chars"] == len(BETA_BODY.strip())
    assert beta_row["skill_count"] == 0
    assert beta_row["preload_share_pct"] == 0.0

    # Per-(agent, skill) breakdown row for alpha/widget.
    skill_row_re = re.compile(
        r"^\|\s*alpha\s*\|\s*swe-workbench:widget\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|$", re.MULTILINE
    )
    skill_match = skill_row_re.search(content)
    assert skill_match, f"no per-(agent, skill) row found for alpha/widget in:\n{content}"
    assert int(skill_match.group(1)) == len(WIDGET_BODY.strip())


# ---------------------------------------------------------------------------
# Root normalization — asserted against the REAL repo (its real skill `dir` values are what
# actually need normalizing; a synthetic fixture's short tmp_path is a weaker guarantee).
# ---------------------------------------------------------------------------


@requires_node
def test_real_repo_output_has_no_leaked_absolute_root_path():
    result = _run_ledger(["--write"])
    assert result.returncode == 0, f"--write failed: {result.stderr}"

    content = LEDGER.read_text(encoding="utf-8")
    assert "<PLUGIN_ROOT>" in content, "expected the <PLUGIN_ROOT> placeholder to appear in the ledger"
    assert str(ROOT) not in content, (
        "the real absolute repo root path leaked into docs/dispatch-ledger.md — this makes the "
        "ledger non-reproducible across machines"
    )


# ---------------------------------------------------------------------------
# --check / --write idempotency against the real repo.
# ---------------------------------------------------------------------------


@requires_node
def test_check_write_are_idempotent_against_real_repo():
    write_result = _run_ledger(["--write"])
    assert write_result.returncode == 0, f"--write failed: {write_result.stderr}"

    check_result = _run_ledger(["--check"])
    assert check_result.returncode == 0, f"--check should pass clean right after --write: {check_result.stderr}"

    second_write_result = _run_ledger(["--write"])
    assert second_write_result.returncode == 0
    assert "nothing needed changing" in second_write_result.stdout.lower(), (
        f"expected a second --write to be a no-op, got: {second_write_result.stdout!r}"
    )

    # Leave the working tree clean either way.
    _run_ledger(["--write"])


# ---------------------------------------------------------------------------
# --check failure mode against a corrupted real ledger.
# ---------------------------------------------------------------------------


@requires_node
def test_check_fails_on_corrupted_ledger_and_mentions_write():
    # Ensure a clean, in-sync starting point.
    setup = _run_ledger(["--write"])
    assert setup.returncode == 0, f"--write failed: {setup.stderr}"
    original = LEDGER.read_text(encoding="utf-8")

    try:
        LEDGER.write_text(original + "\nstray corrupting line\n", encoding="utf-8")

        check_result = _run_ledger(["--check"])
        assert check_result.returncode == 1, "expected --check to fail on a corrupted ledger"
        assert "--write" in check_result.stderr, (
            f"expected the --check failure message to point at --write, got: {check_result.stderr!r}"
        )
    finally:
        # Restore the working tree to a clean, in-sync state regardless of assertion outcome.
        restore = _run_ledger(["--write"])
        assert restore.returncode == 0, f"failed to restore docs/dispatch-ledger.md: {restore.stderr}"
        assert LEDGER.read_text(encoding="utf-8") == original

"""Regression test for the drift-detection bash embedded in
.github/workflows/dependabot-peer-sync.yml's "Check for peerDependencies drift" step.

Reproduces the exact bug a PR review caught: pi-coding-agent and pi-tui bump as two
SEPARATE dependabot PRs, so the first PR of every such pair leaves the two packages'
devDependencies pins out of lockstep — scripts/sync-peer-deps.sh --check correctly treats
that as a hard error (exit 2), not actionable drift (exit 1), but the original workflow
bash only checked "did --check exit 0", so it treated exit 2 the same as exit 1 and went
on to run the apply step, which hits the identical guard and fails the whole job. This
test extracts the step's actual bash from the YAML (so it fails loudly if that bash drifts
from what's tested here) and drives it against a stub sync-peer-deps.sh for each exit code.
"""
import re
import subprocess
from pathlib import Path

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "dependabot-peer-sync.yml"


def _extract_drift_check_bash() -> str:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"name: Check for peerDependencies drift\n\s*id: check\n\s*run: \|\n(.*?)\n\n",
        text,
        re.DOTALL,
    )
    assert m, "could not locate the 'Check for peerDependencies drift' step's run block"
    # De-indent: the YAML block is indented 10 spaces under `run: |`.
    lines = m.group(1).splitlines()
    return "\n".join(line[10:] if line.startswith(" " * 10) else line for line in lines)


_DRIFT_CHECK_BASH = _extract_drift_check_bash()


def _run_drift_check(tmp_path: Path, stub_exit_code: int) -> tuple[str, str]:
    """Run the extracted bash against a stub sync-peer-deps.sh that exits stub_exit_code.

    Returns (github_output_content, stdout) — GitHub Actions workflow-command annotations
    like ::warning:: are written to stdout, not stderr.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    stub = scripts_dir / "sync-peer-deps.sh"
    stub.write_text(f"#!/usr/bin/env bash\nexit {stub_exit_code}\n")
    stub.chmod(0o755)

    github_output = tmp_path / "github_output"
    github_output.write_text("")

    script = f"set -euo pipefail\n{_DRIFT_CHECK_BASH}\n"
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**_CLEAN_ENV, "GITHUB_OUTPUT": str(github_output)},
    )
    assert result.returncode == 0, (
        f"drift-check bash itself must not fail (stub exit {stub_exit_code}): "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return github_output.read_text(), result.stdout


class TestDriftCheckExitCodeHandling:
    def test_exit_0_sets_drift_false(self, tmp_path):
        output, _ = _run_drift_check(tmp_path, 0)
        assert "drift=false" in output

    def test_exit_1_sets_drift_true(self, tmp_path):
        """Exit 1 is scripts/sync-peer-deps.sh's actionable-drift code — the apply step
        should run next."""
        output, _ = _run_drift_check(tmp_path, 1)
        assert "drift=true" in output

    def test_exit_2_sets_drift_false_not_true(self, tmp_path):
        """The regression this test locks in: exit 2 (hard error, e.g. the two packages'
        devDependencies pins are out of lockstep) must NOT be treated as actionable drift —
        it must be a clean no-op, not an attempt to run the apply step (which would hit the
        identical guard and fail the job)."""
        output, stdout = _run_drift_check(tmp_path, 2)
        assert "drift=false" in output
        assert "drift=true" not in output
        assert "::warning::" in stdout

    def test_unexpected_exit_code_also_falls_back_to_no_op(self, tmp_path):
        """Any exit code other than 0/1 is treated as a hard error, not just 2 specifically —
        a defensive default in case the script's contract changes underneath this workflow."""
        output, stdout = _run_drift_check(tmp_path, 7)
        assert "drift=false" in output
        assert "::warning::" in stdout

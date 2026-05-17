"""
Regression tests for the GH_REPO export in scripts/release.sh.

Guards against "No default remote repository has been set" failures
on multi-remote clones (e.g. after `gh repo fork` adds sibling remotes).
"""
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

RELEASE_SH = Path(__file__).parent.parent / "scripts" / "release.sh"


def _script_lines() -> list[str]:
    return RELEASE_SH.read_text().splitlines()


def _is_shell_comment(line: str) -> bool:
    """Return True if the line is a shell comment (non-code)."""
    return line.lstrip().startswith("#")


def _gh_call_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Return (1-based index, text) for non-comment gh pr/repo call lines."""
    return [
        (i + 1, ln)
        for i, ln in enumerate(lines)
        if re.search(r"\bgh (pr|repo) ", ln)
        and not _is_shell_comment(ln)
        and "--repo" not in ln
    ]


class TestExportOrdering:
    """Static: export GH_REPO must precede the first gh pr / gh repo call."""

    def test_export_precedes_first_gh_pr_or_repo_call(self):
        lines = _script_lines()
        export_idx = next(
            (i for i, ln in enumerate(lines) if "export GH_REPO" in ln),
            None,
        )
        assert export_idx is not None, "export GH_REPO not found in release.sh"

        gh_calls = _gh_call_lines(lines)
        assert gh_calls, "No non-comment 'gh pr' or 'gh repo' call found in release.sh"

        first_gh_lineno, _ = gh_calls[0]
        export_lineno = export_idx + 1
        assert export_lineno < first_gh_lineno, (
            f"export GH_REPO (line {export_lineno}) must come before "
            f"first 'gh pr/repo' call (line {first_gh_lineno})"
        )


class TestNoOrphanCalls:
    """Static: every gh pr/repo call is either after the export or has --repo."""

    def test_no_gh_calls_before_export_without_repo_flag(self):
        lines = _script_lines()
        export_idx = next(
            (i for i, ln in enumerate(lines) if "export GH_REPO" in ln),
            None,
        )
        assert export_idx is not None, "export GH_REPO not found in release.sh"

        export_lineno = export_idx + 1
        orphans = [
            (lineno, ln.strip())
            for lineno, ln in _gh_call_lines(lines)
            if lineno < export_lineno
        ]

        assert orphans == [], (
            "Found gh pr/repo calls before export GH_REPO without --repo flag:\n"
            + "\n".join(f"  line {n}: {text}" for n, text in orphans)
        )


class TestExtractionRoundTrip:
    """Dynamic: the sed pipeline produces owner/repo for all origin URL forms."""

    # Extraction snippet lifted verbatim from release.sh
    _SNIPPET = textwrap.dedent("""\
        ORIGIN_URL=$(git remote get-url origin 2>/dev/null || true)
        GH_REPO=$(printf '%s\\n' "$ORIGIN_URL" \\
          | sed -E 's#^git@github\\.com:#https://github.com/#' \\
          | sed -E 's#^https://github\\.com/##; s#\\.git$##')
        printf '%s\\n' "$GH_REPO"
    """)

    def _run(self, fake_url: str) -> str:
        """Stub `git` on PATH to return fake_url, then run the extraction snippet."""
        stub_dir = Path(tempfile.mkdtemp(prefix="gh_repo_stub_"))
        try:
            stub = stub_dir / "git"
            stub.write_text(
                f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(fake_url)}\n"
            )
            stub.chmod(0o755)
            env = {**os.environ, "PATH": f"{stub_dir}:{os.environ['PATH']}"}
            result = subprocess.run(
                ["bash", "-c", self._SNIPPET],
                capture_output=True,
                text=True,
                env=env,
            )
            assert result.returncode == 0, f"snippet failed: {result.stderr}"
            return result.stdout.strip()
        finally:
            shutil.rmtree(stub_dir, ignore_errors=True)

    def test_ssh_url_with_git_suffix(self):
        assert self._run("git@github.com:lugassawan/swe-workbench.git") == "lugassawan/swe-workbench"

    def test_https_url_with_git_suffix(self):
        assert self._run("https://github.com/lugassawan/swe-workbench.git") == "lugassawan/swe-workbench"

    def test_ssh_url_without_git_suffix(self):
        assert self._run("git@github.com:lugassawan/swe-workbench") == "lugassawan/swe-workbench"

    def test_https_url_without_git_suffix(self):
        assert self._run("https://github.com/lugassawan/swe-workbench") == "lugassawan/swe-workbench"

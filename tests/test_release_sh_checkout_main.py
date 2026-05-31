"""
Regression tests for guarded git checkout main in scripts/release.sh.

Guards against bare `git checkout main` failing in rimba multi-worktree layouts
with 'fatal: main is already used by worktree at ...'.

Both the resume arm (~line 52) and the post-merge sync (~line 310) must be
wrapped in: if ! git checkout main; then ... exit 1; fi
"""
from pathlib import Path

RELEASE_SH = Path(__file__).parent.parent / "scripts" / "release.sh"


def _script_lines() -> list[str]:
    return RELEASE_SH.read_text().splitlines()


def _is_shell_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _bare_checkout_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Return (1-based lineno, text) for standalone bare `git checkout main` lines."""
    return [
        (i + 1, ln)
        for i, ln in enumerate(lines)
        if ln.strip() == "git checkout main"
        and not _is_shell_comment(ln)
    ]


def _guard_indices(lines: list[str]) -> list[int]:
    """Return 0-based indices of `if ! git checkout main; then` lines."""
    return [
        i
        for i, ln in enumerate(lines)
        if "if ! git checkout main; then" in ln
        and not _is_shell_comment(ln)
    ]


class TestCheckoutMainGuarded:
    """Static: every git checkout main must be wrapped in an if ! guard."""

    def test_no_bare_git_checkout_main(self):
        lines = _script_lines()
        bare = _bare_checkout_lines(lines)
        assert bare == [], (
            "Found bare 'git checkout main' (unguarded) in release.sh:\n"
            + "\n".join(f"  line {n}: {text.strip()}" for n, text in bare)
            + "\nWrap each in:\n"
            + "  if ! git checkout main; then\n"
            + '    echo "Error: could not switch to main (checked out in another worktree?)." >&2\n'
            + "    exit 1\n"
            + "  fi"
        )

    def test_at_least_two_guards_present(self):
        """Both the resume arm and the post-merge sync must be guarded."""
        lines = _script_lines()
        guards = _guard_indices(lines)
        assert len(guards) >= 2, (
            f"Expected at least 2 guarded 'if ! git checkout main; then' blocks, "
            f"found {len(guards)}"
        )

    def test_each_guard_has_error_echo_and_exit(self):
        """Every guard block must emit 'Error: could not switch to main' to stderr and exit 1."""
        lines = _script_lines()
        guards = _guard_indices(lines)
        assert guards, "No 'if ! git checkout main; then' guards found — expected at least 2"

        for idx in guards:
            lineno = idx + 1
            # Inspect up to 5 lines after the guard opener
            block = lines[idx : idx + 5]
            has_error = any("Error: could not switch to main" in ln for ln in block)
            has_exit = any(ln.strip() == "exit 1" for ln in block)
            assert has_error, (
                f"Guard at line {lineno} is missing the 'Error: could not switch to main' "
                f"echo within the next 5 lines"
            )
            assert has_exit, (
                f"Guard at line {lineno} is missing 'exit 1' within the next 5 lines"
            )

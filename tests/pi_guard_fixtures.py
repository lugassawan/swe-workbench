"""Shared fixture set for hooks/bash_guard.sh's differential acceptance criterion:

  For this fixture set (including the backtick/$(...) vectors bash_guard.sh now closes),
  the verdict produced through the Pi adapter must be identical to the verdict produced by
  invoking the guard script directly with the equivalent Claude-Code-shaped payload.

A single source shared by tests/test_hooks.py (direct invocation) and
tests/test_pi_extension.py (through pi/extensions/guards.ts) — a future change to
hooks/bash_guard.sh's semantics has to update the expectation here, and both suites re-verify
against it, or CI fails on whichever one goes stale.

Each entry is a GuardCase. expected="block" means exit 2 + "BLOCKED" in stderr directly, or
{block: true} through the Pi adapter; expected="allow" means exit 0 with empty stdout (a
plain allow is SILENT); expected="warn" means exit 0 with one line of stdout JSON whose
permissionDecisionReason equals expected_reason — asserted on BOTH paths, so the
differential criterion covers verdict and message parity. scene=True rows stage the
two-repo attribution scene via stage_guard_scene() and format {protected}/{feature}
placeholders at runtime.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from conftest import _CLEAN_ENV

Verdict = Literal["allow", "warn", "block"]


@dataclass(frozen=True)
class GuardCase:
    command: str
    expected: Verdict
    scene: bool = False
    expected_reason: str | None = None
    # Which staged repo is the process/payload cwd for scene rows.
    process_cwd_role: str = "protected"


# Allow/block rows predating tri-state verdicts; guard_cases() lifts them into GuardCase
# form. Kept as plain tuples so the historical row bytes stay reviewable.
_LEGACY_ROWS: list[tuple[str, bool]] = [
    ("rm -rf /", True),
    ("rm -rf ~", True),
    ("rm -rf $HOME", True),
    ("sudo rm -rf /", True),
    ("rm -rf /Users/foo", True),
    # backtick/$(...) rm -rf bypass vectors — the reason this fixture set exists as a
    # differential contract
    ("`rm -rf /`", True),
    ("var=`rm -rf /`", True),
    ("$(rm -rf /)", True),
    ("var=$(rm -rf /)", True),
    ("echo `rm -rf /`", True),
    ("echo $(rm -rf /)", True),
    # force-push backtick command substitutions must remain blocked through
    # both direct-hook and Pi-adapter paths.
    ("OUT=`git push --force origin main`", True),
    ("OUT=`git push -f origin main`", True),
    # same bypass class: process substitution (`<(...)`/`>(...)`) has the identical "(" shape
    # and was left open by a $(-only patch
    ("<(rm -rf ~)", True),
    (">(rm -rf /)", True),
    ("echo <(rm -rf /Users/bob)", True),
    # quote-wrapped / backslash-escaped rm — found by the same review: the fast-gate case
    # used to run on pre-quote-strip text, so a quote immediately before "rm" defeated it
    ('"rm" -rf ~', True),
    ("'rm' -rf $HOME", True),
    ('bash -c "rm -rf /"', True),
    ("\\rm -rf ~", True),
    # allow-list, including legitimate backtick/$(...) subshells with no rm inside
    ("ls -la", False),
    ("rm -rf ./build", False),
    ("rm -rf node_modules", False),
    ("echo `ls`", False),
    ("x=$(date)", False),
    ("echo $(pwd)", False),
    # Force-push forms must remain blocked through both direct-hook and Pi-adapter paths.
    ('git push -o "x;y" --force origin main', True),
    (r"git push -o x\;y --force origin main", True),
    ('git push -o "x&&y" --force origin main', True),
    ("git -c x=y push --force origin main", True),
    ("git push --force --all origin", True),
    ("git push --mirror origin", True),
    # Prefix and option spellings must not hide protected force pushes.
    ("FOO=1 git push --force origin main", True),
    ("sudo git push --force origin main", True),
    ("/usr/local/bin/rtk git push --force origin main", True),
    ('ssh host "git push --force origin main"', True),
    ("xargs git push --force origin main", True),
    ("git push -oX --force origin main", True),
    ("git push --repo=up --force origin main", True),
    ("git push --dry-run -fq origin main", True),
    ("git push -forigin main", True),
    # Wrapper arguments, interpreters, and shell control prefixes stay transparent.
    ("env FOO=1 git push --force origin main", True),
    ("sudo -u root git push --force origin main", True),
    ("sudo FOO=1 git push --force origin main", True),
    ("nice -n 5 git push --force origin main", True),
    ("timeout 30 git push --force origin main", True),
    ("watch -n1 git push --force origin main", True),
    ("xargs -n1 git push --force origin main", True),
    ("bash -c 'git push --force origin main'", True),
    ('sh -c "git push --force origin main"', True),
    ('ssh -p 2222 host "git push --force origin main"', True),
    ("! git push --force origin main", True),
    ("until git push --force origin main; do sleep 1; done", True),
    ("FOO='a b' git push --force origin main", True),
    # Container/session wrappers also execute the protected force push.
    ("docker exec dev git push --force origin main", True),
    ("su -c 'git push --force origin main'", True),
    ("podman exec dev git push --force origin main", True),
    ("kubectl exec pod -- git push --force origin main", True),
    ("setsid git push --force origin main", True),
    ("stdbuf -oL git push --force origin main", True),
    ("flock lock git push --force origin main", True),
    ("script -q /dev/null git push --force origin main", True),
    ("/usr/local/bin/docker exec dev git push --force origin main", True),
    ("/usr/local/bin/podman exec dev git push --force origin main", True),
    ("/usr/local/bin/kubectl exec pod -- git push --force origin main", True),
    # nested non-interactive `pi` session — the bash escape hatch around the subagent
    # dispatcher's --exclude-tools recursion guard
    ("pi -p 'review this'", True),
    ("pi --print x", True),
    ("echo $(pi -p x)", True),
    ("/usr/local/bin/pi -p x", True),
    # a separator character embedded inside a QUOTED pi argument must not be treated as a
    # segment break — this is the vector that defeated the segmenter's first version
    ('pi -m ";" -p file.txt', True),
    ('pi --system-prompt "a;b" --print', True),
    # backslash-continuation join must be parity-aware: an EVEN trailing-backslash count is
    # literal escaped backslashes, not a continuation — it must not swallow a genuinely
    # separate command (rm or pi) on the next line
    ("echo hi\\\\\nrm -rf ~", True),
    ("echo hi\\\\\npi -p x", True),
    # a backslash-ESCAPED separator between pi and its flag is a literal argument byte in
    # real bash, not a real segment break
    ('pi \\; -p "review this"', True),
    # a trailing backslash INSIDE a comment has no continuation meaning — the comment must
    # not absorb a real command on the next physical line
    ("echo a # note \\\nrm -rf ~", True),
    ("echo a # note \\\npi -p x", True),
    # a REAL (unescaped) newline INSIDE a quoted argument is a literal argument byte, not a
    # segment break — the awk record boundary must respect quote state too
    ('pi -m "a\nb" -p x', True),
    # case-insensitive command-name resolution ("Pi"/"PI" resolve to the same binary as "pi"
    # on a case-insensitive filesystem, e.g. macOS's default) must still be caught
    ("Pi -p x", True),
    # flags stay case-sensitive even though the command name doesn't — "--PRINT" is not a
    # real flag spelling
    ("Pi --PRINT x", False),
    # non-recursive pi invocations must stay allowed
    ("pi --version", False),
    ("pi list", False),
    ("git log -p && pi list", False),
    (
        "rtk git push -u origin feature/x && TMP=$(mktemp) "
        "&& trap 'rm -f \"$TMP\"' EXIT",
        False,
    ),
]


def guard_cases() -> list[GuardCase]:
    """Every differential fixture row, as frozen GuardCase records."""
    return [GuardCase(command=cmd, expected="block" if blocked else "allow") for cmd, blocked in _LEGACY_ROWS] + _SCENE_ROWS


def stage_guard_scene(base: Path) -> tuple[Path, Path]:
    """Stage the attribution scene: protected/ on main and feature/ on feat/work.

    Returns (protected_path, feature_path); the caller picks which one is the process
    cwd / payload cwd for the row under test.
    """
    def _git(*args: str, cwd: Path) -> None:
        subprocess.run(
            ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
            env=dict(_CLEAN_ENV),
        )

    def _repo(name: str, branch: str) -> Path:
        repo = base / name
        _git("init", "-b", branch, str(repo), cwd=base)
        _git("config", "user.email", "test@example.com", cwd=repo)
        _git("config", "user.name", "Test", cwd=repo)
        no_hooks = base / ".nohooks"
        no_hooks.mkdir(exist_ok=True)
        _git("config", "core.hooksPath", str(no_hooks), cwd=repo)
        (repo / "README.md").write_text("hello\n")
        _git("add", "README.md", cwd=repo)
        _git("commit", "-m", "init", cwd=repo)
        return repo

    protected, feature = _repo("protected", "main"), _repo("feature", "feat/work")
    # Attribution fixtures: a relative -C target inside the feature repo, and a symlink
    # so git — not path-prefix matching — decides which repo a target resolves to.
    (feature / "sub").mkdir()
    (feature / "protlink").symlink_to(protected)
    return protected, feature


# CWD-attribution rows. Placeholders ({protected}/{feature}) format against
# stage_guard_scene() at run time; expected_reason carries the same placeholders so both
# suites assert full message parity, not just the verdict.
_SCENE_ROWS: list[GuardCase] = [
    GuardCase(
        "cd {feature} && git push -f",
        "warn",
        scene=True,
        expected_reason=(
            "bash_guard: target repo resolved to {feature}; "
            "protected-branch check ran there, not {protected}"
        ),
    ),
    GuardCase("cd {protected} && git push -f", "block", scene=True, process_cwd_role="feature"),
    GuardCase(
        "git -C {feature} push -f",
        "warn",
        scene=True,
        expected_reason=(
            "bash_guard: target repo resolved to {feature}; "
            "protected-branch check ran there, not {protected}"
        ),
    ),
    GuardCase("git -C {protected} push -f", "block", scene=True, process_cwd_role="feature"),
    GuardCase("cd $DEPLOY_DIR && git push -f", "block", scene=True),
    GuardCase(
        "cd $DEPLOY_DIR && git push -f",
        "warn",
        scene=True,
        process_cwd_role="feature",
        expected_reason=(
            "bash_guard: could not resolve effective directory (unresolvable cd); "
            "protected-branch check ran against {feature} only"
        ),
    ),
    GuardCase(
        "cd {feature} && cd {protected} && git push -f", "block", scene=True, process_cwd_role="feature"
    ),
    GuardCase("cd {feature}; git push -f", "block", scene=True),
    GuardCase("git -C protlink push -f", "block", scene=True, process_cwd_role="feature"),
    # A .. component is unresolvable → uncertain → legacy check decides (feature cwd →
    # allow) with the attribution-uncertain warn riding along.
    GuardCase(
        "git -C sub/../sub push -f",
        "warn",
        scene=True,
        process_cwd_role="feature",
        expected_reason=(
            "bash_guard: could not resolve effective directory (unresolvable cd); "
            "protected-branch check ran against {feature} only"
        ),
    ),
    # A resolvable subdir target IS a target ≠ base (same repo, different dir) — the
    # re-attribution warn fires per the behavior matrix; same-repo noise suppression is
    # deliberately not implemented.
    GuardCase(
        "git -C sub push -f",
        "warn",
        scene=True,
        process_cwd_role="feature",
        expected_reason=(
            "bash_guard: target repo resolved to {feature}/sub; "
            "protected-branch check ran there, not {feature}"
        ),
    ),
    GuardCase(
        "cd {feature} && git reset --hard",
        "warn",
        scene=True,
        expected_reason=(
            "bash_guard: target repo resolved to {feature}; "
            "protected-branch check ran there, not {protected}"
        ),
    ),
    GuardCase("cd {protected} && git reset --hard", "block", scene=True, process_cwd_role="feature"),
    GuardCase("git -C {protected} reset --hard", "block", scene=True, process_cwd_role="feature"),
    GuardCase("cd {feature} && git push -f origin main", "block", scene=True),
    GuardCase(
        "cd {feature} && git push -f; cd {protected} && git push -f",
        "block",
        scene=True,
        process_cwd_role="feature",
    ),
    # A push right of || runs only when the left side FAILED — a cd left of || must not
    # leave its target folded for the rest of the chain (never-shrinks).
    GuardCase("cd {feature} || git push -f", "block", scene=True),
    GuardCase("cd {feature} || true && git push -f", "block", scene=True),
    GuardCase("cd {feature} || git reset --hard", "block", scene=True),
    # A pathed cd is an external binary in a child process — it cannot change the parent
    # cwd, so it must neither fold nor evade the legacy check.
    GuardCase("/usr/bin/cd {feature} && git push -f", "block", scene=True),
    # Repo-redirecting git flags decide the repo elsewhere — attribution is uncertain.
    GuardCase(
        "git --git-dir={protected}/.git reset --hard",
        "warn",
        scene=True,
        process_cwd_role="feature",
        expected_reason=(
            "bash_guard: could not resolve effective directory (unresolvable cd); "
            "protected-branch check ran against {feature} only"
        ),
    ),
    # Detection-scope pin: a quoted reset mention inside another git command is not a
    # reset — the tokenized scan does not resume after a non-reset subcommand.
    GuardCase('git commit -m "git reset --hard"', "allow"),
]

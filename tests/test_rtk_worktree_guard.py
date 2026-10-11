"""Behavioural tests for hooks/rtk_worktree_guard.sh (rationale: docs/cross-harness.md §1).

Hermetic: markers, settings, repos, worktrees and the stub `rtk` live under tmp_path, and
the hook's PATH holds only symlinked tools plus the stub. Only TestContractPin reaches the
real `rtk` (skipped when absent), to keep the stub honest. An autouse fixture fails any
test that leaves a marker or worktree registration pointing under its tmp_path.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
HOOK = ROOT / "hooks" / "rtk_worktree_guard.sh"
GOLDEN = ROOT / "tests" / "fixtures" / "rtk_rewrite_golden.json"
BASH = shutil.which("bash") or "/bin/bash"
REAL_RTK = shutil.which("rtk")

# Everything the hook may shell out to; a tool missing here makes it fail open and the
# deny-expecting tests fail loudly.
_TOOLS = (
    "jq", "git", "awk", "sed", "grep", "tr", "cat", "head", "mktemp",
    "sleep", "rm", "rmdir", "mkdir", "mv", "dirname", "basename", "date", "wc",
)  # fmt: skip

SETTINGS_WITH_RTK = {
    "hooks": {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}
        ]
    }
}

# Models `rtk rewrite`: rc 3 + text when rewritten, rc 1 when left alone, and (allow-rule
# mode) rc 0 + text when every segment is allowed. test_stub_matches_real_rtk_rewrite pins it.
_STUB_SOURCE = textwrap.dedent(
    '''\
    #!{python} -S
    import os
    import re
    import sys

    SEP = re.compile(r"(&&|\\|\\||;|\\||\\n)")
    ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\\S*$")
    WRAPPERS = {"time", "command", "builtin", "exec", "nohup", "nice", "timeout"}
    DURATION = re.compile(r"^[0-9.]+[smhd]?$")


    def split_command(cmd):
        # [segment, separator, segment, ...]; separators inside quotes do not split
        parts, buf, quote, i = [], "", "", 0
        while i < len(cmd):
            ch = cmd[i]
            if quote:
                buf += ch
                if ch == quote:
                    quote = ""
            elif ch in "\\"'":
                quote = ch
                buf += ch
            else:
                m = SEP.match(cmd, i)
                if m:
                    parts += [buf, m.group(0)]
                    buf, i = "", m.end()
                    continue
                buf += ch
            i += 1
        return parts + [buf]


    def rewrite_segment(seg, consumer=False):
        stripped = seg.lstrip()
        lead = seg[: len(seg) - len(stripped)]
        rest, prefix = stripped, ""
        in_wrapper = skip = False
        while True:
            m = re.match(r"(\\S+)(\\s+)(.*)$", rest, re.S)
            if not m:
                break
            word = m.group(1)
            if word == "RTK_DISABLED=1":
                return seg
            if skip:
                skip = False
            elif ASSIGN.match(word) or word in WRAPPERS:
                in_wrapper = word in WRAPPERS
            elif in_wrapper and word.startswith("-"):
                skip = word in ("-n", "-k", "-s")
            elif in_wrapper and DURATION.match(word):
                pass
            else:
                break
            prefix += word + m.group(2)
            rest = m.group(3)
        first = rest.split(None, 1)[0] if rest.strip() else ""
        if first in ("git", "ls") or (consumer and first == "grep"):
            return lead + prefix + "rtk " + rest
        if first == "cat":
            return lead + prefix + "rtk read" + rest[len("cat"):]
        return seg


    def allowed(cmd):
        # an allow rule such as `Bash(git *)` covers a command only when every typed
        # segment starts with git and nothing is piped
        if re.search(r"(?<!\\|)\\|(?!\\|)", cmd):
            return False
        segments = [s.strip() for s in re.split(r"&&|\\|\\||;|\\n", cmd)]
        return all(s.startswith("git ") for s in segments if s)


    def main(argv):
        args = argv[1:]
        if not args or args[0] != "rewrite":
            return 2
        args = args[1:]
        if args and args[0] == "--":
            args = args[1:]
        if not args:
            return 2
        hang = os.environ.get("RTK_STUB_HANG")
        if hang:
            os.execvp("sleep", ["rtk-stub-" + hang, "30"])
        forced = os.environ.get("RTK_STUB_RC")
        if forced is not None:
            return int(forced)
        cmd = args[0]
        fixed_rc = os.environ.get("RTK_STUB_FIXED_RC")
        if fixed_rc is not None and "RTK_DISABLED=1" in cmd:
            return int(fixed_rc)
        words = cmd.split(None, 1)
        if words and words[0] == "rtk":
            sys.stdout.write(cmd)
            return 3
        if "$(" in cmd or "`" in cmd or "<<" in cmd:
            return 1
        parts = split_command(cmd)
        # RTK rewrites a `grep` consumer instead of the producer feeding it
        grep_consumer = any(
            parts[i - 1] == "|" and parts[i].split(None, 1)[:1] == ["grep"]
            for i in range(2, len(parts), 2)
        )
        out = []
        for i, p in enumerate(parts):
            if i % 2:
                out.append(p)
            elif grep_consumer and i + 1 < len(parts) and parts[i + 1] == "|":
                out.append(p)
            else:
                out.append(rewrite_segment(p, consumer=i > 0 and parts[i - 1] == "|"))
        result = "".join(out)
        if result == cmd:
            return 1
        sys.stdout.write(result)
        if os.environ.get("RTK_STUB_ALLOW_RULE") and allowed(cmd):
            return 0
        return 3


    sys.exit(main(sys.argv))
    '''
)


def _git(args, cwd, env):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )


def _write_stub(directory: Path) -> Path:
    stub = directory / "rtk"
    stub.write_text(_STUB_SOURCE.replace("{python}", sys.executable), encoding="utf-8")
    stub.chmod(0o755)
    return stub


@pytest.fixture(scope="module")
def git_fixture(tmp_path_factory):
    """One repo with a linked worktree per module: building it per test dominated the
    runtime. Tests only read it; what they write into it is removed by Sandbox.cleanup."""
    base = tmp_path_factory.mktemp("rtk-git")
    repo, wt, home = base / "repo", base / "work" / "wt", base / "home"
    home.mkdir()
    genv = {**dict(_CLEAN_ENV), "HOME": str(home)}
    repo.mkdir()
    _git(["init", "-q"], repo, genv)
    _git(["commit", "-q", "--allow-empty", "-m", "init"], repo, genv)
    wt.parent.mkdir()
    _git(["worktree", "add", "-q", "-b", "wt-branch", str(wt)], repo, genv)
    yield SimpleNamespace(repo=repo, wt=wt)
    for cmd in (["worktree", "remove", "--force", str(wt)], ["worktree", "prune"]):
        subprocess.run(["git", *cmd], cwd=repo, env=genv, capture_output=True)


@pytest.fixture
def stub_only(tmp_path):
    """Just the stub and a HOME, for tests that never run the hook."""
    bin_dir, home = tmp_path / "stub-bin", tmp_path / "home"
    bin_dir.mkdir()
    (home / ".claude").mkdir(parents=True)
    return SimpleNamespace(stub=_write_stub(bin_dir), home=home, base=tmp_path)


class Sandbox:
    def __init__(self, base: Path, repo: Path, wt: Path):
        self.base = base
        self.home = base / "home"
        self.tmpdir = base / "tmp"
        self.stub_bin = base / "stub-bin"
        self.tool_bin = base / "tool-bin"
        self.repo = repo
        self.wt = wt
        self.elsewhere = base / "elsewhere"
        self.session = "sess-" + uuid.uuid4().hex[:8]
        for d in (self.home / ".claude", self.tmpdir, self.stub_bin, self.tool_bin, self.elsewhere):
            d.mkdir(parents=True)
        for name in _TOOLS:
            real = shutil.which(name)
            if real:
                (self.tool_bin / name).symlink_to(real)
        self.stub = _write_stub(self.stub_bin)

    def cleanup(self):
        """Undo what a test wrote into the shared repo/worktree."""
        for leftover in (
            self.repo / ".claude",
            self.wt / ".claude",
            self.wt / "sub",
            Path(str(self.wt) + "-other"),
        ):
            shutil.rmtree(leftover, ignore_errors=True)

    @property
    def marker_dir(self) -> Path:
        return self.tmpdir / "swe_wb_rtk_worktree"

    def marker(self, agent: str | None = None) -> Path:
        name = self.session if agent is None else f"{self.session}_{agent}"
        return self.marker_dir / name

    def env(self, *, stub=True, omit_tools=(), **extra) -> dict:
        tool_dir = self.tool_bin
        if omit_tools:
            tool_dir = self.base / "tool-bin-reduced"
            tool_dir.mkdir()
            for link in self.tool_bin.iterdir():
                if link.name not in omit_tools:
                    (tool_dir / link.name).symlink_to(link.resolve())
        path = f"{self.stub_bin}:{tool_dir}" if stub else str(tool_dir)
        base = dict(_CLEAN_ENV)
        # ambient values must not leak a developer's real config dir or kill-switch in
        for ambient in ("CLAUDE_CONFIG_DIR", "SWE_WORKBENCH_RTK_WORKTREE_GUARD"):
            base.pop(ambient, None)
        return {**base, "HOME": str(self.home), "TMPDIR": str(self.tmpdir), "PATH": path, **extra}

    def write_settings(self, where: str = "home", data=SETTINGS_WITH_RTK, name="settings.json"):
        base = {"home": self.home, "project": self.repo, "worktree": self.wt}[where]
        target = base / ".claude" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data), encoding="utf-8")

    def run(self, payload=None, *, raw: str | None = None, env=None, timeout=20):
        stdin = raw if raw is not None else json.dumps(payload)
        return subprocess.run(
            [BASH, str(HOOK)],
            input=stdin,
            env=env if env is not None else self.env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    # payload builders -------------------------------------------------------
    def enter_payload(self, agent=None, path=None):
        wt = str(path or self.wt)
        p = {
            "hook_event_name": "PostToolUse",
            "tool_name": "EnterWorktree",
            "session_id": self.session,
            "cwd": wt,
            "tool_response": {"worktreePath": wt},
        }
        if agent:
            p["agent_id"] = agent
        return p

    def exit_payload(self, agent=None):
        p = {
            "hook_event_name": "PostToolUse",
            "tool_name": "ExitWorktree",
            "session_id": self.session,
            "cwd": str(self.repo),
            "tool_response": {"worktreePath": str(self.wt), "originalCwd": str(self.repo)},
        }
        if agent:
            p["agent_id"] = agent
        return p

    def bash_payload(self, command, cwd=None, agent=None, tool="Bash"):
        p = {
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "session_id": self.session,
            "cwd": str(cwd or self.wt),
            "tool_input": {"command": command},
        }
        if agent:
            p["agent_id"] = agent
        return p

    def isolate(self, agent=None, *, via_hook=False):
        """Configure RTK's hook and make the session isolated. The marker is written
        directly (fast) unless via_hook, which delivers a real EnterWorktree; the enter
        path has dedicated tests, so tests of the Bash path need not pay for it."""
        self.write_settings()
        if via_hook:
            r = self.run(self.enter_payload(agent=agent))
            assert r.returncode == 0, r.stderr
            return r
        self.marker_dir.mkdir(mode=0o700, exist_ok=True)
        self.marker(agent).write_text(str(self.wt.resolve()) + "\n", encoding="utf-8")
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")


@pytest.fixture
def sandbox(tmp_path, git_fixture):
    box = Sandbox(tmp_path, git_fixture.repo, git_fixture.wt)
    try:
        yield box
    finally:
        box.cleanup()


@pytest.fixture(autouse=True)
def _no_marker_residue(tmp_path_factory):
    """No marker in the real temp dirs may point under this pytest session's temp root.
    Matching by that root means unrelated live sessions cannot fail an unrelated test."""
    yield
    session_root = str(tmp_path_factory.getbasetemp().resolve())
    leaked = []
    for d in {Path("/tmp"), Path(os.environ.get("TMPDIR") or "/tmp")}:
        for marker_dir in d.glob("swe_wb_rtk_worktree*"):
            for marker in marker_dir.glob("*") if marker_dir.is_dir() else [marker_dir]:
                try:
                    if marker.read_text().startswith(session_root):
                        leaked.append(str(marker))
                except OSError:
                    pass
    assert leaked == [], f"test leaked a marker into a real temp dir: {leaked}"


@pytest.fixture(autouse=True, scope="module")
def _no_worktree_residue(tmp_path_factory):
    """No test module may register a worktree on the real repository."""
    yield
    session_root = str(tmp_path_factory.getbasetemp().resolve())
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=ROOT, env=dict(_CLEAN_ENV), capture_output=True, text=True,
    ).stdout  # fmt: skip
    leaked = [ln for ln in listing.splitlines() if ln.startswith("worktree ") and session_root in ln]
    assert leaked == [], f"module registered a worktree on the real repository: {leaked}"


def _fix_from(stderr: str) -> str:
    _, _, rest = stderr.partition("Next step — run exactly:\n")
    lines = rest.rstrip("\n").split("\n")
    return "\n".join(ln[2:] if ln.startswith("  ") else ln for ln in lines)


def _tags(stderr: str) -> str:
    m = re.search(r"BLOCKED \[rtk-worktree:([a-z-]+)\]", stderr)
    return m.group(1) if m else ""


RTK_GIT = re.compile(r"(^|[\s;&|(])(\S*/)?rtk\s+(proxy\s+)?(\S*/)?git(\s|$)")

# (id, template, expect_containment_deny) -- the oracle is the verified experiment matrix:
# deny exactly where what will actually run is `rtk [proxy] git ...`.
MATRIX = [
    ("bare", "git {op}", True),
    ("dash-C", "git -C {wt} {op}", True),
    ("rtk", "rtk git {op}", True),
    ("rtk-proxy", "rtk proxy git {op}", True),
    ("abs-git", "/usr/bin/git {op}", False),
    ("abs-rtk", "/opt/x/rtk git {op}", True),
    ("disabled", "RTK_DISABLED=1 git {op}", False),
    ("env-disabled", "env RTK_DISABLED=1 git {op}", False),
    ("export-then-git", "export RTK_DISABLED=1; git {op}", True),
    ("compound", "git {op} && git log", True),
    ("ls-then-git", "ls && git {op}", True),
    ("pipe", "git {op} | head -3", True),
    ("env-assign", "FOO=1 git {op}", True),
    ("multi-line", "git {op}\ngit log", True),
    ("compound-disabled", "RTK_DISABLED=1 git {op} && RTK_DISABLED=1 git log", False),
    ("ls-then-disabled", "ls && RTK_DISABLED=1 git {op}", False),
]
OPS = [("status", "status"), ("mutating", "commit --allow-empty -m x")]
CASES = [
    pytest.param(tpl, op, deny, id=f"{cid}-{oid}")
    for cid, tpl, deny in MATRIX
    for oid, op in OPS
]
DENY_CASES = [
    pytest.param(tpl, op, id=f"{cid}-{oid}")
    for cid, tpl, deny in MATRIX
    if deny
    for oid, op in OPS
]


def _assert_clean_tmp(box: Sandbox):
    leftovers = [p.name for p in box.tmpdir.iterdir() if p.name != "swe_wb_rtk_worktree"]
    assert leftovers == [], f"hook left temp files behind: {leftovers}"


class TestSpellingMatrix:
    @pytest.mark.parametrize("template,op,deny", CASES)
    def test_decision_follows_what_will_actually_run(self, sandbox, template, op, deny):
        sandbox.isolate()
        cmd = template.format(op=op, wt=sandbox.wt)
        r = sandbox.run(sandbox.bash_payload(cmd))
        if deny:
            assert r.returncode == 2, (cmd, r.stdout, r.stderr)
            assert _tags(r.stderr) == "containment", r.stderr
            assert str(sandbox.wt.resolve()) in r.stderr
        else:
            assert r.returncode == 0, (cmd, r.stderr)
            assert "BLOCKED" not in r.stderr
        _assert_clean_tmp(sandbox)

    @pytest.mark.parametrize("template,op", DENY_CASES)
    def test_rendered_next_step_is_itself_allowed(self, sandbox, template, op):
        sandbox.isolate()
        cmd = template.format(op=op, wt=sandbox.wt)
        denied = sandbox.run(sandbox.bash_payload(cmd))
        assert denied.returncode == 2
        fix = _fix_from(denied.stderr)
        assert "RTK_DISABLED=1" in fix
        assert not RTK_GIT.search(fix), f"fix still routes git through rtk: {fix!r}"
        again = sandbox.run(sandbox.bash_payload(fix))
        assert again.returncode == 0, (cmd, fix, again.stderr)


class TestQuotedCommandsGetAnExactFix:
    @pytest.mark.parametrize(
        "cmd,fix",
        [
            pytest.param(
                'git commit --allow-empty -m "x"',
                'RTK_DISABLED=1 git commit --allow-empty -m "x"',
                id="double-quoted",
            ),
            pytest.param(
                "git commit --allow-empty -m 'x'",
                "RTK_DISABLED=1 git commit --allow-empty -m 'x'",
                id="single-quoted",
            ),
            pytest.param(
                'git commit --allow-empty -m "a; git b && rtk git c"',
                'RTK_DISABLED=1 git commit --allow-empty -m "a; git b && rtk git c"',
                id="separators-inside-the-message-are-left-alone",
            ),
            pytest.param(
                'git status; echo "done"',
                'RTK_DISABLED=1 git status; echo "done"',
                id="quote-in-a-non-git-segment",
            ),
        ],
    )
    def test_fix_is_the_typed_command_with_only_the_prefix_added(self, sandbox, cmd, fix):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 2, r.stderr
        assert _tags(r.stderr) == "containment", r.stderr
        assert _fix_from(r.stderr) == fix
        assert sandbox.run(sandbox.bash_payload(fix)).returncode == 0

    @pytest.mark.parametrize(
        "cmd,fix",
        [
            ("git status; ls", "RTK_DISABLED=1 git status; ls"),
            ("ls && git status", "ls && RTK_DISABLED=1 git status"),
            ("git status && git log", "RTK_DISABLED=1 git status && RTK_DISABLED=1 git log"),
            ("FOO=1 git status", "RTK_DISABLED=1 FOO=1 git status"),
            ("rtk proxy git status", "RTK_DISABLED=1 git status"),
        ],
    )
    def test_other_segments_keep_the_text_the_model_wrote(self, sandbox, cmd, fix):
        # RTK also rewrites `ls`; the rendered fix must not embed that rewrite.
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 2, r.stderr
        assert _fix_from(r.stderr) == fix


class TestParseComplexity:
    @pytest.mark.parametrize(
        "cmd",
        [
            pytest.param("rtk git log $(git rev-parse HEAD)", id="command-substitution"),
            pytest.param("rtk git log `git rev-parse HEAD`", id="backtick"),
            pytest.param("rtk git commit -F - <<EOF\nmsg\nEOF", id="heredoc"),
        ],
    )
    def test_denied_with_the_fixed_next_step(self, sandbox, cmd):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 2, r.stderr
        assert _tags(r.stderr) == "parse-complexity", r.stderr
        assert "own Bash call" in r.stderr
        assert "RTK_DISABLED=1 " in r.stderr
        assert "Next step — run exactly:" not in r.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            pytest.param("git log $(git rev-parse HEAD)", id="command-substitution"),
            pytest.param("git commit -F - <<EOF\nmsg\nEOF", id="heredoc"),
        ],
    )
    def test_command_rtk_leaves_alone_is_not_this_hooks_business(self, sandbox, cmd):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 0, r.stderr
        assert r.stderr == ""

    def test_fix_that_would_still_deny_is_not_offered_as_exact(self, sandbox):
        # A backslash-newline hides `rtk git` from the renderer but not the scanner, so
        # the fix is a no-op the self-check must refuse to offer.
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload("rtk \\\ngit status"))
        assert r.returncode == 2, r.stderr
        assert _tags(r.stderr) == "no-exact-fix", r.stderr
        assert "Next step — run exactly:" not in r.stderr

    def test_undecidable_self_check_is_not_treated_as_verified(self, sandbox):
        # If the rendered fix cannot be run back through `rtk rewrite` (here: an odd exit
        # code), "run exactly" would present an unverified command as verified.
        sandbox.isolate()
        env = sandbox.env(RTK_STUB_FIXED_RC="7")
        r = sandbox.run(sandbox.bash_payload("git status"), env=env)
        assert r.returncode == 2, r.stderr
        assert _tags(r.stderr) == "no-exact-fix", r.stderr
        assert "Next step — run exactly:" not in r.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            "time git status",
            "time -p git status",
            "command git status",
            "builtin git status",
            "exec git status",
            "nohup git status",
            "nice git status",
            "nice -n 5 git status",
            "RTK_DISABLED_NOT=1 time git status",
        ],
    )
    def test_wrapper_launchers_are_denied_without_a_naive_rendered_fix(self, sandbox, cmd):
        # RTK rewrites `time git` to `time rtk git`; a textual `RTK_DISABLED=1` splice would
        # yield `command RTK_DISABLED=1 git`, which does not run, so no exact fix is offered.
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 2, r.stderr
        assert _tags(r.stderr) == "no-exact-fix", r.stderr
        assert "own Bash call" in r.stderr

    @pytest.mark.parametrize(
        "cmd",
        ["time RTK_DISABLED=1 git status", "RTK_DISABLED=1 command git status", "time ls"],
    )
    def test_wrapped_commands_rtk_leaves_alone_are_allowed(self, sandbox, cmd):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 0, r.stderr


class TestSegmentScanner:
    @pytest.mark.parametrize(
        "cmd",
        [
            "timeout 5 git status",
            "timeout -k 1 5 git status",
            "timeout 5 git log --grep=rtk",
            "timeout 5 git log --grep rtk",
            "timeout 5 git checkout fix/rtk-hook",
            "timeout 5 git show docs/rtk.md",
        ],
    )
    def test_any_launcher_rtk_spliced_in_is_denied(self, sandbox, cmd):
        # RTK only ever splices `rtk` itself; an `rtk` word elsewhere in the typed text
        # (branch, path, --grep) must not switch that detection off.
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 2, r.stderr
        assert _tags(r.stderr) == "no-exact-fix", r.stderr

    def test_typed_rtk_in_argument_position_is_not_a_launch(self, sandbox):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload("echo rtk git status"))
        assert r.returncode == 0, r.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            pytest.param("echo hi; # x; rtk git status", id="comment"),
            pytest.param("cat <<\\EOF\nrtk git status\nEOF", id="backslash-delimiter"),
            pytest.param("cat <<'---'\nrtk git status\n---", id="punctuation-delimiter"),
            pytest.param("cat <<-EOF\n\trtk git status\n\tEOF", id="tab-stripped-delimiter"),
        ],
    )
    def test_text_that_never_executes_is_not_denied(self, sandbox, cmd):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 0, r.stderr

    @pytest.mark.parametrize(
        "cmd",
        [
            pytest.param('echo "<<EOF"\nrtk git status', id="quoted-heredoc-marker"),
            pytest.param("cat <<< hi\nrtk git status", id="here-string"),
            pytest.param("echo $((1<<y))\nrtk git status", id="arithmetic-shift"),
            pytest.param("cat <<EOF\nbody\nEOF\nrtk git status", id="after-heredoc-end"),
        ],
    )
    def test_command_after_a_non_heredoc_is_still_scanned(self, sandbox, cmd):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload(cmd))
        assert r.returncode == 2, r.stderr


class TestScoping:
    def test_enter_does_nothing_when_rtk_would_not_rewrite_git(self, sandbox):
        # e.g. RTK's `exclude_commands = ["git"]`: the marker (and its advice) would mislead
        sandbox.write_settings()
        r = sandbox.run(sandbox.enter_payload(), env=sandbox.env(RTK_STUB_RC="1"))
        assert r.returncode == 0
        assert r.stdout == ""
        assert not sandbox.marker().exists()

    def test_enter_does_nothing_without_rtk_on_path(self, sandbox):
        sandbox.write_settings()
        r = sandbox.run(sandbox.enter_payload(), env=sandbox.env(stub=False))
        assert r.stdout == ""
        assert not sandbox.marker().exists()

    def test_prune_leaves_empty_marker_files_alone(self, sandbox):
        # an empty file may be another session mid-write
        sandbox.marker_dir.mkdir()
        racing = sandbox.marker_dir / "racing-session"
        racing.write_text("")
        sandbox.isolate(via_hook=True)
        assert racing.exists()

    def test_subagent_without_its_own_marker_inherits_the_session_marker(self, sandbox):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload("git status", agent="agent9"))
        assert r.returncode == 2, r.stderr
        assert _tags(r.stderr) == "containment"
        outside = sandbox.run(sandbox.bash_payload("git status", cwd=sandbox.elsewhere, agent="agent9"))
        assert outside.returncode == 0

    def test_agents_own_marker_wins_over_the_session_marker(self, sandbox):
        sandbox.isolate()
        other = sandbox.base / "other-wt"
        other.mkdir()
        sandbox.run(sandbox.enter_payload(agent="agent9", path=other))
        # the agent's marker points at a different worktree, so the session's does not apply
        r = sandbox.run(sandbox.bash_payload("git status", cwd=sandbox.wt, agent="agent9"))
        assert r.returncode == 0, r.stderr

    def test_config_dir_env_replaces_home_dot_claude(self, sandbox):
        cfg = sandbox.base / "relocated-config"
        cfg.mkdir()
        (cfg / "settings.json").write_text(json.dumps(SETTINGS_WITH_RTK))
        env = sandbox.env(CLAUDE_CONFIG_DIR=str(cfg))
        r = sandbox.run(sandbox.enter_payload(), env=env)
        assert r.returncode == 0
        assert sandbox.marker().exists()

    def test_home_settings_are_not_read_when_config_dir_is_set(self, sandbox):
        sandbox.write_settings()
        cfg = sandbox.base / "empty-config"
        cfg.mkdir()
        sandbox.run(sandbox.enter_payload(), env=sandbox.env(CLAUDE_CONFIG_DIR=str(cfg)))
        assert not sandbox.marker().exists()

    def test_marker_dir_is_private(self, sandbox):
        sandbox.isolate(via_hook=True)
        assert stat.S_IMODE(sandbox.marker_dir.stat().st_mode) == 0o700
        assert [p.name for p in sandbox.marker_dir.iterdir()] == [sandbox.session]

    def test_symlinked_marker_dir_is_not_followed(self, sandbox):
        target = sandbox.base / "attacker-dir"
        target.mkdir()
        sandbox.marker_dir.symlink_to(target)
        sandbox.write_settings()
        sandbox.run(sandbox.enter_payload())
        assert list(target.iterdir()) == []
        denied = sandbox.run(sandbox.bash_payload("git status"))
        assert denied.returncode == 0

    def test_kill_switch_disables_marker_and_deny(self, sandbox):
        off = sandbox.env(SWE_WORKBENCH_RTK_WORKTREE_GUARD="0")
        sandbox.write_settings()
        sandbox.run(sandbox.enter_payload(), env=off)
        assert not sandbox.marker().exists()
        sandbox.isolate()
        assert sandbox.run(sandbox.bash_payload("git status")).returncode == 2
        assert sandbox.run(sandbox.bash_payload("git status"), env=off).returncode == 0

    def test_no_marker_allows(self, sandbox):
        r = sandbox.run(sandbox.bash_payload("git status"))
        assert r.returncode == 0
        assert r.stderr == ""

    def test_cwd_outside_the_marked_worktree_allows(self, sandbox):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload("git status", cwd=sandbox.elsewhere))
        assert r.returncode == 0, r.stderr

    def test_cwd_in_a_subdirectory_of_the_worktree_is_scoped_in(self, sandbox):
        sandbox.isolate()
        sub = sandbox.wt / "sub"
        sub.mkdir()
        r = sandbox.run(sandbox.bash_payload("git status", cwd=sub))
        assert r.returncode == 2

    def test_sibling_directory_sharing_a_prefix_is_not_inside(self, sandbox):
        sandbox.isolate()
        sibling = Path(str(sandbox.wt) + "-other")
        sibling.mkdir()
        r = sandbox.run(sandbox.bash_payload("git status", cwd=sibling))
        assert r.returncode == 0

    def test_non_bash_pre_tool_use_is_ignored(self, sandbox):
        sandbox.isolate()
        r = sandbox.run(sandbox.bash_payload("git status", tool="Read"))
        assert r.returncode == 0

    def test_enter_without_rtk_hook_writes_no_marker_and_no_context(self, sandbox):
        sandbox.write_settings(data={"hooks": {}})
        r = sandbox.run(sandbox.enter_payload())
        assert r.returncode == 0
        assert r.stdout == ""
        assert not sandbox.marker().exists()

    def test_enter_with_rtk_hook_writes_marker_and_context(self, sandbox):
        r = sandbox.isolate(via_hook=True)
        assert sandbox.marker().read_text().strip() == str(sandbox.wt.resolve())
        ctx = json.loads(r.stdout)["hookSpecificOutput"]
        assert ctx["hookEventName"] == "PostToolUse"
        assert "RTK_DISABLED=1" in ctx["additionalContext"]

    @pytest.mark.parametrize(
        "where,name",
        [
            ("project", "settings.json"),
            ("project", "settings.local.json"),
            ("worktree", "settings.json"),
            ("worktree", "settings.local.json"),
        ],
    )
    def test_project_level_settings_are_honoured(self, sandbox, where, name):
        sandbox.write_settings(where=where, name=name)
        sandbox.run(sandbox.enter_payload())
        assert sandbox.marker().exists()

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(
                {"hooks": {"PreToolUse": [{"hooks": [{"command": "my-rtk hook claude"}]}]}},
                id="lookalike-binary",
            ),
            pytest.param({"env": {"NOTE": "rtk hook claude"}}, id="outside-hooks"),
        ],
    )
    def test_lookalike_settings_do_not_count(self, sandbox, data):
        sandbox.write_settings(data=data)
        sandbox.run(sandbox.enter_payload())
        assert not sandbox.marker().exists()

    def test_absolute_path_rtk_hook_entry_counts(self, sandbox):
        data = {"hooks": {"PreToolUse": [{"hooks": [{"command": "/opt/homebrew/bin/rtk hook claude"}]}]}}
        sandbox.write_settings(data=data)
        sandbox.run(sandbox.enter_payload())
        assert sandbox.marker().exists()

    def test_reentering_the_same_worktree_does_not_repeat_the_context(self, sandbox):
        first = sandbox.isolate(via_hook=True)
        assert first.stdout != ""
        again = sandbox.run(sandbox.enter_payload())
        assert again.returncode == 0
        assert again.stdout == ""
        assert sandbox.marker().exists()

    def test_enter_prunes_markers_whose_worktree_no_longer_exists(self, sandbox):
        # Headless sessions end without ExitWorktree, leaving markers that point at
        # removed worktrees; entering a new one must sweep those, and only those.
        sandbox.marker_dir.mkdir()
        stale = sandbox.marker_dir / "stale-session"
        stale.write_text(str(sandbox.base / "gone" / "wt") + "\n")
        live = sandbox.marker_dir / "live-session"
        live.write_text(str(sandbox.wt.resolve()) + "\n")
        sandbox.isolate(via_hook=True)
        assert not stale.exists()
        assert live.exists()
        assert sandbox.marker().exists()

    def test_exit_worktree_removes_marker_and_empty_marker_dir(self, sandbox):
        sandbox.isolate()
        assert sandbox.marker().exists()
        r = sandbox.run(sandbox.exit_payload())
        assert r.returncode == 0
        assert not sandbox.marker().exists()
        assert not sandbox.marker_dir.exists()
        assert list(sandbox.tmpdir.iterdir()) == []

    def test_exit_keeps_marker_dir_when_another_session_still_has_a_marker(self, sandbox):
        sandbox.isolate()
        other = sandbox.marker_dir / "other-session"
        other.write_text(str(sandbox.wt))
        sandbox.run(sandbox.exit_payload())
        assert other.exists()
        assert not sandbox.marker().exists()

    def test_after_exit_the_command_is_allowed(self, sandbox):
        sandbox.isolate()
        sandbox.run(sandbox.exit_payload())
        r = sandbox.run(sandbox.bash_payload("git status"))
        assert r.returncode == 0

    def test_agent_id_gets_its_own_marker_key(self, sandbox):
        sandbox.isolate(agent="agent7", via_hook=True)
        assert sandbox.marker(agent="agent7").exists()
        assert not sandbox.marker().exists()
        mine = sandbox.run(sandbox.bash_payload("git status", agent="agent7"))
        assert mine.returncode == 2
        parent = sandbox.run(sandbox.bash_payload("git status"))
        assert parent.returncode == 0
        sibling = sandbox.run(sandbox.bash_payload("git status", agent="agent8"))
        assert sibling.returncode == 0
        sandbox.run(sandbox.exit_payload(agent="agent7"))
        assert not sandbox.marker(agent="agent7").exists()

    def test_ids_are_sanitized_before_touching_the_filesystem(self, sandbox):
        sandbox.write_settings()
        p = sandbox.enter_payload()
        p["session_id"] = "../../escape"
        sandbox.run(p)
        assert not (sandbox.tmpdir.parent / "escape").exists()
        assert [m.name for m in sandbox.marker_dir.iterdir()] == ["______escape"]


class TestFailOpen:
    def _assert_open(self, r):
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "BLOCKED" not in r.stderr

    @pytest.mark.parametrize("raw", ["{not json", "", "[]", "null"])
    def test_malformed_stdin(self, sandbox, raw):
        self._assert_open(sandbox.run(raw=raw))

    def test_missing_jq(self, sandbox):
        sandbox.isolate()
        env = sandbox.env(omit_tools=("jq",))
        self._assert_open(sandbox.run(sandbox.bash_payload("git status"), env=env))

    def test_missing_rtk(self, sandbox):
        sandbox.isolate()
        env = sandbox.env(stub=False)
        self._assert_open(sandbox.run(sandbox.bash_payload("git status"), env=env))

    @pytest.mark.parametrize("rc", ["0", "1", "2", "7", "124", "3"])
    def test_rewrite_exit_codes_without_a_rewritten_command_allow(self, sandbox, rc):
        sandbox.isolate()
        env = sandbox.env(RTK_STUB_RC=rc)
        self._assert_open(sandbox.run(sandbox.bash_payload("git status"), env=env))
        _assert_clean_tmp(sandbox)

    @pytest.mark.parametrize(
        "cmd",
        [
            "git status",
            "git -C {wt} status",
            "git commit --allow-empty -m x",
            "git status && git log",
        ],
    )
    def test_allow_rule_rewrite_exiting_zero_is_still_denied(self, sandbox, cmd):
        # With `Bash(git *)` allowed, RTK exits 0 *with* the rewritten command; treating
        # rc 0 as "unchanged" would silently disable the guard for the commonest config.
        sandbox.isolate()
        env = sandbox.env(RTK_STUB_ALLOW_RULE="1")
        r = sandbox.run(sandbox.bash_payload(cmd.format(wt=sandbox.wt)), env=env)
        assert r.returncode == 2, r.stderr
        assert _tags(r.stderr) == "containment", r.stderr
        fix = _fix_from(r.stderr)
        assert not RTK_GIT.search(fix), fix
        assert sandbox.run(sandbox.bash_payload(fix), env=env).returncode == 0

    def test_unreadable_cwd_is_fail_open(self, sandbox):
        sandbox.isolate()
        p = sandbox.bash_payload("git status")
        p["cwd"] = str(sandbox.base / "does-not-exist")
        self._assert_open(sandbox.run(p))

    def test_hung_rewrite_is_killed_reaped_and_allowed(self, sandbox):
        sandbox.isolate()
        token = uuid.uuid4().hex
        env = sandbox.env(RTK_STUB_HANG=token)
        started = time.monotonic()
        r = sandbox.run(sandbox.bash_payload("git status"), env=env, timeout=30)
        elapsed = time.monotonic() - started
        self._assert_open(r)
        assert elapsed < 10, f"hook did not bound the rewrite call ({elapsed:.1f}s)"
        orphans = subprocess.run(
            ["pgrep", "-f", f"rtk-stub-{token}"],
            env=dict(_CLEAN_ENV), capture_output=True, text=True,
        )  # fmt: skip
        assert orphans.returncode == 1, f"orphaned rewrite child: {orphans.stdout!r}"
        _assert_clean_tmp(sandbox)


class TestContractPin:
    FIXTURES = [
        "git status",
        "git -C /x status",
        "RTK_DISABLED=1 git status",
        "env RTK_DISABLED=1 git status",
        "/usr/bin/git status",
        "rtk git status",
        "rtk proxy git status",
        "/opt/x/rtk git status",
        "export RTK_DISABLED=1; git status",
        "time git status",
        "time -p git status",
        "command git status",
        "builtin git status",
        "exec git status",
        "nohup git status",
        "nice git status",
        "nice -n 5 git status",
        "timeout 5 git status",
        "timeout -k 1 5 git status",
        "time RTK_DISABLED=1 git status",
        "RTK_DISABLED=1 command git status",
        "echo rtk git status",
        "ls && git status",
        "ls && RTK_DISABLED=1 git status",
        "RTK_DISABLED=1 git status && RTK_DISABLED=1 git log",
        "git status | head -3",
        "git status | grep foo",
        "FOO=1 git status",
        "git status\ngit log",
        "git status; ls",
        "git status || cat x",
        "cd /x && git status 2>&1",
        "timeout 5 git log --grep=rtk",
        'git commit --allow-empty -m "x"',
        'git commit --allow-empty -m "a; git b"',
        "git log $(git rev-parse HEAD)",
        "git commit -F - <<EOF\nmsg\nEOF",
        "echo hi",
    ]

    # Under `permissions.allow: ["Bash(git *)"]` RTK reports a fully-allowed rewrite as rc 0
    # with the rewritten command on stdout, not rc 3.
    ALLOW_RULE_FIXTURES = [
        "git status",
        "git -C /x status",
        "git commit --allow-empty -m x",
        "git status && git log",
        "ls && git status",
        "git status | head -3",
        "time git status",
        "RTK_DISABLED=1 git status",
    ]

    @staticmethod
    def _run_rewrite(binary, cmd, home, cwd, allow_rule, extra_env=None):
        # neutral cwd and a temp HOME: the real rc depends on any settings found there
        settings = Path(home) / ".claude" / "settings.json"
        if allow_rule:
            settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git *)"]}}))
        elif settings.exists():
            settings.unlink()
        env = {**dict(_CLEAN_ENV), "HOME": str(home), **(extra_env or {})}
        done = subprocess.run(
            [str(binary), "rewrite", "--", cmd], env=env, cwd=cwd, capture_output=True, text=True
        )
        return {"rc": done.returncode, "stdout": done.stdout}

    @staticmethod
    def _recorded():
        return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]

    def test_golden_covers_every_pinned_spelling(self):
        recorded = {(c["cmd"], c["allow_rule"]) for c in self._recorded()}
        wanted = {(c, False) for c in self.FIXTURES} | {(c, True) for c in self.ALLOW_RULE_FIXTURES}
        assert wanted <= recorded, f"regenerate the golden file: {sorted(wanted - recorded)}"

    @pytest.mark.parametrize(
        "case",
        json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"],
        ids=lambda c: f"{'allow:' if c['allow_rule'] else ''}{c['cmd']!r}",
    )
    def test_stub_reproduces_the_recorded_rtk_rewrite(self, stub_only, case):
        # Runs everywhere (CI has no rtk): the stub every hook test leans on is held to
        # answers recorded from the real binary.
        extra = {"RTK_STUB_ALLOW_RULE": "1"} if case["allow_rule"] else {}
        got = self._run_rewrite(stub_only.stub, case["cmd"], stub_only.home, stub_only.base, False, extra)
        assert got == {"rc": case["rc"], "stdout": case["stdout"]}

    @pytest.mark.skipif(REAL_RTK is None, reason="real rtk not installed")
    @pytest.mark.parametrize(
        "case",
        json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"],
        ids=lambda c: f"{'allow:' if c['allow_rule'] else ''}{c['cmd']!r}",
    )
    def test_recorded_rewrite_still_matches_real_rtk(self, stub_only, case):
        got = self._run_rewrite(
            REAL_RTK, case["cmd"], stub_only.home, stub_only.base, case["allow_rule"]
        )
        assert got == {"rc": case["rc"], "stdout": case["stdout"]}, (
            "real rtk no longer answers as recorded; re-record with "
            "RTK_GOLDEN_REGEN=1 and re-check the hook's assumptions"
        )

    @pytest.mark.skipif(REAL_RTK is None, reason="real rtk not installed")
    @pytest.mark.skipif(not os.environ.get("RTK_GOLDEN_REGEN"), reason="set RTK_GOLDEN_REGEN=1")
    def test_regenerate_golden(self, stub_only):
        version = subprocess.run(
            [str(REAL_RTK), "--version"], env=dict(_CLEAN_ENV), capture_output=True, text=True
        ).stdout.strip()
        cases = []
        for allow_rule, cmds in ((False, self.FIXTURES), (True, self.ALLOW_RULE_FIXTURES)):
            for cmd in cmds:
                got = self._run_rewrite(REAL_RTK, cmd, stub_only.home, stub_only.base, allow_rule)
                cases.append({"cmd": cmd, "allow_rule": allow_rule, **got})
        GOLDEN.parent.mkdir(exist_ok=True)
        payload = {"rtk_version": version, "cases": cases}
        GOLDEN.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

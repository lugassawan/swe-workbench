"""Shared fixture set for hooks/bash_guard.sh's differential acceptance criterion:

  For this fixture set (including the backtick/$(...) vectors bash_guard.sh now closes),
  the verdict produced through the Pi adapter must be identical to the verdict produced by
  invoking the guard script directly with the equivalent Claude-Code-shaped payload.

A single source shared by tests/test_hooks.py (direct invocation) and
tests/test_pi_extension.py (through pi/extensions/guards.ts) — a future change to
hooks/bash_guard.sh's semantics has to update the expectation here, and both suites re-verify
against it, or CI fails on whichever one goes stale.

Each entry is (command, expect_blocked). expect_blocked=True means exit 2 + "BLOCKED" in
stderr directly, or {block: true} through the Pi adapter.

BASH_GUARD_FIXTURES verdicts must hold on every branch in SHARED_FIXTURE_BRANCHES; a verdict
that depends on the current branch belongs in BASH_GUARD_BRANCH_FIXTURES, keyed by branch name.
Both suites run each branch's rows with the guard's cwd set to a committed temp repo on it.
"""

import subprocess
from collections.abc import Mapping
from pathlib import Path

SHARED_FIXTURE_BRANCHES: tuple[str, ...] = ("main", "feature/x")


def make_branch_repo(dest: Path, branch: str, env: Mapping[str, str]) -> Path:
    """A committed temp repo on `branch`, so `git rev-parse --abbrev-ref HEAD` resolves."""
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=dest, env=env, check=True)
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.email=t@t.com",
         "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=dest, env=env, check=True,
    )
    return dest


BASH_GUARD_FIXTURES: list[tuple[str, bool]] = [
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
    # Redirect syntax and empty global-option values must not alter Git argv classification.
    ("git push --force origin main 2>&1", True),
    ("git push --force origin main > /dev/null", True),
    ("git push --force origin main >/dev/null", True),
    ("git push --force origin feature/x 2>&1", False),
    ("git push --force origin feature/x > /dev/null", False),
    ("git push --force origin feature/x >/dev/null", False),
    ("git -C '' push --force origin main", True),
    ('git -C "" push --force origin main', True),
    ("git -C '' push --force origin feature/x", False),
    ('git -C "" push --force origin feature/x', False),
    # Rows below are blocked whatever the current branch is.
    ("X=1 git push --force origin main", True),
    (">/dev/null git push --force origin main", True),
    ("git push --force origin $(echo feature)", True),
    ('git push --force origin "feature/$(date)"', True),
    ("git push $(echo -)f origin main", True),
    ("git push --force --no-follow-tags $(echo origin main)", True),
    ("git commit -m \"$(cat <<'EOT' | sh -s\ngit push --force origin main\nEOT\n)\"", True),
    # Glob and matching refspecs push every ref (a wildcard tag force push over-blocks too);
    # unique-prefix long options spell all/branches/mirror.
    ("git push --force origin 'refs/heads/*:refs/heads/*'", True),
    ("git push --force origin refs/heads/*:refs/heads/*", True),
    ("git push --force origin 'refs/tags/*'", True),
    ("git push -f origin :", True),
    ("git push origin +:", True),
    ("git push origin 'refs/heads/*:refs/heads/*'", False),
    ("git push origin :", False),
    ("git push -f --al origin", True),
    ("git push -f --b origin", True),
    ("git push --branche -f origin", True),
    ("git push --mirro origin", True),
    ("git push --force -Z --al origin", True),
    ("git push -Z --mirro origin", True),
    ("git push --al origin", False),
    ("git push --force-with-lease --al origin", False),
    # eval, ssh and watch re-split their argv into one command line, so a word that holds
    # spaces joins its neighbours (ssh host echo "…push text…" over-blocks the same way).
    ('eval git "push -f" origin main', True),
    ('eval git "push --force" origin main', True),
    ('ssh host "git push" -f origin main', True),
    ('watch git "push -f" origin main', True),
    ('sudo ssh host "git push" -f origin main', True),
    ('ssh host echo "doc git push -f origin main"', True),
    ('eval git "push -f" origin feature/x', False),
    ('ssh host "git push" -f origin feature/x', False),
    ('ssh host "ls -la"', False),
    # An unquoted brace group is expansion the guard cannot evaluate: it is a dynamic word, so a
    # force push using one blocks on every branch (quoted braces and `{}` stay literal).
    ("git push --force origin {main,}", True),
    ("git push {--force,} origin main", True),
    ("git push --force origin {a..b}", True),
    ("git push -f origin feature/{x,y}", True),
    ("git push --force origin {a,{b,c}}", True),
    ("git push origin {main,}", False),
    ("git push --force-with-lease origin {main,}", False),
    ("git push --force origin '{main,}'", False),
    ('git push --force origin "{main,}"', False),
    ("git push --force origin ${BR} feature/x", False),
    ("echo {a,b}", False),
    # A `)` ending a case pattern does not close the enclosing substitution.
    ("echo $(case a in a) git push --force origin main;; esac)", True),
    ("echo $(case a in (a) git push --force origin main;; esac)", True),
    ("echo $(echo $(case a in a) git push -f origin main;; esac))", True),
    ("echo $(case a in a) echo ok;; esac); git push --force origin main", True),
    ("echo $(case a in a) git push --force origin feature/x;; esac)", False),
    ("echo $(case a in a) echo ok;; esac) && echo done", False),
    ("echo $(echo case) done", False),
    # Escaped backticks nest one layer per level (\\, \` and \$ lose one backslash).
    ("echo `echo \\`git push --force origin main\\``", True),
    ("echo `echo \\`echo \\\\\\`git push -f origin main\\\\\\`\\``", True),
    ("echo `echo \\$(git push -f origin main)`", True),
    ("echo `echo \\`git push --force origin feature/x\\``", False),
    ("echo \\`git push --force origin main\\`", False),
    ('echo "\\`git push --force origin main\\`"', False),
    # An unquoted heredoc body is data too, except for the substitutions it expands; a shell
    # reading it as a script still runs it.
    ("cat <<EOF\nit's\nEOF\ngit push --force origin main", True),
    ("cat <<EOF\ngit push --force origin main\nEOF", False),
    ("cat <<-EOF\n\tgit push --force origin main\n\tEOF", False),
    ("cat <<EOF > notes.txt\ngit push --force origin main\nEOF", False),
    ("bash <<EOF\ngit push --force origin main\nEOF", True),
    ("cat <<EOF\n$(git push --force origin main)\nEOF", True),
    ("cat <<EOF\n`git push --force origin main`\nEOF", True),
    ("cat <<EOF\nit's $(git push -f origin main)\nEOF", True),
    ("cat <<EOF\n\\$(git push --force origin main)\nEOF", False),
    ("cat <<EOF\n$(git push --force origin feature/x)\nEOF", False),
    # A `$(cat <<'EOT' ...)` heredoc is code only where its word is run: the command word, a
    # word between a wrapper and git, or a shell's argument. An assignment value or a word
    # after git is data, whatever prefixes the command.
    ('MSG="$(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)"', False),
    ('X=1 git commit -m "$(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)"', False),
    ('rtk git commit -m "$(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)"', False),
    ('X=1 echo "$(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)"', False),
    ('eval "$(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)"', True),
    ('bash -c "$(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)"', True),
    ('sudo $(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)', True),
    ('FOO=1 sudo $(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)', True),
    ('$(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)', True),
    ('if $(cat <<\'EOT\'\ngit push --force origin main\nEOT\n); then :; fi', True),
    ('! $(cat <<\'EOT\'\ngit push --force origin main\nEOT\n)', True),
    # `<<WORD` inside (( )) or ${ } is not a heredoc: the push after it still runs.
    ("(( 1 <<EOT\n)); git push -f origin main\nEOT", True),
    ("(( 1 <<'EOT'\n)); git push -f origin main\nEOT", True),
    ("echo ${x:+a <<EOT\n}; git push -f origin main\nEOT", True),
    # `case` opens a case only as a command word followed by blanks; `case=1` is an assignment, and
    # `if`, `while`, `!` and `time` still leave command position.
    ("git push $(case=1; true) origin main -f", True),
    ("git push $(case-x; true) origin main -f", True),
    ("git push $(if case x in x) true;; esac; then :; fi) origin main -f", True),
    ("git push $(! case x in x) true;; esac) origin main -f", True),
    ("git push $(time case x in x) true;; esac) origin main -f", True),
    # The `cat` heredoc shortcut applies only when `cat` is the whole substitution; a nested
    # `$(cat <<'EOT'…)` is a command word whose output runs.
    ("x=$(echo x; $(cat <<'EOT'\ngit push -f origin main\nEOT\n))", True),
    ("x=$(true && $(cat <<'EOT'\ngit push -f origin main\nEOT\n))", True),
    ("x=$($(cat <<'EOT'\ngit push -f origin main\nEOT\n) --x)", True),
    ("x=$(cat <<'EOT'\ngit push -f origin main\nEOT\n)", False),
    # A current-branch query leading the command can still be a wrapper's name.
    ("$(git branch --show-current) git push -f origin main", True),
    # A word after git is never a shell interpreter, even `.`.
    ("git commit . -m \"$(cat <<'EOT'\nnever run git push --force origin main\nEOT\n)\"", False),
    # A here-string is the script a shell reads, so a `$(cat <<'EOF' ...)` inside it is code;
    # fed to `cat` it is data.
    ("ssh host bash -s <<< \"$(cat <<'EOF'\ncd repo && git push --force origin main\nEOF\n)\"", True),
    ("bash <<< \"$(cat <<'EOF'\ngit push --force origin main\nEOF\n)\"", True),
    ("sudo -u deploy bash <<< \"$(cat <<'EOF'\ngit push --force origin main\nEOF\n)\"", True),
    ("source /dev/stdin <<< \"$(cat <<'EOF'\ngit push --force origin main\nEOF\n)\"", True),
    ("cat <<< \"$(cat <<'EOT'\ngit push --force origin main\nEOT\n)\"", False),
    # A quoted heredoc body in a compound or nested substitution is skipped like any other, so
    # its apostrophe cannot swallow the push after it; the body itself is scanned as code there.
    ("echo $(true; cat <<'EOT'\nit's\nEOT\n); git push -f origin main", True),
    ("echo $(true && cat <<'EOT'\nit's\nEOT\n); git push -f origin main", True),
    ("echo $(\ncat <<'EOT'\nit's\nEOT\n); git push -f origin main", True),
    ("echo $(echo $(cat <<'EOT'\nit's\nEOT\n)); git push -f origin main", True),
    # A substitution flag with another repository selected cannot be attributed to the current branch.
    ("git -C ../other-repo push $(echo --force) origin", True),
    ("git --git-dir=../other/.git push $(echo --force) origin", True),
    # Brace groups after a protected ref read as a possible force flag (a known over-block).
    ("git push origin main {a,b}", True),
    # Push state must not leak between segments: the second push is judged on its own.
    ("git push $(echo x) ; git push --force origin main", True),
    # Quoted text that is data stays allowed.
    ("git commit -m 'document git push --force origin main'", False),
    ("git log --grep='git push --force origin main'", False),
    ("gh pr create --body \"$(cat <<'EOT'\ngit push --force origin main\nEOT\n)\"", False),
    # Dynamic destinations are never expanded to decide a destructive push policy; only a word
    # that is exactly a current-branch query is read as HEAD (see the branch rows).
    ("git push --force origin refs/heads/$(git branch --show-current)", True),
    ("git push --force origin $(git branch --show-current)x", True),
    ("git push --force origin $(git branch --show-current) $(echo main)", True),
    ("git -C other push --force origin $(git branch --show-current)", True),
    ("git push --force-with-lease origin $(git branch --show-current)", False),
    ("git push --force-with-lease origin `git branch --show-current`", False),
    ("bash -c 'git push --force origin main && cd x'", True),
    ("bash -c 'git push --force origin feature/x && cd x'", False),
    ('echo "git push --force origin main && cd x"', False),
    ("eval 'git push --force origin main'", True),
    ("su -c 'git push --force origin main'", True),
    ('ssh host "git push --force origin main"', True),
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
    # Hard resets whose repository cannot be resolved are blocked whatever the current branch is;
    # a soft reset and quoted text are not judged at all.
    ("git -C /nonexistent-swb reset --hard", True),
    ("git -c a=b -C /nonexistent-swb reset --hard", True),
    ("git --no-pager -C /nonexistent-swb reset --hard", True),
    ("git --git-dir=/nonexistent-swb/.git reset --hard", True),
    ('git -C "$(echo x)" reset --hard', True),
    ("GIT_DIR=/x git reset --hard", True),
    ("bash -c 'git -C /nonexistent-swb reset --hard'", True),
    ("git -C /nonexistent-swb reset --soft HEAD~1", False),
    ("echo 'git reset --hard'", False),
    # the subcommand is the first non-option word, so `reset --hard` after another subcommand
    # is data; none of these depend on the branch or on a repository that exists
    ("git commit -m x reset --hard -C /nonexistent-swb", False),
    ("git -C /nonexistent-swb commit -m x reset --hard", False),
    ("git help reset --hard", False),
    # an unknown global option before the subcommand may take it as a value: still judged
    ("git --attr-source HEAD -C /nonexistent-swb reset --hard", True),
    # a force push into a repository that cannot be resolved blocks on any branch
    ("git -C /nonexistent-swb push --force", True),
    # push long options resolve by unique prefix, as git's parse-options does
    ("git push --mirr origin", True),
    # an ambiguous prefix (--force, --force-with-lease, --force-if-includes) is rejected by git
    ("git push --forc origin main", False),
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

# Verdicts that depend on the branch the guard runs on.
BASH_GUARD_BRANCH_FIXTURES: dict[str, list[tuple[str, bool]]] = {
    "main": [
        ("git push origin --force 2>&1", True),
        # a bare substitution first can be the force flag; the destination is then implicit
        ("git push $(echo --force) origin", True),
        ('git push "$(git remote)"', True),
        ("git push $(echo --force) origin feature/x", False),
        # the positional count of one push must not suppress the check on the next
        ("git push origin feature/x ; git push $(echo -f) origin", True),
        # a whole-word current-branch query is the current branch
        ("git push --force origin $(git branch --show-current)", True),
        ('git push --force origin "$(git branch --show-current)"', True),
        ("git push --force origin `git branch --show-current`", True),
        ("git push --force origin $(git rev-parse --abbrev-ref HEAD)", True),
        ("git push --force origin $(git symbolic-ref --short HEAD)", True),
        ("git push --force origin $(rtk git branch --show-current)", True),
        ("git push --force origin $(git branch --show-current 2>/dev/null)", True),
    ],
    "feature/x": [
        ("git push origin --force 2>&1", False),
        ("git push $(echo --force) origin", False),
        ('git push "$(git remote)"', False),
        ("git push $(echo --force) origin feature/x", False),
        ("git push origin feature/x ; git push $(echo -f) origin", False),
        ("git push --force origin $(git branch --show-current)", False),
        ('git push --force origin "$(git branch --show-current)"', False),
        ("git push --force origin `git branch --show-current`", False),
        ("git push --force origin $(git rev-parse --abbrev-ref HEAD)", False),
        ("git push --force origin $(git symbolic-ref --short HEAD)", False),
        ("git push --force origin $(rtk git branch --show-current)", False),
        ("git push --force origin $(git branch --show-current 2>/dev/null)", False),
    ],
}

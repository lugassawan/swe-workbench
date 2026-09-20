"""
Regression tests for resume of merged-but-untagged releases (issue #695).

A release stranded between PR merge and tag publication must be finished by
a re-run; transient git/gh transport failures must retry boundedly instead
of aborting the release mid-flight.
"""

import re
import subprocess
import textwrap
from pathlib import Path

from conftest import _CLEAN_ENV

RELEASE_SH = Path(__file__).parent.parent / "scripts" / "release.sh"


def _script_lines() -> list[str]:
    return RELEASE_SH.read_text().splitlines()


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _write_stub(stub_dir: Path, name: str, body: str) -> None:
    stub = stub_dir / name
    stub.write_text(f"#!/bin/sh\n{body}\n")
    stub.chmod(0o755)


def _run_snippet(
    snippet: str,
    stub_dir: Path,
    extra_env: dict | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run a bash snippet under stubbed PATH.

    Snippets that read repo-relative files (.version-bump.json) or whose
    stubs write relative artifacts (push_log) must pass cwd= explicitly —
    bash -c otherwise inherits the pytest process cwd.
    """
    env = {**_CLEAN_ENV, "PATH": f"{stub_dir}:{_CLEAN_ENV.get('PATH', '')}"}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        cwd=cwd,
    )


def _extract_functions(*names: str) -> str:
    """Extract named top-level bash functions from release.sh verbatim.

    Dynamic snippets are assembled from the REAL shipped bodies — a copied
    snippet would drift from the script while the tests stay green (a drift
    both Phase-4 reviewers flagged on the original copy-paste seam).
    """
    lines = RELEASE_SH.read_text().splitlines()
    blocks = []
    for name in names:
        start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{name}()"))
        end = next(i for i in range(start, len(lines)) if lines[i] == "}")
        blocks.append("\n".join(lines[start : end + 1]))
    return "\n".join(blocks)


def _extract_resume_wiring() -> str:
    """Extract the top-level discovery wiring between its section markers."""
    text = RELEASE_SH.read_text()
    start = text.index("# ── Resume unfinished releases")
    end = text.index("# ── Compute next version")
    return text[start:end].rstrip()


_RETRY_SNIPPET = "\n".join(
    [
        "set -euo pipefail",
        _extract_functions("retry_transport"),
        'retry_transport 3 "git fetch" git fetch origin',
    ]
)


class TestRetryTransportStatic:
    def test_retry_transport_defined(self):
        assert any(
            ln.startswith("retry_transport()")
            for ln in _script_lines()
            if not _is_comment(ln)
        ), "retry_transport() function definition not found"

    def test_transport_ops_are_wrapped(self):
        """fetch, both pulls, and the tag push must run via retry_transport."""
        lines = [ln for ln in _script_lines() if not _is_comment(ln)]
        for pattern in (
            r"retry_transport\s+\d+\s+\"git fetch[^\"]*\"\s+git fetch\b",
            r"retry_transport\s+\d+\s+\"git pull[^\"]*\"\s+git pull --ff-only\b",
            r"retry_transport\s+\d+\s+\"branch push[^\"]*\"\s+git push\b",
            r"retry_transport\s+\d+\s+\"tag push[^\"]*\"\s+git push\b",
        ):
            assert any(
                re.search(pattern, ln) for ln in lines
            ), f"No line matches required wrapper pattern: {pattern}"

    def test_git_pull_always_wrapped(self):
        """Every executable 'git pull --ff-only' runs via retry_transport, and
        no echo'd guidance teaches a manual pull recipe."""
        for ln in _script_lines():
            if _is_comment(ln) or "git pull --ff-only" not in ln:
                continue
            if "echo " in ln:
                raise AssertionError(
                    f"Guidance teaches a manual pull recipe: {ln.strip()!r}"
                )
            assert re.search(
                r"retry_transport\s+\d+\s+\"git pull[^\"]*\"\s+git pull --ff-only", ln
            ), f"Bare 'git pull --ff-only' outside retry_transport: {ln.strip()!r}"


_RESUME_SNIPPET = "\n".join(
    [
        "set -euo pipefail",
        'GH_REPO="owner/repo"',
        'RESUME_TAG="v9.9.9"',
        _extract_functions("retry_transport", "resume_release"),
        'resume_release "$RESUME_TAG"',
    ]
)


_PR_JSON_OK = (
    '{"number":694,"headRefName":"chore/bump-v9.9.9","mergeCommit":{"oid":"c9035a0"}}'
)


def _resume_env(
    tmp_path: Path,
    gh_body: str,
    git_body: str,
) -> None:
    """Wire gh/git stubs for the extracted resume_release snippet.

    The git stub must be path-aware: resume reads BOTH the manifest list
    (.version-bump.json) and each declared manifest at the merge SHA via
    `git show <sha>:<path>`.
    """
    _write_stub(tmp_path, "gh", gh_body)
    _write_stub(tmp_path, "git", git_body)


def _gh_stub(pr_list_json: str, rollup: str = '{"statusCheckRollup":[]}') -> str:
    # Honors --jq by piping through real jq — the snippet consumes the same
    # filtered shape real gh emits.
    return textwrap.dedent(
        f"""\
        prog=""
        prev=""
        for a in "$@"; do
          if [ "$prev" = "--jq" ]; then prog=$a; fi
          prev=$a
        done
        if [ "$1" = "pr" ] && [ "$2" = "list" ]; then printf '[%s]' '{pr_list_json}' | jq -r "$prog"; exit $?; fi
        if [ "$1" = "pr" ] && [ "$2" = "view" ]; then printf '%s' '{rollup}' | jq -r "$prog"; exit $?; fi
        exit 0
    """
    )


def _git_stub_ok(tmp_path: Path, manifest_json: str = '{"version":"9.9.9"}') -> str:
    return textwrap.dedent(
        f"""\
        case "$1" in
          merge-base) exit 0 ;;
          show)
            case "$2" in
              *.version-bump.json) printf '%s' '{{"files":[{{"path":".claude-plugin/plugin.json","field":".version"}}]}}' ;;
              *) printf '%s' '{manifest_json}' ;;
            esac ;;
          ls-remote) printf '' ;;
          rev-parse) exit 1 ;;
          tag|push) printf '%s\\n' "$*" >> push_log ;;
        esac
        exit 0
    """
    )


class TestResumeStatic:
    def test_resume_flag_usage_documented(self):
        assert any(
            "--resume vX.Y.Z" in ln and not _is_comment(ln) for ln in _script_lines()
        ), "usage text does not document --resume"

    def test_resume_flag_validated(self):
        assert any(
            re.search(r"RESUME_TAG.*=~.*\^v\[0-9\]", ln) and not _is_comment(ln)
            for ln in _script_lines()
        ), "--resume argument is not regex-validated against vX.Y.Z"

    def test_no_verify_appears_exactly_once_on_resume_push(self):
        hits = [
            ln.strip()
            for ln in _script_lines()
            if "--no-verify" in ln and not _is_comment(ln)
        ]
        assert len(hits) == 1, f"expected exactly 1 --no-verify line, got {hits}"
        assert (
            '"tag push"' in hits[0] and "git push --no-verify" in hits[0]
        ), "--no-verify must live on the resume-path tag push only"


class TestResumeDynamic:
    def test_happy_path_pushes_with_no_verify(self, tmp_path):
        """Verified tuple -> tag pushed with --no-verify (CI already validated the tree)."""
        _resume_env(tmp_path, _gh_stub(_PR_JSON_OK), _git_stub_ok(tmp_path))
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        push_log = (tmp_path / "push_log").read_text()
        assert "--no-verify" in push_log, f"push args: {push_log!r}"

    def test_no_merged_pr_fails_closed(self, tmp_path):
        _resume_env(tmp_path, _gh_stub("null"), _git_stub_ok(tmp_path))
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "no merged PR found" in result.stderr

    def test_mergecommit_null_fails_closed(self, tmp_path):
        """A merged PR without a merge commit oid must not be resumable."""
        _resume_env(
            tmp_path,
            _gh_stub(
                '{"number":694,"headRefName":"chore/bump-v9.9.9","mergeCommit":null}'
            ),
            _git_stub_ok(tmp_path),
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "no merge commit" in result.stderr

    def test_merge_sha_not_on_main_fails_closed(self, tmp_path):
        git_body = _git_stub_ok(tmp_path).replace(
            "merge-base) exit 0", "merge-base) exit 1"
        )
        _resume_env(tmp_path, _gh_stub(_PR_JSON_OK), git_body)
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "not reachable from origin/main" in result.stderr

    def test_failed_ci_checks_fail_closed(self, tmp_path):
        """A PR merged over red CI must not take the --no-verify shortcut."""
        _resume_env(
            tmp_path,
            _gh_stub(
                _PR_JSON_OK, rollup='{"statusCheckRollup":[{"conclusion":"FAILURE"}]}'
            ),
            _git_stub_ok(tmp_path),
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "failed CI checks" in result.stderr
        assert not (tmp_path / "push_log").exists()

    def test_timed_out_ci_check_fails_closed(self, tmp_path):
        """Non-FAILURE terminal conclusions (TIMED_OUT, CANCELLED) must not
        pass the CI gate — the fresh path treats cancel as failing too."""
        _resume_env(
            tmp_path,
            _gh_stub(
                _PR_JSON_OK,
                rollup='{"statusCheckRollup":[{"conclusion":"TIMED_OUT"}]}',
            ),
            _git_stub_ok(tmp_path),
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "failed CI checks" in result.stderr

    def test_manifest_list_unreadable_at_sha_fails_closed(self, tmp_path):
        """.version-bump.json itself missing at the merge SHA must fail loudly,
        not silently skip the manifest verification (fail-open guard)."""
        git_body = _git_stub_ok(tmp_path).replace(
            """*.version-bump.json) printf '%s' '{"files":[{"path":".claude-plugin/plugin.json","field":".version"}]}' ;;""",
            '*.version-bump.json) echo "fatal: not found" >&2; exit 128 ;;',
        )
        assert "exit 128" in git_body, "stub arm replacement failed to apply"
        _resume_env(tmp_path, _gh_stub(_PR_JSON_OK), git_body)
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "refusing to skip manifest verification" in result.stderr

    def test_manifest_mismatch_fails_closed(self, tmp_path):
        _resume_env(
            tmp_path,
            _gh_stub(_PR_JSON_OK),
            _git_stub_ok(tmp_path, manifest_json='{"version":"9.9.8"}'),
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "expected '9.9.9'" in result.stderr

    def test_tag_already_published_is_success_no_push(self, tmp_path):
        git_body = _git_stub_ok(tmp_path).replace(
            "ls-remote) printf ''",
            "ls-remote) printf 'c9035a0\\trefs/tags/v9.9.9\\nc9035a0\\trefs/tags/v9.9.9^{}\\n'",
        )
        _resume_env(tmp_path, _gh_stub(_PR_JSON_OK), git_body)
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "already published" in result.stdout
        assert not (
            tmp_path / "push_log"
        ).exists(), "must not push when the tag is already published"

    def test_stderr_noise_on_success_does_not_pollute_tag_lookup(self, tmp_path):
        """A successful ls-remote that also writes an ssh warning to stderr
        must not corrupt the parsed tag state (false refusal / phantom tag)."""
        git_body = _git_stub_ok(tmp_path).replace(
            "ls-remote) printf ''",
            "ls-remote) printf 'ssh: Warning: Permanently added host\\n' >&2; printf ''",
        )
        _resume_env(tmp_path, _gh_stub(_PR_JSON_OK), git_body)
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        push_log = (tmp_path / "push_log").read_text()
        assert (
            "--no-verify" in push_log
        ), "stderr noise on a successful lookup must not be parsed as tag state"

    def test_remote_tag_wrong_sha_fails_closed(self, tmp_path):
        git_body = _git_stub_ok(tmp_path).replace(
            "ls-remote) printf ''",
            "ls-remote) printf 'deadbeef\\trefs/tags/v9.9.9\\ndeadbeef\\trefs/tags/v9.9.9^{}\\n'",
        )
        _resume_env(tmp_path, _gh_stub(_PR_JSON_OK), git_body)
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "not merge commit" in result.stderr


class TestRetryTransportDynamic:
    def test_transient_then_success(self, tmp_path):
        """git fails twice then succeeds → exit 0, three attempts recorded."""
        _write_stub(
            tmp_path,
            "git",
            textwrap.dedent(f"""\
            COUNT=$(cat {tmp_path}/count 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {tmp_path}/count
            [ "$COUNT" -ge 3 ] && exit 0
            exit 128
        """),
        )
        _write_stub(tmp_path, "sleep", "exit 0")
        result = _run_snippet(_RETRY_SNIPPET, tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert (tmp_path / "count").read_text().strip() == "3"

    def test_persistent_failure_caps_out(self, tmp_path):
        _write_stub(
            tmp_path,
            "git",
            'echo "fatal: Could not read from remote repository." >&2; exit 128',
        )
        _write_stub(
            tmp_path,
            "sleep",
            textwrap.dedent(f"""\
            COUNT=$(cat {tmp_path}/sleeps 2>/dev/null || echo 0)
            COUNT=$((COUNT + 1))
            printf '%d\\n' "$COUNT" > {tmp_path}/sleeps
            exit 0
        """),
        )
        result = _run_snippet(_RETRY_SNIPPET, tmp_path)
        assert result.returncode == 1
        assert "transient failure cap reached" in result.stderr
        assert result.stderr.count("Could not read from remote repository") == 1, (
            "the underlying error must be surfaced exactly once (at the cap), "
            "not leaked on every transient attempt nor swallowed entirely"
        )
        assert (
            (tmp_path / "sleeps").read_text().strip() == "2"
        ), "cap(3) allows 2 sleeps, then the 3rd failure aborts"


# The exact gh --jq program used by discovery; a static test pins the script
# copy to this string so the two cannot drift.
_DISCOVERY_JQ = (
    '.[] | select(.headRefName | test("^chore/bump-v[0-9]+[.][0-9]+[.][0-9]+$")) '
    '| select(.mergeCommit.oid != null and .mergeCommit.oid != "") '
    '| [(.headRefName | sub("^chore/bump-"; "")), (.number | tostring), .mergeCommit.oid] | @tsv'
)

_DISCOVERY_SNIPPET = "\n".join(
    [
        "set -euo pipefail",
        _extract_functions(
            "retry_transport", "discover_untagged_releases", "resume_release"
        ),
        # Override resume_release with a logging stub so the wiring test
        # exercises the discovery DECISIONS; tuple verification has its own
        # extracted-body tests in TestResumeDynamic.
        "resume_release() { printf 'resume %s\\n' \"$1\" >> discovery_log; }",
        _extract_resume_wiring(),
        'echo "No unfinished releases — starting a fresh one."',
        "exit 0",
    ]
)

_MERGED_PRS_JSON = """[
  {"number": 691, "headRefName": "chore/bump-v9.9.8", "mergeCommit": {"oid": "59c9208"}},
  {"number": 694, "headRefName": "chore/bump-v9.9.9", "mergeCommit": {"oid": "c9035a0"}},
  {"number": 690, "headRefName": "chore/close-umbrella", "mergeCommit": {"oid": "c7fed0e"}}
]"""


class TestDiscoveryStatic:
    def test_discovery_precedes_version_computation(self):
        lines = _script_lines()
        compute_idx = next(
            i for i, ln in enumerate(lines) if "Compute next version" in ln
        )
        discovery_idx = next(
            i for i, ln in enumerate(lines) if "discover_untagged_releases() {" in ln
        )
        wiring_idx = next(
            i
            for i, ln in enumerate(lines)
            if i > discovery_idx
            and "discover_untagged_releases" in ln
            and "()" not in ln
            and not _is_comment(ln)
        )
        assert (
            wiring_idx < compute_idx
        ), "discovery wiring must run before the 'Compute next version' section"

    def test_discovery_jq_program_pinned(self):
        """The full --jq program must appear verbatim (single line) in the script."""
        assert any(
            _DISCOVERY_JQ in ln for ln in _script_lines()
        ), "release.sh discovery --jq program drifted from the pinned test copy"

    def test_pr_list_window_covers_stranded_releases(self):
        """Both merged-PR lookups must use --limit 100 — a stranded release is
        exactly the PR most likely to have fallen out of a busy merge window."""
        wrapped = [
            ln
            for ln in _script_lines()
            if not _is_comment(ln)
            and "gh pr list" in ln
            and "--state merged" in ln
            and "--limit 100" in ln
        ]
        assert (
            len(wrapped) == 2
        ), f"expected 2 merged-PR lookups with --limit 100, found {len(wrapped)}: {wrapped}"

    def test_resume_reads_manifest_list_at_merge_sha(self):
        assert any(
            'git show "${merge_sha}:.version-bump.json"' in ln and not _is_comment(ln)
            for ln in _script_lines()
        ), "manifest list must be read at the merge SHA, not the working tree"

    def test_ambiguity_guard_requires_resume(self):
        assert any(
            "multiple merged-but-untagged releases" in ln and not _is_comment(ln)
            for ln in _script_lines()
        )


class TestDiscoveryDynamic:
    def _make_stubs(self, tmp_path: Path, tagged: list[str]) -> None:
        # gh stub honors --jq by piping the sample JSON through real jq, so the
        # snippet consumes genuinely filtered TSV, the shape real gh emits.
        _write_stub(
            tmp_path,
            "gh",
            textwrap.dedent("""\
            if [ "$1" = "pr" ] && [ "$2" = "list" ]; then
              prog=""
              prev=""
              for a in "$@"; do
                if [ "$prev" = "--jq" ]; then prog=$a; fi
                prev=$a
              done
              printf '%s' "$MERGED_PRS_JSON" | jq -r "$prog"
              exit $?
            fi
            exit 0
        """),
        )
        _write_stub(
            tmp_path,
            "git",
            textwrap.dedent("""\
            if [ "$1" = "ls-remote" ]; then
              for t in TAGGED_LIST; do
                case "$*" in *"$t"*) printf '%s\\t%s\\n' "sha-$t" "$t"; exit 0 ;; esac
              done
              exit 0
            fi
            exit 0
        """).replace("TAGGED_LIST", " ".join(tagged)),
        )
        _write_stub(tmp_path, "sleep", "exit 0")

    def test_single_untagged_auto_resumes(self, tmp_path):
        self._make_stubs(tmp_path, tagged=["refs/tags/v9.9.8"])
        result = _run_snippet(
            _DISCOVERY_SNIPPET,
            tmp_path,
            {"MERGED_PRS_JSON": _MERGED_PRS_JSON},
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Found unfinished release v9.9.9" in result.stdout
        assert (tmp_path / "discovery_log").read_text() == "resume v9.9.9\n"

    def test_stderr_noise_on_success_does_not_defeat_discovery(self, tmp_path):
        """gh succeeding while printing a warning must still surface the
        untagged candidate — merged stderr would read as a phantom tag."""
        self._make_stubs(tmp_path, tagged=["refs/tags/v9.9.8"])
        gh = tmp_path / "gh"
        gh.write_text(
            gh.read_text().replace(
                'jq -r "$prog"',
                'jq -r "$prog" 2>/dev/null; printf "ssh: Warning\\n" >&2',
            )
        )
        assert "ssh: Warning" in gh.read_text(), "stub noise injection failed to apply"
        result = _run_snippet(
            _DISCOVERY_SNIPPET,
            tmp_path,
            {"MERGED_PRS_JSON": _MERGED_PRS_JSON},
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert (tmp_path / "discovery_log").read_text() == "resume v9.9.9\n"

    def test_two_stacked_refuse_and_list(self, tmp_path):
        self._make_stubs(tmp_path, tagged=[])
        result = _run_snippet(
            _DISCOVERY_SNIPPET,
            tmp_path,
            {"MERGED_PRS_JSON": _MERGED_PRS_JSON},
            cwd=tmp_path,
        )
        assert result.returncode == 1
        assert "multiple merged-but-untagged releases" in result.stderr
        assert "v9.9.8" in result.stderr and "v9.9.9" in result.stderr
        assert "--resume" in result.stderr

    def test_all_tagged_fresh_release(self, tmp_path):
        self._make_stubs(tmp_path, tagged=["refs/tags/v9.9.8", "refs/tags/v9.9.9"])
        result = _run_snippet(
            _DISCOVERY_SNIPPET,
            tmp_path,
            {"MERGED_PRS_JSON": _MERGED_PRS_JSON},
            cwd=tmp_path,
        )
        assert result.returncode == 0
        assert "No unfinished releases" in result.stdout

    def test_non_bump_prs_ignored(self, tmp_path):
        """headRefName without the chore/bump-vX.Y.Z shape is not a candidate."""
        self._make_stubs(tmp_path, tagged=[])
        result = _run_snippet(
            _DISCOVERY_SNIPPET,
            tmp_path,
            {
                "MERGED_PRS_JSON": (
                    '[{"number": 690, "headRefName": "chore/close-umbrella", '
                    '"mergeCommit": {"oid": "c7fed0e"}}]'
                )
            },
            cwd=tmp_path,
        )
        assert result.returncode == 0
        assert "No unfinished releases" in result.stdout

    def test_discovery_jq_program_filters_correctly(self):
        """The pinned jq program emits exactly the bump rows as TSV."""
        proc = subprocess.run(
            ["jq", "-r", _DISCOVERY_JQ],
            input=_MERGED_PRS_JSON,
            capture_output=True,
            text=True,
            env=dict(_CLEAN_ENV),
        )
        assert proc.returncode == 0, proc.stderr
        rows = [ln for ln in proc.stdout.splitlines() if ln]
        assert rows == [
            "v9.9.8\t691\t59c9208",
            "v9.9.9\t694\tc9035a0",
        ]


class TestFailurePathMessaging:
    def test_no_manual_tag_recipe_in_guidance(self):
        """Echo'd guidance must not teach manual `git tag -a` — recovery goes
        through --resume, which verifies the tuple instead of trusting the
        operator's local state."""
        for ln in _script_lines():
            if _is_comment(ln) or "echo" not in ln:
                continue
            assert (
                "git tag -a" not in ln
            ), f"Guidance still teaches manual tagging: {ln.strip()!r}"

    def test_ci_failure_paths_advertise_resume(self):
        """Every 'Once CI passes' guidance must offer the --resume path."""
        resume_lines = [
            ln for ln in _script_lines() if not _is_comment(ln) and "--resume" in ln
        ]
        assert len(resume_lines) >= 4, (
            "expected --resume advertised in usage + >=3 failure paths, "
            f"found {len(resume_lines)}: {[ln.strip() for l in resume_lines]}"
        )

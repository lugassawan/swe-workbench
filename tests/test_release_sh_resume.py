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


_RETRY_SNIPPET = textwrap.dedent("""\
    set -euo pipefail
    retry_transport() {
      local max_attempts=$1 desc=$2
      shift 2
      local attempt=0
      while true; do
        if "$@"; then
          return 0
        fi
        attempt=$((attempt + 1))
        if [[ "$attempt" -ge "$max_attempts" ]]; then
          echo "Error: ${desc} failed after ${attempt} attempts (transient failure cap reached)." >&2
          echo "  Re-run this script — it resumes the unfinished release." >&2
          return 1
        fi
        echo "[$(date '+%H:%M:%S')] ${desc} transient failure (attempt ${attempt}/${max_attempts}); retrying in 10s..." >&2
        sleep 10
      done
    }
    retry_transport 3 "git fetch" git fetch origin
""")


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
        """Every executable 'git pull --ff-only' runs via retry_transport.

        Echo'd guidance strings may mention git pull — they are recipes the
        operator runs by hand, not transport ops this script executes. Task 4
        replaces that guidance with --resume and guards it separately.
        """
        for ln in _script_lines():
            if _is_comment(ln) or "git pull --ff-only" not in ln:
                continue
            if "echo " in ln:
                continue
            assert re.search(
                r"retry_transport\s+\d+\s+\"git pull[^\"]*\"\s+git pull --ff-only", ln
            ), f"Bare 'git pull --ff-only' outside retry_transport: {ln.strip()!r}"


_RESUME_SNIPPET = textwrap.dedent("""\
    set -euo pipefail
    GH_REPO="owner/repo"
    RESUME_TAG="v0.1.36"
    retry_transport() {
      local max_attempts=$1 desc=$2
      shift 2
      local attempt=0
      while true; do
        if "$@"; then
          return 0
        fi
        attempt=$((attempt + 1))
        if [[ "$attempt" -ge "$max_attempts" ]]; then
          echo "Error: ${desc} failed after ${attempt} attempts." >&2
          return 1
        fi
        sleep 10
      done
    }
    resume_release() {
      local tag=$1
      local ver=${tag#v}
      local branch="chore/bump-${tag}"
      echo "Resuming release ${tag}..."
      local pr_json
      pr_json=$(retry_transport 5 "gh pr list (${branch})" \\
        gh pr list --state merged --limit 20 \\
          --json number,headRefName,mergeCommit \\
          --jq "[.[] | select(.headRefName == \\"${branch}\\")][0]") || return 1
      if [[ -z "$pr_json" || "$pr_json" == "null" ]]; then
        echo "Error: no merged PR found for branch '${branch}'." >&2
        return 1
      fi
      local pr_num merge_sha
      pr_num=$(printf '%s' "$pr_json" | jq -r '.number')
      merge_sha=$(printf '%s' "$pr_json" | jq -r '.mergeCommit.oid')
      if ! git merge-base --is-ancestor "$merge_sha" origin/main; then
        echo "Error: merge SHA ${merge_sha} of PR #${pr_num} is not reachable from origin/main." >&2
        return 1
      fi
      while IFS=$'\\t' read -r path field; do
        local at_sha
        at_sha=$(git show "${merge_sha}:${path}" | jq -r "$field")
        if [[ "$at_sha" != "$ver" ]]; then
          echo "Error: ${path} at ${merge_sha} reports '${at_sha}', expected '${ver}'." >&2
          return 1
        fi
      done < <(jq -r '.files[] | [.path, .field] | @tsv' .version-bump.json)
      local remote_tag remote_tag_commit
      remote_tag=$(retry_transport 5 "tag lookup ${tag}" \\
        git ls-remote --tags origin "refs/tags/${tag}" "refs/tags/${tag}^{}") || return 1
      remote_tag_commit=$(printf '%s' "$remote_tag" | grep '\\^{}' | awk '{print $1}' || true)
      [[ -z "$remote_tag_commit" ]] && remote_tag_commit=$(printf '%s' "$remote_tag" | awk '{print $1}' | head -1)
      if [[ -n "$remote_tag_commit" ]]; then
        if [[ "$remote_tag_commit" != "$merge_sha" ]]; then
          echo "Error: remote tag ${tag} points to ${remote_tag_commit}, not merge commit ${merge_sha}." >&2
          return 1
        fi
        echo "Tag ${tag} already published at ${merge_sha} — nothing to do."
        return 0
      fi
      if ! git rev-parse -q --verify "refs/tags/${tag}" >/dev/null 2>&1; then
        git tag -a "$tag" -m "Release ${tag}" "$merge_sha"
      elif [[ "$(git rev-parse "${tag}^{commit}")" == "$merge_sha" ]]; then
        echo "Tag ${tag} exists locally at ${merge_sha} — pushing."
      else
        echo "Error: local tag ${tag} points elsewhere." >&2
        return 1
      fi
      retry_transport 5 "tag push" git push --no-verify origin "$tag"
      echo "Resumed release complete!"
      return 0
    }
    resume_release "$RESUME_TAG"
""")


def _resume_env(tmp_path: Path, gh_body: str, git_body: str) -> None:
    _write_stub(tmp_path, "gh", gh_body)
    _write_stub(tmp_path, "git", git_body)
    (tmp_path / ".version-bump.json").write_text(
        '{"files":[{"path":".claude-plugin/plugin.json","field":".version"}]}'
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
        assert re.search(
            r"git push --no-verify", hits[0]
        ), "--no-verify must live on the resume-path tag push"


class TestResumeDynamic:
    def test_happy_path_pushes_with_no_verify(self, tmp_path):
        """Verified tuple → tag pushed with --no-verify (CI already validated the tree)."""
        _resume_env(
            tmp_path,
            'if [ "$1" = "pr" ]; then printf \'{"number":694,"headRefName":"chore/bump-v0.1.36","mergeCommit":{"oid":"c9035a0"}}\'; fi',
            textwrap.dedent("""\
            case "$1" in
              merge-base) exit 0 ;;
              show) printf '{"version":"0.1.36"}' ;;
              ls-remote) printf '' ;;
              rev-parse) exit 1 ;;
              tag|push) printf '%s\\n' "$*" >> push_log ;;
            esac
            exit 0
        """),
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        push_log = (tmp_path / "push_log").read_text()
        assert "--no-verify" in push_log, f"push args: {push_log!r}"

    def test_no_merged_pr_fails_closed(self, tmp_path):
        _resume_env(
            tmp_path,
            'if [ "$1" = "pr" ]; then printf "null"; fi',
            "exit 0",
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "no merged PR found" in result.stderr

    def test_merge_sha_not_on_main_fails_closed(self, tmp_path):
        _resume_env(
            tmp_path,
            'if [ "$1" = "pr" ]; then printf \'{"number":694,"headRefName":"chore/bump-v0.1.36","mergeCommit":{"oid":"c9035a0"}}\'; fi',
            'case "$1" in merge-base) exit 1 ;; *) exit 0 ;; esac',
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "not reachable from origin/main" in result.stderr

    def test_manifest_mismatch_fails_closed(self, tmp_path):
        _resume_env(
            tmp_path,
            'if [ "$1" = "pr" ]; then printf \'{"number":694,"headRefName":"chore/bump-v0.1.36","mergeCommit":{"oid":"c9035a0"}}\'; fi',
            textwrap.dedent("""\
            case "$1" in
              merge-base) exit 0 ;;
              show) printf '{"version":"0.1.35"}' ;;
              *) exit 0 ;;
            esac
        """),
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 1
        assert "expected '0.1.36'" in result.stderr

    def test_tag_already_published_is_success_no_push(self, tmp_path):
        _resume_env(
            tmp_path,
            'if [ "$1" = "pr" ]; then printf \'{"number":694,"headRefName":"chore/bump-v0.1.36","mergeCommit":{"oid":"c9035a0"}}\'; fi',
            textwrap.dedent("""\
            case "$1" in
              merge-base) exit 0 ;;
              show) printf '{"version":"0.1.36"}' ;;
              ls-remote) printf 'c9035a0\\trefs/tags/v0.1.36\\nc9035a0\\trefs/tags/v0.1.36^{}\\n' ;;
              *) exit 0 ;;
            esac
        """),
        )
        result = _run_snippet(_RESUME_SNIPPET, tmp_path, cwd=tmp_path)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "already published" in result.stdout
        assert not (
            tmp_path / "push_log"
        ).exists(), "must not push when the tag is already published"

    def test_remote_tag_wrong_sha_fails_closed(self, tmp_path):
        _resume_env(
            tmp_path,
            'if [ "$1" = "pr" ]; then printf \'{"number":694,"headRefName":"chore/bump-v0.1.36","mergeCommit":{"oid":"c9035a0"}}\'; fi',
            textwrap.dedent("""\
            case "$1" in
              merge-base) exit 0 ;;
              show) printf '{"version":"0.1.36"}' ;;
              ls-remote) printf 'deadbeef\\trefs/tags/v0.1.36\\ndeadbeef\\trefs/tags/v0.1.36^{}\\n' ;;
              *) exit 0 ;;
            esac
        """),
        )
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
        _write_stub(tmp_path, "git", "exit 128")
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
        assert (
            (tmp_path / "sleeps").read_text().strip() == "2"
        ), "cap(3) allows 2 sleeps, then the 3rd failure aborts"


# The exact gh --jq program used by discovery. Duplicated here so the tests
# exercise the real filter; a static test below pins the copy in release.sh
# to this string so the two cannot drift.
_DISCOVERY_JQ = (
    '.[] | select(.headRefName | test("^chore/bump-v[0-9]+[.][0-9]+[.][0-9]+$")) '
    '| select(.mergeCommit.oid != null and .mergeCommit.oid != "") '
    '| [(.headRefName | sub("^chore/bump-"; "")), (.number | tostring), .mergeCommit.oid] | @tsv'
)

_DISCOVERY_SNIPPET = textwrap.dedent("""\
    set -euo pipefail
    retry_transport() {
      local max_attempts=$1 desc=$2
      shift 2
      local attempt=0
      while true; do
        if "$@"; then
          return 0
        fi
        attempt=$((attempt + 1))
        if [[ "$attempt" -ge "$max_attempts" ]]; then
          return 1
        fi
        sleep 10
      done
    }
    discover_untagged_releases() {
      local merged_prs ver num sha tag_out
      merged_prs=$(retry_transport 5 "gh pr list" \\
        gh pr list --state merged --limit 20 \\
          --json number,headRefName,mergeCommit \\
          --jq '__DISCOVERY_JQ__') || return 1
      while IFS=$'\\t' read -r ver num sha; do
        [[ -n "$ver" ]] || continue
        tag_out=$(retry_transport 5 "tag lookup ${ver}" \\
          git ls-remote --tags origin "refs/tags/${ver}") || return 1
        if [[ -z "$tag_out" ]]; then
          printf '%s\\t%s\\t%s\\n' "$ver" "$num" "$sha"
        fi
      done <<<"$merged_prs"
    }
    UNTAGGED=$(discover_untagged_releases) || { echo "Error: could not query GitHub for unfinished releases." >&2; exit 1; }
    UNTAGGED_COUNT=0
    if [[ -n "$UNTAGGED" ]]; then
      UNTAGGED_COUNT=$(printf '%s\\n' "$UNTAGGED" | grep -c .)
    fi
    if [[ "$UNTAGGED_COUNT" -ge 2 ]]; then
      echo "Error: multiple merged-but-untagged releases found — refusing to guess." >&2
      printf '%s\\n' "$UNTAGGED" | while IFS=$'\\t' read -r ver num sha; do
        echo "  ${ver}  PR #${num}  ${sha}" >&2
      done
      echo "Finish one explicitly with: release.sh --resume vX.Y.Z" >&2
      exit 1
    elif [[ "$UNTAGGED_COUNT" -eq 1 ]]; then
      RESUME_TAG=$(printf '%s\\n' "$UNTAGGED" | head -1 | cut -f1)
      echo "Found unfinished release ${RESUME_TAG} — resuming before starting a new release."
      printf 'resume %s\\n' "$RESUME_TAG" >> discovery_log
      exit 0
    fi
    echo "No unfinished releases — starting a fresh one."
    exit 0
""").replace("__DISCOVERY_JQ__", _DISCOVERY_JQ)

_MERGED_PRS_JSON = """[
  {"number": 691, "headRefName": "chore/bump-v0.1.35", "mergeCommit": {"oid": "59c9208"}},
  {"number": 694, "headRefName": "chore/bump-v0.1.36", "mergeCommit": {"oid": "c9035a0"}},
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
        assert any(
            _DISCOVERY_JQ.split("| select(.mergeCommit")[0].rstrip() in ln
            for ln in _script_lines()
        ), "release.sh discovery --jq program drifted from the pinned test copy"

    def test_ambiguity_guard_requires_resume(self):
        assert any(
            "multiple merged-but-untagged releases" in ln and not _is_comment(ln)
            for ln in _script_lines()
        )


class TestDiscoveryDynamic:
    def _make_stubs(self, tmp_path: Path, tagged: list[str]) -> None:
        # The gh stub honors --jq by piping the sample JSON through real jq,
        # so the snippet's post-processing sees genuinely filtered TSV — the
        # same shape real gh emits.
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
        self._make_stubs(tmp_path, tagged=["refs/tags/v0.1.35"])
        result = _run_snippet(
            _DISCOVERY_SNIPPET,
            tmp_path,
            {"MERGED_PRS_JSON": _MERGED_PRS_JSON},
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Found unfinished release v0.1.36" in result.stdout
        assert (tmp_path / "discovery_log").read_text() == "resume v0.1.36\n"

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
        assert "v0.1.35" in result.stderr and "v0.1.36" in result.stderr
        assert "--resume" in result.stderr

    def test_all_tagged_fresh_release(self, tmp_path):
        self._make_stubs(tmp_path, tagged=["refs/tags/v0.1.35", "refs/tags/v0.1.36"])
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
            "v0.1.35\t691\t59c9208",
            "v0.1.36\t694\tc9035a0",
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

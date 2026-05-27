"""Guard: every CI job must declare timeout-minutes; pr.yml must have a concurrency guard.

Prevents hung jobs (especially lychee's live network requests in markdown-links) from
consuming GitHub Actions quota up to the 6-hour default, and ensures stale in-progress
runs are cancelled when a new push arrives on an open PR.
"""

import glob
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

WORKFLOW_FILES = [
    Path(p).name
    for p in sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml")))
]

# Anchors to the start of the jobs: section; everything else (on:, permissions:) is ignored.
JOBS_SECTION_RE = re.compile(r"^jobs:\s*$", re.MULTILINE)

# Matches job-name keys at exactly 2-space indent with no inline value, e.g. "  smoke:"
JOB_KEY_RE = re.compile(r"^  (\S[^:]*):\s*$", re.MULTILINE)

# Matches timeout-minutes at exactly 4-space indent (direct job property), e.g. "    timeout-minutes: 15"
# [1-9]\d* requires a positive integer — rejects 0 which disables the timeout on GitHub Actions.
TIMEOUT_RE = re.compile(r"^    timeout-minutes:\s*[1-9]\d*\s*$", re.MULTILINE)


@pytest.mark.parametrize("filename", WORKFLOW_FILES)
def test_every_job_has_timeout_minutes(filename):
    text = (ROOT / ".github" / "workflows" / filename).read_text()

    jobs_match = JOBS_SECTION_RE.search(text)
    assert jobs_match, f"{filename}: no 'jobs:' section found"
    # Scope all subsequent scanning to the jobs: block only, so trigger keys in
    # the on: block (pull_request, schedule, etc.) are not mistaken for job names.
    jobs_section = text[jobs_match.end():]

    job_matches = list(JOB_KEY_RE.finditer(jobs_section))
    assert job_matches, f"{filename}: no job keys found under 'jobs:' — check indentation regex"

    missing = []
    for i, match in enumerate(job_matches):
        job_name = match.group(1)
        start = match.end()
        end = job_matches[i + 1].start() if i + 1 < len(job_matches) else len(jobs_section)
        segment = jobs_section[start:end]
        if not TIMEOUT_RE.search(segment):
            missing.append(job_name)

    assert not missing, (
        f"{filename}: job(s) missing 'timeout-minutes': {missing}"
    )


def test_pr_yml_has_concurrency_guard():
    text = (ROOT / ".github" / "workflows" / "pr.yml").read_text()

    # Match the top-level concurrency: block and capture its indented body
    conc_match = re.search(r"^concurrency:\s*\n((?:  .+\n?)+)", text, re.MULTILINE)
    assert conc_match, "pr.yml: missing top-level 'concurrency:' block"

    conc_body = conc_match.group(1)
    assert "github.ref" in conc_body, (
        "pr.yml: concurrency group must reference ${{ github.ref }}"
    )
    assert re.search(r"cancel-in-progress:\s*true", conc_body), (
        "pr.yml: missing 'cancel-in-progress: true' inside concurrency block"
    )

"""Guards the Step 6 inline-comment POST in the PR-review skills against the
`gh api -F body=` @-expansion hazard (issue #494).

A reviewer finding body is free-form text that can legitimately start with
`@author...`. `gh api -F body=` treats an @-prefixed value as a file path to
read, so posting such a finding with `-F` would silently read (or fail to
read) a bogus file instead of posting the literal text. `-f body=` forces a
raw string and is the fix mirrored from `reply-and-resolve.sh` (see
test_reply_and_resolve_script.py::test_body_flag_is_lowercase_f_not_uppercase_f).

Unlike the runtime script, `gh api` and the `-F body=` flag sit on separate
continuation lines inside the skill's fenced code block, so a single-line
`"body=" in ln and "gh api" in ln` filter would match nothing and pass
vacuously. This test extracts the fenced bash block containing the POST and
asserts on the literal flag string within it — scoped to the code block, not
the whole file, since the "Common mistakes" table also mentions `-F body=`
in prose as the anti-pattern being warned against.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKILL_PATHS = [
    ROOT / "skills" / "workflow-pr-review" / "SKILL.md",
    ROOT / "skills" / "workflow-pr-review-followup" / "SKILL.md",
]

CODE_BLOCK_RE = re.compile(r"```bash\n(.*?)\n\s*```", re.DOTALL)


def _post_code_block(text: str) -> str:
    for block in CODE_BLOCK_RE.findall(text):
        if "pulls/${PR}/comments" in block:
            return block
    raise AssertionError("no fenced bash block found for the pulls/{PR}/comments POST")


def test_step6_post_uses_lowercase_f_not_uppercase_f_for_body():
    for path in SKILL_PATHS:
        block = _post_code_block(path.read_text())
        assert '-f body="$BODY"' in block, (
            f"{path}: expected -f body=\"$BODY\" (raw string) in the Step 6 "
            "inline-comment POST"
        )
        assert '-F body="$BODY"' not in block, (
            f"{path}: -F body=\"$BODY\" would @-file-expand a finding body "
            "that starts with @author"
        )

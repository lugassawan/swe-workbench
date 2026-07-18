"""Guards the raw-body discipline of the shared PR-review posting core's two
comment-posting call sites against injection/@-expansion hazards (issue #494).

A reviewer finding body is free-form text that can legitimately start with
`@author...` or contain `"`/`\\` characters. Two distinct hazards apply
depending on the call site:

1. `gh api -F body=` treats an @-prefixed value as a file path to read, so
   posting such a finding with `-F` would silently read (or fail to read) a
   bogus file instead of posting the literal text. `-f body=` forces a raw
   string and is the fix mirrored from `reply-and-resolve.sh` (see
   test_reply_and_resolve_script.py::test_body_flag_is_lowercase_f_not_uppercase_f).
2. Building a JSON array (GitHub's `comments[]` field) by string-concatenating
   a free-form body directly into a JSON literal would let a body containing
   `"` or `\\` break the JSON or inject fields. `jq --arg` escapes safely.

Since issue #531, the primary inline-posting path is the atomic
`POST /pulls/{n}/reviews` call with a `comments[]` array (pending-review
model). `gh api` bracket-indexed field flags (`-f "comments[0][path]=..."`)
cannot build this array — they build a JSON *object* keyed by stringified
indices, which GitHub's API rejects — so `comments[]` is built as real JSON
via `jq` and the whole payload is posted with `gh api --input -` (see
docs/gh-api-field-flags.md). The old single-comment `POST /pulls/{n}/comments`
call is now reachable only as the model-A fallback after a confirmed
double-422 on the atomic path, and still uses `-f`/`-F` field flags directly
(a scalar-field endpoint, not an array), carrying the original raw-body
requirement — so this test guards both call sites.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKILL_PATHS = [
    ROOT / "skills" / "workflow-pr-review-post" / "SKILL.md",
]

CODE_BLOCK_RE = re.compile(r"```bash\n(.*?)\n\s*```", re.DOTALL)


def _blocks_containing(text: str, marker: str) -> list[str]:
    return [block for block in CODE_BLOCK_RE.findall(text) if marker in block]


def test_comments_array_never_built_via_bracket_indexed_field_flags():
    # Scoped to fenced bash blocks only — prose elsewhere in the file (Common
    # mistakes table, Step 2 explanation) legitimately names this anti-pattern
    # to warn against it; only *executable* bash reintroducing it is a bug.
    for path in SKILL_PATHS:
        for block in CODE_BLOCK_RE.findall(path.read_text()):
            assert "comments[$i][" not in block and "comments[0][" not in block, (
                f"{path}: a bash block builds comments[] via gh api "
                "bracket-indexed field flags — this produces a JSON object "
                "with stringified keys, not an array, which GitHub's Reviews "
                "API rejects. Build comments[] as real JSON via jq instead."
            )


def test_comments_json_assembled_via_jq_arg_for_body():
    for path in SKILL_PATHS:
        blocks = _blocks_containing(path.read_text(), "COMMENTS_JSON")
        assert blocks, (
            f"{path}: no fenced bash block found assembling COMMENTS_JSON"
        )
        assert any('--arg body "$BODY"' in b for b in blocks), (
            f"{path}: expected jq --arg body \"$BODY\" (safe raw-string "
            "escaping) when assembling a comments[] row — string-concatenating "
            "$BODY into a JSON literal would let a body containing \" or \\ "
            "break the JSON or inject fields"
        )
        assert any('--argjson line "$LINE"' in b for b in blocks), (
            f"{path}: expected jq --argjson line \"$LINE\" (typed scalar) "
            "when assembling a comments[] row"
        )


def test_atomic_reviews_post_uses_input_flag_not_f_F_for_body():
    for path in SKILL_PATHS:
        blocks = _blocks_containing(path.read_text(), "pulls/${PR}/reviews")
        assert blocks, (
            f"{path}: no fenced bash block found for the atomic "
            "pulls/{PR}/reviews POST"
        )
        assert any("--input -" in b for b in blocks), (
            f"{path}: the atomic pulls/{{PR}}/reviews POST must use "
            "'gh api --input -' with a jq-built JSON payload — -f/-F field "
            "flags cannot represent the comments[] array field"
        )


def test_fallback_per_comment_post_uses_lowercase_f_not_uppercase_f_for_body():
    for path in SKILL_PATHS:
        blocks = _blocks_containing(path.read_text(), "pulls/${PR}/comments")
        assert blocks, (
            f"{path}: no fenced bash block found for the model-A fallback "
            "pulls/{PR}/comments POST"
        )
        assert any('-f body="$BODY"' in b for b in blocks), (
            f"{path}: expected -f body=\"$BODY\" (raw string) in the fallback "
            "per-comment POST"
        )
        assert not any('-F body="$BODY"' in b for b in blocks), (
            f"{path}: -F body=\"$BODY\" would @-file-expand a finding body "
            "that starts with @author"
        )

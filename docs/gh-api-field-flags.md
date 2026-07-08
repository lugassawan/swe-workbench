# `gh api` field flags: `-f` vs `-F`

`gh api` accepts request-body fields two ways, and mixing them up fails **silently** — no
error, no warning, just the wrong content posted.

| Flag | Long form | Semantics |
|---|---|---|
| `-f key=value` | `--raw-field` | Value is always sent as a literal string. |
| `-F key=value` | `--field` | Value is typed: JSON `true`/`false`/numbers are converted; and if the value starts with `@`, it is treated as a **file path to read** (`@-` reads stdin) instead of a literal string. |

## Two failure modes

1. **`-f body=@/path/to/file.md`** — `-f` never does `@`-expansion, so this posts the *literal
   string* `@/path/to/file.md`, not the file's contents. To post a body sourced from a file, use
   `-F body=@/path/to/file.md` instead.
2. **`-F body="@author, thanks for the review"`** — a free-form body that happens to start with
   `@` gets `@`-expanded by `-F`: `gh` tries to open a file named `author, thanks for the review`
   and the call fails (or, worse, reads an unrelated file that happens to exist at that path).

Both are silent at the call site — the bug only surfaces later, as a garbled or missing comment.

## Rule

| Body source | Flag |
|---|---|
| Free-form string that may start with `@` (a reply, a reviewer finding) | `-f body="$VALUE"` |
| Content that must be read from a file | `-F body=@/path/to/file.md` |
| Typed scalar (e.g. `line` as an integer) | `-F line="$LINE"` |

## Spot-check

After posting, confirm the body landed as the literal string you intended:

```bash
gh api <endpoint>/<id> -q '.body'
```

## Where this is enforced

- `runtime/reply-and-resolve.sh` uses `-f body=` for both reply call sites (reply bodies start
  with `@{author}`); guarded by
  `tests/test_reply_and_resolve_script.py::test_body_flag_is_lowercase_f_not_uppercase_f`.
- `skills/workflow-pr-review/SKILL.md` and `skills/workflow-pr-review-followup/SKILL.md` use
  `-f body="$BODY"` in the Step 6 inline-comment POST (a reviewer finding can also start with
  `@author`); guarded by `tests/test_pr_review_skill_body_flag.py`.

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

## Arrays of objects: `-f`/`-F` field flags don't work, use `--input -`

`gh api -f`/`-F` bracket notation (`key[]=value`) only builds arrays of **scalars**.
Numeric-indexed bracket notation (`comments[0][path]=...`, `comments[1][path]=...`) does
**not** build an array of objects — it builds a JSON *object* keyed by stringified indices
(`{"comments":{"0":{...},"1":{...}}}`), which most array-typed API fields (e.g. GitHub's
`POST /pulls/{n}/reviews` `comments` field) reject outright. Verified against a live `gh`
install — this is not a theoretical gap.

For an array-of-objects field, build the whole request body as JSON (`jq` is the natural
tool) and post it via `gh api --input -`, which reads the request body verbatim from stdin.
`jq --arg`/`--argjson` give the same raw-string safety `-f` gives a scalar field — a value
starting with `@` is embedded as a literal JSON string, never file-expanded, because the
payload never passes through `gh api`'s own field-flag parser at all:

```bash
PAYLOAD=$(jq -n --arg body "$BODY" '{body: $body, comments: $comments_array}')
gh api --method POST <endpoint> --input - <<<"$PAYLOAD"
```

Never string-concatenate a free-form value directly into a JSON literal (`"body": "'"$BODY"'"`)
— a value containing `"` or `\` breaks the JSON or injects fields. Always go through `jq --arg`.

## Where this is enforced

- `runtime/reply-and-resolve.sh` uses `-f body=` for both reply call sites (reply bodies start
  with `@{author}`); guarded by
  `tests/test_reply_and_resolve_script.py::test_body_flag_is_lowercase_f_not_uppercase_f`.
- `skills/workflow-pr-review-post/SKILL.md` (the shared posting core used by
  `workflow-pr-review`, `workflow-pr-review-followup`, and the `/swe-workbench:review`
  specialist PR-mode sub-flow) builds the Step 2 `comments[]` array via `jq --arg body`
  and posts it with `gh api --input -` (see above), and uses `-f body="$BODY"` in the
  Step 4 model-A fallback's single-comment POST (a reviewer finding can also start with
  `@author`); both guarded by `tests/test_pr_review_skill_body_flag.py`.

---
name: language-bash
description: Bash idioms — strict mode, quoting, parameter expansion, arrays, pipefail, trap cleanup, idempotency, heredocs, and POSIX portability. Auto-load when working with .sh, .bash files, or when the user mentions bash, shell, sh, shellcheck, set -e, or pipefail.
---

# Bash

## Strict mode
```bash
set -euo pipefail
IFS=$'\n\t'
```
- `-e` is suppressed in conditional contexts (`||`, `&&`, `if`, `!`); explicit subshells `(...)` **do** inherit it — use `|| true` to absorb expected failures.
- `-u` treats unset variables as errors; unset arrays trigger it: declare before use (`arr=()`) or guard with `${arr[@]+"${arr[@]}"}` for optional arrays.
- `IFS=$'\n\t'` prevents accidental word-splitting on spaces in `for` loops and command substitution.

## Quoting and tests
- Always `"$var"` — bare `$var` triggers word splitting and glob expansion.
- `'literal'` for fixed strings with no expansion needed.
- Prefer `[[ ]]` over `[ ]`: supports `=~` regex, no word splitting, lexical string comparison.
- `$()` over backticks: nestable, readable, no escaping required.

```bash
if [[ "$filename" =~ \.(sh|bash)$ ]]; then
  shellcheck "$filename"
fi
```

## Parameter expansion
- `${var:-default}` — substitute default if unset or empty.
- `${var:?error msg}` — abort with message if unset; pairs well with `set -u`.
- `${var%suffix}` — strip shortest suffix match (e.g. strip extension).
- `${var//pattern/repl}` — replace all occurrences in-place.

## Arrays and word splitting
```bash
files=(src/a.sh "src/b script.sh" src/c.sh)
for f in "${files[@]}"; do   # each element quoted separately
  process "$f"
done
```
- `"${arr[@]}"` — each element as a separate quoted word; always use for iteration.
- `"${arr[*]}"` — all elements joined by `IFS[0]`; use only for joining to a string.
- Never `for x in $(cmd)` — use `mapfile -t arr < <(cmd)` or `while IFS= read -r line`.

## Pipelines and subshells
- `pipefail` makes a pipeline fail when any stage fails, not just the last.
- Command substitution `$(...)` runs in a subshell; variable assignments inside don't leak out.
- `cmd || true` absorbs an expected non-zero exit under `-e`; `cmd 2>/dev/null` suppresses stderr noise separately.
- Background jobs: `proc &`; always `wait "$pid"` before consuming results.
- Redirect ordering matters: `cmd >/dev/null 2>&1` silences all; `cmd 2>&1 >/dev/null` silences stdout only (stderr still shows — order determines what `2>&1` copies).

## Cleanup with trap
```bash
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
trap 'echo "interrupted" >&2; exit 130' INT TERM
```
- Register `trap` early — after state the handler depends on exists, before risky operations.
- `trap '...' ERR` fires only on non-zero exit codes; use for diagnostic logging (cannot prevent `-e` from exiting).
- Signal names: `EXIT` (always), `ERR` (errors), `INT` (Ctrl-C), `TERM` (kill).
- **Alternative:** idempotent scripts that are safe to re-run don't need cleanup traps — see §Idempotency.

## Idempotency and resumability
```bash
COMMITTED=0
[[ -f .committed ]] && COMMITTED=1

if (( COMMITTED == 0 )); then
  git commit -m "$msg"
  touch .committed
fi
```
- Check-before-act: `[[ -f sentinel ]] || create_it`.
- Detect external state via read-only queries: `git ls-remote`, `gh pr view --json state`.
- Atomic file rewrites: `tmp=$(mktemp) && generate > "$tmp" && mv "$tmp" target`.
- Integer flags (`STEP_DONE=0/1`) let downstream branches re-enter safely after interruption.

## Heredocs
```bash
# Literal — no variable expansion:
sql=$(cat <<'EOF'
SELECT * FROM $table WHERE id = $id
EOF
)

# Interpolating — $USER expands:
cat <<EOF
Deploying as $USER to $ENV
EOF

# Strip leading tabs (not spaces) with <<-:
if true; then
	cat <<-EOF
	indented content
	EOF
fi
```

## Bash vs POSIX sh
- `#!/usr/bin/env bash` when using `[[ ]]`, arrays, `${var,,}`, `mapfile`, or process substitution.
- `#!/bin/sh` only when strict POSIX portability is required — drop all bash-isms.
- Run `shellcheck --shell=bash` (or `--shell=sh`) to enforce the declared contract.

## Tests
- `bats-core` for non-trivial scripts: one assertion per test, temp dirs for isolation.
- For inline assertions in one-shot scripts:
```bash
assert_eq() { [[ "$1" == "$2" ]] || { echo "FAIL: expected '$2', got '$1'" >&2; exit 1; }; }
```
- Mock external commands by prepending a temp dir containing stub scripts to `PATH`.
- **eval/cwd trap**: when testing `eval "$(script 2>&1)"` patterns, capture the script output FIRST from a valid cwd, THEN `cd` to the eval directory, THEN eval. `$(...)` launches a subshell that inherits the cwd at expansion time — `cd eval_cwd && eval "$(script)"` means the script runs FROM `eval_cwd`, not the original directory, and may exit early.
```bash
# Wrong — script inherits eval_cwd as cwd, may exit early if it's not a git repo:
cd "$eval_cwd" && eval "$(bash script.sh arg 2>&1)"

# Correct — capture first, then move, then eval:
output="$(bash script.sh arg 2>&1)"; cd "$eval_cwd"; eval "$output"
```
  Under `set -e`, use `output=$(…) || handle_error` — `$?` is unreachable because the parent script aborts at the failed assignment before the next line executes. The `||` forms a conditional context that suppresses `set -e` and runs the handler on non-zero exit.

## Avoid
- Backtick substitution `` `cmd` `` — use `$(cmd)`.
- Unquoted `$var` and `$@` — always quote.
- `for f in $(ls)` or `for f in $(find ...)` — use globs or `mapfile`.
- Parsing `ls` output for filenames — use `find` or shell globs.
- `eval` on user-controlled or external input — command injection risk.
- `cd dir && cmd` without a subshell — if `cmd` fails, subsequent code runs from the wrong directory; use `(cd dir && cmd)` to scope the change.
- `cat file | grep` (UUOC) — use `grep pattern file`.
- `set -x` in production — use `PS4` with a debug flag and enable only in targeted blocks.

# Shell footgun: `echo` vs `printf` on variables containing JSON

`echo` is not portable when its argument contains backslash escapes, and piping or
redirecting a JSON-bearing variable through it can silently corrupt the JSON.

## Why zsh differs

- **zsh's `echo`** interprets `\n`, `\t`, `\\`, and other backslash escapes in its argument
  by default — no flag required.
- **bash's `echo`** does **not** expand them unless `shopt -s xpg_echo` is set or `-e` is
  passed explicitly.
- **POSIX** leaves this implementation-defined. There is no portable `echo` behavior for
  data that may contain backslashes.

Every `.sh`/`.bash` file in this repo carries `#!/usr/bin/env bash`, so this hazard cannot
fire there. It fires in fenced ` ```bash ` blocks inside skill/command/agent markdown —
those run through the Bash tool in the user's **login shell**, which on macOS is zsh.

## The JSON case

`\n` inside a JSON string is a legal two-character escape (backslash, `n`). zsh's `echo`
converts that pair into a single raw newline byte. A raw newline inside a JSON string is an
unescaped control character — invalid JSON:

```bash
J='{"body":"line1\nline2"}'
echo "$J" > /tmp/payload.json      # zsh: the \n becomes a raw newline byte
jq . /tmp/payload.json             # parse error below — corrupted upstream, not here
```

The failure surfaces far from its cause, in whatever later reads the file:

```
jq: parse error: Invalid string: control characters from U+0000 through U+001F must be escaped
```

## `printf "$VAR"` is the dangerous fix

The naive translation of `echo "$VAR"` is `printf "$VAR"` — and that is a **different, worse**
bug. `printf`'s first argument is a **format string**: a literal `%s` inside `$VAR` reads a
nonexistent argument, and in some `printf(1)` implementations a literal `%n` is a memory-write
primitive. `$VAR` must always be an **argument** to a literal `'%s'` format, never the format
string itself:

```bash
printf '%s' "$VAR"     # correct — '%s' is a literal format, $VAR is its argument
printf "$VAR"          # wrong — $VAR IS the format string
```

## Newline convention

| Use case | Form |
|---|---|
| Exact bytes matter (JSON → file, JSON → parser) | `printf '%s' "$VAR"` |
| Replacing `echo` in a line-oriented pipe (`\| awk`, `\| grep`, `\| cut`) | `printf '%s\n' "$VAR"` |

Dropping the trailing newline in the line-oriented case is a silent behavior change — some
consumers (`awk`, `grep -q`, `cut`) tolerate a missing final newline, but relying on that is
fragile. Only use the bare `'%s'` form when the destination is a file or parser that must
receive the value's exact bytes.

## What stays fine

- `echo` of a **literal** string with no variable — nothing to expand.
- `echo ... >&2` or `echo ... >/dev/null` for human-facing status/diagnostic output — no
  parser downstream, so escape expansion has nothing to corrupt.

## Where this is enforced

- `scripts/validate.py::check_no_echo_var_hazard` scans fenced ` ```bash ` blocks under
  `skills/`, `commands/`, and `agents/` for a variable piped or redirected through `echo`.
- `tests/test_validate.py::TestCheckNoEchoVarHazard` covers the flag/no-flag cases.

`shared/docs/` is skipped explicitly by the scanner (worked-example content, #637) —
this page shows the bad pattern as a worked example above, and scanning it would trip
the guard on its own content. The scan covers `skills/`, `commands/`, `agents/`, and
`shared/` minus `shared/docs/`.

# Secret detection

The `secret_guard.py` hook intercepts every `Write` and `Edit` tool call and
blocks the operation **before the file is written** when the content contains a
hardcoded secret. This catches accidental leaks at authoring time, even when
the git `pre-commit` hook is absent or bypassed.

## How it works

| Layer | Detail |
|---|---|
| **Hook event** | `PreToolUse` on matcher `Write\|Edit` |
| **Script** | `hooks/secret_guard.py` — stdlib only (`re`, `json`), no external deps |
| **Input** | JSON payload on stdin (Claude Code hook protocol) |
| **Block** | writes `BLOCKED: …` to stderr, exits 2 |
| **Allow** | exits 0, empty stderr |
| **Tool routing** | `Write` → scan `tool_input.content`; `Edit` → scan `tool_input.new_string` only (removing a secret in `old_string` is never blocked) |

### Pattern tiers

**HIGH confidence** — block on any line, regardless of suppression:

| Pattern name | Regex |
|---|---|
| `github-pat` | `ghp_[A-Za-z0-9]{36}` |
| `github-fine-grained-pat` | `github_pat_[A-Za-z0-9_]{82}` |
| `aws-access-key-id` | `AKIA[0-9A-Z]{16}` |
| `private-key-pem` | `-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----` |

**NEEDS-CONTEXT** — block only when a key name is adjacent to a literal value;
skipped automatically on lines that contain an environment-variable reference
(`os.environ`, `os.getenv`, `process.env`, `ENV[`, `getenv`) or a `# nosecret` comment:

| Pattern name | What it matches |
|---|---|
| `aws-secret-access-key` | `aws_secret… = …40-char value…` |
| `generic-api-key` | `API_KEY = …≥16 chars…` |
| `generic-secret` | `SECRET / PASSWORD / PASSWD / TOKEN = …≥8 chars…` |
| `dotenv-assignment` | `SECRET=…` / `TOKEN=…` etc. at line start (`.env` style) |

## Suppression & allowlist

### Per-line suppression

Add `# nosecret` anywhere on the line to skip **NEEDS-CONTEXT** pattern checks for that line:

```python
BOOTSTRAP_TOKEN = "<placeholder>"  # nosecret
```

Only that exact line is suppressed. Adjacent lines are checked normally.

> **Note:** `# nosecret` has **no effect** on HIGH-confidence patterns (`github-pat`,
> `github-fine-grained-pat`, `aws-access-key-id`, `private-key-pem`). Those patterns are always blocked.
> If you have a genuine fixture that looks like a GitHub PAT, AWS key, or PEM header, add the file
> path to `_ALLOWLIST_SUFFIXES` instead.

### Filename allowlist

Certain files are exempt from all checks (the hook exits 0 immediately):

| Exempted path | Reason |
|---|---|
| Any file named `.gitignore` | May reference token formats as ignore patterns |
| `tests/test_secret_guard.py` | The test corpus contains shaped-but-fake fixture tokens |

Add future fixture files to `_ALLOWLIST_SUFFIXES` in `hooks/secret_guard.py`
**by explicit absolute suffix**, never by a broad glob — the allowlist is
intentionally narrow.

## Troubleshooting

**False positive — I'm assigning from an env var, not hardcoding**

The hook already skips NEEDS-CONTEXT patterns when the line contains
`os.environ`, `os.getenv`, `process.env`, `ENV[`, or `getenv`. If a reference
form you use is not covered, add a `# nosecret` on that line, or open an issue
to extend `_REF_PATTERN` in `hooks/secret_guard.py`.

**The hook is blocking a test fixture**

For NEEDS-CONTEXT patterns: add `# nosecret` on each fixture line.
For HIGH-confidence patterns (GitHub PAT, AWS key ID, PEM private-key header): `# nosecret` has no effect —
add the file's absolute path to `_ALLOWLIST_SUFFIXES` instead.

**The hook seems to do nothing**

The hook activates once the plugin is (re)loaded at the installed version.
Verify the entry is present in `hooks/hooks.json` and that the script is
executable (`chmod +x hooks/secret_guard.py`).

## Security note

This hook is a **guardrail against accidental leaks by a cooperative agent**,
not an adversarial control. An agent or user who controls the write payload
can trivially evade it (e.g., by encoding the secret or splitting across
lines). The fail-open posture (exit 0 on parse/interpreter errors) is
deliberate: a broken guard that blocked every file write would be worse than
no guard at all.

Defense-in-depth remains important. Combine this hook with:

- The `.githooks/pre-commit` scanner (catches leaks that reach the index)
- Repository secret scanning (GitHub Advanced Security, etc.)
- Credential rotation and short-lived tokens where possible

# Security Policy

## Supported Versions

Only the current minor release receives security fixes. Older minors are unsupported.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |
| < 0.1   | No        |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security bugs.**

Use GitHub's private vulnerability reporting instead:

**Security tab → "Report a vulnerability"** — or go directly to:
<https://github.com/lugassawan/swe-workbench/security/advisories/new>

## Scope

**In scope** — vulnerabilities in the plugin's own files:
- Subagent and skill prompts (`agents/`, `skills/`)
- Commands (`commands/`)
- Hooks (`hooks/`)
- Scripts (`scripts/`)
- Plugin manifests (`.claude-plugin/`)

**Out of scope** — security issues that originate entirely in the user's own codebase (not caused by the plugin). That code is the user's responsibility.

## Response Time

This is a personal-time project. Acknowledgement aim: 7 days. Patches for critical issues: best-effort, no formal SLA. Fixes are prioritised by severity.

# Severity-output contract

Standard output format used by all auditor agents. Each agent extends the severity ladder with domain-specific criteria inline.

## Finding format

Each finding follows this pipe-delimited line format:

```
Severity | File:Line | Issue | Why it matters | Suggested fix
```

## Severity ladder

| Tier | Role-agnostic criteria |
|---|---|
| **Critical** | Exploitable or guaranteed-failure now, no preconditions needed |
| **High** | Exploitable or likely-failure with realistic preconditions |
| **Medium** | Defense-in-depth gap — failure is recoverable without production incident |
| **Low** | Hygiene: no realistic failure path, but worth noting |

Domain agents extend these tiers with domain-specific examples in their own severity table.

## Sort order

Group findings by severity, highest first: Critical → High → Medium → Low. Within each tier, sort by file then line number.

## Silence rule

If no findings, say so explicitly: "No \<domain\> issues found in this diff." Silence is not a passing grade.

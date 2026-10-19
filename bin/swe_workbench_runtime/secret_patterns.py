"""Credential patterns shared by runtime scripts that must refuse or scrub secrets."""

from __future__ import annotations

import re

SECRET_PATTERNS = (
    re.compile(
        r"\b(?:authorization|proxy-authorization)\s*:\s*(?:bearer|basic)\s+\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|sk)_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:github_pat_|sk-ant-|glpat-)[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)

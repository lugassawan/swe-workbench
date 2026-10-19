"""Tests for the shared credential patterns used by runtime scripts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bin"))

from swe_workbench_runtime import secret_patterns

# Fixtures are assembled from parts so no credential-shaped literal sits in the source.
_BODY = "abcdefgh12345678"


def _matches(text: str) -> bool:
    return any(pattern.search(text) for pattern in secret_patterns.SECRET_PATTERNS)


@pytest.mark.parametrize(
    "sample",
    [
        "Authorization: Bearer " + "abc123def456",
        "proxy-authorization: Basic " + "dXNlcjpwYXNz",
        "token " + "ghp" + "_" + _BODY,
        "token " + "gho" + "_" + _BODY,
        "token " + "ghu" + "_" + _BODY,
        "token " + "ghs" + "_" + _BODY,
        "key " + "sk" + "_live_" + "abcdefgh1234",
        "key " + "sk" + "-" + _BODY,
        "key " + "sk" + "-proj-" + _BODY,
        "key " + "sk" + "-ant-" + _BODY,
        "pat " + "github" + "_pat_" + _BODY,
        "pat " + "glpat" + "-" + _BODY,
        "slack " + "xoxb" + "-" + _BODY,
        "slack " + "xoxp" + "-" + _BODY,
        "aws " + "AKIA" + "ABCDEFGHIJKLMNOP",
    ],
)
def test_each_token_family_matches(sample: str) -> None:
    assert _matches(sample)


@pytest.mark.parametrize(
    "sample",
    [
        "plain prose with no credentials",
        "a sketch of the task-list",
        "AKIA too short",
    ],
)
def test_ordinary_text_does_not_match(sample: str) -> None:
    assert not _matches(sample)

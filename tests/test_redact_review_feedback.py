"""Cases from the PR review threads: host suffixes, tracker keys, URL query/fragment service ids,
and the prose contract for private names the environment cannot know."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_redact_script import counts, load_module, run

ROOT = Path(__file__).parent.parent
DOCS = {
    "report-issue": ROOT / "commands" / "report-issue.md",
    "capture": ROOT / "commands" / "capture.md",
    "product-manager": ROOT / "agents" / "product-manager.md",
}


@pytest.fixture(scope="module")
def mod():
    return load_module()


# ── bare-host suffixes ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("build.acme.info is down", "[internal-host] is down"),
        ("api.acme.biz is down", "[internal-host] is down"),
        ("shop.acme.online is down", "[internal-host] is down"),
        ("edge.acme.network is down", "[internal-host] is down"),
    ],
)
def test_more_public_suffixes_are_hosts(mod, text, expected):
    out, _ = run(mod, text)
    assert out == expected


@pytest.mark.parametrize("text", ['logger.info("hi")', "call app.dev(x) now", "obj.cloud(a, b)"])
def test_a_dotted_name_that_is_called_is_code_not_a_host(mod, text):
    out, found = run(mod, text)
    assert out == text and not found


# ── tracker keys ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("see ACME-123 for context", "see [internal-ticket] for context"),
        ("PROJ-42 and ABC7-9999 both", "[internal-ticket] and [internal-ticket] both"),
        ("(ACME-123).", "([internal-ticket])."),
    ],
)
def test_tracker_keys_are_replaced(mod, text, expected):
    out, found = run(mod, text)
    assert out == expected
    assert set(found) == {"internal-ticket"}


def test_public_standard_identifiers_are_not_tracker_keys(mod):
    text = "UTF-8 and SHA-256 and ISO-8601 and HTTP-2 and RFC-2119 and CVE-2024-1234 and PEP-8"
    out, found = run(mod, text)
    assert out == text and not found


def test_an_allowed_tracker_key_is_kept(mod):
    out, found = run(mod, "see ACME-123", allow=("ACME-123",))
    assert out == "see ACME-123" and not found


def test_tracker_key_pass_is_idempotent(mod):
    first, _ = run(mod, "fixes ACME-123 and PROJ-7")
    second, again = run(mod, first)
    assert second == first and not again


# ── service ids in URL query, fragment and non-documentation paths ───────────


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "https://github.com/lugassawan/swe-workbench/issues/808?source=payments-service",
            "https://github.com/lugassawan/swe-workbench/issues/808?source=[internal-service]",
        ),
        ("http://localhost:3000/payments-service/health", "http://localhost:3000/[internal-service]/health"),
        ("https://docs.github.com/en/rest?q=payments-service", "https://docs.github.com/en/rest?q=[internal-service]"),
        ("https://docs.python.org/3/x#payments-service", "https://docs.python.org/3/x#[internal-service]"),
    ],
)
def test_service_ids_are_replaced_outside_documentation_paths(mod, text, expected):
    out, found = run(mod, text)
    assert out == expected
    assert counts(found) == {"internal-service": 1}


def test_documentation_paths_keep_their_own_wording(mod):
    text = "https://docs.github.com/en/rest/guides/getting-started-with-the-rest-api"
    out, found = run(mod, text)
    assert out == text and not found


# ── private names the environment cannot know ────────────────────────────────


def _joined(text: str) -> str:
    return re.sub(r"\\\n\s*", " ", text)


@pytest.mark.parametrize("name", sorted(DOCS))
def test_agent_supplies_private_names_through_a_deny_file(name):
    text = DOCS[name].read_text()
    joined = _joined(text)
    assert "--deny-file <deny-path>" in joined, f"{name}: the redactor call must pass the agent's deny file"
    assert ".deny" in text and "CATEGORY=TERM" in text, (
        f"{name}: the prose must say how the deny file is written (CATEGORY=TERM per line)"
    )
    assert "private" in text.lower() and "organi" in text.lower(), (
        f"{name}: the prose must tell the agent to list the private organisations/products it used"
    )


def test_report_issue_branch_b_also_passes_the_deny_file():
    text = DOCS["report-issue"].read_text()
    branch_b = text[text.find("### Branch B"):text.find("Delegate to the `swe-workbench:product-manager` subagent")]
    assert "--deny-file" in _joined(branch_b)


@pytest.mark.parametrize("name", sorted(DOCS))
def test_cleanup_reaps_the_deny_file(name):
    text = DOCS[name].read_text()
    cleanup = text[text.find('swe-workbench-clean-state-files "'):]
    cleanup = cleanup[: cleanup.find("2>/dev/null")]
    assert '<unix-timestamp>.deny"' in cleanup, f"{name}: cleanup must name the .deny file"


@pytest.mark.parametrize("name", ["report-issue", "capture"])
def test_placeholder_vocabulary_lists_the_ticket_placeholder(name):
    assert "[internal-ticket]" in DOCS[name].read_text()

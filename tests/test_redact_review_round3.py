"""Third review round: more public suffixes, tracker-key edges, target-repo URL paths, dead parameter."""

from __future__ import annotations

import inspect

import pytest
from test_redact_script import load_module, run


@pytest.fixture(scope="module")
def mod():
    return load_module()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("portal.acme.edu is down", "[internal-host] is down"),
        ("intranet.acme.gov is down", "[internal-host] is down"),
        ("build.acme.page is down", "[internal-host] is down"),
        ("stream.acme.live is down", "[internal-host] is down"),
        ("press.acme.news is down", "[internal-host] is down"),
        ("notes.acme.blog is down", "[internal-host] is down"),
    ],
)
def test_more_public_suffixes_are_hosts(mod, text, expected):
    out, _ = run(mod, text)
    assert out == expected


@pytest.mark.parametrize(
    "text",
    [
        "target Q3-2025 and ship in H2-2024 or FY-2026",
        "CP-1252 mojibake and PSR-4 autoloading",
        "GH-1234 was fixed upstream",
    ],
)
def test_dates_and_public_shorthand_are_not_tracker_keys(mod, text):
    out, found = run(mod, text)
    assert out == text and not found


@pytest.mark.parametrize(
    "text,expected",
    [
        ("branch feature/ACME-123-fix is open", "branch feature/[internal-ticket]-fix is open"),
        ("branch hotfix-ACME-123 is open", "branch hotfix-[internal-ticket] is open"),
        ("ACME-123-followup", "[internal-ticket]-followup"),
    ],
)
def test_hyphen_embedded_tracker_keys_are_replaced(mod, text, expected):
    out, _ = run(mod, text)
    assert out == expected


def test_public_standards_next_to_hyphens_are_still_kept(mod):
    text = "use SHA-256-bit hashes, UTF-8-encoded text, CVE-2024-1234 and AES-256-GCM"
    out, found = run(mod, text)
    assert out == text and not found


def test_target_repo_url_paths_are_public_but_their_query_is_not(mod):
    kept = "https://github.com/lugassawan/swe-workbench/blob/main/docs/rest-api.md"
    out, found = run(mod, kept)
    assert out == kept and not found
    out, _ = run(mod, kept + "?source=payments-service")
    assert out == kept + "?source=[internal-service]"
    api = "https://api.github.com/repos/lugassawan/swe-workbench/contents/docs/rest-api.md"
    out, found = run(mod, api)
    assert out == api and not found


def test_another_repositorys_url_is_still_replaced_whole(mod):
    out, _ = run(mod, "see https://github.com/acme/ledger/blob/main/docs/rest-api.md now")
    assert out == "see [internal-host] now"


def test_documentation_path_helper_takes_no_unused_parameters(mod):
    params = list(inspect.signature(mod._documentation_path).parameters)
    assert "rules" not in params, params

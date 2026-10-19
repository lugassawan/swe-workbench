"""Hardening cases for bin/swe-workbench-redact found in review.

Same fixture discipline as test_redact_script.py: every value is fake and credential-shaped
strings are assembled from parts.
"""

from __future__ import annotations

import pytest
from test_redact_script import (
    _BODY,
    GH_TOKEN,
    TARGET,
    _git,
    counts,
    load_module,
    run,
    run_cli,
)


@pytest.fixture(scope="module")
def mod():
    return load_module()


# ── URL handling ──────────────────────────────────────────────────────────────


def test_bracketed_ipv6_urls_do_not_crash(mod):
    out, found = run(mod, "dev server at http://[::1]:3000/ is up")
    assert out == "dev server at http://[::1]:3000/ is up" and not found
    out, found = run(mod, "peer http://[fe80::1]/x refused")
    assert out == "peer [internal-host] refused"
    assert counts(found) == {"internal-host": 1}
    run(mod, "broken http://[abc link")  # must not raise


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "https://docs.python.org/3/x?e=bob@corp.example.com",
            "https://docs.python.org/3/x?e=[internal-email]",
        ),
        ("http://localhost:8080/Users/alice/secret/file", "http://localhost:8080[local-path]"),
        (
            "https://github.com/lugassawan/swe-workbench/issues/3?x=/Users/bob/y",
            "https://github.com/lugassawan/swe-workbench/issues/3?x=[local-path]",
        ),
        (
            "http://127.0.0.1:8080/?host=db.prod.acme.com&ip=10.1.1.1",
            "http://127.0.0.1:8080/?host=[internal-host]&ip=[internal-ip]",
        ),
        ("https://docs.github.com/x;/Users/alice/secret", "https://docs.github.com/x;[local-path]"),
    ],
)
def test_a_vouched_url_only_exempts_its_host_not_its_tail(mod, text, expected):
    out, _ = run(mod, text)
    assert out == expected


def test_deny_terms_still_fire_in_a_public_url_tail(mod):
    out, _ = run(
        mod,
        "http://localhost:8080/ws/alice/acmecorp-billing",
        deny=(("user", "alice"), ("repo", "acmecorp-billing")),
    )
    assert out == "http://localhost:8080/ws/[local-user]/[internal-repo]"


@pytest.mark.parametrize(
    "text",
    [
        "https://api.github.com/repos/lugassawan/swe-workbench/issues",
        "visit github.com for details",
        "https://docs.github.com/en/rest/guides/getting-started-with-the-rest-api",
        "https://pypi.org/project/some-pkg-api/",
        "https://pip.pypa.io/en/stable/ and https://registry.npmjs.org/left-pad",
    ],
)
def test_public_documentation_urls_are_kept(mod, text):
    out, found = run(mod, text)
    assert out == text and not found


def test_other_github_owner_page_is_replaced(mod):
    out, _ = run(mod, "see https://github.com/acme now")
    assert out == "see [internal-host] now"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("remote git@github.com:acme/secret-repo.git ok", "remote [internal-host] ok"),
        ("git@gitlab.internal.acme.co:team/payments-api.git", "[internal-host]"),
    ],
)
def test_scp_style_remotes_are_replaced_whole(mod, text, expected):
    out, _ = run(mod, text)
    assert out == expected


def test_scp_remote_of_the_target_repo_is_kept(mod):
    text = "origin git@github.com:lugassawan/swe-workbench.git ok"
    out, found = run(mod, text)
    assert out == text and not found


# ── paths ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("/mnt/c/Users/bob/Doc", "[local-path]"),
        ("/System/Volumes/Data/Users/bob/x", "[local-path]"),
        ("/@fs/Users/bob/proj/a.js", "[local-path]"),
        ("gcc -I/Users/alice/inc -L/home/bob/lib", "gcc -I[local-path] -L[local-path]"),
        ("C:/Users/alice/x.py", "[local-path]"),
        ("C:\\\\Users\\\\alice\\\\proj\\\\x.py", "[local-path]"),
        ("cd /Users/Alice Smith/Documents/acme-secret now", "cd [local-path] now"),
        ('open "/Users/Jane Doe/My Project/x.py"', 'open "[local-path]"'),
        ("C:\\Users\\Jane Doe\\Documents\\x done", "[local-path] done"),
        ("/Users/jdoe/Library/Application Support/tool/cfg", "[local-path]"),
    ],
)
def test_more_local_path_shapes_are_replaced_whole(mod, text, expected):
    out, found = run(mod, text)
    assert out == expected
    assert set(found) == {"local-path"}


# ── credentials ───────────────────────────────────────────────────────────────

_EXTRA_SECRETS = {
    "authorization-token": "Authorization: token " + "abcdef1234567890",
    "bare-bearer": "Bearer " + "abcdefghijklmnop1234",
    "password-assign": "password=" + "hunter2",
    "env-export": "export DB_PASSWORD='" + "s3cr3t!!" + "'",
    "api-key-header": "X-Api-Key: " + "s3cr3tvalue123",
    "cookie-header": "Cookie: " + "sid=abc123; theme=dark",
    "google-key": "AIza" + "SyA1234567890abcdefghijklmnopqrstuv",
    "aws-session": "ASIA" + "IOSFODNN7EXAMPLE",
    "npm-token": "npm" + "_" + "a" * 36,
    "hf-token": "hf" + "_" + "b" * 30,
    "aws-secret-assign": "AWS_SECRET_ACCESS_KEY=" + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "pgp-block": "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----\nlQOYBF\n-----END " + "PGP PRIVATE KEY BLOCK-----",
}


@pytest.mark.parametrize("secret", list(_EXTRA_SECRETS.values()), ids=list(_EXTRA_SECRETS))
def test_more_credential_shapes_are_replaced(mod, secret):
    out, found = run(mod, f"before {secret}\nafter")
    assert out == "before [redacted-token]\nafter"
    assert counts(found) == {"redacted-token": 1}


def test_credential_match_does_not_eat_closing_delimiters(mod):
    out, _ = run(mod, "sent `Authorization: Bearer abc123def456` then")
    assert out == "sent `[redacted-token]` then"
    out, _ = run(mod, '{"h":"Authorization: Bearer abc123def456"}')
    assert out == '{"h":"[redacted-token]"}'


def test_assignment_credential_pass_is_idempotent(mod):
    first, _ = run(mod, "password=hunter2 and token: abc12345")
    second, again = run(mod, first)
    assert second == first and not again


# ── hosts, emails, boundaries, normalization ─────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("grafana.acme.co is down", "[internal-host] is down"),
        ("PROD-DB.ACME.COM is down", "[internal-host] is down"),
        ("_db.prod.acme.com_ italics", "_[internal-host]_ italics"),
        ("host:db.acme.internal up", "host:[internal-host] up"),
    ],
)
def test_more_bare_host_shapes_are_replaced(mod, text, expected):
    out, _ = run(mod, text)
    assert out == expected


def test_log_call_and_package_versions_are_not_hosts_or_emails(mod):
    text = 'logger.info("hi") with left-pad@1.3.0 and @types/node@20.1.0'
    out, found = run(mod, text)
    assert out == text and not found


def test_deny_terms_match_inside_snake_case_identifiers(mod):
    out, _ = run(mod, "set acmecorp_prod_db and ACMECORP_TOKEN_x", deny=(("org", "acmecorp"),))
    assert out == "set [internal-org]_prod_db and [internal-org]_TOKEN_x"


@pytest.mark.parametrize("invisible", ["\u00ad", "\u200e", "\u202a"], ids=["soft-hyphen", "lrm", "lre"])
def test_format_characters_cannot_hide_a_token(mod, invisible):
    split = GH_TOKEN[:4] + invisible + GH_TOKEN[4:]
    out, found = run(mod, f"leak {split} here")
    assert out == "leak [redacted-token] here"
    assert counts(found) == {"redacted-token": 1}


def test_nfkc_is_applied_before_matching(mod):
    fullwidth = "\uff47\uff48\uff50\uff3f" + _BODY  # fullwidth "ghp_" prefix
    out, _ = run(mod, f"leak {fullwidth} here")
    assert out == "leak [redacted-token] here"
    out, _ = run(mod, "path \uff0fUsers\uff0falice\uff0fx here")
    assert out == "path [local-path] here"


def test_preserve_never_exempts_paths_ips_or_usernames(mod):
    line = "fails on /Users/alice/proj/x.py at 10.1.2.3"
    out, _ = run(mod, line, preserve=(line,))
    assert out == "fails on [local-path] at [internal-ip]"
    out, _ = run(mod, "by alice here", deny=(("user", "alice"),), preserve=("by alice here",))
    assert out == "by [local-user] here"


# ── CLI hardening ─────────────────────────────────────────────────────────────


def test_write_phase_failure_removes_the_destination_already_written(tmp_path):
    good = tmp_path / "good.draft"
    good.write_text("fine", encoding="utf-8")
    out1 = tmp_path / "out1"
    result = run_cli(
        [
            "--no-auto-context",
            "--field", "a", str(good), str(out1),
            "--field", "b", str(good), str(tmp_path / "missing-dir" / "out2"),
        ],
        tmp_path,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert not out1.exists()


def test_abbreviated_field_flag_is_refused_and_still_clears_the_destination(tmp_path):
    out = tmp_path / "o.md"
    out.write_text("stale", encoding="utf-8")
    result = run_cli(["--no-auto-context", "--fi", "body", str(tmp_path / "d.md"), str(out)], tmp_path)
    assert result.returncode != 0
    assert result.stdout == ""
    assert not out.exists()


def test_bad_deny_spec_error_does_not_echo_the_term(tmp_path):
    a = tmp_path / "a"
    a.write_text("x", encoding="utf-8")
    result = run_cli(
        ["--no-auto-context", "--deny", "orgg=SECRETTERM", "--field", "body", str(a), str(tmp_path / "o")],
        tmp_path,
    )
    assert result.returncode != 0
    assert "SECRETTERM" not in result.stderr and "SECRETTERM" not in result.stdout


def test_auto_context_handles_nested_remote_paths(mod, tmp_path):
    home = tmp_path / "home" / "zelda"
    home.mkdir(parents=True)
    repo = tmp_path / "work" / "checkout"
    repo.mkdir(parents=True)
    _git(["init", "-q"], repo)
    _git(["remote", "add", "origin", "git@gitlab.example.com:globexgrp/sub/ledger-core.git"], repo)
    terms, _ = mod.collect_auto_context(
        home=home, cwd=repo, target_repo=TARGET, hostname="localhost", memory_names=lambda: []
    )
    assert ("internal-org", "globexgrp") in terms
    assert ("internal-repo", "ledger-core") in terms

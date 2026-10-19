"""Behavioural tests for bin/swe-workbench-redact.

Every fixture value is fake: credential-shaped strings are assembled from parts, hosts use
reserved example domains, and "local" paths use made-up usernames. No test reads a real
home directory, hostname or repository.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
REDACT = ROOT / "bin" / "swe-workbench-redact"
RESULT_CHECK = ROOT / "bin" / "swe-workbench-result-check"
TARGET = "lugassawan/swe-workbench"

_BODY = "abcdefgh12345678"
GH_TOKEN = "ghp" + "_" + _BODY
SK_TOKEN = "sk" + "-" + _BODY
SLACK_TOKEN = "xoxb" + "-" + _BODY
GITLAB_TOKEN = "glpat" + "-" + _BODY
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
BEARER = "Authorization: Bearer " + "abc123def456"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + "." + "c2lnbmF0dXJlMTIzNDU2"
PRIVATE_KEY = (
    "-----BEGIN " + "RSA PRIVATE KEY-----\n" + "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n"
    "-----END " + "RSA PRIVATE KEY-----"
)


def load_module():
    """Import the extensionless script for pure-core unit tests."""
    if str(REDACT.parent) not in sys.path:
        sys.path.insert(0, str(REDACT.parent))
    loader = importlib.machinery.SourceFileLoader("swe_workbench_redact_script", str(REDACT))
    spec = importlib.util.spec_from_loader("swe_workbench_redact_script", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return load_module()


def make_rules(mod, **overrides):
    base = dict(
        target_repo=TARGET,
        allow=(),
        deny=(),
        preserve=(),
        plugin_names=("report-issue", "workflow-commit-and-pr", "product-manager"),
    )
    base.update(overrides)
    return mod.Rules.build(**base)


def run(mod, text, **overrides):
    return mod.redact(text, make_rules(mod, **overrides))


def counts(counter):
    return dict(counter)


def run_cli(args, cwd, env_extra=None):
    env = {**_CLEAN_ENV, **(env_extra or {})}
    return subprocess.run(
        [str(REDACT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def envelope_of(result):
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["schema"] == "swb.redact/1"
    return parsed


# ── per-category regressions ──────────────────────────────────────────────────


def test_email_is_replaced(mod):
    out, found = run(mod, "ping jane.doe@corp.example.com about it")
    assert out == "ping [internal-email] about it"
    assert counts(found) == {"internal-email": 1}


def test_unknown_url_is_replaced_whole(mod):
    out, found = run(mod, "see https://wiki.corp.example.com/pages/42?x=1 now")
    assert out == "see [internal-host] now"
    assert counts(found) == {"internal-host": 1}


def test_markdown_link_syntax_survives(mod):
    out, _ = run(mod, "read [the page](https://wiki.corp.example.com/a) first")
    assert out == "read [the page]([internal-host]) first"


def test_bare_internal_hostname_is_replaced(mod):
    out, found = run(mod, "connect to db01.prod.internal:5432 please")
    assert out == "connect to [internal-host] please"
    assert counts(found) == {"internal-host": 1}


def test_ipv4_is_replaced(mod):
    out, found = run(mod, "host 10.20.30.40 refused")
    assert out == "host [internal-ip] refused"
    assert counts(found) == {"internal-ip": 1}


def test_ipv6_is_replaced(mod):
    out, found = run(mod, "peer 2001:db8::8a2e:370:7334 refused")
    assert out == "peer [internal-ip] refused"
    assert counts(found) == {"internal-ip": 1}


@pytest.mark.parametrize(
    "secret",
    [GH_TOKEN, SK_TOKEN, SLACK_TOKEN, GITLAB_TOKEN, AWS_KEY, BEARER, JWT, PRIVATE_KEY],
    ids=["github", "sk", "slack", "gitlab", "aws", "bearer", "jwt", "private-key"],
)
def test_each_credential_family_is_replaced(mod, secret):
    out, found = run(mod, f"before {secret} after")
    assert out == "before [redacted-token] after"
    assert counts(found) == {"redacted-token": 1}


@pytest.mark.parametrize(
    "path",
    [
        "/Users/jdoe/Projects/acme/src/app.py",
        "/home/jdoe/work/notes.md",
        "C:\\Users\\jdoe\\Documents\\notes.txt",
        "/private/var/folders/ab/cd1234/T/scratch.txt",
        "/var/folders/ab/cd1234/T/scratch.txt",
    ],
)
def test_local_paths_are_replaced_whole(mod, path):
    out, found = run(mod, f"opened {path} yesterday")
    assert out == "opened [local-path] yesterday"
    assert counts(found) == {"local-path": 1}


@pytest.mark.parametrize(
    "text",
    ["[[rimba-bare-repo]]", "feedback_rimba_bare_repo.md", "MEMORY.md", "project_x_thing.md"],
)
def test_memory_references_are_replaced(mod, text):
    out, found = run(mod, f"per {text} we learned")
    assert out == "per [memory-ref] we learned"
    assert counts(found) == {"memory-ref": 1}


def test_deny_listed_memory_name_is_replaced(mod):
    out, found = run(mod, "see rimba-bare-repo-notes for why", deny=(("memory", "rimba-bare-repo-notes"),))
    assert out == "see [memory-ref] for why"
    assert counts(found) == {"memory-ref": 1}


def test_service_identifier_is_replaced(mod):
    out, found = run(mod, "the payments-service call timed out")
    assert out == "the [internal-service] call timed out"
    assert counts(found) == {"internal-service": 1}


def test_cross_repo_reference_is_replaced(mod):
    out, found = run(mod, "tracked in acme/ledger#123 upstream")
    assert out == "tracked in [internal-repo] upstream"
    assert counts(found) == {"internal-repo": 1}


@pytest.mark.parametrize(
    "category,placeholder",
    [("org", "internal-org"), ("repo", "internal-repo"), ("user", "local-user"), ("host", "internal-host")],
)
def test_deny_terms_map_to_their_placeholder(mod, category, placeholder):
    out, found = run(mod, "talked to Acmecorp today", deny=((category, "acmecorp"),))
    assert out == f"talked to [{placeholder}] today"
    assert counts(found) == {placeholder: 1}


def test_deny_term_does_not_match_inside_a_longer_word(mod):
    out, found = run(mod, "the macmecorpse thing", deny=(("org", "acmecorp"),))
    assert out == "the macmecorpse thing"
    assert not found


# ── per-category false positives ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "see https://github.com/lugassawan/swe-workbench/issues/776 for context",
        "repo https://github.com/lugassawan/swe-workbench",
        "see github.com/lugassawan/swe-workbench/pull/5 here",
        "cross ref lugassawan/swe-workbench#776 holds",
        "swe-workbench keeps its name",
        "run /swe-workbench:report-issue and the workflow-commit-and-pr skill",
        "ask the product-manager agent",
        "docs at https://docs.python.org/3/library/pathlib.html are fine",
        "also docs.python.org and pypi.org and nodejs.org",
        "read https://docs.github.com/en/rest and https://cli.github.com/manual",
        "version 0.9.8.7 shipped",
        "at 12:30:45 the job ran",
        "loopback 127.0.0.1 and ::1 and localhost",
        "config under ~/.claude/plugins/cache works",
        "maintainer lugassawan owns it",
    ],
)
def test_allowed_text_is_untouched(mod, text):
    out, found = run(mod, text)
    assert out == text
    assert not found


def test_other_github_url_is_still_replaced(mod):
    out, found = run(mod, "see https://github.com/acme/ledger/issues/9 now")
    assert out == "see [internal-host] now"
    assert counts(found) == {"internal-host": 1}


def test_username_path_is_redacted_even_for_target_owner(mod):
    out, found = run(mod, "file at /Users/lugassawan/Workspaces/x.py")
    assert out == "file at [local-path]"
    assert counts(found) == {"local-path": 1}


def test_allow_term_restores_exact_span(mod):
    out, found = run(mod, "mail jane@corp.example.com", allow=("jane@corp.example.com",))
    assert out == "mail jane@corp.example.com"
    assert not found


def test_allow_term_restores_exact_host_of_a_url(mod):
    out, found = run(mod, "see https://wiki.corp.example.com/a", allow=("wiki.corp.example.com",))
    assert out == "see https://wiki.corp.example.com/a"
    assert not found


def test_allow_term_cannot_restore_a_credential(mod):
    out, found = run(mod, f"key {GH_TOKEN}", allow=(GH_TOKEN,))
    assert out == "key [redacted-token]"
    assert counts(found) == {"redacted-token": 1}


def test_preserve_span_is_skipped(mod):
    text = "I wrote payments-service myself and jane@corp.example.com too"
    out, found = run(mod, text, preserve=("payments-service myself",))
    assert out == "I wrote payments-service myself and [internal-email] too"
    assert counts(found) == {"internal-email": 1}


def test_credential_inside_preserved_span_still_fires(mod):
    text = f"typed {GH_TOKEN} by hand"
    out, found = run(mod, text, preserve=(f"typed {GH_TOKEN} by hand",))
    assert out == "typed [redacted-token] by hand"
    assert counts(found) == {"redacted-token": 1}


def test_deny_term_equal_to_target_owner_is_not_redacted(mod):
    out, found = run(mod, "owner lugassawan wrote this", deny=(("user", "lugassawan"),))
    assert out == "owner lugassawan wrote this"
    assert not found


# ── contract ──────────────────────────────────────────────────────────────────


def test_redaction_is_idempotent(mod):
    messy = "\n".join(
        [
            "mail jane@corp.example.com from 10.1.2.3",
            f"token {GH_TOKEN} and {BEARER}",
            "/Users/jdoe/proj/a.py and https://wiki.corp.example.com/a",
            "payments-service per [[some-note]] and acme/ledger#4",
            "see [internal-service] and [redacted-token]",
        ]
    )
    first, _ = run(mod, messy)
    second, again = run(mod, first)
    assert second == first
    assert not again


def test_email_inside_url_is_counted_once(mod):
    out, found = run(mod, "go to https://wiki.corp.example.com/?owner=jane@corp.example.com now")
    assert out == "go to [internal-host] now" or out == "go to [internal-email] now"
    assert sum(found.values()) == 1


def test_credential_inside_url_wins_the_label_and_is_counted_once(mod):
    out, found = run(mod, f"call https://wiki.corp.example.com/api?token={GH_TOKEN} now")
    assert "wiki.corp" not in out and GH_TOKEN not in out
    assert counts(found) == {"redacted-token": 1}


def test_zero_width_split_token_is_still_caught(mod):
    split = GH_TOKEN[:6] + "\u200b" + GH_TOKEN[6:10] + "\u2060" + GH_TOKEN[10:]
    out, found = run(mod, f"leak {split} here")
    assert out == "leak [redacted-token] here"
    assert counts(found) == {"redacted-token": 1}


def test_zero_width_characters_are_stripped_from_clean_text(mod):
    out, found = run(mod, "plain\u200b text\ufeff")
    assert out == "plain text"
    assert not found


def test_code_fences_are_scanned_and_fence_syntax_survives(mod):
    text = "```bash\ncurl https://wiki.corp.example.com/x\n```\n`10.0.0.5`"
    out, found = run(mod, text)
    assert out == "```bash\ncurl [internal-host]\n```\n`[internal-ip]`"
    assert counts(found) == {"internal-host": 1, "internal-ip": 1}


def test_existing_placeholders_are_not_rematched(mod):
    text = "the [internal-service] and [memory-ref] and [local-user] stay"
    out, found = run(mod, text)
    assert out == text
    assert not found


def test_plugin_name_with_service_suffix_is_allowed(mod):
    out, found = run(mod, "the billing-service helper", plugin_names=("billing-service",))
    assert out == "the billing-service helper"
    assert not found


# ── CLI ───────────────────────────────────────────────────────────────────────


def test_cli_writes_sanitized_sibling_and_leaves_draft_untouched(tmp_path):
    draft = tmp_path / "body.draft.md"
    out = tmp_path / "body.md"
    draft.write_text("mail jane@corp.example.com and 10.1.2.3\n", encoding="utf-8")
    result = run_cli(
        ["--no-auto-context", "--target-repo", TARGET, "--field", "body", str(draft), str(out)], tmp_path
    )
    parsed = envelope_of(result)
    assert out.read_text(encoding="utf-8") == "mail [internal-email] and [internal-ip]\n"
    assert draft.read_text(encoding="utf-8") == "mail jane@corp.example.com and 10.1.2.3\n"
    assert parsed["status"] == "ok"
    assert parsed["data"]["total"] == 2
    assert parsed["data"]["outputs"] == [str(out)]


def test_cli_envelope_has_counts_only_and_no_removed_value(tmp_path):
    secret_email = "jane.doe@corp.example.com"
    draft = tmp_path / "d.md"
    out = tmp_path / "o.md"
    draft.write_text(f"{secret_email} {GH_TOKEN} /Users/jdoe/x.py 10.9.8.7", encoding="utf-8")
    result = run_cli(["--no-auto-context", "--field", "body", str(draft), str(out)], tmp_path)
    parsed = envelope_of(result)
    for removed in (secret_email, GH_TOKEN, "jdoe", "10.9.8.7", "corp.example.com"):
        assert removed not in result.stdout
    assert parsed["data"]["summary"].startswith("4 replacement(s) — ")
    keys = {row["key"]: row["count"] for row in parsed["data"]["by_category"]}
    assert keys == {"internal-email": 1, "redacted-token": 1, "local-path": 1, "internal-ip": 1}


def test_cli_clean_input_reports_none_detected(tmp_path):
    draft = tmp_path / "d.md"
    out = tmp_path / "o.md"
    draft.write_text("nothing sensitive here\n", encoding="utf-8")
    parsed = envelope_of(run_cli(["--no-auto-context", "--field", "body", str(draft), str(out)], tmp_path))
    assert parsed["data"]["total"] == 0
    assert parsed["data"]["summary"] == "none detected"
    assert parsed["data"]["by_category"] == []
    assert out.read_text(encoding="utf-8") == "nothing sensitive here\n"


def test_cli_multi_field_reports_per_field_counts(tmp_path):
    files = {}
    for name, content in {
        "title": "crash on 10.0.0.1",
        "body": "mail a@corp.example.com and b@corp.example.com",
        "attachment-1": "clean",
    }.items():
        draft = tmp_path / f"{name}.draft"
        draft.write_text(content, encoding="utf-8")
        files[name] = (draft, tmp_path / f"{name}.out")
    args = ["--no-auto-context"]
    for name, (src, dst) in files.items():
        args += ["--field", name, str(src), str(dst)]
    parsed = envelope_of(run_cli(args, tmp_path))
    by_field = {row["key"]: row["count"] for row in parsed["data"]["by_field"]}
    assert by_field == {"title": 1, "body": 2, "attachment-1": 0}
    assert [row["key"] for row in parsed["data"]["by_field"]] == ["title", "body", "attachment-1"]
    assert parsed["data"]["total"] == 3
    assert files["title"][1].read_text(encoding="utf-8") == "crash on [internal-ip]"


def test_cli_pipes_through_result_check(tmp_path):
    draft = tmp_path / "d.md"
    out = tmp_path / "o.md"
    draft.write_text("mail jane@corp.example.com", encoding="utf-8")
    produced = run_cli(["--no-auto-context", "--field", "body", str(draft), str(out)], tmp_path)
    checked = subprocess.run(
        [str(RESULT_CHECK), "swb.redact/1"],
        input=produced.stdout,
        capture_output=True,
        text=True,
        env=dict(_CLEAN_ENV),
    )
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout == produced.stdout


def test_cli_second_run_over_output_reports_none_detected(tmp_path):
    draft = tmp_path / "d.md"
    first = tmp_path / "o1.md"
    second = tmp_path / "o2.md"
    draft.write_text(f"{GH_TOKEN} jane@corp.example.com 10.0.0.9", encoding="utf-8")
    run_cli(["--no-auto-context", "--field", "body", str(draft), str(first)], tmp_path)
    parsed = envelope_of(run_cli(["--no-auto-context", "--field", "body", str(first), str(second)], tmp_path))
    assert parsed["data"]["summary"] == "none detected"
    assert second.read_text(encoding="utf-8") == first.read_text(encoding="utf-8")


def test_cli_allow_deny_and_preserve_files(tmp_path):
    draft = tmp_path / "d.md"
    out = tmp_path / "o.md"
    preserve = tmp_path / "preserve.txt"
    deny = tmp_path / "deny.txt"
    draft.write_text("Acmecorp met bob@corp.example.com and jane@corp.example.com", encoding="utf-8")
    preserve.write_text("bob@corp.example.com\n", encoding="utf-8")
    deny.write_text("# comment\norg=acmecorp\n\n", encoding="utf-8")
    result = run_cli(
        [
            "--no-auto-context",
            "--deny-file", str(deny),
            "--preserve-file", str(preserve),
            "--allow", "nothing-matches-this",
            "--field", "body", str(draft), str(out),
        ],
        tmp_path,
    )
    envelope_of(result)
    assert out.read_text(encoding="utf-8") == "[internal-org] met bob@corp.example.com and [internal-email]"


def test_cli_deny_flag_adds_terms(tmp_path):
    draft = tmp_path / "d.md"
    out = tmp_path / "o.md"
    draft.write_text("Acmecorp shipped", encoding="utf-8")
    envelope_of(run_cli(["--no-auto-context", "--deny", "org=acmecorp", "--field", "body", str(draft), str(out)], tmp_path))
    assert out.read_text(encoding="utf-8") == "[internal-org] shipped"


# ── fail closed ───────────────────────────────────────────────────────────────


def test_missing_source_fails_closed_with_empty_stdout_and_no_output(tmp_path):
    out = tmp_path / "o.md"
    result = run_cli(["--no-auto-context", "--field", "body", str(tmp_path / "missing.md"), str(out)], tmp_path)
    assert result.returncode != 0
    assert result.stdout == ""
    assert not out.exists()


def test_failure_removes_a_stale_destination_from_an_earlier_run(tmp_path):
    out = tmp_path / "o.md"
    out.write_text("stale sanitized text from an earlier run", encoding="utf-8")
    result = run_cli(["--no-auto-context", "--field", "body", str(tmp_path / "missing.md"), str(out)], tmp_path)
    assert result.returncode != 0
    assert not out.exists()


def test_bad_argument_still_removes_stale_destination(tmp_path):
    out = tmp_path / "o.md"
    out.write_text("stale", encoding="utf-8")
    result = run_cli(["--no-auto-context", "--bogus-flag", "--field", "body", str(tmp_path / "d.md"), str(out)], tmp_path)
    assert result.returncode != 0
    assert result.stdout == ""
    assert not out.exists()


def test_second_field_failure_leaves_no_destination_at_all(tmp_path):
    good = tmp_path / "good.draft"
    good.write_text("fine", encoding="utf-8")
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    result = run_cli(
        [
            "--no-auto-context",
            "--field", "a", str(good), str(out1),
            "--field", "b", str(tmp_path / "missing"), str(out2),
        ],
        tmp_path,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert not out1.exists() and not out2.exists()


def test_non_utf8_source_fails_closed(tmp_path):
    draft = tmp_path / "d.bin"
    draft.write_bytes(b"\xff\xfe\x00bad")
    out = tmp_path / "o"
    result = run_cli(["--no-auto-context", "--field", "body", str(draft), str(out)], tmp_path)
    assert result.returncode != 0
    assert result.stdout == ""
    assert not out.exists()


def test_source_equal_to_destination_is_refused_and_draft_survives(tmp_path):
    draft = tmp_path / "d.md"
    draft.write_text("jane@corp.example.com", encoding="utf-8")
    result = run_cli(["--no-auto-context", "--field", "body", str(draft), str(draft)], tmp_path)
    assert result.returncode != 0
    assert result.stdout == ""
    assert draft.read_text(encoding="utf-8") == "jane@corp.example.com"


def test_duplicate_field_names_are_refused(tmp_path):
    a = tmp_path / "a"
    a.write_text("x", encoding="utf-8")
    result = run_cli(
        ["--no-auto-context", "--field", "body", str(a), str(tmp_path / "o1"), "--field", "body", str(a), str(tmp_path / "o2")],
        tmp_path,
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_bad_target_repo_is_refused(tmp_path):
    a = tmp_path / "a"
    a.write_text("x", encoding="utf-8")
    result = run_cli(["--no-auto-context", "--target-repo", "not-a-slug", "--field", "body", str(a), str(tmp_path / "o")], tmp_path)
    assert result.returncode != 0
    assert result.stdout == ""


def test_bad_deny_spec_is_refused(tmp_path):
    a = tmp_path / "a"
    a.write_text("x", encoding="utf-8")
    result = run_cli(["--no-auto-context", "--deny", "nonsense=foo", "--field", "body", str(a), str(tmp_path / "o")], tmp_path)
    assert result.returncode != 0
    assert result.stdout == ""


def test_help_exits_zero(tmp_path):
    result = run_cli(["--help"], tmp_path)
    assert result.returncode == 0
    assert "swe-workbench-redact" in result.stdout


# ── auto-context adapter ──────────────────────────────────────────────────────


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, env=dict(_CLEAN_ENV))


def test_auto_context_collects_user_org_repo_and_memory_terms(mod, tmp_path):
    home = tmp_path / "home" / "zelda"
    home.mkdir(parents=True)
    repo = tmp_path / "work" / "ledgerapp"
    repo.mkdir(parents=True)
    _git(["init", "-q"], repo)
    _git(["remote", "add", "origin", "git@github.com:globexcorp/ledger-core.git"], repo)

    terms, warnings = mod.collect_auto_context(
        home=home,
        cwd=repo,
        target_repo=TARGET,
        hostname="buildbox-07.corp.example.com",
        memory_names=lambda: ["feedback_rimba_bare_repo", "project_776_notes"],
    )

    assert ("local-user", "zelda") in terms
    assert ("internal-host", "buildbox-07") in terms
    assert ("internal-org", "globexcorp") in terms
    assert ("internal-repo", "ledger-core") in terms
    assert ("internal-repo", "ledgerapp") in terms
    assert ("memory-ref", "feedback_rimba_bare_repo") in terms
    assert warnings == []


def test_auto_context_skips_terms_that_equal_the_target(mod, tmp_path):
    home = tmp_path / "home" / "lugassawan"
    home.mkdir(parents=True)
    repo = tmp_path / "swe-workbench"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["remote", "add", "origin", "https://github.com/lugassawan/swe-workbench.git"], repo)

    terms, _ = mod.collect_auto_context(
        home=home, cwd=repo, target_repo=TARGET, hostname="localhost", memory_names=lambda: []
    )

    assert terms == []


def test_auto_context_lookup_failures_become_warnings_not_errors(mod, tmp_path):
    home = tmp_path / "home" / "zelda"
    home.mkdir(parents=True)
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()

    def boom():
        raise OSError("memory store unreadable")

    terms, warnings = mod.collect_auto_context(
        home=home, cwd=not_a_repo, target_repo=TARGET, hostname="buildbox-07", memory_names=boom
    )

    assert ("local-user", "zelda") in terms
    assert {w["code"] for w in warnings} == {"auto-context-unavailable"}


def test_cli_auto_context_redacts_the_fake_home_username(tmp_path):
    home = tmp_path / "home" / "zelda"
    home.mkdir(parents=True)
    draft = tmp_path / "d.md"
    out = tmp_path / "o.md"
    draft.write_text("reported by zelda on a laptop", encoding="utf-8")
    result = run_cli(
        ["--target-repo", TARGET, "--field", "body", str(draft), str(out)],
        tmp_path,
        env_extra={"HOME": str(home)},
    )
    envelope_of(result)
    assert out.read_text(encoding="utf-8") == "reported by [local-user] on a laptop"


def test_cli_no_auto_context_leaves_the_username_alone(tmp_path):
    home = tmp_path / "home" / "zelda"
    home.mkdir(parents=True)
    draft = tmp_path / "d.md"
    out = tmp_path / "o.md"
    draft.write_text("reported by zelda on a laptop", encoding="utf-8")
    result = run_cli(
        ["--no-auto-context", "--field", "body", str(draft), str(out)], tmp_path, env_extra={"HOME": str(home)}
    )
    envelope_of(result)
    assert out.read_text(encoding="utf-8") == "reported by zelda on a laptop"

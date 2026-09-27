"""Behavioral tests for bin/swe-workbench-memory.

Every test is hermetic: both SWE_WORKBENCH_MEMORY_STATE_DIR (Pi store root override)
and HOME (Claude store root) point into tmp dirs, and XDG_STATE_HOME is unset —
no test ever touches a real ~/.claude or real XDG state tree.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
RUNTIME = ROOT / "bin" / "swe-workbench-memory"
RESULT_CHECK = ROOT / "bin" / "swe-workbench-result-check"


def load_runtime_module():
    """Import the extensionless bin/swe-workbench-memory for in-process probes."""
    loader = importlib.machinery.SourceFileLoader(
        "swe_workbench_memory_runtime", str(RUNTIME)
    )
    spec = importlib.util.spec_from_loader("swe_workbench_memory_runtime", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass field resolution looks the module up
    loader.exec_module(module)
    return module


def run_memory(args, cwd, input_text=None):
    env = dict(_CLEAN_ENV)
    env["SWE_WORKBENCH_MEMORY_STATE_DIR"] = str(Path(cwd) / "state")
    env["HOME"] = str(Path(cwd) / "home")
    env.pop("XDG_STATE_HOME", None)
    env.pop("SWE_WORKBENCH_HANDOFF_STATE_DIR", None)
    return subprocess.run(
        [str(RUNTIME), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        input=input_text,
    )


def envelope(result):
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["schema"] == "swb.memory/1"
    assert isinstance(parsed["warnings"], list)
    return parsed


_runtime_module = None


def _runtime():
    """Load bin/swe-workbench-memory once and reuse it — claude_slug() is pure (no I/O),
    so sharing one loaded module across slug_of() calls is safe."""
    global _runtime_module
    if _runtime_module is None:
        _runtime_module = load_runtime_module()
    return _runtime_module


def slug_of(path) -> str:
    """Delegates to the runtime's OWN claude_slug() — never an independently mirrored
    recipe. Behavioral tests below only need "the same string the runtime computes for
    this path", not a from-scratch reimplementation; recipe correctness itself is pinned
    by test_claude_slug_matches_pinned_fixtures below against literal, hardcoded output
    from the real Claude Code JS recipe (never derived from this runtime)."""
    return _runtime().claude_slug(Path(path).resolve())


def legacy_slug_of(path) -> str:
    return str(Path(path).resolve()).replace("/", "-").lstrip("-")


def write_store(store_dir: Path, entries) -> None:
    """Fabricate a Claude-format memory store using the runtime's OWN on-disk naming
    convention (entry_file_name), so identity-dedup (type + stem + raw-name hash) behaves
    the same for fabricated fixtures as it does for real record()-written entries.
    entries: [(name, description, type)] newest-first."""
    store_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Memory index", ""]
    for name, description, entry_type in entries:
        file_name = _runtime().entry_file_name(entry_type, name)
        (store_dir / file_name).write_text(
            "---\n"
            f"name: {name}\n"
            f'description: "{description}"\n'
            "metadata:\n"
            "  node_type: memory\n"
            f"  type: {entry_type}\n"
            "---\n"
            "\n"
            f"body of {name}\n",
            encoding="utf-8",
        )
        lines.append(f"- [{name}]({file_name}) — {description}")
    (store_dir / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def tree_hash(root: Path) -> str:
    if not root.exists():
        return "absent"
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def worktree_repo(tmp_path):
    """A real git repo at tmp/main-repo plus a linked worktree at tmp/wt."""
    main = tmp_path / "main-repo"
    main.mkdir()
    wt = tmp_path / "wt"

    def git(*args, cwd=None):
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd or main),
            capture_output=True,
            text=True,
            env=dict(_CLEAN_ENV),
        )
        assert result.returncode == 0, result.stderr
        return result

    git("init", str(main))
    git("commit", "--allow-empty", "-m", "x")
    git("worktree", "add", str(wt), "-b", "feat")
    return main, wt


# ── Anchoring + slug recipe (plan Step 1) ────────────────────────────────────


def test_non_git_cwd_falls_back_to_cwd_slug(tmp_path):
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    out = run_memory(["show", "--as", "pi"], cwd=plain)
    data = envelope(out)["data"]
    assert data["anchor"]["slug"] == slug_of(plain)
    assert data["anchor"]["main_checkout"] is None


# Literal fixtures pinned against the real Claude Code JS recipe via `node -e` — never
# derived from this runtime, so a regression in claude_slug() cannot silently self-validate.
CLAUDE_SLUG_FIXTURES = [
    (
        "/Users/dev/code/example-repo",
        "-Users-dev-code-example-repo",
    ),
    (
        "/Users/dev/My Projects/foo_bar.baz qux",
        "-Users-dev-My-Projects-foo-bar-baz-qux",
    ),
    (
        "/Users/dev/code/" + "a" * 200 + "/tail",
        "-Users-dev-code-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-yy9ryl",
    ),
    (
        "/Users/dev/code/example-\U0001f600-repo",
        "-Users-dev-code-example----repo",
    ),
]


def test_claude_slug_matches_pinned_real_recipe_fixtures():
    module = _runtime()
    for path, expected_slug in CLAUDE_SLUG_FIXTURES:
        assert module.claude_slug(Path(path)) == expected_slug, path


def test_claude_slug_keeps_leading_dash_unlike_legacy_recipe(tmp_path):
    module = _runtime()
    path = Path("/a/b")
    assert module.claude_slug(path) == "-a-b"
    assert module.legacy_pi_slug(path) == "a-b"


def test_claude_slug_handles_lone_surrogate_from_non_utf8_path_component():
    """A directory name holding non-UTF-8 bytes decodes (PEP 383, os.fsdecode) to a lone
    surrogate codepoint — a real POSIX path this runtime must not crash on merely resolving
    an anchor for. str.encode("utf-16-le") without errors="surrogatepass" raises
    UnicodeEncodeError (a ValueError, not a MemoryError — main()'s `except MemoryError` would
    never catch it), turning every subcommand into a raw traceback for this one input class."""
    import os

    module = _runtime()
    path = Path(os.fsdecode(b"/tmp/foo-\xff-bar"))
    slug = module.claude_slug(path)
    assert "�" not in slug  # never silently mangled into a replacement character either
    assert slug.startswith("-tmp-foo-")
    assert slug.endswith("-bar")


def test_git_worktree_anchors_to_main_checkout(tmp_path, worktree_repo):
    main, wt = worktree_repo
    out = run_memory(["show", "--as", "pi"], cwd=wt)
    data = envelope(out)["data"]
    assert data["anchor"]["slug"] == slug_of(main)
    assert data["anchor"]["main_checkout"] == str(main.resolve())


def test_plain_repo_anchors_to_repo_root(tmp_path, worktree_repo):
    main, _ = worktree_repo
    out = run_memory(["show", "--as", "pi"], cwd=main)
    data = envelope(out)["data"]
    assert data["anchor"]["slug"] == slug_of(main)
    assert data["anchor"]["main_checkout"] == str(main.resolve())


def test_dual_slug_claude_read_merges_main_first(worktree_repo):
    main, wt = worktree_repo
    home = wt / "home"
    write_store(
        home / ".claude" / "projects" / slug_of(main) / "memory",
        [
            ("keep-builds-green", "Never merge on red", "feedback"),
            ("slug-format", "Use the readable slug", "project"),
        ],
    )
    write_store(
        home / ".claude" / "projects" / slug_of(wt) / "memory",
        [
            ("worktree-only", "Seen only from the worktree slug", "feedback"),
            ("keep-builds-green", "Duplicate by basename", "feedback"),
        ],
    )
    out = run_memory(["show", "--as", "pi"], cwd=wt)
    parsed = envelope(out)
    claude_entries = [e for e in parsed["data"]["entries"] if e["store"] == "claude"]
    assert [e["name"] for e in claude_entries] == [
        "keep-builds-green",
        "slug-format",
        "worktree-only",
    ]
    assert [e["order"] for e in claude_entries] == [0, 1, 0]
    expected_file = _runtime().entry_file_name("feedback", "keep-builds-green")
    assert [e["file"] for e in claude_entries].count(expected_file) == 1
    # Entries carry an absolute per-entry path to the store they actually live in —
    # store-path + basename composition would resolve worktree-slug entries wrongly.
    by_name = {e["name"]: e for e in claude_entries}
    for entry in claude_entries:
        assert Path(entry["path"]).is_file()
    cwd_memory = home / ".claude" / "projects" / slug_of(wt) / "memory"
    main_memory = home / ".claude" / "projects" / slug_of(main) / "memory"
    assert Path(by_name["worktree-only"]["path"]).is_relative_to(cwd_memory)
    assert Path(by_name["keep-builds-green"]["path"]).is_relative_to(main_memory)
    stores = parsed["data"]["stores"]
    assert stores["claude_cwd"] == {"path": str(cwd_memory), "exists": True}


def test_claude_cwd_merge_never_collapses_non_generated_filenames_by_prefix(worktree_repo):
    """Claude Code's own natively-written memory files don't follow entry_file_name()'s
    {type}_{stem}_{hash8}_{date8}.md shape — _entry_identity must never strip a trailing
    word from such a filename as if it were a date digest, or two genuinely distinct
    entries sharing a name prefix silently collapse into one."""
    main, wt = worktree_repo
    home = wt / "home"
    main_memory = home / ".claude" / "projects" / slug_of(main) / "memory"
    cwd_memory = home / ".claude" / "projects" / slug_of(wt) / "memory"
    main_memory.mkdir(parents=True)
    cwd_memory.mkdir(parents=True)
    (main_memory / "feedback_workflow_bug.md").write_text(
        "---\nname: workflow-bug\ndescription: \"A workflow bug\"\nmetadata:\n"
        "  node_type: memory\n  type: feedback\n---\nbody\n",
        encoding="utf-8",
    )
    (main_memory / "MEMORY.md").write_text(
        "# Memory index\n\n- [workflow-bug](feedback_workflow_bug.md) — A workflow bug\n",
        encoding="utf-8",
    )
    (cwd_memory / "feedback_workflow_fix.md").write_text(
        "---\nname: workflow-fix\ndescription: \"A workflow fix\"\nmetadata:\n"
        "  node_type: memory\n  type: feedback\n---\nbody\n",
        encoding="utf-8",
    )
    (cwd_memory / "MEMORY.md").write_text(
        "# Memory index\n\n- [workflow-fix](feedback_workflow_fix.md) — A workflow fix\n",
        encoding="utf-8",
    )
    out = run_memory(["show", "--as", "pi"], cwd=wt)
    parsed = envelope(out)
    claude_names = {e["name"] for e in parsed["data"]["entries"] if e["store"] == "claude"}
    assert claude_names == {"workflow-bug", "workflow-fix"}


def test_pi_legacy_slug_store_merges_new_first_and_dedupes_by_identity(tmp_path):
    """A Pi store written before this fix (legacy_pi_slug: replace('/','-').lstrip('-'))
    is still discovered and merged — new store first, legacy second, deduped by identity
    so a re-record under the new slug wins over its legacy-store predecessor."""
    new_store = tmp_path / "state" / slug_of(tmp_path)
    legacy_store = tmp_path / "state" / legacy_slug_of(tmp_path)
    assert new_store != legacy_store
    write_store(
        new_store,
        [("new-only", "Written after the fix", "feedback")],
    )
    write_store(
        legacy_store,
        [
            ("legacy-only", "Written before the fix", "feedback"),
            ("new-only", "Stale legacy copy", "feedback"),
        ],
    )
    out = run_memory(["show", "--as", "pi"], cwd=tmp_path)
    parsed = envelope(out)
    pi_entries = [e for e in parsed["data"]["entries"] if e["store"] == "pi"]
    assert [e["name"] for e in pi_entries] == ["new-only", "legacy-only"]
    assert [e["description"] for e in pi_entries] == [
        "Written after the fix",
        "Written before the fix",
    ]
    stores = parsed["data"]["stores"]
    assert stores["pi_legacy"] == {"path": str(legacy_store), "exists": True}


def test_pi_record_never_writes_to_legacy_slug_store(tmp_path):
    legacy_store = tmp_path / "state" / legacy_slug_of(tmp_path)
    write_store(legacy_store, [("old", "d", "feedback")])
    before = tree_hash(legacy_store)
    out = run_memory(
        ["record", "--as", "pi", "--name", "fresh", "--description", "d"],
        cwd=tmp_path,
        input_text="b",
    )
    envelope(out)
    assert tree_hash(legacy_store) == before
    assert pi_store_dir(tmp_path) != legacy_store
    assert (pi_store_dir(tmp_path) / "MEMORY.md").is_file()


# ── render --other-only ──────────────────────────────────────────────────


def test_render_other_only_drops_own_section_in_plain_repo(tmp_path, both_stores):
    """In a plain repo (no worktree), Claude Code's own native memory feature already
    covers the ENTIRE own store (cwd_slug == slug) — --other-only must drop it in full."""
    plain = run_memory(["render", "--as", "claude"], cwd=tmp_path)
    both = envelope(plain)["data"]["markdown"]
    assert "## Claude Code memory" in both

    other_only = run_memory(["render", "--as", "claude", "--other-only"], cwd=tmp_path)
    markdown = envelope(other_only)["data"]["markdown"]
    assert "## Claude Code memory" not in markdown
    assert "## Pi memory" in markdown
    assert "pi-entry" in markdown


def test_render_other_only_keeps_main_slug_entries_in_worktree(worktree_repo):
    """In a worktree, Claude Code's native feature only covers the cwd-slug store — the
    main-checkout store is invisible to it natively, so --other-only must still render it."""
    main, wt = worktree_repo
    home = wt / "home"
    write_store(
        home / ".claude" / "projects" / slug_of(main) / "memory",
        [("main-only", "Lives at the main checkout slug", "feedback")],
    )
    write_store(
        home / ".claude" / "projects" / slug_of(wt) / "memory",
        [("cwd-only", "Lives at the worktree cwd slug", "feedback")],
    )
    out = run_memory(["render", "--as", "claude", "--other-only"], cwd=wt)
    markdown = envelope(out)["data"]["markdown"]
    assert "main-only" in markdown
    assert "cwd-only" not in markdown


def test_render_other_only_is_a_noop_for_pi(tmp_path, both_stores):
    """Pi has no native memory feature to duplicate against — Pi always renders both,
    even if --other-only is passed."""
    without_flag = envelope(run_memory(["render", "--as", "pi"], cwd=tmp_path))["data"]
    with_flag = envelope(run_memory(["render", "--as", "pi", "--other-only"], cwd=tmp_path))[
        "data"
    ]
    assert with_flag["markdown"] == without_flag["markdown"]


# ── render (plan Step 5) ─────────────────────────────────────────────────────


@pytest.fixture
def both_stores(tmp_path):
    home = tmp_path / "home"
    write_store(
        home / ".claude" / "projects" / slug_of(tmp_path) / "memory",
        [
            ("claude-entry", "Claude wrote this", "feedback"),
            ("claude-two", "Second Claude entry", "project"),
        ],
    )
    pi_store = tmp_path / "state" / slug_of(tmp_path)
    write_store(
        pi_store,
        [
            ("pi-entry", "Pi wrote this", "feedback"),
            ("pi-two", "Second Pi entry", "project"),
        ],
    )
    return home, pi_store


def test_render_pi_puts_fence_first_and_own_store_first(tmp_path, both_stores):
    out = run_memory(["render", "--as", "pi"], cwd=tmp_path)
    data = envelope(out)["data"]
    markdown = data["markdown"]
    assert markdown.splitlines()[0].startswith(
        "The following is accumulated project memory"
    )
    assert "## Pi memory" in markdown
    assert "## Claude Code memory" in markdown
    assert markdown.index("## Pi memory") < markdown.index("## Claude Code memory")
    assert "pi-entry" in markdown and "Pi wrote this" in markdown
    assert "claude-entry" in markdown and "Claude wrote this" in markdown
    assert data["truncated"] is False
    assert data["dropped_entries"] == 0
    assert data["stores"]["claude"]["exists"] is True
    assert data["stores"]["pi"]["exists"] is True


def test_render_claude_own_store_first(tmp_path, both_stores):
    out = run_memory(["render", "--as", "claude"], cwd=tmp_path)
    markdown = envelope(out)["data"]["markdown"]
    assert markdown.index("## Claude Code memory") < markdown.index("## Pi memory")


def test_render_empty_stores_yields_empty_markdown(tmp_path):
    out = run_memory(["render", "--as", "pi"], cwd=tmp_path)
    parsed = envelope(out)
    assert parsed["data"]["markdown"] == ""
    assert parsed["status"] == "ok"


def test_render_caps_at_16kib_by_dropping_oldest_entries(tmp_path):
    store = tmp_path / "state" / slug_of(tmp_path)
    long_description = "x" * 600
    write_store(
        store, [(f"entry-{i:02d}", long_description, "feedback") for i in range(40)]
    )
    out = run_memory(["render", "--as", "pi"], cwd=tmp_path)
    data = envelope(out)["data"]
    assert data["truncated"] is True
    assert data["dropped_entries"] > 0
    assert len(data["markdown"].encode("utf-8")) <= 16384
    assert "entries omitted" in data["markdown"]
    # write order is newest-first: entry-00 is newest (kept), entry-39 is oldest (dropped first)
    assert "entry-00" in data["markdown"]
    assert "entry-39" not in data["markdown"]


def test_render_unreadable_entry_file_warns_and_continues(tmp_path):
    store = tmp_path / "state" / slug_of(tmp_path)
    write_store(
        store,
        [
            ("readable", "Fine to read", "feedback"),
            ("sealed", "Cannot read", "project"),
        ],
    )
    sealed_file = _runtime().entry_file_name("project", "sealed")
    (store / sealed_file).chmod(0o000)
    out = run_memory(["render", "--as", "pi"], cwd=tmp_path)
    parsed = envelope(out)
    assert parsed["status"] == "partial"
    unreadable = [w for w in parsed["warnings"] if w["code"] == "entry_unreadable"]
    assert unreadable and unreadable[0]["subject"].endswith(sealed_file)
    assert "readable" in parsed["data"]["markdown"]


# ── record + refusals (plan Step 8) ─────────────────────────────────────────


def pi_store_dir(cwd) -> Path:
    return Path(cwd) / "state" / slug_of(cwd)


def test_record_pi_writes_exact_on_disk_format(tmp_path):
    out = run_memory(
        [
            "record",
            "--as",
            "pi",
            "--name",
            "prefer-tdd",
            "--description",
            "Write the failing test first",
        ],
        cwd=tmp_path,
        input_text="Red green refactor\n",
    )
    data = envelope(out)["data"]
    assert data["store"] == "pi"
    store = pi_store_dir(tmp_path)
    assert data["index_path"] == str(store / "MEMORY.md")
    index = (store / "MEMORY.md").read_text(encoding="utf-8")
    assert index.splitlines()[0] == "# Memory index"
    entry_files = sorted(p.name for p in store.glob("feedback_prefer_tdd_*.md"))
    assert len(entry_files) == 1
    assert (
        index.splitlines()[2]
        == f"- [prefer-tdd]({entry_files[0]}) — Write the failing test first"
    )
    entry = (store / entry_files[0]).read_text(encoding="utf-8")
    assert "name: prefer-tdd\n" in entry
    assert 'description: "Write the failing test first"\n' in entry
    assert "metadata:\n" in entry
    assert "  node_type: memory\n" in entry
    assert "  type: feedback\n" in entry
    assert "  originHarness: pi\n" in entry
    assert "Red green refactor" in entry
    assert data["entry_path"] == str(store / entry_files[0])


def test_record_from_worktree_writes_main_slug_store(worktree_repo, tmp_path):
    main, wt = worktree_repo
    out = run_memory(
        [
            "record",
            "--as",
            "pi",
            "--name",
            "wt-note",
            "--description",
            "Anchored on main",
        ],
        cwd=wt,
        input_text="",
    )
    envelope(out)
    main_store = wt / "state" / slug_of(main)
    wt_store = wt / "state" / slug_of(wt)
    assert (main_store / "MEMORY.md").is_file()
    assert not wt_store.exists()
    assert (main_store / ".origin").read_text(encoding="utf-8").strip() == str(
        main.resolve()
    )


def test_record_newest_entry_inserted_above_existing(tmp_path):
    run_memory(
        ["record", "--as", "pi", "--name", "first", "--description", "d1"],
        cwd=tmp_path,
        input_text="",
    )
    run_memory(
        ["record", "--as", "pi", "--name", "second", "--description", "d2"],
        cwd=tmp_path,
        input_text="",
    )
    index = (pi_store_dir(tmp_path) / "MEMORY.md").read_text(encoding="utf-8")
    lines = index.splitlines()
    assert lines[0] == "# Memory index"
    assert lines[1] == ""
    assert lines[2].startswith("- [second](")
    assert lines[3].startswith("- [first](")


def test_record_same_name_replaces_index_line(tmp_path):
    # Same name + same date hash to the same entry file, so a re-record must leave
    # exactly one index line — the newest description wins, no stale duplicate.
    run_memory(
        ["record", "--as", "pi", "--name", "dup", "--description", "first version"],
        cwd=tmp_path,
        input_text="body one\n",
    )
    run_memory(
        ["record", "--as", "pi", "--name", "dup", "--description", "second version"],
        cwd=tmp_path,
        input_text="body two\n",
    )
    store = pi_store_dir(tmp_path)
    index = (store / "MEMORY.md").read_text(encoding="utf-8")
    entry_lines = [l for l in index.splitlines() if l.startswith("- [dup](")]
    assert len(entry_lines) == 1
    assert "second version" in entry_lines[0]
    entry_files = list(store.glob("feedback_dup_*.md"))
    assert len(entry_files) == 1
    body = entry_files[0].read_text(encoding="utf-8")
    assert "second version" in body
    assert "body two" in body
    assert "first version" not in body


def test_record_refuses_non_owning_store_both_directions(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    before_home = tree_hash(home)
    before_state = tree_hash(tmp_path / "state")
    out = run_memory(
        [
            "record",
            "--as",
            "pi",
            "--name",
            "x",
            "--description",
            "d",
            "--store",
            "claude",
        ],
        cwd=tmp_path,
        input_text="",
    )
    assert out.returncode == 1
    assert out.stdout == ""
    assert "refusing to write non-owning store" in out.stderr
    assert tree_hash(home) == before_home
    assert tree_hash(tmp_path / "state") == before_state

    out = run_memory(
        [
            "record",
            "--as",
            "claude",
            "--name",
            "x",
            "--description",
            "d",
            "--store",
            "pi",
        ],
        cwd=tmp_path,
        input_text="",
    )
    assert out.returncode == 1
    assert out.stdout == ""
    assert "refusing to write non-owning store" in out.stderr
    assert tree_hash(home) == before_home
    assert tree_hash(tmp_path / "state") == before_state


def test_record_refuses_secret_shaped_input(tmp_path):
    cases = [
        (
            [
                "record",
                "--as",
                "pi",
                "--name",
                "x",
                "--description",
                "token ghp_" + "A" * 20,
            ],
            "b",
        ),
        (
            ["record", "--as", "pi", "--name", "x", "--description", "d"],
            "Authorization: Bearer sk_" + "B" * 20,
        ),
        (
            [
                "record",
                "--as",
                "pi",
                "--name",
                "x",
                "--description",
                "anthropic sk-ant-api03-" + "C" * 24,
            ],
            "b",
        ),
        (
            ["record", "--as", "pi", "--name", "ghu_" + "D" * 20, "--description", "d"],
            "b",
        ),
        (
            [
                "record",
                "--as",
                "pi",
                "--name",
                "x",
                "--description",
                "openai sk-" + "E" * 24,
            ],
            "b",
        ),
        (
            [
                "record",
                "--as",
                "pi",
                "--name",
                "x",
                "--description",
                "openai sk-proj-" + "F" * 24,
            ],
            "b",
        ),
    ]
    for args, body in cases:
        out = run_memory(args, cwd=tmp_path, input_text=body)
        assert out.returncode == 1
        assert out.stdout == ""
        assert not pi_store_dir(tmp_path).exists()


def test_record_refuses_empty_name_or_description(tmp_path):
    for args in (
        ["record", "--as", "pi", "--name", "", "--description", "d"],
        ["record", "--as", "pi", "--name", "x", "--description", ""],
    ):
        out = run_memory(args, cwd=tmp_path, input_text="")
        assert out.returncode == 1
        assert out.stdout == ""
        assert not pi_store_dir(tmp_path).exists()


def test_record_refuses_invalid_type(tmp_path):
    # argparse's own choices= rejects this before cmd_record ever runs — exit code 2
    # (argparse's usage-error convention), not the InputError family's exit code 1.
    out = run_memory(
        [
            "record",
            "--as",
            "pi",
            "--name",
            "x",
            "--description",
            "d",
            "--type",
            "gossip",
        ],
        cwd=tmp_path,
        input_text="",
    )
    assert out.returncode == 2
    assert out.stdout == ""
    assert not pi_store_dir(tmp_path).exists()


def test_record_accepts_all_four_entry_types(tmp_path):
    for entry_type in ("user", "feedback", "project", "reference"):
        out = run_memory(
            [
                "record",
                "--as",
                "pi",
                "--name",
                f"entry-{entry_type}",
                "--description",
                "d",
                "--type",
                entry_type,
            ],
            cwd=tmp_path,
            input_text="b",
        )
        data = envelope(out)["data"]
        assert data["store"] == "pi"
        entry_text = Path(data["entry_path"]).read_text(encoding="utf-8")
        assert f"  type: {entry_type}\n" in entry_text


def test_record_parallel_appends_serialize_under_flock(tmp_path):
    processes = [
        subprocess.Popen(
            [
                str(RUNTIME),
                "record",
                "--as",
                "pi",
                "--name",
                f"parallel-{name}",
                "--description",
                "concurrent",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            cwd=str(tmp_path),
            env={
                **_CLEAN_ENV,
                "SWE_WORKBENCH_MEMORY_STATE_DIR": str(tmp_path / "state"),
                "HOME": str(tmp_path / "home"),
            },
        )
        for name in ("a", "b")
    ]
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        assert json.loads(stdout)["schema"] == "swb.memory/1"
    index = (pi_store_dir(tmp_path) / "MEMORY.md").read_text(encoding="utf-8")
    lines = index.splitlines()
    assert "- [parallel-a](" in index and "- [parallel-b](" in index
    assert lines[0] == "# Memory index" and lines[1] == ""
    assert len(lines) == 4  # header, blank, two entries — no torn interleaving


def test_record_same_name_parallel_keeps_single_index_line(tmp_path):
    # Same name + date hash to one entry file; entry write and index update must
    # both sit inside the flock so the re-record is atomic vs a concurrent writer.
    processes = [
        subprocess.Popen(
            [
                str(RUNTIME),
                "record",
                "--as",
                "pi",
                "--name",
                "dup",
                "--description",
                f"attempt-{label}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            cwd=str(tmp_path),
            env={
                **_CLEAN_ENV,
                "SWE_WORKBENCH_MEMORY_STATE_DIR": str(tmp_path / "state"),
                "HOME": str(tmp_path / "home"),
            },
        )
        for label in ("one", "two")
    ]
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        assert json.loads(stdout)["schema"] == "swb.memory/1"
    store = pi_store_dir(tmp_path)
    index = (store / "MEMORY.md").read_text(encoding="utf-8")
    assert len([l for l in index.splitlines() if l.startswith("- [dup](")]) == 1
    entry_files = list(store.glob("feedback_dup_*.md"))
    assert len(entry_files) == 1
    body = entry_files[0].read_text(encoding="utf-8")
    assert body.startswith("---\n")
    assert "name: dup\n" in body
    assert "attempt-one" in body or "attempt-two" in body


def test_pi_store_chmod_stops_at_state_root_override(tmp_path):
    # Regression (Phase-4 review): the fixed 4-level chmod walk escaped a state-dir
    # override and chmodded user-provided ancestor directories.
    override = tmp_path / "layer-one" / "layer-two"
    override.mkdir(parents=True)
    override.chmod(0o750)
    (tmp_path / "layer-one").chmod(0o755)
    env = dict(_CLEAN_ENV)
    env["SWE_WORKBENCH_MEMORY_STATE_DIR"] = str(override)
    env["HOME"] = str(tmp_path / "home")
    env.pop("XDG_STATE_HOME", None)
    result = subprocess.run(
        [str(RUNTIME), "record", "--as", "pi", "--name", "n", "--description", "d"],
        input="",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "layer-one").stat().st_mode & 0o777 == 0o755
    assert override.stat().st_mode & 0o777 == 0o750
    assert (override / slug_of(tmp_path)).stat().st_mode & 0o777 == 0o700


def test_pi_store_prepare_failure_is_clean_storage_error(tmp_path, monkeypatch, capsys):
    # A failing mkdir/chmod must surface as the prefixed one-line StorageError
    # message with exit 1 — never a raw PermissionError traceback.
    (tmp_path / "home").mkdir()
    body_file = tmp_path / "body.md"
    body_file.write_text("body\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SWE_WORKBENCH_MEMORY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    def deny(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", deny)
    module = load_runtime_module()
    code = module.main(
        [
            "record",
            "--as",
            "pi",
            "--name",
            "x",
            "--description",
            "d",
            "--body-file",
            str(body_file),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.splitlines() == [
        "swe-workbench-memory: could not prepare the Pi memory store directory: "
        "[Errno 13] Permission denied"
    ]


def test_record_body_file_round_trip(tmp_path):
    body_file = tmp_path / "note.md"
    body_file.write_text("## Gotcha\nAlways run the full suite.\n", encoding="utf-8")
    out = run_memory(
        [
            "record",
            "--as",
            "pi",
            "--name",
            "note",
            "--description",
            "d",
            "--body-file",
            str(body_file),
        ],
        cwd=tmp_path,
        input_text="",
    )
    envelope(out)
    entry = next(pi_store_dir(tmp_path).glob("feedback_note_*.md"))
    text = entry.read_text(encoding="utf-8")
    assert "## Gotcha" in text
    assert "Always run the full suite." in text


def test_record_refuses_missing_body_file_before_any_write(tmp_path):
    out = run_memory(
        [
            "record",
            "--as",
            "pi",
            "--name",
            "x",
            "--description",
            "d",
            "--body-file",
            str(tmp_path / "absent.md"),
        ],
        cwd=tmp_path,
        input_text="",
    )
    assert out.returncode == 1
    assert out.stdout == ""
    assert "could not read --body-file" in out.stderr
    assert not pi_store_dir(tmp_path).exists()


def test_record_claude_writes_claude_store_in_claude_format(tmp_path, worktree_repo):
    main, wt = worktree_repo
    home = wt / "home"
    out = run_memory(
        [
            "record",
            "--as",
            "claude",
            "--name",
            "claude-note",
            "--description",
            "Written by the runtime",
        ],
        cwd=wt,
        input_text="body text\n",
    )
    data = envelope(out)["data"]
    assert data["store"] == "claude"
    store = home / ".claude" / "projects" / slug_of(main) / "memory"
    assert data["index_path"] == str(store / "MEMORY.md")
    index = (store / "MEMORY.md").read_text(encoding="utf-8")
    assert index.splitlines()[0] == "# Memory index"
    assert "- [claude-note](" in index and "— Written by the runtime" in index
    entry = next(store.glob("feedback_claude_note_*.md"))
    assert "  originHarness: claude\n" in entry.read_text(encoding="utf-8")


# ── envelope plumbing ────────────────────────────────────────────────────────


def test_envelope_passes_result_check_registry(tmp_path, both_stores):
    for args in (["render", "--as", "pi"], ["show", "--as", "pi"]):
        produced = run_memory(args, cwd=tmp_path)
        assert produced.returncode == 0, produced.stderr
        checked = subprocess.run(
            [str(RESULT_CHECK), "swb.memory/1"],
            input=produced.stdout,
            capture_output=True,
            text=True,
            env=dict(_CLEAN_ENV),
        )
        assert checked.returncode == 0, checked.stderr
        assert json.loads(checked.stdout) == json.loads(produced.stdout)


def test_show_lists_own_store_entries_first_with_recency_order(tmp_path, both_stores):
    out = run_memory(["show", "--as", "pi"], cwd=tmp_path)
    entries = envelope(out)["data"]["entries"]
    assert [e["store"] for e in entries] == ["pi", "pi", "claude", "claude"]
    assert [e["name"] for e in entries] == [
        "pi-entry",
        "pi-two",
        "claude-entry",
        "claude-two",
    ]
    assert [e["order"] for e in entries] == [0, 1, 0, 1]
    assert entries[0]["type"] == "feedback"
    assert entries[0]["description"] == "Pi wrote this"


def test_record_rejects_bracketed_names(tmp_path):
    """`[`/`]` in a name can never round-trip through the index-line format —
    refuse at record time so writer and parser agree."""
    result = run_memory(
        ["record", "--as", "pi", "--name", "deploy [prod]", "--description", "d"],
        cwd=tmp_path,
        input_text="b",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "square brackets" in result.stderr
    assert not (tmp_path / "state" / slug_of(tmp_path)).exists()


def test_show_parses_legacy_bracketed_summary(tmp_path):
    """INDEX_LINE is non-greedy: an index line written before the bracket guard
    still parses instead of silently vanishing from every consumer."""
    claude = tmp_path / "home" / ".claude" / "projects" / slug_of(tmp_path) / "memory"
    claude.mkdir(parents=True)
    (claude / "MEMORY.md").write_text(
        "# Memory index\n\n- [deploy [prod]](feedback_deployprod_00112233.md) — bracketed\n"
    )
    (claude / "feedback_deployprod_00112233.md").write_text(
        "---\n"
        "name: deploy-prod\n"
        'description: "bracketed legacy"\n'
        "metadata:\n"
        "  node_type: memory\n"
        "  type: feedback\n"
        "---\n"
        "body\n"
    )
    parsed = envelope(run_memory(["show", "--as", "pi"], cwd=tmp_path))
    summaries = [e["summary"] for e in parsed["data"]["entries"]]
    assert "deploy [prod]" in summaries


def test_record_replaces_cross_day_same_name_line(tmp_path):
    """The date digest is dated, so a cross-day re-record yields a different
    file name — the dedup must key on the raw-name-hash identity, not the full
    name."""
    store = tmp_path / "state" / slug_of(tmp_path)
    store.mkdir(parents=True)
    name_hash = hashlib.sha256(b"dup").hexdigest()[:8]
    stale_file = f"feedback_dup_{name_hash}_deadbeef.md"
    (store / "MEMORY.md").write_text(
        f"# Memory index\n\n- [dup]({stale_file}) — old body\n"
    )
    (store / stale_file).write_text("---\nname: dup\n---\nold\n")
    result = run_memory(
        ["record", "--as", "pi", "--name", "dup", "--description", "new"],
        cwd=tmp_path,
        input_text="new body",
    )
    envelope(result)
    index = (store / "MEMORY.md").read_text()
    dup_lines = [line for line in index.splitlines() if "feedback_dup_" in line]
    assert len(dup_lines) == 1, index
    assert "deadbeef" not in index


def test_distinct_names_with_same_stem_never_collide(tmp_path):
    """Entry identity keys on the raw name's hash: two distinct names that
    sanitize to the same stem must both stay listed — the feature exists to
    keep gotchas from silently disappearing."""
    first = run_memory(
        ["record", "--as", "pi", "--name", "My Feature!", "--description", "one"],
        cwd=tmp_path,
        input_text="first body",
    )
    second = run_memory(
        ["record", "--as", "pi", "--name", "My-Feature?", "--description", "two"],
        cwd=tmp_path,
        input_text="second body",
    )
    envelope(first)
    envelope(second)
    index = (store_index(tmp_path)).read_text()
    stem_lines = [line for line in index.splitlines() if "feedback_My_Feature_" in line]
    assert len(stem_lines) == 2, index
    parsed = envelope(run_memory(["show", "--as", "pi"], cwd=tmp_path))
    names = [e["name"] for e in parsed["data"]["entries"]]
    assert "My Feature!" in names and "My-Feature?" in names


def store_index(tmp_path) -> Path:
    return tmp_path / "state" / slug_of(tmp_path) / "MEMORY.md"


def test_record_enforces_length_caps(tmp_path):
    """Each cap refuses fail-closed before any write; at-cap input passes."""
    refusals = [
        ("n" * 201, "d", "b"),
        ("ok", "d" * 1001, "b"),
        ("ok", "d", "b" * 12001),
    ]
    for name, description, body in refusals:
        result = run_memory(
            ["record", "--as", "pi", "--name", name, "--description", description],
            cwd=tmp_path,
            input_text=body,
        )
        assert result.returncode == 1, (name[:10], len(description), len(body))
        assert result.stdout == ""
        assert "byte cap" in result.stderr
    assert not (tmp_path / "state" / slug_of(tmp_path)).exists()
    accepted = run_memory(
        [
            "record",
            "--as",
            "pi",
            "--name",
            "n" * 200,
            "--description",
            "d" * 1000,
        ],
        cwd=tmp_path,
        input_text="b" * 12000,
    )
    envelope(accepted)
    assert store_index(tmp_path).is_file()


def test_invalid_utf8_index_degrades_and_record_fails_clean(tmp_path):
    """Non-UTF-8 bytes degrade render/show to a partial warning, and record
    surfaces the prefixed one-line StorageError — never a raw traceback."""
    store = tmp_path / "state" / slug_of(tmp_path)
    store.mkdir(parents=True)
    (store / "MEMORY.md").write_bytes(
        b"# Memory index\n\n- [\xff\xfe](feedback_bad.md) \xe2\x80\x94 detail\n"
    )
    rendered = run_memory(["render", "--as", "pi"], cwd=tmp_path)
    parsed = envelope(rendered)
    assert parsed["status"] == "partial"
    assert any(w["code"] == "index_unreadable" for w in parsed["warnings"])

    before = (store / "MEMORY.md").read_bytes()
    recorded = run_memory(
        ["record", "--as", "pi", "--name", "fresh", "--description", "d"],
        cwd=tmp_path,
        input_text="b",
    )
    assert recorded.returncode == 1
    assert recorded.stdout == ""
    assert recorded.stderr.startswith("swe-workbench-memory:")
    assert "Traceback" not in recorded.stderr
    assert (store / "MEMORY.md").read_bytes() == before

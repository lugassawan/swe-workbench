"""Behavioral tests for bin/swe-workbench-memory (issue #697).

Every test is hermetic: both SWE_WORKBENCH_MEMORY_STATE_DIR (Pi store root override)
and HOME (Claude store root) point into tmp dirs, and XDG_STATE_HOME is unset —
no test ever touches a real ~/.claude or real XDG state tree.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
RUNTIME = ROOT / "bin" / "swe-workbench-memory"
RESULT_CHECK = ROOT / "bin" / "swe-workbench-result-check"


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


def slug_of(path) -> str:
    return str(Path(path).resolve()).replace("/", "-").lstrip("-")


def write_store(store_dir: Path, entries) -> None:
    """Fabricate a Claude-format memory store. entries: [(name, description, type)] newest-first."""
    store_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Memory index", ""]
    for name, description, entry_type in entries:
        file_name = f"{entry_type}_{name}.md"
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
    claude_entries = [
        e for e in envelope(out)["data"]["entries"] if e["store"] == "claude"
    ]
    assert [e["name"] for e in claude_entries] == [
        "keep-builds-green",
        "slug-format",
        "worktree-only",
    ]
    assert [e["order"] for e in claude_entries] == [0, 1, 0]
    assert [e["file"] for e in claude_entries].count(
        "feedback_keep-builds-green.md"
    ) == 1


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
    (store / "project_sealed.md").chmod(0o000)
    out = run_memory(["render", "--as", "pi"], cwd=tmp_path)
    parsed = envelope(out)
    assert parsed["status"] == "partial"
    unreadable = [w for w in parsed["warnings"] if w["code"] == "entry_unreadable"]
    assert unreadable and unreadable[0]["subject"].endswith("project_sealed.md")
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
    assert out.returncode == 1
    assert out.stdout == ""
    assert not pi_store_dir(tmp_path).exists()


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

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

SOURCE_SCRIPT = Path(__file__).parent.parent / "bin" / "swe-workbench-reap-session-scratch"


def isolated_reaper(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / SOURCE_SCRIPT.name
    shutil.copy2(SOURCE_SCRIPT, script)
    script.chmod(0o755)
    return script


def write_adapter(script: Path, name: str, body: str) -> Path:
    adapter = script.parent / f"swe-workbench-session-scratch-adapter-{name}"
    adapter.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n")
    adapter.chmod(0o755)
    return adapter


def write_success_adapter(
    script: Path,
    name: str,
    root: Path | str,
    candidates: list[str],
    *,
    protocol: str = "SWB_SESSION_SCRATCH_V1",
    adapter_id: str | None = None,
    count: str | None = None,
    extra_records: list[str] | None = None,
) -> Path:
    records = [
        protocol,
        adapter_id or name,
        str(root),
        count if count is not None else str(len(candidates)),
        *candidates,
        *(extra_records or []),
    ]
    body = "printf '%s\\n' " + " ".join(shlex.quote(record) for record in records)
    return write_adapter(script, name, body)


def run_reaper(
    script: Path, *, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(_CLEAN_ENV)
    env.update(env_overrides or {})
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        cwd=script.parent,
        env=env,
    )


def swept_count(stdout: str) -> int:
    assignments = [
        line for line in stdout.splitlines() if line.startswith("SWEPT_SESSION_FILES=")
    ]
    assert len(assignments) == 1
    return int(assignments[0].split("=", 1)[1])


def create_target(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "authorized"
    target = root / "session" / "scratch"
    target.mkdir(parents=True)
    return root, target


def assert_noop(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0
    assert swept_count(result.stdout) == 0


def test_no_packaged_adapters_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)

    result = run_reaper(script)

    assert_noop(result)
    assert "no active" in result.stderr


def test_inactive_adapter_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    write_adapter(script, "inactive", "exit 3")

    result = run_reaper(script)

    assert_noop(result)
    assert "no active" in result.stderr


def test_active_adapter_sweeps_authorized_target(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "leftover.txt").write_text("x")
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert result.returncode == 0
    assert swept_count(result.stdout) == 1
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_term_interrupt_removes_active_adapter_descriptor_temp(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    ready_file = tmp_path / "adapter-ready"
    pid_file = tmp_path / "adapter-pid"
    write_adapter(
        script,
        "blocking",
        "\n".join(
            [
                f"printf '%s\\n' \"$$\" > {shlex.quote(str(pid_file))}",
                f"touch {shlex.quote(str(ready_file))}",
                "while :; do sleep 1; done",
            ]
        ),
    )
    env = dict(_CLEAN_ENV)
    env["TMPDIR"] = str(tmp_path)
    process = subprocess.Popen(
        ["bash", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=script.parent,
        env=env,
    )

    try:
        for _ in range(100):
            if ready_file.exists():
                break
            if process.poll() is not None:
                pytest.fail("reaper exited before the adapter blocked")
            time.sleep(0.01)
        else:
            pytest.fail("blocking adapter did not become ready")

        process.terminate()
        process.wait(timeout=5)

        assert not list(tmp_path.glob("swe-workbench-session-scratch.*"))
    finally:
        if pid_file.exists():
            os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)


def test_multiple_active_adapters_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "keep.txt").write_text("x")
    write_success_adapter(script, "first", root, ["session/scratch"])
    write_success_adapter(script, "second", root, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()
    assert "multiple active" in result.stderr


def test_active_adapter_failure_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    write_adapter(script, "broken", "exit 1")

    result = run_reaper(script)

    assert_noop(result)
    assert "could not resolve" in result.stderr


@pytest.mark.parametrize(
    ("protocol", "adapter_id", "count", "candidates", "extra_records"),
    [
        ("SWB_SESSION_SCRATCH_V2", "fixture", None, ["session/scratch"], None),
        ("SWB_SESSION_SCRATCH_V1", "bad_id", None, ["session/scratch"], None),
        ("SWB_SESSION_SCRATCH_V1", "Fixture", None, ["session/scratch"], None),
        ("SWB_SESSION_SCRATCH_V1", "fixture", "one", ["session/scratch"], None),
        ("SWB_SESSION_SCRATCH_V1", "fixture", "0", ["session/scratch"], None),
        ("SWB_SESSION_SCRATCH_V1", "fixture", "2", ["session/scratch"], None),
        ("SWB_SESSION_SCRATCH_V1", "fixture", "1", [], None),
        ("SWB_SESSION_SCRATCH_V1", "fixture", "1", ["session/scratch"], ["extra"]),
        ("SWB_SESSION_SCRATCH_V1", "fixture", "1", ["session/scratch"], [""]),
    ],
)
def test_malformed_descriptor_is_noop(
    tmp_path: Path,
    protocol: str,
    adapter_id: str,
    count: str | None,
    candidates: list[str],
    extra_records: list[str] | None,
) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "keep.txt").write_text("x")
    write_success_adapter(
        script,
        "fixture",
        root,
        candidates,
        protocol=protocol,
        adapter_id=adapter_id,
        count=count,
        extra_records=extra_records,
    )

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()


def test_zero_count_descriptor_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "keep.txt").write_text("x")
    write_success_adapter(script, "fixture", root, [], count="0")

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()


@pytest.mark.parametrize(
    "candidate",
    [
        "/absolute/scratch",
        "scratch",
        "session/../scratch",
        "session/./scratch",
        "session//scratch",
        "session/scratch/",
    ],
)
def test_invalid_relative_candidate_is_noop(tmp_path: Path, candidate: str) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "keep.txt").write_text("x")
    write_success_adapter(script, "fixture", root, [candidate])

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()


def test_root_symlink_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    actual_root, target = create_target(tmp_path)
    root_link = tmp_path / "authorized-link"
    root_link.symlink_to(actual_root, target_is_directory=True)
    (target / "keep.txt").write_text("x")
    write_success_adapter(script, "fixture", root_link, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()


def test_target_symlink_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root = tmp_path / "authorized"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    session = root / "session"
    session.mkdir()
    (session / "scratch").symlink_to(outside, target_is_directory=True)
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)
    assert (outside / "keep.txt").exists()


def test_symlinked_intermediate_component_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root = tmp_path / "authorized"
    outside = tmp_path / "outside"
    target = outside / "scratch"
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("x")
    root.mkdir()
    (root / "session").symlink_to(outside, target_is_directory=True)
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()



@pytest.mark.parametrize("root_kind", ["missing", "file", "filesystem-root"])
def test_unsafe_authorized_root_is_noop(tmp_path: Path, root_kind: str) -> None:
    script = isolated_reaper(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    if root_kind == "missing":
        root: Path | str = tmp_path / "missing"
    elif root_kind == "file":
        root = tmp_path / "not-a-directory"
        root.write_text("x")
    else:
        root = "/"
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()


@pytest.mark.parametrize("target_kind", ["missing", "file"])
def test_missing_or_non_directory_target_is_noop(
    tmp_path: Path, target_kind: str
) -> None:
    script = isolated_reaper(tmp_path)
    root = tmp_path / "authorized"
    root.mkdir()
    target = root / "session" / "scratch"
    target.parent.mkdir()
    if target_kind == "file":
        target.write_text("x")
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)
    if target_kind == "file":
        assert target.exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="requires root to fabricate ownership")
@pytest.mark.parametrize("foreign_path", ["root", "target"])
def test_foreign_owned_path_is_noop(tmp_path: Path, foreign_path: str) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "keep.txt").write_text("x")
    path = root if foreign_path == "root" else target
    os.chown(path, 1, 1)
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    try:
        result = run_reaper(script)

        assert_noop(result)
        assert (target / "keep.txt").exists()
    finally:
        os.chown(path, os.getuid(), os.getgid())


def test_target_disappearing_before_removal_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root = tmp_path / "authorized"
    (root / "session").mkdir(parents=True)
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)


def test_target_containing_git_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "keep.txt").write_text("x")
    (target / ".git").mkdir()
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()


def test_target_containing_dangling_git_symlink_is_noop(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "keep.txt").write_text("x")
    (target / ".git").symlink_to(tmp_path / "missing-git")
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert_noop(result)
    assert (target / "keep.txt").exists()


def test_happy_path_removes_top_level_entries_and_preserves_target(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "one.txt").write_text("x")
    (target / ".hidden").write_text("x")
    nested = target / "nested"
    nested.mkdir()
    (nested / "two.txt").write_text("x")
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    result = run_reaper(script)

    assert result.returncode == 0
    assert swept_count(result.stdout) == 3
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_idempotent_rerun_preserves_empty_target(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    (target / "one.txt").write_text("x")
    write_success_adapter(script, "fixture", root, ["session/scratch"])

    first = run_reaper(script)
    second = run_reaper(script)

    assert swept_count(first.stdout) == 1
    assert swept_count(second.stdout) == 0
    assert target.is_dir()


def test_partial_removal_counts_only_successful_entries(tmp_path: Path) -> None:
    script = isolated_reaper(tmp_path)
    root, target = create_target(tmp_path)
    removable = target / "remove.txt"
    protected = target / "protected.txt"
    removable.write_text("x")
    protected.write_text("x")
    write_success_adapter(script, "fixture", root, ["session/scratch"])
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_rm = fake_bin / "rm"
    fake_rm.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$*\" == *protected.txt ]]; then exit 1; fi\n"
        "/bin/rm \"$@\"\n"
    )
    fake_rm.chmod(0o755)

    result = run_reaper(script, env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"})

    assert result.returncode == 0
    assert swept_count(result.stdout) == 1
    assert not removable.exists()
    assert protected.exists()
    assert "failed to remove" in result.stderr

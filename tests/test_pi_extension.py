"""Contract and behavioural tests for the Pi Coding Agent adapter.

Two layers:
  - Always-on (static/contract): pi/package.json shape, bin/README.md anchor shape, no
    hardcoded root hop in the extension source. No Node required.
  - Behavioural (skipif no Node >= 22): drives the real pi/extensions/index.ts through
    `node --experimental-strip-types` with a stub ExtensionAPI, since every
    `@earendil-works/*` import in the extension is type-only and therefore elided by the
    stripper — no module resolution, no node_modules, needed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
PACKAGE_JSON = ROOT / "pi" / "package.json"
INDEX_TS = ROOT / "pi" / "extensions" / "index.ts"
BIN_README = ROOT / "bin" / "README.md"

_DRIVER = """
import { pathToFileURL } from "node:url";
import { delimiter } from "node:path";

const mod = await import(pathToFileURL(process.argv[2]).href);
const factory = mod.default;

const handlers = {};
const stubPi = {
  on(event, handler) {
    handlers[event] = handler;
  },
};
const stubCtx = { hasUI: true, ui: { notify() {} } };

await factory(stubPi);
await factory(stubPi); // second invocation: defends against this file loading as two Extension instances

const discoverResult = await handlers["resources_discover"](
  { type: "resources_discover", cwd: process.cwd(), reason: "startup" },
  stubCtx,
);

const firstInjection = await handlers["before_agent_start"](
  { type: "before_agent_start", prompt: "hi", systemPrompt: "BASE-PROMPT", systemPromptOptions: {} },
  stubCtx,
);
const promptAfterFirst = firstInjection && firstInjection.systemPrompt
  ? firstInjection.systemPrompt
  : "BASE-PROMPT";

const secondInjection = await handlers["before_agent_start"](
  { type: "before_agent_start", prompt: "hi again", systemPrompt: promptAfterFirst, systemPromptOptions: {} },
  stubCtx,
);

console.log(JSON.stringify({
  discoverResult,
  pathEntries: (process.env.PATH ?? "").split(delimiter).filter(Boolean),
  firstInjection,
  secondInjection,
}));
"""


def _node_major_version():
    node = shutil.which("node")
    if node is None:
        return None
    result = subprocess.run(
        [node, "--version"], capture_output=True, text=True, env=_CLEAN_ENV, timeout=10
    )
    # "v22.6.0\n" -> 22
    return int(result.stdout.strip().lstrip("v").split(".")[0])


_NODE_MAJOR = _node_major_version()
requires_node = pytest.mark.skipif(
    _NODE_MAJOR is None or _NODE_MAJOR < 22,
    reason="behavioural pi extension tests require Node >= 22 (--experimental-strip-types)",
)


# ---------------------------------------------------------------------------
# Always-on: static/contract checks
# ---------------------------------------------------------------------------


def test_package_json_is_valid_json_with_exact_keys():
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert set(data.keys()) == {
        "name",
        "version",
        "private",
        "type",
        "description",
        "pi",
        "peerDependencies",
    }


def test_package_json_values():
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert data["name"] == "swe-workbench-pi"
    assert data["version"] == "0.0.0"
    assert data["private"] is True
    assert data["type"] == "module"
    assert data["pi"] == {"extensions": ["./extensions"]}
    assert data["peerDependencies"] == {"@earendil-works/pi-coding-agent": "*"}


def test_package_json_has_no_pi_skills_key():
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert "skills" not in data["pi"], (
        "pi.skills must be absent — the extension's resources_discover handler must stay the "
        "sole, single source of truth for skill paths, not one of two independently maintained "
        "declarations that could drift apart"
    )


def test_package_json_has_no_dependencies_key():
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert "dependencies" not in data


def test_bin_readme_current_scripts_section_has_a_terminating_heading():
    text = BIN_README.read_text(encoding="utf-8")
    start = text.find("## Current scripts")
    assert start != -1, "bin/README.md must contain the literal '## Current scripts' heading"
    next_heading = text.find("\n## ", start + len("## Current scripts"))
    assert next_heading != -1, (
        "a later '## ' heading must terminate the Current scripts section so extraction "
        "in pi/extensions/index.ts has a well-defined end"
    )


def test_index_ts_has_no_hardcoded_root_hop():
    text = INDEX_TS.read_text(encoding="utf-8")
    assert '"../.."' not in text and "'../..'" not in text, (
        "the plugin root must be resolved by walking up for .claude-plugin/plugin.json, "
        "not a hardcoded hop — a #611 relocation would silently break a hardcoded hop"
    )


# ---------------------------------------------------------------------------
# Behavioural: drive the real extension under node --experimental-strip-types
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def extension_result(tmp_path_factory):
    if _NODE_MAJOR is None or _NODE_MAJOR < 22:
        pytest.skip("requires Node >= 22")
    driver = tmp_path_factory.mktemp("pi-extension-driver") / "driver.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--experimental-strip-types", str(driver), str(INDEX_TS)],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=30,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    return json.loads(result.stdout)


@requires_node
def test_resources_discover_returns_exactly_the_skills_dir(extension_result):
    assert extension_result["discoverResult"] == {"skillPaths": [str(ROOT / "skills")]}


@requires_node
def test_path_gains_bin_dir_exactly_once_after_two_factory_invocations(extension_result):
    bin_dir = str(ROOT / "bin")
    assert extension_result["pathEntries"].count(bin_dir) == 1


@requires_node
def test_before_agent_start_injects_marker_and_first_script_row(extension_result):
    injected = extension_result["firstInjection"]["systemPrompt"]
    assert "<!-- swe-workbench:pi-bin-preamble -->" in injected
    assert "swe-workbench-clean-ephemeral" in injected


@requires_node
def test_before_agent_start_does_not_duplicate_on_already_injected_prompt(extension_result):
    # Second call received a prompt that already contains the marker; it must be a no-op.
    # A void handler return serializes as an absent key, not JSON null.
    second = extension_result.get("secondInjection")
    assert second is None or "systemPrompt" not in second


@requires_node
def test_missing_bin_readme_degrades_gracefully(tmp_path_factory):
    """A missing bin/README.md must not take down PATH exposure or skill discovery.

    Regression test: the extension used to read bin/README.md unguarded, so a missing file
    threw synchronously inside the factory — which fails the whole extension, not just the
    system-prompt preamble feature (the one failure mode the code already degrades for).
    """
    synthetic_root = tmp_path_factory.mktemp("pi-synthetic-root")
    (synthetic_root / ".claude-plugin").mkdir()
    (synthetic_root / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (synthetic_root / "bin").mkdir()  # deliberately no README.md
    (synthetic_root / "skills").mkdir()
    synthetic_index = synthetic_root / "pi" / "extensions" / "index.ts"
    synthetic_index.parent.mkdir(parents=True)
    synthetic_index.write_text(INDEX_TS.read_text(encoding="utf-8"), encoding="utf-8")

    driver = tmp_path_factory.mktemp("pi-extension-driver-missing-readme") / "driver.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--experimental-strip-types", str(driver), str(synthetic_index)],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=30,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    parsed = json.loads(result.stdout)
    assert parsed["discoverResult"] == {"skillPaths": [str(synthetic_root / "skills")]}
    assert str(synthetic_root / "bin") in parsed["pathEntries"]
    assert "systemPrompt" not in (parsed.get("firstInjection") or {})

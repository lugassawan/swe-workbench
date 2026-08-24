"""Contract and behavioural tests for the Pi Coding Agent adapter.

Two layers:
  - Always-on (static/contract): root package.json shape, bin/README.md anchor shape, no
    hardcoded root hop in the extension source. No Node required.
  - Behavioural (skipif no Node >= 22): drives the real pi/extensions/index.ts through
    `node --experimental-strip-types` with a stub ExtensionAPI, since every
    `@earendil-works/*` import in the extension is type-only and therefore elided by the
    stripper — no module resolution, no node_modules, needed.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
PACKAGE_JSON = ROOT / "package.json"
INDEX_TS = ROOT / "pi" / "extensions" / "index.ts"
GUARDS_TS = ROOT / "pi" / "extensions" / "guards.ts"
GUARD_RUNNER_TS = ROOT / "pi" / "extensions" / "guard-runner.ts"
TOOL_VOCAB_TS = ROOT / "pi" / "extensions" / "tool-vocab.ts"
ASK_USER_TS = ROOT / "pi" / "extensions" / "ask-user.ts"
BIN_README = ROOT / "bin" / "README.md"
SKILLS_DIR = ROOT / "skills"

# Concatenated (not a single literal) so this fixture's shape never appears contiguous in this
# file's own source — this file is not on secret_guard.py's allowlist (unlike
# tests/test_secret_guard.py), and the live PreToolUse:Write hook on the session authoring this
# file would otherwise block the edit that introduces it.
_SECRET_CONTENT = "API_KEY" + '="abcdefghijklmnop1234"'

_DRIVER = """
import { pathToFileURL } from "node:url";
import { delimiter } from "node:path";

const [, , indexPath, configJson] = process.argv;
const config = configJson ? JSON.parse(configJson) : {};
const excludedTools = new Set(config.excludedTools || []);

const mod = await import(pathToFileURL(indexPath).href);
const factory = mod.default;

const handlers = {};
const registeredToolNames = [];
const stubPi = {
  on(event, handler) {
    handlers[event] = handler;
  },
  registerTool(tool) {
    registeredToolNames.push(tool.name);
  },
  // Mirrors the real SDK's isAllowedTool: a registered tool this session's own argv excludes
  // (simulated here via config.excludedTools) is filtered out of the active set even though
  // registerTool() was called for it — see index.ts's getPreamble() for why this matters.
  getActiveTools() {
    return registeredToolNames.filter((name) => !excludedTools.has(name));
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
_NODE_TOO_OLD = _NODE_MAJOR is None or _NODE_MAJOR < 22

if _NODE_TOO_OLD and os.environ.get("CI"):
    # CI's pytest job pins Node >= 22 via actions/setup-node specifically so these
    # behavioural tests always run there — a missing/too-old Node in CI is a broken
    # job, not something to silently skip past. A local run without Node still gets
    # the softer skip below.
    pytest.fail(
        "Node >= 22 required for pi extension behavioural tests but not found (or "
        "too old) in CI — check the pytest job's actions/setup-node step",
        pytrace=False,
    )

requires_node = pytest.mark.skipif(
    _NODE_TOO_OLD,
    reason="behavioural pi extension tests require Node >= 22 (--experimental-strip-types)",
)


# ---------------------------------------------------------------------------
# Always-on: static/contract checks
# ---------------------------------------------------------------------------


def test_package_json_is_valid_json_with_required_keys():
    """Required-keys-present, not an exact-set equality — the manifest is expected to
    grow (Group 2's devDependencies/scripts, later phases' own additions), and an
    exact-set assertion would just be a maintenance tax. Forbidden-keys-absent coverage
    (dependencies, pi.skills) lives in the two dedicated tests below — not duplicated
    here."""
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    for key in ("name", "version", "private", "type", "description", "pi", "peerDependencies"):
        assert key in data, f"package.json must have a {key!r} key"


def test_package_json_values():
    """No hardcoded version literal here — check_pi_package_json() in scripts/validate.py
    asserts version parity against plugin.json on every PR, so a per-release literal would
    break on every single version bump before the next release even lands. This test only
    asserts fields that don't change per release."""
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert data["name"] == "swe-workbench-pi"
    assert data["private"] is True
    assert data["type"] == "module"
    assert data["pi"] == {"extensions": ["./pi/extensions/index.ts"]}

    dev_pin = data["devDependencies"]["@earendil-works/pi-coding-agent"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", dev_pin), (
        f"devDependencies pin must be an exact X.Y.Z version — no ^, ~, *, ||, - range, "
        f"or other npm range syntax anywhere in the string — got {dev_pin!r}"
    )

    peer_range = data["peerDependencies"]["@earendil-works/pi-coding-agent"]
    parts = peer_range.split()
    assert len(parts) == 2, (
        f"peerDependencies range must have an explicit floor and ceiling, got {peer_range!r}"
    )
    floor, ceiling = parts
    assert floor == ">=0.84.2", (
        f"peerDependencies floor must equal the devDependencies pin ({dev_pin!r}), got {floor!r}"
    )
    assert ceiling == "<1", (
        "peerDependencies ceiling must stay below the next major — pre-1.0 semver gives no "
        f"compatibility guarantee across majors — got {ceiling!r}. A widened or dropped "
        "ceiling would let an untested major version of the peer satisfy this range silently."
    )

    assert data["peerDependenciesMeta"]["@earendil-works/pi-coding-agent"]["optional"] is True, (
        "without peerDependenciesMeta.optional, npm >=7 auto-installs the full Pi SDK into "
        "every consumer's tree for an import that is type-only and elided at runtime"
    )

    # pi-tui is type-only at compile time — pi resolves it at runtime via its jiti
    # alias map. Pin lockstep with the SDK: a divergent pin typechecks a shape pi never loads.
    tui_dev_pin = data["devDependencies"]["@earendil-works/pi-tui"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", tui_dev_pin), (
        f"pi-tui devDependencies pin must be an exact X.Y.Z version, got {tui_dev_pin!r}"
    )
    assert tui_dev_pin == dev_pin, (
        f"pi-tui dev pin ({tui_dev_pin!r}) must equal the pi-coding-agent pin ({dev_pin!r}) — "
        "pi nests and publishes them lockstep; a divergent pin typechecks against a shape the "
        "host never provides"
    )
    assert data["peerDependencies"]["@earendil-works/pi-tui"] == peer_range, (
        "pi-tui peer range must mirror the pi-coding-agent entry — same compatibility envelope, "
        "same anti-untested-major ceiling"
    )
    assert data["peerDependenciesMeta"]["@earendil-works/pi-tui"]["optional"] is True, (
        "pi resolves pi-tui for extensions itself (jiti alias map); an npm auto-install into "
        "consumers would be redundant payload for a specifier npm never needs to resolve"
    )


def test_package_json_has_no_forbidden_pi_keys():
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert "skills" not in data["pi"], (
        "pi.skills must be absent — the extension's resources_discover handler must stay the "
        "sole, single source of truth for skill paths, not one of two independently maintained "
        "declarations that could drift apart"
    )
    assert "prompts" not in data["pi"], (
        "pi.prompts must be absent — the manifest route's loader recurses into subdirectories "
        "where resources_discover's promptPaths loader does not; declaring it here would "
        "silently republish a future commands/<subdir>/*.md as a top-level command"
    )
    assert "themes" not in data["pi"], "pi.themes is not used by this plugin"


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
def test_resources_discover_returns_exactly_the_skills_and_commands_dirs(extension_result):
    assert extension_result["discoverResult"] == {
        "skillPaths": [str(ROOT / "skills")],
        "promptPaths": [str(ROOT / "commands")],
    }


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
def test_before_agent_start_injects_tool_vocab_section(extension_result):
    injected = extension_result["firstInjection"]["systemPrompt"]
    assert "Claude Code -> Pi tool vocabulary" in injected
    assert "| `Read` | `read` |" in injected
    assert "ask_user_question" in injected


@requires_node
def test_before_agent_start_names_task_tool_when_kill_switch_unset(extension_result):
    """index.ts's getPreamble() reads pi.getActiveTools() — with the kill switch unset (the
    default) and no --exclude-tools in play, `task` is actually registered AND active, so the
    preamble must name the real `task` tool, not warn against fabricating one."""
    injected = extension_result["firstInjection"]["systemPrompt"]
    assert "`task(agent, prompt)`" in injected
    assert "fabricate `Task` calls" not in injected


@requires_node
def test_before_agent_start_falls_back_when_task_registered_but_excluded(tmp_path_factory):
    """Regression test for the dispatched-child case: registerSubagent() still calls
    pi.registerTool() for `task` whenever SWE_WORKBENCH_PI_TOOLS is unset — including inside a
    child session whose own argv carries `--exclude-tools task,subagent` (subagent.ts's own
    recursion guard). The preamble must NOT tell that child to use a `task` tool that has been
    filtered out of its actual active-tool set — checking pi.getActiveTools() (not the raw env
    var) is what index.ts's getPreamble() now does to get this right."""
    result = _run_node(
        _DRIVER,
        [str(INDEX_TS), json.dumps({"excludedTools": ["task"]})],
        tmp_path_factory,
        label="pi-extension-driver-task-excluded",
    )
    injected = result["firstInjection"]["systemPrompt"]
    assert "fabricate `Task` calls" in injected
    assert "`task(agent, prompt)`" not in injected


@requires_node
def test_tool_vocab_preamble_survives_the_kill_switch(tmp_path_factory):
    """SWE_WORKBENCH_PI_TOOLS=0 gates Tier-2 tool registration only — the Tier-1 vocabulary
    prose must stay unconditional, since disabling it makes the session worse, not safer. With
    the kill switch on, `task` is never registered, so the preamble must fall back to the
    do-not-fabricate framing rather than naming a tool that isn't actually live."""
    driver = tmp_path_factory.mktemp("pi-extension-driver-kill-switch") / "driver.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    node = shutil.which("node")
    assert node is not None
    run_env = dict(_CLEAN_ENV)
    run_env["SWE_WORKBENCH_PI_TOOLS"] = "0"
    result = subprocess.run(
        [node, "--experimental-strip-types", str(driver), str(INDEX_TS)],
        capture_output=True, text=True, env=run_env, timeout=30,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    parsed = json.loads(result.stdout)
    injected = parsed["firstInjection"]["systemPrompt"]
    assert "Claude Code -> Pi tool vocabulary" in injected
    assert "| `Read` | `read` |" in injected
    assert "fabricate `Task` calls" in injected
    assert "`task(agent, prompt)`" not in injected


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
    bin-scripts row of the preamble (the one failure mode the code already degrades for). The
    rest of the preamble — tool-vocab.ts's content, including the anti-hallucination rule —
    must still be injected; only the bin-scripts row disappears.
    """
    synthetic_root = tmp_path_factory.mktemp("pi-synthetic-root")
    (synthetic_root / ".claude-plugin").mkdir()
    (synthetic_root / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (synthetic_root / "bin").mkdir()  # deliberately no README.md
    (synthetic_root / "skills").mkdir()
    synthetic_index = synthetic_root / "pi" / "extensions" / "index.ts"
    synthetic_index.parent.mkdir(parents=True)
    synthetic_index.write_text(INDEX_TS.read_text(encoding="utf-8"), encoding="utf-8")
    for helper in (
        "guards.ts",
        "cc-payload.ts",
        "guard-runner.ts",
        "tool-vocab.ts",
        "ask-user.ts",
        "agent-spec.ts",
        "model-policy.ts",
        "task-call-line.ts",
        "dispatch-resolver.ts",
        "subagent.ts",
    ):
        (synthetic_index.parent / helper).write_text(
            (ROOT / "pi" / "extensions" / helper).read_text(encoding="utf-8"), encoding="utf-8"
        )

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
    assert parsed["discoverResult"] == {
        "skillPaths": [str(synthetic_root / "skills")],
        "promptPaths": [str(synthetic_root / "commands")],
    }
    assert str(synthetic_root / "bin") in parsed["pathEntries"]
    injected = parsed["firstInjection"]["systemPrompt"]
    assert "<!-- swe-workbench:pi-bin-preamble -->" in injected
    assert "swe-workbench-clean-ephemeral" not in injected, "bin-scripts row must be absent"
    assert "Claude Code -> Pi tool vocabulary" in injected, "tool-vocab section must still inject"


# ---------------------------------------------------------------------------
# Behavioural: guards.ts driving the REAL hooks/bash_guard.sh + hooks/secret_guard.py +
# hooks/workflow_resume_hint.sh + hooks/skill_autoload_hint.sh through guard-runner.ts's real
# spawn. Everything below drives the actual scripts, not a mock — the acceptance criterion is
# that the adapter reproduces the same verdict a direct Claude-Code-shaped invocation would
# get, not that its own translation logic is internally self-consistent.
# ---------------------------------------------------------------------------

_GUARDS_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , guardsPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const { registerGuards } = await import(pathToFileURL(guardsPath).href);
const { runGuard: realRunGuard } = await import(pathToFileURL(config.guardRunnerPath).href);

const handlers = {};
const sentMessages = [];
const notifications = [];
const stubPi = {
  on(event, handler) { handlers[event] = handler; },
  sendMessage(message, options) { sentMessages.push({ message, options }); },
};
const stubCtx = {
  hasUI: true,
  cwd: config.cwd,
  signal: undefined,
  isProjectTrusted: () => true,
  ui: { notify: (msg, level) => notifications.push({ msg, level }) },
  sessionManager: { getSessionId: () => config.sessionId },
};

let runGuardCallCount = 0;
const runGuard = config.forceSpawnFailure
  ? async () => { throw new Error("forced spawn failure (test)"); }
  : async (options) => { runGuardCallCount++; return realRunGuard(options); };

registerGuards(stubPi, config.root, { runGuard });

async function toolCall(toolName, input) {
  return handlers["tool_call"]({ type: "tool_call", toolCallId: "t", toolName, input }, stubCtx);
}

const out = {};
out.bashBlocked = await toolCall("bash", { command: "rm -rf /" });
out.bashAllowed = await toolCall("bash", { command: "ls -la" });
out.bashBacktickBlocked = await toolCall("bash", { command: "`rm -rf /`" });
out.writeBlocked = await toolCall("write", { path: "/tmp/f.py", content: config.secretContent });
out.writeAllowed = await toolCall("write", { path: "/tmp/f.py", content: "print(1)" });

runGuardCallCount = 0;
out.editShortCircuit = await toolCall("edit", {
  path: "/tmp/f.py",
  edits: [
    { oldText: "a", newText: config.secretContent },
    { oldText: "b", newText: "safe" },
  ],
});
out.editRunGuardCalls = runGuardCallCount;

out.sessionStart = await handlers["session_start"]({ type: "session_start", reason: "startup" }, stubCtx);
out.sentAfterSessionStart = sentMessages.slice();

sentMessages.length = 0;
out.toolResult = await handlers["tool_result"](
  { type: "tool_result", toolCallId: "t2", toolName: "edit", input: { path: config.tsFilePath }, content: [], isError: false },
  stubCtx,
);
out.sentAfterToolResult = sentMessages.slice();

console.log(JSON.stringify({ out, notifications }));
"""

_TWO_SESSION_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , guardsPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const { registerGuards } = await import(pathToFileURL(guardsPath).href);

const handlers = {};
const stubPi = { on(event, handler) { handlers[event] = handler; }, sendMessage() {} };

registerGuards(stubPi, config.root, {});

const results = [];
for (const sessionId of config.sessionIds) {
  const sent = [];
  const ctx = {
    hasUI: true,
    cwd: config.cwd,
    signal: undefined,
    ui: { notify() {} },
    sessionManager: { getSessionId: () => sessionId },
  };
  const originalSendMessage = stubPi.sendMessage;
  stubPi.sendMessage = (message, options) => sent.push({ message, options });
  await handlers["tool_result"](
    { type: "tool_result", toolCallId: "t", toolName: "edit", input: { path: config.tsFilePath }, content: [], isError: false },
    ctx,
  );
  stubPi.sendMessage = originalSendMessage;
  results.push({ sessionId, sentCount: sent.length });
}

console.log(JSON.stringify(results));
"""

_EMPTY_SESSION_ID_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , guardsPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const { registerGuards } = await import(pathToFileURL(guardsPath).href);

const handlers = {};
const stubPi = { on(event, handler) { handlers[event] = handler; }, sendMessage() {} };
registerGuards(stubPi, config.root, {});

const ctx = {
  hasUI: true,
  cwd: config.cwd,
  signal: undefined,
  ui: { notify() {} },
  sessionManager: { getSessionId: () => "" },
};

try {
  await handlers["tool_result"](
    { type: "tool_result", toolCallId: "t", toolName: "edit", input: { path: config.tsFilePath }, content: [], isError: false },
    ctx,
  );
  console.log(JSON.stringify({ threw: false }));
} catch (err) {
  console.log(JSON.stringify({ threw: true, message: String(err && err.message) }));
}
"""


def _run_node(driver_src, args, tmp_path_factory, *, label):
    if _NODE_MAJOR is None or _NODE_MAJOR < 22:
        pytest.skip("requires Node >= 22")
    driver = tmp_path_factory.mktemp(label) / "driver.mjs"
    driver.write_text(driver_src, encoding="utf-8")
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--experimental-strip-types", str(driver), *args],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=30,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def guards_result(tmp_path_factory):
    import uuid

    config = {
        "root": str(ROOT),
        "guardRunnerPath": str(GUARD_RUNNER_TS),
        "cwd": str(ROOT),
        # unique per test run — skill_autoload_hint.sh's dedup sentinel is keyed by
        # session+skill and persists on disk across repeated pytest invocations on the same
        # machine/day, so a fixed literal here would flake on a second run.
        "sessionId": f"sess-guards-fixture-{uuid.uuid4().hex}",
        "secretContent": _SECRET_CONTENT,
        "tsFilePath": str(ROOT / "pi" / "extensions" / "index.ts"),
        "forceSpawnFailure": False,
    }
    return _run_node(_GUARDS_DRIVER, [str(GUARDS_TS), json.dumps(config)], tmp_path_factory, label="pi-guards-driver")


@requires_node
def test_bash_guard_blocks_rm_rf_via_adapter(guards_result):
    assert guards_result["out"]["bashBlocked"] == {
        "block": True,
        "reason": "BLOCKED: destructive rm against root or home",
    }


@requires_node
def test_bash_guard_allows_safe_command_via_adapter(guards_result):
    assert guards_result["out"].get("bashAllowed") is None


@requires_node
def test_bash_guard_blocks_401_backtick_vector_via_adapter(guards_result):
    """Regression coverage for the backtick rm -rf bypass hooks/bash_guard.sh now closes,
    driven through the real Pi adapter rather than invoking the script directly."""
    assert guards_result["out"]["bashBacktickBlocked"] == {
        "block": True,
        "reason": "BLOCKED: destructive rm against root or home",
    }


@requires_node
def test_secret_guard_blocks_write_with_secret_via_adapter(guards_result):
    result = guards_result["out"]["writeBlocked"]
    assert result["block"] is True
    assert "BLOCKED: hardcoded secret detected" in result["reason"]


@requires_node
def test_secret_guard_allows_clean_write_via_adapter(guards_result):
    assert guards_result["out"].get("writeAllowed") is None


@requires_node
def test_edit_guard_checks_one_payload_per_edits_element_and_short_circuits(guards_result):
    """The blocked edits[] element is FIRST, so only ONE guard-runner call should happen —
    proving payloads are per-element (not joined) and the loop stops at the first block."""
    result = guards_result["out"]["editShortCircuit"]
    assert result["block"] is True
    assert "line 1" in result["reason"], (
        "block reason must report a line number against the single new_string that was "
        "actually sent, not a fabricated line number from a joined multi-edit document"
    )
    assert guards_result["out"]["editRunGuardCalls"] == 1, (
        "guard-runner must not be invoked for edits[] elements after the first block"
    )


_SESSION_START_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , guardsPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const { registerGuards } = await import(pathToFileURL(guardsPath).href);

const handlers = {};
const sent = [];
const stubPi = {
  on(event, handler) { handlers[event] = handler; },
  sendMessage(message, options) { sent.push({ message, options }); },
};
registerGuards(stubPi, config.root, {});

const stubCtx = {
  hasUI: true,
  cwd: config.cwd,
  signal: undefined,
  isProjectTrusted: () => true,
  ui: { notify() {} },
  sessionManager: { getSessionId: () => "sess-resume-hint" },
};

await handlers["session_start"]({ type: "session_start", reason: "startup" }, stubCtx);
console.log(JSON.stringify({ sent }));
"""


@requires_node
def test_session_start_emits_resume_hint_via_send_message(tmp_path_factory):
    """Builds its own git repo + workflow-state checkpoint rather than running against ROOT —
    workflow_resume_hint.sh only emits an advisory when a fresh checkpoint exists for the
    current branch, OR when cwd is a linked git worktree with no checkpoint. Relying on ROOT's
    ambient worktree-ness made this test pass locally (inside a rimba worktree) but fail in CI
    (a plain checkout, is_linked_worktree=0, no advisory)."""
    import subprocess

    repo_dir = tmp_path_factory.mktemp("pi-resume-hint-repo") / "repo"
    repo_dir.mkdir()
    branch = "feature/pi-resume-hint-test"
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=repo_dir, env=_CLEAN_ENV, check=True)
    (repo_dir / "README").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, env=_CLEAN_ENV, check=True)
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.email=t@t.com", "-c", "user.name=T",
         "commit", "-qm", "init"],
        cwd=repo_dir, env=_CLEAN_ENV, check=True,
    )

    state_dir = repo_dir / ".claude" / "cache" / "workflow-state"
    state_dir.mkdir(parents=True)
    state = {
        "version": 1,
        "skill": "swe-workbench:workflow-development",
        "mode": "B",
        "phase": "3",
        "phase_label": "Verify",
        "completed_phases": ["1", "2"],
        "context": {
            "branch": branch, "worktree_root": None, "pr": None,
            "base": None, "head_sha": None, "decision": None, "notes": "checkpoint",
        },
        "updated_at": "2026-08-21T00:00:00Z",
    }
    safe_branch = branch.replace("/", "-")
    (state_dir / f"{safe_branch}.json").write_text(json.dumps(state), encoding="utf-8")

    config = {"root": str(ROOT), "cwd": str(repo_dir)}
    result = _run_node(
        _SESSION_START_DRIVER, [str(GUARDS_TS), json.dumps(config)], tmp_path_factory, label="pi-session-start-hint"
    )
    sent = result["sent"]
    assert len(sent) == 1
    assert sent[0]["message"]["customType"] == "swe-workbench:workflow-resume-hint"
    assert sent[0]["message"]["display"] is False
    assert sent[0]["options"]["deliverAs"] == "nextTurn"
    assert isinstance(sent[0]["message"]["content"], str) and sent[0]["message"]["content"]


@requires_node
def test_tool_result_emits_skill_hint_via_send_message_steer(guards_result):
    sent = guards_result["out"]["sentAfterToolResult"]
    assert len(sent) == 1
    assert sent[0]["message"]["customType"] == "swe-workbench:skill-autoload-hint"
    assert sent[0]["options"]["deliverAs"] == "steer"
    assert "language-typescript" in sent[0]["message"]["content"]


@requires_node
def test_forced_spawn_failure_bash_guard_fails_closed(tmp_path_factory):
    """Without this test, a `catch { return {} }` that silently flips fail-closed to fail-open
    would still pass every happy-path test above."""
    config = {
        "root": str(ROOT),
        "guardRunnerPath": str(GUARD_RUNNER_TS),
        "cwd": str(ROOT),
        "sessionId": "sess-spawn-fail",
        "secretContent": _SECRET_CONTENT,
        "tsFilePath": str(ROOT / "pi" / "extensions" / "index.ts"),
        "forceSpawnFailure": True,
    }
    result = _run_node(_GUARDS_DRIVER, [str(GUARDS_TS), json.dumps(config)], tmp_path_factory, label="pi-guards-spawn-fail")
    assert result["out"]["bashBlocked"]["block"] is True
    assert result["out"]["bashAllowed"]["block"] is True  # every bash call blocks when the guard itself cannot run


@requires_node
def test_forced_spawn_failure_secret_guard_fails_open(tmp_path_factory):
    config = {
        "root": str(ROOT),
        "guardRunnerPath": str(GUARD_RUNNER_TS),
        "cwd": str(ROOT),
        "sessionId": "sess-spawn-fail",
        "secretContent": _SECRET_CONTENT,
        "tsFilePath": str(ROOT / "pi" / "extensions" / "index.ts"),
        "forceSpawnFailure": True,
    }
    result = _run_node(_GUARDS_DRIVER, [str(GUARDS_TS), json.dumps(config)], tmp_path_factory, label="pi-guards-spawn-fail-2")
    assert result["out"].get("writeBlocked") is None  # secret_guard.py's spawn failure must fail OPEN
    assert result["out"].get("editShortCircuit") is None


_REAL_SPAWN_FAILURE_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , guardRunnerPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const { runGuard } = await import(pathToFileURL(guardRunnerPath).href);

try {
  await runGuard({
    interpreter: config.interpreter,
    scriptPath: config.scriptPath,
    payload: {},
    cwd: config.cwd,
    pluginRoot: config.cwd,
    signal: undefined,
  });
  console.log(JSON.stringify({ threw: false }));
} catch (err) {
  console.log(JSON.stringify({ threw: true, message: String(err && err.message) }));
}
"""


@requires_node
def test_guard_runner_real_spawn_rejects_on_nonexistent_interpreter(tmp_path_factory):
    """Exercises guard-runner.ts's ACTUAL child_process.spawn -> child.on("error") -> reject
    wiring — not the injected-mock failure path the tests above use. This is the highest-stakes
    branch in the diff (it's what governs bash_guard.sh's fail-closed posture) and must be
    covered by more than a fake throwing function standing in for it."""
    config = {
        "interpreter": "/nonexistent/interpreter-xyz-607",
        "scriptPath": str(ROOT / "hooks" / "bash_guard.sh"),
        "cwd": str(ROOT),
    }
    result = _run_node(
        _REAL_SPAWN_FAILURE_DRIVER,
        [str(GUARD_RUNNER_TS), json.dumps(config)],
        tmp_path_factory,
        label="pi-guard-runner-real-spawn-fail",
    )
    assert result["threw"] is True


@requires_node
def test_missing_script_exits_127_and_bash_guard_still_fails_closed(tmp_path_factory):
    """A missing/unreadable hooks/bash_guard.sh makes bash itself exit 127 — spawn() succeeds
    (bash exists), so this is NOT a JS-level spawn failure. Regression coverage: an exit code
    outside {0, 2} used to fall straight through to allow. Uses the REAL (uninjected) runGuard."""
    synthetic_root = tmp_path_factory.mktemp("pi-missing-script-root")
    # deliberately no hooks/ directory at all under synthetic_root
    config = {"root": str(synthetic_root), "cwd": str(ROOT), "tsFilePath": str(ROOT / "pi" / "extensions" / "index.ts")}
    result = _run_node(
        _GUARDS_DRIVER,
        [str(GUARDS_TS), json.dumps({**config, "guardRunnerPath": str(GUARD_RUNNER_TS), "sessionId": "sess-missing-script", "secretContent": _SECRET_CONTENT, "forceSpawnFailure": False})],
        tmp_path_factory,
        label="pi-guards-missing-script",
    )
    blocked = result["out"]["bashAllowed"]  # "ls -la" — a totally safe command
    assert blocked is not None and blocked["block"] is True
    assert "fail-closed" in blocked["reason"]


@requires_node
def test_skill_hint_session_id_is_hard_required_not_pid_fallback(tmp_path_factory):
    """An empty session id must never silently fall back to skill_autoload_hint.sh's $$ PID
    sentinel — two Pi sessions sharing one process would then share dedup state."""
    config = {"root": str(ROOT), "cwd": str(ROOT), "tsFilePath": str(ROOT / "pi" / "extensions" / "index.ts")}
    result = _run_node(
        _EMPTY_SESSION_ID_DRIVER, [str(GUARDS_TS), json.dumps(config)], tmp_path_factory, label="pi-guards-empty-session"
    )
    assert result["threw"] is True
    assert "session id" in result["message"].lower()


@requires_node
def test_skill_hint_two_sessions_share_no_adapter_level_dedup_state(tmp_path_factory):
    """Session A hints once, then is suppressed on a second call for the SAME session (that
    dedup lives entirely in skill_autoload_hint.sh's own filesystem sentinel). Session B, with a
    different id, must still get a hint despite A already being fully hinted — proving the
    adapter itself holds no cross-session Set/Map of its own."""
    import uuid

    session_a = f"sess-a-{uuid.uuid4().hex}"
    session_b = f"sess-b-{uuid.uuid4().hex}"
    config = {
        "root": str(ROOT),
        "cwd": str(ROOT),
        "tsFilePath": str(ROOT / "pi" / "extensions" / "index.ts"),
        "sessionIds": [session_a, session_a, session_b],
    }
    results = _run_node(
        _TWO_SESSION_DRIVER, [str(GUARDS_TS), json.dumps(config)], tmp_path_factory, label="pi-guards-two-session"
    )
    assert [r["sessionId"] for r in results] == [session_a, session_a, session_b]
    assert results[0]["sentCount"] == 1, "session A's first tool_result must produce a hint"
    assert results[1]["sentCount"] == 0, "session A's second tool_result for the same file must be deduped"
    assert results[2]["sentCount"] == 1, "session B must still get a hint despite session A already being fully hinted"


# ---------------------------------------------------------------------------
# Differential acceptance criterion — Pi-adapter half. tests/test_hooks.py runs the SAME
# pi_guard_fixtures.BASH_GUARD_FIXTURES set by invoking hooks/bash_guard.sh directly; this
# drives the identical fixture set through pi/extensions/guards.ts and asserts an identical
# block/allow verdict.
# ---------------------------------------------------------------------------

_BASH_FIXTURES_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , guardsPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const { registerGuards } = await import(pathToFileURL(guardsPath).href);

const handlers = {};
const stubPi = { on(event, handler) { handlers[event] = handler; }, sendMessage() {} };
registerGuards(stubPi, config.root, {});

const stubCtx = {
  hasUI: true,
  cwd: config.cwd,
  signal: undefined,
  ui: { notify() {} },
  sessionManager: { getSessionId: () => "sess-differential" },
};

const results = [];
for (const command of config.commands) {
  const result = await handlers["tool_call"]({ type: "tool_call", toolCallId: "t", toolName: "bash", input: { command } }, stubCtx);
  results.push(result ? { blocked: true, reason: result.reason } : { blocked: false });
}

console.log(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def bash_fixtures_via_adapter(tmp_path_factory):
    from pi_guard_fixtures import BASH_GUARD_FIXTURES

    config = {"root": str(ROOT), "cwd": str(ROOT), "commands": [cmd for cmd, _ in BASH_GUARD_FIXTURES]}
    return _run_node(
        _BASH_FIXTURES_DRIVER, [str(GUARDS_TS), json.dumps(config)], tmp_path_factory, label="pi-bash-fixtures-driver"
    )


@requires_node
def test_adapter_verdict_matches_direct_invocation_for_every_fixture(bash_fixtures_via_adapter):
    from pi_guard_fixtures import BASH_GUARD_FIXTURES

    assert len(bash_fixtures_via_adapter) == len(BASH_GUARD_FIXTURES)
    mismatches = []
    for (cmd, expect_blocked), result in zip(BASH_GUARD_FIXTURES, bash_fixtures_via_adapter):
        if result["blocked"] != expect_blocked:
            mismatches.append(f"{cmd!r}: expected blocked={expect_blocked}, adapter returned {result}")
    assert not mismatches, "adapter verdict diverged from direct-invocation verdict:\n" + "\n".join(mismatches)


# ---------------------------------------------------------------------------
# Behavioural: tool-vocab.ts. Pure text generation — no stub `pi`/`ctx` needed, but still
# imported through Node under --experimental-strip-types since it is a .ts module.
# ---------------------------------------------------------------------------

_TOOL_VOCAB_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , modPath, root, taskToolRegistered] = process.argv;
const mod = await import(pathToFileURL(modPath).href);
const section = taskToolRegistered === undefined
  ? mod.toolVocabSection(root)
  : mod.toolVocabSection(root, taskToolRegistered === "true");
console.log(JSON.stringify(section));
"""


def _tool_vocab_section(root, tmp_path_factory, task_tool_registered=None):
    args = [str(TOOL_VOCAB_TS), str(root)]
    if task_tool_registered is not None:
        args.append("true" if task_tool_registered else "false")
    return _run_node(_TOOL_VOCAB_DRIVER, args, tmp_path_factory, label="pi-tool-vocab-driver")


@requires_node
def test_tool_vocab_section_has_rename_table_and_legend_rule(tmp_path_factory):
    section = _tool_vocab_section(ROOT, tmp_path_factory)
    assert section["title"] == "Claude Code -> Pi tool vocabulary"
    for cc_name, pi_name in [("Read", "read"), ("Write", "write"), ("Edit", "edit"), ("Bash", "bash"), ("Grep", "grep"), ("Glob", "find"), ("LS", "ls")]:
        assert f"`{cc_name}`" in section["body"] and f"`{pi_name}`" in section["body"]
    assert "swe-workbench:<id>" in section["body"] and "/skill:<id>" in section["body"]
    assert "superpowers:<id>" in section["body"]
    assert "ask_user_question" in section["body"]
    assert "ExitPlanMode" in section["body"]
    assert "EnterWorktree" in section["body"]
    assert "fabricate `Task` calls" in section["body"]


@requires_node
def test_tool_vocab_section_names_task_tool_when_registered(tmp_path_factory):
    """taskToolRegistered=true must swap the 'do not fabricate `Task` calls' framing for prose
    naming the real `task` tool — a stale fabrication warning while `task` is actually live would
    actively mislead the model."""
    section = _tool_vocab_section(ROOT, tmp_path_factory, task_tool_registered=True)
    assert "`task(agent, prompt)`" in section["body"]
    assert "fabricate `Task` calls" not in section["body"]
    # Unaffected sections must still be present.
    assert "| `Read` | `read` |" in section["body"]
    assert "ask_user_question" in section["body"]


@requires_node
def test_tool_vocab_generated_skill_id_list_matches_disk(tmp_path_factory):
    section = _tool_vocab_section(ROOT, tmp_path_factory)
    on_disk = sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))
    for skill_id in on_disk:
        assert skill_id in section["body"], f"{skill_id} missing from the generated skill legend"


@requires_node
def test_tool_vocab_missing_skills_dir_degrades_to_rule_without_list(tmp_path_factory):
    """A root with no skills/ directory at all must not throw — the legend degrades to the bare
    rule, mirroring index.ts's readCurrentScripts posture for a missing bin/README.md."""
    synthetic_root = tmp_path_factory.mktemp("pi-tool-vocab-no-skills")
    section = _tool_vocab_section(synthetic_root, tmp_path_factory)
    assert "swe-workbench:<id>" in section["body"]
    assert "Available ids:" not in section["body"]


# ---------------------------------------------------------------------------
# Behavioural: ask-user.ts. Drives the real registerAskUser(pi) against a stub ExtensionAPI/
# ExtensionContext — no LLM, no real TUI.
# ---------------------------------------------------------------------------

_ASK_USER_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , modPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const mod = await import(pathToFileURL(modPath).href);

let registered;
const stubPi = { registerTool(tool) { registered = tool; } };
mod.registerAskUser(stubPi);

const out = { registered: registered !== undefined };
if (registered) {
  const inputCalls = [];
  const selectCalls = [];
  function makeCtx(hasUI) {
    return {
      hasUI,
      ui: {
        select: async (title, options) => { selectCalls.push({ title, options }); return options[0]; },
        input: async (...args) => { inputCalls.push(args); return "SHOULD-NEVER-HAPPEN"; },
      },
    };
  }
  async function run(hasUI, params) {
    try {
      const result = await registered.execute("tc1", params, undefined, undefined, makeCtx(hasUI));
      return { ok: true, result };
    } catch (err) {
      return { ok: false, message: String(err && err.message) };
    }
  }
  out.singleSelect = await run(true, config.singleParams);
  out.multiSelect = await run(true, config.multiParams);
  out.duplicate = await run(true, config.duplicateParams);
  out.noUI = await run(false, config.singleParams);
  out.selectCalls = selectCalls;
  out.inputCalls = inputCalls;
}
console.log(JSON.stringify(out));
"""


def _ask_user_result(env, tmp_path_factory):
    config = {
        "singleParams": {
            "questions": [
                {"question": "Pick one", "header": "Pick", "multiSelect": False, "options": [{"label": "A", "description": "desc A"}, {"label": "B"}]},
            ]
        },
        "multiParams": {
            "questions": [{"question": "Pick many", "header": "Many", "multiSelect": True, "options": [{"label": "A"}, {"label": "B"}]}]
        },
        "duplicateParams": {
            "questions": [
                {"question": "Same text", "header": "Q1", "multiSelect": False, "options": [{"label": "A"}, {"label": "B"}]},
                {"question": "Same text", "header": "Q2", "multiSelect": False, "options": [{"label": "C"}, {"label": "D"}]},
            ]
        },
    }
    node = shutil.which("node")
    assert node is not None
    driver = tmp_path_factory.mktemp("pi-ask-user-driver") / "driver.mjs"
    driver.write_text(_ASK_USER_DRIVER, encoding="utf-8")
    run_env = dict(_CLEAN_ENV)
    run_env.update(env)
    result = subprocess.run(
        [node, "--experimental-strip-types", str(driver), str(ASK_USER_TS), json.dumps(config)],
        capture_output=True, text=True, env=run_env, timeout=30,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    return json.loads(result.stdout)


@requires_node
def test_ask_user_registers_by_default(tmp_path_factory):
    result = _ask_user_result({}, tmp_path_factory)
    assert result["registered"] is True


@requires_node
def test_ask_user_kill_switch_skips_registration(tmp_path_factory):
    result = _ask_user_result({"SWE_WORKBENCH_PI_TOOLS": "0"}, tmp_path_factory)
    assert result["registered"] is False


@requires_node
def test_ask_user_single_select_returns_the_choice_via_ctx_ui_select(tmp_path_factory):
    result = _ask_user_result({}, tmp_path_factory)
    assert result["singleSelect"]["ok"] is True
    assert result["singleSelect"]["result"]["details"] == {"Pick one": "A — desc A"}
    assert result["selectCalls"][0]["options"] == ["A — desc A", "B"]
    assert result["inputCalls"] == [], "ask_user_question must never fall back to ctx.ui.input"


@requires_node
def test_ask_user_multi_select_is_rejected_with_a_remedy(tmp_path_factory):
    result = _ask_user_result({}, tmp_path_factory)
    assert result["multiSelect"]["ok"] is False
    assert "sequential single-select" in result["multiSelect"]["message"]


@requires_node
def test_ask_user_duplicate_question_text_is_rejected(tmp_path_factory):
    """answers[] is keyed by question text — a duplicate would silently overwrite an earlier
    answer with no error, one of the user's picks vanishing unnoticed. Must reject up front,
    before any ctx.ui.select call."""
    result = _ask_user_result({}, tmp_path_factory)
    assert result["duplicate"]["ok"] is False
    assert "duplicate question" in result["duplicate"]["message"]


@requires_node
def test_ask_user_no_ui_fails_loudly_without_calling_input(tmp_path_factory):
    result = _ask_user_result({}, tmp_path_factory)
    assert result["noUI"]["ok"] is False
    assert "interactive UI" in result["noUI"]["message"]
    assert result["inputCalls"] == [], "hasUI:false must fail loudly, never silently fall back to ctx.ui.input"


# ---------------------------------------------------------------------------
# Behavioural: subagent.ts. Drives the real registerSubagent(pi, root) against a stub
# ExtensionAPI/ExtensionContext and a synthetic agents/+skills/ tree — no real `pi.exec`, no LLM.
# ---------------------------------------------------------------------------

SUBAGENT_TS = ROOT / "pi" / "extensions" / "subagent.ts"
AGENT_SPEC_TS = ROOT / "pi" / "extensions" / "agent-spec.ts"
MODEL_POLICY_TS = ROOT / "pi" / "extensions" / "model-policy.ts"

_SUBAGENT_DRIVER = """
import { existsSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [, , modPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const mod = await import(pathToFileURL(modPath).href);

const execCalls = [];
const modelRegistryCalls = [];
const notifyCalls = [];
const stubPi = {
  registerTool(tool) { this._registered = tool; },
  async exec(command, args, options) {
    // Read the composed prompt's content HERE, before returning — subagent.ts deletes the temp
    // file in its own `finally` immediately after this call resolves, so by the time run()
    // returns to the caller below, the file is already gone.
    const promptIdx = args.indexOf("--append-system-prompt");
    const promptFileContent = promptIdx === -1 ? null : readFileSync(args[promptIdx + 1], "utf8");
    execCalls.push({
      command, args, promptFileContent,
      cwd: options && options.cwd, timeout: options && options.timeout,
    });
    if (config.execBehavior === "throw") throw new Error("forced exec throw (test)");
    if (config.execBehavior === "failure") return { stdout: "", stderr: "boom", code: 1, killed: false };
    return { stdout: "agent output", stderr: "", code: 0, killed: false };
  },
};

mod.registerSubagent(stubPi, config.root);
const registered = stubPi._registered;
const out = { registered: registered !== undefined, toolName: registered && registered.name };

function lastPromptFile() {
  const last = execCalls[execCalls.length - 1];
  const idx = last.args.indexOf("--append-system-prompt");
  return last.args[idx + 1];
}

async function run(agent, prompt, model, availableModels, scopedModels, thinkingLevel, hasUI) {
  const ctx = {
    cwd: config.cwd,
    model,
    thinkingLevel,
    hasUI: hasUI === undefined ? true : hasUI,
    ui: { notify: (message, level) => notifyCalls.push({ message, level }) },
    scopedModels: scopedModels || [],
    modelRegistry: {
      getAvailable() {
        modelRegistryCalls.push(availableModels || []);
        return availableModels || [];
      },
    },
  };
  try {
    const result = await registered.execute("tc1", { agent, prompt }, undefined, undefined, ctx);
    return { ok: true, result };
  } catch (err) {
    return { ok: false, message: String(err && err.message) };
  }
}

if (registered) {
  out.notFound = await run("does-not-exist", "hi");
  // execute()'s unknown-agent error must strip the id before interpolating it into tool
  // output — same pre-validation threat model as the render path.
  out.notFoundPoisoned = await run("ev\\x1bil\\u202e", "hi");

  // renderCall probes. This driver runs under plain `node --experimental-strip-types`
  // with no pi jiti alias map, so the module's dynamic pi-tui import is unsettled or
  // rejected at probe time — the registered renderCall takes the fallback-throw branch in
  // that state, which is Pi's framework-fallback contract (tool-execution.js catches and
  // swaps in createCallFallback). The resolved path is proven through the exported pure
  // renderer with an injected fake Text ctor instead.
  const stubTheme = {
    fg: (token, s) => `<${token}>${s}</${token}>`,
    bold: (s) => `**${s}**`,
  };
  out.composedLine = typeof mod.composeTaskCallLine === "function"
    ? mod.composeTaskCallLine("reviewer", stubTheme)
    : null;
  // Mid-stream args reach renderCall BEFORE execute() validates the agent id, so the
  // formatter itself must neutralize control and bidi/format chars (ESC/OSC/newline, RLO,
  // ZWSP) — the row is already on screen by the time an invalid id would be rejected.
  out.composedLineStripped = typeof mod.composeTaskCallLine === "function"
    ? mod.composeTaskCallLine("rev\\x1biewer\\u202e\\u061c\\u200b\\u0007\\n", stubTheme)
    : null;
  class FakeText {
    constructor(text, paddingX, paddingY) { this.text = text; this.px = paddingX; this.py = paddingY; }
  }
  out.hasRenderCall = typeof registered.renderCall === "function";
  const probe = (fn) => {
    try { return { threw: false, value: fn() }; } catch (err) { return { threw: true, message: String(err && err.message) }; }
  };
  // A control-only agent id strips to an empty segment — the enriched line would degrade
  // to "task \u00b7 " with a dangling separator, so the renderer must fall back instead.
  out.renderControlOnlyAgent = probe(() => mod.renderTaskCall({ agent: "\\x1b" }, stubTheme, FakeText));
  out.renderNamedNoCtor = probe(() => registered.renderCall({ agent: "reviewer", prompt: "hi" }, stubTheme));
  out.renderUnnamed = probe(() => registered.renderCall({ prompt: "hi" }, stubTheme));
  out.renderBlankAgent = probe(() => registered.renderCall({ agent: "   ", prompt: "hi" }, stubTheme));
  out.renderTaskCallMissingCtor = probe(() => mod.renderTaskCall({ agent: "reviewer" }, stubTheme, undefined));
  out.renderTaskCallResolved = probe(() => {
    const c = mod.renderTaskCall({ agent: "code-impl" }, stubTheme, FakeText);
    return { text: c.text, px: c.px, py: c.py };
  });

  out.emptyTools = await run("empty-tools-agent", "hi");

  execCalls.length = 0;
  out.success = await run("real-agent", "hi");
  out.successExecCalls = execCalls.slice();
  out.promptFileGoneAfterSuccess = !existsSync(lastPromptFile());

  execCalls.length = 0;
  notifyCalls.length = 0;
  out.withModel = await run("real-agent", "hi", { provider: "anthropic", id: "claude-x" });
  out.withModelExecCalls = execCalls.slice();
  out.withModelNotifyCalls = notifyCalls.slice();

  execCalls.length = 0;
  out.execThrows = await run("real-agent", "hi");
  out.promptFileGoneAfterThrow = !existsSync(lastPromptFile());

  execCalls.length = 0;
  out.execFails = await run("real-agent", "hi");

  const anthropicCandidates = [
    { provider: "anthropic", id: "claude-haiku-4-5" },
    { provider: "anthropic", id: "claude-sonnet-5" },
    { provider: "anthropic", id: "claude-opus-5" },
  ];
  const mixedProviderCandidates = [
    ...anthropicCandidates,
    { provider: "openai-codex", id: "gpt-5.6-luna" },
  ];
  const noHaikuCandidates = anthropicCandidates.filter((c) => c.id !== "claude-haiku-4-5");

  execCalls.length = 0;
  out.tieredAgentResolvesHaiku = await run(
    "tiered-agent", "hi", { provider: "anthropic", id: "claude-sonnet-5" }, anthropicCandidates,
  );
  out.tieredAgentExecCalls = execCalls.slice();

  execCalls.length = 0;
  out.tieredAgentIgnoresOtherProviderCandidates = await run(
    "tiered-agent", "hi", { provider: "anthropic", id: "claude-sonnet-5" }, mixedProviderCandidates,
  );
  out.tieredAgentIgnoresOtherProviderExecCalls = execCalls.slice();

  // Parent's own thinking level (ctx.thinkingLevel) must survive unchanged on a fallback path
  // when present — this run passes "high" explicitly.
  execCalls.length = 0;
  notifyCalls.length = 0;
  out.untieredAgentFallsBackToParentModel = await run(
    "real-agent", "hi", { provider: "anthropic", id: "claude-sonnet-5" }, anthropicCandidates, undefined, "high",
  );
  out.untieredAgentFallsBackExecCalls = execCalls.slice();
  out.untieredAgentFallsBackNotifyCalls = notifyCalls.slice();

  // Same fallback, but with no parent thinking level at all — --thinking must be omitted, not
  // sent as some default.
  execCalls.length = 0;
  out.untieredAgentNoParentThinking = await run(
    "real-agent", "hi", { provider: "anthropic", id: "claude-sonnet-5" }, anthropicCandidates,
  );
  out.untieredAgentNoParentThinkingExecCalls = execCalls.slice();

  execCalls.length = 0;
  notifyCalls.length = 0;
  out.effortUnknownFallback = await run(
    "tiered-no-effort-agent", "hi", { provider: "anthropic", id: "claude-sonnet-5" }, anthropicCandidates,
  );
  out.effortUnknownExecCalls = execCalls.slice();
  out.effortUnknownNotifyCalls = notifyCalls.slice();

  execCalls.length = 0;
  notifyCalls.length = 0;
  out.providerUnsupportedFallback = await run(
    "tiered-agent", "hi", { provider: "google", id: "gemini-x" }, [],
  );
  out.providerUnsupportedExecCalls = execCalls.slice();
  out.providerUnsupportedNotifyCalls = notifyCalls.slice();

  execCalls.length = 0;
  notifyCalls.length = 0;
  out.modelUnavailableFallback = await run(
    "tiered-agent", "hi", { provider: "anthropic", id: "claude-sonnet-5" }, noHaikuCandidates,
  );
  out.modelUnavailableExecCalls = execCalls.slice();
  out.modelUnavailableNotifyCalls = notifyCalls.slice();

  // hasUI:false (print mode) must still surface the fallback in the tool result content, but
  // must never call ctx.ui.notify (there is no UI to receive it).
  execCalls.length = 0;
  notifyCalls.length = 0;
  out.fallbackHeadless = await run(
    "real-agent", "hi", { provider: "anthropic", id: "claude-sonnet-5" }, anthropicCandidates,
    undefined, undefined, false,
  );
  out.fallbackHeadlessNotifyCalls = notifyCalls.slice();

  // ctx.scopedModels restricts the session to only claude-sonnet-5 — the haiku-tier candidate
  // exists in the full modelRegistry catalog but is NOT in scope, so resolution must respect
  // the restriction (fall back to the parent model) rather than reaching past it.
  const sonnetOnlyScope = [{ model: { provider: "anthropic", id: "claude-sonnet-5" } }];

  execCalls.length = 0;
  modelRegistryCalls.length = 0;
  out.scopedModelsRestrictsResolution = await run(
    "tiered-agent", "hi", { provider: "anthropic", id: "claude-sonnet-5" }, anthropicCandidates, sonnetOnlyScope,
  );
  out.scopedModelsExecCalls = execCalls.slice();
  out.scopedModelsBypassedModelRegistry = modelRegistryCalls.length === 0;
}
console.log(JSON.stringify(out));
"""


def _write_synthetic_agents_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("pi-subagent-root")
    agents = root / "agents"
    agents.mkdir()
    (agents / "real-agent.md").write_text(
        "---\n"
        "name: real-agent\n"
        "description: test agent\n"
        "tools: Read, Bash\n"
        "skills:\n"
        "  - swe-workbench:fake-skill\n"
        "---\n\n"
        "Real agent body.\n",
        encoding="utf-8",
    )
    (agents / "empty-tools-agent.md").write_text(
        "---\n"
        "name: empty-tools-agent\n"
        "description: test agent with no mappable tools\n"
        "tools: Skill\n"
        "---\n\n"
        "Empty tools agent body.\n",
        encoding="utf-8",
    )
    (agents / "tiered-agent.md").write_text(
        "---\n"
        "name: tiered-agent\n"
        "description: test agent with a known model tier and effort\n"
        "model: haiku\n"
        "effort: high\n"
        "tools: Read\n"
        "---\n\n"
        "Tiered agent body.\n",
        encoding="utf-8",
    )
    (agents / "tiered-no-effort-agent.md").write_text(
        "---\n"
        "name: tiered-no-effort-agent\n"
        "description: test agent with a known model tier but no effort\n"
        "model: sonnet\n"
        "tools: Read\n"
        "---\n\n"
        "Tiered no-effort agent body.\n",
        encoding="utf-8",
    )
    skill_dir = root / "skills" / "fake-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: fake-skill\ndescription: test skill\n---\n"
        "<!-- preload-canary: SWB-PRELOAD-FAKE-SKILL -->\n\nFake skill body.\n",
        encoding="utf-8",
    )
    return root


def _subagent_result(root, tmp_path_factory, *, exec_behavior="success", env=None):
    config = {"root": str(root), "cwd": str(root), "execBehavior": exec_behavior}
    node = shutil.which("node")
    assert node is not None
    driver = tmp_path_factory.mktemp("pi-subagent-driver") / "driver.mjs"
    driver.write_text(_SUBAGENT_DRIVER, encoding="utf-8")
    run_env = dict(_CLEAN_ENV)
    run_env.update(env or {})
    result = subprocess.run(
        [node, "--experimental-strip-types", str(driver), str(SUBAGENT_TS), json.dumps(config)],
        capture_output=True, text=True, env=run_env, timeout=30,
    )
    assert result.returncode == 0, f"driver failed: {result.stderr}"
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def subagent_root(tmp_path_factory):
    return _write_synthetic_agents_root(tmp_path_factory)


@requires_node
def test_subagent_registers_by_default(subagent_root, tmp_path_factory):
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["registered"] is True
    assert result["toolName"] == "task"


@requires_node
def test_subagent_kill_switch_skips_registration(subagent_root, tmp_path_factory):
    result = _subagent_result(subagent_root, tmp_path_factory, env={"SWE_WORKBENCH_PI_TOOLS": "0"})
    assert result["registered"] is False


@requires_node
def test_task_call_line_composes_tool_title_and_agent_identity(subagent_root, tmp_path_factory):
    """Assert composeTaskCallLine reproduces Pi's createCallFallback() toolTitle segment
    plus a muted agent suffix."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["composedLine"] == "<toolTitle>**task**</toolTitle><muted> · reviewer</muted>"
    assert result["hasRenderCall"] is True, "task must register a renderCall override"


@requires_node
def test_task_call_line_strips_control_chars_from_unvalidated_agent_arg(subagent_root, tmp_path_factory):
    """Assert the composed line neutralizes control and bidi/format chars in the agent id.

    renderCall fires on mid-stream args before execute() validation, so ESC/OSC/newline and
    RLO/ZWSP injection must be stripped in the formatter itself (screen-clear, title, and
    visual-reorder spoofing guard).
    """
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["composedLineStripped"] == "<toolTitle>**task**</toolTitle><muted> · reviewer</muted>"


@requires_node
def test_task_render_call_falls_back_when_agent_strips_to_empty(subagent_root, tmp_path_factory):
    """Assert a control-only agent id falls back rather than rendering a dangling separator."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["renderControlOnlyAgent"]["threw"] is True
    assert "task" in result["renderControlOnlyAgent"]["message"]


@requires_node
def test_task_render_call_throws_to_framework_fallback_without_pi_tui(subagent_root, tmp_path_factory):
    """Assert the degrade contract: with no Text constructor, renderCall throws so Pi swaps
    in its own fallback heading."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["hasRenderCall"] is True
    # Explicit-undefined ctor is environment-independent: must always throw with a message
    # naming the tool (Pi's fallback swaps in the plain heading; the message is ours).
    assert result["renderTaskCallMissingCtor"]["threw"] is True
    assert "task" in result["renderTaskCallMissingCtor"]["message"]
    # The registered renderCall races the pi-tui import: nodeless CI must take the throw
    # (fallback) branch; where pi-tui resolved, it must return the enriched component instead.
    named = result["renderNamedNoCtor"]
    if named["threw"]:
        assert "task" in named["message"]
    else:
        assert named["value"] is not None, "resolved path must return a component, not undefined"


@requires_node
def test_task_render_call_throws_for_missing_or_blank_agent(subagent_root, tmp_path_factory):
    """Assert renderCall falls back (throws) for absent, partial, or blank agent args."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["hasRenderCall"] is True
    assert result["renderUnnamed"]["threw"] is True
    assert "task" in result["renderUnnamed"]["message"], (
        "must be the renderer's deliberate fallback throw, not a TypeError from a missing function"
    )
    assert result["renderBlankAgent"]["threw"] is True
    assert "task" in result["renderBlankAgent"]["message"]


@requires_node
def test_task_render_task_call_builds_text_with_composed_line_and_zero_padding(subagent_root, tmp_path_factory):
    """Assert the resolved path builds a Text with the composed line and (0, 0) padding."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    outcome = result["renderTaskCallResolved"]
    assert outcome["threw"] is False
    resolved = outcome["value"]
    assert resolved["text"] == "<toolTitle>**task**</toolTitle><muted> · code-impl</muted>"
    assert [resolved["px"], resolved["py"]] == [0, 0]


@requires_node
def test_subagent_unknown_agent_reports_available_list(subagent_root, tmp_path_factory):
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["notFound"]["ok"] is False
    assert "does-not-exist" in result["notFound"]["message"]
    assert "empty-tools-agent" in result["notFound"]["message"]
    assert "real-agent" in result["notFound"]["message"]


@requires_node
def test_subagent_unknown_agent_error_strips_poisoned_id(subagent_root, tmp_path_factory):
    """Assert the unknown-agent error strips control/format chars before interpolation.

    The message becomes tool-output content rendered unescaped, so a raw ESC/RLO in the
    echoed id would spoof the terminal through the result row.
    """
    result = _subagent_result(subagent_root, tmp_path_factory)
    poisoned = result["notFoundPoisoned"]
    assert poisoned["ok"] is False
    assert "\x1b" not in poisoned["message"]
    assert "\u202e" not in poisoned["message"]
    assert '"evil"' in poisoned["message"], "stripped id must remain identifiable"


@requires_node
def test_subagent_empty_translated_tools_throws_before_exec(subagent_root, tmp_path_factory):
    """empty-tools-agent's only tool token (Skill) is drop-only — translateToolTokens must
    throw before pi.exec is ever called, never silently build an empty --tools allowlist."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["emptyTools"]["ok"] is False
    assert "no Pi mapping" in result["emptyTools"]["message"] or "empty" in result["emptyTools"]["message"]


@requires_node
def test_subagent_success_builds_expected_argv_and_cleans_up_temp_file(subagent_root, tmp_path_factory):
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["success"]["ok"] is True
    assert result["success"]["result"]["content"] == [{"type": "text", "text": "agent output"}]

    call = result["successExecCalls"][0]
    assert call["command"] == "pi"
    args = call["args"]
    assert args[0] == "-p" and args[1] == "hi"
    assert "--append-system-prompt" in args
    tools_idx = args.index("--tools")
    tool_names = set(args[tools_idx + 1].split(","))
    assert tool_names == {"read", "bash", "ask_user_question"}
    exclude_idx = args.index("--exclude-tools")
    assert args[exclude_idx + 1] == "task,subagent"
    assert "--no-session" in args
    assert "--model" not in args, "no --model flag when ctx.model is undefined"
    assert "--thinking" not in args, "no --thinking flag when ctx.model is undefined"

    assert result["promptFileGoneAfterSuccess"] is True


@requires_node
def test_subagent_composed_prompt_contains_agent_body_and_preloaded_skill_content(subagent_root, tmp_path_factory):
    """The whole point of this feature is that a dispatched agent's body AND its preloaded
    skills actually land in the child's system prompt — not just that some file got written and
    later deleted. Reads the --append-system-prompt temp file's real content (captured by the
    driver's stub exec() before subagent.ts's own finally block deletes it) and asserts on it."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    content = result["successExecCalls"][0]["promptFileContent"]
    assert content is not None
    assert "Real agent body." in content
    assert "Fake skill body." in content
    assert "SWB-PRELOAD-FAKE-SKILL" in content, "the preload-canary marker must survive composition"


@requires_node
def test_subagent_passes_model_when_ctx_model_defined(subagent_root, tmp_path_factory):
    """real-agent has no `model:` frontmatter tier, so this exercises the `tier-unknown`
    fallback path: ctx.model is passed through to --model unchanged, no --thinking (no parent
    thinking level was passed), and the fallback is surfaced as a UI warning plus a
    `[swe-workbench] ...` content line. The tier-resolution success path is covered separately
    below (tiered-agent)."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    args = result["withModelExecCalls"][0]["args"]
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "anthropic/claude-x"
    assert "--thinking" not in args

    run = result["withModel"]
    assert run["ok"] is True
    details = run["result"]["details"]
    assert details["agent"] == "real-agent"
    assert details["model"] == "anthropic/claude-x"
    assert details["fallbackReason"] == "tier-unknown"
    assert details["policySource"] == "parent-fallback"
    assert details.get("tier") is None
    content = run["result"]["content"]
    assert len(content) == 2, "a fallback warning line must be prepended to the stdout text"
    assert content[0]["text"].startswith("[swe-workbench] ")
    assert "tier-unknown" in content[0]["text"]
    assert content[1] == {"type": "text", "text": "agent output"}

    assert len(result["withModelNotifyCalls"]) == 1
    assert result["withModelNotifyCalls"][0]["level"] == "warning"


@requires_node
def test_subagent_cleans_up_temp_file_when_exec_throws(subagent_root, tmp_path_factory):
    result = _subagent_result(subagent_root, tmp_path_factory, exec_behavior="throw")
    assert result["execThrows"]["ok"] is False
    assert "forced exec throw" in result["execThrows"]["message"]
    assert result["promptFileGoneAfterThrow"] is True


@requires_node
def test_subagent_nonzero_exit_surfaces_stderr(subagent_root, tmp_path_factory):
    result = _subagent_result(subagent_root, tmp_path_factory, exec_behavior="failure")
    assert result["execFails"]["ok"] is False
    assert "boom" in result["execFails"]["message"]


@requires_node
def test_subagent_nonzero_exit_includes_fallback_warning_when_dispatch_degraded(subagent_root, tmp_path_factory):
    """A dispatch that already fell back to the parent model (real-agent has no `model:` tier,
    so this is a tier-unknown fallback) and then ALSO exits non-zero must surface both signals —
    losing the fallback context on a failure is exactly when a caller most needs to know the
    dispatched model wasn't the intended one."""
    result = _subagent_result(subagent_root, tmp_path_factory, exec_behavior="failure")
    run = result["withModel"]
    assert run["ok"] is False
    assert "exited 1" in run["message"]
    assert "boom" in run["message"]
    assert "tier-unknown" in run["message"]


_CAP_OUTPUT_DRIVER = """
import { pathToFileURL } from "node:url";
const [, , modPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const mod = await import(pathToFileURL(modPath).href);
console.log(JSON.stringify({
  underCap: mod.capOutput(config.shortText),
  emojiBoundary: mod.capOutput(config.emojiBoundaryText),
  plainBoundary: mod.capOutput(config.plainBoundaryText),
}));
"""


@requires_node
def test_cap_output_does_not_split_a_surrogate_pair_at_the_boundary(tmp_path_factory):
    """capOutput's slice() is a UTF-16 code-unit cut, tested directly (not through the full
    exec/JSON/stdout-UTF-8 round trip — a lone surrogate does not survive that pipeline intact,
    so this Unicode edge case has to be verified in-process). A surrogate pair (an emoji)
    straddling the OUTPUT_CAP_CHARS boundary must not leave a lone leading surrogate dangling in
    the truncated result — the resulting string must stay well-formed UTF-16 throughout."""
    emoji = "\U0001F600"  # 2 UTF-16 code units — the high surrogate lands exactly at index 49999
    config = {
        "shortText": "hello",
        "emojiBoundaryText": ("a" * 49999) + emoji + "TAIL",
        "plainBoundaryText": "b" * 50010,
    }
    result = _run_node(_CAP_OUTPUT_DRIVER, [str(SUBAGENT_TS), json.dumps(config)], tmp_path_factory, label="pi-cap-output-driver")

    assert result["underCap"] == "hello", "text under the cap must pass through unchanged"

    emoji_boundary = result["emojiBoundary"]
    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in emoji_boundary), (
        "a lone surrogate leaked into the truncated output — ill-formed UTF-16"
    )
    assert emoji_boundary.startswith("a" * 49999)
    assert "[truncated" in emoji_boundary

    plain_boundary = result["plainBoundary"]
    assert plain_boundary.startswith("b" * 50000)
    assert "[truncated" in plain_boundary


@requires_node
def test_subagent_tiered_agent_resolves_model_via_tier_table(subagent_root, tmp_path_factory):
    """End-to-end: tiered-agent's `model: haiku`/`effort: high` frontmatter, combined with
    ctx.model on anthropic and a fabricated ctx.modelRegistry.getAvailable() candidate list, must
    resolve to the haiku-tier candidate and its policy thinking level — not the parent's own
    (sonnet) model, and no fallback warning."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    run = result["tieredAgentResolvesHaiku"]
    assert run["ok"] is True
    args = result["tieredAgentExecCalls"][0]["args"]
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "anthropic/claude-haiku-4-5"
    thinking_idx = args.index("--thinking")
    assert args[thinking_idx + 1] == "high"

    details = run["result"]["details"]
    assert details["tier"] == "haiku"
    assert details["portableEffort"] == "high"
    assert details["policySource"] == "model-policy"
    assert details.get("fallbackReason") is None
    assert run["result"]["content"] == [{"type": "text", "text": "agent output"}], (
        "no fallback warning line on the success path"
    )


@requires_node
def test_subagent_tiered_agent_ignores_other_provider_candidates(subagent_root, tmp_path_factory):
    """The candidate list handed to resolveDispatch must already be filtered to
    ctx.model.provider — an openai-codex candidate must never leak into an anthropic
    resolution, even when both are present in ctx.modelRegistry.getAvailable()'s raw result."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["tieredAgentIgnoresOtherProviderCandidates"]["ok"] is True
    args = result["tieredAgentIgnoresOtherProviderExecCalls"][0]["args"]
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "anthropic/claude-haiku-4-5"
    thinking_idx = args.index("--thinking")
    assert args[thinking_idx + 1] == "high"


@requires_node
def test_subagent_untiered_agent_falls_back_to_parent_model(subagent_root, tmp_path_factory):
    """real-agent has no `model:` tier — even with a populated modelRegistry available, the
    resolved model must be the parent's own (ctx.model) unchanged, not something derived from the
    policy table, and the parent's own thinking level ("high", passed as ctx.thinkingLevel) must
    survive unchanged onto --thinking."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    run = result["untieredAgentFallsBackToParentModel"]
    assert run["ok"] is True
    args = result["untieredAgentFallsBackExecCalls"][0]["args"]
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "anthropic/claude-sonnet-5"
    thinking_idx = args.index("--thinking")
    assert args[thinking_idx + 1] == "high"

    details = run["result"]["details"]
    assert details["fallbackReason"] == "tier-unknown"
    assert details["policySource"] == "parent-fallback"
    assert len(result["untieredAgentFallsBackNotifyCalls"]) == 1


@requires_node
def test_subagent_fallback_omits_thinking_when_parent_has_none(subagent_root, tmp_path_factory):
    """The same tier-unknown fallback, but with no ctx.thinkingLevel at all — --thinking must be
    omitted entirely, never sent with some default value."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    assert result["untieredAgentNoParentThinking"]["ok"] is True
    args = result["untieredAgentNoParentThinkingExecCalls"][0]["args"]
    assert "--model" in args
    assert "--thinking" not in args


@requires_node
def test_subagent_effort_unknown_falls_back_to_parent_model(subagent_root, tmp_path_factory):
    """tiered-no-effort-agent has a known `model: sonnet` tier but no `effort:` — resolution must
    still fall back to the parent's own model/thinking (never a partially-resolved policy id),
    with fallbackReason "effort-unknown" and the known tier still reported."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    run = result["effortUnknownFallback"]
    assert run["ok"] is True
    args = result["effortUnknownExecCalls"][0]["args"]
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "anthropic/claude-sonnet-5"
    assert "--thinking" not in args

    details = run["result"]["details"]
    assert details["fallbackReason"] == "effort-unknown"
    assert details["policySource"] == "parent-fallback"
    assert details["tier"] == "sonnet"
    assert details.get("portableEffort") is None
    assert len(result["effortUnknownNotifyCalls"]) == 1


@requires_node
def test_subagent_provider_unsupported_falls_back_to_parent_model(subagent_root, tmp_path_factory):
    """tiered-agent's tier is known, but ctx.model.provider ("google") has no MODEL_POLICY row —
    resolution must fall back to the parent's own model unchanged with fallbackReason
    "provider-unsupported", even though the tier itself is recognized."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    run = result["providerUnsupportedFallback"]
    assert run["ok"] is True
    args = result["providerUnsupportedExecCalls"][0]["args"]
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "google/gemini-x"
    assert "--thinking" not in args

    details = run["result"]["details"]
    assert details["fallbackReason"] == "provider-unsupported"
    assert details["policySource"] == "parent-fallback"
    assert len(result["providerUnsupportedNotifyCalls"]) == 1


@requires_node
def test_subagent_model_unavailable_falls_back_to_parent_model(subagent_root, tmp_path_factory):
    """tiered-agent's tier/effort resolve via policy to claude-haiku-4-5, but the candidate pool
    doesn't carry that exact id — resolution must fall back to the parent's own model unchanged
    with fallbackReason "model-unavailable", never a substring or nearby-id match."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    run = result["modelUnavailableFallback"]
    assert run["ok"] is True
    args = result["modelUnavailableExecCalls"][0]["args"]
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "anthropic/claude-sonnet-5"

    details = run["result"]["details"]
    assert details["fallbackReason"] == "model-unavailable"
    assert details["policySource"] == "parent-fallback"
    assert details["tier"] == "haiku"
    assert details["portableEffort"] == "high"
    assert len(result["modelUnavailableNotifyCalls"]) == 1


@requires_node
def test_subagent_fallback_headless_skips_notify_but_still_warns_in_content(subagent_root, tmp_path_factory):
    """hasUI:false (print mode, the real shape for every dispatched child) must never call
    ctx.ui.notify — there's no UI to receive it — but the warning must still land in the tool
    result content, since that's the only place a headless caller can see it."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    run = result["fallbackHeadless"]
    assert run["ok"] is True
    assert result["fallbackHeadlessNotifyCalls"] == []
    content = run["result"]["content"]
    assert content[0]["text"].startswith("[swe-workbench] ")


@requires_node
def test_subagent_respects_scoped_models_over_full_registry(subagent_root, tmp_path_factory):
    """A session-scoped model list (ctx.scopedModels, from --models/enabledModels) must win over
    the full ctx.modelRegistry.getAvailable() catalog — a haiku candidate that exists in the full
    catalog but was never scoped into this session must not be reachable, and resolveTargetDispatch
    must not even query the full registry when scoping is configured."""
    result = _subagent_result(subagent_root, tmp_path_factory)
    run = result["scopedModelsRestrictsResolution"]
    assert run["ok"] is True
    args = result["scopedModelsExecCalls"][0]["args"]
    model_idx = args.index("--model")
    assert args[model_idx + 1] == "anthropic/claude-sonnet-5", (
        "haiku isn't in scope, so resolution must fall back to the parent's (sonnet) model"
    )
    assert result["scopedModelsBypassedModelRegistry"] is True
    assert run["result"]["details"]["fallbackReason"] == "model-unavailable"


# ---------------------------------------------------------------------------
# Behavioural: agent-spec.ts's pure functions (parseAgentSpec, composeSystemPrompt) directly —
# subagent.ts's integration tests above only exercise the well-formed happy path; these cover
# parser edge cases (missing required keys, CRLF normalization, zero/multiple skills) that a
# fixture-driven integration test alone would not catch a regression in.
# ---------------------------------------------------------------------------

_AGENT_SPEC_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , modPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const mod = await import(pathToFileURL(modPath).href);

function tryParse(text) {
  try {
    return { ok: true, result: mod.parseAgentSpec(text) };
  } catch (err) {
    return { ok: false, message: String(err && err.message) };
  }
}

const out = {
  wellFormed: tryParse(config.wellFormedText),
  missingName: tryParse(config.missingNameText),
  missingDescription: tryParse(config.missingDescriptionText),
  crlf: tryParse(config.crlfText),
  noSkills: tryParse(config.noSkillsText),
  multiSkills: tryParse(config.multiSkillsText),
  composeNoSkills: mod.composeSystemPrompt({ body: "Agent body." }, []),
  composeMultiSkills: mod.composeSystemPrompt(
    { body: "Agent body." },
    [
      { id: "swe-workbench:a", body: "Skill A body.", dir: "/fake/skills/a" },
      { id: "swe-workbench:b", body: "Skill B body.", dir: "/fake/skills/b" },
    ],
  ),
};
console.log(JSON.stringify(out));
"""

_WELL_FORMED_TEXT = (
    "---\nname: sample\ndescription: sample agent\ntools: Read, Bash\n"
    "skills:\n  - swe-workbench:one\n  - swe-workbench:two\n---\n\nSample agent body.\n"
)
_MISSING_NAME_TEXT = "---\ndescription: sample agent\n---\n\nBody.\n"
_MISSING_DESCRIPTION_TEXT = "---\nname: sample\n---\n\nBody.\n"
_CRLF_TEXT = "---\r\nname: sample\r\ndescription: sample agent\r\n---\r\n\r\nCRLF body.\r\n"
_NO_SKILLS_TEXT = "---\nname: sample\ndescription: sample agent\ntools: Read\n---\n\nNo skills body.\n"
_MULTI_SKILLS_TEXT = (
    "---\nname: sample\ndescription: sample agent\ntools: Read\n"
    "skills:\n  - swe-workbench:one\n  - swe-workbench:two\n  - swe-workbench:three\n"
    "---\n\nMulti skills body.\n"
)


@pytest.fixture(scope="module")
def agent_spec_result(tmp_path_factory):
    config = {
        "wellFormedText": _WELL_FORMED_TEXT,
        "missingNameText": _MISSING_NAME_TEXT,
        "missingDescriptionText": _MISSING_DESCRIPTION_TEXT,
        "crlfText": _CRLF_TEXT,
        "noSkillsText": _NO_SKILLS_TEXT,
        "multiSkillsText": _MULTI_SKILLS_TEXT,
    }
    return _run_node(
        _AGENT_SPEC_DRIVER, [str(AGENT_SPEC_TS), json.dumps(config)], tmp_path_factory, label="pi-agent-spec-driver"
    )


@requires_node
def test_parse_agent_spec_well_formed_extracts_all_fields(agent_spec_result):
    result = agent_spec_result["wellFormed"]
    assert result["ok"] is True
    spec = result["result"]
    assert spec["name"] == "sample"
    assert spec["description"] == "sample agent"
    assert spec["tools"] == ["Read", "Bash"]
    assert spec["skillIds"] == ["swe-workbench:one", "swe-workbench:two"]
    assert spec["body"] == "Sample agent body."


@requires_node
def test_parse_agent_spec_missing_name_throws(agent_spec_result):
    result = agent_spec_result["missingName"]
    assert result["ok"] is False
    assert "name" in result["message"]


@requires_node
def test_parse_agent_spec_missing_description_throws(agent_spec_result):
    result = agent_spec_result["missingDescription"]
    assert result["ok"] is False
    assert "description" in result["message"]


@requires_node
def test_parse_agent_spec_normalizes_crlf(agent_spec_result):
    result = agent_spec_result["crlf"]
    assert result["ok"] is True
    assert result["result"]["name"] == "sample"
    assert result["result"]["body"] == "CRLF body."


@requires_node
def test_parse_agent_spec_empty_skills_list_when_no_skills_key(agent_spec_result):
    result = agent_spec_result["noSkills"]
    assert result["ok"] is True
    assert result["result"]["skillIds"] == []


@requires_node
def test_parse_agent_spec_multiple_skills_preserves_order(agent_spec_result):
    result = agent_spec_result["multiSkills"]
    assert result["ok"] is True
    assert result["result"]["skillIds"] == ["swe-workbench:one", "swe-workbench:two", "swe-workbench:three"]


@requires_node
def test_compose_system_prompt_with_zero_skills_is_just_the_body(agent_spec_result):
    assert agent_spec_result["composeNoSkills"] == "Agent body."


@requires_node
def test_compose_system_prompt_with_multiple_skills_preserves_order(agent_spec_result):
    composed = agent_spec_result["composeMultiSkills"]
    body_idx = composed.index("Agent body.")
    a_idx = composed.index("Skill A body.")
    b_idx = composed.index("Skill B body.")
    assert body_idx < a_idx < b_idx, "skills must appear after the agent body, in skills: order"
    assert "swe-workbench:a" in composed and "swe-workbench:b" in composed


@requires_node
def test_compose_system_prompt_states_each_skills_resolvable_directory(agent_spec_result):
    """A skill's body can point at its own examples/ (or similar) with a bare relative path —
    the composed section must state the skill's absolute directory so a dispatched child with
    `read` can actually resolve that pointer, not just see a dead reference."""
    composed = agent_spec_result["composeMultiSkills"]
    assert "/fake/skills/a" in composed
    assert "/fake/skills/b" in composed


# ---------------------------------------------------------------------------
# Behavioural: model-policy.ts's pure functions directly. No stub `pi`/`ctx` needed.
# ---------------------------------------------------------------------------

_MODEL_POLICY_DRIVER = """
import { pathToFileURL } from "node:url";

const [, , modPath, configJson] = process.argv;
const config = JSON.parse(configJson);
const mod = await import(pathToFileURL(modPath).href);

const out = {
  knownTiers: {
    haiku: mod.isKnownModelTier("haiku"),
    sonnet: mod.isKnownModelTier("sonnet"),
    opus: mod.isKnownModelTier("opus"),
    other: mod.isKnownModelTier("gpt-5"),
    undef: mod.isKnownModelTier(undefined),
  },
  knownEfforts: {
    low: mod.isKnownEffort("low"),
    medium: mod.isKnownEffort("medium"),
    high: mod.isKnownEffort("high"),
    xhigh: mod.isKnownEffort("xhigh"),
    max: mod.isKnownEffort("max"),
    other: mod.isKnownEffort("ultra"),
    undef: mod.isKnownEffort(undefined),
  },
};
for (const [label, c] of Object.entries(config.cases)) {
  out[label] = mod.resolveDispatch({ parent: c.parent, tier: c.tier, effort: c.effort, candidates: c.candidates });
}
console.log(JSON.stringify(out));
"""


# Verbatim id list + order from the installed SDK's bundled Anthropic catalog
# (node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/
# providers/data/anthropic.json) — NOT a clean one-id-per-tier fixture. This is deliberate:
# multiple ids share the "opus"/"sonnet"/"haiku" substring (dated/versioned siblings of the bare
# flagship id). resolveDispatch's exact-id matching must pick precisely the bare flagship id
# despite these lookalikes sharing the pool, never a substring/nearby match.
_ANTHROPIC_CANDIDATES = [
    {"provider": "anthropic", "id": "claude-fable-5"},
    {"provider": "anthropic", "id": "claude-haiku-4-5"},
    {"provider": "anthropic", "id": "claude-haiku-4-5-20251001"},
    {"provider": "anthropic", "id": "claude-opus-4-5"},
    {"provider": "anthropic", "id": "claude-opus-4-5-20251101"},
    {"provider": "anthropic", "id": "claude-opus-4-6"},
    {"provider": "anthropic", "id": "claude-opus-4-7"},
    {"provider": "anthropic", "id": "claude-opus-4-8"},
    {"provider": "anthropic", "id": "claude-opus-5"},
    {"provider": "anthropic", "id": "claude-sonnet-4-5"},
    {"provider": "anthropic", "id": "claude-sonnet-4-5-20250929"},
    {"provider": "anthropic", "id": "claude-sonnet-4-6"},
    {"provider": "anthropic", "id": "claude-sonnet-5"},
]
_CODEX_CANDIDATES = [
    {"provider": "openai-codex", "id": "gpt-5.6-luna"},
    {"provider": "openai-codex", "id": "gpt-5.6-sol"},
    {"provider": "openai-codex", "id": "gpt-5.6-terra"},
    {"provider": "openai-codex", "id": "gpt-5.4-mini"},
]
_ZAI_CANDIDATES = [
    {"provider": "zai", "id": "glm-5.3"},
    {"provider": "zai", "id": "glm-5.2"},
    {"provider": "zai", "id": "glm-5.2-highspeed"},
]
_CANDIDATES_BY_PROVIDER = {"anthropic": _ANTHROPIC_CANDIDATES, "openai-codex": _CODEX_CANDIDATES, "zai": _ZAI_CANDIDATES}
_PARENT_BY_PROVIDER = {
    "anthropic": {"provider": "anthropic", "id": "claude-sonnet-5", "thinking": "medium"},
    "openai-codex": {"provider": "openai-codex", "id": "gpt-5.6-terra", "thinking": "medium"},
    "zai": {"provider": "zai", "id": "glm-5.3", "thinking": "medium"},
}
_DEFAULT_TIER_EFFORT = {"opus": "high", "sonnet": "xhigh", "haiku": "high"}

# The ticket's 3x3 default matrix, expected (model id, thinking) per (provider, tier), fed
# through DEFAULT_TIER_EFFORT — same source of truth as test_pi_contract.py's
# _TICKET_DEFAULT_MATRIX, exercised here via the real resolveDispatch() call site instead of a
# raw MODEL_POLICY table dump.
_EXPECTED_DEFAULT_CELL = {
    "anthropic": {
        "opus": ("claude-opus-5", "high"),
        "sonnet": ("claude-sonnet-5", "xhigh"),
        "haiku": ("claude-haiku-4-5", "high"),
    },
    "openai-codex": {
        "opus": ("gpt-5.6-sol", "high"),
        "sonnet": ("gpt-5.6-terra", "xhigh"),
        "haiku": ("gpt-5.6-luna", "high"),
    },
    "zai": {
        "opus": ("glm-5.3", "max"),
        "sonnet": ("glm-5.3", "high"),
        "haiku": ("glm-5.2-highspeed", "high"),
    },
}


def _model_policy_result(tmp_path_factory):
    cases = {}
    for provider, tiers in _EXPECTED_DEFAULT_CELL.items():
        for tier in tiers:
            cases[f"default_{provider}_{tier}"] = {
                "parent": _PARENT_BY_PROVIDER[provider],
                "tier": tier,
                "effort": _DEFAULT_TIER_EFFORT[tier],
                "candidates": _CANDIDATES_BY_PROVIDER[provider],
            }

    # Non-default zai efforts, to prove the shifted tables aren't just correct at their one
    # ticket-pinned point each.
    cases["zai_opus_low"] = {
        "parent": _PARENT_BY_PROVIDER["zai"], "tier": "opus", "effort": "low", "candidates": _ZAI_CANDIDATES,
    }
    cases["zai_sonnet_max"] = {
        "parent": _PARENT_BY_PROVIDER["zai"], "tier": "sonnet", "effort": "max", "candidates": _ZAI_CANDIDATES,
    }

    # One case per FallbackReason.
    cases["fallback_provider_unsupported"] = {
        "parent": {"provider": "google", "id": "gemini-x", "thinking": "medium"},
        "tier": "opus", "effort": "high", "candidates": [],
    }
    cases["fallback_tier_unknown"] = {
        "parent": _PARENT_BY_PROVIDER["anthropic"], "tier": "unknown-tier", "effort": "high",
        "candidates": _ANTHROPIC_CANDIDATES,
    }
    cases["fallback_effort_unknown"] = {
        "parent": _PARENT_BY_PROVIDER["anthropic"], "tier": "opus", "effort": "unknown-effort",
        "candidates": _ANTHROPIC_CANDIDATES,
    }
    cases["fallback_model_unavailable"] = {
        "parent": _PARENT_BY_PROVIDER["anthropic"], "tier": "opus", "effort": "high",
        "candidates": [c for c in _ANTHROPIC_CANDIDATES if c["id"] != "claude-opus-5"],
    }

    return _run_node(
        _MODEL_POLICY_DRIVER, [str(MODEL_POLICY_TS), json.dumps({"cases": cases})], tmp_path_factory,
        label="pi-model-policy-driver",
    )


@requires_node
def test_is_known_model_tier_and_effort(tmp_path_factory):
    result = _model_policy_result(tmp_path_factory)
    assert result["knownTiers"] == {"haiku": True, "sonnet": True, "opus": True, "other": False, "undef": False}
    assert result["knownEfforts"] == {
        "low": True, "medium": True, "high": True, "xhigh": True, "max": True, "other": False, "undef": False,
    }


@requires_node
@pytest.mark.parametrize(
    "provider,tier",
    [(p, t) for p, tiers in _EXPECTED_DEFAULT_CELL.items() for t in tiers],
)
def test_resolve_dispatch_default_cell(tmp_path_factory, provider, tier):
    """Every (provider, tier) cell at its tier's default effort resolves to the ticket's 3x3
    matrix — exact model id, exact effective thinking level, policySource "model-policy", no
    fallbackReason."""
    result = _model_policy_result(tmp_path_factory)
    expected_model, expected_thinking = _EXPECTED_DEFAULT_CELL[provider][tier]
    cell = result[f"default_{provider}_{tier}"]
    assert cell["model"] == {"provider": provider, "id": expected_model}
    assert cell["thinking"] == expected_thinking
    assert cell["tier"] == tier
    assert cell["portableEffort"] == _DEFAULT_TIER_EFFORT[tier]
    assert cell["policySource"] == "model-policy"
    assert cell.get("fallbackReason") is None


@requires_node
def test_resolve_dispatch_zai_thinking_table_beyond_the_default_cell(tmp_path_factory):
    """Z.AI's shifted tables must hold at more than their one ticket-pinned default point —
    opus shifts every effort up toward max, sonnet shifts every effort down toward low."""
    result = _model_policy_result(tmp_path_factory)
    assert result["zai_opus_low"]["thinking"] == "high"
    assert result["zai_sonnet_max"]["thinking"] == "xhigh"


@requires_node
def test_resolve_dispatch_exact_id_ignores_lookalike_candidates(tmp_path_factory):
    """The anthropic candidate pool carries dated/versioned siblings of the flagship ids
    (claude-opus-4-5..4-8 alongside claude-opus-5, etc.) — exact-id equality must resolve to
    precisely the policy's own id, never a lookalike, regardless of how many siblings share the
    pool or what order they appear in."""
    result = _model_policy_result(tmp_path_factory)
    assert result["default_anthropic_opus"]["model"]["id"] == "claude-opus-5"
    assert result["default_anthropic_sonnet"]["model"]["id"] == "claude-sonnet-5"
    assert result["default_anthropic_haiku"]["model"]["id"] == "claude-haiku-4-5"


@requires_node
@pytest.mark.parametrize(
    "label,reason",
    [
        ("fallback_provider_unsupported", "provider-unsupported"),
        ("fallback_tier_unknown", "tier-unknown"),
        ("fallback_effort_unknown", "effort-unknown"),
        ("fallback_model_unavailable", "model-unavailable"),
    ],
)
def test_resolve_dispatch_fallback_reasons(tmp_path_factory, label, reason):
    """Every FallbackReason returns the parent's own model/thinking unchanged, with
    policySource "parent-fallback" and the structured reason set — never a throw, never a
    partially-resolved id."""
    result = _model_policy_result(tmp_path_factory)
    cell = result[label]
    parent = cell["model"]
    case_parent = {
        "fallback_provider_unsupported": {"provider": "google", "id": "gemini-x"},
        "fallback_tier_unknown": {"provider": "anthropic", "id": "claude-sonnet-5"},
        "fallback_effort_unknown": {"provider": "anthropic", "id": "claude-sonnet-5"},
        "fallback_model_unavailable": {"provider": "anthropic", "id": "claude-sonnet-5"},
    }[label]
    assert parent == case_parent
    assert cell["thinking"] == "medium", "the parent's own ctx.thinkingLevel must survive unchanged"
    assert cell["policySource"] == "parent-fallback"
    assert cell["fallbackReason"] == reason

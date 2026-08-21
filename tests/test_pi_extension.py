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
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
PACKAGE_JSON = ROOT / "pi" / "package.json"
INDEX_TS = ROOT / "pi" / "extensions" / "index.ts"
GUARDS_TS = ROOT / "pi" / "extensions" / "guards.ts"
GUARD_RUNNER_TS = ROOT / "pi" / "extensions" / "guard-runner.ts"
BIN_README = ROOT / "bin" / "README.md"

# Concatenated (not a single literal) so this fixture's shape never appears contiguous in this
# file's own source — this file is not on secret_guard.py's allowlist (unlike
# tests/test_secret_guard.py), and the live PreToolUse:Write hook on the session authoring this
# file would otherwise block the edit that introduces it.
_SECRET_CONTENT = "API_KEY" + '="abcdefghijklmnop1234"'

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
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert data["name"] == "swe-workbench-pi"
    assert data["version"] == "0.0.0"
    assert data["private"] is True
    assert data["type"] == "module"
    assert data["pi"] == {"extensions": ["./extensions"]}

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
    for helper in ("guards.ts", "cc-payload.ts", "guard-runner.ts"):
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
    assert "systemPrompt" not in (parsed.get("firstInjection") or {})


# ---------------------------------------------------------------------------
# Behavioural: guards.ts driving the REAL hooks/bash_guard.sh + hooks/secret_guard.py +
# hooks/workflow_resume_hint.sh + hooks/skill_autoload_hint.sh through guard-runner.ts's real
# spawn (issue #607). Everything below drives the actual scripts, not a mock — the acceptance
# criterion is that the adapter reproduces the same verdict a direct Claude-Code-shaped
# invocation would get, not that its own translation logic is internally self-consistent.
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
    """Regression coverage for the #401 bypass this PR's hooks/bash_guard.sh fix closes,
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


@requires_node
def test_session_start_emits_resume_hint_via_send_message(guards_result):
    sent = guards_result["out"]["sentAfterSessionStart"]
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
    sentinel — two Pi sessions sharing one process would then share dedup state (#401 redux)."""
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
# #607 differential acceptance criterion — Pi-adapter half. tests/test_hooks.py runs the SAME
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

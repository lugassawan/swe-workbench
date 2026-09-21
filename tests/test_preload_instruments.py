"""Tests for the preload instruments: scripts/preload-probe.mjs, scripts/preload-telemetry.py,
and hooks/skill_usage_flush.sh's citation-harvest block.

Every live dispatch path (the ones that actually spawn `pi` and read real provider-billed usage)
is explicitly out of scope here: those require `pi auth` configured for a provider and cost real
money, so they are exercised by a human outside this test suite. What is covered here is every
surface reachable without a dispatch — argv construction, `--dry-run`, the pure parsers, the
harvest hook, and the reporters over hand-written JSONL fixtures.

Node-version gating mirrors tests/test_pi_extension.py's `_node_major_version` / `_NODE_TOO_OLD` /
`requires_node` pattern (duplicated here rather than imported — this repo already duplicates this
small helper across more than one test file).
"""

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "scripts" / "preload-probe.mjs"
PROBE_LIB = ROOT / "scripts" / "preload-probe-lib.mjs"
FLUSH_SH = ROOT / "hooks" / "skill_usage_flush.sh"
TELEMETRY = ROOT / "scripts" / "preload-telemetry.py"
ABLATION_CORPUS = ROOT / "tests" / "fixtures" / "ablation_corpus"


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

requires_node = pytest.mark.skipif(
    _NODE_TOO_OLD,
    reason="preload-probe.mjs behavioural tests require Node >= 22 (--experimental-strip-types)",
)


def _run_probe(args, env=None, **kwargs):
    node = shutil.which("node")
    assert node is not None
    return subprocess.run(
        [node, "--experimental-strip-types", str(PROBE), *args],
        capture_output=True,
        text=True,
        env=env if env is not None else _CLEAN_ENV,
        timeout=30,
        **kwargs,
    )


def _call_lib_function(fn_name, *fn_args):
    """Invokes one exported pure function from scripts/preload-probe-lib.mjs directly and
    returns its JSON-decoded return value, via a tiny `node -e` snippet that imports the module
    and calls it. No `pi` dispatch, no filesystem I/O, no CLI parsing — preload-probe-lib.mjs has
    no side effects at import time (unlike preload-probe.mjs itself), so this is a plain function
    call at the JS level — the pipe-delimited parser is independently testable this way without a
    process spawn beyond invoking node itself."""
    node = shutil.which("node")
    assert node is not None
    snippet = (
        "import(process.argv[1]).then((m) => {"
        f"const result = m.{fn_name}(...JSON.parse(process.argv[2]));"
        "process.stdout.write(JSON.stringify(result));"
        "});"
    )
    result = subprocess.run(
        [node, "--experimental-strip-types", "-e", snippet, str(PROBE_LIB), json.dumps(list(fn_args))],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=15,
    )
    assert result.returncode == 0, f"preload-probe-lib.mjs call to {fn_name} failed: {result.stderr}"
    return json.loads(result.stdout)


def _call_lib_function_outcome(fn_name, *fn_args):
    """Like _call_lib_function, but never asserts success: invokes one exported lib function
    and returns {"thrown": False, "value": ...} or {"thrown": True, "message": ...} — for
    testing functions whose CONTRACT is to throw (usageOrDispatchError's measurement gate)."""
    node = shutil.which("node")
    assert node is not None
    snippet = (
        "import(process.argv[1]).then((m) => {"
        f"const result = m.{fn_name}(...JSON.parse(process.argv[2]));"
        "process.stdout.write(JSON.stringify({thrown: false, value: result}));"
        "}).catch((e) => {"
        "process.stdout.write(JSON.stringify({thrown: true, message: String(e.message)}));"
        "});"
    )
    result = subprocess.run(
        [node, "--experimental-strip-types", "-e", snippet, str(PROBE_LIB), json.dumps(list(fn_args))],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=15,
    )
    assert result.returncode == 0, f"lib call to {fn_name} failed: {result.stderr}"
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def real_agent_id():
    """A real agents/*.md id, asserted to exist rather than assumed — an agent can be renamed or
    removed, and these tests must fail loudly on that rather than silently probing a ghost."""
    agents_dir = ROOT / "agents"
    names = sorted(p.stem for p in agents_dir.glob("*.md"))
    assert names, "expected at least one agents/*.md file"
    assert "reviewer" in names, "expected 'reviewer' agent to exist (used as the test fixture id)"
    return "reviewer"


@requires_node
def test_cache_dry_run_prints_expected_argv_shape(real_agent_id):
    result = _run_probe(["cache", "--agent", real_agent_id, "--dry-run"])
    assert result.returncode == 0, f"probe failed: {result.stderr}"

    argv = json.loads(result.stdout)
    assert isinstance(argv, list)
    for expected in ("-p", "--append-system-prompt", "--no-session", "--mode", "json"):
        assert expected in argv, f"expected {expected!r} in dry-run argv: {argv}"

    # Simplifications versus subagent.ts must actually be taken, not silently expanded.
    assert "--tools" not in argv
    assert "--model" not in argv


@requires_node
def test_cache_dry_run_unknown_agent_fails_with_not_found_message():
    result = _run_probe(["cache", "--agent", "totally-not-a-real-agent", "--dry-run"])
    assert result.returncode != 0
    assert "totally-not-a-real-agent" in result.stderr
    assert "not" in result.stderr.lower() or "unknown" in result.stderr.lower()


@requires_node
def test_cache_without_agent_flag_fails_with_usage_error():
    result = _run_probe(["cache", "--dry-run"])
    assert result.returncode != 0
    assert "--agent" in result.stderr


@requires_node
def test_unknown_subcommand_fails():
    """A token that is not a real subcommand must hit the unknown-subcommand path specifically,
    and say so. The token has to be one that will never become a real subcommand — naming a
    planned-but-unimplemented one would turn this into a duplicate of that subcommand's own
    argument-validation test the moment it lands, silently losing coverage of this path."""
    result = _run_probe(["bogus"])
    assert result.returncode != 0
    assert 'unknown subcommand "bogus"' in result.stderr
    # The error must name every implemented subcommand so the caller can pick a real one.
    assert "cache" in result.stderr
    assert "ablate" in result.stderr


@requires_node
def test_no_subcommand_at_all_fails_with_usage():
    result = _run_probe([])
    assert result.returncode != 0
    assert "unknown subcommand" in result.stderr
    assert "usage:" in result.stderr


def test_every_pi_spawn_is_bounded_by_a_timeout_and_a_maxbuffer():
    """Every `pi` dispatch this probe makes must carry both bounds.

    Neither can be exercised without a real (paid) dispatch, so this is a source-shape ratchet
    over the single spawn site instead. Both bounds guard money already spent: without a
    `timeout`, a hung provider call hangs the probe indefinitely; without a `maxBuffer`, Node's
    1 MiB default lets an ablate run's NDJSON event stream overflow, killing the child and
    surfacing an error only after the provider call has already been billed.
    """
    text = PROBE.read_text()

    spawn_sites = re.findall(r"spawnSync\(\s*\"pi\"", text)
    assert len(spawn_sites) == 1, (
        f"expected exactly one spawnSync(\"pi\", ...) site, found {len(spawn_sites)} — every "
        "new site needs the same timeout/maxBuffer bounds"
    )

    call = re.search(r"spawnSync\(\s*\"pi\",\s*args,\s*\{(.*?)\}\s*\)", text, re.DOTALL)
    assert call, "could not locate the spawnSync(\"pi\", ...) options object"
    options = call.group(1)
    assert "timeout:" in options, "spawnSync(\"pi\", ...) must pass a timeout"
    assert "maxBuffer:" in options, "spawnSync(\"pi\", ...) must pass a maxBuffer"

    # The bounds must be real values, not zero/undefined placeholders.
    assert re.search(r"const DISPATCH_TIMEOUT_MS = 15 \* 60 \* 1000;", text), (
        "DISPATCH_TIMEOUT_MS must stay pinned to subagent.ts's own 15-minute TASK_TIMEOUT_MS"
    )
    assert re.search(r"const DISPATCH_MAX_BUFFER_BYTES = 50 \* 1024 \* 1024;", text), (
        "DISPATCH_MAX_BUFFER_BYTES must stay well clear of Node's 1 MiB spawnSync default"
    )


@requires_node
def test_timeout_diagnostic_identifies_arm_without_echoing_partial_content():
    """A timed-out paid arm must identify where it stalled without leaking captured reasoning.

    Regression target: replacing the structured formatter with the former bare
    ``spawnSync pi ETIMEDOUT`` message loses the diff/arm and all progress metadata; including
    raw stdout/stderr instead leaks model reasoning and possibly provider diagnostics.
    """
    sensitive = "SENSITIVE MODEL REASONING"
    stdout = "\n".join(
        [
            json.dumps({"type": "message_start", "private": sensitive}),
            "not-json",
            json.dumps({"type": "message_update", "delta": sensitive}),
        ]
    )
    outcome = _call_lib_function(
        "formatPiSpawnError",
        {
            "errorCode": "ETIMEDOUT",
            "errorMessage": "spawnSync pi ETIMEDOUT",
            "label": "01.diff omit(principle-clean-architecture)",
            "elapsedMs": 900123,
            "timeoutMs": 900000,
            "stdout": stdout,
            "stderr": sensitive,
        },
    )

    assert "pi dispatch timed out" in outcome
    assert 'label="01.diff omit(principle-clean-architecture)"' in outcome
    assert "elapsed=900123ms" in outcome
    assert "limit=900000ms" in outcome
    assert re.search(r"stdoutBytes=[1-9][0-9]*", outcome)
    assert re.search(r"stderrBytes=[1-9][0-9]*", outcome)
    assert "lastEventType=message_update" in outcome
    assert "code=ETIMEDOUT" in outcome
    assert sensitive not in outcome


@requires_node
def test_timeout_diagnostic_rejects_untrusted_event_type_content():
    sensitive = "sensitive_model_reasoning"
    outcome = _call_lib_function(
        "formatPiSpawnError",
        {
            "errorCode": "ETIMEDOUT",
            "errorMessage": "spawnSync pi ETIMEDOUT",
            "label": "01.diff omit(principle-clean-architecture)",
            "elapsedMs": 900000,
            "timeoutMs": 900000,
            "stdout": json.dumps({"type": sensitive}),
            "stderr": "",
        },
    )

    assert "lastEventType=unknown" in outcome
    assert sensitive not in outcome


@requires_node
@pytest.mark.parametrize(
    "event_type",
    [
        "session",
        "agent_start",
        "agent_end",
        "agent_settled",
        "turn_start",
        "turn_end",
        "message_start",
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
        "queue_update",
        "compaction_start",
        "compaction_end",
        "entry_appended",
        "session_info_changed",
        "thinking_level_changed",
        "auto_retry_start",
        "auto_retry_end",
        "summarization_retry_scheduled",
        "summarization_retry_attempt_start",
        "summarization_retry_finished",
        "bash_execution_update",
    ],
)
def test_timeout_diagnostic_recognizes_documented_pi_event_types(event_type: str):
    outcome = _call_lib_function(
        "formatPiSpawnError",
        {
            "errorCode": "ETIMEDOUT",
            "errorMessage": "spawnSync pi ETIMEDOUT",
            "label": "01.diff baseline",
            "elapsedMs": 900000,
            "timeoutMs": 900000,
            "stdout": json.dumps({"type": event_type}),
            "stderr": "",
        },
    )

    assert f"lastEventType={event_type}" in outcome


@requires_node
def test_timeout_diagnostic_uses_raw_captured_byte_counts():
    outcome = _call_lib_function(
        "formatPiSpawnError",
        {
            "errorCode": "ETIMEDOUT",
            "errorMessage": "spawnSync pi ETIMEDOUT",
            "label": "01.diff omit(principle-clean-architecture)",
            "elapsedMs": 900000,
            "timeoutMs": 900000,
            "stdout": "\ufffd",
            "stderr": "\ufffd",
            "stdoutBytes": 1,
            "stderrBytes": 2,
        },
    )

    assert "stdoutBytes=1" in outcome
    assert "stderrBytes=2" in outcome


_PRELOAD_CANARY_BEGIN = "<!-- BEGIN shared/agents/preload-canary-citation.md -->"
_PRELOAD_CANARY_END = "<!-- END shared/agents/preload-canary-citation.md -->"


def test_all_agents_carry_the_preload_canary_citation_block():
    """shared/agents/preload-canary-citation.md must be inlined into every agents/*.md file via
    the sentinel-block mechanism — the citation signal only exists for agents that carry the
    instruction. No Node/`pi` involvement needed here — this is a plain text-shape assertion over
    the static agent files, so it does not need `requires_node`."""
    agents_dir = ROOT / "agents"
    agent_files = sorted(agents_dir.glob("*.md"))
    assert len(agent_files) == 22, f"expected 22 agents/*.md files, found {len(agent_files)}"

    for path in agent_files:
        text = path.read_text()
        assert _PRELOAD_CANARY_BEGIN in text, f"{path.name} missing BEGIN sentinel"
        assert _PRELOAD_CANARY_END in text, f"{path.name} missing END sentinel"

        begin_idx = text.index(_PRELOAD_CANARY_BEGIN) + len(_PRELOAD_CANARY_BEGIN)
        end_idx = text.index(_PRELOAD_CANARY_END)
        assert begin_idx < end_idx, f"{path.name} has END before BEGIN"

        inner = text[begin_idx:end_idx].strip()
        assert inner, f"{path.name} has an empty preload-canary-citation block (sync not run?)"


def test_ablation_corpus_holds_at_least_ten_real_diffs():
    """Issue #689's C3 premise: the corpus must hold at least 10 real diffs from the repo's
    history — the 2 hand-authored synthetic fixtures were explicitly judged insufficient to
    trust an ablation sweep."""
    files = sorted(ABLATION_CORPUS.glob("*.diff"))
    assert len(files) >= 10, f"expected >= 10 corpus diffs, found {len(files)}"


def test_recorded_measurements_document_cache_read_fraction_and_c3_decision():
    """Acceptance criteria (a)+(b) of issue #689: the Recorded measurements section must carry
    at least one dated cache-read fraction line, and a written C3 proceed/drop decision. The
    figures themselves are human-run instrument output recorded verbatim — this ratchet only
    pins their presence and shape, never their values."""
    text = (ROOT / "docs" / "skill-preload.md").read_text()
    assert "## Recorded measurements" in text, "docs/skill-preload.md lost its Recorded measurements section"

    section = text.split("\n## Recorded measurements\n", 1)[1]
    assert re.search(r"cache-read fraction 0\.\d+.*\(\d{4}-\d{2}-\d{2}\)", section), (
        "expected at least one dated cache-read fraction line under ## Recorded measurements"
    )
    assert "C3 decision:" in section, "expected a written C3 proceed/drop decision line"


SWEEP_MANDATED_AGENTS = {"senior-engineer", "architect", "reviewer"}
TRIAGE_REQUIRED_AGENTS = sorted(
    p.stem for p in (ROOT / "agents").glob("*.md") if p.stem not in SWEEP_MANDATED_AGENTS
)


@pytest.mark.parametrize("agent", TRIAGE_REQUIRED_AGENTS)
def test_c3_sweep_triage_covers_every_non_mandated_agent(agent):
    """Every agent beyond the three heaviest (which are swept by ticket mandate) must appear
    in the C3 sweep triage table. The agent list is discovered live from agents/*.md so the
    table stays complete as agents are added."""
    text = (ROOT / "docs" / "skill-preload.md").read_text()
    assert "### C3 sweep triage" in text, "docs/skill-preload.md lost its C3 sweep triage section"

    # Newline-anchored: the runbook's backticked `## Recorded measurements` mention must not
    # truncate the slice before the section's real tail.
    section = text.split("### C3 sweep triage", 1)[1].split("\n## Recorded measurements\n", 1)[0]
    assert f"| {agent} |" in section, (
        f"agent '{agent}' missing from the C3 sweep triage table"
    )


def test_c3_sweep_triage_section_carries_the_human_runbook():
    """The triage section must include the human sweep runbook — the paste-able ablate loop with
    its --omit flag — so the ablation sweeps don't require reconstructing the invocation from
    the instrument's usage string. Pins presence and shape only, never the figures."""
    text = (ROOT / "docs" / "skill-preload.md").read_text()
    assert "### C3 sweep triage" in text, "docs/skill-preload.md lost its C3 sweep triage section"

    section = text.split("### C3 sweep triage", 1)[1].split("\n## Recorded measurements\n", 1)[0]
    assert "preload-probe.mjs ablate" in section, "triage section must carry the sweep runbook command"
    assert "--omit" in section, "triage section must show the --omit flag the sweep loop uses"


def test_citation_instruction_does_not_claim_the_sections_are_above_it():
    """composeSystemPrompt (pi/extensions/agent-spec.ts) appends each `## Preloaded skill:`
    section AFTER the agent body, and this fragment is inlined at the very end of that body — so
    the sections it points at are below it, never above. A positional word pointing the wrong way
    would send the agent looking in the wrong direction for the one thing the whole citation
    signal depends on it finding."""
    text = (ROOT / "shared" / "agents" / "preload-canary-citation.md").read_text()
    assert "sections above" not in text, (
        "the preloaded-skill sections are composed BELOW this instruction, not above it"
    )
    assert "## Preloaded skill: <id>" in text


# ---------------------------------------------------------------------------
# hooks/skill_usage_flush.sh reads back SWB-CANARIES-APPLIED and appends
# canary-citations.jsonl.
#
# Fixture/subprocess pattern mirrors tests/test_skill_usage_telemetry.py
# (same hook, same env wiring), duplicated here rather than imported since
# that file's fixtures are function-scoped and private to its module.
# ---------------------------------------------------------------------------


@pytest.fixture()
def canary_plugin_root(tmp_path: Path) -> Path:
    """Minimal plugin dir with an agents/reviewer.md (no opt-out)."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "reviewer.md").write_text(
        "---\nname: reviewer\nmodel: sonnet\n---\nReviewer body.\n"
    )
    return tmp_path


@pytest.fixture()
def canary_cache_dir(tmp_path: Path) -> Path:
    """Isolated cache directory; CLAUDE_PROJECT_DIR points here."""
    d = tmp_path / "project"
    d.mkdir()
    return d


def _canary_env(plugin_root: Path, cache_dir: Path) -> dict:
    env = dict(_CLEAN_ENV)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    env["CLAUDE_PROJECT_DIR"] = str(cache_dir)
    return env


def _run_flush_for_canary(
    stdin_json: dict, plugin_root: Path, cache_dir: Path
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(FLUSH_SH)],
        input=json.dumps(stdin_json),
        capture_output=True,
        text=True,
        env=_canary_env(plugin_root, cache_dir),
    )


def _citations_file(cache_dir: Path) -> Path:
    return cache_dir / ".claude" / "cache" / "skill-usage" / "canary-citations.jsonl"


def _read_citation_records(cache_dir: Path) -> list[dict]:
    path = _citations_file(cache_dir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestCanaryCitationHarvest:
    def test_citation_marker_appends_jsonl_record(self, canary_plugin_root, canary_cache_dir):
        """A last_assistant_message ending in the marker line appends a JSONL
        record with the parsed, namespaced skill ids."""
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-001",
                "agent_type": "reviewer",
                "last_assistant_message": (
                    "Some analysis here.\n"
                    "SWB-CANARIES-APPLIED: swe-workbench:principle-ddd, "
                    "swe-workbench:principle-tdd"
                ),
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["agent_type"] == "reviewer"
        assert records[0]["agent_id"] == "cite-001"
        assert records[0]["cited_skills"] == [
            "swe-workbench:principle-ddd",
            "swe-workbench:principle-tdd",
        ]

    def test_citation_marker_none_appends_empty_list(self, canary_plugin_root, canary_cache_dir):
        """SWB-CANARIES-APPLIED: NONE → a record with an empty cited_skills array."""
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-002",
                "agent_type": "reviewer",
                "last_assistant_message": "Nothing applied.\nSWB-CANARIES-APPLIED: NONE",
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["cited_skills"] == []

    def test_missing_last_assistant_message_is_silent_noop(
        self, canary_plugin_root, canary_cache_dir
    ):
        """No last_assistant_message field at all → exits 0, emits the same {}
        the existing skill-usage flush emits for an agent with no buffer, and
        never creates canary-citations.jsonl."""
        result = _run_flush_for_canary(
            {"agent_id": "cite-003", "agent_type": "reviewer"},
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {}
        assert not _citations_file(canary_cache_dir).exists()

    def test_message_without_marker_line_records_null_cited_skills(
        self, canary_plugin_root, canary_cache_dir
    ):
        """last_assistant_message present but no SWB-CANARIES-APPLIED line → a record is still
        appended, with cited_skills: null.

        The dispatch happened and was observed; the agent just dropped the trailing instruction.
        Recording it is what lets the reporter compute citation rates against every sampled
        dispatch — the denominator the demotion decision rule actually names — instead of only
        against the dispatches that happened to comply.
        """
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-004",
                "agent_type": "reviewer",
                "last_assistant_message": "Just an ordinary response with no marker.",
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["agent_type"] == "reviewer"
        assert records[0]["agent_id"] == "cite-004"
        assert records[0]["cited_skills"] is None

    def test_null_none_and_populated_are_three_distinct_record_shapes(
        self, canary_plugin_root, canary_cache_dir
    ):
        """null (no marker emitted), [] (marker emitted saying NONE), and a populated list are
        three different facts and must never collapse into each other."""
        for agent_id, message in (
            ("shape-null", "No marker at all here."),
            ("shape-none", "Done.\nSWB-CANARIES-APPLIED: NONE"),
            ("shape-cited", "Done.\nSWB-CANARIES-APPLIED: swe-workbench:principle-ddd"),
        ):
            result = _run_flush_for_canary(
                {
                    "agent_id": agent_id,
                    "agent_type": "reviewer",
                    "last_assistant_message": message,
                },
                canary_plugin_root,
                canary_cache_dir,
            )
            assert result.returncode == 0

        records = _read_citation_records(canary_cache_dir)
        by_id = {rec["agent_id"]: rec["cited_skills"] for rec in records}
        assert by_id == {
            "shape-null": None,
            "shape-none": [],
            "shape-cited": ["swe-workbench:principle-ddd"],
        }

    def test_backtick_wrapped_marker_line_is_still_harvested(
        self, canary_plugin_root, canary_cache_dir
    ):
        """The instruction fragment shows the marker as inline code, so a model can plausibly
        emit its own closing line backtick-wrapped. A regex anchored strictly at
        `^SWB-CANARIES-APPLIED:` would silently drop that citation and score it as a
        non-compliant dispatch."""
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-007",
                "agent_type": "reviewer",
                "last_assistant_message": (
                    "Analysis.\n"
                    "`SWB-CANARIES-APPLIED: swe-workbench:principle-ddd, "
                    "swe-workbench:principle-tdd`"
                ),
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["cited_skills"] == [
            "swe-workbench:principle-ddd",
            "swe-workbench:principle-tdd",
        ]

    def test_backtick_wrapped_none_marker_is_an_explicit_none_not_a_dropped_marker(
        self, canary_plugin_root, canary_cache_dir
    ):
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-008",
                "agent_type": "reviewer",
                "last_assistant_message": "Nothing applied.\n`SWB-CANARIES-APPLIED: NONE`",
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["cited_skills"] == []

    def test_stray_commas_do_not_leak_empty_string_entries(
        self, canary_plugin_root, canary_cache_dir
    ):
        """A malformed marker with a stray double-comma and trailing comma +
        whitespace must not produce empty-string entries in cited_skills."""
        result = _run_flush_for_canary(
            {
                "agent_id": "cite-006",
                "agent_type": "reviewer",
                "last_assistant_message": (
                    "SWB-CANARIES-APPLIED: swe-workbench:principle-ddd,,"
                    "swe-workbench:principle-tdd,  "
                ),
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["cited_skills"] == [
            "swe-workbench:principle-ddd",
            "swe-workbench:principle-tdd",
        ]
        assert "" not in records[0]["cited_skills"]

    def test_citation_harvest_does_not_disturb_existing_buffer_flush(
        self, canary_plugin_root, canary_cache_dir
    ):
        """Regression: when both a citation marker AND a skill-usage buffer
        file are present, the pre-existing buffer-flush systemMessage
        behaviour is unaffected by the new citation-harvest logic."""
        skill_cache = canary_cache_dir / ".claude" / "cache" / "skill-usage"
        skill_cache.mkdir(parents=True)
        today = __import__("datetime").date.today().strftime("%Y%m%d")
        buf = skill_cache / f"{today}-cite-005.txt"
        buf.write_text("swe-workbench:principle-clean-code\n")

        result = _run_flush_for_canary(
            {
                "agent_id": "cite-005",
                "agent_type": "reviewer",
                "last_assistant_message": (
                    "Body.\nSWB-CANARIES-APPLIED: swe-workbench:principle-clean-code"
                ),
            },
            canary_plugin_root,
            canary_cache_dir,
        )
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert "systemMessage" in out
        assert "Skills used by reviewer" in out["systemMessage"]
        assert "swe-workbench:principle-clean-code" in out["systemMessage"]
        assert not buf.exists(), "buffer should still be deleted after flush"

        records = _read_citation_records(canary_cache_dir)
        assert len(records) == 1
        assert records[0]["cited_skills"] == ["swe-workbench:principle-clean-code"]


# ---------------------------------------------------------------------------
# preload-probe.mjs `cache --dry-run` must stay side-effect free despite the
# live path's cache-runs.jsonl append, plus scripts/preload-telemetry.py's
# canary and cache reporters.
# ---------------------------------------------------------------------------


@requires_node
def test_cache_dry_run_writes_no_cache_runs_file(tmp_path: Path, real_agent_id):
    """--dry-run must exit before any file I/O beyond argv construction. The live-append path
    itself cannot be exercised without a real `pi` dispatch, so this asserts the negative: the
    append never fires on the path that does not dispatch."""
    env = {**_CLEAN_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    result = _run_probe(["cache", "--agent", real_agent_id, "--dry-run"], env=env)
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert not (tmp_path / ".claude" / "cache" / "dispatch-probes").exists()
    assert not (tmp_path / ".claude" / "cache" / "dispatch-probes" / "cache-runs.jsonl").exists()


def _run_telemetry(args, project_dir=None):
    env = dict(_CLEAN_ENV)
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(TELEMETRY), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


class TestPreloadTelemetryCanary:
    def _citations_file(self, project_dir: Path) -> Path:
        path = project_dir / ".claude" / "cache" / "skill-usage" / "canary-citations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def test_citation_rate_and_zero_citation_row(self, tmp_path: Path):
        """Hand-constructed scenario against the real 'reviewer' agent's real preloaded skills
        (agents/*.md discovery is fixed to this repo's own tree, not redirectable — only the
        citations JSONL data directory is redirected via CLAUDE_PROJECT_DIR).

        reviewer preloads (among others) swe-workbench:principle-code-review and
        swe-workbench:principle-clean-code. 4 synthetic dispatches: principle-code-review cited
        in 2 of them (hand calc: 2/4 = 50.0%), principle-clean-code cited in 0 of them (must
        still get its own 0/4 row, not be omitted).
        """
        lines = [
            {
                "agent_type": "reviewer",
                "cited_skills": [
                    "swe-workbench:principle-code-review",
                    "swe-workbench:principle-solid",
                ],
                "agent_id": "r1",
            },
            {
                "agent_type": "reviewer",
                "cited_skills": ["swe-workbench:principle-code-review"],
                "agent_id": "r2",
            },
            {"agent_type": "reviewer", "cited_skills": [], "agent_id": "r3"},
            {
                "agent_type": "reviewer",
                "cited_skills": ["swe-workbench:principle-solid"],
                "agent_id": "r4",
            },
        ]
        path = self._citations_file(tmp_path)
        path.write_text("\n".join(json.dumps(rec) for rec in lines) + "\n")

        result = _run_telemetry(["canary", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        out = result.stdout

        assert "reviewer" in out and "4 dispatch(es) recorded" in out
        assert "swe-workbench:principle-code-review: 2/4 (50.0%)" in out
        assert "swe-workbench:principle-clean-code: 0/4 (0.0%)" in out
        # Every record here carries a list, so marker compliance is a clean 4/4.
        assert "marker compliance: 4/4 (100.0%)" in out
        # The caveat must be present unconditionally, not just for low rates.
        assert "CAVEAT:" in out
        assert "SubagentStop" in out

    def test_rates_use_all_dispatches_as_denominator_not_just_marker_emitting_ones(
        self, tmp_path: Path
    ):
        """The demotion decision rule's denominator is sampled dispatches, not compliant ones.

        Hand calc over 5 records: 2 emitted no marker at all (cited_skills: null), 1 emitted an
        explicit NONE ([]), 2 cited principle-code-review. Citation rate must be 2/5 = 40.0%
        (NOT 2/3 = 66.7%, which is what counting only marker-emitting records would report), and
        marker compliance must be 3/5 = 60.0%.
        """
        lines = [
            {"agent_type": "reviewer", "cited_skills": None, "agent_id": "n1"},
            {"agent_type": "reviewer", "cited_skills": None, "agent_id": "n2"},
            {"agent_type": "reviewer", "cited_skills": [], "agent_id": "e1"},
            {
                "agent_type": "reviewer",
                "cited_skills": ["swe-workbench:principle-code-review"],
                "agent_id": "c1",
            },
            {
                "agent_type": "reviewer",
                "cited_skills": ["swe-workbench:principle-code-review"],
                "agent_id": "c2",
            },
        ]
        path = self._citations_file(tmp_path)
        path.write_text("\n".join(json.dumps(rec) for rec in lines) + "\n")

        result = _run_telemetry(["canary", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        out = result.stdout

        assert "5 dispatch(es) recorded" in out
        assert "marker compliance: 3/5 (60.0%)" in out
        assert "swe-workbench:principle-code-review: 2/5 (40.0%)" in out
        # The marker-emitting-only denominator must not appear anywhere.
        assert "2/3" not in out

    def test_zero_data_reports_marker_compliance_as_no_data_not_as_zero_percent(
        self, tmp_path: Path
    ):
        """0 of 0 dispatches emitting a marker is "no data yet", not "0% compliance" — the same
        distinction the per-skill 0/0 rows already draw."""
        result = _run_telemetry(["canary", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "marker compliance: 0/0 (no dispatch data yet)" in result.stdout
        assert "0.0%)" not in result.stdout

    def test_missing_citations_file_exits_zero_with_message(self, tmp_path: Path):
        """A known agent (real agents/*.md id) with zero recorded dispatches is an expected,
        non-fatal data-coverage gap — exit 0, informational message. This must stay distinct
        from an --agent value that isn't in the discovered preload universe at all (covered by
        test_unknown_agent_exits_nonzero_with_error below)."""
        result = _run_telemetry(["canary", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "no citation data collected yet" in result.stdout
        # A skill with no data yet still gets its own distinct 0/0 row, not omitted.
        assert "swe-workbench:principle-code-review: 0/0" in result.stdout
        assert "CAVEAT:" in result.stdout

    def test_unknown_agent_exits_nonzero_with_error(self, tmp_path: Path):
        """An --agent id that is NOT in the discovered preload universe at all (no `skills:`
        frontmatter entries in any agents/*.md) is a usage error — typo'd or nonexistent agent —
        distinct from a known agent with 0 recorded dispatches (which exits 0, see above)."""
        result = _run_telemetry(
            ["canary", "--agent", "totally-not-a-real-agent"], project_dir=tmp_path
        )
        assert result.returncode != 0
        assert (
            "no such agent in the preload universe: totally-not-a-real-agent" in result.stderr
        )
        # Must not be reported as ordinary "0 dispatches" data-coverage output on stdout.
        assert "0 dispatches recorded" not in result.stdout

    def test_corrupted_line_is_skipped_not_fatal(self, tmp_path: Path):
        path = self._citations_file(tmp_path)
        good = {
            "agent_type": "reviewer",
            "cited_skills": ["swe-workbench:principle-code-review"],
            "agent_id": "r1",
        }
        path.write_text(json.dumps(good) + "\n" + "not valid json {\n")

        result = _run_telemetry(["canary", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "skipped 1 malformed line" in result.stdout
        # The rest of the file is still processed and reported.
        assert "swe-workbench:principle-code-review: 1/1 (100.0%)" in result.stdout


class TestPreloadTelemetryCache:
    def _cache_runs_file(self, project_dir: Path) -> Path:
        path = project_dir / ".claude" / "cache" / "dispatch-probes" / "cache-runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def test_pairing_and_cache_read_fraction_reporting(self, tmp_path: Path):
        run1 = {
            "agent": "reviewer",
            "run": 1,
            "usage": {
                "input": 1000,
                "output": 50,
                "cacheRead": 0,
                "cacheWrite": 900,
                "cost": {"input": 0.01, "output": 0.002, "cacheRead": 0.0, "cacheWrite": 0.015, "total": 0.027},
            },
            "cacheReadFraction": 0.0,
            "ts": "2026-01-01T00:00:00.000Z",
        }
        run2 = {
            "agent": "reviewer",
            "run": 2,
            "usage": {
                "input": 100,
                "output": 50,
                "cacheRead": 900,
                "cacheWrite": 0,
                "cost": {"input": 0.001, "output": 0.002, "cacheRead": 0.0009, "cacheWrite": 0.0, "total": 0.0039},
            },
            "cacheReadFraction": 0.9,
            "ts": "2026-01-01T00:00:05.000Z",
        }
        path = self._cache_runs_file(tmp_path)
        path.write_text(json.dumps(run1) + "\n" + json.dumps(run2) + "\n")

        result = _run_telemetry(["cache", "--agent", "reviewer"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        out = result.stdout

        assert "agent: reviewer" in out
        assert "cacheRead=0" in out
        assert "cacheRead=900" in out
        assert "cacheReadFraction=0.0" in out
        assert "cacheReadFraction=0.9" in out
        assert "cache: YES — run 2 showed cache-read activity (cacheRead > 0)" in out

    def test_missing_cache_runs_file_exits_zero_pointing_at_probe_command(self, tmp_path: Path):
        result = _run_telemetry(["cache"], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "no cache-probe run data collected yet" in result.stdout
        assert "preload-probe.mjs cache --agent" in result.stdout

    def test_known_agent_with_no_runs_exits_zero(self, tmp_path: Path, real_agent_id):
        """A real agents/*.md id with zero recorded probe runs is an expected data-coverage
        gap, not a usage error — exit 0 with an informational message."""
        result = _run_telemetry(["cache", "--agent", real_agent_id], project_dir=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "no cache-probe run data collected yet" in result.stdout

    def test_unknown_agent_exits_nonzero_with_error(self, tmp_path: Path):
        """An --agent id that is not a real agents/*.md id is a usage error — a typo or a
        nonexistent agent — and must be distinguishable from a real agent with no runs yet
        (above), which is the same distinction the canary subcommand draws."""
        result = _run_telemetry(
            ["cache", "--agent", "totally-not-a-real-agent"], project_dir=tmp_path
        )
        assert result.returncode != 0
        assert "no such agent: totally-not-a-real-agent" in result.stderr
        # Must not be reported as ordinary "no data yet" coverage output on stdout.
        assert "no cache-probe run data collected yet" not in result.stdout

    def test_unknown_agent_error_precedes_any_report_output(self, tmp_path: Path):
        """The usage error must not be buried under the report header."""
        result = _run_telemetry(
            ["cache", "--agent", "totally-not-a-real-agent"], project_dir=tmp_path
        )
        assert result.returncode != 0
        assert "== preload-telemetry cache report ==" not in result.stdout


def test_telemetry_no_subcommand_exits_nonzero_with_usage():
    result = _run_telemetry([])
    assert result.returncode != 0
    assert "canary" in result.stderr and "cache" in result.stderr


def test_telemetry_unknown_subcommand_exits_nonzero():
    result = _run_telemetry(["bogus"])
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


# ---------------------------------------------------------------------------
# preload-probe.mjs's `ablate` subcommand (run mode + report mode), plus the standalone pure
# helpers factored into preload-probe-lib.mjs. No test spawns real `pi` — same constraint the
# `cache` subcommand's own tests above follow.
# ---------------------------------------------------------------------------


class TestExtractFinalAssistantText:
    """Pins the retry-recovery contract dispatchArmMeasurement depends on: the LAST assistant
    message_end wins over an earlier errored empty one. If this regresses (first-wins, or
    empty-content ends mishandled), recovered retries would abort paid-for ablation sweeps."""

    RECOVERED_RETRY_STREAM = "\n".join(
        [
            '{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"error","errorMessage":"provider 5xx"}}',
            '{"type":"turn_end","message":{"role":"assistant","content":[],"stopReason":"error","errorMessage":"provider 5xx"},"toolResults":[]}',
            '{"type":"agent_end","messages":[],"willRetry":true}',
            '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"Medium | a.ts:1 | x | y | z"}],"stopReason":"stop"}}',
        ]
    )

    ERRORED_LAST_STREAM = (
        '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"ignored"}],"stopReason":"stop"}}\n'
        '{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"error","errorMessage":"provider 5xx"}}'
    )

    @requires_node
    def test_recovered_retry_returns_the_successful_turn_text(self):
        result = _call_lib_function("extractFinalAssistantText", self.RECOVERED_RETRY_STREAM)
        assert result == "Medium | a.ts:1 | x | y | z"

    @requires_node
    def test_errored_last_yields_empty_string_not_the_earlier_text(self):
        result = _call_lib_function("extractFinalAssistantText", self.ERRORED_LAST_STREAM)
        assert result == ""

    @requires_node
    def test_no_assistant_message_end_returns_none(self):
        stream = '{"type":"message_end","message":{"role":"user","content":[]}}'
        assert _call_lib_function("extractFinalAssistantText", stream) is None

    @requires_node
    def test_quota_exhaustion_shape_throws_through_the_usage_gate(self):
        """The quota-exhaustion stream shape (ERROR_STREAM) through the composed gate:
        no usage + provider error must throw naming the provider's message."""
        outcome = _call_lib_function_outcome(
            "usageOrDispatchError", TestExtractDispatchError.ERROR_STREAM, "run 1 (cold)"
        )
        assert outcome["thrown"] is True
        assert "Codex error: The usage limit has been reached" in outcome["message"]


class TestUsageOrDispatchError:
    """usageOrDispatchError — the cache probe's measurement gate, composed from the two
    extractors above. Its contract is to THROW on any unmeasurable dispatch, so these tests
    capture outcomes rather than assert exit 0."""

    VALID_STREAM = (
        '{"type":"message_update","usage":{"input":0,"cacheRead":0,"cacheWrite":0}}\n'
        '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"ack"}],'
        '"usage":{"input":13580,"output":5,"cacheRead":0,"cacheWrite":0,"cost":{"total":0.06805}},'
        '"stopReason":"stop"}}'
    )
    ZERO_WITH_ERROR_STREAM = (
        '{"type":"message_update","usage":{"input":0,"cacheRead":0,"cacheWrite":0}}\n'
        '{"type":"message_end","message":{"role":"assistant","content":[],'
        '"usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"cost":{"total":0}},'
        '"stopReason":"error","errorMessage":"Codex error: The usage limit has been reached"}}'
    )
    ZERO_NO_ERROR_STREAM = (
        '{"type":"message_end","message":{"role":"assistant","content":[],'
        '"usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"cost":{"total":0}},'
        '"stopReason":"stop"}}'
    )

    @requires_node
    def test_valid_usage_passes_through(self):
        outcome = _call_lib_function_outcome("usageOrDispatchError", self.VALID_STREAM, "run 1")
        assert outcome["thrown"] is False
        assert outcome["value"]["input"] == 13580

    @requires_node
    def test_zero_billed_with_provider_error_throws_both_facts(self):
        outcome = _call_lib_function_outcome(
            "usageOrDispatchError", self.ZERO_WITH_ERROR_STREAM, "run 1 (cold)"
        )
        assert outcome["thrown"] is True
        assert "run 1 (cold)" in outcome["message"]
        assert "zero billed tokens" in outcome["message"]
        assert "Codex error: The usage limit has been reached" in outcome["message"]

    @requires_node
    def test_zero_billed_without_error_throws_fallback(self):
        outcome = _call_lib_function_outcome(
            "usageOrDispatchError", self.ZERO_NO_ERROR_STREAM, "run 2"
        )
        assert outcome["thrown"] is True
        assert "zero billed tokens" in outcome["message"]
        assert "not a measurable dispatch" in outcome["message"]

    @requires_node
    def test_no_usage_at_all_throws_with_label(self):
        outcome = _call_lib_function_outcome(
            "usageOrDispatchError", '{"type":"agent_start"}', "run 1"
        )
        assert outcome["thrown"] is True
        assert "run 1" in outcome["message"]
        assert "no usage found" in outcome["message"]


class TestExtractDispatchError:
    """extractDispatchError — the guard that keeps a failed provider dispatch from being read
    as a measurement. A failed turn emits message-level events carrying stopReason "error" +
    errorMessage while `pi --mode json` still exits 0 — so the only reliable failure signal is
    in the event stream, not the exit code."""

    ERROR_STREAM = "\n".join(
        [
            '{"type":"session","version":3,"id":"x","timestamp":"2026-08-31T04:55:32.714Z","cwd":"/repo"}',
            '{"type":"agent_start"}',
            '{"type":"turn_start"}',
            '{"type":"message_start","message":{"role":"user","content":[{"type":"text","text":"ack"}],"timestamp":1}}',
            '{"type":"message_end","message":{"role":"user","content":[{"type":"text","text":"ack"}],"timestamp":1}}',
            '{"type":"message_start","message":{"role":"assistant","content":[],"api":"openai-codex-responses","provider":"openai-codex","model":"gpt-5.6-sol","usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"stopReason":"error","timestamp":2,"errorMessage":"Codex error: The usage limit has been reached"}}',
            '{"type":"message_end","message":{"role":"assistant","content":[],"api":"openai-codex-responses","provider":"openai-codex","model":"gpt-5.6-sol","usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"stopReason":"error","timestamp":2,"errorMessage":"Codex error: The usage limit has been reached"}}',
            '{"type":"turn_end","message":{"role":"assistant","content":[],"stopReason":"error","errorMessage":"Codex error: The usage limit has been reached"},"toolResults":[]}',
            '{"type":"agent_end","messages":[],"willRetry":false}',
            '{"type":"agent_settled"}',
        ]
    )

    HEALTHY_STREAM = "\n".join(
        [
            '{"type":"session","version":3,"id":"x","timestamp":"2026-08-31T04:55:32.714Z","cwd":"/repo"}',
            '{"type":"agent_start"}',
            '{"type":"turn_start"}',
            '{"type":"message_update","usage":{"input":100,"output":5,"cacheRead":900,"cacheWrite":0,"cost":{"total":0.004}}}',
            '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"ack."}],"stopReason":"stop","usage":{"input":100,"output":5,"cacheRead":900,"cacheWrite":0,"cost":{"total":0.004}}}}',
            '{"type":"agent_settled"}',
        ]
    )

    @requires_node
    def test_provider_error_stream_returns_error_message(self):
        result = _call_lib_function("extractDispatchError", self.ERROR_STREAM)
        assert result == "Codex error: The usage limit has been reached"

    @requires_node
    def test_healthy_stream_returns_none(self):
        result = _call_lib_function("extractDispatchError", self.HEALTHY_STREAM)
        assert result is None

    @requires_node
    def test_malformed_lines_are_skipped_not_fatal(self):
        result = _call_lib_function("extractDispatchError", "not json {\n" + self.ERROR_STREAM)
        assert result == "Codex error: The usage limit has been reached"

    @requires_node
    def test_error_without_message_gets_fallback_string(self):
        stream = '{"type":"message_end","message":{"role":"assistant","content":[],"stopReason":"error"}}'
        result = _call_lib_function("extractDispatchError", stream)
        assert isinstance(result, str) and result


class TestModelIdentityOrDispatchError:
    @requires_node
    def test_matching_final_provider_and_model_return_canonical_identity(self):
        stream = (
            '{"type":"message_end","message":{"role":"assistant","provider":"openai-codex",'
            '"model":"gpt-5.6-sol","content":[],"stopReason":"stop"}}'
        )
        identity = _call_lib_function(
            "modelIdentityOrDispatchError", stream, "openai-codex/gpt-5.6-sol"
        )
        assert identity == "openai-codex/gpt-5.6-sol"

    @requires_node
    def test_provider_fallback_mismatch_throws(self):
        stream = (
            '{"type":"message_end","message":{"role":"assistant","provider":"zai",'
            '"model":"glm-5.3","content":[],"stopReason":"stop"}}'
        )
        outcome = _call_lib_function_outcome(
            "modelIdentityOrDispatchError", stream, "openai-codex/gpt-5.6-sol"
        )
        assert outcome["thrown"] is True
        assert "requested openai-codex/gpt-5.6-sol" in outcome["message"]
        assert "received zai/glm-5.3" in outcome["message"]

    @requires_node
    def test_missing_provider_identity_throws(self):
        stream = (
            '{"type":"message_end","message":{"role":"assistant","content":[],'
            '"stopReason":"stop"}}'
        )
        outcome = _call_lib_function_outcome(
            "modelIdentityOrDispatchError", stream, "openai-codex/gpt-5.6-sol"
        )
        assert outcome["thrown"] is True
        assert "no provider/model identity" in outcome["message"]


class TestExtractFinalUsage:
    """extractFinalUsage — usage must come from the authoritative final assistant message_end,
    not from message_update streaming snapshots: codex-shaped streams carry ZEROED usage
    snapshots during streaming while the real numbers land only on the final message_end.
    Fixtures below are that codex-shaped stream.
    """

    CODEX_STREAM = "\n".join(
        [
            '{"type":"session","version":3,"id":"x","timestamp":"2026-08-31T12:46:59.233Z","cwd":"/repo"}',
            '{"type":"agent_start"}',
            '{"type":"turn_start"}',
            '{"type":"message_start","message":{"role":"user","content":[{"type":"text","text":"ack"}],"timestamp":1}}',
            '{"type":"message_end","message":{"role":"user","content":[{"type":"text","text":"ack"}],"timestamp":1}}',
            '{"type":"message_start","message":{"role":"assistant","content":[],"usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"totalTokens":0,"cost":{"total":0}},"stopReason":"pending","timestamp":2}}',
            '{"type":"message_update","usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"totalTokens":0,"cost":{"total":0}},"assistantMessageEvent":{"type":"text_start","contentIndex":0}}',
            '{"type":"message_update","usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"totalTokens":0,"cost":{"total":0}},"assistantMessageEvent":{"type":"text_delta","contentIndex":0,"delta":"ack"}}',
            '{"type":"message_update","usage":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"totalTokens":0,"cost":{"total":0}},"assistantMessageEvent":{"type":"text_end","contentIndex":0,"content":"ack"}}',
            '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"ack"}],"usage":{"input":13580,"output":5,"cacheRead":0,"cacheWrite":0,"totalTokens":13585,"cost":{"input":0.0679,"output":0.00015,"cacheRead":0,"cacheWrite":0,"total":0.06805}},"stopReason":"stop","timestamp":2}}',
            '{"type":"agent_settled"}',
        ]
    )

    @requires_node
    def test_codex_zeroed_snapshots_yield_authoritative_message_end_usage(self):
        result = _call_lib_function("extractFinalUsage", self.CODEX_STREAM)
        assert result is not None
        assert result["input"] == 13580
        assert result["cacheRead"] == 0
        assert result["cost"]["total"] == 0.06805

    @requires_node
    def test_message_end_preferred_over_earlier_message_update_snapshots(self):
        """Even when message_update carries real cumulative usage (the zai shape), the final
        assistant message_end remains the authoritative source and must win."""
        stream = "\n".join(
            [
                '{"type":"message_update","usage":{"input":55,"cacheRead":29824,"cacheWrite":0,"cost":{"total":0.0078}}}',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"ack"}],"usage":{"input":55,"cacheRead":29824,"cacheWrite":0,"cost":{"total":0.00784444}},"stopReason":"stop"}}',
            ]
        )
        result = _call_lib_function("extractFinalUsage", stream)
        assert result["cost"]["total"] == 0.00784444

    @requires_node
    def test_falls_back_to_message_update_when_no_assistant_message_end(self):
        stream = "\n".join(
            [
                '{"type":"message_update","usage":{"input":10,"cacheRead":0,"cacheWrite":0,"cost":{"total":0.001}}}',
                '{"type":"message_update","usage":{"input":20,"cacheRead":5,"cacheWrite":0,"cost":{"total":0.002}}}',
            ]
        )
        result = _call_lib_function("extractFinalUsage", stream)
        assert result["input"] == 20
        assert result["cacheRead"] == 5

    @requires_node
    def test_errored_message_end_is_not_used_as_authoritative(self):
        """An errored final message_end (stopReason error, zeroed usage) must not override an
        earlier usable usage — the dispatch-error path owns failure reporting."""
        stream = "\n".join(
            [
                '{"type":"message_update","usage":{"input":20,"cacheRead":5,"cacheWrite":0,"cost":{"total":0.002}}}',
                '{"type":"message_end","message":{"role":"assistant","content":[],"usage":{"input":0,"cacheRead":0,"cacheWrite":0,"cost":{"total":0}},"stopReason":"error","errorMessage":"boom"}}',
            ]
        )
        result = _call_lib_function("extractFinalUsage", stream)
        assert result["input"] == 20

    @requires_node
    def test_no_usage_anywhere_returns_none(self):
        stream = '{"type":"agent_start"}\n{"type":"agent_settled"}'
        assert _call_lib_function("extractFinalUsage", stream) is None


class TestParsePipeDelimitedFindings:
    """Direct, no-process-spawn (beyond `node` itself) unit tests of
    parsePipeDelimitedFindings — the standalone parser factored out of the ablate dispatch flow
    into scripts/preload-probe-lib.mjs specifically so it's testable this way."""

    @requires_node
    def test_no_issues_sentence_yields_zero_findings_not_an_error(self):
        text = "No security issues found in this diff."
        findings = _call_lib_function("parsePipeDelimitedFindings", text)
        assert findings == []

    @requires_node
    def test_well_formed_findings_are_parsed(self):
        text = (
            "Critical | a.ts:10 | SQL injection | Attacker-controlled input reaches a raw query "
            "| Use a parameterized query\n"
            "Medium | b.ts:20 | Missing null check | Crashes on empty input | Add a guard clause\n"
            "Low | c.ts:30 | Unused import | Dead code | Remove the import\n"
        )
        findings = _call_lib_function("parsePipeDelimitedFindings", text)
        assert len(findings) == 3
        assert findings[0] == {
            "severity": "Critical",
            "fileLine": "a.ts:10",
            "issue": "SQL injection",
            "whyItMatters": "Attacker-controlled input reaches a raw query",
            "suggestedFix": "Use a parameterized query",
        }
        assert [f["severity"] for f in findings] == ["Critical", "Medium", "Low"]

    @requires_node
    def test_mixed_prose_and_findings_skips_non_matching_lines(self):
        text = (
            "Here is my review of this diff:\n"
            "\n"
            "High | c.ts:5 | Leaked secret | Committed API key | Rotate and remove from history\n"
            "\n"
            "That's everything I found.\n"
        )
        findings = _call_lib_function("parsePipeDelimitedFindings", text)
        assert len(findings) == 1
        assert findings[0]["severity"] == "High"
        assert findings[0]["fileLine"] == "c.ts:5"

    @requires_node
    def test_tolerates_surrounding_whitespace_around_pipes(self):
        text = "Low  |  d.ts:1  |  minor nit  |  style only  |  rename variable  \n"
        findings = _call_lib_function("parsePipeDelimitedFindings", text)
        assert len(findings) == 1
        assert findings[0] == {
            "severity": "Low",
            "fileLine": "d.ts:1",
            "issue": "minor nit",
            "whyItMatters": "style only",
            "suggestedFix": "rename variable",
        }

    @requires_node
    def test_unknown_severity_word_is_not_treated_as_a_finding(self):
        """A line that happens to have 5 pipe-delimited fields but whose first field isn't one
        of the 4 known severity tiers (e.g. a stray markdown table row) must not be misparsed as
        a finding."""
        text = "Column A | Column B | Column C | Column D | Column E\n"
        findings = _call_lib_function("parsePipeDelimitedFindings", text)
        assert findings == []

    @requires_node
    def test_bare_pipe_inside_a_field_does_not_drop_the_finding(self):
        """A finding whose Suggested fix text contains a bare `|` (realistic for a TypeScript
        review, e.g. recommending a union type like `string | number`) must still be parsed as
        one finding, with that pipe preserved as literal content in the field — not silently
        dropped because the line no longer splits into exactly 5 parts on every `|`."""
        text = (
            "Medium | e.ts:12 | Overly broad parameter type | Callers can pass unexpected values "
            "| Narrow the parameter to `string | number` instead of `any`\n"
        )
        findings = _call_lib_function("parsePipeDelimitedFindings", text)
        assert len(findings) == 1
        assert findings[0] == {
            "severity": "Medium",
            "fileLine": "e.ts:12",
            "issue": "Overly broad parameter type",
            "whyItMatters": "Callers can pass unexpected values",
            "suggestedFix": "Narrow the parameter to `string | number` instead of `any`",
        }

    @requires_node
    def test_ablation_response_rejects_unstructured_prose(self):
        outcome = _call_lib_function_outcome(
            "parseAblationResponse", "I reviewed the diff and everything looks fine."
        )
        assert outcome["thrown"] is True
        assert "unexpected output line" in outcome["message"]

    @requires_node
    def test_ablation_response_accepts_explicit_no_issues_sentence(self):
        findings = _call_lib_function(
            "parseAblationResponse", "No architecture issues found in this diff."
        )
        assert findings == []

    @requires_node
    def test_ablation_response_rejects_duplicate_no_issues_sentences(self):
        outcome = _call_lib_function_outcome(
            "parseAblationResponse",
            "No architecture issues found in this diff.\nNo ablation issues found in this diff.",
        )
        assert outcome["thrown"] is True
        assert "duplicate no-issues sentence" in outcome["message"]

    @requires_node
    def test_ablation_response_rejects_prose_beside_a_valid_finding(self):
        text = (
            "Here is my review:\n"
            "High | a.ts:1 | Broken branch | Crashes callers | Add a guard\n"
        )
        outcome = _call_lib_function_outcome("parseAblationResponse", text)
        assert outcome["thrown"] is True
        assert "unexpected output line" in outcome["message"]

    @requires_node
    def test_ablation_response_allows_required_canary_footer(self):
        text = (
            "High | a.ts:1 | Broken branch | Crashes callers | Add a guard\n"
            "SWB-CANARIES-APPLIED: swe-workbench:principle-clean-code\n"
        )
        findings = _call_lib_function("parseAblationResponse", text)
        assert len(findings) == 1
        assert findings[0]["fileLine"] == "a.ts:1"

    @requires_node
    def test_ablation_response_rejects_empty_finding_fields(self):
        outcome = _call_lib_function_outcome(
            "parseAblationResponse", "High | a.ts:1 | Broken branch |  | Add a guard"
        )
        assert outcome["thrown"] is True
        assert "unexpected output line" in outcome["message"]

    @pytest.mark.parametrize("file_line", ["a.ts", "a.ts:0", ":12", "a.ts:ten"])
    @requires_node
    def test_ablation_response_rejects_malformed_file_line(self, file_line: str):
        outcome = _call_lib_function_outcome(
            "parseAblationResponse",
            f"High | {file_line} | Broken branch | Crashes callers | Add a guard",
        )
        assert outcome["thrown"] is True
        assert "unexpected output line" in outcome["message"]


@requires_node
def test_ablate_dry_run_reports_both_arms_prefix_lengths_and_confirms_pure_subset(real_agent_id):
    result = _run_probe(
        [
            "ablate",
            "--agent",
            real_agent_id,
            "--corpus",
            str(ABLATION_CORPUS),
            "--omit",
            "principle-ddd",
            "--dry-run",
        ]
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    out = result.stdout

    baseline_match = re.search(r"baseline prefix length: (\d+) chars", out)
    omit_match = re.search(r"omit\(principle-ddd\) prefix length: (\d+) chars", out)
    assert baseline_match and omit_match, f"dry-run output missing expected lines: {out!r}"
    baseline_len = int(baseline_match.group(1))
    omit_len = int(omit_match.group(1))
    diff = baseline_len - omit_len
    assert diff > 0, "omitting a preloaded skill must shrink the composed prefix"

    # Ballpark tolerance (brief: "don't assert exact byte equality... ballpark is fine"):
    # composeSystemPrompt() adds a "## Preloaded skill: ..." header + relative-path note + a
    # "\n\n---\n\n" separator around each skill's (frontmatter-stripped) body, so the removed
    # prefix is somewhat larger than the raw on-disk file (which still includes frontmatter,
    # partially offsetting that overhead) — assert same order of magnitude, not exact equality.
    skill_file = ROOT / "skills" / "principle-ddd" / "SKILL.md"
    raw_len = len(skill_file.read_text())
    assert raw_len * 0.5 <= diff <= raw_len * 1.5, (
        f"prefix length diff {diff} not within a reasonable ballpark of raw skill file size {raw_len}"
    )

    assert "confirmed: omit arm introduces no lines absent from baseline" in out


@requires_node
def test_ablate_dry_run_unknown_omit_skill_fails_fast_naming_actual_skills(real_agent_id):
    result = _run_probe(
        [
            "ablate",
            "--agent",
            real_agent_id,
            "--corpus",
            str(ABLATION_CORPUS),
            "--omit",
            "totally-not-a-preloaded-skill",
            "--dry-run",
        ]
    )
    assert result.returncode != 0
    assert "totally-not-a-preloaded-skill" in result.stderr
    # The error must name the agent's actual preloaded skill ids so the caller can pick a real one.
    assert "principle-ddd" in result.stderr
    assert "principle-code-review" in result.stderr


@requires_node
def test_ablate_nonexistent_corpus_dir_fails_with_clear_error(real_agent_id, tmp_path):
    missing = tmp_path / "does-not-exist"
    result = _run_probe(
        ["ablate", "--agent", real_agent_id, "--corpus", str(missing), "--omit", "principle-ddd"]
    )
    assert result.returncode != 0
    assert str(missing) in result.stderr


@requires_node
def test_ablate_empty_corpus_dir_fails_with_clear_error(real_agent_id, tmp_path):
    empty_dir = tmp_path / "empty-corpus"
    empty_dir.mkdir()
    result = _run_probe(
        ["ablate", "--agent", real_agent_id, "--corpus", str(empty_dir), "--omit", "principle-ddd"]
    )
    assert result.returncode != 0
    assert "no *.diff files" in result.stderr


@requires_node
def test_ablate_run_missing_agent_fails_with_usage_error():
    result = _run_probe(["ablate", "--corpus", str(ABLATION_CORPUS), "--omit", "principle-ddd"])
    assert result.returncode != 0
    assert "--agent" in result.stderr


@requires_node
def test_ablate_run_missing_corpus_fails_with_usage_error(real_agent_id):
    result = _run_probe(["ablate", "--agent", real_agent_id, "--omit", "principle-ddd"])
    assert result.returncode != 0
    assert "--corpus" in result.stderr


@requires_node
def test_ablate_run_missing_omit_fails_with_usage_error(real_agent_id):
    result = _run_probe(["ablate", "--agent", real_agent_id, "--corpus", str(ABLATION_CORPUS)])
    assert result.returncode != 0
    assert "--omit" in result.stderr


@requires_node
def test_ablate_live_run_requires_explicit_sweep_and_model(real_agent_id):
    result = _run_probe(
        [
            "ablate",
            "--agent",
            real_agent_id,
            "--corpus",
            str(ABLATION_CORPUS),
            "--omit",
            "principle-ddd",
        ]
    )
    assert result.returncode != 0
    assert "--sweep" in result.stderr
    assert "--model" in result.stderr


@requires_node
def test_ablate_report_requires_explicit_sweep():
    result = _run_probe(["ablate", "--report"])
    assert result.returncode != 0
    assert "--sweep" in result.stderr


class TestAblateReport:
    SWEEP = "c3-2026-09-20"
    MODEL = "openai-codex/gpt-5.6-sol"

    def _ablation_runs_file(self, project_dir: Path) -> Path:
        path = project_dir / ".claude" / "cache" / "dispatch-probes" / "ablation-runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _record(self, *, arm: str, findings: list[dict], **overrides) -> dict:
        record = {
            "schemaVersion": 2,
            "sweep": self.SWEEP,
            "agent": "reviewer",
            "omitted": "principle-ddd",
            "diff": "01.diff",
            "arm": arm,
            "model": self.MODEL,
            "commit": "abc123",
            "corpus": {"fingerprint": "sha256:corpus", "files": ["01.diff"]},
            "promptFingerprint": f"sha256:{arm}-prompt",
            "findings": findings,
            "usage": {
                "input": 100,
                "output": 10,
                "cacheRead": 0,
                "cacheWrite": 0,
                "cost": {"total": 0.01},
            },
            "ts": "2026-09-20T00:00:00.000Z",
        }
        record.update(overrides)
        return record

    def _write_records(self, project_dir: Path, records: list[dict]) -> None:
        path = self._ablation_runs_file(project_dir)
        path.write_text("".join(f"{json.dumps(record)}\n" for record in records))

    @requires_node
    def test_no_data_file_yet_exits_zero_pointing_at_run_mode(self, tmp_path: Path):
        env = {**_CLEAN_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = _run_probe(["ablate", "--report", "--sweep", self.SWEEP], env=env)
        assert result.returncode == 0, result.stderr
        assert "no ablation-run data collected yet" in result.stdout
        assert "ablate --agent" in result.stdout

    @requires_node
    def test_lost_and_downgrade_counts_match_hand_calculation(self, tmp_path: Path):
        """Hand-constructed fixture, one diff, one omitted skill:
        - a.ts:10  baseline High -> omit-arm Low   => severity downgrade
        - a.ts:20  baseline Medium -> absent        => lost finding
        - a.ts:30  baseline Critical -> omit-arm Critical (unchanged) => neither lost nor
          downgraded
        Hand calc: lost=1, downgraded=1.
        """
        baseline = self._record(
            arm="baseline",
            findings=[
                {
                    "severity": "High",
                    "fileLine": "a.ts:10",
                    "issue": "x",
                    "whyItMatters": "y",
                    "suggestedFix": "z",
                },
                {
                    "severity": "Medium",
                    "fileLine": "a.ts:20",
                    "issue": "x2",
                    "whyItMatters": "y2",
                    "suggestedFix": "z2",
                },
                {
                    "severity": "Critical",
                    "fileLine": "a.ts:30",
                    "issue": "x3",
                    "whyItMatters": "y3",
                    "suggestedFix": "z3",
                },
            ],
        )
        omit = self._record(
            arm="omit",
            findings=[
                {
                    "severity": "Low",
                    "fileLine": "a.ts:10",
                    "issue": "x",
                    "whyItMatters": "y",
                    "suggestedFix": "z",
                },
                {
                    "severity": "Critical",
                    "fileLine": "a.ts:30",
                    "issue": "x3",
                    "whyItMatters": "y3",
                    "suggestedFix": "z3",
                },
            ],
        )
        self._write_records(tmp_path, [baseline, omit])

        env = {**_CLEAN_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = _run_probe(
            ["ablate", "--report", "--sweep", self.SWEEP, "--agent", "reviewer"], env=env
        )
        assert result.returncode == 0, result.stderr
        out = result.stdout

        assert (
            "agent=reviewer omitted=principle-ddd: lost=1 downgraded=1 "
            f"model={self.MODEL}" in out
        )
        assert "lost: a.ts:20 (Medium)" in out
        assert "downgraded: a.ts:10 High -> Low" in out
        assert "a.ts:30" not in out

    @requires_node
    def test_agent_filter_excludes_other_agents_data(self, tmp_path: Path):
        other_agent_baseline = self._record(
            arm="baseline", findings=[], agent="some-other-agent", omitted="some-skill"
        )
        other_agent_omit = self._record(
            arm="omit", findings=[], agent="some-other-agent", omitted="some-skill"
        )
        self._write_records(tmp_path, [other_agent_baseline, other_agent_omit])

        env = {**_CLEAN_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = _run_probe(
            ["ablate", "--report", "--sweep", self.SWEEP, "--agent", "reviewer"], env=env
        )
        assert result.returncode == 0, result.stderr
        assert "no ablation-run data collected yet" in result.stdout
        assert "some-other-agent" not in result.stdout

    @pytest.mark.parametrize(
        ("records", "message"),
        [
            (lambda self: [self._record(arm="baseline", findings=[])], "incomplete"),
            (
                lambda self: [
                    self._record(arm="baseline", findings=[]),
                    self._record(arm="baseline", findings=[]),
                    self._record(arm="omit", findings=[]),
                ],
                "duplicate",
            ),
            (
                lambda self: [
                    self._record(arm="baseline", findings=[]),
                    self._record(arm="omit", findings=[], model="different/model"),
                ],
                "mixed model",
            ),
            (
                lambda self: [
                    self._record(
                        arm="baseline",
                        findings=[],
                        usage={"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0},
                    ),
                    self._record(arm="omit", findings=[]),
                ],
                "usage.cost.total",
            ),
            (
                lambda self: [
                    self._record(arm="baseline", findings=[{}]),
                    self._record(arm="omit", findings=[]),
                ],
                "invalid finding",
            ),
            (
                lambda self: [
                    self._record(
                        arm="baseline",
                        findings=[
                            {
                                "severity": "High",
                                "fileLine": "a.ts:1",
                                "issue": "   ",
                                "whyItMatters": "Crashes callers",
                                "suggestedFix": "Add a guard",
                            }
                        ],
                    ),
                    self._record(arm="omit", findings=[]),
                ],
                "invalid finding",
            ),
            (
                lambda self: [
                    self._record(
                        arm="baseline",
                        findings=[],
                        usage={
                            "input": 0,
                            "output": 0,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                            "cost": {"total": 0},
                        },
                    ),
                    self._record(arm="omit", findings=[]),
                ],
                "zero billed",
            ),
        ],
    )
    @requires_node
    def test_report_fails_closed_without_emitting_summary(
        self, tmp_path: Path, records, message: str
    ):
        self._write_records(tmp_path, records(self))
        env = {**_CLEAN_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = _run_probe(
            ["ablate", "--report", "--sweep", self.SWEEP, "--agent", "reviewer"], env=env
        )
        assert result.returncode != 0
        assert message in result.stderr.lower()
        assert "agent=reviewer omitted=" not in result.stdout

    @requires_node
    def test_report_fails_closed_on_malformed_jsonl(self, tmp_path: Path):
        path = self._ablation_runs_file(tmp_path)
        path.write_text("{not-json}\n")
        env = {**_CLEAN_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = _run_probe(["ablate", "--report", "--sweep", self.SWEEP], env=env)
        assert result.returncode != 0
        assert "malformed json" in result.stderr.lower()

    @requires_node
    def test_report_rejects_model_drift_between_skill_pairs(self, tmp_path: Path):
        records = [
            self._record(arm="baseline", findings=[]),
            self._record(arm="omit", findings=[]),
            self._record(
                arm="baseline",
                findings=[],
                omitted="principle-clean-architecture",
                model="different/model",
            ),
            self._record(
                arm="omit",
                findings=[],
                omitted="principle-clean-architecture",
                model="different/model",
            ),
        ]
        self._write_records(tmp_path, records)
        env = {**_CLEAN_ENV, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = _run_probe(["ablate", "--report", "--sweep", self.SWEEP], env=env)
        assert result.returncode != 0
        assert "mixed model values in sweep" in result.stderr.lower()
        assert "agent=reviewer omitted=" not in result.stdout

    @requires_node
    def test_record_validation_rejects_incomplete_usage_before_persistence(self):
        record = self._record(
            arm="baseline",
            findings=[],
            usage={"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0},
        )
        outcome = _call_lib_function_outcome("validateAblationRecord", record)
        assert outcome["thrown"] is True
        assert "usage.cost.total" in outcome["message"]

    @requires_node
    def test_record_validation_rejects_duplicate_finding_locations(self):
        finding = {
            "severity": "High",
            "fileLine": "a.ts:1",
            "issue": "Broken branch",
            "whyItMatters": "Crashes callers",
            "suggestedFix": "Add a guard",
        }
        record = self._record(arm="baseline", findings=[finding, finding])
        outcome = _call_lib_function_outcome("validateAblationRecord", record)
        assert outcome["thrown"] is True
        assert "duplicate finding location" in outcome["message"]

    @requires_node
    def test_record_validation_rejects_malformed_finding_location(self):
        finding = {
            "severity": "High",
            "fileLine": "a.ts:0",
            "issue": "Broken branch",
            "whyItMatters": "Crashes callers",
            "suggestedFix": "Add a guard",
        }
        record = self._record(arm="baseline", findings=[finding])
        outcome = _call_lib_function_outcome("validateAblationRecord", record)
        assert outcome["thrown"] is True
        assert "invalid finding" in outcome["message"]

    @requires_node
    def test_plan_ablation_arms_resumes_only_missing_arm(self):
        baseline = self._record(arm="baseline", findings=[])
        identity = {
            key: baseline[key]
            for key in ("sweep", "agent", "omitted", "model", "commit", "corpus")
        }
        identity["promptFingerprints"] = {
            "baseline": "sha256:baseline-prompt",
            "omit": "sha256:omit-prompt",
        }
        pending = _call_lib_function("planAblationArms", [baseline], identity)
        assert pending == [{"diff": "01.diff", "arm": "omit"}]

    @requires_node
    def test_live_run_persists_provenance_and_resume_skips_complete_arms(
        self, tmp_path: Path, real_agent_id: str
    ):
        bin_dir = tmp_path / "bin"
        corpus_dir = tmp_path / "corpus"
        project_dir = tmp_path / "project"
        calls_file = tmp_path / "pi-calls"
        bin_dir.mkdir()
        corpus_dir.mkdir()
        project_dir.mkdir()
        (corpus_dir / "01.diff").write_text("diff --git a/a.ts b/a.ts\n")

        fake_git = bin_dir / "git"
        fake_git.write_text(
            """#!/bin/sh
if [ "$1" = "-C" ]; then shift 2; fi
case "$1 $2" in
  "rev-parse HEAD") printf '%s\\n' abc123 ;;
  "status --porcelain") : ;;
  *) exit 2 ;;
esac
"""
        )
        fake_pi = bin_dir / "pi"
        fake_pi.write_text(
            """#!/bin/sh
printf '%s\\n' call >> "$FAKE_PI_CALLS"
printf '%s\\n' '{"type":"message_end","message":{"role":"assistant","provider":"openai-codex","model":"gpt-5.6-sol","content":[{"type":"text","text":"No architecture issues found in this diff."}],"usage":{"input":100,"output":10,"cacheRead":0,"cacheWrite":0,"cost":{"total":0.01}},"stopReason":"stop"}}'
"""
        )
        fake_git.chmod(0o755)
        fake_pi.chmod(0o755)

        env = {
            **_CLEAN_ENV,
            "PATH": f"{bin_dir}:{_CLEAN_ENV['PATH']}",
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "FAKE_PI_CALLS": str(calls_file),
        }
        args = [
            "ablate",
            "--agent",
            real_agent_id,
            "--corpus",
            str(corpus_dir),
            "--omit",
            "principle-ddd",
            "--sweep",
            self.SWEEP,
            "--model",
            self.MODEL,
        ]
        first = _run_probe(args, env=env)
        second = _run_probe(args, env=env)

        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        assert "already complete; no dispatches needed" in second.stdout
        assert calls_file.read_text().splitlines() == ["call", "call"]

        records = [
            json.loads(line)
            for line in self._ablation_runs_file(project_dir).read_text().splitlines()
        ]
        assert {record["arm"] for record in records} == {"baseline", "omit"}
        assert all(record["schemaVersion"] == 2 for record in records)
        assert all(record["model"] == self.MODEL for record in records)
        assert all(record["commit"] == "abc123" for record in records)
        assert all(record["corpus"]["fingerprint"].startswith("sha256:") for record in records)
        assert all(record["promptFingerprint"].startswith("sha256:") for record in records)
        assert all(record["usage"]["cost"]["total"] == 0.01 for record in records)

    @requires_node
    def test_corpus_content_is_snapshotted_once_for_hashing_and_both_arms(
        self, tmp_path: Path, real_agent_id: str
    ):
        bin_dir = tmp_path / "bin"
        corpus_dir = tmp_path / "corpus"
        project_dir = tmp_path / "project"
        prompts_dir = tmp_path / "prompts"
        calls_file = tmp_path / "pi-calls"
        corpus_file = corpus_dir / "01.diff"
        bin_dir.mkdir()
        corpus_dir.mkdir()
        project_dir.mkdir()
        prompts_dir.mkdir()
        corpus_file.write_text("ORIGINAL CORPUS CONTENT\n")

        fake_git = bin_dir / "git"
        fake_git.write_text(
            """#!/bin/sh
if [ "$1" = "-C" ]; then shift 2; fi
case "$1 $2" in
  "rev-parse HEAD") printf '%s\\n' abc123 ;;
  "status --porcelain") : ;;
  *) exit 2 ;;
esac
"""
        )
        fake_pi = bin_dir / "pi"
        fake_pi.write_text(
            """#!/bin/sh
prompt=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-p" ]; then shift; prompt=$1; fi
  shift
done
printf '%s\\n' call >> "$FAKE_PI_CALLS"
count=$(wc -l < "$FAKE_PI_CALLS" | tr -d ' ')
printf '%s' "$prompt" > "$FAKE_PROMPTS_DIR/$count"
if [ "$count" -eq 1 ]; then printf '%s\\n' 'CHANGED AFTER FINGERPRINT' > "$FAKE_CORPUS_FILE"; fi
printf '%s\\n' '{"type":"message_end","message":{"role":"assistant","provider":"openai-codex","model":"gpt-5.6-sol","content":[{"type":"text","text":"No ablation issues found in this diff."}],"usage":{"input":100,"output":10,"cacheRead":0,"cacheWrite":0,"cost":{"total":0.01}},"stopReason":"stop"}}'
"""
        )
        fake_git.chmod(0o755)
        fake_pi.chmod(0o755)

        env = {
            **_CLEAN_ENV,
            "PATH": f"{bin_dir}:{_CLEAN_ENV['PATH']}",
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "FAKE_PI_CALLS": str(calls_file),
            "FAKE_PROMPTS_DIR": str(prompts_dir),
            "FAKE_CORPUS_FILE": str(corpus_file),
        }
        result = _run_probe(
            [
                "ablate",
                "--agent",
                real_agent_id,
                "--corpus",
                str(corpus_dir),
                "--omit",
                "principle-ddd",
                "--sweep",
                self.SWEEP,
                "--model",
                self.MODEL,
            ],
            env=env,
        )

        assert result.returncode == 0, result.stderr
        baseline_prompt = (prompts_dir / "1").read_text()
        omit_prompt = (prompts_dir / "2").read_text()
        assert baseline_prompt == omit_prompt
        assert "ORIGINAL CORPUS CONTENT" in baseline_prompt

    @requires_node
    def test_incomplete_provider_usage_stops_before_persistence_or_next_arm(
        self, tmp_path: Path, real_agent_id: str
    ):
        bin_dir = tmp_path / "bin"
        corpus_dir = tmp_path / "corpus"
        project_dir = tmp_path / "project"
        calls_file = tmp_path / "pi-calls"
        bin_dir.mkdir()
        corpus_dir.mkdir()
        project_dir.mkdir()
        (corpus_dir / "01.diff").write_text("diff --git a/a.ts b/a.ts\n")

        fake_git = bin_dir / "git"
        fake_git.write_text(
            """#!/bin/sh
if [ "$1" = "-C" ]; then shift 2; fi
case "$1 $2" in
  "rev-parse HEAD") printf '%s\\n' abc123 ;;
  "status --porcelain") : ;;
  *) exit 2 ;;
esac
"""
        )
        fake_pi = bin_dir / "pi"
        fake_pi.write_text(
            """#!/bin/sh
printf '%s\\n' call >> "$FAKE_PI_CALLS"
printf '%s\\n' '{"type":"message_end","message":{"role":"assistant","provider":"openai-codex","model":"gpt-5.6-sol","content":[{"type":"text","text":"No ablation issues found in this diff."}],"usage":{"input":100,"output":10,"cacheRead":0,"cacheWrite":0},"stopReason":"stop"}}'
"""
        )
        fake_git.chmod(0o755)
        fake_pi.chmod(0o755)

        env = {
            **_CLEAN_ENV,
            "PATH": f"{bin_dir}:{_CLEAN_ENV['PATH']}",
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "FAKE_PI_CALLS": str(calls_file),
        }
        result = _run_probe(
            [
                "ablate",
                "--agent",
                real_agent_id,
                "--corpus",
                str(corpus_dir),
                "--omit",
                "principle-ddd",
                "--sweep",
                self.SWEEP,
                "--model",
                self.MODEL,
            ],
            env=env,
        )

        assert result.returncode != 0
        assert "usage.cost.total" in result.stderr
        assert calls_file.read_text().splitlines() == ["call"]
        assert not self._ablation_runs_file(project_dir).exists()

    @requires_node
    def test_spawn_failure_names_the_pending_arm_and_persists_no_evidence(
        self, tmp_path: Path, real_agent_id: str
    ):
        """Removing label propagation from runPiOnce must lose this operator-safe context."""
        bin_dir = tmp_path / "bin"
        corpus_dir = tmp_path / "corpus"
        project_dir = tmp_path / "project"
        bin_dir.mkdir()
        corpus_dir.mkdir()
        project_dir.mkdir()
        (corpus_dir / "01.diff").write_text("diff --git a/a.ts b/a.ts\n")

        fake_git = bin_dir / "git"
        fake_git.write_text(
            """#!/bin/sh
if [ "$1" = "-C" ]; then shift 2; fi
case "$1 $2" in
  "rev-parse HEAD") printf '%s\\n' abc123 ;;
  "status --porcelain") : ;;
  *) exit 2 ;;
esac
"""
        )
        fake_git.chmod(0o755)

        env = {
            **_CLEAN_ENV,
            "PATH": str(bin_dir),
            "CLAUDE_PROJECT_DIR": str(project_dir),
        }
        result = _run_probe(
            [
                "ablate",
                "--agent",
                real_agent_id,
                "--corpus",
                str(corpus_dir),
                "--omit",
                "principle-ddd",
                "--sweep",
                self.SWEEP,
                "--model",
                self.MODEL,
            ],
            env=env,
        )

        assert result.returncode != 0
        assert 'label="01.diff baseline"' in result.stderr
        assert "code=ENOENT" in result.stderr
        assert "stdoutBytes=0" in result.stderr
        assert "stderrBytes=0" in result.stderr
        assert "lastEventType=none" in result.stderr
        assert not self._ablation_runs_file(project_dir).exists()

    @requires_node
    def test_concurrent_resume_is_rejected_before_duplicate_dispatches(
        self, tmp_path: Path, real_agent_id: str
    ):
        bin_dir = tmp_path / "bin"
        corpus_dir = tmp_path / "corpus"
        project_dir = tmp_path / "project"
        calls_file = tmp_path / "pi-calls"
        gate_file = tmp_path / "release-pi"
        bin_dir.mkdir()
        corpus_dir.mkdir()
        project_dir.mkdir()
        (corpus_dir / "01.diff").write_text("diff --git a/a.ts b/a.ts\n")

        fake_git = bin_dir / "git"
        fake_git.write_text(
            """#!/bin/sh
if [ "$1" = "-C" ]; then shift 2; fi
case "$1 $2" in
  "rev-parse HEAD") printf '%s\\n' abc123 ;;
  "status --porcelain") : ;;
  *) exit 2 ;;
esac
"""
        )
        fake_pi = bin_dir / "pi"
        fake_pi.write_text(
            """#!/bin/sh
printf '%s\\n' call >> "$FAKE_PI_CALLS"
while [ ! -e "$FAKE_PI_GATE" ]; do sleep 0.05; done
printf '%s\\n' '{"type":"message_end","message":{"role":"assistant","provider":"openai-codex","model":"gpt-5.6-sol","content":[{"type":"text","text":"No ablation issues found in this diff."}],"usage":{"input":100,"output":10,"cacheRead":0,"cacheWrite":0,"cost":{"total":0.01}},"stopReason":"stop"}}'
"""
        )
        fake_git.chmod(0o755)
        fake_pi.chmod(0o755)

        env = {
            **_CLEAN_ENV,
            "PATH": f"{bin_dir}:{_CLEAN_ENV['PATH']}",
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "FAKE_PI_CALLS": str(calls_file),
            "FAKE_PI_GATE": str(gate_file),
        }
        node = shutil.which("node")
        assert node is not None
        command = [
            node,
            "--experimental-strip-types",
            str(PROBE),
            "ablate",
            "--agent",
            real_agent_id,
            "--corpus",
            str(corpus_dir),
            "--omit",
            "principle-ddd",
            "--sweep",
            self.SWEEP,
            "--model",
            self.MODEL,
        ]
        first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        second = None
        try:
            deadline = time.monotonic() + 5
            while not calls_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert calls_file.exists(), "first probe did not reach its dispatch"
            second = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
            )
            time.sleep(0.2)
            gate_file.touch()
            first_stdout, first_stderr = first.communicate(timeout=15)
            second_stdout, second_stderr = second.communicate(timeout=15)
        finally:
            for process in (first, second):
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

        assert first.returncode == 0, first_stderr
        assert second.returncode != 0, second_stdout
        assert "already locked" in second_stderr
        assert calls_file.read_text().splitlines() == ["call", "call"]

#!/usr/bin/env python3
"""C2/C4 reporter for issue #681's preload instrumentation (Task 6).

Two subcommands, both stdlib-only and read-only over durable JSONL data other tools already
write:

  canary  Reads .claude/cache/skill-usage/canary-citations.jsonl (written by Task 5's
          hooks/skill_usage_flush.sh citation-harvest block) and reports, per (agent, preloaded
          skill), how often that skill's namespaced id showed up in a dispatch's cited skills.

  cache   Reads .claude/cache/dispatch-probes/cache-runs.jsonl (written by this same task's
          additive change to scripts/preload-probe.mjs's live `cache` path) and reports the
          cold-vs-repeat usage comparison for each recorded run pair.

Neither subcommand spawns `pi` or any other process — both are pure readers over data other
tools already produced. Usage:

    python3 scripts/preload-telemetry.py canary [--agent <id>]
    python3 scripts/preload-telemetry.py cache [--agent <id>]

Data-directory resolution: both subcommands resolve their JSONL data file the same way
hooks/skill_usage_flush.sh resolves its cache_dir — ${CLAUDE_PROJECT_DIR:-$PWD} as the base —
so pointing CLAUDE_PROJECT_DIR at a scratch directory (as this file's own tests do) redirects
both subcommands without any extra flag.
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

# validate.py lives alongside this script in scripts/ — Python already puts a directly-run
# script's own directory at sys.path[0], but this insert is a defensive belt-and-suspenders
# match for scripts/compress-descriptions.py's existing import pattern for the same module.
sys.path.insert(0, str(SCRIPT_DIR))
import validate  # noqa: E402


# --------------------------------------------------------------------------------------------
# Data-directory resolution (mirrors hooks/skill_usage_flush.sh's `cache_dir` env-var-or-cwd
# fallback: `${CLAUDE_PROJECT_DIR:-$PWD}/.claude/cache/...`).
# --------------------------------------------------------------------------------------------


def _project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _citations_path() -> Path:
    return _project_dir() / ".claude" / "cache" / "skill-usage" / "canary-citations.jsonl"


def _cache_runs_path() -> Path:
    return _project_dir() / ".claude" / "cache" / "dispatch-probes" / "cache-runs.jsonl"


def _read_jsonl(path: Path) -> tuple[list, int]:
    """Reads a JSONL file, skipping (not crashing on) lines that fail to parse.

    Returns (records, skipped_count). A missing file returns ([], 0) — "no data yet" is an
    expected state for both subcommands, not an error.
    """
    if not path.exists():
        return [], 0
    records = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1
    return records, skipped


# --------------------------------------------------------------------------------------------
# canary subcommand
# --------------------------------------------------------------------------------------------

# Mirrors tests/test_skill_preload.py's _discover_preload_pairs() (near the top of that file) —
# the reference implementation for discovering the full universe of (agent, skill) preload
# pairs from agents/*.md `skills:` frontmatter. Deliberately duplicated, not imported, so this
# reporter carries no test-file dependency; keep this in sync if that function changes.
def _discover_preload_pairs(agents_dir: Path) -> list[tuple[str, str]]:
    pairs = []
    for agent_md in sorted(agents_dir.glob("*.md")):
        fm = validate.parse_frontmatter(agent_md)
        if fm is None:
            continue
        entries = fm.get("skills")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if entry.startswith("swe-workbench:"):
                pairs.append((agent_md.stem, entry.split(":", 1)[1]))
    return pairs


# Paraphrases (does not omit) the plan's finding: the harness that can collect this data may not
# be the harness where the citation is actually meaningful. Printed unconditionally, every run —
# not just for low rates — per the brief.
CANARY_CAVEAT = (
    'CAVEAT: a zero or low citation rate below must NOT be read as "the skill is unused." '
    "The harness where preload provably fires (Pi) has no SubagentStop hook — both telemetry "
    'hooks are pinned "n/a" on Pi (tests/test_pi_contract.py) — so this citation data can '
    "never be collected there at all. Claude Code's in-session Agent tool DOES have "
    "SubagentStop, but has been observed to NOT reliably honor an agent's `skills:` frontmatter "
    'preloading (docs/skill-preload.md\'s "Known caveat" section). The harness that can collect '
    "this data may not be the harness where the citation is actually meaningful, and vice "
    "versa — treat every number below as directional, not conclusive."
)


def run_canary(agent_filter: str | None) -> int:
    agents_dir = ROOT / "agents"
    pairs = _discover_preload_pairs(agents_dir)

    by_agent: dict[str, list[str]] = {}
    for agent, skill in pairs:
        by_agent.setdefault(agent, []).append(skill)

    print("== preload-telemetry canary report ==")
    print()
    print(CANARY_CAVEAT)
    print()

    if agent_filter is not None and agent_filter not in by_agent:
        print(
            f"agent {agent_filter!r} not found in the discovered preload universe "
            "(no `skills:` frontmatter entries namespaced swe-workbench:<skill> in "
            f"agents/{agent_filter}.md)"
        )
        return 0

    universe = [agent_filter] if agent_filter is not None else sorted(by_agent)

    citations_path = _citations_path()
    records, skipped = _read_jsonl(citations_path)

    if skipped:
        print(f"warning: skipped {skipped} malformed line(s) in {citations_path}")
        print()

    if not records:
        print(f"no citation data collected yet ({citations_path} not found or empty)")
        print()

    agent_totals: dict[str, int] = {}
    skill_hits: dict[tuple[str, str], int] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        agent_type = rec.get("agent_type")
        if not isinstance(agent_type, str):
            continue
        agent_totals[agent_type] = agent_totals.get(agent_type, 0) + 1
        cited = rec.get("cited_skills")
        if isinstance(cited, list):
            for skill_id in cited:
                key = (agent_type, skill_id)
                skill_hits[key] = skill_hits.get(key, 0) + 1

    if not universe:
        print("no agents found in the discovered preload universe")
        return 0

    for agent in universe:
        total = agent_totals.get(agent, 0)
        skills = by_agent.get(agent, [])
        if total == 0:
            print(f"agent: {agent} — 0 dispatches recorded")
        else:
            print(f"agent: {agent} — {total} dispatch(es) recorded")
        for skill in skills:
            namespaced = f"swe-workbench:{skill}"
            cited = skill_hits.get((agent, namespaced), 0)
            if total == 0:
                # 0 cited / 0 total ("no data yet") is reported distinctly from 0 cited / N
                # total ("cited zero times out of N observed dispatches") — never conflate them.
                print(f"  {namespaced}: 0/0 (no dispatch data yet)")
            else:
                rate = (cited / total) * 100
                print(f"  {namespaced}: {cited}/{total} ({rate:.1f}%)")
        print()

    return 0


# --------------------------------------------------------------------------------------------
# cache subcommand
# --------------------------------------------------------------------------------------------

_PROBE_HINT = "node --experimental-strip-types scripts/preload-probe.mjs cache --agent <id>"


def _pair_cache_runs(records: list) -> list[tuple[str, dict, dict]]:
    """Pairs run:1/run:2 records by agent + adjacency in file order (append order), NOT by
    timestamp proximity — a live probe invocation always writes exactly one run:1 then one
    run:2 record in sequence for its agent, per the brief."""
    pending: dict[str, dict] = {}
    pairs: list[tuple[str, dict, dict]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        agent = rec.get("agent")
        run = rec.get("run")
        if not isinstance(agent, str):
            continue
        if run == 1:
            pending[agent] = rec
        elif run == 2:
            first = pending.pop(agent, None)
            if first is not None:
                pairs.append((agent, first, rec))
    return pairs


def run_cache(agent_filter: str | None) -> int:
    print("== preload-telemetry cache report ==")
    print()

    path = _cache_runs_path()
    records, skipped = _read_jsonl(path)

    if skipped:
        print(f"warning: skipped {skipped} malformed line(s) in {path}")
        print()

    if not records:
        print(f"no cache-probe run data collected yet ({path} not found or empty).")
        print(f"Run: {_PROBE_HINT}")
        return 0

    pairs = _pair_cache_runs(records)
    if agent_filter is not None:
        pairs = [p for p in pairs if p[0] == agent_filter]

    if not pairs:
        scope = f" for agent {agent_filter!r}" if agent_filter is not None else ""
        print(f"no complete run:1/run:2 pairs recorded{scope}.")
        print(f"Run: {_PROBE_HINT}")
        return 0

    for agent, r1, r2 in pairs:
        print(f"agent: {agent}")
        for label, rec in (("run 1 (cold)", r1), ("run 2 (repeat, same prefix)", r2)):
            usage = rec.get("usage") or {}
            cost_total = (usage.get("cost") or {}).get("total")
            print(
                f"  {label}: input={usage.get('input')} cacheRead={usage.get('cacheRead')} "
                f"cacheWrite={usage.get('cacheWrite')} cost.total={cost_total} "
                f"cacheReadFraction={rec.get('cacheReadFraction')}"
            )
        run2_cache_read = (r2.get("usage") or {}).get("cacheRead") or 0
        cache_hit = run2_cache_read > 0
        verdict = (
            "cache: YES — run 2 showed cache-read activity (cacheRead > 0)"
            if cache_hit
            else "cache: NO — run 2 showed no cache-read activity (cacheRead == 0 or missing)"
        )
        print(f"  {verdict}")
        print()

    return 0


# --------------------------------------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preload-telemetry.py",
        description=(
            "C2/C4 reporter for issue #681 preload instrumentation: "
            "canary citation rates and cache-probe run comparisons."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    canary_p = sub.add_parser(
        "canary", help="report preloaded-skill citation rate per (agent, skill)"
    )
    canary_p.add_argument("--agent", default=None, help="filter the report to one agent id")

    cache_p = sub.add_parser(
        "cache", help="report cached-vs-fresh usage comparisons from recorded probe runs"
    )
    cache_p.add_argument("--agent", default=None, help="filter the report to one agent id")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "canary":
        return run_canary(args.agent)
    if args.subcommand == "cache":
        return run_cache(args.agent)

    # Unreachable: add_subparsers(required=True) plus a fixed choice set means argparse itself
    # already exits non-zero with a usage message for a missing or unknown subcommand.
    parser.error(f"unknown subcommand {args.subcommand!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

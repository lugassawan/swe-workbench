"""Behavioral contract for Pi's reviewed subagent dispatch profiles."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _CLEAN_ENV

ROOT = Path(__file__).parent.parent
MODULE = ROOT / "pi" / "extensions" / "dispatch-profile.ts"
AGENT_SPEC = ROOT / "pi" / "extensions" / "agent-spec.ts"

_DRIVER = r"""
import { pathToFileURL } from "node:url";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const [modulePath, agentSpecPath, root] = process.argv.slice(2);
const profiles = await import(pathToFileURL(modulePath).href);
const agentSpec = await import(pathToFileURL(agentSpecPath).href);
const fixture = (profile, agent, effort, skills) =>
  profiles.resolveDispatchProfile({
    profile,
    agent,
    declaredEffort: effort,
    declaredSkillIds: skills,
  });
const agentNames = readdirSync(join(root, "agents"))
  .filter((name) => name.endsWith(".md"))
  .map((name) => name.slice(0, -3))
  .sort();
const allAgents = Object.fromEntries(agentNames.map((name) => {
  const spec = agentSpec.parseAgentSpec(readFileSync(join(root, "agents", `${name}.md`), "utf8"));
  return [name, fixture("economy", name, spec.effort, spec.skillIds)];
}));
console.log(JSON.stringify({
  profiles: profiles.DISPATCH_PROFILES,
  balanced: fixture("balanced", "reviewer", "xhigh", ["a", "b"]),
  economyReviewer: fixture("economy", "reviewer", "xhigh", [
    "swe-workbench:principle-code-review",
    "swe-workbench:principle-clean-code",
    "swe-workbench:principle-error-handling",
    "swe-workbench:principle-solid",
    "swe-workbench:principle-security",
    "swe-workbench:principle-performance",
    "swe-workbench:principle-resiliency",
    "swe-workbench:principle-accessibility",
    "swe-workbench:principle-concurrency",
    "swe-workbench:principle-observability",
    "swe-workbench:principle-testing",
    "swe-workbench:principle-cost-awareness",
    "swe-workbench:principle-version-control",
    "swe-workbench:principle-ddd",
  ]),
  protected: Object.fromEntries(["architect", "migrator", "security-auditor", "senior-engineer"].map((name) =>
    [name, fixture("economy", name, "high", ["a", "b"])])),
  efforts: Object.fromEntries(["low", "medium", "high", "xhigh", "max", "unknown"].map((effort) =>
    [effort, fixture("economy", "reviewer", effort, ["a"])])),
  full: fixture("full", "reviewer", "xhigh", ["a", "b"]),
  unknown: fixture("economy", "reviewer", undefined, ["a"]),
  retry: [
    profiles.parseFullPreloadRetry("SWB_FULL_PRELOAD_RETRY: missing-domain-guidance"),
    profiles.parseFullPreloadRetry("text\nSWB_FULL_PRELOAD_RETRY: cross-domain-ambiguity"),
    profiles.parseFullPreloadRetry("SWB_FULL_PRELOAD_RETRY: unknown"),
    profiles.parseFullPreloadRetry("prefix SWB_FULL_PRELOAD_RETRY: missing-domain-guidance"),
    profiles.parseFullPreloadRetry("SWB_FULL_PRELOAD_RETRY: missing-domain-guidance\nmore"),
  ],
  guidance: profiles.parentProfileGuidance("economy"),
  allAgents,
}));
"""


@pytest.fixture(scope="module")
def profile_result(tmp_path_factory):
    node = shutil.which("node")
    assert node is not None, "Node is required to execute TypeScript policy tests"
    driver = tmp_path_factory.mktemp("dispatch-profile-driver") / "driver.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    result = subprocess.run(
        [node, "--experimental-strip-types", str(driver), str(MODULE), str(AGENT_SPEC), str(ROOT)],
        capture_output=True,
        text=True,
        env=_CLEAN_ENV,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_balanced_preserves_declared_effort_and_all_preloads(profile_result):
    plan = profile_result["balanced"]
    assert profile_result["profiles"] == ["economy", "balanced", "full"]
    assert plan["effectiveEffort"] == "xhigh"
    assert plan["preloadSkillIds"] == ["a", "b"]
    assert plan["onDemandSkillIds"] == []
    assert plan["allowFullPreloadRetry"] is False


def test_economy_reviewer_uses_exact_core_and_on_demand_remainder(profile_result):
    plan = profile_result["economyReviewer"]
    assert plan["effectiveEffort"] == "high"
    assert plan["preloadSkillIds"] == [
        "swe-workbench:principle-code-review",
        "swe-workbench:principle-clean-code",
        "swe-workbench:principle-security",
        "swe-workbench:principle-testing",
    ]
    assert plan["onDemandSkillIds"] == [
        "swe-workbench:principle-error-handling",
        "swe-workbench:principle-solid",
        "swe-workbench:principle-performance",
        "swe-workbench:principle-resiliency",
        "swe-workbench:principle-accessibility",
        "swe-workbench:principle-concurrency",
        "swe-workbench:principle-observability",
        "swe-workbench:principle-cost-awareness",
        "swe-workbench:principle-version-control",
        "swe-workbench:principle-ddd",
    ]
    assert plan["allowFullPreloadRetry"] is True


def test_economy_protected_agents_keep_effort_and_full_preload(profile_result):
    for name, plan in profile_result["protected"].items():
        assert plan["effectiveEffort"] == "high", name
        assert plan["preloadSkillIds"] == ["a", "b"], name
        assert plan["onDemandSkillIds"] == [], name


@pytest.mark.parametrize(
    ("declared", "expected"),
    [("low", "low"), ("medium", "low"), ("high", "medium"), ("xhigh", "high"), ("max", "xhigh"), ("unknown", "unknown")],
)
def test_economy_lowers_only_known_routine_efforts_one_rung(profile_result, declared, expected):
    assert profile_result["efforts"][declared]["effectiveEffort"] == expected


def test_full_uses_max_effort_and_full_preload(profile_result):
    plan = profile_result["full"]
    assert plan["effectiveEffort"] == "max"
    assert plan["preloadSkillIds"] == ["a", "b"]
    assert plan["onDemandSkillIds"] == []
    assert plan["allowFullPreloadRetry"] is False


def test_unknown_or_missing_effort_stays_available_to_model_policy_fallback(profile_result):
    assert "effectiveEffort" not in profile_result["unknown"]


def test_every_real_agent_resolves_with_core_subset_of_declared_skills(profile_result):
    assert len(profile_result["allAgents"]) == 23
    for name, plan in profile_result["allAgents"].items():
        declared = set(plan["preloadSkillIds"]) | set(plan["onDemandSkillIds"])
        assert declared, name
        assert set(plan["preloadSkillIds"]).isdisjoint(plan["onDemandSkillIds"]), name


def test_output_family_covers_every_real_agent(profile_result):
    families = {"implementation", "review", "audit", "advisory"}
    for name, plan in profile_result["allAgents"].items():
        assert plan["outputFamily"] in families, name


def test_retry_marker_accepts_only_closed_reasons_on_a_standalone_final_line(profile_result):
    assert profile_result["retry"] == [
        "missing-domain-guidance",
        "cross-domain-ambiguity",
        None,
        None,
        None,
    ]


def test_economy_parent_guidance_preserves_workflow_and_review_gates(profile_result):
    guidance = profile_result["guidance"]
    assert "workflow-delegated-implementation" in guidance
    assert "reviewer" in guidance
    assert "Verify" in guidance
    assert "Review" in guidance

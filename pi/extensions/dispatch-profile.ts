/** Pure profile policy for quota-aware Pi subagent dispatch. */
import { isKnownEffort, type Effort } from "./model-policy.ts";

export const DISPATCH_PROFILES = ["economy", "balanced", "full"] as const;
export type DispatchProfile = (typeof DISPATCH_PROFILES)[number];

export type OutputFamily = "implementation" | "review" | "audit" | "advisory";

export const FULL_PRELOAD_RETRY_REASONS = [
  "missing-domain-guidance",
  "cross-domain-ambiguity",
  "output-contract-conflict",
] as const;
export type FullPreloadRetryReason = (typeof FULL_PRELOAD_RETRY_REASONS)[number];

export interface DispatchProfilePlan {
  readonly profile: DispatchProfile;
  readonly effectiveEffort: string | undefined;
  readonly preloadSkillIds: readonly string[];
  readonly onDemandSkillIds: readonly string[];
  readonly outputFamily: OutputFamily;
  readonly outputCapChars: number;
  readonly allowFullPreloadRetry: boolean;
}

const PROTECTED_AGENTS = new Set([
  "architect",
  "migrator",
  "security-auditor",
  "senior-engineer",
]);

const REVIEWER_CORE_SKILLS = new Set([
  "swe-workbench:principle-code-review",
  "swe-workbench:principle-clean-code",
  "swe-workbench:principle-security",
  "swe-workbench:principle-testing",
]);

const LOWER_EFFORT: Readonly<Record<Effort, Effort>> = {
  low: "low",
  medium: "low",
  high: "medium",
  xhigh: "high",
  max: "xhigh",
};

const OUTPUT_FAMILIES: Readonly<Record<string, OutputFamily>> = {
  "accessibility-auditor": "audit",
  "alignment-assessor": "audit",
  architect: "advisory",
  auditor: "audit",
  "code-impl": "implementation",
  "conflict-resolver": "implementation",
  "contributor-auditor": "audit",
  debugger: "implementation",
  "dependency-auditor": "audit",
  "e2e-test-verifier": "audit",
  "e2e-test-writer": "implementation",
  migrator: "implementation",
  "performance-tuner": "audit",
  "product-designer": "advisory",
  "product-manager": "advisory",
  "redundancy-assessor": "audit",
  refactorer: "implementation",
  reviewer: "review",
  "security-auditor": "audit",
  "senior-engineer": "advisory",
  "tech-writer": "advisory",
  "test-reviewer": "review",
  "test-writer": "implementation",
};

function outputFamilyFor(agent: string): OutputFamily {
  const family = OUTPUT_FAMILIES[agent];
  return family ?? "implementation";
}

function outputCapFor(profile: DispatchProfile): number {
  switch (profile) {
    case "economy":
      return 8_000;
    case "balanced":
      return 16_000;
    case "full":
      return 32_000;
  }
}

function effectiveEffort(profile: DispatchProfile, agent: string, declaredEffort: string | undefined): string | undefined {
  if (!isKnownEffort(declaredEffort)) return declaredEffort;
  if (profile === "full") return "max";
  if (profile === "economy" && !PROTECTED_AGENTS.has(agent)) return LOWER_EFFORT[declaredEffort];
  return declaredEffort;
}

function preloadPlan(profile: DispatchProfile, agent: string, skillIds: readonly string[]) {
  if (profile !== "economy" || agent !== "reviewer" || PROTECTED_AGENTS.has(agent)) {
    return { preloadSkillIds: skillIds, onDemandSkillIds: [] as readonly string[] };
  }
  return {
    preloadSkillIds: skillIds.filter((id) => REVIEWER_CORE_SKILLS.has(id)),
    onDemandSkillIds: skillIds.filter((id) => !REVIEWER_CORE_SKILLS.has(id)),
  };
}

/** Resolves a reviewed profile without selecting a provider, model ID, or credential. */
export function resolveDispatchProfile(params: {
  readonly profile: DispatchProfile;
  readonly agent: string;
  readonly declaredEffort: string | undefined;
  readonly declaredSkillIds: readonly string[];
}): DispatchProfilePlan {
  const { profile, agent, declaredEffort, declaredSkillIds } = params;
  const preloads = preloadPlan(profile, agent, declaredSkillIds);
  return {
    profile,
    effectiveEffort: effectiveEffort(profile, agent, declaredEffort),
    ...preloads,
    outputFamily: outputFamilyFor(agent),
    outputCapChars: outputCapFor(profile),
    // A retry only restores guidance when Economy actually withheld it.
    allowFullPreloadRetry: preloads.onDemandSkillIds.length > 0,
  };
}

/** Reads a semantic retry request only when it is the exact final output line. */
export function parseFullPreloadRetry(text: string): FullPreloadRetryReason | undefined {
  const normalized = text.replace(/\r\n/g, "\n").trimEnd();
  const match = /(?:^|\n)SWB_FULL_PRELOAD_RETRY: ([a-z-]+)$/.exec(normalized);
  if (match === null) return undefined;
  const reason = match[1];
  return (FULL_PRELOAD_RETRY_REASONS as readonly string[]).includes(reason)
    ? reason as FullPreloadRetryReason
    : undefined;
}

/** States the bounded response shape injected into a child prompt. */
export function outputContract(family: OutputFamily, capChars: number, allowRetry: boolean): string {
  const shape: Readonly<Record<OutputFamily, string>> = {
    implementation: "status, files changed, verification evidence, concerns, and blockers",
    review: "severity counts, actionable findings, and the required review decision footer",
    audit: "finding counts, highest-risk findings, and evidence anchors",
    advisory: "recommendation, evidence anchors, risks, and unresolved decisions",
  };
  const retry = allowRetry
    ? ` If full domain guidance is required, end with exactly SWB_FULL_PRELOAD_RETRY: <${FULL_PRELOAD_RETRY_REASONS.join("|")}>.`
    : "";
  return `Return ${shape[family]}. Keep the response within ${capChars} characters.${retry}`;
}

/** Parent-only policy guidance; it never changes the shared agent frontmatter contract. */
export function parentProfileGuidance(profile: DispatchProfile): string {
  if (profile !== "economy") {
    return "Balanced and Full retain normal swe-workbench workflow selection; do not alter Verify or Review gates.";
  }
  return [
    "Economy changes dispatch strategy, not workflow guarantees.",
    "Implement small and medium changes in the parent; use workflow-delegated-implementation only when its existing scope gate is met.",
    "Never skip command-mandated consultations, Verify, or the independent reviewer in Review.",
  ].join(" ");
}

/**
 * Phase policy: swe-workbench's two-mode plan/execute contract (docs/pi-plan-mode.md)
 * as plain data and pure functions.
 *
 * Layer: domain, same SDK-free posture as model-policy.ts and agent-spec.ts — no Pi SDK import,
 * not even as a type. The adapter consuming this module owns everything that touches Pi:
 * reading the armed command's prompt, resolving paths, and acting on isMutationBlocked's verdict.
 */

import type { ModelTier } from "./model-policy.ts";
import { MODEL_POLICY, isSupportedProvider } from "./model-policy.ts";

/** The line a plan-group commands/*.md body carries to declare plan phase; extractPhase scans
 *  for it and tests/test_pi_contract.py pins it to the same literal the command files carry. */
export const PHASE_MARKER = "<!-- swb-phase: plan -->";

export type Phase = "plan" | "execute";

/** Marker seen -> "plan"; approval also flips the session to "execute"; no marker -> "disarmed". */
export type PhaseState = "disarmed" | "plan" | "execute";

/** `"plan"` iff PHASE_MARKER appears as a whole line of `prompt` (the armed command's body). */
export function extractPhase(prompt: string): Phase | undefined {
  return prompt.split(/\r?\n/).includes(PHASE_MARKER) ? "plan" : undefined;
}

/** Where the agent persists plans, relative to the repo root — the one directory the plan-phase
 *  mutation gate leaves writable, so a lost session never loses a drafted plan. */
export const PLANS_RELATIVE_DIR = "docs/superpowers/plans";

/** Pi's file-mutation tool names (lowercase — Edit/Write are the Claude names, not Pi's). */
export const BLOCKED_TOOLS_IN_PLAN: ReadonlySet<string> = new Set(["edit", "write"]);

/** True iff the plan-phase gate blocks this call: plan phase + a blocked tool + a target outside
 *  `plansDir`. Containment is lexical — equality or a separator-suffixed prefix — and stays
 *  correct without normalization because both arguments are absolute paths the adapter has
 *  already resolved. */
export function isMutationBlocked(
  toolName: string,
  targetPath: string,
  plansDir: string,
  state: PhaseState,
): boolean {
  if (state !== "plan") return false;
  if (!BLOCKED_TOOLS_IN_PLAN.has(toolName)) return false;
  return targetPath !== plansDir && !targetPath.startsWith(plansDir + "/");
}

/** Preference-ordered model ids for the phase's governing tier — plan drafts on opus, execute
 *  runs on sonnet — from MODEL_POLICY, the single source of truth. Multi-id rows are fallback
 *  lists, so the full order is returned and the adapter walks candidates via
 *  modelRegistry.find; a first-id-only return would strand the phase flip on a dead id. Ids
 *  ONLY, never a thinking level: setThinkingLevel on flip would silently change session
 *  effort (§4 of docs/pi-plan-mode.md defers that). `undefined` = unsupported
 *  provider — the caller notifies and stays on the current model. */
export function resolvePhaseModels(
  provider: string,
  phase: Phase,
): readonly string[] | undefined {
  if (!isSupportedProvider(provider)) return undefined;
  const tier: ModelTier = phase === "plan" ? "opus" : "sonnet";
  const { model } = MODEL_POLICY[provider][tier];
  return typeof model === "string" ? [model] : model;
}

const PLAN_SECTION = `## Plan phase

Plan phase is active: author the implementation plan — do not implement it.

- edit/write is allowed ONLY under ${PLANS_RELATIVE_DIR}/. Persist the plan there in
  superpowers:writing-plans format as you draft it, so a lost session never loses the plan.
- Every other edit/write is blocked.
- Do not mutate other files via bash to work around the block.
- Call submit_plan when the plan is complete.`;

const EXECUTE_SECTION = `## Execute phase

Execute phase is active: the approved plan governs, and edit/write is allowed.

- If the approved plan is not yet on disk, persist it verbatim under ${PLANS_RELATIVE_DIR}/
  first; then execute it task-by-task (superpowers:executing-plans or
  superpowers:subagent-driven-development).
- The Workflow section's five-phase lifecycle (Branch → Implement → Verify → Review → Deliver)
  belongs entirely to this phase — it starts only after plan approval.`;

/** The system-prompt section each phase injects: stable prose per state, `""` when disarmed
 *  (nothing is injected — the session behaves as if the feature did not exist). */
export function phaseSystemSection(state: PhaseState): string {
  switch (state) {
    case "plan":
      return PLAN_SECTION;
    case "execute":
      return EXECUTE_SECTION;
    case "disarmed":
      return "";
  }
}

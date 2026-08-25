/**
 * Composes model-policy.ts's resolveDispatch with the real Pi ExtensionContext for subagent.ts's
 * `task` tool. Split from subagent.ts at the line cap (same reason task-call-line.ts was split
 * earlier) — see that file's header for the layering this repo uses.
 *
 * Type-only Pi SDK reference (ExtensionContext), consistent with every other adapter file's
 * stripper-safe posture — see docs/plugin-platform-decisions.md §9.
 */
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { AgentSpec } from "./agent-spec.ts";
import {
  type Effort,
  type FallbackReason,
  type ModelCandidate,
  type ModelTier,
  type ParentThinkingLevel,
  resolveDispatch,
} from "./model-policy.ts";
import { sanitizeAgentId } from "./task-call-line.ts";

type PoolSource = "scoped" | "available";

export interface DispatchDetails {
  readonly agent: string;
  readonly tier: ModelTier | undefined;
  readonly portableEffort: Effort | undefined;
  readonly model: string | undefined;
  readonly thinking: ParentThinkingLevel | undefined;
  readonly policySource: "model-policy" | "parent-fallback" | undefined;
  readonly poolSource: PoolSource | undefined;
  readonly fallbackReason: FallbackReason | undefined;
}

export interface TargetDispatch {
  readonly model: { provider: string; id: string } | undefined;
  readonly thinking: ParentThinkingLevel | undefined;
  readonly details: DispatchDetails;
  readonly warning: string | undefined;
}

/** Decides which model (and thinking level) to dispatch the child with, via model-policy.ts's
 *  resolveDispatch — exact id equality against the candidate pool, never a substring or
 *  shortest-match heuristic. Undefined `ctx.model` -> both flags omitted (today's
 *  omit-the-flag-entirely fallback; there is no parent model to fall back to). Otherwise: an
 *  unrecognized/missing `spec.model` tier, an unrecognized/missing `spec.effort`, a provider with
 *  no MODEL_POLICY row, or no available candidate matching the resolved id all degrade to the
 *  parent's own active model and thinking level unchanged, carrying a structured
 *  `fallbackReason` for `details.fallbackReason` and a `warning` string for the caller to surface
 *  — this function never throws. Candidates come from `ctx.scopedModels` when the session is
 *  scoped (`--models`/`enabledModels`) — an explicit session-level restriction that resolution
 *  must respect, not bypass — and fall back to the full `ctx.modelRegistry.getAvailable()`
 *  catalog only when no scoping is configured (`scopedModels` is documented as empty in that
 *  case). */
export function resolveTargetDispatch(
  ctx: ExtensionContext,
  agent: string,
  spec: Pick<AgentSpec, "model" | "effort">,
): TargetDispatch {
  if (!ctx.model) {
    return {
      model: undefined,
      thinking: undefined,
      details: {
        agent,
        tier: undefined,
        portableEffort: undefined,
        model: undefined,
        thinking: undefined,
        policySource: undefined,
        poolSource: undefined,
        fallbackReason: undefined,
      },
      warning: undefined,
    };
  }

  const poolSource: PoolSource = ctx.scopedModels.length > 0 ? "scoped" : "available";
  const pool = poolSource === "scoped" ? ctx.scopedModels.map((sm) => sm.model) : ctx.modelRegistry.getAvailable();
  const candidates: ModelCandidate[] = pool
    .filter((m) => m.provider === ctx.model!.provider)
    .map((m) => ({ provider: m.provider, id: m.id }));

  const result = resolveDispatch({
    parent: {
      provider: ctx.model.provider,
      id: ctx.model.id,
      thinking: ctx.thinkingLevel,
    },
    tier: spec.model,
    effort: spec.effort,
    candidates,
  });

  const details: DispatchDetails = {
    agent,
    tier: result.tier,
    portableEffort: result.portableEffort,
    model: `${result.model.provider}/${result.model.id}`,
    thinking: result.thinking,
    policySource: result.policySource,
    poolSource,
    fallbackReason: result.fallbackReason,
  };

  // No "task: " prefix here — this string is reused standalone (ctx.ui.notify), prefixed with
  // "[swe-workbench] " (tool result content), and suffixed onto the "task: ..." exit-error
  // message on a failed dispatch (subagent.ts) — each call site supplies its own framing.
  const warning = result.fallbackReason
    ? `model-dispatch policy degraded to the parent model (${details.model}) for agent ` +
      `"${sanitizeAgentId(agent)}" — reason: ${result.fallbackReason}`
    : undefined;

  return { model: result.model, thinking: result.thinking, details, warning };
}

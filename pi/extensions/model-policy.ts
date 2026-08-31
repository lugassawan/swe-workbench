/**
 * Model-dispatch policy: maps a Claude-Code-style tier name (an agent's `model:` frontmatter
 * value — haiku/sonnet/opus) plus a portable reasoning effort (an agent's `effort:` frontmatter
 * value) to an exact Pi model id and an effective thinking level, per provider.
 *
 * Layer: domain, same SDK-free posture as agent-spec.ts and tool-vocab.ts — only plain data and
 * pure functions here, no Pi SDK import, not even as a type. subagent.ts supplies real SDK
 * `Model` objects (mapped to the local ModelCandidate shape) and owns everything that actually
 * queries ctx.modelRegistry.
 *
 * Model selection here is EXACT id equality, never a substring or shortest-match heuristic (see
 * docs/plugin-platform-decisions.md §9 for why the earlier substring-match design was replaced) —
 * a catalog reshuffle or a new sibling id can never silently re-point a tier at the wrong model.
 */

/** The only `model:` values agents/*.md frontmatter uses today (ratcheted against the live
 *  inventory in tests/test_pi_contract.py's MODEL_TIERS, the same pattern as TOOL_TOKENS). */
export const KNOWN_MODEL_TIERS = ["haiku", "sonnet", "opus"] as const;
export type ModelTier = (typeof KNOWN_MODEL_TIERS)[number];

export function isKnownModelTier(value: string | undefined): value is ModelTier {
  return value !== undefined && (KNOWN_MODEL_TIERS as readonly string[]).includes(value);
}

/** The only `effort:` values agents/*.md frontmatter uses today (ratcheted against the live
 *  inventory in tests/test_pi_contract.py's EFFORTS, the same pattern as MODEL_TIERS). Portable
 *  across harnesses: Claude Code reads this directly as reasoning effort; Pi resolves it (via
 *  MODEL_POLICY) into a provider-effective thinking level. */
export const KNOWN_EFFORTS = ["low", "medium", "high", "xhigh", "max"] as const;
export type Effort = (typeof KNOWN_EFFORTS)[number];

export function isKnownEffort(value: string | undefined): value is Effort {
  return value !== undefined && (KNOWN_EFFORTS as readonly string[]).includes(value);
}

/** The providers this policy has a row for. Any other `ctx.model.provider` degrades to the
 *  parent's own current model — see resolveDispatch's `provider-unsupported` FallbackReason. */
export const SUPPORTED_PROVIDERS = ["anthropic", "openai-codex", "zai"] as const;
export type SupportedProvider = (typeof SUPPORTED_PROVIDERS)[number];

export function isSupportedProvider(value: string): value is SupportedProvider {
  return (SUPPORTED_PROVIDERS as readonly string[]).includes(value);
}

/** A subset of Pi's own `off | minimal | low | medium | high | xhigh | max` thinking-level
 *  vocabulary — this policy never emits `off` or `minimal` on the success path, since no agent's
 *  portable `effort:` maps to either. */
export type ThinkingLevel = "low" | "medium" | "high" | "xhigh" | "max";

/** The parent session's own thinking level as Pi reports it — the full 7-value vocabulary
 *  (ThinkingLevel is this policy's narrower 5-value subset). Forwarded verbatim on every
 *  fallback path, never pattern-matched, so `off`/`minimal` are real, reachable values here.
 *  Kept distinct from ThinkingLevel so dispatch-resolver.ts's call site never needs an
 *  unchecked narrowing cast. */
export type ParentThinkingLevel = ThinkingLevel | "off" | "minimal";

/** Structurally shaped like the Pi SDK's `Model<Api>` (provider/id) but NOT imported from it —
 *  this file stays SDK-free (see header). subagent.ts maps real SDK `Model` objects into this
 *  shape before calling resolveDispatch. */
export interface ModelCandidate {
  readonly provider: string;
  readonly id: string;
}

/** Portable effort passes straight through as the effective thinking level — the identity table
 *  seven of the nine (provider, tier) cells share below. */
const IDENTITY: Readonly<Record<Effort, ThinkingLevel>> = {
  low: "low",
  medium: "medium",
  high: "high",
  xhigh: "xhigh",
  max: "max",
};

/** Z.AI's `glm-5.3` serves both the opus and sonnet tier, so thinking level is the only axis
 *  left to keep opus's dispatch strictly deeper than sonnet's for the same nominal effort: this
 *  table shifts every effort UP by two rungs on the `[low, medium, high, xhigh, max]` ladder,
 *  clamped at `max` — reproducing the ticket-pinned `high -> max` translation (opus's default
 *  effort per DEFAULT_TIER_EFFORT is "high") while staying monotone and gapless over all five
 *  efforts. Per Z.AI's own spec, `glm-5.3` always reasons and genuinely supports `max` as one of
 *  its three real effort levels (`low`/`high`/`max`) — the pinned Pi SDK's bundled catalog entry
 *  for it now ships a real `thinkingLevelMap` for those three levels (see the pinned-catalog test
 *  in tests/test_pi_contract.py), so this nominal `high -> max` shift dispatches as genuine `max`
 *  thinking, no longer clamped down to `high` the way it was before that catalog bump.
 *  `medium`/`xhigh` aren't directly supported and still round up to the nearest real level
 *  (`high`/`max`) — that narrower nominal-vs-effective divergence is expected and doesn't need
 *  runtime handling here (see this file's header). */
const ZAI_OPUS_THINKING: Readonly<Record<Effort, ThinkingLevel>> = {
  low: "high",
  medium: "xhigh",
  high: "max",
  xhigh: "max",
  max: "max",
};

/** Shifts every effort DOWN by one rung on the same ladder, clamped at `low` — reproducing the
 *  ticket-pinned `xhigh -> high` translation (sonnet's default effort is "xhigh") so zai's sonnet
 *  dispatch stays strictly shallower than its opus dispatch for the same nominal effort. */
const ZAI_SONNET_THINKING: Readonly<Record<Effort, ThinkingLevel>> = {
  low: "low",
  medium: "low",
  high: "medium",
  xhigh: "high",
  max: "xhigh",
};

interface TierPolicy {
  /** Exact catalog id — never a pattern. */
  readonly model: string;
  /** Exhaustive portable-effort -> provider-effective-thinking-level map, all 5 efforts. */
  readonly thinking: Readonly<Record<Effort, ThinkingLevel>>;
}

/** One cell per (provider, tier). See ZAI_OPUS_THINKING/ZAI_SONNET_THINKING above for why zai's
 *  two rows diverge, and docs/cost-tiers.md's "On the Pi Coding Agent" section for the full 3x3
 *  matrix. */
export const MODEL_POLICY: Readonly<Record<SupportedProvider, Readonly<Record<ModelTier, TierPolicy>>>> = {
  anthropic: {
    opus: { model: "claude-opus-5", thinking: IDENTITY },
    sonnet: { model: "claude-sonnet-5", thinking: IDENTITY },
    haiku: { model: "claude-haiku-4-5", thinking: IDENTITY },
  },
  "openai-codex": {
    opus: { model: "gpt-5.6-sol", thinking: IDENTITY },
    sonnet: { model: "gpt-5.6-terra", thinking: IDENTITY },
    haiku: { model: "gpt-5.6-luna", thinking: IDENTITY },
  },
  zai: {
    opus: { model: "glm-5.3", thinking: ZAI_OPUS_THINKING },
    sonnet: { model: "glm-5.3", thinking: ZAI_SONNET_THINKING },
    haiku: { model: "glm-5.2-highspeed", thinking: IDENTITY },
  },
};

/** Default portable effort per tier — what every agents/*.md declares today. Feeding this
 *  through MODEL_POLICY reproduces docs/cost-tiers.md's 3x3 default matrix exactly; that
 *  identity is the matrix test (tests/test_pi_contract.py), so the matrix has one source of
 *  truth, not two. */
export const DEFAULT_TIER_EFFORT: Readonly<Record<ModelTier, Effort>> = {
  opus: "high",
  sonnet: "xhigh",
  haiku: "high",
};

/** Every way resolveDispatch degrades to the parent's own model/thinking level unchanged. */
export const KNOWN_FALLBACK_REASONS = [
  "provider-unsupported",
  "tier-unknown",
  "effort-unknown",
  "model-unavailable",
] as const;
export type FallbackReason = (typeof KNOWN_FALLBACK_REASONS)[number];

export interface DispatchParent {
  readonly provider: string;
  readonly id: string;
  /** The parent session's own current thinking level, used unchanged on every fallback path. */
  readonly thinking: ParentThinkingLevel | undefined;
}

export interface DispatchResult {
  readonly model: { readonly provider: string; readonly id: string };
  /** A real ThinkingLevel on the success path (from a TierPolicy's own thinking map); the
   *  parent's own (possibly off/minimal) ParentThinkingLevel unchanged on any fallback path. */
  readonly thinking: ParentThinkingLevel | undefined;
  readonly tier: ModelTier | undefined;
  readonly portableEffort: Effort | undefined;
  readonly policySource: "model-policy" | "parent-fallback";
  readonly fallbackReason: FallbackReason | undefined;
}

/** Resolves a Claude-Code-style (tier, effort) pair to an exact model id + effective thinking
 *  level via MODEL_POLICY. `candidates` should already be filtered to one provider (subagent.ts
 *  filters to the parent session's active provider) — model selection is exact id equality
 *  against `candidates`, never a substring or shortest-match heuristic, so a neighbouring tier's
 *  id is structurally unreachable. Every failure path returns the parent's own model and
 *  thinking level unchanged, with a structured `fallbackReason` — this function never throws.
 *  Pure. */
export function resolveDispatch(params: {
  readonly parent: DispatchParent;
  readonly tier: string | undefined;
  readonly effort: string | undefined;
  readonly candidates: readonly ModelCandidate[];
}): DispatchResult {
  const { parent, tier, effort, candidates } = params;

  const fallback = (fallbackReason: FallbackReason): DispatchResult => ({
    model: { provider: parent.provider, id: parent.id },
    thinking: parent.thinking,
    tier: isKnownModelTier(tier) ? tier : undefined,
    portableEffort: isKnownEffort(effort) ? effort : undefined,
    policySource: "parent-fallback",
    fallbackReason,
  });

  if (!isSupportedProvider(parent.provider)) return fallback("provider-unsupported");
  if (!isKnownModelTier(tier)) return fallback("tier-unknown");
  if (!isKnownEffort(effort)) return fallback("effort-unknown");

  const policy = MODEL_POLICY[parent.provider][tier];
  const match = candidates.find((c) => c.provider === parent.provider && c.id === policy.model);
  if (!match) return fallback("model-unavailable");

  return {
    model: { provider: match.provider, id: match.id },
    thinking: policy.thinking[effort],
    tier,
    portableEffort: effort,
    policySource: "model-policy",
    fallbackReason: undefined,
  };
}

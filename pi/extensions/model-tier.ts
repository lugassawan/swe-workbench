/**
 * Model-tier resolution: maps a Claude-Code-style tier name (an agent's `model:` frontmatter
 * value — haiku/sonnet/opus) to a concrete Pi model, by name, per provider.
 *
 * Layer: domain, same SDK-free posture as agent-spec.ts and tool-vocab.ts — only plain data and
 * pure functions here, no Pi SDK import, not even as a type. subagent.ts supplies real SDK
 * `Model` objects (mapped to the local ModelCandidate shape) and owns everything that actually
 * queries ctx.modelRegistry.
 */

/** The only `model:` values agents/*.md frontmatter uses today (ratcheted against the live
 *  inventory in tests/test_pi_contract.py's MODEL_TIERS, the same pattern as TOOL_TOKENS). */
export const KNOWN_MODEL_TIERS = ["haiku", "sonnet", "opus"] as const;
export type ModelTier = (typeof KNOWN_MODEL_TIERS)[number];

export function isKnownModelTier(value: string | undefined): value is ModelTier {
  return value !== undefined && (KNOWN_MODEL_TIERS as readonly string[]).includes(value);
}

/** Structurally shaped like the Pi SDK's `Model<Api>` (provider/id) but NOT imported from it —
 *  this file stays SDK-free (see header). subagent.ts maps real SDK `Model` objects into this
 *  shape before calling resolveModelForTier. */
export interface ModelCandidate {
  readonly provider: string;
  readonly id: string;
}

/** Per-provider tier -> model-id-substring pattern(s), by name — not cost. Hardcoded editorial
 *  content, not scanned from disk or a runtime-editable settings file: see
 *  docs/plugin-platform-decisions.md §9 for the full trust-boundary rationale (this table lives
 *  in reviewed source, resolution never leaves the parent's own provider/authenticated models).
 *  Multiple patterns for one tier (zai's haiku row) are tried in priority order. */
export const MODEL_TIER_TABLE: Readonly<Record<string, Readonly<Record<ModelTier, readonly string[]>>>> = {
  anthropic: {
    opus: ["opus"],
    sonnet: ["sonnet"],
    haiku: ["haiku"],
  },
  "openai-codex": {
    opus: ["sol"],
    sonnet: ["terra"],
    haiku: ["luna"],
  },
  zai: {
    opus: ["glm-5.3"],
    sonnet: ["glm-5.3"],
    haiku: ["glm-5.2-highspeed", "glm-5.2"],
  },
};

/** Among candidates whose id contains `pattern`, returns the one with the SHORTEST id —
 *  disambiguates real-world catalog collisions where a bare tier pattern (e.g. "opus") also
 *  matches older dated/versioned siblings of the intended model (e.g. Anthropic's bundled
 *  catalog carries "claude-opus-4-5", "claude-opus-4-5-20251101", "claude-opus-4-6",
 *  "claude-opus-4-7", and "claude-opus-4-8" alongside the intended "claude-opus-5" — all six
 *  contain the substring "opus", in catalog (not chronological) order, so a naive first-match
 *  would silently resolve to a stale, non-flagship snapshot). The intended bare id is always the
 *  shortest match: any dated/versioned variant is strictly the bare id plus extra suffix
 *  characters, so it can never be shorter. Undefined if no candidate matches. */
function shortestMatch(pattern: string, candidates: readonly ModelCandidate[]): ModelCandidate | undefined {
  return candidates
    .filter((c) => c.id.includes(pattern))
    .reduce<ModelCandidate | undefined>(
      (best, candidate) => (best === undefined || candidate.id.length < best.id.length ? candidate : best),
      undefined,
    );
}

/** Resolves a Claude-Code-style model tier to one of `candidates` via MODEL_TIER_TABLE, by
 *  name — never by cost or capability inference. `candidates` should already be filtered to one
 *  provider (subagent.ts filters to the parent session's active provider); `provider` selects
 *  which row of MODEL_TIER_TABLE to use. Returns undefined when the provider has no table entry,
 *  the tier has no pattern for it, or none of its patterns match an available candidate — the
 *  caller is expected to fall back to the parent's current model in every undefined case. Pure. */
export function resolveModelForTier(
  provider: string,
  tier: ModelTier,
  candidates: readonly ModelCandidate[],
): ModelCandidate | undefined {
  const patterns = MODEL_TIER_TABLE[provider]?.[tier];
  if (!patterns) return undefined;
  for (const pattern of patterns) {
    const match = shortestMatch(pattern, candidates);
    if (match) return match;
  }
  return undefined;
}

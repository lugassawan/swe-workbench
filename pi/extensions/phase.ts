/**
 * Plan-phase adapter (docs/decisions-pi-plan-mode.md): arms plan/execute when an armed
 * command's expanded prompt carries PHASE_MARKER, flips the session to the phase's governing
 * model, injects the per-state system section, and enforces the plans-dir mutation gate on
 * edit/write — the Pi-touching half of the SDK-free policy in phase-policy.ts. Handlers
 * observe and block, never replace a tool, and self-wrap fallible bodies (the event runner
 * has no try/catch around handler bodies, unlike emitUserBash).
 */
import { resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  extractPhase,
  isMutationBlocked,
  phaseSystemSection,
  PLANS_RELATIVE_DIR,
  resolvePhaseModels,
  type PhaseState,
} from "./phase-policy.ts";

/** Per-state dedup marker (index.ts's PREAMBLE_MARKER pattern): the suffix is the phase, so a
 *  state transition appends the new section while re-runs in the same state never duplicate. */
const phaseSectionMarker = (state: PhaseState): string => `<!-- swb-phase-section:${state} -->`;

const BLOCK_REASON =
  "Plan phase is active — edit/write are blocked outside docs/superpowers/plans until the " +
  "plan is approved. Writing the plan file itself is allowed. Call submit_plan with the " +
  "complete plan when ready; user approval switches this session to the execution model. " +
  "Do not mutate other files via bash during plan phase.";

export function registerPhase(pi: ExtensionAPI, root: string): void {
  let phase: PhaseState = "disarmed";
  // True only while our own setModel call is firing its model_select event, so that event
  // does not read as a user override and disarm the phase we just armed.
  let ourFlip = false;
  const plansDir = resolve(root, PLANS_RELATIVE_DIR);

  // Best-effort flip on arming: an unusable provider/candidate notifies and stays on the
  // current model — a failed flip must never un-arm the phase (the gate still holds).
  async function flipToPlanModel(ctx: ExtensionContext): Promise<void> {
    const provider = ctx.model?.provider;
    if (provider === undefined) {
      ctx.ui.notify(
        "swe-workbench: plan phase armed, but the session has no current model to resolve a " +
          "plan-phase model from — staying on the current model.",
        "warning",
      );
      return;
    }
    const candidates = resolvePhaseModels(provider, "plan");
    if (candidates === undefined) {
      ctx.ui.notify(
        `swe-workbench: plan phase armed on ${provider}, which has no plan-phase model policy ` +
          "— staying on the current model.",
        "warning",
      );
      return;
    }
    const model = candidates
      .map((id) => ctx.modelRegistry.find(provider, id))
      .find((found) => found !== undefined);
    if (model === undefined) {
      ctx.ui.notify(
        `swe-workbench: plan phase armed on ${provider}, but none of its plan-phase models ` +
          `(${candidates.join(", ")}) are available — staying on the current model.`,
        "warning",
      );
      return;
    }
    ourFlip = true;
    try {
      if (await pi.setModel(model)) return;
      ctx.ui.notify(
        `swe-workbench: plan phase armed, but activating ${provider}/${model.id} failed — ` +
          "staying on the current model.",
        "warning",
      );
    } finally {
      // setModel awaits its model_select emit before resolving, so this reset only matters
      // when no event fired (model unchanged / refused) — a stale ourFlip would swallow the next disarm.
      ourFlip = false;
    }
  }

  pi.on("before_agent_start", async (event, ctx) => {
    try {
      // Plan phase never arms headless: ctx.ui.notify has no surface there, and a `-p` run
      // must behave as if the feature did not exist.
      if (!ctx.hasUI) return undefined;
      if (phase === "disarmed" && extractPhase(event.prompt) === "plan") {
        phase = "plan";
        await flipToPlanModel(ctx);
      }
      const section = phaseSystemSection(phase);
      if (section === "") return undefined;
      const marker = phaseSectionMarker(phase);
      if (event.systemPrompt.includes(marker)) return undefined;
      return { systemPrompt: `${event.systemPrompt}\n\n${marker}\n\n${section}` };
    } catch {
      return undefined;
    }
  });

  // Registered after registerGuards by index.ts call order: the gate observes calls the
  // security guards already vetted; isMutationBlocked filters tool names, so only `path` is read here.
  pi.on("tool_call", (event, ctx) => {
    try {
      const target = (event.input as { path?: unknown }).path;
      if (typeof target !== "string" || target === "") return undefined;
      if (!isMutationBlocked(event.toolName, resolve(ctx.cwd, target), plansDir, phase)) {
        return undefined;
      }
      return { block: true, reason: BLOCK_REASON, terminate: true };
    } catch {
      return undefined;
    }
  });

  // A user-driven model change (set/cycle) abandons the phase; "restore" does not. ourFlip
  // marks the event our own flip just caused, so arming survives it.
  pi.on("model_select", (event) => {
    if (!ourFlip && (event.source === "set" || event.source === "cycle")) {
      phase = "disarmed";
    }
    ourFlip = false;
  });

  // Phase state is per-session: a new/resumed/reloaded session, or a switch to another one,
  // reverts to disarmed until an armed command's prompt arms it again.
  pi.on("session_start", () => {
    phase = "disarmed";
    ourFlip = false;
  });

  pi.on("session_before_switch", () => {
    phase = "disarmed";
    ourFlip = false;
  });
}

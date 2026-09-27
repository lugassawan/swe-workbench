/**
 * Plan-phase adapter (docs/decisions-pi-plan-mode.md): arms plan/execute when an armed
 * command's prompt carries PHASE_MARKER, flips the session to the phase's governing model,
 * injects the per-state system section, enforces the plans-dir mutation gate, and registers
 * submit_plan — the approval transition to execute. The Pi-touching half of phase-policy.ts;
 * submit_plan's schema and TUI picker live in phase-dialog.ts. Handlers observe and block,
 * never replace a tool, and self-wrap fallible bodies (the event runner adds no try/catch).
 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resolve } from "node:path";
import { approvalChoice, SUBMIT_PLAN_PARAMS_SCHEMA } from "./phase-dialog.ts";
import {
  extractPhase,
  isMutationBlocked,
  phaseSystemSection,
  PLANS_RELATIVE_DIR,
  resolvePhaseModels,
  type Phase,
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

/** Drops every phase-section block whose state is not `keep`: a state change between turns
 *  (approval, user-override disarm) leaves the previous state's marker+section riding the
 *  carried systemPrompt, and its prose ("edit/write is blocked…") must not govern a state it
 *  no longer describes. Matches the exact literals this module appends, so adjacent content
 *  from other handlers is never touched. */
function stripStaleSections(systemPrompt: string, keep: PhaseState): string {
  let cleaned = systemPrompt;
  for (const state of ["plan", "execute"] as const) {
    if (state !== keep) cleaned = cleaned.split(`\n\n${phaseSectionMarker(state)}\n\n${phaseSystemSection(state)}`).join("");
  }
  return cleaned;
}

export function registerPhase(pi: ExtensionAPI, root: string): void {
  let phase: PhaseState = "disarmed";
  // True only while our own setModel call is firing its model_select event, so that event
  // does not read as a user override and disarm the phase we just armed.
  let ourFlip = false;
  const plansDir = resolve(root, PLANS_RELATIVE_DIR);

  /** Best-effort flip to the phase's governing model: an unusable provider/candidate notifies
   *  and stays on the current model — a failed flip must never un-arm the phase (the gate
   *  still holds). `subject` names the occasion in the warnings (arming vs approval) and
   *  `failTail` its degraded ending; returns the activated "provider/id" for the caller's
   *  transition copy, undefined when the flip degraded to a notify. */
  async function flipToPhaseModel(ctx: ExtensionContext, toPhase: Phase, subject: string, failTail: string): Promise<string | undefined> {
    const warn = (detail: string) =>
      ctx.ui.notify(`swe-workbench: ${subject} ${detail} — ${failTail}.`, "warning");
    const provider = ctx.model?.provider;
    if (provider === undefined) {
      warn(`but the session has no current model to resolve a ${toPhase}-phase model from`);
      return undefined;
    }
    const candidates = resolvePhaseModels(provider, toPhase);
    if (candidates === undefined) {
      warn(`on ${provider}, which has no ${toPhase}-phase model policy`);
      return undefined;
    }
    const model = candidates.map((id) => ctx.modelRegistry.find(provider, id)).find((found) => found !== undefined);
    if (model === undefined) {
      warn(`on ${provider}, but none of its ${toPhase}-phase models (${candidates.join(", ")}) are available`);
      return undefined;
    }
    ourFlip = true;
    try {
      if (await pi.setModel(model)) return `${provider}/${model.id}`;
      warn(`but activating ${provider}/${model.id} failed`);
    } catch {
      // setModel throwing must degrade to the same warn, not escape — an escaping throw gets
      // swallowed by before_agent_start's catch, silencing this warning and the section append.
      warn(`but activating ${provider}/${model.id} failed`);
    } finally {
      // setModel awaits its model_select emit before resolving, so this reset only matters
      // when no event fired (model unchanged / refused) — a stale ourFlip would swallow the next disarm.
      ourFlip = false;
    }
    return undefined;
  }

  pi.on("before_agent_start", async (event, ctx) => {
    try {
      // Plan phase never arms headless: ctx.ui.notify has no surface there, and a `-p` run
      // must behave as if the feature did not exist.
      if (!ctx.hasUI) return undefined;
      if (phase === "disarmed" && extractPhase(event.prompt) === "plan") {
        phase = "plan";
        await flipToPhaseModel(ctx, "plan", "plan phase armed", "staying on the current model");
      }
      const base = stripStaleSections(event.systemPrompt, phase);
      const section = phaseSystemSection(phase);
      if (section === "" || base.includes(phaseSectionMarker(phase))) {
        return base === event.systemPrompt ? undefined : { systemPrompt: base };
      }
      return { systemPrompt: `${base}\n\n${phaseSectionMarker(phase)}\n\n${section}` };
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
  // marks the event our own flip just caused (arming or approval), so the phase survives it.
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

  // Same Tier-2 kill switch as ask-user.ts/subagent.ts — gates tool registration only; the
  // arming/gate handlers above ARE the phase feature and stay on regardless.
  if (process.env.SWE_WORKBENCH_PI_TOOLS === "0") return;

  pi.registerTool({
    name: "submit_plan",
    label: "Submit Plan",
    description:
      "Submit the completed implementation plan for user approval. Approval switches this " +
      "session to the execute phase and its governing model; a revision returns the user's " +
      "feedback while plan phase stays armed.",
    promptSnippet:
      "submit_plan(plan): submit the finished plan for user approval — approval switches the " +
      "session to execution; revisions come back as feedback while plan phase stays armed.",
    promptGuidelines: ["Call submit_plan only with the complete final plan — it interrupts the user for a decision."],
    parameters: SUBMIT_PLAN_PARAMS_SCHEMA,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!ctx.hasUI) {
        throw new Error(
          "submit_plan needs an interactive session — run the phase-armed command in the TUI, or proceed without the plan gate.",
        );
      }
      const { plan } = params as unknown as { plan: string };
      let approved = false;
      let revision: string | undefined;
      if (ctx.mode === "tui") {
        const choice = await approvalChoice(ctx, signal);
        if (choice === undefined) {
          throw new Error(
            "submit_plan: the user dismissed the approval dialog without choosing — the plan is " +
              "not approved; check in with the user rather than assuming either way.",
          );
        }
        approved = choice === "Approve";
        if (!approved) {
          revision = await ctx.ui.editor("Revise plan", plan);
          if (revision === undefined || revision.trim() === "") {
            throw new Error(
              "submit_plan: the user closed the revision editor without revising — the plan is " +
                "not approved; check in with the user rather than assuming approval.",
            );
          }
        }
      } else {
        approved = await ctx.ui.confirm(
          "Approve plan?",
          "Approve the plan and switch this session to execution?",
          { signal },
        );
      }
      if (!approved) {
        // Neither outcome leaves plan phase — the gate keeps steering until a later call is approved.
        const text =
          revision !== undefined
            ? `Plan revision requested by user — plan phase stays active. Revised plan:\n\n${revision}`
            : "Plan rejected by user — plan phase stays active. Ask the user what to change, revise the plan, and call submit_plan again.";
        return { content: [{ type: "text" as const, text }], details: undefined };
      }
      // Approval disarms the gate before the flip so no setModel failure path can leave an
      // approved plan still mutation-blocked; the flip itself is best-effort.
      phase = "execute";
      const switchedTo = await flipToPhaseModel(ctx, "execute", "plan approved", "continuing on the current model");
      const transition =
        switchedTo !== undefined
          ? `Plan approved by user. Execution phase active — session model switched to ${switchedTo}.`
          : "Plan approved by user. Execution phase active — model switch failed — continuing on the current model.";
      return { content: [{ type: "text" as const, text: `${plan}\n\n${transition}` }], details: undefined };
    },
  });
}

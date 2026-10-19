import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import {
  composeSystemPrompt,
  listAgentNames,
  readAgentSpec,
  readSkillBody,
  skillDir,
  skillPath,
  translateToolTokens,
} from "./agent-spec.ts";
import { resolveTargetDispatch } from "./dispatch-resolver.ts";
import { outputContract, parseFullPreloadRetry, resolveDispatchProfile } from "./dispatch-profile.ts";
import type { DispatchProfileController } from "./dispatch-profile-ui.ts";
import { runSubagentAttempt } from "./subagent-attempt.ts";
import { capOutput, createSessionOutputStore } from "./subagent-output.ts";
import { parseNestedTaskJson } from "./subagent-json.ts";
import { TASK_TOOL_NAME, taskRenderCall, taskRenderResult, sanitizeAgentId } from "./task-call-line.ts";

export { composeTaskCallLine, composeTaskDispatchLine, renderTaskCall, renderTaskResult, TASK_TOOL_NAME } from "./task-call-line.ts";
export { capOutput } from "./subagent-output.ts";

interface TaskParams { agent: string; prompt: string; }

const TASK_PARAMS_SCHEMA = {
  type: "object",
  properties: {
    agent: { type: "string", description: "The agents/*.md agent id to dispatch, e.g. \"reviewer\" or \"debugger\"." },
    prompt: { type: "string", description: "The task/prompt to hand the dispatched agent." },
  },
  required: ["agent", "prompt"], additionalProperties: false,
} as ToolDefinition["parameters"];

/** Registers the profile-aware first-party child dispatcher. */
export function registerSubagent(pi: ExtensionAPI, root: string, profiles?: DispatchProfileController): void {
  if (process.env.SWE_WORKBENCH_PI_TOOLS === "0") return;
  // Direct consumers of this module predate profile registration; the extension entry point
  // always supplies the persistent controller. Keep their legacy balanced semantics intact.
  const profileController = profiles ?? {
    read: () => ({ kind: "configured" as const, profile: "balanced" as const }),
    ensureSelected: async () => ({ profile: "balanced" as const, selectedNow: false }),
  };
  const outputs = createSessionOutputStore();
  // Minimal direct-module test consumers predate extension events; Pi's real ExtensionAPI has on().
  if (typeof (pi as { on?: unknown }).on === "function") {
    pi.on("session_shutdown", () => { try { outputs.cleanup(); } catch { /* cleanup is best effort */ } });
  }

  pi.registerTool({
    name: TASK_TOOL_NAME,
    label: "Task",
    description: "Dispatch an agents/*.md agent as a nested Pi session with its declared tools and profile-aware guidance.",
    promptSnippet: 'task(agent, prompt): dispatch an agent as a nested session and get its final response.',
    promptGuidelines: ["Only dispatch an agent that exists under agents/*.md."],
    parameters: TASK_PARAMS_SCHEMA,
    renderCall: taskRenderCall,
    renderResult: taskRenderResult,
    async execute(_toolCallId, rawParams, signal, onUpdate, ctx) {
      const { agent, prompt } = rawParams as unknown as TaskParams;
      const available = listAgentNames(root);
      if (!available.includes(agent)) {
        throw new Error(`task: unknown agent "${sanitizeAgentId(agent)}" — available agents: ${available.join(", ")}`);
      }
      const selected = await profileController.ensureSelected(ctx);
      if (selected.selectedNow) {
        return {
          content: [{ type: "text" as const, text: `Dispatch profile saved as ${selected.profile}. Re-evaluate this task dispatch before starting a child.` }],
          details: { profile: selected.profile, selectedNow: true },
        };
      }

      const started = Date.now();
      const spec = readAgentSpec(root, agent);
      const plan = resolveDispatchProfile({
        profile: selected.profile, agent, declaredEffort: spec.effort, declaredSkillIds: spec.skillIds,
      });
      const toolNames = Array.from(new Set([...translateToolTokens(spec.tools), "ask_user_question"]));
      const preloaded = plan.preloadSkillIds.map((id) => ({ id, body: readSkillBody(root, id), dir: skillDir(root, id) }));
      const promptFor = (allSkills: boolean, retry: boolean) => composeSystemPrompt(
        spec,
        allSkills ? spec.skillIds.map((id) => ({ id, body: readSkillBody(root, id), dir: skillDir(root, id) })) : preloaded,
        {
          onDemandSkills: allSkills ? [] : plan.onDemandSkillIds.map((id) => ({ id, path: skillPath(root, id) })),
          outputContract: outputContract(plan.outputFamily, plan.outputCapChars, !retry && plan.allowFullPreloadRetry),
        },
      );
      const dispatch = resolveTargetDispatch(ctx, agent, { model: spec.model, effort: plan.effectiveEffort });
      onUpdate?.({ content: [], details: dispatch.details });
      if (dispatch.warning && ctx.hasUI) ctx.ui.notify(dispatch.warning, "warning");
      const input = (systemPrompt: string) => ({
        prompt, systemPrompt, toolNames,
        model: dispatch.model ? `${dispatch.model.provider}/${dispatch.model.id}` : undefined,
        thinking: dispatch.thinking, cwd: ctx.cwd, signal,
      });

      let first;
      try {
        first = await runSubagentAttempt(pi, input(promptFor(false, false)));
      } catch (err) {
        const suffix = dispatch.warning ? ` (${dispatch.warning})` : "";
        throw new Error(`${err instanceof Error ? err.message : String(err)}${suffix}`);
      }
      const retryReason = plan.allowFullPreloadRetry ? parseFullPreloadRetry(first.text) : undefined;
      let stdout = first.stdout;
      let parsed = first;
      if (retryReason) {
        if (signal?.aborted) throw new Error(`task: dispatched agent "${sanitizeAgentId(agent)}" was aborted before retry`);
        try {
          const second = await runSubagentAttempt(pi, input(promptFor(true, true)));
          stdout += `\n${second.stdout}`;
          // Parsing the concatenated streams preserves the final response and aggregates usage.
          parsed = { stdout, ...parseNestedTaskJson(stdout) };
        } catch (err) {
          const suffix = dispatch.warning ? ` (${dispatch.warning})` : "";
          throw new Error(`task: dispatched agent "${sanitizeAgentId(agent)}" retry failed — ${err instanceof Error ? err.message : String(err)}${suffix}`);
        }
      }
      const projection = outputs.project(parsed.text, plan.outputCapChars);
      const uncachedInput = parsed.usage.input;
      return {
        content: [
          ...(dispatch.warning ? [{ type: "text" as const, text: `[swe-workbench] ${dispatch.warning}` }] : []),
          { type: "text" as const, text: projection.text },
        ],
        details: {
          code: 0, killed: false, ...dispatch.details, profile: plan.profile,
          declaredEffort: spec.effort, effectiveEffort: plan.effectiveEffort,
          preloadSkillIds: plan.preloadSkillIds, onDemandSkillIds: plan.onDemandSkillIds,
          uncachedInput, outputChars: projection.totalChars, truncated: projection.truncated,
          artifactPresent: projection.fullOutputPath !== undefined, fullOutputPath: projection.fullOutputPath,
          retryReason, retried: retryReason !== undefined, durationMs: Date.now() - started,
        },
        usage: parsed.usage,
      };
    },
  });
}

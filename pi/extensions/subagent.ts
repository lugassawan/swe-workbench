/**
 * Registers `task`, a first-party subagent dispatcher: runs one of this plugin's agents/*.md
 * definitions as a nested `pi` child process, with that agent's declared tools, preloaded
 * skills, and (when its `model:` frontmatter names a known tier) a resolved model composed into
 * its dispatch.
 *
 * Exists because pi-subagents' `skills:` field only makes a skill *available* (an XML manifest
 * read on demand via its own `read` tool) — it never preloads skill body into context, which
 * this repo's agents/*.md convention requires (docs/skill-preload.md). See
 * docs/plugin-platform-decisions.md §9 for the full rationale, the model-tier-mapping safety
 * posture, and how the `bash`-escape-hatch recursion gap is closed (in hooks/bash_guard.sh, not
 * here).
 *
 * Everything that touches Pi itself (argv construction, pi.exec, temp-file lifecycle, tool
 * registration, model-registry queries) lives here. agent-spec.ts and model-tier.ts stay
 * SDK-free — see their own file headers.
 */
import { mkdtempSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import {
  type AgentSpec,
  composeSystemPrompt,
  listAgentNames,
  readAgentSpec,
  readSkillBody,
  skillDir,
  translateToolTokens,
} from "./agent-spec.ts";
import { isKnownModelTier, type ModelCandidate, resolveModelForTier } from "./model-tier.ts";
import { sanitizeAgentId, TASK_TOOL_NAME, taskRenderCall } from "./task-call-line.ts";

// Re-exported so the behavioural pytest driver and index.ts (which import only this
// module) keep a single import surface for the task tool — rendering and tool name included.
export { composeTaskCallLine, renderTaskCall, TASK_TOOL_NAME } from "./task-call-line.ts";

/** pi-subagents' own tool name (verified against its published source), excluded defensively
 *  alongside TASK_TOOL_NAME in case the user also has that package installed. */
const PI_SUBAGENTS_TOOL_NAME = "subagent";

const TASK_TIMEOUT_MS = 15 * 60 * 1000;
const OUTPUT_CAP_CHARS = 50_000;

/** Applied to both the success path's stdout and the failure path's stderr — a dispatched
 *  child's output (or its error output on a bad exit) becomes part of the PARENT model's
 *  context, so an uncapped dump either way is the same context-bloat risk. `.slice()` is a
 *  UTF-16 code-unit cut, which can land inside a surrogate pair (e.g. an emoji) right at the
 *  boundary — the trailing `.replace()` drops a lone leading surrogate left dangling by that
 *  cut, so the result is never an ill-formed UTF-16 string. Exported for direct unit testing —
 *  a lone surrogate does not survive a stdout/JSON/UTF-8 round trip intact, so this specific
 *  Unicode edge case needs to be tested in-process, not via the full exec path. */
export function capOutput(text: string): string {
  return text.length > OUTPUT_CAP_CHARS
    ? `${text.slice(0, OUTPUT_CAP_CHARS).replace(/[\uD800-\uDBFF]$/, "")}\n\n[truncated — output exceeded ${OUTPUT_CAP_CHARS} chars]`
    : text;
}

interface TaskParams {
  agent: string;
  prompt: string;
}

const TASK_PARAMS_SCHEMA = {
  type: "object",
  properties: {
    agent: {
      type: "string",
      description: "The agents/*.md agent id to dispatch, e.g. \"reviewer\" or \"debugger\".",
    },
    prompt: {
      type: "string",
      description: "The task/prompt to hand the dispatched agent.",
    },
  },
  required: ["agent", "prompt"],
  additionalProperties: false,
} as ToolDefinition["parameters"];

/** Decides which model to dispatch the child with. Undefined `ctx.model` -> undefined (today's
 *  omit-the-flag fallback). Otherwise: an unrecognized/missing `spec.model` tier, a provider with
 *  no MODEL_TIER_TABLE row, or no available candidate matching the row's pattern(s) all degrade
 *  to the parent's own active model unchanged — this function never throws and never reaches for
 *  a provider other than `ctx.model.provider`. Candidates come from `ctx.scopedModels` when the
 *  session is scoped (`--models`/`enabledModels`) — an explicit session-level restriction that
 *  tier resolution must respect, not bypass — and fall back to the full
 *  `ctx.modelRegistry.getAvailable()` catalog only when no scoping is configured (`scopedModels`
 *  is documented as empty in that case). */
function resolveTargetModel(
  ctx: ExtensionContext,
  spec: Pick<AgentSpec, "model">,
): { provider: string; id: string } | undefined {
  if (!ctx.model) return undefined;
  const parent = { provider: ctx.model.provider, id: ctx.model.id };
  if (!isKnownModelTier(spec.model)) return parent;

  const pool = ctx.scopedModels.length > 0 ? ctx.scopedModels.map((sm) => sm.model) : ctx.modelRegistry.getAvailable();
  const candidates: ModelCandidate[] = pool
    .filter((m) => m.provider === parent.provider)
    .map((m) => ({ provider: m.provider, id: m.id }));
  return resolveModelForTier(parent.provider, spec.model, candidates) ?? parent;
}

export function registerSubagent(pi: ExtensionAPI, root: string): void {
  // Same Tier-2 kill switch as ask-user.ts's registerAskUser — an immutable config read at
  // registration time, gating tool registration only. Tier-1 vocabulary prose stays unconditional.
  if (process.env.SWE_WORKBENCH_PI_TOOLS === "0") return;

  pi.registerTool({
    name: TASK_TOOL_NAME,
    label: "Task",
    description:
      "Dispatch one of this plugin's agents/*.md agents (e.g. \"reviewer\", \"debugger\") as a " +
      "nested Pi session, with that agent's declared tools and preloaded skills. Runs to " +
      "completion and returns its final text response.",
    promptSnippet:
      'task(agent, prompt): dispatch a named agents/*.md agent (e.g. task({ agent: "reviewer", ' +
      'prompt: "..." })) as a nested session and get its final response back.',
    promptGuidelines: [
      "Only dispatch an agent id that actually exists under agents/*.md — an unknown id fails " +
        "with the available list rather than guessing.",
    ],
    parameters: TASK_PARAMS_SCHEMA,
    renderCall: taskRenderCall,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const { agent, prompt } = params as unknown as TaskParams;

      const available = listAgentNames(root);
      if (!available.includes(agent)) {
        throw new Error(
          `task: unknown agent "${sanitizeAgentId(agent)}" — available agents: ${available.join(", ")}`,
        );
      }

      const spec = readAgentSpec(root, agent);
      const translated = translateToolTokens(spec.tools);
      // ask_user_question is granted even though it's structurally guaranteed to fail: the
      // child always runs in print mode (ctx.hasUI: false), so any call throws. That thrown
      // message is the point — it steers a dispatched agent to report a decision only a human
      // could make, instead of silently guessing.
      const toolNames = Array.from(new Set([...translated, "ask_user_question"]));

      const skills = spec.skillIds.map((id) => ({ id, body: readSkillBody(root, id), dir: skillDir(root, id) }));
      const systemPrompt = composeSystemPrompt(spec, skills);

      const tmpDir = mkdtempSync(join(tmpdir(), "swe-workbench-subagent-"));
      const promptFile = join(tmpDir, "system-prompt.md");
      try {
        writeFileSync(promptFile, systemPrompt, { mode: 0o600 });

        const args = [
          "-p",
          prompt,
          "--append-system-prompt",
          promptFile,
          "--tools",
          toolNames.join(","),
          "--exclude-tools",
          `${TASK_TOOL_NAME},${PI_SUBAGENTS_TOOL_NAME}`,
          "--no-session",
        ];
        const targetModel = resolveTargetModel(ctx, spec);
        if (targetModel) {
          args.push("--model", `${targetModel.provider}/${targetModel.id}`);
        }

        const result = await pi.exec("pi", args, { cwd: ctx.cwd, timeout: TASK_TIMEOUT_MS, signal });

        if (result.code !== 0) {
          const stderr = capOutput(result.stderr.trim()) || "(no stderr)";
          throw new Error(
            `task: dispatched agent "${agent}" exited ${result.code}${result.killed ? " (killed)" : ""} — ${stderr}`,
          );
        }

        return {
          content: [{ type: "text" as const, text: capOutput(result.stdout) }],
          details: { code: result.code, killed: result.killed },
        };
      } finally {
        // Unlink then rmdir AFTER pi.exec() resolves, never before — a missing file at read
        // time makes Pi's resolvePromptInput silently use the literal path string as the
        // prompt instead of erroring, which would corrupt the child's system prompt silently.
        try {
          unlinkSync(promptFile);
        } catch (err) {
          if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
        }
        try {
          rmdirSync(tmpDir);
        } catch (err) {
          if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
        }
      }
    },
  });
}

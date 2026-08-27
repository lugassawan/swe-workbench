/**
 * Registers `task`, a first-party subagent dispatcher: runs one of this plugin's agents/*.md
 * definitions as a nested `pi` child process, with that agent's declared tools, preloaded
 * skills, and (when its `model:` frontmatter names a known tier) a resolved model composed into
 * its dispatch.
 *
 * Exists because pi-subagents' `skills:` field only makes a skill *available* (an XML manifest
 * read on demand via its own `read` tool) — it never preloads skill body into context, which
 * this repo's agents/*.md convention requires (docs/skill-preload.md). See
 * docs/plugin-platform-decisions.md §9 for the full rationale, the model-dispatch-policy safety
 * posture, and how the `bash`-escape-hatch recursion gap is closed (in hooks/bash_guard.sh, not
 * here).
 *
 * Everything that touches Pi itself (argv construction, pi.exec, temp-file lifecycle, tool
 * registration, model-registry queries) lives here or in dispatch-resolver.ts (split off at the
 * line cap). agent-spec.ts and model-policy.ts stay SDK-free — see their own file headers.
 */
import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { mkdtempSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  composeSystemPrompt,
  listAgentNames,
  readAgentSpec,
  readSkillBody,
  skillDir,
  translateToolTokens,
} from "./agent-spec.ts";
import { resolveTargetDispatch } from "./dispatch-resolver.ts";
import { sanitizeAgentId, TASK_TOOL_NAME, taskRenderCall, taskRenderResult } from "./task-call-line.ts";

// Re-exported so the behavioural pytest driver and index.ts (which import only this
// module) keep a single import surface for the task tool — rendering and tool name included.
export {
  composeTaskCallLine,
  composeTaskDispatchLine,
  renderTaskCall,
  renderTaskResult,
  TASK_TOOL_NAME
} from "./task-call-line.ts";

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
    renderResult: taskRenderResult,
    async execute(_toolCallId, params, signal, onUpdate, ctx) {
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
        const dispatch = resolveTargetDispatch(ctx, agent, spec);
        onUpdate?.({ content: [], details: dispatch.details });
        if (dispatch.model) {
          args.push("--model", `${dispatch.model.provider}/${dispatch.model.id}`);
        }
        if (dispatch.thinking) {
          args.push("--thinking", dispatch.thinking);
        }

        // Print mode has no UI to catch ctx.ui.notify — the warning must also land in the tool
        // result content below so a degraded dispatch is visible headless, not just in a TUI.
        if (dispatch.warning && ctx.hasUI) ctx.ui.notify(dispatch.warning, "warning");

        const result = await pi.exec("pi", args, { cwd: ctx.cwd, timeout: TASK_TIMEOUT_MS, signal });

        if (result.code !== 0) {
          const stderr = capOutput(result.stderr.trim()) || "(no stderr)";
          // A degraded dispatch that then also fails is exactly when the caller most needs the
          // fallback context — never drop it just because the child errored for an unrelated
          // reason (bad args, timeout, crash).
          const warningSuffix = dispatch.warning ? ` (${dispatch.warning})` : "";
          throw new Error(
            `task: dispatched agent "${agent}" exited ${result.code}` +
              `${result.killed ? " (killed)" : ""}${warningSuffix} — ${stderr}`,
          );
        }

        const content = [
          ...(dispatch.warning ? [{ type: "text" as const, text: `[swe-workbench] ${dispatch.warning}` }] : []),
          { type: "text" as const, text: capOutput(result.stdout) },
        ];

        return {
          content,
          details: { code: result.code, killed: result.killed, ...dispatch.details },
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

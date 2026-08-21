/**
 * Registers `task`, a first-party subagent dispatcher: runs one of this plugin's agents/*.md
 * definitions as a nested `pi` child process, with that agent's declared tools and preloaded
 * skills composed into its system prompt.
 *
 * Exists because pi-subagents' `skills:` field only makes a skill *available* (an XML manifest
 * read on demand via its own `read` tool) — it never preloads skill body into context, which
 * this repo's agents/*.md convention requires (docs/skill-preload.md). See
 * docs/plugin-platform-decisions.md §9 for the full rationale and the accepted `bash`-escape-
 * hatch recursion gap.
 *
 * Everything that touches Pi itself (argv construction, pi.exec, temp-file lifecycle, tool
 * registration) lives here. agent-spec.ts stays SDK-free — see its own file header.
 */
import { mkdtempSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";
import {
  composeSystemPrompt,
  listAgentNames,
  readAgentSpec,
  readSkillBody,
  translateToolTokens,
} from "./agent-spec.ts";

/** Single source of truth for the tool's registered name — consumed both by pi.registerTool()
 *  below and by the `--exclude-tools` argv builder, so a rename can't silently desync
 *  registration from the recursion guard. */
export const TASK_TOOL_NAME = "task";

/** pi-subagents' own tool name (verified against its published source), excluded defensively
 *  alongside TASK_TOOL_NAME in case the user also has that package installed. */
const PI_SUBAGENTS_TOOL_NAME = "subagent";

const TASK_TIMEOUT_MS = 15 * 60 * 1000;
const OUTPUT_CAP_CHARS = 50_000;

/** Applied to both the success path's stdout and the failure path's stderr — a dispatched
 *  child's output (or its error output on a bad exit) becomes part of the PARENT model's
 *  context, so an uncapped dump either way is the same context-bloat risk. */
function capOutput(text: string): string {
  return text.length > OUTPUT_CAP_CHARS
    ? `${text.slice(0, OUTPUT_CAP_CHARS)}\n\n[truncated — output exceeded ${OUTPUT_CAP_CHARS} chars]`
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
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const { agent, prompt } = params as unknown as TaskParams;

      const available = listAgentNames(root);
      if (!available.includes(agent)) {
        throw new Error(`task: unknown agent "${agent}" — available agents: ${available.join(", ")}`);
      }

      const spec = readAgentSpec(root, agent);
      const translated = translateToolTokens(spec.tools);
      // ask_user_question is granted even though no agent declares it and the child (always
      // print-mode, ctx.hasUI: false) is structurally guaranteed to reject any call to it — the
      // rejection message itself is the point: it steers the dispatched agent to stop and report
      // the blocking decision back to us, instead of silently guessing when it hits one that
      // only a user could make. Registering the tool costs nothing (translated tokens already
      // dominate the system prompt's "Available tools" documentation) and gives the model a
      // named way to signal "I need a human here" rather than no signal at all.
      const toolNames = Array.from(new Set([...translated, "ask_user_question"]));

      const skills = spec.skillIds.map((id) => ({ id, body: readSkillBody(root, id) }));
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
        if (ctx.model) {
          args.push("--model", `${ctx.model.provider}/${ctx.model.id}`);
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

/**
 * Registers `memory_record`, a native tool the model calls to save cross-harness memory
 * (the model can't invoke the `/memory` prompt template on its own).
 *
 * Trust-gated twice: `session_start` hides the tool when the project is untrusted, and
 * `execute()` re-checks independently. No confirmation prompt; ctx.ui.notify is the signal.
 *
 * Entry types, byte caps, the secret scan, and the slug recipe all live in
 * bin/swe-workbench-memory — this is a thin shim over an argv-only spawn.
 */
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";
import { ENTRY_TYPES, MEMORY_TOOL_NAME } from "./memory-guidance.ts";
import { spawnRuntime } from "./guard-runner.ts";

const RUNTIME_RELATIVE_PATH = join("bin", "swe-workbench-memory");
const RUNTIME_TIMEOUT_MS = 10_000;

interface MemoryRecordParams {
  name: string;
  description: string;
  type: (typeof ENTRY_TYPES)[number];
  body: string;
}

// prettier-ignore
const MEMORY_RECORD_SCHEMA = {
  type: "object", properties: {
    name: { type: "string", description: "Short, stable identifier. Recording under a name that already exists updates that entry in place — there is no delete." },
    description: { type: "string", description: "One-line summary shown in the memory index." },
    type: { type: "string", enum: [...ENTRY_TYPES], description: `One of: ${ENTRY_TYPES.join(", ")}.` },
    body: { type: "string", description: "The full entry: the fact/rule, then a **Why:** line and a **How to apply:** line." },
  },
  required: ["name", "description", "type", "body"], additionalProperties: false,
} as ToolDefinition["parameters"];

interface RecordEnvelope {
  data?: { entry_path?: unknown };
}

function parseEntryPath(stdout: string): string | undefined {
  try {
    const path = (JSON.parse(stdout.trim()) as RecordEnvelope)?.data?.entry_path;
    return typeof path === "string" ? path : undefined;
  } catch {
    return undefined;
  }
}

const UNTRUSTED_MESSAGE =
  "memory_record requires a trusted project — this repository is not trusted this session.";

export function registerMemoryRecord(pi: ExtensionAPI, root: string): void {
  // Same kill switch as ask-user.ts/subagent.ts.
  if (process.env.SWE_WORKBENCH_PI_TOOLS === "0") return;

  const runtimePath = join(root, RUNTIME_RELATIVE_PATH);

  // Hide from an untrusted session's active set; execute() re-checks independently below.
  pi.on("session_start", (_event, ctx: ExtensionContext) => {
    if (ctx.isProjectTrusted()) return;
    pi.setActiveTools(pi.getActiveTools().filter((name) => name !== MEMORY_TOOL_NAME));
  });

  pi.registerTool({
    name: MEMORY_TOOL_NAME,
    label: "Memory Record",
    description:
      "Save a cross-harness memory entry (Claude Code and Pi both read it). Use only for " +
      "durable, non-obvious facts — see the system prompt's \"When to call memory_record\" " +
      "section for what qualifies.",
    promptSnippet:
      `${MEMORY_TOOL_NAME}(name, description, type, body): save a memory entry that both ` +
      "Claude Code and Pi sessions on this repo will see going forward.",
    parameters: MEMORY_RECORD_SCHEMA,
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      if (!ctx.isProjectTrusted()) {
        throw new Error(UNTRUSTED_MESSAGE);
      }

      const { name, description, type, body } = params as unknown as MemoryRecordParams;
      const result = await spawnRuntime({
        command: "python3",
        args: [
          runtimePath,
          "record",
          "--as",
          "pi",
          "--store",
          "pi",
          "--name",
          name,
          "--description",
          description,
          "--type",
          type,
        ],
        cwd: ctx.cwd,
        timeoutMs: RUNTIME_TIMEOUT_MS,
        input: body,
      });

      if (result.code !== 0) {
        throw new Error(result.stderr.trim() || `memory_record: runtime exited ${result.code}`);
      }

      const entryPath = parseEntryPath(result.stdout);
      if (entryPath === undefined) {
        throw new Error(
          `memory_record: runtime succeeded but its output could not be parsed: ${result.stdout.slice(0, 500)}`,
        );
      }

      if (ctx.hasUI) {
        ctx.ui.notify(`Memory saved: ${name}`);
      }

      return {
        content: [{ type: "text" as const, text: entryPath }],
        details: { entryPath },
      };
    },
  });
}

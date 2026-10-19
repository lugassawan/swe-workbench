import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { mkdtempSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { extractLastAssistantText, parseNestedTaskJson } from "./subagent-json.ts";
import { capOutput } from "./subagent-output.ts";
import { MEMORY_TOOL_NAME } from "./memory-guidance.ts";
import { TASK_TOOL_NAME } from "./task-call-line.ts";

const PI_SUBAGENTS_TOOL_NAME = "subagent";
const TASK_TIMEOUT_MS = 15 * 60 * 1000;

export interface AttemptInput {
  readonly prompt: string;
  readonly systemPrompt: string;
  readonly toolNames: readonly string[];
  readonly model: string | undefined;
  readonly thinking: string | undefined;
  readonly cwd: string;
  readonly signal: AbortSignal | undefined;
}

export interface AttemptResult {
  readonly stdout: string;
  readonly text: string;
  readonly usage: ReturnType<typeof parseNestedTaskJson>["usage"];
}

/** Executes exactly one child process and preserves legacy diagnostics/failure semantics. */
export async function runSubagentAttempt(pi: ExtensionAPI, input: AttemptInput): Promise<AttemptResult> {
  const tmpDir = mkdtempSync(join(tmpdir(), "swe-workbench-subagent-"));
  const promptFile = join(tmpDir, "system-prompt.md");
  try {
    writeFileSync(promptFile, input.systemPrompt, { mode: 0o600 });
    const args = [
      "-p", input.prompt, "--mode", "json", "--append-system-prompt", promptFile,
      "--tools", input.toolNames.join(","),
      "--exclude-tools", `${TASK_TOOL_NAME},${PI_SUBAGENTS_TOOL_NAME},${MEMORY_TOOL_NAME}`,
      "--no-session",
    ];
    if (input.model) args.push("--model", input.model);
    if (input.thinking) args.push("--thinking", input.thinking);
    const result = await pi.exec("pi", args, { cwd: input.cwd, timeout: TASK_TIMEOUT_MS, signal: input.signal });
    if (result.code !== 0) {
      const stderr = capOutput(result.stderr.trim()) || "(no stderr)";
      const lastMessage = extractLastAssistantText(result.stdout);
      const partialSuffix = lastMessage ? `\n\nLast assistant message:\n${capOutput(lastMessage)}` : "";
      throw new Error(`task: child exited ${result.code}${result.killed ? " (killed)" : ""} — ${stderr}${partialSuffix}`);
    }
    try {
      const parsed = parseNestedTaskJson(result.stdout);
      return { stdout: result.stdout, ...parsed };
    } catch (err) {
      throw new Error(`task: child failed — ${capOutput(err instanceof Error ? err.message : String(err))}`);
    }
  } finally {
    try { unlinkSync(promptFile); } catch (err) { if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err; }
    try { rmdirSync(tmpDir); } catch (err) { if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err; }
  }
}

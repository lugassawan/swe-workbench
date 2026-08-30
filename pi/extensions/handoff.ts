/**
 * Pi-side handoff safeguards — the native mirror of hooks/handoff_guard.py.
 *
 * Why native instead of wiring the hook script: the hook consumes Claude Code's
 * PreToolUse payload shape (tool_name/tool_input/session_id) and resolves the runtime
 * through CLAUDE_PLUGIN_ROOT. Pi's tool_call events have a different shape, session
 * identity lives on ctx.sessionManager, and quota exhaustion on Pi surfaces as an HTTP
 * status on after_provider_response — none of which the Claude hook can see. Both
 * adapters delegate every decision to the same harness-neutral runtime
 * (bin/swe-workbench-handoff guard), so the ownership rules never fork.
 *
 * Quota asymmetry (deliberate): Pi has no trustworthy subscription-quota signal — context-usage
 * accessors report context-window usage, which is NOT quota — so the only Pi-side quota
 * affordance is recovery after an actual HTTP 429. No pre-limit warnings.
 *
 * Failure postures mirror the Claude hook: a missing runtime install fails OPEN (a broken
 * plugin install must not deadlock every mutation), while any other runtime failure —
 * spawn error, timeout, corrupt lease state, undecidable output — fails CLOSED.
 */
import { existsSync } from "node:fs";
import { join } from "node:path";
import type {
  ExtensionAPI,
  ExtensionContext,
  ToolCallEventResult,
} from "@earendil-works/pi-coding-agent";
import { spawnRuntime } from "./guard-runner.ts";

const STATUS_KEY = "swb-handoff";
const RUNTIME_RELATIVE_PATH = join("bin", "swe-workbench-handoff");
const RUNTIME_TIMEOUT_MS = 10_000;

/** Exact recovery text — persisted in the footer so it survives terminal scroll. */
const QUOTA_RECOVERY_TEXT =
  "Pi quota exhausted (HTTP 429) — stop, then recover in Claude Code: " +
  "swe-workbench-handoff recover --from pi --source-stopped " +
  "| swe-workbench-result-check swb.handoff/1";

const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;
const CHECKED_PIPE = String.raw`\| swe-workbench-result-check swb\.handoff/1`;
const PI_SESSION_ARGUMENT = '"${PI_SESSION_ID:?missing PI_SESSION_ID}"';

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Anchored single-pipeline allowlist, normalized over line continuations. Only resume and
 * recover may pass through a released/foreign lease; close authenticates through the normal
 * owner/session check, so it is deliberately absent (mirrors the Claude-side decision).
 */
const CONTROL_COMMANDS: readonly RegExp[] = [
  new RegExp(
    `^swe-workbench-handoff resume "?${UUID_PATTERN.source}"? --as "?pi"? ` +
      `--receiver-session ${escapeRegExp(PI_SESSION_ARGUMENT)} ` +
      `(?:--acknowledge-degraded )?${CHECKED_PIPE}$`,
  ),
  new RegExp(
    `^swe-workbench-handoff recover --from "?claude"? --source-stopped ${CHECKED_PIPE}$`,
  ),
];

function isControlCommand(command: string): boolean {
  const normalized = command.replace(/\\\n/g, " ").split(/\s+/).filter(Boolean).join(" ");
  return CONTROL_COMMANDS.some((pattern) => pattern.test(normalized));
}

interface RuntimeResult {
  code: number | null;
  stdout: string;
  stderr: string;
}

function runHandoffRuntime(runtimePath: string, args: string[], cwd: string): Promise<RuntimeResult> {
  return spawnRuntime({
    command: "python3",
    args: [runtimePath, ...args],
    cwd,
    timeoutMs: RUNTIME_TIMEOUT_MS,
  });
}

interface GuardData {
  decision?: unknown;
  reason?: unknown;
  instruction?: unknown;
}

function parseGuardDecision(stdout: string): GuardData | undefined {
  const trimmed = stdout.trim();
  if (!trimmed) return undefined;
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== "object") return undefined;
    const data = (parsed as { data?: unknown }).data;
    if (data === null || typeof data !== "object") return undefined;
    return data as GuardData;
  } catch {
    return undefined;
  }
}

function blockReason(data: GuardData | undefined, fallback: string): string {
  if (data === undefined) return fallback;
  const reason = typeof data.reason === "string" ? data.reason : "";
  const instruction = typeof data.instruction === "string" ? data.instruction : "";
  if (reason && instruction) return `${reason} — ${instruction}`;
  return instruction || reason || fallback;
}

export function registerHandoff(pi: ExtensionAPI, root: string): void {
  const runtimePath = join(root, RUNTIME_RELATIVE_PATH);

  let warnedMissingRuntime = false;
  let quotaWarningShown = false;

  pi.on("tool_call", async (event, ctx: ExtensionContext): Promise<ToolCallEventResult | undefined> => {
    const toolName = (event as { toolName?: unknown }).toolName;
    if (toolName !== "bash" && toolName !== "write" && toolName !== "edit") return undefined;

    if (toolName === "bash") {
      // `input` is unknown-shaped at this boundary; a nullish input must not throw — this
      // handler is first-registered and a throw would abort the tool_call loop before the
      // security guards run.
      const command = (event.input as { command?: unknown } | undefined)?.command;
      if (typeof command === "string" && isControlCommand(command)) return undefined;
    }

    // emitToolCall has no try/catch around handler bodies and this is the FIRST-registered
    // tool_call handler — a throw here would abort the loop before registerGuards' checks run.
    // Per the invariant index.ts documents: wrap the body, return undefined on throw.
    try {
      if (!existsSync(runtimePath)) {
        if (!warnedMissingRuntime && ctx.hasUI) {
          warnedMissingRuntime = true;
          ctx.ui.notify(
            "swe-workbench: bin/swe-workbench-handoff is missing — handoff ownership is not enforced this session.",
            "warning",
          );
        }
        return undefined;
      }

      const args = ["guard", "--as", "pi"];
      const sessionId = ctx.sessionManager.getSessionId();
      if (sessionId) args.push("--session-ref", sessionId);

      const result = await runHandoffRuntime(runtimePath, args, ctx.cwd);
      const data = parseGuardDecision(result.stdout);

      if (result.code === 0 && data !== undefined && data.decision === "allow") return undefined;
      if (data !== undefined && data.decision === "deny") {
        return { block: true, reason: blockReason(data, "handoff lease denies mutation from this Pi session") };
      }
      return {
        block: true,
        reason:
          "swe-workbench handoff ownership could not be verified; repair the handoff runtime " +
          "or state before mutating this worktree",
      };
    } catch {
      return undefined;
    }
  });

  pi.on("after_provider_response", (event, ctx: ExtensionContext) => {
    const status = (event as { status?: unknown }).status;
    if (status !== 429) return;
    // Persistent recovery status + at most one warning per session. Context-window usage
    // is intentionally never consulted — it is not subscription quota.
    if (!ctx.hasUI) return;
    ctx.ui.setStatus(STATUS_KEY, QUOTA_RECOVERY_TEXT);
    if (!quotaWarningShown) {
      quotaWarningShown = true;
      ctx.ui.notify(QUOTA_RECOVERY_TEXT, "warning");
    }
  });
}

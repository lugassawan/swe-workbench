/**
 * Composition root: wires bash_guard.sh/secret_guard.py as Pi tool_call guards, and
 * workflow_resume_hint.sh/memory_hint.sh/skill_autoload_hint.sh as Pi session/tool_result hint
 * sources — all via guard-runner.ts, never reimplemented.
 *
 * `toolName` narrowing uses a manual cast rather than the SDK's `isToolCallEventType` helper so
 * every @earendil-works/pi-coding-agent import here stays `import type`-only (pinned by
 * tests/test_pi_contract.py).
 */
import { join } from "node:path";
import type {
  BashToolCallEvent,
  EditToolCallEvent,
  ExtensionAPI,
  ExtensionContext,
  SessionCompactEvent,
  SessionStartEvent,
  ToolCallEventResult,
  WriteToolCallEvent,
} from "@earendil-works/pi-coding-agent";
import {
  bashPayload,
  editPayloads,
  GUARD_DISPATCH,
  type GuardSpec,
  memoryHintPayload,
  resumeHintPayload,
  sessionCompactSource,
  sessionStartSource,
  skillHintPayload,
  writePayload,
} from "./cc-payload.ts";
import { runGuard as defaultRunGuard, type RunGuard } from "./guard-runner.ts";

const RESUME_HINT_SCRIPT = "hooks/workflow_resume_hint.sh";
const SKILL_HINT_SCRIPT = "hooks/skill_autoload_hint.sh";
const MEMORY_HINT_SCRIPT = "hooks/memory_hint.sh";

interface HookSpecificOutput {
  hookSpecificOutput?: { additionalContext?: string };
}

/** Parses a hint script's stdout envelope; absent/malformed/empty stdout is a silent no-op —
 *  these are advisory hooks, not guards, and never block or throw on their own output shape. */
function parseAdditionalContext(stdout: string): string | undefined {
  const trimmed = stdout.trim();
  if (!trimmed) return undefined;
  try {
    return (JSON.parse(trimmed) as HookSpecificOutput).hookSpecificOutput?.additionalContext;
  } catch {
    return undefined;
  }
}

export interface RegisterGuardsOptions {
  /** Injectable so tests can force a spawn failure without touching the real hooks/ scripts. */
  runGuard?: RunGuard;
}

export function registerGuards(pi: ExtensionAPI, root: string, options: RegisterGuardsOptions = {}): void {
  const run = options.runGuard ?? defaultRunGuard;

  // Applies a guard's OWN declared posture to a run with no real verdict — spawn
  // failure/timeout, or an exit code outside {0, 2} (this repo's hooks only ever emit those
  // two; 127/126/null mean the guard never actually ran). bash_guard.sh fails closed;
  // secret_guard.py fails open — but never silently, since an unnoticed self-disabled guard is
  // worse than no guard.
  function handleGuardFailure(spec: GuardSpec, ctx: ExtensionContext, detail: string): ToolCallEventResult | undefined {
    if (spec.failPosture === "closed") {
      return { block: true, reason: `${detail} — blocking (fail-closed)` };
    }
    if (ctx.hasUI) {
      ctx.ui.notify(`${detail} — not blocking (fail-open)`, "warning");
    }
    return undefined;
  }

  async function checkGuard(
    spec: GuardSpec,
    payload: Record<string, unknown>,
    ctx: ExtensionContext,
  ): Promise<ToolCallEventResult | undefined> {
    let result;
    try {
      result = await run({
        interpreter: spec.interpreter,
        scriptPath: join(root, spec.scriptRelPath),
        payload,
        cwd: ctx.cwd,
        pluginRoot: root,
        signal: ctx.signal,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return handleGuardFailure(spec, ctx, `${spec.scriptRelPath} could not run: ${message}`);
    }

    if (result.code === 2) {
      return { block: true, reason: result.stderr.trim() || `${spec.scriptRelPath}: blocked` };
    }
    if (result.code === 0) {
      return undefined;
    }
    return handleGuardFailure(
      spec,
      ctx,
      `${spec.scriptRelPath} exited ${result.code} unexpectedly: ${result.stderr.trim()}`,
    );
  }

  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName === "bash") {
      return checkGuard(GUARD_DISPATCH.bash, bashPayload(event as BashToolCallEvent), ctx);
    }
    if (event.toolName === "write") {
      return checkGuard(GUARD_DISPATCH.write, writePayload(event as WriteToolCallEvent), ctx);
    }
    if (event.toolName === "edit") {
      for (const payload of editPayloads(event as EditToolCallEvent)) {
        const result = await checkGuard(GUARD_DISPATCH.edit, payload, ctx);
        if (result?.block) return result; // short-circuit at the first blocked edits[] element
      }
    }
    return undefined;
  });

  async function emitHint(
    scriptRelPath: string,
    payload: Record<string, unknown>,
    ctx: ExtensionContext,
    customType: string,
    deliverAs: "nextTurn" | "steer",
  ): Promise<void> {
    let result;
    try {
      result = await run({
        interpreter: "bash",
        scriptPath: join(root, scriptRelPath),
        payload,
        cwd: ctx.cwd,
        pluginRoot: root,
        signal: ctx.signal,
      });
    } catch {
      return; // advisory-only: fail open, same as the hook's own Claude Code posture
    }
    if (result.code !== 0) return;
    const content = parseAdditionalContext(result.stdout);
    if (!content) return;
    pi.sendMessage({ customType, content, display: false }, { deliverAs });
  }

  // Gated on project trust: both hints here inject content into model context (repo-committed
  // workflow state, agent-written cross-harness memory) — an untrusted repo must see neither.
  pi.on("session_start", async (event, ctx) => {
    if (!ctx.isProjectTrusted()) return;
    const source = sessionStartSource(event as SessionStartEvent);
    await emitHint(RESUME_HINT_SCRIPT, resumeHintPayload(ctx.cwd, source), ctx, "swe-workbench:workflow-resume-hint", "nextTurn");
    await emitHint(MEMORY_HINT_SCRIPT, memoryHintPayload(ctx.cwd), ctx, "swe-workbench:memory-hint", "nextTurn");
  });

  pi.on("session_compact", async (event, ctx) => {
    if (!ctx.isProjectTrusted()) return;
    const source = sessionCompactSource(event as SessionCompactEvent);
    await emitHint(RESUME_HINT_SCRIPT, resumeHintPayload(ctx.cwd, source), ctx, "swe-workbench:workflow-resume-hint", "nextTurn");
    await emitHint(MEMORY_HINT_SCRIPT, memoryHintPayload(ctx.cwd), ctx, "swe-workbench:memory-hint", "nextTurn");
  });

  pi.on("tool_result", async (event, ctx) => {
    if (event.toolName !== "read" && event.toolName !== "write" && event.toolName !== "edit") return undefined;

    const filePath = (event.input as { path?: unknown }).path;
    if (typeof filePath !== "string" || !filePath) return undefined;

    const sessionId = ctx.sessionManager.getSessionId();
    if (!sessionId) {
      // skill_autoload_hint.sh falls back to $$ (the process PID) when session_id is absent —
      // two Pi sessions sharing one process would then silently share its dedup sentinel.
      throw new Error(
        "swe-workbench: ctx.sessionManager.getSessionId() returned empty — refusing to call " +
          "skill_autoload_hint.sh without a session id",
      );
    }

    await emitHint(
      SKILL_HINT_SCRIPT,
      skillHintPayload(filePath, sessionId),
      ctx,
      "swe-workbench:skill-autoload-hint",
      "steer",
    );
    return undefined;
  });
}

/**
 * swe-workbench adapter for Pi Coding Agent.
 *
 * Mirrors three harness affordances Claude Code already provides for this plugin, pointing at
 * the SAME skills/, bin/, and commands/ trees Claude Code uses — nothing under those is
 * duplicated:
 *   1. `<plugin>/bin` on PATH, so every skill's bare `swe-workbench-<name>` command resolves
 *      unchanged (see bin/README.md).
 *   2. All skills/<name>/SKILL.md directories reachable, via `resources_discover`.
 *   3. All commands/*.md reachable as Pi prompt templates, also via `resources_discover`'s
 *      `promptPaths` — deliberately NOT the `pi.prompts` manifest key. The manifest
 *      route's loader (`collectFiles()`) recurses into subdirectories; `promptPaths`'s loader
 *      (`loadTemplatesFromDir()`, dist/core/prompt-templates.js) does not. Since template names
 *      are derived with a flat `basename()` at every depth, the manifest route would silently
 *      publish any future `commands/<subdir>/*.md` as a top-level `/command` — this repo held
 *      exactly such a subdirectory (`commands/shared/`) until Phase 0 removed it. The
 *      `resources_discover` route makes that class of bug structurally unrepresentable instead
 *      of requiring a regression test to catch it.
 *
 * Two Pi API facts recorded here so a later phase does not rediscover them the hard way:
 *   - `ExtensionContext` (dist/core/extensions/types.d.ts) exposes no settings accessor. An
 *     extension that wants the user's `shellPath`/`shellCommandPrefix` would have to re-register
 *     the `bash` tool, which silently discards both — and a `commandPrefix` approach would
 *     overwrite the user's own `shellCommandPrefix`. The bin/ wiring only ever appends to
 *     `process.env.PATH` and never re-registers the bash tool.
 *   - The shipped `examples/extensions/bash-spawn-hook.ts` wraps the bash tool by dropping its
 *     `_ctx` argument, which kills the `PI_SESSION_ID`/`PI_MODEL`/`PI_PROVIDER` env vars the bash
 *     tool's own guidelines tell the model to read. Do not copy that pattern verbatim.
 *
 * Scope note: tool_call handlers ARE registered by this adapter (handoff.ts — ownership,
 * guards.ts — security, phase.ts — plan-phase steering); they observe and block, never
 * replace the tool.
 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { existsSync } from "node:fs";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { registerAskUser } from "./ask-user.ts";
import { binScriptsSection } from "./bin-scripts.ts";
import { registerGuards } from "./guards.ts";
import { registerHandoff } from "./handoff.ts";
import { memoryGuidanceSection, MEMORY_TOOL_NAME } from "./memory-guidance.ts";
import { registerMemoryRecord } from "./memory-record.ts";
import { registerPhase } from "./phase.ts";
import { registerSubagent, TASK_TOOL_NAME } from "./subagent.ts";
import { toolVocabSection } from "./tool-vocab.ts";

class PluginRootNotFoundError extends Error {
  constructor(startDir: string) {
    super(`swe-workbench: could not find .claude-plugin/plugin.json above ${startDir}`);
    this.name = "PluginRootNotFoundError";
  }
}

/** Walks up from `startDir` until a directory contains .claude-plugin/plugin.json. */
function findPluginRoot(startDir: string): string {
  let dir = startDir;
  while (true) {
    if (existsSync(join(dir, ".claude-plugin", "plugin.json"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) throw new PluginRootNotFoundError(startDir);
    dir = parent;
  }
}

const PREAMBLE_MARKER = "<!-- swe-workbench:pi-bin-preamble -->";

function composePreamble(sections: { title: string; body: string }[]): string {
  return (
    `\n\n${PREAMBLE_MARKER}\n` +
    sections.map((s) => `## ${s.title}\n\n${s.body}`).join("\n\n")
  );
}

export default function (pi: ExtensionAPI): void {
  const here = dirname(fileURLToPath(import.meta.url));
  const root = findPluginRoot(here);

  const binDir = join(root, "bin");
  const pathEntries = (process.env.PATH ?? "").split(delimiter).filter(Boolean);
  if (!pathEntries.includes(binDir)) {
    process.env.PATH = [...pathEntries, binDir].join(delimiter);
  }

  // toolVocabSection is pure and never fails, so it must NOT be dragged down by an
  // unreadable/empty bin/ — Tier-1 vocabulary prose (including the anti-hallucination rule)
  // stays on unconditionally, same posture as ask-user.ts's kill switch. composePreamble (via
  // getPreamble() below) is still computed exactly once per session (cached after first call),
  // so the single PREAMBLE_MARKER dedup check keeps proving something real.
  const generatedBinSection = binScriptsSection(root);
  const generatedSection = generatedBinSection === null ? [] : [generatedBinSection];

  let warnedMissingAnchor = false;
  let cachedPreamble: string | undefined;

  // Computed lazily (on first before_agent_start) and cached. `SWE_WORKBENCH_PI_TOOLS` alone
  // is not enough: a dispatched child re-runs this same index.ts with the kill switch still
  // unset, but its own argv carries `--exclude-tools task,subagent` — the real tool registry
  // has already filtered `task` out by the time extensions finish registering (see
  // docs/task-dispatch.md). Only pi.getActiveTools() reflects that; the env var
  // alone would tell a dispatched agent to use a tool deliberately removed from its surface.
  function getPreamble(): string {
    if (cachedPreamble === undefined) {
      const taskToolRegistered = pi.getActiveTools().includes(TASK_TOOL_NAME);
      const memoryToolActive = pi.getActiveTools().includes(MEMORY_TOOL_NAME);
      const sections = [...generatedSection, toolVocabSection(root, taskToolRegistered)];
      if (memoryToolActive) sections.push(memoryGuidanceSection());
      cachedPreamble = composePreamble(sections);
    }
    return cachedPreamble;
  }

  pi.on("resources_discover", () => ({
    skillPaths: [join(root, "skills")],
    promptPaths: [join(root, "commands")],
  }));

  pi.on("session_start", (_event, ctx: ExtensionContext) => {
    if (generatedBinSection === null && !warnedMissingAnchor && ctx.hasUI) {
      warnedMissingAnchor = true;
      ctx.ui.notify(
        "swe-workbench: bin/ could not be read (or has no swe-workbench-* scripts) — the " +
          "bin/ script inventory will not be injected into the system prompt this session.",
        "warning",
      );
    }
  });

  pi.on("before_agent_start", (event) => {
    if (event.systemPrompt.includes(PREAMBLE_MARKER)) return;
    return { systemPrompt: event.systemPrompt + getPreamble() };
  });

  // Registration order is load-bearing. emitToolCall runs tool_call handlers in registration
  // order, short-circuits only on `block: true` (an `undefined` allow never stops later
  // handlers), and — unlike emitUserBash — wraps no handler body in try/catch, so every
  // tool_call handler must self-wrap and return `undefined` on throw. The order below:
  //
  //   1. registerHandoff — an ownership denial must win the block reason: it carries the
  //      receiver resume instruction. Its allow is `undefined`, so everything below still
  //      runs on each allowed call.
  //   2. registerGuards — security verdicts come first; a security guard registered after a
  //      non-security handler would be a silent regression.
  //   3. registerPhase — the plan-phase gate BLOCKS (never replaces) edit/write outside
  //      ~/.pi/agent/plans, and must never preempt a security verdict.
  //   4. registerMemoryRecord — no tool_call handler, so it is not order-sensitive; placed
  //      after the tool_call handlers above for readability.
  //   5. registerAskUser — no tool_call handler today; a future one belongs after (2).
  registerHandoff(pi, root);
  registerGuards(pi, root);
  registerPhase(pi, root);
  registerMemoryRecord(pi, root);
  registerAskUser(pi);
  registerSubagent(pi, root);
}

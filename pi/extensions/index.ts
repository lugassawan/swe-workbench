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
 *     overwrite the user's own `shellCommandPrefix`. This adapter only ever appends to
 *     `process.env.PATH`; it never touches the bash tool or `pi.on("tool_call")`.
 *   - The shipped `examples/extensions/bash-spawn-hook.ts` wraps the bash tool by dropping its
 *     `_ctx` argument, which kills the `PI_SESSION_ID`/`PI_MODEL`/`PI_PROVIDER` env vars the bash
 *     tool's own guidelines tell the model to read. Do not copy that pattern verbatim.
 */
import { existsSync, readFileSync } from "node:fs";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { registerAskUser } from "./ask-user.ts";
import { registerGuards } from "./guards.ts";
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

/** Extracts the body of bin/README.md's "## Current scripts" section, up to the next "## " heading. */
function extractCurrentScripts(readmeText: string): string | null {
  const heading = "## Current scripts";
  const start = readmeText.indexOf(heading);
  if (start === -1) return null;
  const rest = readmeText.slice(start + heading.length);
  const nextHeadingOffset = rest.indexOf("\n## ");
  const body = nextHeadingOffset === -1 ? rest : rest.slice(0, nextHeadingOffset);
  return body.trim();
}

/**
 * Reads bin/README.md and extracts the "## Current scripts" section. Returns null on any
 * failure (file missing/unreadable, or heading missing) — this is a doc file, not load-bearing
 * for PATH exposure or skill discovery, so its absence must degrade only the bin-scripts row of
 * the preamble, never take down the whole extension or the rest of the preamble (in particular,
 * toolVocabSection's content — including the anti-hallucination rule — must still be injected).
 */
function readCurrentScripts(binDir: string): string | null {
  let readmeText: string;
  try {
    readmeText = readFileSync(join(binDir, "README.md"), "utf8");
  } catch {
    return null;
  }
  return extractCurrentScripts(readmeText);
}

export default function (pi: ExtensionAPI): void {
  const here = dirname(fileURLToPath(import.meta.url));
  const root = findPluginRoot(here);

  const binDir = join(root, "bin");
  const pathEntries = (process.env.PATH ?? "").split(delimiter).filter(Boolean);
  if (!pathEntries.includes(binDir)) {
    process.env.PATH = [...pathEntries, binDir].join(delimiter);
  }

  // Only the bin-scripts section depends on bin/README.md; toolVocabSection is pure and never
  // fails, so it must NOT be dragged down by a missing/unreadable README — Tier-1 vocabulary
  // prose (including the anti-hallucination rule) stays on unconditionally, same posture as
  // ask-user.ts's kill switch. composePreamble (via getPreamble() below) is still computed
  // exactly once per session (cached after first call), so the single PREAMBLE_MARKER dedup
  // check keeps proving something real.
  const currentScripts = readCurrentScripts(binDir);
  const binSection =
    currentScripts === null
      ? []
      : [{ title: "swe-workbench bin/ scripts (bare commands, already on PATH)", body: currentScripts }];

  let warnedMissingAnchor = false;
  let cachedPreamble: string | undefined;

  // Computed lazily (on first before_agent_start, not at factory-invocation time) and cached.
  // `SWE_WORKBENCH_PI_TOOLS` alone is NOT enough to decide this: registerSubagent() still calls
  // pi.registerTool() unconditionally whenever the kill switch is off, even in a dispatched
  // child whose own argv carries `--exclude-tools task,subagent` — the child re-runs this same
  // index.ts, the kill switch env var is still unset there, but the real tool registry has
  // already filtered `task` out (see docs/plugin-platform-decisions.md §9's recursion-guard
  // section). Only pi.getActiveTools(), read after all extensions have finished registering
  // their tools, reflects that filtering — checking the env var here would tell every
  // dispatched agent to use a `task` tool that was deliberately removed from its own
  // function-calling surface.
  function getPreamble(): string {
    if (cachedPreamble === undefined) {
      const taskToolRegistered = pi.getActiveTools().includes(TASK_TOOL_NAME);
      cachedPreamble = composePreamble([...binSection, toolVocabSection(root, taskToolRegistered)]);
    }
    return cachedPreamble;
  }

  pi.on("resources_discover", () => ({
    skillPaths: [join(root, "skills")],
    promptPaths: [join(root, "commands")],
  }));

  pi.on("session_start", (_event, ctx: ExtensionContext) => {
    if (currentScripts === null && !warnedMissingAnchor && ctx.hasUI) {
      warnedMissingAnchor = true;
      ctx.ui.notify(
        "swe-workbench: bin/README.md's '## Current scripts' section could not be read — the " +
          "bin/ script inventory will not be injected into the system prompt this session.",
        "warning",
      );
    }
  });

  pi.on("before_agent_start", (event) => {
    if (event.systemPrompt.includes(PREAMBLE_MARKER)) return;
    return { systemPrompt: event.systemPrompt + getPreamble() };
  });

  // registerGuards must register first: emitToolCall (runner.js:701) runs tool_call handlers in
  // registration order and short-circuits only on `block: true`, so a later-registered guard
  // would be a silent security regression. registerAskUser adds no tool_call handler today, but
  // a future one must be added after this line too — and emitToolCall has no try/catch around a
  // handler's body (unlike emitUserBash), so any future tool_call handler must wrap its own body
  // and return undefined on throw.
  registerGuards(pi, root);
  registerAskUser(pi);
  registerSubagent(pi, root);
}

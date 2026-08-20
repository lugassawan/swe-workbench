/**
 * swe-workbench adapter for Pi Coding Agent (ADR-0001 phase 1, issue #604).
 *
 * Mirrors two harness affordances Claude Code already provides for this plugin, pointing at
 * the SAME skills/ and bin/ trees Claude Code uses — nothing under skills/ is duplicated:
 *   1. `<plugin>/bin` on PATH, so every skill's bare `swe-workbench-<name>` command resolves
 *      unchanged (see bin/README.md).
 *   2. All skills/<name>/SKILL.md directories reachable, via `resources_discover`.
 *
 * Two Pi API facts recorded here so a later phase (#607) does not rediscover them the hard way:
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
 * for PATH exposure or skill discovery, so its absence must degrade the preamble feature alone,
 * never take down the whole extension.
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

  const currentScripts = readCurrentScripts(binDir);
  const preamble =
    currentScripts === null
      ? null
      : composePreamble([
          { title: "swe-workbench bin/ scripts (bare commands, already on PATH)", body: currentScripts },
        ]);

  let warnedMissingAnchor = false;

  pi.on("resources_discover", () => ({ skillPaths: [join(root, "skills")] }));

  pi.on("session_start", (_event, ctx: ExtensionContext) => {
    if (preamble === null && !warnedMissingAnchor && ctx.hasUI) {
      warnedMissingAnchor = true;
      ctx.ui.notify(
        "swe-workbench: bin/README.md's '## Current scripts' section could not be read — the " +
          "bin/ script inventory will not be injected into the system prompt this session.",
        "warning",
      );
    }
  });

  pi.on("before_agent_start", (event) => {
    if (preamble === null) return;
    if (event.systemPrompt.includes(PREAMBLE_MARKER)) return;
    return { systemPrompt: event.systemPrompt + preamble };
  });
}

#!/usr/bin/env node
// --experimental-strip-types is required to load pi/extensions/agent-spec.ts below.
/**
 * Standalone probe: does a real agent dispatch's preloaded prompt (agent body + every preloaded
 * skill body, per composeSystemPrompt() in pi/extensions/agent-spec.ts — background in
 * docs/skill-preload.md) actually get billed by the provider as a cache hit on a second,
 * back-to-back dispatch?
 *
 * `pi --mode json` reports real provider-billed usage (including a dollar cost breakdown) per
 * turn. The `cache` subcommand here dispatches the SAME agent twice in a row, inside the
 * provider's cache TTL, and compares the two turns' usage directly — no estimation needed.
 *
 * This file reproduces (deliberately simplified, see below) the exact dispatch shape the `task`
 * tool builds in pi/extensions/subagent.ts's `execute()`. A later task adds an `ablate`
 * subcommand to this same file (dispatch on process.argv[2]) — shared composition logic below
 * (buildDispatchArgv, resolveAgentDispatch) is written as reusable functions so that addition
 * doesn't require restructuring this file.
 *
 * Deliberate simplifications versus subagent.ts (do not "complete" these — see task-2-brief.md):
 *   - No `--tools`/`--exclude-tools`. subagent.ts derives these from translateToolTokens(), but
 *     this probe only measures prefix caching, not tool-call behavior, and omitting them keeps
 *     the dispatched child from doing real tool-using work (the point is a trivial prompt that
 *     returns fast).
 *   - No `--model`/`--thinking` resolution. subagent.ts derives these from resolveTargetDispatch()
 *     in dispatch-resolver.ts, which requires a live Pi ExtensionContext (ctx.model,
 *     ctx.scopedModels, ctx.modelRegistry) — there is no way to construct one from a standalone
 *     script outside a running Pi session. The invoked `pi` process falls back to its own
 *     configured default model, unless an explicit `--model <provider>/<id>` is passed through
 *     via this probe's own `--model` flag.
 */
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join } from "node:path";

/** Fixed, deterministic prompt for both dispatches — trivial on purpose (see file header: the
 *  point is measuring prefix caching, not exercising real tool-using work). */
const TRIVIAL_PROMPT = "Reply with the single word: ack.";

const USAGE =
  "usage: node --experimental-strip-types scripts/preload-probe.mjs cache --agent <id> " +
  "[--dry-run] [--model <provider>/<id>]";

class UsageError extends Error {}

/** Resolves this plugin's root (repo root) from this script's own location — the script lives in
 *  scripts/, one level below root, mirroring the fileURLToPath(new URL("..", import.meta.url))
 *  pattern this repo's own extensions use for the same purpose. */
function pluginRoot() {
  return fileURLToPath(new URL("..", import.meta.url));
}

/** Parses process.argv.slice(2) into { subcommand, agent, dryRun, model }. Throws UsageError on
 *  any malformed invocation — caller is responsible for turning that into a clear stderr message
 *  and exit 1. */
function parseArgs(argv) {
  const [subcommand, ...rest] = argv;
  let agent;
  let dryRun = false;
  let model;

  for (let i = 0; i < rest.length; i++) {
    const token = rest[i];
    if (token === "--agent") {
      agent = rest[++i];
    } else if (token === "--dry-run") {
      dryRun = true;
    } else if (token === "--model") {
      model = rest[++i];
    } else {
      throw new UsageError(`unrecognized argument "${token}"\n${USAGE}`);
    }
  }

  if (subcommand !== "cache") {
    throw new UsageError(
      `unknown subcommand "${subcommand ?? ""}" — only "cache" is implemented\n${USAGE}`,
    );
  }
  if (!agent) {
    throw new UsageError(`--agent <id> is required\n${USAGE}`);
  }

  return { subcommand, agent, dryRun, model };
}

/** Loads pi/extensions/agent-spec.ts via the same pathToFileURL(...).href dynamic-import pattern
 *  tests/test_pi_extension.py's _run_node helper drives against index.ts — that file is SDK-free
 *  (no @earendil-works/* imports), so this works without node_modules resolvable for its own
 *  imports; only this *script* needs --experimental-strip-types to load a .ts file at all. */
async function loadAgentSpecModule(root) {
  const modulePath = join(root, "pi", "extensions", "agent-spec.ts");
  return import(pathToFileURL(modulePath).href);
}

/** Reads and composes an agent's full dispatch system prompt (body + every preloaded skill's
 *  body, in skills: order) via agent-spec.ts's own exports — no prompt-assembly logic
 *  reimplemented here. Throws with an "available agents" listing (same UX as the `task` tool's
 *  own unknown-agent error in subagent.ts) when `agent` isn't a real agents/*.md id. */
function resolveSystemPrompt(agentSpecModule, root, agent) {
  const { listAgentNames, readAgentSpec, readSkillBody, skillDir, composeSystemPrompt } = agentSpecModule;

  const available = listAgentNames(root);
  if (!available.includes(agent)) {
    throw new Error(`unknown agent "${agent}" — available agents: ${available.join(", ")}`);
  }

  const spec = readAgentSpec(root, agent);
  const skills = spec.skillIds.map((id) => ({ id, body: readSkillBody(root, id), dir: skillDir(root, id) }));
  return composeSystemPrompt(spec, skills);
}

/** Builds the `pi` argv array per the "Argv reproduction" contract: subagent.ts's own shape
 *  (-p, --append-system-prompt, --no-session, --mode json), with --tools/--exclude-tools and
 *  --model/--thinking omitted per the simplifications in this file's header — plus an optional
 *  passthrough --model when the caller supplied one. Pure — takes the already-resolved prompt
 *  file path rather than touching the filesystem itself, so the same function serves both the
 *  --dry-run path (a path that is never written) and the live path (a real temp file). */
function buildDispatchArgv({ promptFilePath, model }) {
  const args = ["-p", TRIVIAL_PROMPT, "--append-system-prompt", promptFilePath, "--no-session", "--mode", "json"];
  if (model) {
    args.push("--model", model);
  }
  return args;
}

/** Runs `pi` once with the given argv and captures stdout as text. Throws (with captured stderr)
 *  on a missing binary or non-zero exit — never swallows a dispatch failure. */
function runPiOnce(args) {
  const result = spawnSync("pi", args, { encoding: "utf8" });
  if (result.error) {
    throw new Error(`failed to spawn "pi": ${result.error.message}`);
  }
  if (result.status !== 0) {
    const stderr = (result.stderr ?? "").trim() || "(no stderr)";
    throw new Error(
      `pi exited ${result.status}${result.signal ? ` (signal ${result.signal})` : ""} — ${stderr}`,
    );
  }
  return result.stdout ?? "";
}

/** Parses `pi --mode json` NDJSON output and returns the usage object from the LAST
 *  `message_update` line (usage is cumulative per turn, so the last line carries the turn's final
 *  usage). Lines that aren't valid JSON, or JSON without the right shape, are skipped
 *  defensively — never crash on a stray non-JSON line. Returns null if no message_update line was
 *  found. */
function lastMessageUpdateUsage(ndjson) {
  let lastUsage = null;
  for (const line of ndjson.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try {
      obj = JSON.parse(trimmed);
    } catch {
      continue;
    }
    if (obj && obj.type === "message_update" && obj.usage) {
      lastUsage = obj.usage;
    }
  }
  return lastUsage;
}

/** Fraction of input tokens that were served from cache, guarding divide-by-zero. */
function cacheReadFraction(usage) {
  const denom = usage.input + usage.cacheRead;
  return denom === 0 ? 0 : usage.cacheRead / denom;
}

function formatRunSummary(label, usage) {
  const lines = [`${label}:`];
  if (!usage) {
    lines.push("  no message_update usage found in this run's output");
    return lines.join("\n");
  }
  lines.push(`  input=${usage.input} cacheRead=${usage.cacheRead} cacheWrite=${usage.cacheWrite}`);
  lines.push(`  cost.total=$${usage.cost?.total ?? "?"}`);
  lines.push(`  cacheReadFraction=${cacheReadFraction(usage).toFixed(4)}`);
  return lines.join("\n");
}

async function main(argv) {
  const { agent, dryRun, model } = parseArgs(argv);
  const root = pluginRoot();
  const agentSpecModule = await loadAgentSpecModule(root);
  const systemPrompt = resolveSystemPrompt(agentSpecModule, root, agent);

  if (dryRun) {
    // Per contract: print the constructed argv WITHOUT spawning pi or making a temp file. The
    // path below is never written to disk — it's a representative placeholder for the position
    // --append-system-prompt's real value would occupy on a live run.
    const placeholderPromptFilePath = join(tmpdir(), "swe-workbench-preload-probe-dry-run", "system-prompt.md");
    const args = buildDispatchArgv({ promptFilePath: placeholderPromptFilePath, model });
    console.log(JSON.stringify(args));
    return;
  }

  const tmpDir = mkdtempSync(join(tmpdir(), "swe-workbench-preload-probe-"));
  const promptFilePath = join(tmpDir, "system-prompt.md");
  try {
    writeFileSync(promptFilePath, systemPrompt, { mode: 0o600 });
    const args = buildDispatchArgv({ promptFilePath, model });

    const firstStdout = runPiOnce(args);
    const secondStdout = runPiOnce(args);

    const firstUsage = lastMessageUpdateUsage(firstStdout);
    const secondUsage = lastMessageUpdateUsage(secondStdout);

    console.log(formatRunSummary("run 1 (cold)", firstUsage));
    console.log(formatRunSummary("run 2 (repeat, same prefix)", secondUsage));

    const cacheHit = Boolean(secondUsage && secondUsage.cacheRead > 0);
    console.log(
      cacheHit
        ? "cache: YES — run 2 showed cache-read activity (cacheRead > 0)"
        : "cache: NO — run 2 showed no cache-read activity (cacheRead == 0 or missing)",
    );
  } finally {
    // Unlink then rmdir, tolerate ENOENT on both — same posture as subagent.ts's temp-file
    // cleanup.
    try {
      unlinkSync(promptFilePath);
    } catch (err) {
      if (err.code !== "ENOENT") throw err;
    }
    try {
      rmdirSync(tmpDir);
    } catch (err) {
      if (err.code !== "ENOENT") throw err;
    }
  }
}

try {
  await main(process.argv.slice(2));
} catch (err) {
  if (err instanceof UsageError) {
    console.error(err.message);
  } else {
    console.error(`preload-probe: ${err.message}`);
  }
  process.exit(1);
}

#!/usr/bin/env node
// --experimental-strip-types is required to load pi/extensions/agent-spec.ts below.
/**
 * Standalone probe: does a real agent dispatch's preloaded prompt (agent body + every preloaded
 * skill body, per composeSystemPrompt() in pi/extensions/agent-spec.ts — background in
 * docs/skill-preload.md) actually get billed by the provider as a cache hit on a second,
 * back-to-back dispatch (the `cache` subcommand), and does removing one preloaded skill change
 * what a reviewer-shaped agent actually flags on a real diff (the `ablate` subcommand)?
 *
 * `pi --mode json` reports real provider-billed usage (including a dollar cost breakdown) per
 * turn, and streams every session event (message_start/message_update/message_end/...) as one
 * JSON object per line. The `cache` subcommand dispatches the SAME agent twice in a row, inside
 * the provider's cache TTL, and compares the two turns' usage directly — no estimation needed.
 * The `ablate` subcommand dispatches an agent twice per corpus diff — once with its full,
 * unmodified preload, once with one skill filtered out — and diffs the two runs' reported
 * findings.
 *
 * This file reproduces (deliberately simplified, see below) the exact dispatch shape the `task`
 * tool builds in pi/extensions/subagent.ts's `execute()`.
 *
 * Deliberate simplifications versus subagent.ts — each is a choice, not an omission to fix:
 *   - No `--tools`/`--exclude-tools`. subagent.ts derives these from translateToolTokens(), but
 *     this probe only measures prefix caching / preload content, not tool-call behavior, and
 *     omitting them keeps the dispatched child from doing real tool-using work (the point is a
 *     prompt that returns fast and whose only job is producing text).
 *   - No `--model`/`--thinking` resolution. subagent.ts derives these from resolveTargetDispatch()
 *     in dispatch-resolver.ts, which requires a live Pi ExtensionContext (ctx.model,
 *     ctx.scopedModels, ctx.modelRegistry) — there is no way to construct one from a standalone
 *     script outside a running Pi session. The invoked `pi` process falls back to its own
 *     configured default model, unless an explicit `--model <provider>/<id>` is passed through
 *     via this probe's own `--model` flag.
 */
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmdirSync, unlinkSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join } from "node:path";
import { compareArm, extractDispatchError, extractFinalAssistantText, parsePipeDelimitedFindings } from "./preload-probe-lib.mjs";

/** Fixed, deterministic prompt for the `cache` subcommand's two dispatches — trivial on purpose
 *  (see file header: the point is measuring prefix caching, not exercising real tool-using
 *  work). */
const TRIVIAL_PROMPT = "Reply with the single word: ack.";

/** Fixed instruction prefix for every `ablate` dispatch — kept constant, named, and identical
 *  across every arm/diff so the ONLY variable between a baseline and omit-arm dispatch is the
 *  presence/absence of the omitted skill's body in the system prompt. */
const ABLATE_REVIEW_PROMPT_PREFIX = "Review this diff:\n\n";

const USAGE =
  "usage:\n" +
  "  node --experimental-strip-types scripts/preload-probe.mjs cache --agent <id> [--dry-run] [--model <provider>/<id>]\n" +
  "  node --experimental-strip-types scripts/preload-probe.mjs ablate --agent <id> --corpus <dir> --omit <skill-id> [--dry-run] [--model <provider>/<id>]\n" +
  "  node --experimental-strip-types scripts/preload-probe.mjs ablate --report [--agent <id>]";

class UsageError extends Error {}

/** Resolves this plugin's root (repo root) from this script's own location — the script lives in
 *  scripts/, one level below root, mirroring the fileURLToPath(new URL("..", import.meta.url))
 *  pattern this repo's own extensions use for the same purpose. */
function pluginRoot() {
  return fileURLToPath(new URL("..", import.meta.url));
}

/** Parses process.argv.slice(2) into a mode-tagged options object. Throws UsageError on any
 *  malformed invocation — caller is responsible for turning that into a clear stderr message and
 *  exit 1.
 *
 *  Returns one of:
 *    { subcommand: "cache", agent, dryRun, model }
 *    { subcommand: "ablate", mode: "run", agent, corpus, omit, dryRun, model }
 *    { subcommand: "ablate", mode: "report", agent }  // agent optional (undefined = all agents)
 */
function parseArgs(argv) {
  const [subcommand, ...rest] = argv;

  if (subcommand !== "cache" && subcommand !== "ablate") {
    throw new UsageError(
      `unknown subcommand "${subcommand ?? ""}" — only "cache" and "ablate" are implemented\n${USAGE}`,
    );
  }

  if (subcommand === "cache") {
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
    if (!agent) {
      throw new UsageError(`--agent <id> is required\n${USAGE}`);
    }
    return { subcommand, agent, dryRun, model };
  }

  // subcommand === "ablate"
  let agent;
  let corpus;
  let omit;
  let dryRun = false;
  let model;
  let report = false;
  for (let i = 0; i < rest.length; i++) {
    const token = rest[i];
    if (token === "--agent") {
      agent = rest[++i];
    } else if (token === "--corpus") {
      corpus = rest[++i];
    } else if (token === "--omit") {
      omit = rest[++i];
    } else if (token === "--dry-run") {
      dryRun = true;
    } else if (token === "--model") {
      model = rest[++i];
    } else if (token === "--report") {
      report = true;
    } else {
      throw new UsageError(`unrecognized argument "${token}"\n${USAGE}`);
    }
  }

  if (report) {
    return { subcommand, mode: "report", agent };
  }

  if (!agent) {
    throw new UsageError(`--agent <id> is required\n${USAGE}`);
  }
  if (!corpus) {
    throw new UsageError(`--corpus <dir> is required\n${USAGE}`);
  }
  if (!omit) {
    throw new UsageError(`--omit <skill-id> is required\n${USAGE}`);
  }
  return { subcommand, mode: "run", agent, corpus, omit, dryRun, model };
}

/** Loads pi/extensions/agent-spec.ts via the same pathToFileURL(...).href dynamic-import pattern
 *  tests/test_pi_extension.py's _run_node helper drives against index.ts — that file is SDK-free
 *  (no @earendil-works/* imports), so this works without node_modules resolvable for its own
 *  imports; only this *script* needs --experimental-strip-types to load a .ts file at all. */
async function loadAgentSpecModule(root) {
  const modulePath = join(root, "pi", "extensions", "agent-spec.ts");
  return import(pathToFileURL(modulePath).href);
}

/** Reads an agent's spec, throwing with an "available agents" listing (same UX as the `task`
 *  tool's own unknown-agent error in subagent.ts) when `agent` isn't a real agents/*.md id. */
function resolveAgentSpecOrThrow(agentSpecModule, root, agent) {
  const { listAgentNames, readAgentSpec } = agentSpecModule;
  const available = listAgentNames(root);
  if (!available.includes(agent)) {
    throw new Error(`unknown agent "${agent}" — available agents: ${available.join(", ")}`);
  }
  return readAgentSpec(root, agent);
}

/** Composes a system prompt for an explicit list of skill ids (rather than always
 *  `spec.skillIds`) — the shared building block both `resolveSystemPrompt` (cache, full preload)
 *  and the ablate arms (full preload vs. one skill filtered out) are built from, via
 *  agent-spec.ts's own exports. No prompt-assembly logic reimplemented here. */
function composePromptForSkillIds(agentSpecModule, root, spec, skillIds) {
  const { readSkillBody, skillDir, composeSystemPrompt } = agentSpecModule;
  const skills = skillIds.map((id) => ({ id, body: readSkillBody(root, id), dir: skillDir(root, id) }));
  return composeSystemPrompt(spec, skills);
}

/** Resolves an agent's full dispatch system prompt (body + every preloaded skill's body, in
 *  `skills:` order) — the `cache` subcommand's dispatch prompt. */
function resolveSystemPrompt(agentSpecModule, root, agent) {
  const spec = resolveAgentSpecOrThrow(agentSpecModule, root, agent);
  return composePromptForSkillIds(agentSpecModule, root, spec, spec.skillIds);
}

/** `agents/*.md`'s `skills:` entries are namespaced (`swe-workbench:<id>`), per
 *  pi/extensions/agent-spec.ts's `AgentSpec.skillIds`. That file's own `bareSkillId()` helper
 *  (strips the `swe-workbench:` prefix) is private/unexported, so this is the same one-line
 *  strip re-implemented locally here — not an import of a private helper. */
const SKILL_NAMESPACE_PREFIX = "swe-workbench:";
function bareSkillId(skillId) {
  return skillId.startsWith(SKILL_NAMESPACE_PREFIX) ? skillId.slice(SKILL_NAMESPACE_PREFIX.length) : skillId;
}

/** Resolves both ablate arms' system prompts for one (agent, omit) pair: the baseline arm (full,
 *  unmodified `spec.skillIds`) and the omit arm (`spec.skillIds` filtered to exclude the skill
 *  whose bare id matches `omitBare`, leaving every other skill and the agent body untouched).
 *  Fails fast — before any dispatch — if `omitBare` isn't actually among the agent's preloaded
 *  skills in bare form, naming the agent's actual preloaded skill ids in the error: an omit-arm
 *  that isn't really missing anything would make the whole ablation run pointless. */
function resolveAblateArms(agentSpecModule, root, agent, omitBare) {
  const spec = resolveAgentSpecOrThrow(agentSpecModule, root, agent);
  const bareIds = spec.skillIds.map(bareSkillId);
  if (!bareIds.includes(omitBare)) {
    throw new Error(
      `--omit "${omitBare}" is not among agent "${agent}"'s preloaded skills (bare form) — ` +
        `actual preloaded skill ids: ${bareIds.join(", ")}`,
    );
  }
  const omitSkillIds = spec.skillIds.filter((id) => bareSkillId(id) !== omitBare);
  const baselinePrompt = composePromptForSkillIds(agentSpecModule, root, spec, spec.skillIds);
  const omitPrompt = composePromptForSkillIds(agentSpecModule, root, spec, omitSkillIds);
  return { spec, baselinePrompt, omitPrompt };
}

/** Lists `*.diff` files (sorted, for determinism) directly under `corpusDir`. Throws a clear
 *  error if the directory doesn't exist/isn't readable, or exists but contains no `*.diff`
 *  files — both are clear, non-zero-exit errors, not silently treated as an empty corpus. */
function listCorpusDiffFiles(corpusDir) {
  let entries;
  try {
    entries = readdirSync(corpusDir, { withFileTypes: true });
  } catch (err) {
    throw new Error(`--corpus directory not found or not readable: "${corpusDir}" (${err.message})`);
  }
  const files = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".diff"))
    .map((entry) => entry.name)
    .sort();
  if (files.length === 0) {
    throw new Error(`--corpus directory contains no *.diff files: "${corpusDir}"`);
  }
  return files;
}

/** Builds the `pi` argv array per the "Argv reproduction" contract: subagent.ts's own shape
 *  (-p, --append-system-prompt, --no-session, --mode json), with --tools/--exclude-tools and
 *  --model/--thinking omitted per the simplifications in this file's header — plus an optional
 *  passthrough --model when the caller supplied one. Pure — takes the already-resolved prompt
 *  file path rather than touching the filesystem itself, so the same function serves both the
 *  --dry-run path (a path that is never written) and the live path (a real temp file). `prompt`
 *  defaults to the `cache` subcommand's TRIVIAL_PROMPT; `ablate` passes its own diff-review
 *  prompt through the same parameter — this is the ONE shared dispatch-argv builder for both
 *  subcommands, not a duplicate. */
function buildDispatchArgv({ prompt = TRIVIAL_PROMPT, promptFilePath, model }) {
  const args = ["-p", prompt, "--append-system-prompt", promptFilePath, "--no-session", "--mode", "json"];
  if (model) {
    args.push("--model", model);
  }
  return args;
}

/** Wall-clock ceiling for one `pi` dispatch, matching pi/extensions/subagent.ts's own
 *  TASK_TIMEOUT_MS (15 minutes) — this probe reproduces that file's dispatch shape, so it takes
 *  the same bound. Without it a hung provider call hangs the probe indefinitely. */
const DISPATCH_TIMEOUT_MS = 15 * 60 * 1000;

/** stdout/stderr capture ceiling for one `pi` dispatch. Node's spawnSync default is 1 MiB, which
 *  an `ablate` run's NDJSON event stream over a real diff review can plausibly exceed — and
 *  exceeding it kills the child and surfaces an error only AFTER the live provider call has
 *  already been paid for. 50 MiB is deliberately generous, matching subagent.ts's
 *  OUTPUT_CAP_CHARS posture of capping well clear of realistic output rather than silently
 *  truncating at a default. */
const DISPATCH_MAX_BUFFER_BYTES = 50 * 1024 * 1024;

/** Runs `pi` once with the given argv and captures stdout as text. Throws (with captured stderr)
 *  on a missing binary, a timeout, an output-size overrun, or a non-zero exit — never swallows a
 *  dispatch failure. */
function runPiOnce(args) {
  const result = spawnSync("pi", args, {
    encoding: "utf8",
    timeout: DISPATCH_TIMEOUT_MS,
    maxBuffer: DISPATCH_MAX_BUFFER_BYTES,
  });
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

/** Writes `systemPrompt` to a fresh temp file, runs `fn(promptFilePath)`, and always cleans up —
 *  the shared temp-file dance both the `cache` subcommand (one temp file, two dispatches reusing
 *  it) and `ablate` (one temp file per arm, since each arm's system prompt differs) build on, so
 *  neither duplicates the mkdtemp/write/unlink/rmdir sequence. Unlink then rmdir, tolerate ENOENT
 *  on both — same posture subagent.ts's own temp-file cleanup uses. */
function withTempSystemPromptFile(systemPrompt, fn) {
  const tmpDir = mkdtempSync(join(tmpdir(), "swe-workbench-preload-probe-"));
  const promptFilePath = join(tmpDir, "system-prompt.md");
  try {
    writeFileSync(promptFilePath, systemPrompt, { mode: 0o600 });
    return fn(promptFilePath);
  } finally {
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

// extractFinalAssistantText, parsePipeDelimitedFindings, and SEVERITY_RANK now live in
// ./preload-probe-lib.mjs (imported above) — factored out so the pipe-delimited finding parser
// is a standalone, independently-testable pure function.

/** Resolves the dispatch-probes cache directory the same way hooks/skill_usage_flush.sh's
 *  `cache_dir` resolves its own cache dir (`${CLAUDE_PROJECT_DIR:-$PWD}/.claude/cache/skill-usage`)
 *  — same env-var-or-cwd fallback, different leaf directory: durable dispatch-probe run records
 *  live in dispatch-probes/, not skill-usage/. Shared by both `cache-runs.jsonl` and
 *  `ablation-runs.jsonl` — same directory, sibling files. */
function cacheRunsDir() {
  const base = process.env.CLAUDE_PROJECT_DIR ?? process.cwd();
  return join(base, ".claude", "cache", "dispatch-probes");
}

/** Appends one JSON record for a single dispatch run to cache-runs.jsonl — live path only, one
 *  call per run (two per invocation). `preload-telemetry.py cache` reads these back to report a
 *  durable, aggregable cache-vs-fresh comparison across invocations, rather than only the
 *  single-invocation summary this script prints. Never throws: an append failure (permissions,
 *  disk) is a warning on stderr, not a reason to fail the whole probe — the human-readable
 *  summary this script already prints to stdout is still the primary output. No-ops (nothing to
 *  record, nothing to warn about) when `usage` is null, i.e. no message_update line was found
 *  for that run. */
function appendCacheRunRecord(agent, run, usage) {
  if (!usage) return;
  const record = {
    agent,
    run,
    usage: {
      input: usage.input,
      output: usage.output,
      cacheRead: usage.cacheRead,
      cacheWrite: usage.cacheWrite,
      cost: usage.cost,
    },
    cacheReadFraction: cacheReadFraction(usage),
    ts: new Date().toISOString(),
  };
  try {
    const dir = cacheRunsDir();
    mkdirSync(dir, { recursive: true });
    appendFileSync(join(dir, "cache-runs.jsonl"), `${JSON.stringify(record)}\n`);
  } catch (err) {
    console.error(`preload-probe: warning: failed to append cache-run record: ${err.message}`);
  }
}

/** Appends one JSON record for a single ablate dispatch arm to ablation-runs.jsonl (sibling of
 *  cache-runs.jsonl, same directory-resolution/mkdir -p logic reused via cacheRunsDir() rather
 *  than duplicated). Record shape: `{diff, agent, omitted, findings[]}`, with `omitted: null` for
 *  the baseline arm and `omitted: "<bare-skill-id>"` (the exact string the caller passed to
 *  `--omit`) for the omit arm. Same never-throws-on-append-failure posture as
 *  appendCacheRunRecord. */
function appendAblationRunRecord(diffFilename, agent, omitted, findings) {
  const record = { diff: diffFilename, agent, omitted, findings };
  try {
    const dir = cacheRunsDir();
    mkdirSync(dir, { recursive: true });
    appendFileSync(join(dir, "ablation-runs.jsonl"), `${JSON.stringify(record)}\n`);
  } catch (err) {
    console.error(`preload-probe: warning: failed to append ablation-run record: ${err.message}`);
  }
}

function ablationRunsFilePath() {
  return join(cacheRunsDir(), "ablation-runs.jsonl");
}

/** Fraction of input tokens that were served from cache, guarding divide-by-zero. */
function cacheReadFraction(usage) {
  const denom = usage.input + usage.cacheRead;
  return denom === 0 ? 0 : usage.cacheRead / denom;
}

/** Parses one dispatch's NDJSON into its final usage, hard-failing when the turn died before
 *  reporting any — a dispatch with no usage is not a measurement (see extractDispatchError in
 *  preload-probe-lib.mjs for the exit-0-despite-provider-error ground truth). The provider's own
 *  errorMessage is surfaced verbatim when present. */
function usageOrDispatchError(ndjson, label) {
  const usage = lastMessageUpdateUsage(ndjson);
  if (usage) return usage;
  const dispatchError = extractDispatchError(ndjson);
  throw new Error(`${label}: ${dispatchError ?? "no message_update usage found in this run's output"}`);
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

/** Dispatches one ablate arm (a single `pi --mode json` run) and returns its parsed findings.
 *  Reuses withTempSystemPromptFile (temp-file handling), buildDispatchArgv (argv construction),
 *  and runPiOnce (spawn) — the exact same helpers the `cache` subcommand's dispatch uses, just
 *  with an explicit `prompt` (the diff-review prompt) instead of the default TRIVIAL_PROMPT, and
 *  a text extractor instead of a usage extractor. A missing assistant `message_end` (extractor
 *  returns null) is a warning, not a hard failure — treated as zero findings, consistent with
 *  `cache`'s own "no usage found" being reported rather than thrown. */
function dispatchArmFindings({ systemPrompt, prompt, model }) {
  return withTempSystemPromptFile(systemPrompt, (promptFilePath) => {
    const args = buildDispatchArgv({ prompt, promptFilePath, model });
    const stdout = runPiOnce(args);
    // An errored dispatch would otherwise parse as "" here and be recorded as a clean
    // zero-findings arm — silently corrupting the ablation comparison.
    const dispatchError = extractDispatchError(stdout);
    if (dispatchError) {
      throw new Error(`dispatch failed before producing findings — ${dispatchError}`);
    }
    const text = extractFinalAssistantText(stdout);
    if (text === null) {
      console.error("preload-probe: warning: no assistant message_end found in this run's output");
    }
    return parsePipeDelimitedFindings(text ?? "");
  });
}

/** Prints both arms' composed-prefix lengths and the line-level diff between them, per
 *  `--dry-run`'s contract: confirm the omitted skill's body is excluded and nothing else
 *  changed, without dispatching. Composition is append-only sections (agent body, then each
 *  skill's section, joined by a fixed separator — composeSystemPrompt in agent-spec.ts), so the
 *  omit arm's lines are always a subset of the baseline arm's; a simple set-difference is enough
 *  to confirm "nothing else changed" without needing a real diff algorithm. */
function printAblateDryRunSummary({ omit, baselinePrompt, omitPrompt, corpusFileCount }) {
  const baselineLen = baselinePrompt.length;
  const omitLen = omitPrompt.length;
  console.log(`corpus: ${corpusFileCount} *.diff file(s) found`);
  console.log(`baseline prefix length: ${baselineLen} chars`);
  console.log(`omit(${omit}) prefix length: ${omitLen} chars`);
  console.log(`prefix length diff (baseline - omit): ${baselineLen - omitLen} chars`);

  const baselineLines = new Set(baselinePrompt.split("\n"));
  const omitLines = new Set(omitPrompt.split("\n"));
  const extraInOmit = [...omitLines].filter((line) => !baselineLines.has(line));
  console.log(
    extraInOmit.length === 0
      ? "confirmed: omit arm introduces no lines absent from baseline (pure subset removal)"
      : `WARNING: ${extraInOmit.length} line(s) in omit arm not present in baseline — expected 0`,
  );
}

async function mainCache({ agent, dryRun, model }) {
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

  const { firstUsage, secondUsage } = withTempSystemPromptFile(systemPrompt, (promptFilePath) => {
    const args = buildDispatchArgv({ promptFilePath, model });
    return {
      firstUsage: usageOrDispatchError(runPiOnce(args), "run 1 (cold)"),
      secondUsage: usageOrDispatchError(runPiOnce(args), "run 2 (repeat, same prefix)"),
    };
  });

  appendCacheRunRecord(agent, 1, firstUsage);
  appendCacheRunRecord(agent, 2, secondUsage);

  console.log(formatRunSummary("run 1 (cold)", firstUsage));
  console.log(formatRunSummary("run 2 (repeat, same prefix)", secondUsage));

  const cacheHit = Boolean(secondUsage && secondUsage.cacheRead > 0);
  console.log(
    cacheHit
      ? "cache: YES — run 2 showed cache-read activity (cacheRead > 0)"
      : "cache: NO — run 2 showed no cache-read activity (cacheRead == 0 or missing)",
  );
}

async function mainAblateRun({ agent, corpus, omit, dryRun, model }) {
  const root = pluginRoot();
  const agentSpecModule = await loadAgentSpecModule(root);
  const { baselinePrompt, omitPrompt } = resolveAblateArms(agentSpecModule, root, agent, omit);
  // Validated even under --dry-run: a bad --corpus is a usage mistake worth catching before the
  // (expensive, real-money) live pilot, and dry-run's own summary reports the file count.
  const files = listCorpusDiffFiles(corpus);

  if (dryRun) {
    printAblateDryRunSummary({ omit, baselinePrompt, omitPrompt, corpusFileCount: files.length });
    return;
  }

  for (const filename of files) {
    const diffContent = readFileSync(join(corpus, filename), "utf8");
    const prompt = `${ABLATE_REVIEW_PROMPT_PREFIX}${diffContent}`;

    const baselineFindings = dispatchArmFindings({ systemPrompt: baselinePrompt, prompt, model });
    appendAblationRunRecord(filename, agent, null, baselineFindings);
    console.log(`${filename} baseline: ${baselineFindings.length} finding(s)`);

    const omitFindings = dispatchArmFindings({ systemPrompt: omitPrompt, prompt, model });
    appendAblationRunRecord(filename, agent, omit, omitFindings);
    console.log(`${filename} omit(${omit}): ${omitFindings.length} finding(s)`);
  }
}

/** Reads ablation-runs.jsonl back into an array of records. Returns null (distinct from an empty
 *  array) when the file doesn't exist at all — the "no data yet" case report mode needs to
 *  distinguish from "data exists but nothing matched the --agent filter". Malformed lines are
 *  skipped defensively, same posture as lastMessageUpdateUsage. */
function readAblationRecords() {
  const path = ablationRunsFilePath();
  if (!existsSync(path)) return null;
  const text = readFileSync(path, "utf8");
  const records = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      records.push(JSON.parse(trimmed));
    } catch {
      continue;
    }
  }
  return records;
}

/** Groups ablation-runs.jsonl records by agent, splitting each agent's records into its baseline
 *  records (keyed by diff filename — `omitted: null`) and its omit-arm records (kept as a flat
 *  list, each still carrying its own `diff`/`omitted` fields, since one agent can have several
 *  different omitted skills' worth of runs). Records missing required fields, or excluded by
 *  `agentFilter`, are skipped. */
function groupAblationRecords(records, agentFilter) {
  const byAgent = new Map();
  for (const rec of records) {
    if (!rec || typeof rec !== "object" || !rec.diff || !rec.agent) continue;
    if (agentFilter && rec.agent !== agentFilter) continue;
    let bucket = byAgent.get(rec.agent);
    if (!bucket) {
      bucket = { baselineByDiff: new Map(), omitRecords: [] };
      byAgent.set(rec.agent, bucket);
    }
    if (rec.omitted === null || rec.omitted === undefined) {
      bucket.baselineByDiff.set(rec.diff, Array.isArray(rec.findings) ? rec.findings : []);
    } else {
      bucket.omitRecords.push(rec);
    }
  }
  return byAgent;
}

// compareArm (the baseline-vs-omit-arm matching heuristic, documented in detail in
// ./preload-probe-lib.mjs) is imported above, alongside the other pure ablate-report helpers.

function reportAblation(agentFilter) {
  const records = readAblationRecords();
  if (records === null) {
    console.log(
      "no ablation-run data collected yet — run:\n" +
        "  node --experimental-strip-types scripts/preload-probe.mjs ablate --agent <id> --corpus <dir> --omit <skill-id>\n" +
        "first, then re-run --report.",
    );
    return;
  }

  const byAgent = groupAblationRecords(records, agentFilter);
  if (byAgent.size === 0) {
    console.log(
      `no ablation-run data collected yet${agentFilter ? ` for agent "${agentFilter}"` : ""} — run ` +
        "ablate first, then re-run --report.",
    );
    return;
  }

  for (const [agent, bucket] of byAgent) {
    const omittedSkills = [...new Set(bucket.omitRecords.map((rec) => rec.omitted))];
    for (const omitted of omittedSkills) {
      let totalLost = 0;
      let totalDowngraded = 0;
      const perDiffLines = [];

      for (const rec of bucket.omitRecords.filter((r) => r.omitted === omitted)) {
        const baselineFindings = bucket.baselineByDiff.get(rec.diff);
        if (!baselineFindings) {
          console.error(
            `preload-probe: warning: no baseline record found for diff "${rec.diff}" (agent "${agent}") — skipping`,
          );
          continue;
        }
        const omitFindings = Array.isArray(rec.findings) ? rec.findings : [];
        const { lost, downgraded } = compareArm(baselineFindings, omitFindings);
        totalLost += lost.length;
        totalDowngraded += downgraded.length;

        if (lost.length > 0 || downgraded.length > 0) {
          perDiffLines.push(`  ${rec.diff}:`);
          for (const finding of lost) {
            perDiffLines.push(`    lost: ${finding.fileLine} (${finding.severity})`);
          }
          for (const d of downgraded) {
            perDiffLines.push(`    downgraded: ${d.baseline.fileLine} ${d.baseline.severity} -> ${d.omit.severity}`);
          }
        }
      }

      console.log(`agent=${agent} omitted=${omitted}: lost=${totalLost} downgraded=${totalDowngraded}`);
      for (const line of perDiffLines) {
        console.log(line);
      }
    }
  }
}

async function main(argv) {
  const parsed = parseArgs(argv);

  if (parsed.subcommand === "cache") {
    return mainCache(parsed);
  }

  // subcommand === "ablate"
  if (parsed.mode === "report") {
    reportAblation(parsed.agent);
    return;
  }
  return mainAblateRun(parsed);
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

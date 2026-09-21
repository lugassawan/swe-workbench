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
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join } from "node:path";
import {
  extractFinalAssistantText,
  formatPiSpawnError,
  modelIdentityOrDispatchError,
  parseAblationResponse,
  planAblationArms,
  summarizeAblationRecords,
  usageOrDispatchError,
  validateAblationRecord,
} from "./preload-probe-lib.mjs";

/** Fixed, deterministic prompt for the `cache` subcommand's two dispatches — trivial on purpose
 *  (see file header: the point is measuring prefix caching, not exercising real tool-using
 *  work). */
const TRIVIAL_PROMPT = "Reply with the single word: ack.";

/** Fixed instruction prefix for every `ablate` dispatch — kept constant, named, and identical
 *  across every arm/diff so the ONLY variable between a baseline and omit-arm dispatch is the
 *  presence/absence of the omitted skill's body in the system prompt. */
const ABLATE_REVIEW_PROMPT_PREFIX = "Review this diff:\n\n";

const ABLATE_OUTPUT_CONTRACT = `## Ablation probe output contract

For this probe, replace the agent's normal response shape with exactly one of:

- One finding per line: \`Severity | File:Line | Issue | Why it matters | Suggested fix\`
- \`No ablation issues found in this diff.\` when there are no findings

Do not emit headings, prose, tables, code fences, summaries, or review decisions. Preserve the
mandatory \`SWB-CANARIES-APPLIED: ...\` footer when the agent instructions require it.`;

const USAGE =
  "usage:\n" +
  "  node --experimental-strip-types scripts/preload-probe.mjs cache --agent <id> [--dry-run] [--model <provider>/<id>]\n" +
  "  node --experimental-strip-types scripts/preload-probe.mjs ablate --agent <id> --corpus <dir> --omit <skill-id> --sweep <id> --model <provider>/<id> [--dry-run]\n" +
  "  node --experimental-strip-types scripts/preload-probe.mjs ablate --report --sweep <id> [--agent <id>]";

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
 *    { subcommand: "ablate", mode: "run", agent, corpus, omit, sweep, dryRun, model }
 *    { subcommand: "ablate", mode: "report", sweep, agent }  // agent optional
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
  let sweep;
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
    } else if (token === "--sweep") {
      sweep = rest[++i];
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
    if (!sweep) {
      throw new UsageError(`--sweep <id> is required in report mode\n${USAGE}`);
    }
    return { subcommand, mode: "report", sweep, agent };
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
  return { subcommand, mode: "run", agent, corpus, omit, sweep, dryRun, model };
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
  const withOutputContract = (prompt) => `${prompt}\n\n---\n\n${ABLATE_OUTPUT_CONTRACT}`;
  const baselinePrompt = withOutputContract(
    composePromptForSkillIds(agentSpecModule, root, spec, spec.skillIds),
  );
  const omitPrompt = withOutputContract(
    composePromptForSkillIds(agentSpecModule, root, spec, omitSkillIds),
  );
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

function sha256(parts) {
  const hash = createHash("sha256");
  for (const part of parts) hash.update(part);
  return `sha256:${hash.digest("hex")}`;
}

function snapshotCorpus(corpusDir, files) {
  const parts = [];
  const contents = new Map();
  for (const filename of files) {
    const content = readFileSync(join(corpusDir, filename), "utf8");
    contents.set(filename, content);
    parts.push(`${filename}\0`, content, "\0");
  }
  return {
    metadata: { fingerprint: sha256(parts), files },
    contents,
  };
}

function cleanGitCommit(root) {
  const commit = spawnSync("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8" });
  if (commit.status !== 0) {
    throw new Error(`cannot resolve git commit: ${(commit.stderr ?? "").trim() || "git failed"}`);
  }
  const status = spawnSync("git", ["-C", root, "status", "--porcelain"], { encoding: "utf8" });
  if (status.status !== 0) {
    throw new Error(`cannot inspect git status: ${(status.stderr ?? "").trim() || "git failed"}`);
  }
  if ((status.stdout ?? "").trim()) {
    throw new Error("live ablation requires a clean git worktree so its commit is reproducible");
  }
  return commit.stdout.trim();
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

/** Runs `pi` once with the given argv and captures stdout as text. Spawn failures expose only
 *  sanitized progress metadata; non-zero exits retain stderr. No dispatch failure is swallowed. */
function runPiOnce(args, label) {
  const startedAt = Date.now();
  const result = spawnSync("pi", args, {
    timeout: DISPATCH_TIMEOUT_MS,
    maxBuffer: DISPATCH_MAX_BUFFER_BYTES,
  });
  const elapsedMs = Math.max(0, Date.now() - startedAt);
  const stdout = result.stdout?.toString("utf8") ?? "";
  const stderr = result.stderr?.toString("utf8") ?? "";
  if (result.error) {
    throw new Error(
      formatPiSpawnError({
        errorCode: result.error.code,
        errorMessage: result.error.message,
        label,
        elapsedMs,
        timeoutMs: DISPATCH_TIMEOUT_MS,
        stdout,
        stderr,
        stdoutBytes: result.stdout?.length ?? 0,
        stderrBytes: result.stderr?.length ?? 0,
      }),
    );
  }
  if (result.status !== 0) {
    const diagnosticStderr = stderr.trim() || "(no stderr)";
    throw new Error(
      `pi exited ${result.status}${result.signal ? ` (signal ${result.signal})` : ""} — ${diagnosticStderr}`,
    );
  }
  return stdout;
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

// Pure response parsing, usage/model gates, resume planning, and report aggregation live in
// ./preload-probe-lib.mjs so paid-dispatch integrity rules are independently testable.

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
 *  record, nothing to warn about) when `usage` is null — unreachable via the cache path's
 *  usageOrDispatchError gate (which throws first); kept as defense-in-depth for future callers. */
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

/** Persists one authoritative ablation arm. Unlike cache telemetry, ablation reporting
 *  depends on durable per-arm evidence, so a write failure aborts the sweep. */
function appendAblationRunRecord(record) {
  validateAblationRecord(record);
  const dir = cacheRunsDir();
  try {
    mkdirSync(dir, { recursive: true });
    appendFileSync(join(dir, "ablation-runs.jsonl"), `${JSON.stringify(record)}\n`);
  } catch (err) {
    throw new Error(`failed to persist ablation-run record: ${err.message}`);
  }
}

function ablationRunsFilePath() {
  return join(cacheRunsDir(), "ablation-runs.jsonl");
}

/** Holds an atomic per-pair directory lock from resume planning through the final append. A
 *  crash may leave the lock behind deliberately: manual inspection is safer than silently
 *  dispatching a second paid process against uncertain state. */
function withAblationPairLock(identity, fn) {
  const dir = cacheRunsDir();
  mkdirSync(dir, { recursive: true });
  const digest = sha256([identity.sweep, "\0", identity.agent, "\0", identity.omitted]).slice(7, 23);
  const lockPath = join(dir, `ablation-${digest}.lock`);
  try {
    mkdirSync(lockPath);
  } catch (err) {
    if (err.code === "EEXIST") {
      throw new Error(
        `ablation pair is already locked for sweep=${identity.sweep} ` +
          `agent=${identity.agent} omitted=${identity.omitted}; ` +
          `if no probe is running, inspect evidence then remove ${lockPath}`,
      );
    }
    throw err;
  }
  try {
    return fn();
  } finally {
    rmdirSync(lockPath);
  }
}

/** Fraction of input tokens that were served from cache, guarding divide-by-zero. */
function cacheReadFraction(usage) {
  const denom = usage.input + usage.cacheRead;
  return denom === 0 ? 0 : usage.cacheRead / denom;
}

function formatRunSummary(label, usage) {
  const lines = [`${label}:`];
  if (!usage) {
    lines.push("  no usage block found in this run's output");
    return lines.join("\n");
  }
  lines.push(`  input=${usage.input} cacheRead=${usage.cacheRead} cacheWrite=${usage.cacheWrite}`);
  lines.push(`  cost.total=$${usage.cost?.total ?? "?"}`);
  lines.push(`  cacheReadFraction=${cacheReadFraction(usage).toFixed(4)}`);
  return lines.join("\n");
}

/** Dispatches one ablate arm and returns findings plus billed usage. The arm is accepted only
 *  when the final successful turn matches the requested model and emits either structured
 *  findings or the explicit no-issues sentence; ambiguous output is never recorded as zero. */
function dispatchArmMeasurement({ systemPrompt, prompt, model, label }) {
  return withTempSystemPromptFile(systemPrompt, (promptFilePath) => {
    const args = buildDispatchArgv({ prompt, promptFilePath, model });
    const stdout = runPiOnce(args, label);
    const usage = usageOrDispatchError(stdout, label);
    modelIdentityOrDispatchError(stdout, model);
    const text = extractFinalAssistantText(stdout);
    const findings = parseAblationResponse(text ?? "");
    return { findings, usage };
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
      firstUsage: usageOrDispatchError(runPiOnce(args, "run 1 (cold)"), "run 1 (cold)"),
      secondUsage: usageOrDispatchError(
        runPiOnce(args, "run 2 (repeat, same prefix)"),
        "run 2 (repeat, same prefix)",
      ),
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

async function mainAblateRun({ agent, corpus, omit, sweep, dryRun, model }) {
  const root = pluginRoot();
  const agentSpecModule = await loadAgentSpecModule(root);
  const { baselinePrompt, omitPrompt } = resolveAblateArms(agentSpecModule, root, agent, omit);
  const files = listCorpusDiffFiles(corpus);

  if (dryRun) {
    printAblateDryRunSummary({ omit, baselinePrompt, omitPrompt, corpusFileCount: files.length });
    return;
  }
  if (!sweep || !model) {
    throw new UsageError(`live ablate mode requires --sweep <id> and --model <provider>/<id>\n${USAGE}`);
  }

  const corpusSnapshot = snapshotCorpus(corpus, files);
  const identity = {
    sweep,
    agent,
    omitted: omit,
    model,
    commit: cleanGitCommit(root),
    corpus: corpusSnapshot.metadata,
    promptFingerprints: {
      baseline: sha256([baselinePrompt]),
      omit: sha256([omitPrompt]),
    },
  };
  return withAblationPairLock(identity, () => {
    const records = readAblationRecords() ?? [];
    const pending = planAblationArms(records, identity);
    if (pending.length === 0) {
      console.log(
        `sweep=${sweep} agent=${agent} omitted=${omit}: already complete; no dispatches needed`,
      );
      return;
    }

    for (const { diff, arm } of pending) {
      const diffContent = corpusSnapshot.contents.get(diff);
      const prompt = `${ABLATE_REVIEW_PROMPT_PREFIX}${diffContent}`;
      const systemPrompt = arm === "baseline" ? baselinePrompt : omitPrompt;
      const label = `${diff} ${arm}`;
      const { findings, usage } = dispatchArmMeasurement({ systemPrompt, prompt, model, label });
      appendAblationRunRecord({
        schemaVersion: 2,
        sweep: identity.sweep,
        agent: identity.agent,
        omitted: identity.omitted,
        model: identity.model,
        commit: identity.commit,
        corpus: identity.corpus,
        diff,
        arm,
        promptFingerprint: identity.promptFingerprints[arm],
        findings,
        usage,
        ts: new Date().toISOString(),
      });
      console.log(
        `${diff} ${arm}${arm === "omit" ? `(${omit})` : ""}: ${findings.length} finding(s)`,
      );
    }
  });
}

/** Reads the durable evidence file fail-closed. A malformed line invalidates the report
 *  instead of disappearing and making incomplete coverage look clean. */
function readAblationRecords() {
  const path = ablationRunsFilePath();
  if (!existsSync(path)) return null;
  const text = readFileSync(path, "utf8");
  const records = [];
  for (const [index, line] of text.split("\n").entries()) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      records.push(JSON.parse(trimmed));
    } catch {
      throw new Error(`malformed JSON in ablation-runs.jsonl at line ${index + 1}`);
    }
  }
  return records;
}

function reportAblation(sweep, agentFilter) {
  const records = readAblationRecords();
  if (records === null) {
    console.log(
      "no ablation-run data collected yet — run:\n" +
        "  node --experimental-strip-types scripts/preload-probe.mjs ablate --agent <id> --corpus <dir> --omit <skill-id> --sweep <id> --model <provider>/<id>\n" +
        "first, then re-run --report.",
    );
    return;
  }

  const summaries = summarizeAblationRecords(records, { sweep, agent: agentFilter });
  if (summaries.length === 0) {
    console.log(
      `no ablation-run data collected yet for sweep "${sweep}"` +
        `${agentFilter ? ` and agent "${agentFilter}"` : ""} — run ablate first, then re-run --report.`,
    );
    return;
  }

  for (const summary of summaries) {
    console.log(
      `agent=${summary.agent} omitted=${summary.omitted}: ` +
        `lost=${summary.lost} downgraded=${summary.downgraded} model=${summary.model}`,
    );
    for (const detail of summary.diffs) {
      console.log(`  ${detail.diff}:`);
      for (const finding of detail.lost) {
        console.log(`    lost: ${finding.fileLine} (${finding.severity})`);
      }
      for (const downgrade of detail.downgraded) {
        console.log(
          `    downgraded: ${downgrade.baseline.fileLine} ` +
            `${downgrade.baseline.severity} -> ${downgrade.omit.severity}`,
        );
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
    reportAblation(parsed.sweep, parsed.agent);
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

#!/usr/bin/env node
// --experimental-strip-types is required to load pi/extensions/agent-spec.ts below.
/**
 * Static, zero-network, zero-dependency dispatch-cost ledger.
 *
 * For every agent under agents/*.md, measures the real dispatch prefix (agent body + every
 * preloaded skill body, exactly as `composeSystemPrompt` in pi/extensions/agent-spec.ts
 * assembles it — that function is imported and called directly here, never reimplemented) and
 * writes a generated snapshot to docs/dispatch-ledger.md. No `pi` process is spawned; nothing is
 * dispatched. This is C1 of four planned instruments — see docs/dispatch-ledger.md's own header
 * for the ratchet framing.
 *
 * Usage:
 *   node --experimental-strip-types scripts/dispatch-ledger.mjs [--check|--write] [--root <path>]
 *
 * --check (default): recompute the ledger and compare it byte-for-byte against
 *   docs/dispatch-ledger.md on disk. Exits 0 if clean, 1 (with a stderr message pointing at
 *   --write) if drifted or missing.
 * --write: recompute the ledger and overwrite docs/dispatch-ledger.md. Always exits 0. Prints
 *   "Nothing needed changing." when the freshly generated content is byte-identical to what was
 *   already on disk.
 * --root <path>: plugin root to read agents/skills from and (in --write mode) to write
 *   docs/dispatch-ledger.md under. Defaults to this script's own repo root
 *   (fileURLToPath(new URL("..", import.meta.url)), same pattern as preload-probe.mjs's
 *   pluginRoot()). Exists so tests/test_dispatch_ledger.py can point the script at a synthetic
 *   plugin tree instead of the real repo.
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join, sep } from "node:path";

/** Chars-per-token divisor for the derived, clearly-"(est.)"-labeled token columns. There is no
 *  tokenizer available in this repo (matches scripts/validate.py's stdlib-only, zero-dependency
 *  posture) — characters are the exact, deterministic ratchet unit; estimated tokens are a
 *  convenience derived from them, never the thing actually compared byte-for-byte. */
const CHARS_PER_TOKEN_ESTIMATE = 4.0;

const OUTPUT_RELATIVE_PATH = "docs/dispatch-ledger.md";

const USAGE = "usage: node --experimental-strip-types scripts/dispatch-ledger.mjs [--check|--write] [--root <path>]";

class UsageError extends Error {}

/** Resolves this plugin's root (repo root) from this script's own location — same
 *  fileURLToPath(new URL("..", import.meta.url)) pattern as preload-probe.mjs's pluginRoot(). */
function defaultRoot() {
  return fileURLToPath(new URL("..", import.meta.url));
}

/** Strips any trailing path separator(s) so every root string this script handles reaches
 *  normalizeRoot() in one canonical form.
 *
 *  This is load-bearing, not cosmetic. defaultRoot() always ends in a separator (that is what
 *  `new URL("..", ...)` produces), while an explicitly-passed `--root` typically does not. Skill
 *  `dir` values are built with path.join(), which always collapses the separator — so the raw
 *  composed prompt contains `<root>/skills/<id>` either way. Splitting that text on a root that
 *  still carries its own trailing separator consumes the separator too, emitting
 *  `<PLUGIN_ROOT>skills/<id>`; splitting on the canonical form emits `<PLUGIN_ROOT>/skills/<id>`.
 *  That one-character difference lands in every `Preload chars` cell (one char per preloaded
 *  skill), so a ledger generated through one convention reads as out-of-sync when checked through
 *  the other. Canonicalizing once, here, makes the emitted ledger byte-identical either way.
 *  A lone separator ("/") is left intact — stripping it would produce an empty root. */
function canonicalizeRoot(root) {
  let out = root;
  while (out.length > 1 && (out.endsWith(sep) || out.endsWith("/"))) {
    out = out.slice(0, -1);
  }
  return out;
}

/** Parses process.argv.slice(2) into { mode, root }. --check and --write are mutually
 *  exclusive; omitting both defaults to --check, matching scripts/sync-shared-blocks.py's
 *  convention (--check is the default across this repo's generated-artifact scripts). */
function parseArgs(argv) {
  let mode;
  let root;
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (token === "--check" || token === "--write") {
      if (mode !== undefined && mode !== token) {
        throw new UsageError(`--check and --write are mutually exclusive\n${USAGE}`);
      }
      mode = token;
    } else if (token === "--root") {
      root = argv[++i];
      if (root === undefined) {
        throw new UsageError(`--root requires a path argument\n${USAGE}`);
      }
    } else {
      throw new UsageError(`unrecognized argument "${token}"\n${USAGE}`);
    }
  }
  return { mode: mode ?? "--check", root: canonicalizeRoot(root ?? defaultRoot()) };
}

/** Loads pi/extensions/agent-spec.ts via the same pathToFileURL(...).href dynamic-import pattern
 *  as preload-probe.mjs and tests/test_pi_extension.py — that file is SDK-free, so this works
 *  without node_modules resolvable for its own imports; only this *script* needs
 *  --experimental-strip-types to load a .ts file at all. NOTE: always loaded from this script's
 *  OWN repo root (defaultRoot()), never from the caller-supplied --root — a synthetic test
 *  fixture has no pi/extensions/agent-spec.ts of its own to load; it only supplies agents/ and
 *  skills/ data for the real module to read. */
async function loadAgentSpecModule() {
  const modulePath = join(defaultRoot(), "pi", "extensions", "agent-spec.ts");
  return import(pathToFileURL(modulePath).href);
}

/** Replaces every occurrence of the literal absolute repo root with <PLUGIN_ROOT>. Plain
 *  string split/join (not a regex) since `root` is a known literal, not a pattern.
 *  composeSystemPrompt inlines each skill's absolute `dir` verbatim, so the raw composed text
 *  (and its length) would otherwise differ between machines purely because of repo-path length,
 *  making the ledger non-reproducible across a developer machine and CI. `root` must already be
 *  canonical (no trailing separator) — see canonicalizeRoot above for why that matters. */
function normalizeRoot(text, root) {
  return text.split(root).join("<PLUGIN_ROOT>");
}

/** Measures one agent's dispatch prefix. Calls composeSystemPrompt directly — never
 *  reimplements prompt assembly — so this ledger cannot drift from what a real dispatch actually
 *  sends. */
function measureAgent(agentSpecModule, root, agentId) {
  const { readAgentSpec, readSkillBody, skillDir, composeSystemPrompt } = agentSpecModule;

  const spec = readAgentSpec(root, agentId);
  const skills = spec.skillIds.map((id) => ({ id, body: readSkillBody(root, id), dir: skillDir(root, id) }));
  const composed = normalizeRoot(composeSystemPrompt(spec, skills), root);

  const agentBodyChars = normalizeRoot(spec.body.trim(), root).length;
  // preload chars = composed.length - agentBodyChars, NOT sum(skill body lengths): the
  // composition also adds the "\n\n---\n\n" join separator and the "## Preloaded skill: ..."
  // header (with its `dir` line) per skill. Those exist only because preloading exists — zero
  // preloaded skills means zero separator/header overhead too — so they are correctly counted
  // as preload cost, matching what a real dispatch actually sends.
  const preloadChars = composed.length - agentBodyChars;
  const preloadSharePct = composed.length === 0 ? 0 : (preloadChars / composed.length) * 100;

  const skillBreakdown = skills.map((skill) => ({
    id: skill.id,
    bodyChars: normalizeRoot(skill.body.trim(), root).length,
  }));

  return {
    agentId,
    agentBodyChars,
    preloadChars,
    preloadSharePct,
    skillCount: spec.skillIds.length,
    skillBreakdown,
  };
}

function estTokens(chars) {
  return Math.round(chars / CHARS_PER_TOKEN_ESTIMATE);
}

/** Builds the full docs/dispatch-ledger.md content from a list of per-agent measurements
 *  (already sorted, already root-normalized). Pure string formatting — no I/O. */
function renderLedger(measurements) {
  const lines = [];
  lines.push("# Dispatch ledger");
  lines.push("");
  lines.push(
    "This file is generated by `node --experimental-strip-types scripts/dispatch-ledger.mjs " +
      "--write` — never hand-edit it. Run `node --experimental-strip-types " +
      "scripts/dispatch-ledger.mjs --check` to verify it is in sync, and re-run `--write` to " +
      "regenerate it after any change to an agent body or a preloaded skill body. It measures " +
      "every agent's real dispatch prefix cost — the agent's own body plus every preloaded " +
      "skill's body, exactly as `composeSystemPrompt` (`pi/extensions/agent-spec.ts`) assembles " +
      "it for a real dispatch — as a static, zero-network, zero-dependency character count. " +
      "Absolute filesystem paths are normalized to the literal placeholder `<PLUGIN_ROOT>` so " +
      "the ledger is identical across machines. Token columns are a derived **estimate** " +
      `(divisor: ${CHARS_PER_TOKEN_ESTIMATE} chars/token) — characters are the exact, ` +
      "deterministic count this ledger ratchets on.",
  );
  lines.push("");
  lines.push("## Per-agent totals");
  lines.push("");
  lines.push(
    "| Agent | Agent-body chars | Preload chars | Preload share % | Skill count | " +
      "Agent-body tokens (est.) | Preload tokens (est.) |",
  );
  lines.push("|---|---|---|---|---|---|---|");
  for (const m of measurements) {
    lines.push(
      `| ${m.agentId} | ${m.agentBodyChars} | ${m.preloadChars} | ${m.preloadSharePct.toFixed(1)} | ` +
        `${m.skillCount} | ${estTokens(m.agentBodyChars)} | ${estTokens(m.preloadChars)} |`,
    );
  }
  lines.push("");

  const totalAgentBodyChars = measurements.reduce((sum, m) => sum + m.agentBodyChars, 0);
  const totalPreloadChars = measurements.reduce((sum, m) => sum + m.preloadChars, 0);
  const totalComposedChars = totalAgentBodyChars + totalPreloadChars;
  const totalPreloadSharePct = totalComposedChars === 0 ? 0 : (totalPreloadChars / totalComposedChars) * 100;

  lines.push("## Totals");
  lines.push("");
  lines.push("| Agent-body chars | Preload chars | Preload share % | Agent-body tokens (est.) | Preload tokens (est.) |");
  lines.push("|---|---|---|---|---|");
  lines.push(
    `| ${totalAgentBodyChars} | ${totalPreloadChars} | ${totalPreloadSharePct.toFixed(1)} | ` +
      `${estTokens(totalAgentBodyChars)} | ${estTokens(totalPreloadChars)} |`,
  );
  lines.push("");

  lines.push("## Per-(agent, skill) breakdown");
  lines.push("");
  lines.push("| Agent | Skill | Skill body chars | Skill body tokens (est.) |");
  lines.push("|---|---|---|---|");
  for (const m of measurements) {
    for (const skill of m.skillBreakdown) {
      lines.push(`| ${m.agentId} | ${skill.id} | ${skill.bodyChars} | ${estTokens(skill.bodyChars)} |`);
    }
  }
  lines.push("");

  return lines.join("\n");
}

async function buildLedger(root) {
  const agentSpecModule = await loadAgentSpecModule();
  const { listAgentNames } = agentSpecModule;
  // listAgentNames(root) already sorts; sort() here too so this ledger's own ordering
  // guarantee doesn't silently depend on that upstream implementation detail.
  const agentIds = listAgentNames(root).slice().sort();
  const measurements = agentIds.map((agentId) => measureAgent(agentSpecModule, root, agentId));
  return renderLedger(measurements);
}

async function main(argv) {
  const { mode, root } = parseArgs(argv);
  const outputPath = join(root, ...OUTPUT_RELATIVE_PATH.split("/"));

  const fresh = await buildLedger(root);

  if (mode === "--write") {
    const existing = existsSync(outputPath) ? readFileSync(outputPath, "utf8") : null;
    if (existing === fresh) {
      console.log("Nothing needed changing.");
    } else {
      writeFileSync(outputPath, fresh, "utf8");
      console.log(`Updated: ${OUTPUT_RELATIVE_PATH}`);
    }
    return 0;
  }

  // --check
  if (!existsSync(outputPath)) {
    console.error(`${OUTPUT_RELATIVE_PATH} does not exist — run --write to generate it.`);
    return 1;
  }
  const existing = readFileSync(outputPath, "utf8");
  if (existing === fresh) {
    console.log(`${OUTPUT_RELATIVE_PATH} is in sync.`);
    return 0;
  }
  console.error(
    `${OUTPUT_RELATIVE_PATH} is out of sync with the current agents/skills on disk — run ` +
      "`node --experimental-strip-types scripts/dispatch-ledger.mjs --write` to regenerate it.",
  );
  return 1;
}

try {
  process.exit(await main(process.argv.slice(2)));
} catch (err) {
  if (err instanceof UsageError) {
    console.error(err.message);
  } else {
    console.error(`dispatch-ledger: ${err.message}`);
  }
  process.exit(1);
}

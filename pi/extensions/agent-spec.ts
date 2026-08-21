/**
 * Pure parsing/composition for this plugin's agents/*.md convention, plus thin I/O wrappers.
 *
 * Layer: domain, same posture as tool-vocab.ts. This file must import NOTHING from the Pi SDK,
 * not even as a type — only node:fs/node:path, plus a relative import of RENAME_TABLE from
 * ./tool-vocab.ts (also SDK-free). subagent.ts owns everything that touches Pi itself.
 *
 * agents/*.md frontmatter is a fixed, uniform 5-key shape across all 22 files today (name,
 * description, model, tools, skills) — `tools:` is always one comma-separated inline string,
 * `skills:` is always a YAML block sequence of `swe-workbench:<id>` entries. This is a small
 * purpose-built extractor for exactly that shape, not a general YAML parser — it mirrors
 * scripts/validate.py's parse_frontmatter() key/item regexes so the two hand-rolled parsers
 * can't silently diverge on what a line means.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { RENAME_TABLE } from "./tool-vocab.ts";

export interface AgentSpec {
  readonly name: string;
  readonly description: string;
  readonly tools: readonly string[];
  readonly skillIds: readonly string[];
  readonly body: string;
}

const SKILL_NAMESPACE_PREFIX = "swe-workbench:";

/** Tool tokens with no Pi tool equivalent — dropped rather than renamed. Exported so
 *  tests/test_pi_contract.py can assert exhaustiveness over TOOL_TOKENS. */
export const DROP_TOKENS = new Set(["Skill", "WebFetch"]);

const FM_KEY_RE = /^([\w-]+):\s*(.*)$/;
const FM_ITEM_RE = /^-\s+(.*\S)\s*$/;

/** Mirrors the installed Pi SDK's dist/utils/frontmatter.js extractFrontmatter (kept as prose
 *  here, deliberately not a code dependency — see this file's own header): normalize newlines,
 *  find the closing '---' via indexOf from index 3, slice from 4 chars past that match, then
 *  strip() the body. Throws (rather than degrading) on a missing/malformed block — every file
 *  this is called on is one of this plugin's own bundled resources, not untrusted input, so a
 *  malformed one is a bug to surface, not a case to silently tolerate. */
function splitFrontmatter(rawText: string): { frontmatter: string; body: string } {
  const text = rawText.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (!text.startsWith("---")) {
    throw new Error("expected a '---' frontmatter block at the start of the file");
  }
  const end = text.indexOf("\n---", 3);
  if (end === -1) {
    throw new Error("frontmatter block has no closing '---'");
  }
  return { frontmatter: text.slice(3, end), body: text.slice(end + 4).trim() };
}

/** Parses exactly this plugin's agents/*.md frontmatter shape: `tools:` a comma-separated
 *  inline string, `skills:` a block sequence, everything else a plain scalar. Pure. */
export function parseAgentSpec(text: string): AgentSpec {
  const { frontmatter, body } = splitFrontmatter(text);

  const scalars: Record<string, string> = {};
  const lists: Record<string, string[]> = {};
  let pending: string | null = null;

  for (const rawLine of frontmatter.split("\n")) {
    const stripped = rawLine.trim();
    if (stripped === "") continue;

    if (pending !== null) {
      const item = FM_ITEM_RE.exec(stripped);
      if (item) {
        (lists[pending] ??= []).push(item[1].trim());
        continue;
      }
    }

    const key = FM_KEY_RE.exec(stripped);
    if (key) {
      const name = key[1].toLowerCase();
      const value = key[2].trim();
      scalars[name] = value;
      pending = value === "" ? name : null;
    } else {
      pending = null;
    }
  }

  const name = scalars.name;
  const description = scalars.description;
  if (!name) throw new Error("agent frontmatter missing required 'name' key");
  if (!description) throw new Error("agent frontmatter missing required 'description' key");

  const tools = scalars.tools
    ? scalars.tools
        .split(",")
        .map((t) => t.trim())
        .filter((t) => t.length > 0)
    : [];
  const skillIds = lists.skills ?? [];

  return { name, description, tools, skillIds, body };
}

/** Translates Claude Code tool tokens (as found in an agent's `tools:` frontmatter) into Pi
 *  tool names, via RENAME_TABLE for tokens with a real Pi equivalent and DROP_TOKENS for tokens
 *  with none. Throws on any token that is neither — exhaustive over this repo's known token
 *  vocabulary, no silent gaps — and throws if the translated result is empty (an empty --tools
 *  allowlist would silently mute every tool in the dispatched child session). Pure; order- and
 *  duplicate-preserving beyond de-duplication. */
export function translateToolTokens(tokens: readonly string[]): string[] {
  const seen = new Set<string>();
  const translated: string[] = [];
  for (const token of tokens) {
    const renamed = RENAME_TABLE.find(([cc]) => cc === token)?.[1];
    if (renamed !== undefined) {
      if (!seen.has(renamed)) {
        seen.add(renamed);
        translated.push(renamed);
      }
      continue;
    }
    if (DROP_TOKENS.has(token)) continue;
    throw new Error(`translateToolTokens: no Pi mapping (rename or drop) for tool token "${token}"`);
  }
  if (translated.length === 0) {
    throw new Error(
      "translateToolTokens: translated result is empty — refusing to build an empty --tools allowlist",
    );
  }
  return translated;
}

/** Composes an agent's system prompt: its own body, followed by each preloaded skill's
 *  (frontmatter-stripped) body in `skills:` order. Pure string composition. */
export function composeSystemPrompt(
  spec: Pick<AgentSpec, "body">,
  skills: ReadonlyArray<{ readonly id: string; readonly body: string }>,
): string {
  const sections = [spec.body.trim()];
  for (const skill of skills) {
    sections.push(`## Preloaded skill: ${skill.id}\n\n${skill.body.trim()}`);
  }
  return sections.join("\n\n---\n\n");
}

/** Reads and parses agents/<name>.md from this plugin's own bundled resource tree. */
export function readAgentSpec(root: string, name: string): AgentSpec {
  const text = readFileSync(join(root, "agents", `${name}.md`), "utf8");
  return parseAgentSpec(text);
}

/** Reads a preloaded skill's body (frontmatter stripped, preload-canary and everything after
 *  kept — that marker is docs/skill-preload.md's mechanism for verifying preload actually
 *  happened, so it must survive into the composed prompt). `skillId` may be namespaced
 *  (`swe-workbench:<id>`) or bare; the namespace prefix is stripped before resolving the path. */
export function readSkillBody(root: string, skillId: string): string {
  const bareId = skillId.startsWith(SKILL_NAMESPACE_PREFIX)
    ? skillId.slice(SKILL_NAMESPACE_PREFIX.length)
    : skillId;
  const text = readFileSync(join(root, "skills", bareId, "SKILL.md"), "utf8");
  return splitFrontmatter(text).body;
}

/** Lists agent ids (basenames, no .md) under agents/ — for a "not found, available: ..." error. */
export function listAgentNames(root: string): string[] {
  return readdirSync(join(root, "agents"), { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .map((entry) => entry.name.slice(0, -".md".length))
    .sort();
}

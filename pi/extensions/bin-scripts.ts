/**
 * Pure text for the swe-workbench bin/ scripts preamble section.
 *
 * Layer: domain. This file must import NOTHING from the Pi SDK, not even as a type — only
 * node:fs/node:path. Composing it into the system prompt (composePreamble) is index.ts's job.
 *
 * Replaces the old bin/README.md "## Current scripts" splice: that table was human
 * documentation prose re-purposed as a machine-parseable section, so it grew every time a row
 * was edited for readability. This module generates a bare-id list from the real bin/ directory
 * instead — it cannot drift from what actually ships — plus a one-entry CAPABILITY_ROWS
 * allowlist for the one script (`swe-workbench-lsp`) that needs more than its own name to be
 * usable, and a pointer at each script's own `--help` output for everything else.
 */
import { readdirSync } from "node:fs";
import { join } from "node:path";

/** Scripts whose usage is not obvious from the bare id alone — kept deliberately small: expand
 *  one entry at a time, with a recorded reason, only if a Pi session is observed reimplementing
 *  a script inline instead of discovering it. Do not add a second entry casually — it names
 *  exactly this one. */
export const CAPABILITY_ROWS: ReadonlyArray<{ id: string; body: string }> = [
  {
    id: "swe-workbench-lsp",
    body:
      "swe-workbench-lsp — semantic code navigation " +
      "(refs/def/impl/callers/callees/hover/symbols/wsymbols/check)",
  },
];

/** By construction the exact set of bare commands `<root>/bin` on PATH exposes — mirrors
 *  tool-vocab.ts's readSkillIds shape exactly (try/catch -> null) so a missing/unreadable bin/
 *  degrades only this section, never the rest of the preamble. */
function readBinScriptIds(binDir: string): string[] | null {
  try {
    return readdirSync(binDir, { withFileTypes: true })
      .filter((entry) => entry.isFile() && entry.name.startsWith("swe-workbench-"))
      .map((entry) => entry.name)
      .sort();
  } catch {
    return null;
  }
}

/** Returns the {title, body}-shaped section composePreamble expects for the bin/ script
 *  inventory, or null when bin/ is unreadable or (degenerately) empty of swe-workbench-*
 *  entries — present-or-wholly-absent, never "present but empty", matching the old
 *  missing-README fail-soft posture this replaces. */
export function binScriptsSection(root: string): { title: string; body: string } | null {
  const ids = readBinScriptIds(join(root, "bin"));
  if (ids === null || ids.length === 0) return null;

  const idList = ids.map((id) => `\`${id}\``).join(", ");
  const capabilityLines = CAPABILITY_ROWS.map((row) => `- ${row.body}`).join("\n");
  const pointer =
    "Each bare command supports its own `--help` — e.g. `swe-workbench-lsp --help` — for " +
    "usage and argument shape; check before reimplementing a script's behavior inline.";

  const body = [
    `Bare commands on PATH (see "Reference pattern" in bin/README.md for the calling ` +
      `convention): ${idList}.`,
    capabilityLines,
    pointer,
  ].join("\n\n");

  return { title: "swe-workbench bin/ scripts (bare commands, already on PATH)", body };
}

/**
 * Pure, dependency-free helpers factored out of scripts/preload-probe.mjs's `ablate` subcommand
 * so they're independently testable: no process spawn (no `pi`, not even `node` beyond the
 * import itself), no filesystem I/O, no side effects at import time — unlike preload-probe.mjs
 * itself, which runs its CLI immediately on import (`await main(process.argv.slice(2))` at
 * top level). tests/test_preload_instruments.py imports this module directly to unit-test the
 * pipe-delimited finding parser as a plain function call.
 */

/** Severity tiers a well-formed finding line's first field must be one of, per
 *  shared/agents/severity-output-contract.md's ladder — used both to reject stray prose lines
 *  that happen to contain 4 pipe characters, and by the report mode's downgrade comparison
 *  (higher rank = more severe). */
export const SEVERITY_RANK = { Critical: 4, High: 3, Medium: 2, Low: 1 };

/** Matches the literal "no findings" sentence severity-output-contract.md's Silence rule
 *  requires ("No <domain> issues found in this diff."): zero findings, not a parse failure. */
const NO_ISSUES_SENTENCE_RE = /^No .+ issues found in this diff\.$/;

/** Parses an agent's response text into structured findings per
 *  shared/agents/severity-output-contract.md's pipe-delimited format:
 *  `Severity | File:Line | Issue | Why it matters | Suggested fix`, one finding per line.
 *  Tolerant by design: splits on lines, trims whitespace around each `|`, and silently skips any
 *  line that isn't a well-formed 5-field finding (headers, prose, blank lines) — including the
 *  Silence rule's "No X issues found in this diff." sentence, which is zero findings, not an
 *  error. A line is only accepted as a finding if its first field is one of the four known
 *  severity tiers, which is what keeps stray prose containing pipe characters (e.g. a markdown
 *  table cell inside a "Suggested fix" code block on its own line) from being misparsed as a 6th
 *  "finding". */
export function parsePipeDelimitedFindings(responseText) {
  const findings = [];
  for (const rawLine of (responseText ?? "").split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    if (NO_ISSUES_SENTENCE_RE.test(line)) continue;
    const parts = line.split("|").map((part) => part.trim());
    if (parts.length !== 5) continue;
    const [severity, fileLine, issue, whyItMatters, suggestedFix] = parts;
    if (!(severity in SEVERITY_RANK)) continue;
    if (!fileLine || !issue) continue;
    findings.push({ severity, fileLine, issue, whyItMatters, suggestedFix });
  }
  return findings;
}

/** Extracts the final assistant response TEXT from a `pi --mode json` NDJSON stream — what
 *  `ablate` needs (the pipe-delimited findings live in this text), as opposed to
 *  preload-probe.mjs's `lastMessageUpdateUsage`, which only needs the numeric usage block.
 *
 *  Event-shape source (inspected directly, per this task's brief, since nothing in this repo
 *  already extracted final assistant text from a JSON-mode event stream):
 *    - node_modules/@earendil-works/pi-coding-agent/dist/modes/json-event.d.ts: every session
 *      event the `AgentSessionEvent` union produces is JSON.stringify(toJsonEvent(event))'d to
 *      stdout, one per line (dist/modes/print-mode.js's `session.subscribe` callback) — not just
 *      `message_update`. `toJsonEvent` only special-cases `message_update` (flattening `usage`
 *      onto the event and stripping streaming `partial` snapshots); every other event type,
 *      including `message_end`, passes through unchanged.
 *    - node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core/
 *      dist/types.d.ts `AgentEvent` union: `{ type: "message_end", message: AgentMessage }` is
 *      "the final authoritative message" for a turn (per json-event.d.ts's own comment,
 *      distinguishing it from `message_start`'s initial snapshot and `message_update`'s
 *      in-progress deltas).
 *    - node_modules/.../pi-ai/dist/types.d.ts: `AssistantMessage.content` is
 *      `(TextContent | ThinkingContent | ToolCall)[]`, and `TextContent` is
 *      `{ type: "text", text: string }`.
 *
 *  So: scan every NDJSON line for `type === "message_end"` whose `message.role === "assistant"`,
 *  concatenate that message's `content` entries where `type === "text"` (in order), and keep the
 *  LAST such message_end found (mirroring `lastMessageUpdateUsage`'s "last wins" posture — this
 *  probe's `-p` dispatch has no tool calls, so in practice there is exactly one assistant turn,
 *  but "last" is still the correct tie-breaker if that ever changes). Returns null (not an
 *  empty string) when no assistant `message_end` was found at all, so callers can distinguish
 *  "found an empty response" from "found nothing to parse". */
export function extractFinalAssistantText(ndjson) {
  let lastText = null;
  for (const line of ndjson.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try {
      obj = JSON.parse(trimmed);
    } catch {
      continue;
    }
    if (obj && obj.type === "message_end" && obj.message && obj.message.role === "assistant") {
      const content = Array.isArray(obj.message.content) ? obj.message.content : [];
      lastText = content
        .filter((block) => block && block.type === "text" && typeof block.text === "string")
        .map((block) => block.text)
        .join("");
    }
  }
  return lastText;
}

/** Compares one omit-arm's findings against the matching baseline's findings for the same diff.
 *
 *  Matching heuristic (approximate BY DESIGN, per this task's brief — two independent LLM
 *  dispatches reviewing the same diff will not produce byte-identical prose, so findings can't be
 *  matched by exact-equality): match findings by their `fileLine` field. Both arms review the
 *  exact same diff text, so a real finding's file:line reference should be stable across the two
 *  dispatches even when the wording of `Issue`/`Why it matters`/`Suggested fix` varies. A
 *  baseline finding whose `fileLine` has no corresponding entry in the omit arm's findings is
 *  "lost". One whose `fileLine` DOES have a corresponding omit-arm entry, but at a lower position
 *  on the Critical > High > Medium > Low ladder, is a "severity downgrade". If the omit arm
 *  reports the same `fileLine` more than once, the last one wins (last-write-wins on the lookup
 *  map) — a rare case (LLM output, not a hard invariant), not worth a more elaborate multi-match
 *  policy for a 2-diff pilot. */
export function compareArm(baselineFindings, omitFindings) {
  const omitByFileLine = new Map();
  for (const finding of omitFindings) {
    omitByFileLine.set(finding.fileLine, finding);
  }
  const lost = [];
  const downgraded = [];
  for (const baseline of baselineFindings) {
    const match = omitByFileLine.get(baseline.fileLine);
    if (!match) {
      lost.push(baseline);
      continue;
    }
    const baseRank = SEVERITY_RANK[baseline.severity] ?? 0;
    const matchRank = SEVERITY_RANK[match.severity] ?? 0;
    if (matchRank < baseRank) {
      downgraded.push({ baseline, omit: match });
    }
  }
  return { lost, downgraded };
}

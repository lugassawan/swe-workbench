/**
 * Pure, dependency-free helpers split out of scripts/preload-probe.mjs so they are
 * independently testable — no spawns, no filesystem I/O, no import-time side effects
 * (preload-probe.mjs runs its CLI on import). Tested directly by
 * tests/test_preload_instruments.py via node -e imports.
 */

/** The four severity tiers of shared/agents/severity-output-contract.md's ladder; higher
 *  rank = more severe. Doubles as the whitelist for well-formed finding lines. */
export const SEVERITY_RANK = { Critical: 4, High: 3, Medium: 2, Low: 1 };

/** The Silence rule's "No <domain> issues found in this diff." — zero findings, not a parse
 *  failure. */
const NO_ISSUES_SENTENCE_RE = /^No .+ issues found in this diff\.$/;

/** " | " is the field boundary, not bare `|` — a field may itself contain a bare pipe
 *  (e.g. a Suggested fix mentioning `string | number`). */
const FIELD_SEPARATOR = " | ";
const FIELD_COUNT = 5;

/** Splits a line into exactly FIELD_COUNT fields on the first FIELD_COUNT-1 separator
 *  occurrences; everything after the last (including any stray " | " inside an earlier
 *  field) stays in the final field. Returns null when the line isn't a well-formed finding
 *  line at all. */
function splitFindingFields(line) {
  const fields = [];
  let rest = line;
  for (let i = 0; i < FIELD_COUNT - 1; i++) {
    const idx = rest.indexOf(FIELD_SEPARATOR);
    if (idx === -1) return null;
    fields.push(rest.slice(0, idx).trim());
    rest = rest.slice(idx + FIELD_SEPARATOR.length);
  }
  fields.push(rest.trim());
  return fields;
}

/** Parses response text into findings per severity-output-contract.md:
 *  `Severity | File:Line | Issue | Why it matters | Suggested fix`, one per line. Tolerant:
 *  non-matching lines (prose, headers, the Silence sentence, blanks) are skipped, and a line
 *  counts only if its first field is a known severity tier. */
export function parsePipeDelimitedFindings(responseText) {
  const findings = [];
  for (const rawLine of (responseText ?? "").split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    if (NO_ISSUES_SENTENCE_RE.test(line)) continue;
    const parts = splitFindingFields(line);
    if (!parts) continue;
    const [severity, fileLine, issue, whyItMatters, suggestedFix] = parts;
    if (!(severity in SEVERITY_RANK)) continue;
    if (!fileLine || !issue) continue;
    findings.push({ severity, fileLine, issue, whyItMatters, suggestedFix });
  }
  return findings;
}

/** Extracts the final assistant response TEXT from a `pi --mode json` NDJSON stream — what
 *  `ablate` needs, as opposed to extractFinalUsage's numeric block. Scans for the LAST
 *  assistant `message_end` (the turn's authoritative final message) and concatenates its text
 *  content. "Last wins" matters under retries: an earlier errored message_end has empty
 *  content and must not shadow a later successful turn. Returns null when no assistant
 *  message_end exists at all. */
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

/** Extracts the provider-level failure reason from a `pi --mode json` NDJSON stream, or null
 *  when every turn completed without error. A failed provider call still exits 0 — the only
 *  reliable signal is a message-level `stopReason:"error"` event. Callers hard-fail on a
 *  non-null result: a broken dispatch is not a measurement. */
export function extractDispatchError(ndjson) {
  for (const line of ndjson.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try {
      obj = JSON.parse(trimmed);
    } catch {
      continue;
    }
    const message = obj && typeof obj === "object" ? obj.message : null;
    if (obj && typeof obj === "object" && message && typeof message === "object" && message.stopReason === "error") {
      return typeof message.errorMessage === "string" && message.errorMessage
        ? message.errorMessage
        : "dispatch failed (stopReason=error, no errorMessage)";
    }
  }
  return null;
}

/** Extracts the turn's final usage: the LAST non-errored assistant `message_end` usage block
 *  (the authoritative, post-billing snapshot), falling back to the last `message_update`
 *  snapshot only when no message_end carried usage — some providers (openai-codex) zero their
 *  message_update snapshots for the whole stream. Returns null when neither source yields
 *  usage. */
export function extractFinalUsage(ndjson) {
  let lastEndUsage = null;
  let lastUpdateUsage = null;
  for (const line of ndjson.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try {
      obj = JSON.parse(trimmed);
    } catch {
      continue;
    }
    if (!obj || typeof obj !== "object") continue;
    if (
      obj.type === "message_end" &&
      obj.message &&
      typeof obj.message === "object" &&
      obj.message.role === "assistant" &&
      obj.message.stopReason !== "error" &&
      obj.message.usage
    ) {
      lastEndUsage = obj.message.usage;
    } else if (obj.type === "message_update" && obj.usage) {
      lastUpdateUsage = obj.usage;
    }
  }
  return lastEndUsage ?? lastUpdateUsage;
}

/** The cache probe's measurement gate: returns the final usage, or throws — never null or
 *  zero usage. Zero billed tokens (input+cacheRead+cacheWrite all 0) is as unmeasurable as
 *  no usage; the provider's errorMessage is surfaced when the stream carries one. */
export function usageOrDispatchError(ndjson, label) {
  const usage = extractFinalUsage(ndjson);
  if (usage) {
    const billedTokens = usage.input + usage.cacheRead + usage.cacheWrite;
    if (billedTokens > 0) return usage;
    throw new Error(
      `${label}: usage reported zero billed tokens (input/cacheRead/cacheWrite all 0) — ` +
        `${extractDispatchError(ndjson) ?? "not a measurable dispatch"}`,
    );
  }
  const dispatchError = extractDispatchError(ndjson);
  throw new Error(`${label}: ${dispatchError ?? "no usage found in this run's output"}`);
}

/** Compares an omit arm's findings against the baseline for the same diff, matching by
 *  `fileLine` (prose differs across independent dispatches; file:line should not). A baseline
 *  finding with no omit-arm match is "lost"; a match at lower severity is a "downgrade".
 *  Duplicate fileLine in the omit arm: last write wins on the lookup map. */
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

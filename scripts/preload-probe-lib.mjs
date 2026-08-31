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

/** The literal field separator severity-output-contract.md's format uses:
 *  `Severity | File:Line | Issue | Why it matters | Suggested fix`. A field's own text can
 *  legitimately contain a bare `|` character (e.g. a Suggested fix mentioning a TypeScript union
 *  type like `string | number`), so the delimiter search below only treats `|` as a field
 *  boundary when it appears in this exact space-pipe-space form — a bare `|` with no surrounding
 *  space is left untouched inside whichever field it falls in. */
const FIELD_SEPARATOR = " | ";
const FIELD_COUNT = 5;

/** Splits one line into exactly FIELD_COUNT fields by finding the first (FIELD_COUNT - 1)
 *  occurrences of FIELD_SEPARATOR, left to right, and treating everything after the last one as
 *  the final field's raw content — deliberately NOT splitting on every bare `|` character.
 *  Returns null if the line doesn't contain enough separator occurrences to produce
 *  FIELD_COUNT fields (i.e. it isn't a well-formed finding line at all). Any `|` remaining inside
 *  the fifth field (or, if an earlier field's own text happens to contain a " | " sequence, one
 *  misattributed to an earlier boundary) is a known, accepted limitation of this line-oriented
 *  heuristic — see parsePipeDelimitedFindings's own docs for why exact parsing isn't attempted. */
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

/** Parses an agent's response text into structured findings per
 *  shared/agents/severity-output-contract.md's pipe-delimited format:
 *  `Severity | File:Line | Issue | Why it matters | Suggested fix`, one finding per line.
 *  Tolerant by design: splits on lines, trims whitespace around each field, and silently skips
 *  any line that isn't a well-formed 5-field finding (headers, prose, blank lines) — including
 *  the Silence rule's "No X issues found in this diff." sentence, which is zero findings, not an
 *  error. A line is only accepted as a finding if its first field is one of the four known
 *  severity tiers, which is what keeps stray prose containing the field separator (e.g. a
 *  markdown table row) from being misparsed as a finding. Splitting is delimiter-based (see
 *  splitFindingFields), not "split on every `|`" — a field's own text (most often Suggested fix,
 *  e.g. a TypeScript union type like `string | number`) can contain a bare pipe without breaking
 *  the parse or silently dropping the finding. */
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
 *  `ablate` needs (the pipe-delimited findings live in this text), as opposed to
 *  preload-probe.mjs's `lastMessageUpdateUsage`, which only needs the numeric usage block.
 *
 *  Event-shape source (inspected directly, since nothing in this repo already extracted final
 *  assistant text from a JSON-mode event stream):
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

/** Extracts the provider-level failure reason from a `pi --mode json` NDJSON stream, or null
 *  when every turn completed without error.
 *
 *  Why this exists (ground truth, captured live 2026-08-31 against pi 0.84.4 with an
 *  openai-codex quota exhaustion): a dispatch whose provider call fails NEVER emits
 *  `message_update` events — the turn dies before streaming — so `lastMessageUpdateUsage`
 *  sees nothing while `pi` STILL EXITS 0 (dist/modes/print-mode.js only returns non-zero when
 *  the prompt loop itself throws; a provider failure surfaces as message-level events carrying
 *  `stopReason:"error"` + `errorMessage` on `message_start`/`message_end`/`turn_end`). The only
 *  reliable failure signal is therefore in the event stream, not the exit code — and a dispatch
 *  with no usage is not a measurement: reporting it as "cache: NO" would read as a real zero
 *  cache-read fraction. Callers hard-fail on this function's non-null result.
 *
 *  Defensive line parsing mirrors extractFinalAssistantText: non-JSON lines are skipped, never
 *  fatal. An errored message with no `errorMessage` string still returns a non-empty fallback
 *  (stopReason:"error" alone is a failure worth failing on). */
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

/** Extracts the turn's final usage from a `pi --mode json` NDJSON stream: the usage block of
 *  the LAST assistant `message_end` whose stopReason isn't "error" — the authoritative,
 *  post-billing snapshot — falling back to the last `message_update` usage snapshot only when
 *  no assistant message_end carried usage.
 *
 *  Why message_end, not message_update (ground truth, captured live 2026-08-31, pi 0.84.4,
 *  openai-codex/gpt-5.6-sol): codex's message_update events carry ZEROED usage snapshots for
 *  the whole stream — the provider reports no interim usage — so reading the last snapshot
 *  recorded 0/0/0 and $0.00 for a turn whose final message_end billed input=13580 / $0.068.
 *  Providers that DO report cumulative usage mid-stream (zai/glm-5.3) produce identical
 *  message_end and message_update numbers, so preferring message_end costs nothing there.
 *  An ERRORED message_end (stopReason "error") is skipped — failure reporting belongs to
 *  extractDispatchError, which callers consult when usage is missing or implausible.
 *
 *  Returns null when neither source yielded a usage object. */
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

/** Compares one omit-arm's findings against the matching baseline's findings for the same diff.
 *
 *  Matching heuristic (approximate BY DESIGN — two independent LLM dispatches reviewing the same
 *  diff will not produce byte-identical prose, so findings can't be matched by exact-equality):
 *  match findings by their `fileLine` field. Both arms review the
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

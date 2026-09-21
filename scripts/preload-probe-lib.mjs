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
const CANARY_FOOTER_RE = /^SWB-CANARIES-APPLIED: (?:NONE|.+)$/;
const FILE_LINE_RE = /^(.+):[1-9]\d*$/;

function isValidFileLine(value) {
  if (typeof value !== "string" || value !== value.trim()) return false;
  const match = FILE_LINE_RE.exec(value);
  return Boolean(match && match[1].trim());
}

function isNonEmptyTrimmedString(value) {
  return typeof value === "string" && value.length > 0 && value === value.trim();
}

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
    if (!isValidFileLine(fileLine) || !issue) continue;
    findings.push({ severity, fileLine, issue, whyItMatters, suggestedFix });
  }
  return findings;
}

/** Parses a paid ablation response fail-closed: zero findings is valid only when the agent
 *  emitted the severity contract's explicit no-issues sentence. Free-form prose cannot be
 *  silently converted into a clean measurement. */
export function parseAblationResponse(responseText) {
  const findings = [];
  let sawNoIssues = false;
  for (const rawLine of (responseText ?? "").split("\n")) {
    const line = rawLine.trim();
    if (!line || CANARY_FOOTER_RE.test(line)) continue;
    if (NO_ISSUES_SENTENCE_RE.test(line)) {
      if (sawNoIssues) {
        throw new Error("ablation response contained a duplicate no-issues sentence");
      }
      sawNoIssues = true;
      continue;
    }
    const parts = splitFindingFields(line);
    if (parts) {
      const [severity, fileLine, issue, whyItMatters, suggestedFix] = parts;
      if (
        severity in SEVERITY_RANK &&
        isValidFileLine(fileLine) &&
        issue &&
        whyItMatters &&
        suggestedFix
      ) {
        findings.push({ severity, fileLine, issue, whyItMatters, suggestedFix });
        continue;
      }
    }
    throw new Error(`ablation response contained unexpected output line: ${line}`);
  }
  if (sawNoIssues && findings.length > 0) {
    throw new Error("ablation response mixed findings with an explicit no-issues sentence");
  }
  if (findings.length > 0) return findings;
  if (sawNoIssues) return [];
  throw new Error(
    "ablation response contained neither structured findings nor an explicit no-issues sentence",
  );
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

/** Verifies that the final successful assistant turn used the explicitly requested provider/model.
 *  A fallback or missing identity invalidates provider-dependent ablation evidence. */
export function modelIdentityOrDispatchError(ndjson, requestedModel) {
  let actual = null;
  for (const line of ndjson.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let obj;
    try {
      obj = JSON.parse(trimmed);
    } catch {
      continue;
    }
    const message = obj?.type === "message_end" ? obj.message : null;
    if (
      message?.role === "assistant" &&
      message.stopReason !== "error" &&
      typeof message.provider === "string" &&
      typeof message.model === "string"
    ) {
      actual = `${message.provider}/${message.model}`;
    }
  }
  if (!actual) {
    throw new Error("dispatch produced no provider/model identity");
  }
  if (actual !== requestedModel) {
    throw new Error(`requested ${requestedModel} but received ${actual}`);
  }
  return actual;
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

const ABLATION_SCHEMA_VERSION = 2;
const ABLATION_ARMS = ["baseline", "omit"];

function assertNonEmptyString(value, field) {
  if (!isNonEmptyTrimmedString(value)) {
    throw new Error(`invalid ablation record: ${field} must be a non-empty string`);
  }
}

export function validateAblationRecord(record, index = 0) {
  if (!record || typeof record !== "object") {
    throw new Error(`invalid ablation record at index ${index}: expected an object`);
  }
  if (record.schemaVersion !== ABLATION_SCHEMA_VERSION) {
    throw new Error(
      `unsupported ablation record schema at index ${index}; archive legacy data before continuing`,
    );
  }
  for (const field of ["sweep", "agent", "omitted", "diff", "model", "commit", "promptFingerprint", "ts"]) {
    assertNonEmptyString(record[field], field);
  }
  if (!ABLATION_ARMS.includes(record.arm)) {
    throw new Error(`invalid ablation record: arm must be baseline or omit`);
  }
  if (!Array.isArray(record.findings)) {
    throw new Error(`invalid ablation record: findings must be an array`);
  }
  const findingLocations = new Set();
  for (const finding of record.findings) {
    if (
      !finding ||
      typeof finding !== "object" ||
      !(finding.severity in SEVERITY_RANK) ||
      !isValidFileLine(finding.fileLine) ||
      [finding.issue, finding.whyItMatters, finding.suggestedFix].some(
        (field) => !isNonEmptyTrimmedString(field),
      )
    ) {
      throw new Error(`invalid finding in ablation record`);
    }
    if (findingLocations.has(finding.fileLine)) {
      throw new Error(`duplicate finding location in ablation record: ${finding.fileLine}`);
    }
    findingLocations.add(finding.fileLine);
  }
  if (!record.usage || typeof record.usage !== "object") {
    throw new Error(`invalid ablation record: usage is required`);
  }
  for (const field of ["input", "output", "cacheRead", "cacheWrite"]) {
    if (
      typeof record.usage[field] !== "number" ||
      !Number.isFinite(record.usage[field]) ||
      record.usage[field] < 0
    ) {
      throw new Error(`invalid ablation record: usage.${field} must be a nonnegative finite number`);
    }
  }
  if (record.usage.input + record.usage.cacheRead + record.usage.cacheWrite === 0) {
    throw new Error(`invalid ablation record: usage reported zero billed input/cache tokens`);
  }
  if (
    !record.usage.cost ||
    typeof record.usage.cost.total !== "number" ||
    !Number.isFinite(record.usage.cost.total) ||
    record.usage.cost.total < 0
  ) {
    throw new Error(`invalid ablation record: usage.cost.total must be a finite number`);
  }
  if (!record.corpus || typeof record.corpus !== "object") {
    throw new Error(`invalid ablation record: corpus metadata is required`);
  }
  assertNonEmptyString(record.corpus.fingerprint, "corpus.fingerprint");
  if (
    !Array.isArray(record.corpus.files) ||
    record.corpus.files.length === 0 ||
    record.corpus.files.some((file) => typeof file !== "string" || file.length === 0) ||
    new Set(record.corpus.files).size !== record.corpus.files.length
  ) {
    throw new Error(`invalid ablation record: corpus.files must contain unique filenames`);
  }
  if (!record.corpus.files.includes(record.diff)) {
    throw new Error(`invalid ablation record: diff "${record.diff}" is absent from corpus.files`);
  }
  return record;
}

function pairKey(record) {
  return JSON.stringify([record.sweep, record.agent, record.omitted]);
}

function armKey(record) {
  return JSON.stringify([record.sweep, record.agent, record.omitted, record.diff, record.arm]);
}

function sameStringArray(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function validatedGroups(records) {
  const groups = new Map();
  const seenArms = new Set();
  for (const [index, candidate] of records.entries()) {
    const record = validateAblationRecord(candidate, index);
    const key = armKey(record);
    if (seenArms.has(key)) {
      throw new Error(
        `duplicate ablation arm for sweep=${record.sweep} agent=${record.agent} ` +
          `omitted=${record.omitted} diff=${record.diff} arm=${record.arm}`,
      );
    }
    seenArms.add(key);
    const groupKey = pairKey(record);
    const group = groups.get(groupKey) ?? [];
    group.push(record);
    groups.set(groupKey, group);
  }

  for (const group of groups.values()) {
    const first = group[0];
    for (const record of group.slice(1)) {
      if (record.model !== first.model) {
        throw new Error(`mixed model values in ablation pair ${first.agent}/${first.omitted}`);
      }
      if (record.commit !== first.commit) {
        throw new Error(`mixed commit values in ablation pair ${first.agent}/${first.omitted}`);
      }
      if (
        record.corpus.fingerprint !== first.corpus.fingerprint ||
        !sameStringArray(record.corpus.files, first.corpus.files)
      ) {
        throw new Error(`mixed corpus metadata in ablation pair ${first.agent}/${first.omitted}`);
      }
      const sameArm = group.find((other) => other.arm === record.arm && other !== record);
      if (sameArm && sameArm.promptFingerprint !== record.promptFingerprint) {
        throw new Error(`mixed prompt fingerprints in ablation pair ${first.agent}/${first.omitted}`);
      }
    }
  }
  return groups;
}

function assertSweepProvenance(groups, identity) {
  for (const group of groups.values()) {
    const record = group[0];
    if (record.sweep !== identity.sweep) continue;
    if (record.model !== identity.model) {
      throw new Error(`mixed model values in sweep ${identity.sweep}`);
    }
    if (record.commit !== identity.commit) {
      throw new Error(`mixed commit values in sweep ${identity.sweep}`);
    }
    if (
      record.corpus.fingerprint !== identity.corpus.fingerprint ||
      !sameStringArray(record.corpus.files, identity.corpus.files)
    ) {
      throw new Error(`mixed corpus metadata in sweep ${identity.sweep}`);
    }
  }
}

function assertIdentityMatch(record, identity) {
  if (record.model !== identity.model) {
    throw new Error(`mixed model values in ablation pair ${identity.agent}/${identity.omitted}`);
  }
  if (record.commit !== identity.commit) {
    throw new Error(`mixed commit values in ablation pair ${identity.agent}/${identity.omitted}`);
  }
  if (
    record.corpus.fingerprint !== identity.corpus.fingerprint ||
    !sameStringArray(record.corpus.files, identity.corpus.files)
  ) {
    throw new Error(`mixed corpus metadata in ablation pair ${identity.agent}/${identity.omitted}`);
  }
  if (record.promptFingerprint !== identity.promptFingerprints[record.arm]) {
    throw new Error(`mixed prompt fingerprints in ablation pair ${identity.agent}/${identity.omitted}`);
  }
}

/** Returns only the dispatch arms absent from a valid partial pair. Existing duplicate or
 *  provenance-mismatched data fails before a resume can spend more money. */
export function planAblationArms(records, identity) {
  for (const field of ["sweep", "agent", "omitted", "model", "commit"]) {
    assertNonEmptyString(identity[field], `identity.${field}`);
  }
  if (!identity.corpus || !identity.promptFingerprints) {
    throw new Error("invalid ablation identity: corpus and promptFingerprints are required");
  }
  const groups = validatedGroups(records);
  assertSweepProvenance(groups, identity);
  const matching = groups.get(JSON.stringify([identity.sweep, identity.agent, identity.omitted])) ?? [];
  for (const record of matching) assertIdentityMatch(record, identity);
  const completed = new Set(matching.map((record) => `${record.diff}\0${record.arm}`));
  const pending = [];
  for (const diff of identity.corpus.files) {
    for (const arm of ABLATION_ARMS) {
      if (!completed.has(`${diff}\0${arm}`)) pending.push({ diff, arm });
    }
  }
  return pending;
}

/** Validates complete per-skill coverage and computes report-ready lost/downgraded details.
 *  No summary is returned unless every expected diff has exactly one record for each arm. */
export function summarizeAblationRecords(records, { sweep, agent } = {}) {
  assertNonEmptyString(sweep, "report sweep");
  const groups = validatedGroups(records);
  const sweepGroups = [...groups.values()].filter((group) => group[0].sweep === sweep);
  if (sweepGroups.length > 0) {
    const first = sweepGroups[0][0];
    assertSweepProvenance(groups, {
      sweep,
      model: first.model,
      commit: first.commit,
      corpus: first.corpus,
    });
  }
  const summaries = [];
  for (const group of groups.values()) {
    const first = group[0];
    if (first.sweep !== sweep || (agent && first.agent !== agent)) continue;
    const byDiffAndArm = new Map(group.map((record) => [`${record.diff}\0${record.arm}`, record]));
    const expectedCount = first.corpus.files.length * ABLATION_ARMS.length;
    if (group.length !== expectedCount) {
      throw new Error(
        `incomplete ablation pair ${first.agent}/${first.omitted}: expected ${expectedCount} arms, ` +
          `found ${group.length}`,
      );
    }
    let lostCount = 0;
    let downgradedCount = 0;
    const diffs = [];
    for (const diff of first.corpus.files) {
      const baseline = byDiffAndArm.get(`${diff}\0baseline`);
      const omit = byDiffAndArm.get(`${diff}\0omit`);
      if (!baseline || !omit) {
        throw new Error(`incomplete ablation pair ${first.agent}/${first.omitted}: missing arm for ${diff}`);
      }
      const { lost, downgraded } = compareArm(baseline.findings, omit.findings);
      lostCount += lost.length;
      downgradedCount += downgraded.length;
      if (lost.length > 0 || downgraded.length > 0) diffs.push({ diff, lost, downgraded });
    }
    summaries.push({
      agent: first.agent,
      omitted: first.omitted,
      model: first.model,
      commit: first.commit,
      lost: lostCount,
      downgraded: downgradedCount,
      diffs,
    });
  }
  return summaries;
}

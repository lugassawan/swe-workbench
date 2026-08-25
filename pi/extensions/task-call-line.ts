/**
 * The `task` tool's custom renderers: a call-line renderer (`task · <agent>`, so concurrent
 * dispatched agents are distinguishable at a glance) and a result renderer (adds the resolved
 * thinking level, colored via Pi's own `thinking<Level>` theme tokens — the same tokens Pi's own
 * UI uses elsewhere, so a dispatch's reasoning depth reads in the same color language as the
 * rest of the session). Split from subagent.ts (at the line cap).
 *
 * The thinking level is never known at call-render time — it depends on `ctx.model`/
 * `ctx.thinkingLevel`, only available once `execute()` runs — so it's surfaced on the RESULT
 * render instead, which does receive the resolved `details`. `renderResult` only takes over
 * when a thinking level was actually resolved; otherwise it throws, deferring to Pi's own
 * default result rendering exactly as before this file added it.
 *
 * Stripper invariant: every `@earendil-works/*` import is type-only, so pytest runs under
 * `node --experimental-strip-types` with no node_modules; the one runtime specifier
 * (pi-tui below) resolves via Pi's jiti alias map in real sessions.
 */
import type { Theme, ThemeColor } from "@earendil-works/pi-coding-agent";
import type { Text } from "@earendil-works/pi-tui";
import type { ParentThinkingLevel } from "./model-policy.ts";

/** Single source of truth for the registered tool name — consumed by pi.registerTool(),
 *  the `--exclude-tools` argv builder, and the call line below, so a rename can't desync
 *  them. */
export const TASK_TOOL_NAME = "task";

/** Just the two members the renderer needs, so the pure formatter stays testable against
 *  a two-method stub theme. */
export type CallLineTheme = Pick<Theme, "fg" | "bold">;

/** pi-tui's Text constructor type — type-only, never resolved at module scope. */
type TextCtor = typeof Text;

/** Resolved once per process by the dynamic import below — dynamic because a static import
 *  would break the stripper invariant above. Undefined (unresolvable here) keeps every
 *  renderCall on the framework-fallback path; never re-attempted on failure. */
let textCtor: TextCtor | undefined;
void import("@earendil-works/pi-tui")
  .then((mod) => {
    textCtor = mod.Text;
  })
  .catch(() => {
    /* unresolvable in this environment — plain-heading fallback, by design */
  });

/** Terminal/bidi-spoofing chars (controls, RLO/ALM/ZWSP, isolates, separators) with no
 *  place in a rendered id — legitimate ids are [a-z0-9-], so nothing valid is lost. */
const UNSAFE_ID_CHARS = /[\u0000-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2066-\u2069]/g;

/** Shared by this render path and subagent.ts's unknown-agent error — both surface the id
 *  to the terminal before validation sanitizes it. */
export function sanitizeAgentId(agent: string): string {
  return agent.replace(UNSAFE_ID_CHARS, "");
}

/** Composes the call line: the toolTitle segment is byte-identical to Pi's own
 *  createCallFallback() formula, so the enriched line is the fallback heading plus a muted
 *  agent suffix. Exported pure so the nodeless pytest driver can exercise it directly. */
export function composeTaskCallLine(agent: string, theme: CallLineTheme): string {
  const safe = sanitizeAgentId(agent);
  return theme.fg("toolTitle", theme.bold(TASK_TOOL_NAME)) + theme.fg("muted", ` · ${safe}`);
}

/** Renders the task call line. Throws — deliberately — when no agent name is present
 *  (partial mid-stream args, blank, or strips-to-empty) or Text is unresolved: Pi's
 *  ToolExecutionComponent catches renderer throws and swaps in its createCallFallback()
 *  heading, byte-identical to the pre-change display. Injectable ctor so the resolved path
 *  is testable without pi-tui. */
export function renderTaskCall(args: unknown, theme: CallLineTheme, ctor: TextCtor | undefined): Text {
  // Narrowing (not casting) args from unknown — casts are forbidden here.
  const agent =
    typeof args === "object" && args !== null && "agent" in args && typeof args.agent === "string"
      ? args.agent.trim()
      : "";
  // A control-only id strips to empty — fall back rather than render a dangling "task · ".
  if (agent === "" || sanitizeAgentId(agent) === "") {
    throw new Error("task renderCall: no agent name available — framework fallback applies");
  }
  if (ctor === undefined) throw new Error("task renderCall: pi-tui unavailable — framework fallback applies");
  return new ctor(composeTaskCallLine(agent, theme), 0, 0);
}

/** The renderCall subagent.ts registers — renderTaskCall bound to the memoized ctor. */
export function taskRenderCall(args: unknown, theme: CallLineTheme): Text {
  return renderTaskCall(args, theme, textCtor);
}

const THINKING_COLOR_TOKEN: Readonly<Record<ParentThinkingLevel, ThemeColor>> = {
  off: "thinkingOff",
  minimal: "thinkingMinimal",
  low: "thinkingLow",
  medium: "thinkingMedium",
  high: "thinkingHigh",
  xhigh: "thinkingXhigh",
  max: "thinkingMax",
};

function isParentThinkingLevel(value: unknown): value is ParentThinkingLevel {
  return typeof value === "string" && Object.hasOwn(THINKING_COLOR_TOKEN, value);
}

/** Same call-line format, plus the resolved thinking level in its own semantic color. */
export function composeTaskResultHeader(agent: string, theme: CallLineTheme, thinking: ParentThinkingLevel): string {
  return `${composeTaskCallLine(agent, theme)} ${theme.fg(THINKING_COLOR_TOKEN[thinking], `(${thinking})`)}`;
}

/** Same line-count Pi's own createResultFallback() collapses to when a result isn't expanded
 *  (tool-execution.js's FALLBACK_PREVIEW_LINES) — kept in sync by inspection, not import, since
 *  that constant isn't part of the SDK's public surface. */
const RESULT_PREVIEW_LINES = 10;

/** Narrowing (not casting) `details` from unknown, mirroring this file's other args-narrowing
 *  call sites. */
function thinkingFromDetails(details: unknown): unknown {
  return typeof details === "object" && details !== null && "thinking" in details ? details.thinking : undefined;
}

/** Renders the task result line: the same call-line format plus a colored thinking-level
 *  suffix, followed by the agent's own output text — collapsed to RESULT_PREVIEW_LINES with a
 *  "more lines" marker when not expanded, mirroring Pi's own createResultFallback() truncation
 *  contract (every other tool row collapses by default; this one must too, not dump the full,
 *  possibly-50000-char capped output unconditionally). Throws — deliberately — when no thinking
 *  level was resolved (nothing extra to show) or Text is unresolved, so Pi's own default result
 *  rendering takes over unchanged; see this file's header for why the thinking level can only
 *  ever be known here, not at call-render time. Injectable ctor so the resolved path is testable
 *  without pi-tui. */
export function renderTaskResult(
  result: { content: readonly { type: string; text?: string }[]; details?: unknown },
  theme: CallLineTheme,
  ctor: TextCtor | undefined,
  agent: string,
  expanded: boolean,
): Text {
  const thinking = thinkingFromDetails(result.details);
  if (!isParentThinkingLevel(thinking)) {
    throw new Error("task renderResult: no thinking level resolved — framework fallback applies");
  }
  if (ctor === undefined) throw new Error("task renderResult: pi-tui unavailable — framework fallback applies");
  const header = composeTaskResultHeader(agent, theme, thinking);
  const rawBody = result.content
    .filter((c) => c.type === "text" && typeof c.text === "string")
    .map((c) => c.text as string)
    .join("\n\n");
  if (!rawBody) return new ctor(header, 0, 0);

  const lines = rawBody.split("\n");
  const displayLines = expanded ? lines : lines.slice(0, RESULT_PREVIEW_LINES);
  const remaining = lines.length - displayLines.length;
  let body = displayLines.map((line) => theme.fg("toolOutput", line)).join("\n");
  if (remaining > 0) {
    body += theme.fg("muted", `\n... (${remaining} more line${remaining === 1 ? "" : "s"} — expand to see all)`);
  }
  return new ctor(`${header}\n\n${body}`, 0, 0);
}

/** The renderResult subagent.ts registers — renderTaskResult bound to the memoized ctor, agent
 *  id and expanded state read from the shared render context/options. */
export function taskRenderResult(
  result: unknown,
  options: unknown,
  theme: CallLineTheme,
  context: { args: unknown },
): Text {
  // Narrowing (not casting) context.args from unknown — same posture as renderTaskCall's args.
  const args = context.args;
  const agent =
    typeof args === "object" && args !== null && "agent" in args && typeof args.agent === "string"
      ? args.agent.trim()
      : "";
  const expanded =
    typeof options === "object" && options !== null && "expanded" in options && typeof options.expanded === "boolean"
      ? options.expanded
      : false;
  return renderTaskResult(
    result as { content: readonly { type: string; text?: string }[]; details?: unknown },
    theme,
    textCtor,
    agent,
    expanded,
  );
}

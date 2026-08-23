/**
 * The `task` call-line renderer: renders `task · <agent>` so concurrent dispatched
 * agents are distinguishable at a glance. Split from subagent.ts (at the line cap).
 *
 * Stripper invariant: every `@earendil-works/*` import is type-only, so pytest runs under
 * `node --experimental-strip-types` with no node_modules; the one runtime specifier
 * (pi-tui below) resolves via Pi's jiti alias map in real sessions.
 */
import type { Theme } from "@earendil-works/pi-coding-agent";
import type { Text } from "@earendil-works/pi-tui";

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

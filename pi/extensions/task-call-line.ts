/**
 * The `task` activity call-line renderer (#646): composes and renders `task · <agent>` for
 * the tool-call row so concurrent dispatched agents are distinguishable at a glance.
 *
 * Split out of subagent.ts (not merged into it) because that file carries the whole dispatch
 * pipeline and sits at the repo's per-file line cap; this module is the render seam only —
 * subagent.ts registers the renderCall, this file owns everything below it. Like subagent.ts
 * (and unlike SDK-free agent-spec.ts/model-tier.ts), this module touches Pi SDK types.
 *
 * Stripper invariant: every `@earendil-works/*` import here is TYPE-ONLY, so
 * `node --experimental-strip-types` behavioural tests run with no node_modules. The one
 * runtime specifier — pi-tui, for the Text constructor — is a fire-and-forget dynamic
 * import resolved by Pi's own jiti alias map (loader.js maps core packages for extensions);
 * where it cannot resolve, the renderer throws and Pi's ToolExecutionComponent swaps in its
 * plain createCallFallback() heading, byte-identical to the pre-#646 display.
 */
import type { Theme } from "@earendil-works/pi-coding-agent";
import type { Text } from "@earendil-works/pi-tui";

/** Single source of truth for the tool's registered name — subagent.ts consumes this for
 *  both pi.registerTool() and the `--exclude-tools` argv builder, so a rename can't silently
 *  desync registration from the recursion guard. */
export const TASK_TOOL_NAME = "task";

/** The subset of Pi's Theme the call-line renderer needs — interface segregation so the
 *  pure formatter stays testable against a two-method stub (and so a future Theme superset
 *  still satisfies it structurally). */
export type CallLineTheme = Pick<Theme, "fg" | "bold">;

/** pi-tui's Text constructor, obtained lazily (see `textCtor` below). Typed from the
 *  type-only import so the memoized slot and the exported renderer share the real shape
 *  without any runtime resolution of the specifier at module scope. */
type TextCtor = typeof Text;

/** Resolved once per process by the fire-and-forget dynamic import below. Dynamic (not
 *  static) because every top-level specifier in this directory must stay strippable by
 *  `node --experimental-strip-types` with no node_modules present — the behavioural pytest
 *  layer depends on that invariant. Real pi resolves the specifier through its jiti alias
 *  map; the nodeless stripper environment does not, the import rejects, and `undefined`
 *  here means renderCall falls back to Pi's own plain heading via its documented
 *  catch-and-swap contract. Never re-attempted on failure. */
let textCtor: TextCtor | undefined;
void import("@earendil-works/pi-tui")
  .then((mod) => {
    textCtor = mod.Text;
  })
  .catch(() => {
    /* unresolvable in this environment — plain-heading fallback, by design */
  });

/** Terminal-spoofing chars with no place in a rendered agent id: C0/C1/DEL controls
 *  (ESC/OSC/newline — screen-clear and title spoofing), zero-width and bidi format chars
 *  (ZWSP, ALM, LRM/RLM, RLO/LRO and isolates — visual reordering), and the Unicode
 *  separators. Legitimate ids are [a-z0-9-], so nothing valid is ever lost. */
const UNSAFE_ID_CHARS = /[\u0000-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2066-\u2069]/g;

/** Strips UNSAFE_ID_CHARS — shared by the render path and subagent.ts's unknown-agent error,
 *  since both surface the id to the terminal before/without validation having sanitized it. */
export function sanitizeAgentId(agent: string): string {
  return agent.replace(UNSAFE_ID_CHARS, "");
}

/** Composes the `task` activity call line as `task · <agent>`: the toolTitle segment is
 *  byte-identical to Pi's own createCallFallback() formula (tool-execution.js), so the
 *  enriched line is literally the fallback heading plus a muted suffix. The agent segment is
 *  stripped of terminal-spoofing chars — renderCall fires on mid-stream args BEFORE
 *  execute() validates the id, and pi-tui's ANSI wrapping preserves embedded escapes.
 *  Exported pure for the same reason as subagent.ts's capOutput — the nodeless pytest
 *  driver can exercise it directly. */
export function composeTaskCallLine(agent: string, theme: CallLineTheme): string {
  const safe = sanitizeAgentId(agent);
  return theme.fg("toolTitle", theme.bold(TASK_TOOL_NAME)) + theme.fg("muted", ` · ${safe}`);
}

/** Renders the task call line for a tool-call display. Throws — deliberately — when no
 *  agent name is present (partial mid-stream args, blank agent, or an id that strips to
 *  empty) or when pi-tui's Text could not be resolved: Pi's ToolExecutionComponent catches
 *  renderer throws and swaps in its own createCallFallback() heading, which is exactly the
 *  pre-#646 display. That throw-as-degradation is the SDK's documented fallback contract,
 *  not an error path. Exported with an injectable constructor so the resolved path is
 *  testable without pi-tui present. */
export function renderTaskCall(args: unknown, theme: CallLineTheme, ctor: TextCtor | undefined): Text {
  // `in`-narrowing keeps this cast-free under unknown (TS narrows to object & Record<"agent", unknown>).
  const agent =
    typeof args === "object" && args !== null && "agent" in args && typeof args.agent === "string"
      ? args.agent.trim()
      : "";
  // Empty-after-strip (control-only id) must fall back too, or the line degrades to a
  // dangling "task · " separator.
  if (agent === "" || sanitizeAgentId(agent) === "") {
    throw new Error("task renderCall: no agent name available — framework fallback applies");
  }
  if (ctor === undefined) throw new Error("task renderCall: pi-tui unavailable — framework fallback applies");
  return new ctor(composeTaskCallLine(agent, theme), 0, 0);
}

/** The renderCall subagent.ts registers — renderTaskCall bound to the module's memoized
 *  Text constructor. */
export function taskRenderCall(args: unknown, theme: CallLineTheme): Text {
  return renderTaskCall(args, theme, textCtor);
}

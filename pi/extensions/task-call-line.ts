/** Renders Pi task rows with dispatch metadata as it becomes available. */
import type { Theme, ThemeColor } from "@earendil-works/pi-coding-agent";
import type { Component, Text } from "@earendil-works/pi-tui";
import type { ParentThinkingLevel } from "./model-policy.ts";

/** Single source of truth for the registered tool name. */
export const TASK_TOOL_NAME = "task";

/** Just the two members the renderer needs, so pure formatters accept stub themes. */
export type CallLineTheme = Pick<Theme, "fg" | "bold">;

interface TaskDispatchRenderMetadata {
  readonly modelId: string;
  readonly thinking: ParentThinkingLevel;
}

export interface TaskRenderState {
  dispatch?: TaskDispatchRenderMetadata;
}

interface TaskRenderContext {
  args: unknown;
  state: TaskRenderState;
  invalidate: () => void;
}

/** pi-tui's Text constructor type, which is never resolved at module scope. */
type TextCtor = typeof Text;

let textCtor: TextCtor | undefined;
void import("@earendil-works/pi-tui")
  .then((mod) => {
    textCtor = mod.Text;
  })
  .catch(() => {
    /* The framework fallback handles environments without pi-tui. */
  });

const UNSAFE_ID_CHARS = /[\u0000-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2066-\u2069]/g;

/** Strips terminal and bidirectional controls before an identifier reaches the terminal. */
export function sanitizeAgentId(agent: string): string {
  return agent.replace(UNSAFE_ID_CHARS, "");
}

/** Composes the call line from Pi's fallback heading plus a muted agent suffix. */
export function composeTaskCallLine(agent: string, theme: CallLineTheme): string {
  const safe = sanitizeAgentId(agent);
  return theme.fg("toolTitle", theme.bold(TASK_TOOL_NAME)) + theme.fg("muted", ` · ${safe}`);
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

function dispatchMetadataFromDetails(details: unknown): TaskDispatchRenderMetadata | undefined {
  if (typeof details !== "object" || details === null) return undefined;
  if (!("model" in details) || typeof details.model !== "string") return undefined;
  if (!("thinking" in details) || !isParentThinkingLevel(details.thinking)) return undefined;

  const separator = details.model.indexOf("/");
  const rawModelId = separator === -1 ? details.model : details.model.slice(separator + 1);
  const modelId = sanitizeAgentId(rawModelId);
  return modelId === "" ? undefined : { modelId, thinking: details.thinking };
}

/** Adds resolved model metadata to a task call line. */
export function composeTaskDispatchLine(
  agent: string,
  theme: CallLineTheme,
  dispatch: TaskDispatchRenderMetadata,
): string {
  return (
    composeTaskCallLine(agent, theme) +
    theme.fg("muted", ` (${dispatch.modelId} `) +
    theme.fg(THINKING_COLOR_TOKEN[dispatch.thinking], dispatch.thinking) +
    theme.fg("muted", ")")
  );
}

/** Renders a task call line, adding metadata synchronized from partial updates. */
export function renderTaskCall(
  args: unknown,
  theme: CallLineTheme,
  ctor: TextCtor | undefined,
  state?: TaskRenderState,
): Text {
  const agent =
    typeof args === "object" && args !== null && "agent" in args && typeof args.agent === "string"
      ? args.agent.trim()
      : "";
  if (agent === "" || sanitizeAgentId(agent) === "") {
    throw new Error("task renderCall: no agent name available — framework fallback applies");
  }
  if (ctor === undefined) throw new Error("task renderCall: pi-tui unavailable — framework fallback applies");

  const line = state?.dispatch === undefined
    ? composeTaskCallLine(agent, theme)
    : composeTaskDispatchLine(agent, theme, state.dispatch);
  return new ctor(line, 0, 0);
}

/** Renders a task call line with state shared by Pi's call and result slots. */
export function taskRenderCall(
  args: unknown,
  theme: CallLineTheme,
  context?: Pick<TaskRenderContext, "state">,
): Text {
  return renderTaskCall(args, theme, textCtor, context?.state);
}

const RESULT_PREVIEW_LINES = 10;

function emptyComponent(): Component {
  return { render: () => [], invalidate: () => {} };
}

function synchronizeDispatchState(
  details: unknown,
  context: Pick<TaskRenderContext, "state" | "invalidate">,
): TaskDispatchRenderMetadata {
  const dispatch = dispatchMetadataFromDetails(details);
  if (dispatch === undefined) {
    throw new Error("task renderResult: no dispatch metadata resolved — framework fallback applies");
  }

  const current = context.state.dispatch;
  if (current?.modelId !== dispatch.modelId || current.thinking !== dispatch.thinking) {
    context.state.dispatch = dispatch;
    context.invalidate();
  }
  return dispatch;
}

/** Renders only task output; the call renderer owns the stable task header. */
export function renderTaskResult(
  result: { content: readonly { type: string; text?: string }[]; details?: unknown },
  theme: CallLineTheme,
  ctor: TextCtor | undefined,
  _agent: string,
  expanded: boolean,
  context?: Pick<TaskRenderContext, "state" | "invalidate">,
  isPartial = false,
): Component {
  if (context === undefined) {
    if (dispatchMetadataFromDetails(result.details) === undefined) {
      throw new Error("task renderResult: no dispatch metadata resolved — framework fallback applies");
    }
  } else {
    synchronizeDispatchState(result.details, context);
  }
  if (ctor === undefined) throw new Error("task renderResult: pi-tui unavailable — framework fallback applies");
  if (isPartial) return emptyComponent();

  const rawBody = result.content
    .filter((content) => content.type === "text" && typeof content.text === "string")
    .map((content) => content.text)
    .join("\n\n");
  if (rawBody === "") return emptyComponent();

  const lines = rawBody.split("\n");
  const displayLines = expanded ? lines : lines.slice(0, RESULT_PREVIEW_LINES);
  const remaining = lines.length - displayLines.length;
  let body = displayLines.map((line) => theme.fg("toolOutput", line)).join("\n");
  if (remaining > 0) {
    body += theme.fg("muted", `\n... (${remaining} more line${remaining === 1 ? "" : "s"} — expand to see all)`);
  }
  return new ctor(body, 0, 0);
}

/** Renders a task result with state shared by Pi's call and result slots. */
export function taskRenderResult(
  result: unknown,
  options: unknown,
  theme: CallLineTheme,
  context: TaskRenderContext,
): Component {
  const args = context.args;
  const agent =
    typeof args === "object" && args !== null && "agent" in args && typeof args.agent === "string"
      ? args.agent.trim()
      : "";
  const expanded =
    typeof options === "object" && options !== null && "expanded" in options && options.expanded === true;
  const isPartial =
    typeof options === "object" && options !== null && "isPartial" in options && options.isPartial === true;
  return renderTaskResult(
    result as { content: readonly { type: string; text?: string }[]; details?: unknown },
    theme,
    textCtor,
    agent,
    expanded,
    context,
    isPartial,
  );
}

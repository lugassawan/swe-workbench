/**
 * submit_plan's presentation layer, split from phase.ts at its line cap (subagent.ts's
 * dispatch-resolver.ts precedent): the tool's parameter schema and the TUI Approve/Revise
 * picker. Same adapter posture as phase.ts — SDK types via `import type` only, pi-tui
 * components via dynamic import so registration never loads TUI code headless.
 */
import type { ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent";

// Plain JSON-Schema literal, never a TypeBox value import — ask-user.ts's module docstring
// records why value imports of bare specifiers break the pytest harness.
export const SUBMIT_PLAN_PARAMS_SCHEMA = {
  type: "object",
  properties: {
    plan: { type: "string", description: "The complete implementation plan, verbatim — the approval artifact." },
  },
  required: ["plan"],
  additionalProperties: false,
} as ToolDefinition["parameters"];

/** TUI Approve/Revise picker (ask-user.ts's themedSelect posture): resolves the chosen
 *  action, or undefined on dismissal/abort — never a default, so approval cannot happen by
 *  accident. Non-TUI modes never reach this (confirm fallback in the tool body). */
export async function approvalChoice(
  ctx: ExtensionContext,
  signal: AbortSignal | undefined,
): Promise<"Approve" | "Revise" | undefined> {
  const { Container, SelectList, Text } = await import("@earendil-works/pi-tui");
  return ctx.ui.custom((tui, theme, _kb, done) => {
    const settle = (value: "Approve" | "Revise" | undefined) => {
      signal?.removeEventListener("abort", onAbort);
      done(value);
    };
    const onAbort = () => settle(undefined);
    if (signal?.aborted) Promise.resolve().then(onAbort);
    else if (signal) signal.addEventListener("abort", onAbort);
    const container = new Container();
    container.addChild(new Text(theme.fg("accent", theme.bold("Approve plan?")), 1, 0));
    const list = new SelectList(
      [{ value: "Approve", label: "Approve" }, { value: "Revise", label: "Revise" }],
      2,
      {
        selectedPrefix: (t: string) => theme.fg("accent", t),
        selectedText: (t: string) => theme.fg("accent", t),
        description: (t: string) => theme.fg("muted", t),
        scrollInfo: (t: string) => theme.fg("dim", t),
        noMatch: (t: string) => theme.fg("warning", t),
      },
    );
    list.onSelect = (item: { value: string }) => settle(item.value === "Approve" ? "Approve" : "Revise");
    list.onCancel = () => settle(undefined);
    container.addChild(list);
    container.addChild(new Text(theme.fg("dim", "↑↓ navigate • enter select • esc cancel"), 1, 0));
    return {
      render: (w: number) => container.render(w),
      invalidate: () => container.invalidate(),
      handleInput: (data: string) => {
        list.handleInput?.(data);
        tui.requestRender();
      },
    };
  });
}

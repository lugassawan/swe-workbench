import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  DISPATCH_PROFILES,
  parentProfileGuidance,
  type DispatchProfile,
} from "./dispatch-profile.ts";
import {
  dispatchProfilePath,
  readDispatchProfile,
  writeDispatchProfile,
  type ProfileReadResult,
} from "./dispatch-profile-store.ts";
import { TASK_TOOL_NAME } from "./task-call-line.ts";

export const DISPATCH_PROFILE_COMMAND = "swe-workbench-profile";
const GUIDANCE_MARKER = "<!-- swe-workbench:dispatch-profile -->";
const GUIDANCE_BLOCK = new RegExp(`\\n?${GUIDANCE_MARKER}[\\s\\S]*?${GUIDANCE_MARKER}\\n?`, "g");

type ProfileStore = {
  readonly read: () => ProfileReadResult;
  readonly write: (profile: DispatchProfile) => void;
  readonly path: () => string;
};

export interface DispatchProfileController {
  read(): ProfileReadResult;
  ensureSelected(ctx: Pick<ExtensionContext, "hasUI" | "ui">): Promise<{
    readonly profile: DispatchProfile;
    readonly selectedNow: boolean;
  }>;
}

function isProfile(value: string): value is DispatchProfile {
  return (DISPATCH_PROFILES as readonly string[]).includes(value);
}

function profileFromChoice(choice: string | null | undefined): DispatchProfile | undefined {
  if (choice === null || choice === undefined) return undefined;
  const normalized = choice.trim().toLowerCase();
  return isProfile(normalized) ? normalized : undefined;
}

function defaultStore(): ProfileStore {
  const path = dispatchProfilePath();
  return {
    read: () => readDispatchProfile(path),
    write: (profile) => writeDispatchProfile(path, profile),
    path: () => path,
  };
}

function profileOptions(): string[] {
  return [
    "economy",
    "balanced",
    "full",
  ];
}

/** Registers user selection and parent-only guidance for the dispatch profile. */
export function registerDispatchProfile(pi: ExtensionAPI, store: ProfileStore = defaultStore()): DispatchProfileController {
  let pendingSelection: Promise<DispatchProfile | undefined> | undefined;

  async function select(ctx: Pick<ExtensionContext, "hasUI" | "ui">): Promise<DispatchProfile | undefined> {
    if (!ctx.hasUI) return undefined;
    return profileFromChoice(await ctx.ui.select("swe-workbench subagent profile", profileOptions()));
  }

  function selectOnce(ctx: Pick<ExtensionContext, "hasUI" | "ui">): Promise<DispatchProfile | undefined> {
    pendingSelection ??= select(ctx).finally(() => { pendingSelection = undefined; });
    return pendingSelection;
  }

  const controller: DispatchProfileController = {
    read: () => store.read(),
    async ensureSelected(ctx) {
      const current = store.read();
      if (current.kind === "configured") return { profile: current.profile, selectedNow: false };
      if (current.kind === "invalid") throw new Error(`invalid dispatch profile at ${store.path()}: ${current.reason}`);
      const profile = await selectOnce(ctx);
      if (profile === undefined) {
        if (!ctx.hasUI) {
          throw new Error(`dispatch profile needs an interactive session; run /${DISPATCH_PROFILE_COMMAND} first`);
        }
        throw new Error("dispatch profile selection was cancelled");
      }
      store.write(profile);
      return { profile, selectedNow: true };
    },
  };

  pi.registerCommand(DISPATCH_PROFILE_COMMAND, {
    description: "Choose the Economy, Balanced, or Full swe-workbench subagent profile",
    handler: async (args, ctx) => {
      const requested = args.trim();
      const profile = requested === "" ? await select(ctx) : profileFromChoice(requested);
      if (profile === undefined) {
        if (requested !== "") throw new Error(`unknown dispatch profile "${requested}"`);
        return;
      }
      store.write(profile);
      ctx.ui.notify(`swe-workbench dispatch profile: ${profile}`, "info");
    },
  });

  pi.on("before_agent_start", (_event, ctx) => {
    if (!pi.getActiveTools().includes(TASK_TOOL_NAME)) return undefined;
    const current = store.read();
    if (current.kind !== "configured") return undefined;
    return {
      systemPrompt: (_event.systemPrompt.replace(GUIDANCE_BLOCK, "").trimEnd() +
        `\n\n${GUIDANCE_MARKER}\n${parentProfileGuidance(current.profile)}\n${GUIDANCE_MARKER}\n`),
    };
  });

  return controller;
}

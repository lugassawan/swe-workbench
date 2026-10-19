/** Strict user-global persistence for the reviewed dispatch-profile enum. */
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { DISPATCH_PROFILES, type DispatchProfile } from "./dispatch-profile.ts";

export type ProfileReadResult =
  | { readonly kind: "missing" }
  | { readonly kind: "configured"; readonly profile: DispatchProfile }
  | { readonly kind: "invalid"; readonly reason: string };

const PROFILE_FILE = "dispatch-profile.json";
const PROFILE_DIRECTORY = "swe-workbench";

function isProfile(value: unknown): value is DispatchProfile {
  return typeof value === "string" && (DISPATCH_PROFILES as readonly string[]).includes(value);
}

/** Resolves only the user agent directory, never a target repository's `.pi` directory. */
export function dispatchProfilePath(env: NodeJS.ProcessEnv = process.env, home = homedir()): string {
  const agentDir = env.PI_CODING_AGENT_DIR ?? join(home, ".pi", "agent");
  return join(agentDir, PROFILE_DIRECTORY, PROFILE_FILE);
}

/** Reads a versioned document while rejecting every unreviewed field and value. */
export function readDispatchProfile(path: string): ProfileReadResult {
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch (error: unknown) {
    if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT") {
      return { kind: "missing" };
    }
    return { kind: "invalid", reason: "profile file could not be read" };
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { kind: "invalid", reason: "profile file is not valid JSON" };
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { kind: "invalid", reason: "profile document must be an object" };
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (keys.length !== 2 || !keys.every((key) => key === "version" || key === "profile")) {
    return { kind: "invalid", reason: "profile document has unknown or missing fields" };
  }
  if (record.version !== 1) return { kind: "invalid", reason: "profile version must be 1" };
  if (!isProfile(record.profile)) return { kind: "invalid", reason: "profile must be a reviewed enum value" };
  return { kind: "configured", profile: record.profile };
}

/** Writes the only accepted document through a same-directory atomic rename. */
export function writeDispatchProfile(path: string, profile: DispatchProfile): void {
  if (!isProfile(profile)) throw new Error("refusing to persist an unreviewed dispatch profile");
  const directory = dirname(path);
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const temporary = join(directory, `.${PROFILE_FILE}.${process.pid}.${Date.now()}.tmp`);
  try {
    writeFileSync(temporary, `${JSON.stringify({ version: 1, profile })}\n`, { encoding: "utf8", mode: 0o600 });
    renameSync(temporary, path);
  } finally {
    rmSync(temporary, { force: true });
  }
}

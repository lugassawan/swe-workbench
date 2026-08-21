/**
 * Spawns hooks/*.sh|py unchanged with a CC-shaped JSON payload piped to stdin, returning exit
 * code plus stdout/stderr. The ONLY file under pi/extensions/ that imports node:child_process
 * (pinned by tests/test_pi_contract.py) — every hook invocation funnels through this one
 * auditable process boundary (#607).
 *
 * pi.exec() has no stdin API, and every hook reads its payload from stdin — so the transport is
 * spawn() with a piped stdin and an argv array, never a shell-interpolated string.
 */
import { spawn } from "node:child_process";

export interface GuardRunResult {
  readonly code: number | null;
  readonly stdout: string;
  readonly stderr: string;
}

export interface GuardRunOptions {
  readonly interpreter: string;
  readonly scriptPath: string;
  readonly payload: Record<string, unknown>;
  /** bash_guard.sh runs `git rev-parse --abbrev-ref HEAD` against this, not any `.cwd` in the
   *  JSON payload. */
  readonly cwd: string;
  readonly pluginRoot: string;
  readonly signal: AbortSignal | undefined;
}

export type RunGuard = (options: GuardRunOptions) => Promise<GuardRunResult>;

const TIMEOUT_MS = 5_000;

export const runGuard: RunGuard = (options) =>
  new Promise((resolve, reject) => {
    const signal = options.signal
      ? AbortSignal.any([options.signal, AbortSignal.timeout(TIMEOUT_MS)])
      : AbortSignal.timeout(TIMEOUT_MS);

    const child = spawn(options.interpreter, [options.scriptPath], {
      cwd: options.cwd,
      env: { ...process.env, CLAUDE_PLUGIN_ROOT: options.pluginRoot },
      signal,
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";
    let settled = false;

    child.stdout?.on("data", (chunk: Buffer) => {
      stdout += chunk;
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderr += chunk;
    });

    // A guard that exits before its stdin is fully drained raises EPIPE on write/end — it
    // already decided its verdict, so keep draining for the exit code instead of treating this
    // as a spawn failure.
    child.stdin?.on("error", (err: NodeJS.ErrnoException) => {
      if (err.code !== "EPIPE" && !settled) {
        settled = true;
        reject(err);
      }
    });

    child.on("error", (err) => {
      if (!settled) {
        settled = true;
        reject(err);
      }
    });

    // "close" (not "exit") so stdout/stderr are fully drained before resolving.
    child.on("close", (code) => {
      if (!settled) {
        settled = true;
        resolve({ code, stdout, stderr });
      }
    });

    child.stdin?.write(JSON.stringify(options.payload));
    child.stdin?.end();
  });

import { chmodSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";

export interface OutputProjection {
  readonly text: string;
  readonly totalChars: number;
  readonly truncated: boolean;
  readonly fullOutputPath?: string;
}

export interface SessionOutputStore {
  project(text: string, maxChars: number): OutputProjection;
  cleanup(): void;
}

function safeSlice(text: string, start: number, end?: number): string {
  const slice = text.slice(start, end);
  return slice
    .replace(/^[\uDC00-\uDFFF]/, "")
    .replace(/[\uD800-\uDBFF]$/, "");
}

/** Private, runtime-scoped artifact store for overflow that should not enter parent context. */
export function createSessionOutputStore(maxArtifacts = 8): SessionOutputStore {
  let dir: string | undefined;
  const artifacts: string[] = [];

  function ensureDir(): string {
    try {
      if (dir !== undefined) readdirSync(dir);
    } catch {
      dir = undefined;
    }
    if (dir === undefined) dir = mkdtempSync(join(tmpdir(), "swe-workbench-subagent-output-"));
    return dir;
  }

  function truncatedText(text: string, maxChars: number, artifact?: string): string {
    const headLength = Math.max(1, Math.floor(maxChars * 0.7));
    const tailLength = Math.max(1, maxChars - headLength);
    const notice = artifact
      ? `[truncated — showing ${maxChars}/${text.length} chars; complete private output: ${artifact}]`
      : `[truncated — showing ${maxChars}/${text.length} chars]`;
    return `${safeSlice(text, 0, headLength)}\n\n${notice}\n\n${safeSlice(text, text.length - tailLength)}`;
  }

  return {
    project(text, maxChars) {
      if (text.length <= maxChars) return { text, totalChars: text.length, truncated: false };
      try {
        const artifact = join(ensureDir(), `output-${randomUUID()}.txt`);
        writeFileSync(artifact, text, { mode: 0o600, flag: "wx" });
        chmodSync(artifact, 0o600);
        artifacts.push(artifact);
        while (artifacts.length > maxArtifacts) {
          const oldest = artifacts.shift();
          if (oldest) rmSync(oldest, { force: true });
        }
        return { text: truncatedText(text, maxChars, artifact), totalChars: text.length, truncated: true, fullOutputPath: artifact };
      } catch {
        // A diagnostic artifact must never hide an otherwise successful child result.
        return { text: truncatedText(text, maxChars), totalChars: text.length, truncated: true };
      }
    },
    cleanup() {
      if (dir === undefined) return;
      try { rmSync(dir, { recursive: true, force: true }); } finally { dir = undefined; artifacts.length = 0; }
    },
  };
}

/** Diagnostics preserve the historic 50k cap; profile success caps use SessionOutputStore. */
export function capOutput(text: string, maxChars = 50_000): string {
  return text.length > maxChars
    ? `${safeSlice(text, 0, maxChars)}\n\n[truncated — output exceeded ${maxChars} chars]`
    : text;
}

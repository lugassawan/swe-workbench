import { chmodSync, mkdtempSync, readdirSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
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
    if (dir === undefined) dir = mkdtempSync(join(tmpdir(), "swe-workbench-subagent-output-"));
    return dir;
  }

  return {
    project(text, maxChars) {
      if (text.length <= maxChars) return { text, totalChars: text.length, truncated: false };
      const artifact = join(ensureDir(), `output-${Date.now()}-${artifacts.length}.txt`);
      writeFileSync(artifact, text, { mode: 0o600, flag: "wx" });
      chmodSync(artifact, 0o600);
      artifacts.push(artifact);
      while (artifacts.length > maxArtifacts) {
        const oldest = artifacts.shift();
        if (oldest) unlinkSync(oldest);
      }
      const headLength = Math.max(1, Math.floor(maxChars * 0.7));
      const tailLength = Math.max(1, maxChars - headLength);
      const projected = `${safeSlice(text, 0, headLength)}\n\n[truncated — showing ${maxChars}/${text.length} chars; complete private output: ${artifact}]\n\n${safeSlice(text, text.length - tailLength)}`;
      return { text: projected, totalChars: text.length, truncated: true, fullOutputPath: artifact };
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

import { execSync } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type ToolInput = Record<string, unknown>;

const LANGUAGE_SKILLS: Record<string, string> = {
  py: "language-python",
  ts: "language-typescript",
  tsx: "language-typescript",
  js: "language-typescript",
  jsx: "language-typescript",
  mjs: "language-typescript",
  cjs: "language-typescript",
  go: "language-go",
  rs: "language-rust",
  java: "language-java",
  kt: "language-kotlin",
  kts: "language-kotlin",
  rb: "language-ruby",
  swift: "language-swift",
  sh: "language-bash",
  bash: "language-bash",
  sql: "language-sql",
  cs: "language-csharp",
};

let hintedSkills = new Set<string>();

function stringField(input: ToolInput, key: string): string {
  const value = input[key];
  return typeof value === "string" ? value : "";
}

function normalizeCommand(command: string): string {
  return command.replace(/[;|&`$]/g, " ").replace(/[\"'()\[\]{}]/g, "");
}

function protectedBranchReset(command: string): boolean {
  if (!/git\s+reset\s+--hard/.test(command)) return false;
  try {
    const branch = execSync("git rev-parse --abbrev-ref HEAD", { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
    return branch === "main" || branch === "master" || branch.startsWith("release/");
  } catch {
    return false;
  }
}

function blockReasonForBash(command: string): string | null {
  const normalized = normalizeCommand(command);
  if (!/(^|\s)rm\s+|git/.test(normalized)) return null;

  if (/(^|\s)rm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF]?\s+(\/(\*|\s|$)|(~|\$HOME)(\/[^\s]*)?(\s|$)|(\/Users|\/home)(\/[^/\s]+)?(\s|\/|$))/.test(normalized)) {
    return "BLOCKED: destructive rm against root or home";
  }

  if (/git\s+push.*(--force(\s|$)|(^|\s)-f(\s|$))/.test(normalized)
    && /(^|\s|:)(main|master|release\/[^\s:]*)(\s|:|$)/.test(normalized)) {
    return "BLOCKED: force push to protected branch (main/master/release/*)";
  }

  if (protectedBranchReset(normalized)) {
    return "BLOCKED: git reset --hard on protected branch";
  }

  return null;
}

const refPattern = /os\.environ|os\.getenv|process\.env|ENV\[|\bgetenv\b/;
const noSecretPattern = /#\s*nosecret\b/;
const secretPatterns: Array<{ name: string; pattern: RegExp; needsContext: boolean }> = [
  { name: "github-pat", pattern: /ghp_[A-Za-z0-9]{36}/, needsContext: false },
  { name: "github-fine-grained-pat", pattern: /github_pat_[A-Za-z0-9_]{82}/, needsContext: false },
  { name: "aws-access-key-id", pattern: /AKIA[0-9A-Z]{16}/, needsContext: false },
  { name: "private-key-pem", pattern: /-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----/, needsContext: false },
  { name: "aws-secret-access-key", pattern: /aws_secret\w*\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40}[\"']?/i, needsContext: true },
  { name: "generic-api-key", pattern: /\bAPI_KEY\s*=\s*[\"'][^\"']{16,}[\"']/i, needsContext: true },
  { name: "generic-secret", pattern: /\b(?:SECRET|PASSWORD|PASSWD|TOKEN)\s*=\s*[\"'][^\"']{8,}[\"']/i, needsContext: true },
  { name: "dotenv-assignment", pattern: /^(?:SECRET|API_KEY|TOKEN|PASSWORD|PASSWD)=[^\s]{8,}/, needsContext: true },
];

function scanSecret(content: string): { name: string; line: number; needsContext: boolean } | null {
  const lines = content.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const suppressed = noSecretPattern.test(line);
    const isReference = refPattern.test(line);
    for (const item of secretPatterns) {
      if (suppressed || (item.needsContext && isReference)) continue;
      if (item.pattern.test(line)) return { name: item.name, line: index + 1, needsContext: item.needsContext };
    }
  }
  return null;
}

function editedContent(input: ToolInput): string {
  const direct = stringField(input, "newText") || stringField(input, "new_string");
  const edits = input.edits;
  if (!Array.isArray(edits)) return direct;
  const replacementTexts = edits
    .map((edit) => edit && typeof edit === "object" && "newText" in edit ? (edit as { newText?: unknown }).newText : "")
    .filter((value): value is string => typeof value === "string");
  return [direct, ...replacementTexts].filter(Boolean).join("\n");
}

function blockReasonForSecret(toolName: string, input: ToolInput): string | null {
  const normalizedTool = toolName.toLowerCase();
  const content = normalizedTool === "write"
    ? stringField(input, "content")
    : normalizedTool === "edit"
      ? editedContent(input)
      : "";
  if (!content) return null;

  const filePath = stringField(input, "path") || stringField(input, "file_path") || "<unknown>";
  if (filePath.endsWith("/.gitignore") || filePath === ".gitignore") return null;

  const match = scanSecret(content);
  if (!match) return null;

  const suppressionHint = match.needsContext
    ? "\nTo suppress: add `# nosecret` on that line if this is an intentional fixture/example."
    : "";
  return `BLOCKED: hardcoded secret detected (pattern: ${match.name}, line ${match.line}, file: ${filePath})\nReplace the literal with an environment-variable reference (e.g. process.env[...]).${suppressionHint}`;
}

function hintForPath(path: string): string | null {
  const basename = path.split(/[\\/]/).pop() ?? path;
  const dot = basename.lastIndexOf(".");
  if (dot <= 0 || dot === basename.length - 1) return null;
  const extension = basename.slice(dot + 1).toLowerCase();
  const skill = LANGUAGE_SKILLS[extension];
  if (!skill || hintedSkills.has(skill)) return null;
  hintedSkills.add(skill);
  return `Consider \`swe-workbench:${skill}\` for .${extension} work — load the packaged skill to apply language-specific idioms.`;
}

export default function sweWorkbenchPi(pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    const input = (event.input ?? {}) as ToolInput;
    const toolName = event.toolName.toLowerCase();

    if (toolName === "bash") {
      const reason = blockReasonForBash(stringField(input, "command"));
      if (reason) return { block: true, reason };
    }

    if (toolName === "write" || toolName === "edit") {
      const reason = blockReasonForSecret(toolName, input);
      if (reason) return { block: true, reason };
    }

    if (toolName === "read" || toolName === "edit" || toolName === "write") {
      const path = stringField(input, "path") || stringField(input, "file_path");
      const hint = path ? hintForPath(path) : null;
      if (hint) ctx.ui.notify(hint, "info");
    }
  });

  pi.on("session_start", async (_event, ctx) => {
    hintedSkills = new Set<string>();
    ctx.ui.setStatus("swe-workbench", "loaded");
  });
}

/**
 * Pure text for the Claude-Code -> Pi tool-vocabulary preamble section.
 *
 * Layer: domain. This file must import NOTHING from the Pi SDK, not even as a type — only
 * node:fs/node:path. Composing it into the system prompt (composePreamble) is index.ts's job.
 */
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

/** Exactly Pi's built-in tools that correspond to a Claude Code tool this repo's prose names.
 *  Exported for subagent.ts's tool-token translator (agent-spec.ts's translateToolTokens). */
export const RENAME_TABLE: ReadonlyArray<readonly [string, string]> = [
  ["Read", "read"],
  ["Write", "write"],
  ["Edit", "edit"],
  ["Bash", "bash"],
  ["Grep", "grep"],
  ["Glob", "find"],
  ["LS", "ls"],
];

function renameTableSection(): string {
  const rows = RENAME_TABLE.map(([cc, pi]) => `| \`${cc}\` | \`${pi}\` |`).join("\n");
  return (
    "Claude Code tool names this repo's skills/commands/agents prose uses map to these Pi " +
    "built-ins:\n\n| Claude Code | Pi |\n| --- | --- |\n" +
    rows
  );
}

/** Directory names under skills/ that contain a SKILL.md — by construction the exact set Phase
 *  1's resources_discover hands Pi via skillPaths, so this legend cannot drift from it. Returns
 *  null (never throws) on any read failure, mirroring index.ts's readCurrentScripts posture. */
function readSkillIds(root: string): string[] | null {
  try {
    return readdirSync(join(root, "skills"), { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && existsSync(join(root, "skills", entry.name, "SKILL.md")))
      .map((entry) => entry.name)
      .sort();
  } catch {
    return null;
  }
}

function skillLegendSection(root: string): string {
  const rule =
    "Where prose writes `swe-workbench:<id>`, the Pi equivalent is `/skill:<id>` — the " +
    "`swe-workbench:` prefix is a Claude Code namespace, not part of the Pi skill id.";
  const superpowersNote =
    "This repo's prose also delegates to `superpowers:<id>` skills (e.g. " +
    "`superpowers:brainstorming`, `superpowers:executing-plans`) — Pi does not bundle " +
    "Superpowers. Install it as its own Pi package first (`pi install " +
    "git:github.com/obra/superpowers`); the same drop-the-namespace-prefix rule then applies: " +
    "`superpowers:<id>` -> `/skill:<id>`.";
  const ids = readSkillIds(root);
  const withList = ids === null ? rule : `${rule} Available ids: ${ids.join(", ")}.`;
  return `${withList} ${superpowersNote}`;
}

const ASK_USER_QUESTION_SECTION =
  "`AskUserQuestion` is `ask_user_question` on Pi — same intent (present the user a small set " +
  "of options and get a single choice back), different tool name.";

const EXIT_PLAN_MODE_SECTION =
  "Pi has no plan mode, so there is no `ExitPlanMode` tool call. Where prose says \"before " +
  "`ExitPlanMode`\" or \"passed to `ExitPlanMode`\", read it as \"before you begin editing " +
  "files.\" The `## Workflow` section embedding obligation that prose attaches to that moment " +
  "is unchanged.";

const WORKTREE_SECTION =
  "Pi has no session-anchoring tool (no `EnterWorktree`/`ExitWorktree` equivalent). Where " +
  "prose offers `EnterWorktree` with a `cd <absolute-path>` fallback, on Pi the `cd` branch " +
  "is *the* mechanism, not a last resort — always use it.";

// The task-list paragraph is verbatim from superpowers:using-superpowers' Pi reference
// (references/pi-tools.md), so a Pi session never invents a capability Pi core does not ship.
const TASK_LIST_SECTION =
  "Pi core does not ship a standard task-list tool. If a todo/task extension is installed, use " +
  "its documented tool. Otherwise use Superpowers plan files, checklists in Markdown, or a " +
  "repo-local `TODO.md` for task tracking. Older Superpowers docs may refer to `TodoWrite`; " +
  "treat that as the task-tracking action above.";

// Also verbatim from that same reference: the no-subagent-tool paragraph, used only when this
// plugin's own `task` tool (pi/extensions/subagent.ts) is NOT registered.
const NO_SUBAGENT_TOOL_PARAGRAPH =
  "Pi core does not ship a standard subagent tool. The `pi-subagents` package is a strong " +
  "optional companion and provides a `subagent` tool with single-agent, chain, parallel, " +
  "async, forked-context, and resume/status workflows. If no subagent tool is available, do " +
  "not fabricate `Task` calls; execute sequentially in the current session or explain that the " +
  "optional subagent capability is not installed.";

// Used when subagent.ts's `task` tool IS registered — names the real tool instead of telling
// the model not to fabricate one.
const TASK_TOOL_PARAGRAPH =
  "This plugin registers its own `task` tool: `task(agent, prompt)` dispatches any of this " +
  'plugin\'s `agents/*.md` definitions (e.g. `task({ agent: "reviewer", prompt: "..." })`) as ' +
  "a nested Pi session, running with that agent's declared tools and preloaded skills. Use it " +
  "for subagent dispatch. The `pi-subagents` package (if also installed) provides its own, " +
  "separate `subagent` tool for generic delegation — `task` is this plugin's first-party " +
  "alternative, not a wrapper around it.";

function antiHallucinationSection(taskToolRegistered: boolean): string {
  const subagentParagraph = taskToolRegistered ? TASK_TOOL_PARAGRAPH : NO_SUBAGENT_TOOL_PARAGRAPH;
  return `${subagentParagraph}\n\n${TASK_LIST_SECTION}`;
}

/** Returns the {title, body}-shaped section composePreamble expects for the CC->Pi tool
 *  vocabulary this repo's shared prose (skills/, commands/, agents/) assumes.
 *  `taskToolRegistered` should mirror whether subagent.ts's `task` tool was actually registered
 *  this session (index.ts computes this once from the same kill switch registerSubagent reads),
 *  so the preamble never tells the model to fabricate `Task` calls while a real `task` tool is
 *  live, nor names a `task` tool that was never registered. */
export function toolVocabSection(
  root: string,
  taskToolRegistered = false,
): { title: string; body: string } {
  const body = [
    renameTableSection(),
    skillLegendSection(root),
    ASK_USER_QUESTION_SECTION,
    EXIT_PLAN_MODE_SECTION,
    WORKTREE_SECTION,
    antiHallucinationSection(taskToolRegistered),
  ].join("\n\n");
  return { title: "Claude Code -> Pi tool vocabulary", body };
}

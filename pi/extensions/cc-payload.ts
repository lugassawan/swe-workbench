/**
 * Pure translation from Pi's tool-call/session events to the CC-shaped JSON payloads
 * hooks/bash_guard.sh, hooks/secret_guard.py, hooks/workflow_resume_hint.sh,
 * hooks/skill_autoload_hint.sh, and hooks/memory_hint.sh already read from stdin.
 *
 * No I/O, no node:child_process, and no runtime import of @earendil-works/pi-coding-agent —
 * only `import type` — so this file stays exercisable under `node --experimental-strip-types`
 * without ever resolving the SDK package.
 */
import type {
  BashToolCallEvent,
  EditToolCallEvent,
  SessionCompactEvent,
  SessionStartEvent,
  WriteToolCallEvent,
} from "@earendil-works/pi-coding-agent";

export type FailPosture = "open" | "closed";

export interface GuardSpec {
  /** null for bash_guard.sh, which reads only .tool_input.command and never checks tool_name. */
  readonly ccToolName: "Write" | "Edit" | null;
  readonly interpreter: string;
  readonly scriptRelPath: string;
  readonly failPosture: FailPosture;
}

/** Pi tool name -> the CC hook it must reproduce verbatim. Data, not branching logic, so a
 *  contract test can assert every field directly. */
export const GUARD_DISPATCH: Record<"bash" | "write" | "edit", GuardSpec> = {
  bash: {
    ccToolName: null,
    interpreter: "bash",
    scriptRelPath: "hooks/bash_guard.sh",
    failPosture: "closed",
  },
  write: {
    ccToolName: "Write",
    interpreter: "python3",
    scriptRelPath: "hooks/secret_guard.py",
    failPosture: "open",
  },
  edit: {
    ccToolName: "Edit",
    interpreter: "python3",
    scriptRelPath: "hooks/secret_guard.py",
    failPosture: "open",
  },
};

export function bashPayload(event: BashToolCallEvent): Record<string, unknown> {
  return { tool_input: { command: event.input.command } };
}

export function writePayload(event: WriteToolCallEvent): Record<string, unknown> {
  return {
    tool_name: GUARD_DISPATCH.write.ccToolName,
    tool_input: { content: event.input.content, file_path: event.input.path },
  };
}

/**
 * One CC-shaped payload per edits[] element — never joined. secret_guard.py reports a 1-based
 * line number computed against whatever `new_string` it receives; joining every edits[].newText
 * into one string would report a line number against a document that was never actually
 * written, for every element but the first.
 */
export function editPayloads(event: EditToolCallEvent): Record<string, unknown>[] {
  return event.input.edits.map((edit) => ({
    tool_name: GUARD_DISPATCH.edit.ccToolName,
    tool_input: { new_string: edit.newText, file_path: event.input.path },
  }));
}

export type WorkflowResumeSource = "startup" | "resume" | "compact";

/** hooks/workflow_resume_hint.sh's SessionStart `.source` values it conditions wording on. */
const SESSION_START_SOURCE: Record<SessionStartEvent["reason"], WorkflowResumeSource> = {
  startup: "startup",
  new: "startup",
  resume: "resume",
  reload: "resume",
  fork: "resume",
};

export function sessionStartSource(event: SessionStartEvent): WorkflowResumeSource {
  return SESSION_START_SOURCE[event.reason];
}

/** session_compact only ever fires because a compaction happened — Pi's own sub-reason
 *  ("manual"|"threshold"|"overflow") isn't one the hook reads, so `.source` is always "compact". */
export function sessionCompactSource(_event: SessionCompactEvent): WorkflowResumeSource {
  return "compact";
}

export function resumeHintPayload(cwd: string, source: WorkflowResumeSource): Record<string, unknown> {
  return { cwd, source };
}

export function skillHintPayload(filePath: string, sessionId: string): Record<string, unknown> {
  return { tool_input: { file_path: filePath }, session_id: sessionId };
}

/** hooks/memory_hint.sh reads `.cwd` and `.harness` from its session payload. */
export function memoryHintPayload(
  cwd: string,
  harness: "claude" | "pi",
): Record<string, unknown> {
  return { cwd, harness };
}

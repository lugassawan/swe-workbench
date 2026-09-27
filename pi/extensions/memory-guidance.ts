/**
 * Pure text for the "when to record memory" system-prompt section — appended only when the
 * memory_record tool is active. Must import nothing from the Pi SDK.
 */

/** Must equal bin/swe-workbench-memory's ENTRY_TYPES exactly (parity-pinned in tests). */
export const ENTRY_TYPES = ["user", "feedback", "project", "reference"] as const;

export const MEMORY_TOOL_NAME = "memory_record";

const WHEN_TO_SAVE =
  "Call it when something learned this session would help a FUTURE session on this same " +
  "repo, and is not already recoverable by reading the code or git history: a user " +
  "correction to how you approached something, or an unusual approach the user confirmed " +
  "worked (not just corrections — a validated judgment call is worth keeping too); a " +
  "non-obvious project fact, decision, or constraint (convert relative dates like " +
  "\"Thursday\" to absolute ones, since the memory outlives the conversation); a pointer to " +
  "where something lives in an external system (an issue tracker, a dashboard, a channel); " +
  "or a standing preference about how the user wants to collaborate.";

const WHEN_NOT_TO_SAVE =
  "Do not call it for anything derivable from the current state of the code, git log/blame, " +
  "or an existing CLAUDE.md/AGENTS.md file — those are authoritative and memory would only " +
  "duplicate them, going stale the moment the code changes. Do not call it for ephemeral " +
  "task state (an in-progress plan, a todo list, \"what we're doing right now\") — that " +
  "belongs to the conversation, not to future sessions. Never pass a secret, token, or " +
  "credential as any field — the runtime's own secret scan refuses the write, but the right " +
  "move is to never attempt it.";

const TYPES_LINE =
  `Pick \`type\` from: ${ENTRY_TYPES.join(", ")} — feedback/project cover most cases; user is ` +
  "for the user's own role/preferences, reference is for a pointer into an external system.";

const RERECORD_LINE =
  "Recording under a \`name\` that already exists updates that entry in place (the newest " +
  "body wins) — there is no separate delete; re-record with the corrected content instead " +
  "of trying to remove a stale entry.";

const STRUCTURE_LINE =
  "Write the body so a future session can judge edge cases, not just follow a rule: state " +
  "the fact or rule itself, then a **Why:** line (the reason it matters — often a past " +
  "incident or an explicit user preference) and a **How to apply:** line (when this should " +
  "actually change what you do).";

/** Returns the {title, body}-shaped section composePreamble expects. */
export function memoryGuidanceSection(): { title: string; body: string } {
  const body = [WHEN_TO_SAVE, WHEN_NOT_TO_SAVE, TYPES_LINE, RERECORD_LINE, STRUCTURE_LINE].join(
    "\n\n",
  );
  return { title: `When to call \`${MEMORY_TOOL_NAME}\``, body };
}

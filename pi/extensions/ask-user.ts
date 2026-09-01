/**
 * Registers `ask_user_question`, Pi's counterpart to Claude Code's `AskUserQuestion`. Mirrors
 * guards.ts's `registerGuards(pi, root)` shape so index.ts stays a flat composition root.
 *
 * The schema below is written as a plain JSON-Schema object literal, not built with TypeBox —
 * `wrapToolDefinition` (dist/core/tools/tool-definition-wrapper.js) copies `definition.parameters`
 * through to the runtime verbatim, and nothing on the tool-registration path runs TypeBox's
 * `Value.Check`/`Compile` against it. Importing the typebox package as a value would also break
 * the pytest driver, which runs this file under `node --experimental-strip-types` with no
 * bundler and no node_modules alias resolution for that package's nested install location.
 * `ToolDefinition["parameters"]` (a type-only reference into the SDK's own re-export) gives the
 * exact same `TSchema` type — an empty interface every object literal already satisfies —
 * without that import.
 */
import type { ExtensionAPI, ToolDefinition } from "@earendil-works/pi-coding-agent";

interface AskUserOption {
  label: string;
  description?: string;
}

interface AskUserQuestionItem {
  question: string;
  header: string;
  multiSelect: boolean;
  options: AskUserOption[];
}

interface AskUserQuestionParams {
  questions: AskUserQuestionItem[];
}

const QUESTIONS_SCHEMA = {
  type: "object",
  properties: {
    questions: {
      type: "array",
      minItems: 1,
      maxItems: 4,
      items: {
        type: "object",
        properties: {
          question: { type: "string", description: "The complete question to ask the user." },
          header: { type: "string", description: "Short label (<=12 chars) shown as a chip." },
          multiSelect: {
            type: "boolean",
            description: "Must be false — ask_user_question does not support multi-select.",
          },
          options: {
            type: "array",
            minItems: 2,
            maxItems: 4,
            items: {
              type: "object",
              properties: {
                label: { type: "string" },
                description: { type: "string" },
              },
              required: ["label"],
              additionalProperties: false,
            },
          },
        },
        required: ["question", "header", "options", "multiSelect"],
        additionalProperties: false,
      },
    },
  },
  required: ["questions"],
  additionalProperties: false,
} as ToolDefinition["parameters"];

function optionLabel(option: AskUserOption): string {
  return option.description ? `${option.label} — ${option.description}` : option.label;
}

/** Rendered as the last row of every question — choosing it opens a free-text input dialog. */
const OTHER_CHOICE = "Other — type your own answer";

export function registerAskUser(pi: ExtensionAPI): void {
  // Read once per process at registration time — an immutable config read, not a module-state
  // anti-pattern (nothing here mutates after this check). Gates Tier-2 tool registration only;
  // Tier-1 vocabulary prose (tool-vocab.ts) stays on unconditionally.
  if (process.env.SWE_WORKBENCH_PI_TOOLS === "0") return;

  pi.registerTool({
    name: "ask_user_question",
    label: "Ask User Question",
    description:
      "Ask the user one or more fixed-option questions and return their picks. Use only when " +
      "a decision genuinely belongs to the user — never as a substitute for a reasonable default.",
    promptSnippet:
      "ask_user_question(questions): present the user 1-4 fixed-option questions (2-4 options " +
      "each, plus an automatic free-text \"Other\" row) and get their picks back. Use when " +
      "blocked on a decision only the user can make.",
    promptGuidelines: [
      "Never author an \"Other\" option — a free-text \"Other\" row is appended automatically; " +
        "when the user picks it they type an answer that is returned for that question.",
      "Each question is single-select. To collect more than one choice per question, ask " +
        "separate sequential single-select questions instead of setting multiSelect.",
    ],
    parameters: QUESTIONS_SCHEMA,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!ctx.hasUI) {
        throw new Error(
          "ask_user_question requires an interactive UI, but none is available in this mode " +
            "(print/json). Re-run interactively, or supply the decision directly in the prompt " +
            "instead of asking.",
        );
      }

      const { questions } = params as unknown as AskUserQuestionParams;
      const multiSelectQuestion = questions.find((q) => q.multiSelect);
      if (multiSelectQuestion) {
        throw new Error(
          `ask_user_question: multiSelect is not supported — re-ask "${multiSelectQuestion.question}" ` +
            "as sequential single-select questions instead.",
        );
      }

      // answers[] is keyed by question text (see below) — a duplicate would silently overwrite
      // an earlier answer with no error surfaced, one of the user's picks vanishing unnoticed.
      const seen = new Set<string>();
      const duplicate = questions.find((q) => {
        if (seen.has(q.question)) return true;
        seen.add(q.question);
        return false;
      });
      if (duplicate) {
        throw new Error(
          `ask_user_question: duplicate question text "${duplicate.question}" — each question ` +
            "in one call must be distinct text, since answers are returned keyed by question.",
        );
      }

      const answers: Record<string, string> = {};
      for (const q of questions) {
        const choice = await ctx.ui.select(
          q.question,
          [...q.options.map(optionLabel), OTHER_CHOICE],
          { signal },
        );
        if (choice === undefined) {
          throw new Error(
            `ask_user_question: the user dismissed "${q.question}" without choosing an option — ` +
              "stop and check in with the user rather than assuming an answer.",
          );
        }
        if (choice === OTHER_CHOICE) {
          const typed = await ctx.ui.input(q.question, "Type your answer", { signal });
          if (typed === undefined) {
            throw new Error(
              `ask_user_question: the user dismissed the free-text answer to "${q.question}" ` +
                "without entering one — stop and check in with the user rather than assuming an answer.",
            );
          }
          answers[q.question] = typed;
          continue;
        }
        answers[q.question] = choice;
      }

      return {
        content: [{ type: "text" as const, text: JSON.stringify(answers) }],
        details: answers,
      };
    },
  });
}

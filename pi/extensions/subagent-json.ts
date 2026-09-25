interface NestedTaskUsage {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  cacheWrite1h?: number;
  reasoning?: number;
  totalTokens: number;
  cost: {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
    total: number;
  };
}

interface AssistantMessageRecord {
  content: Array<{ type: string; text?: string }>;
  usage: NestedTaskUsage;
  stopReason: string;
  errorMessage?: string;
}

interface ParsedNestedTask {
  text: string;
  usage: NestedTaskUsage;
}

type JsonRecord = Record<string, unknown>;

function protocolError(line: number, field: string, expectation: string): Error {
  return new Error(
    `nested task JSON protocol error at line ${line}: ${field} ${expectation}`,
  );
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, line: number, field: string): JsonRecord {
  if (!isRecord(value)) throw protocolError(line, field, "must be an object");
  return value;
}

function requireString(value: unknown, line: number, field: string): string {
  if (typeof value !== "string") throw protocolError(line, field, "must be a string");
  return value;
}

function requireNumber(record: JsonRecord, key: string, line: number, prefix: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw protocolError(line, `${prefix}.${key}`, "must be a finite non-negative number");
  }
  return value;
}

function optionalNumber(record: JsonRecord, key: string, line: number): number | undefined {
  return record[key] === undefined ? undefined : requireNumber(record, key, line, "usage");
}

function parseUsage(value: unknown, line: number): NestedTaskUsage {
  const usage = requireRecord(value, line, "usage");
  const cost = requireRecord(usage.cost, line, "usage.cost");
  const cacheWrite1h = optionalNumber(usage, "cacheWrite1h", line);
  const reasoning = optionalNumber(usage, "reasoning", line);
  return {
    input: requireNumber(usage, "input", line, "usage"),
    output: requireNumber(usage, "output", line, "usage"),
    cacheRead: requireNumber(usage, "cacheRead", line, "usage"),
    cacheWrite: requireNumber(usage, "cacheWrite", line, "usage"),
    ...(cacheWrite1h === undefined ? {} : { cacheWrite1h }),
    ...(reasoning === undefined ? {} : { reasoning }),
    totalTokens: requireNumber(usage, "totalTokens", line, "usage"),
    cost: {
      input: requireNumber(cost, "input", line, "usage.cost"),
      output: requireNumber(cost, "output", line, "usage.cost"),
      cacheRead: requireNumber(cost, "cacheRead", line, "usage.cost"),
      cacheWrite: requireNumber(cost, "cacheWrite", line, "usage.cost"),
      total: requireNumber(cost, "total", line, "usage.cost"),
    },
  };
}

function parseContent(value: unknown, line: number): AssistantMessageRecord["content"] {
  if (!Array.isArray(value)) throw protocolError(line, "message.content", "must be an array");
  return value.map((rawBlock, index) => {
    const field = `message.content[${index}]`;
    const block = requireRecord(rawBlock, line, field);
    const type = requireString(block.type, line, `${field}.type`);
    if (type !== "text") return { type };
    return { type, text: requireString(block.text, line, `${field}.text`) };
  });
}

function parseAssistantMessage(message: JsonRecord, line: number): AssistantMessageRecord {
  const errorMessage = message.errorMessage;
  if (errorMessage !== undefined && typeof errorMessage !== "string") {
    throw protocolError(line, "message.errorMessage", "must be a string when present");
  }
  return {
    content: parseContent(message.content, line),
    usage: parseUsage(message.usage, line),
    stopReason: requireString(message.stopReason, line, "message.stopReason"),
    ...(errorMessage === undefined ? {} : { errorMessage }),
  };
}

function addUsage(left: NestedTaskUsage, right: NestedTaskUsage): NestedTaskUsage {
  return {
    input: left.input + right.input,
    output: left.output + right.output,
    cacheRead: left.cacheRead + right.cacheRead,
    cacheWrite: left.cacheWrite + right.cacheWrite,
    ...(left.cacheWrite1h === undefined && right.cacheWrite1h === undefined
      ? {}
      : { cacheWrite1h: (left.cacheWrite1h ?? 0) + (right.cacheWrite1h ?? 0) }),
    ...(left.reasoning === undefined && right.reasoning === undefined
      ? {}
      : { reasoning: (left.reasoning ?? 0) + (right.reasoning ?? 0) }),
    totalTokens: left.totalTokens + right.totalTokens,
    cost: {
      input: left.cost.input + right.cost.input,
      output: left.cost.output + right.cost.output,
      cacheRead: left.cost.cacheRead + right.cost.cacheRead,
      cacheWrite: left.cost.cacheWrite + right.cost.cacheWrite,
      total: left.cost.total + right.cost.total,
    },
  };
}

function assertFiniteAggregate(usage: NestedTaskUsage): void {
  const values: Array<[string, number | undefined]> = [
    ["usage.input", usage.input], ["usage.output", usage.output],
    ["usage.cacheRead", usage.cacheRead], ["usage.cacheWrite", usage.cacheWrite],
    ["usage.cacheWrite1h", usage.cacheWrite1h], ["usage.reasoning", usage.reasoning],
    ["usage.totalTokens", usage.totalTokens], ["usage.cost.input", usage.cost.input],
    ["usage.cost.output", usage.cost.output], ["usage.cost.cacheRead", usage.cost.cacheRead],
    ["usage.cost.cacheWrite", usage.cost.cacheWrite], ["usage.cost.total", usage.cost.total],
  ];
  const invalid = values.find(([, value]) => value !== undefined && !Number.isFinite(value));
  if (invalid) throw new Error(`nested task JSON protocol error: aggregate ${invalid[0]} is not finite`);
}

function parseJsonLine(line: string, lineNumber: number): JsonRecord {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    throw protocolError(lineNumber, "record", "contains malformed JSON");
  }
  const event = requireRecord(value, lineNumber, "record");
  requireString(event.type, lineNumber, "record.type");
  return event;
}

export function parseNestedTaskJson(stdout: string): ParsedNestedTask {
  const assistantMessages: AssistantMessageRecord[] = [];
  for (const [index, line] of stdout.split("\n").entries()) {
    if (!line.trim()) continue;
    const lineNumber = index + 1;
    const event = parseJsonLine(line, lineNumber);
    if (event.type !== "message_end") continue;
    const message = requireRecord(event.message, lineNumber, "message");
    const role = requireString(message.role, lineNumber, "message.role");
    if (role === "assistant") assistantMessages.push(parseAssistantMessage(message, lineNumber));
  }

  const finalMessage = assistantMessages.at(-1);
  if (!finalMessage) {
    throw new Error("nested task JSON protocol error: missing final assistant message_end record");
  }
  if (finalMessage.stopReason === "error" || finalMessage.stopReason === "aborted") {
    const errorMessage = finalMessage.errorMessage ?? `request ${finalMessage.stopReason}`;
    throw new Error(`nested task ${finalMessage.stopReason}: ${errorMessage}`);
  }

  const textBlocks = finalMessage.content.filter(
    (block): block is { type: "text"; text: string } => block.type === "text" && block.text !== undefined,
  );
  if (textBlocks.length === 0) {
    throw new Error("nested task JSON protocol error: missing final assistant text output");
  }
  const usage = assistantMessages.map((message) => message.usage).reduce(addUsage);
  assertFiniteAggregate(usage);
  return { text: textBlocks.map((block) => block.text).join("\n"), usage };
}

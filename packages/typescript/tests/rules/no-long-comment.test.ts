import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { noLongCommentDocumentation } from "../../src/rules/no-long-comment.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const UNPUNCTUATED_COMMENT_WALL = `/** ${Array.from({ length: 120 }, () => "context").join(" ")} */\nconst value = 1;`;

new RuleTester().run("no-long-comment", rule, {
  valid: [
    "// The cache is process local.\nconst cache = new Map();",
    "// First fact. Second fact.\nconst value = 1;",
    "/** One. Two. Three. Four. Five. Six. Seven. */\nconst value = 1;",
    "// First fact. Second fact. Third fact.\nconst value = 1;",
    "/** First fact. Second fact. Third fact. */\nexport const value = 1;",
    "// First fact.\n// Second fact.\n// Third fact.\nconst value = 1;",
    [
      "// The runtime parent is held per lease id.",
      "// A provider can open a persistent session on the first command.",
      "// Release happens outside the original run scope.",
      "// Without a parent the host emits no trace context.",
      "// Execute records the parent for that reason.",
      "// Release replays it around the provider call.",
      "// The host still validates the trace header itself.",
      "// The stored value only widens which calls carry the parent.",
      "// Release removes the entry.",
      "// The map therefore remains bounded by live leases.",
      "const parents = new Map<string, Context>();",
    ].join("\n"),
    "// Supports e.g. version 2.1 at https://example.com/a. One constraint.\nconst value = 1;",
    { code: "// One. Two. Three.\nconst value = 1;", filename: "widget.stories.tsx" },
    { code: "// One. Two. Three.\nconst value = 1;", filename: "src/generated/client.ts" },
    { code: "// One. Two. Three. Four.\nconst value = 1;", filename: "scripts/push.ts" },
    { code: "// One. Two. Three. Four.\nconst value = 1;", filename: "eslint.strict.mjs" },
    { code: "/** One. Two. Three. Four. */\nit('works', () => {});", filename: "src/widget.test.ts" },
    "// eslint-disable-next-line: One. Two. Three.\nconst value = 1;",
    "/** @example One. Two. Three. */\nexport const value = 1;",
    "/** @param value One. Two. Three. */\nexport function parse(value: string): string { return value; }",
    [
      "/**",
      " * A callback description. One. Two. Three. Four. Five. Six. Seven. Eight.",
      " * @callback CompletionCallback",
      " */",
      "const completion = value => value;",
    ].join("\n"),
    [
      "/**",
      " * A record description. One. Two. Three. Four. Five. Six. Seven. Eight.",
      " * @typedef {object} ServiceRecord",
      " */",
      "const record = {};",
    ].join("\n"),
    "/** One. Two. Three. Four. Five. Six. Seven. Eight. @customApiTag public */\nconst tagged = {};",
    "/** Public shape. Callers consume it. The wire format stays stable. */\nexport interface Result { ok: boolean; }",
    "/** First mode. Second mode. Third mode. */\nclass Service { run(): void {} }",
    "// Reject invalid input before commit. This prevents a partial write. The protocol requires atomic behavior.\nvalidate(input);",
    "// Legacy clients send this shape. The wire contract requires snake case. Keep compatibility until v3.\nreturn entry;",
    "// The cache is process local. Parallel clients need separate keys. This avoids a cross-request race.\nconst key = path;",
    "// First fact.\n// - One supported mode.\n// - Another supported mode.\nconst modes = [];",
    "/* One. Two. Three. Four. Five. Six. Seven. Eight. */\nrun();",
    noLongCommentDocumentation.examples[0].files[0].source,
    "/** One. Two. Three. Four. Five. Six. Seven. The `traceparent` value is forwarded. */\nconst value = 1;",
    "/** One. Two. Three. Four. Five. Six. Seven. The deadline is 10 ms. */\nconst value = 1;",
    [
      "/** One. Two. Three. Four. Five. Six. Seven. Eight. */",
      "export function decode(value: string): string { return value; }",
    ].join("\n"),
    {
      code: "// First behavior. Second behavior. Third behavior.\nwidget();",
      filename: "src/gui/src/lib/jquery-ui-1.13.2/jquery-ui.js",
    },
  ],
  invalid: [
    { name: "reports the synthetic eight-sentence boundary", code: "/** One. Two. Three. Four. Five. Six. Seven. Eight. */\nconst chart = createChart();", errors: [{ messageId: "tooLong" }] },
    {
      name: "unstructured JSDoc cannot evade the budget by omitting punctuation",
      code: UNPUNCTUATED_COMMENT_WALL,
      errors: [{ messageId: "tooLong" }],
    },
    {
      code: noLongCommentDocumentation.examples[1].files[0].source,
      errors: [{ messageId: "tooLong" }],
    },
    {
      name: "detached one-paragraph JSDoc wall",
      code: `/** One. Two. Three. Four. Five. Six. Seven. Eight. */

const value = 1;`,
      errors: [{ messageId: "tooLong" }],
    },
    {
      name: "an arbitrary count is not a technical anchor",
      code: "/** One. Two. Three. Four. Five. Six. Seven. It covers 3 record types. */\nconst value = 1;",
      errors: [{ messageId: "tooLong" }],
    },
  ],
});

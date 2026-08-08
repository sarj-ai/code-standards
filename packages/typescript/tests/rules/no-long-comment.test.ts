import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-long-comment.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

new RuleTester().run("no-long-comment", rule, {
  valid: [
    "// First fact. Second fact.\nconst value = 1;",
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
    "/** Public shape. Callers consume it. The wire format stays stable. */\nexport interface Result { ok: boolean; }",
    "/** First mode. Second mode. Third mode. */\nclass Service { run(): void {} }",
    "// Reject invalid input before commit. This prevents a partial write. The protocol requires atomic behavior.\nvalidate(input);",
    "// Legacy clients send this shape. The wire contract requires snake case. Keep compatibility until v3.\nreturn entry;",
    "// The cache is process local. Parallel clients need separate keys. This avoids a cross-request race.\nconst key = path;",
    "// First fact.\n// - One supported mode.\n// - Another supported mode.\nconst modes = [];",
    {
      code: "// First behavior. Second behavior. Third behavior.\nwidget();",
      filename: "src/gui/src/lib/jquery-ui-1.13.2/jquery-ui.js",
    },
  ],
  invalid: [
    {
      code: `/**
 * The ports chart shows arrivals and departures across the network.
 * It was originally a line chart, but the lines crossed too often.
 * Bars make adjacent ports easier to compare at a glance.
 * The axis starts at zero so visual differences stay proportional.
 * A single series uses the site navy for brand consistency.
 * Empty ports use a neutral ink so missing traffic remains visible.
 * Tooltip values repeat the units shown on the vertical axis.
 * The chart intentionally keeps labels horizontal on wide screens.
 */
export function PortBars() { return null; }`,
      errors: [{ messageId: "tooLong" }],
    },
  ],
});

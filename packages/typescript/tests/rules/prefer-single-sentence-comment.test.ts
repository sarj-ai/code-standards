import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-single-sentence-comment.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

new RuleTester().run("prefer-single-sentence-comment", rule, {
  valid: [
    "// One useful constraint.\nconst value = 1;",
    "// First. Second. Third.\nconst value = 1;",
    "// One sentence that wraps\n// onto another physical line.\nconst value = 1;",
    "// Supports e.g. compact mode.\nconst value = 1;",
    "// Supports version 2.1.\nconst value = 1;",
    "// See https://example.com/guide. Continue there\nconst value = 1;",
    "// Run `first. Second.` once.\nconst value = 1;",
    { code: "// Generated. With two sentences.\nconst value = 1;", filename: "client.generated.ts" },
    { code: "// First fact. Second fact.\nconst value = 1;", filename: "/repo/vendor/client.ts" },
    {
      name: "ignores Storybook stories",
      code: "// First fact. Second fact.\nexport const Primary = {};",
      filename: "/repo/Button.stories.tsx",
    },
    "// Copyright 2026 Example. Licensed under MIT.\nconst value = 1;",
    "// prettier-ignore First fact. Second fact.\nconst value = 1;",
    { name: "ignores @example", code: "/** @example First. Second. */\nexport const value = 1;" },
    { name: "ignores @remarks", code: "/** @remarks First. Second. */\nexport const value = 1;" },
    { name: "ignores @deprecated", code: "/** @deprecated First. Second. */\nexport const value = 1;" },
    { name: "ignores @see", code: "/** @see First. Second. */\nexport const value = 1;" },
    { name: "ignores @throws", code: "/** @throws First. Second. */\nexport const value = 1;" },
    { name: "ignores @internal", code: "/** @internal First. Second. */\nexport const value = 1;" },
    { name: "ignores @public", code: "/** @public First. Second. */\nexport const value = 1;" },
    { name: "ignores @alpha", code: "/** @alpha First. Second. */\nexport const value = 1;" },
    { name: "ignores @beta", code: "/** @beta First. Second. */\nexport const value = 1;" },
    { name: "ignores @since", code: "/** @since First. Second. */\nexport const value = 1;" },
    { name: "ignores @template", code: "/** @template First. Second. */\nexport const value = 1;" },
    { name: "ignores @fileoverview", code: "/** @fileoverview First. Second. */\nexport const value = 1;" },
    {
      name: "leaves @param to SARJ092",
      code: "/** @param value First. Second. */\nexport function get(value: number): number { return value; }",
    },
    {
      name: "leaves @arg to SARJ092",
      code: "/** @arg value First. Second. */\nexport function get(value: number): number { return value; }",
    },
    {
      name: "leaves @argument to SARJ092",
      code: "/** @argument value First. Second. */\nexport function get(value: number): number { return value; }",
    },
    {
      name: "leaves @returns to SARJ092",
      code: "/** @returns First. Second. */\nexport function get(value: number): number { return value; }",
    },
    {
      name: "leaves @return to SARJ092",
      code: "/** @return First. Second. */\nexport function get(value: number): number { return value; }",
    },
    {
      name: "leaves @yields to SARJ092",
      code: "/** @yields First. Second. */\nexport function get(value: number): number { return value; }",
    },
    {
      name: "leaves @yield to SARJ092",
      code: "/** @yield First. Second. */\nexport function get(value: number): number { return value; }",
    },
  ],
  invalid: [
    {
      code: "// First fact. Second fact.\nconst value = 1;",
      errors: [{ messageId: "preferOneSentence" }],
    },
    {
      code: "// First fact.\n// Second fact.\nconst value = 1;",
      errors: [{ messageId: "preferOneSentence" }],
    },
    {
      code: "/**\n * Constraints:\n * - first item\n * - second item\n */\nexport const value = 1;",
      errors: [{ messageId: "preferOneSentence" }],
    },
  ],
});

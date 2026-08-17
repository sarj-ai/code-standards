import eslintComments from "@eslint-community/eslint-plugin-eslint-comments";
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import tseslint from "typescript-eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/no-vague-suppression-description.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser },
  linterOptions: { reportUnusedDisableDirectives: false },
});

ruleTester.run("no-vague-suppression-description", rule, {
  valid: [
    "// eslint-disable-next-line no-console -- CLI output is the public interface\nconsole.log(value);",
    "// @ts-expect-error -- vendor declaration omits the runtime overload added in v4\nlegacy.call(value);",
    "// @ts-expect-error: generated SDK types model this nullable response as required\nread(value);",
    "// false positive in prose, not a directive\nconst value = 1;",
    "// Unlike @ts-expect-error -- needed, this prose does not suppress anything\nconst value = 1;",
    "/* Unlike @ts-expect-error -- needed, this block is prose. */\nconst value = 1;",
    "/* @ts-ignore -- intentional */\nlegacy.call(value);",
    "// @ts-expect-error\nlegacy.call(value);",
    "// eslint-disable-next-line no-console\nconsole.log(value);",
    "/* @ts-expect-error -- vendor declaration omits the runtime overload */\nlegacy.call(value);",
    "const value = 1; // eslint-disable-line @rule-tester/no-vague-suppression-description -- needed",
    {
      filename: "/repo/src/generated/client.ts",
      code: "// @ts-expect-error -- needed\ncall();",
    },
  ],
  invalid: [
    {
      code: "// eslint-disable-next-line no-console -- needed\nconsole.log(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// eslint-disable-next-line no-console -- false positive\nconsole.log(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// @ts-expect-error: to satisfy linter\nlegacy.call(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "/* @ts-expect-error -- intentional */\nlegacy.call(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// eslint-disable-next-line @rule-tester/no-vague-suppression-description -- needed\nconst value = 1;",
      errors: [{ messageId: "vagueDescription" }],
    },
  ],
});

describe("upstream ownership integration", () => {
  const linter = new Linter({ configType: "flat" });
  const config = [
    {
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      linterOptions: { reportUnusedDisableDirectives: "off" },
      plugins: {
        "@typescript-eslint": tseslint.plugin,
        comments: eslintComments,
        sarj: { rules: { "no-vague-suppression-description": rule } },
      },
      rules: {
        "@typescript-eslint/ban-ts-comment": [
          "error",
          {
            minimumDescriptionLength: 3,
            "ts-check": false,
            "ts-expect-error": "allow-with-description",
            "ts-ignore": true,
            "ts-nocheck": true,
          },
        ],
        "comments/require-description": ["error", { ignore: [] }],
        "no-console": "error",
        "sarj/no-vague-suppression-description": "warn",
      },
    },
  ] as unknown as Linter.Config[];

  it.each([
    {
      code: "// eslint-disable-next-line no-console\nconsole.log(value);",
      expected: ["comments/require-description"],
      name: "missing description is upstream-only",
    },
    {
      code: "// eslint-disable-next-line no-console -- needed\nconsole.log(value);",
      expected: ["sarj/no-vague-suppression-description"],
      name: "vague present description is custom-only",
    },
    {
      code: "// eslint-disable-next-line no-console -- CLI output is the public interface\nconsole.log(value);",
      expected: [],
      name: "concrete description is accepted by both owners",
    },
    {
      code: "// @ts-ignore -- intentional\nconst value: string = 1;",
      expected: ["@typescript-eslint/ban-ts-comment"],
      name: "ts-ignore is upstream-only",
    },
    {
      code: "// Unlike @ts-ignore -- needed, this prose suppresses nothing.\nconst value = 1;",
      expected: [],
      name: "directive mention in prose belongs to neither",
    },
  ])("$name", ({ code, expected }) => {
    const messages = linter.verify(code, config, "src/ownership.ts");
    expect(messages.map((message) => message.ruleId).filter((ruleId) => ruleId !== null)).toEqual(expected);
  });
});

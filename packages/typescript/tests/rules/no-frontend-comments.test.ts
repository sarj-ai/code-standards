import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/no-frontend-comments.js";
import noTestComments from "../../src/rules/no-test-comments.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({ languageOptions: { parser } });

TESTER.run("no-frontend-comments", rule, {
  valid: [
    { filename: "src/view.tsx", code: "export const View = () => <p>Ready</p>;" },
    { filename: "src/view.tsx", code: "const text = '// literal text'; const template = '/* literal */';" },
    { filename: "src/view.tsx", code: "const View = () => <p>// rendered text</p>;" },
    { filename: "src/generated/view.tsx", code: "// Generated upstream\nexport const View = () => null;" },
    { filename: "src/worker.ts", code: "// Server library context\nexport const ready = true;" },
    { filename: "src/view.test.tsx", code: "// Owned by the test-comment rule\nconst ready = true;" },
  ],
  invalid: [
    { filename: "src/view.tsx", code: "// Render the view\nexport const View = () => <p />;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "export const View = () => <p>{/* View status */}Ready</p>;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "/** Public view documentation */\nexport const View = () => null;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/use-view.ts", code: "import { useState } from 'react';\n// Browser helper\nexport const useView = () => useState(true);", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/actions.ts", code: "'use server';\n// Save the changes\nexport async function save() {}", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/client.ts", code: "'use client';\n// Client module\nexport const ready = true;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/helper.ts", code: "// Frontend helper\nexport const ready = true;", options: [{ allFiles: true }], output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "// @ts-expect-error -- invalid fixture\nconst ready: number = 'bad';", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "/* Copyright 2026 Example */\nexport const ready = true;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "/*#__PURE__*/ makeView();", output: null, errors: [{ messageId: "noFrontendComments" }] },
  ],
});

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

it("delegates frontend test comments once and preserves behavioral annotations during fixing", () => {
  const code = "// @ts-expect-error -- invalid fixture\nconst ready: number = 'bad';";
  const linter = new Linter();
  const configuration = [{
    files: ["**/*.tsx"],
    languageOptions: { parser },
    plugins: { sarj: { rules: { "no-frontend-comments": rule, "no-test-comments": noTestComments } } },
    rules: { "sarj/no-frontend-comments": "warn", "sarj/no-test-comments": "warn" },
  }] as const;
  const result = linter.verifyAndFix(code, configuration, { filename: "src/view.test.tsx" });
  expect(result.output).toBe(code);
  expect(result.messages.map(message => message.ruleId)).toEqual(["sarj/no-test-comments"]);
});

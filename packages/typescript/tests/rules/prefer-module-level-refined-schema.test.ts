import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";
import rule from "../../src/rules/prefer-module-level-refined-schema.js";

RuleTester.afterAll = afterAll; RuleTester.describe = describe; RuleTester.it = it; RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { ecmaVersion: "latest", sourceType: "module" } } });
const ZOD_IMPORT = `import { z } from "zod";`;
RULE_TESTER.run("prefer-module-level-refined-schema", rule, {
  valid: [
    `${ZOD_IMPORT} const Batch = z.number().int().min(1).max(1000); export function parse(v: unknown) { return Batch.parse(v); }`,
    `${ZOD_IMPORT} export function parse(v: unknown, maximum: number) { return z.number().int().min(1).max(maximum).parse(v); }`,
    `${ZOD_IMPORT} export function parse(v: unknown) { return z.number().min(1).parse(v); }`,
    { filename: "src/options.test.ts", code: `${ZOD_IMPORT} function parse(v: unknown) { return z.number().int().min(1).parse(v); }` },
  ],
  invalid: [{ code: `${ZOD_IMPORT} export function parse(v: unknown) { return z.number().int().min(1).max(1000).parse(v); }`, errors: [{ messageId: "hoistRefinedSchema" }] },
    { code: `${ZOD_IMPORT} const MAX = 1000; export function parse(v: unknown) { return z.number().int().min(1).max(MAX).parse(v); }`, errors: [{ messageId: "hoistRefinedSchema" }] },
    { code: `${ZOD_IMPORT} export function parse(v: unknown) { return z.array(z.string()).min(1).max(3).parse(v); }`, errors: [{ messageId: "hoistRefinedSchema" }] }],
});

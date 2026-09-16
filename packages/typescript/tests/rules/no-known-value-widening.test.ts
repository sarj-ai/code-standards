import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-known-value-widening.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: { parser: tsParser, parserOptions: {
    projectService: { allowDefaultProject: ["*.ts*"] },
    tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
  } },
});

RULE_TESTER.run("no-known-value-widening", rule, {
  valid: [
    "declare const raw: unknown; const payload: unknown = raw;",
    "declare const raw: any; const payload: unknown = raw;",
    "const fields: Record<string, unknown> = {};",
    "const labels: Record<string, string> = { inbound: 'Inbound' };",
    "declare const tool: { name: string }; const fields = tool;",
    "declare const tool: { name: string }; const fields: { name: string } = tool;",
    "declare const tool: { name: string }; const fields: Record<'name', string> = tool;",
    "declare const tool: { name: string }; export const fields: unknown = tool;",
    "function keep<T>(input: T) { const output: unknown = input; return output; }",
    "declare const tool: { name: string }; const fields = tool satisfies object;",
    { code: "// @generated\ndeclare const tool: { name: string }; const fields: unknown = tool;" },
  ],
  invalid: [
    { code: "declare const tool: { name: string }; const fields: unknown = tool;", errors: [{ messageId: "widening" }] },
    { code: "declare const tool: { name: string }; const fields: object = tool;", errors: [{ messageId: "widening" }] },
    { code: "declare const tool: { name: string }; const fields: Record<string, unknown> = tool;", errors: [{ messageId: "widening" }] },
    { code: "type Bag = Readonly<Record<string, unknown>>; declare const tool: { name: string }; const fields: Bag = tool;", errors: [{ messageId: "widening" }] },
    { code: "declare const tool: { name: string }; function outer() { const fields: unknown = tool; return fields; }", errors: [{ messageId: "widening" }] },
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

SYNTAX_TESTER.run("no-known-value-widening without a type project", rule, {
  valid: ["declare const tool: { name: string }; const fields: unknown = tool;"],
  invalid: [],
});

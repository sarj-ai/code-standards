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
    "function keep<T>(input: T | undefined) { const output: unknown = input; return output; }",
    "function keep<T>(input: T | null) { const output: unknown = input; return output; }",
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
    { name: "preserves the sole named variable annotation binding", code: "export {}; type Opaque = unknown; declare const tool: { name: string }; const fields: Opaque = tool;", output: null, errors: [{ messageId: "widening" }] },
    { name: "retains inference with an independent exported type use", code: "export type Kept = Opaque; type Opaque = unknown; declare const tool: { name: string }; const fields: Opaque = tool;", output: "export type Kept = Opaque; type Opaque = unknown; declare const tool: { name: string }; const fields = tool;", errors: [{ messageId: "widening" }] },
    { name: "does not count a second erasable variable annotation as a witness", code: "export {}; type Opaque = unknown; declare const tool: { name: string }; const first: Opaque = tool; const second: Opaque = tool;", output: null, errors: [{ messageId: "widening" }, { messageId: "widening" }] },
    { name: "retains inference only for an unused private module binding", code: "export {}; declare const tool: { name: string }; const fields: unknown = tool;", output: "export {}; declare const tool: { name: string }; const fields = tool;", errors: [{ messageId: "widening" }] },
    { name: "preserves an exported alias contract", code: "declare const tool: { name: string }; const fields: unknown = tool; export { fields };", output: null, errors: [{ messageId: "widening" }] },
    { name: "preserves explicit annotation comments", code: "export {}; declare const tool: { name: string }; const fields: /* opaque boundary */ unknown = tool;", output: null, errors: [{ messageId: "widening" }] },
    { code: "declare const value: { name: string } | undefined; const output: unknown = value;", errors: [{ messageId: "widening" }] },
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

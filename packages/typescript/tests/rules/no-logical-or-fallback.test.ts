import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";

import rule, { NO_LOGICAL_OR_FALLBACK_DOCUMENTATION } from "../../src/rules/no-logical-or-fallback.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });
const ERROR = { messageId: "logicalOrFallback" } as const;

TESTER.run("no-logical-or-fallback", rule, {
  valid: [
    { name: "explicit empty-string fallback", code: NO_LOGICAL_OR_FALLBACK_DOCUMENTATION.examples[1].files[0].source },
    { name: "boolean aggregation", code: NO_LOGICAL_OR_FALLBACK_DOCUMENTATION.examples[2].files[0].source },
    { name: "nullish fallback", code: 'declare const title: string | undefined; const result = title ?? "Untitled";' },
    { name: "nullable string remains owned upstream", code: 'declare const title: string | undefined; const result = title || "Untitled";' },
    { name: "nullable number remains owned upstream", code: 'declare const value: number | null; const result = value || 10;' },
    { name: "if condition", code: 'declare const a: string, b: string; if (a || b) consume();' },
    { name: "while condition", code: 'declare const a: string, b: string; while (a || b) consume();' },
    { name: "for condition", code: 'declare const a: string, b: string; for (; a || b;) consume();' },
    { name: "ternary condition", code: 'declare const a: string, b: string; const result = a || b ? 1 : 2;' },
    { name: "logical negation", code: 'declare const a: string, b: string; const result = !(a || b);' },
    { name: "Boolean coercion", code: 'declare const a: string, b: string; const result = Boolean(a || b);' },
    { name: "left-hand and guard", code: 'declare const a: string, b: string; const result = (a || b) && render();' },
    { name: "unknown value", code: 'declare const value: unknown; const result = value || "default";' },
    { name: "any value", code: 'declare const value: any; const result = value || "default";' },
    { name: "generic value", code: 'function fallback<T>(value: T) { return value || "default"; }' },
    { name: "object-only input stays with unnecessary-condition", code: 'declare const value: { id: string }; const result = value || { id: "default" };' },
    { name: "always truthy stays with unnecessary-condition", code: 'declare const value: "ready" | "done"; const result = value || "default";' },
    { name: "always falsy stays with unnecessary-condition", code: 'declare const value: "" | 0; const result = value || "default";' },
    { name: "comments and strings are not expressions", code: '// title || "default"\nconst source = "value || fallback";' },
    { name: "generated code is excluded", code: '// @generated\ndeclare const value: string; const result = value || "default";' },
  ],
  invalid: [
    { name: "trimmed title fallback", code: NO_LOGICAL_OR_FALLBACK_DOCUMENTATION.examples[0].files[0].source, output: null, errors: [ERROR] },
    { name: "zero fallback", code: 'function count(value: number) { return value || 10; }', output: null, errors: [ERROR] },
    { name: "bigint zero fallback", code: 'function count(value: bigint) { return value || 10n; }', output: null, errors: [ERROR] },
    { name: "mixed primitive union", code: 'function fallback(value: string | number) { return value || "default"; }', output: null, errors: [ERROR] },
    { name: "literal union can contain an empty value", code: 'function fallback(value: "" | "ready") { return value || "default"; }', output: null, errors: [ERROR] },
    { name: "fallback under right-hand and", code: 'function title(ready: boolean, value: string) { return ready && (value || "default"); }', output: null, errors: [ERROR] },
    { name: "shadowed Boolean may consume the value", code: 'function title(Boolean: (value: string) => string, value: string) { return Boolean(value || "default"); }', output: null, errors: [ERROR] },
    { name: "nonboolean call argument in a condition", code: 'function check(value: string) { if (consume(value || "default")) work(); }', output: null, errors: [ERROR] },
  ],
});

it("executes documented examples", async () => {
  await expect(verifyRuleExamples(rule)).resolves.toBe(3);
});

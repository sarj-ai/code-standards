// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION,
} from "../../src/rules/prefer-named-complex-return-type.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("prefer-named-complex-return-type", rule, {
  valid: [
    "type Result<T> = { id: string; value: T; active: boolean }; function generic<T>(value: T): Result<T> { return { id: '', value, active: true }; }",
    "class Port { read(): { owner: this; id: string; active: boolean } { return { owner: this, id: '', active: true }; } }",
    "function captured(value: string): { value: typeof value; id: string; active: boolean } { return { value, id: '', active: true }; }",
    "function dependent(value: string): { [K in keyof typeof value]: { id: string; active: boolean; value: K } } { return {} as never; }",
    PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION.examples[0].files[0].source,
    "function small(): { id: string; name: string } { return { id: '', name: '' }; }",
    "function inferred() { return { id: '', name: '', active: true }; }",
    "function primitives(): 'a' | 'b' | 'c' { return 'a'; }",
    {
      filename: "src/job.test.ts",
      code: "function fixture(): { a: 1; b: 2; c: 3 } { return { a: 1, b: 2, c: 3 }; }",
    },
    {
      filename: "src/generated/job.ts",
      code: "function generated(): { a: 1; b: 2; c: 3 } { return { a: 1, b: 2, c: 3 }; }",
    },
  ],
  invalid: [
    {
      name: "preserves unresolved ownership boundary 1",
      code: "export type Claim = { id: string; name: string; active: boolean }; export function claim(): { id: string; name: string; active: boolean } { return { id: '', name: '', active: true }; }",
      output: null,
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      name: "preserves unresolved ownership boundary 2",
      code: "type Claim = { id: string; name: string; active: boolean }; function claim(): { id: string; name: string; active: boolean } { return { id: '', name: '', active: true }; }",
      output: null,
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      name: "preserves unresolved ownership boundary 3",
      code: "export type Claim = { id: string; name: string; active: boolean }; function claim<Claim>(): { id: string; name: string; active: boolean } { return { id: '', name: '', active: true }; }",
      output: null,
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      name: "preserves unresolved ownership boundary 4",
      code: "export type Claim = { id: string; name: string; active: boolean }; export type Alternative = { id: string; name: string; active: boolean }; function claim(): { id: string; name: string; active: boolean } { return { id: '', name: '', active: true }; }",
      output: null,
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      name: "preserves unresolved ownership boundary 5",
      code: "export type Claim = { id: string; name: string; active: boolean }; function claim(): { id: string; name: string; readonly active: boolean } { return { id: '', name: '', active: true }; }",
      output: null,
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      name: "preserves unresolved ownership boundary 6",
      code: "export type Claim = { id: string; name: string; active: boolean }; function claim(): { id: string; name: string; active: boolean } { return { id: '', name: '', active: true }; } consume(claim);",
      output: null,
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      name: "reuses the unique existing exported alias",
      code: "export type Claim = { id: string; name: string; active: boolean }; function claim(): { id: string; name: string; active: boolean } { return { id: '', name: '', active: true }; }",
      output:
        "export type Claim = { id: string; name: string; active: boolean }; function claim(): Claim { return { id: '', name: '', active: true }; }",
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      code: PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION.examples[1].files[0]
        .source,
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      code: "declare function load(): Promise<{ id: string; name: string; active: boolean }>;;",
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      code: "interface Port { load(): { id: string; name: string; active: boolean } }",
      errors: [{ messageId: "nameComplexReturnType" }],
    },
  ],
});

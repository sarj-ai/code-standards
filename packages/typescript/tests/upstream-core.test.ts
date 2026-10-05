import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import core from "../src/upstream/core.js";

RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
const options = [
  {
    selector:
      "UnaryExpression[operator='typeof']:not([parent.type='BinaryExpression'][parent.operator=/^(===|!==|==|!=)$/][parent.right.type='Literal'][parent.right.value='undefined']):not([parent.type='BinaryExpression'][parent.operator=/^(===|!==|==|!=)$/][parent.left.type='Literal'][parent.left.value='undefined'])",
    message: "Preserve known types or validate external input.",
  },
  {
    selector: "CallExpression[callee.property.name='forEach']",
    message: "Use for-of.",
  },
  {
    selector: "TSModuleDeclaration[kind='namespace']",
    message: "Use modules.",
  },
];
const restricted = (code: string) => ({ code, options });
const blocked = (code: string) => ({
  ...restricted(code),
  errors: [{ messageId: "restrictedSyntax" }],
});

tester.run("core/no-restricted-syntax", core.rules["no-restricted-syntax"], {
  valid: [
    restricted("typeof value === 'undefined';"),
    restricted("'undefined' !== typeof value;"),
    restricted("type Value = typeof value;"),
    restricted("for (const value of values) consume(value);"),
    restricted("declare module 'contract' { export type ID = string; }"),
  ],
  invalid: [
    blocked("typeof value === 'string';"),
    blocked("typeof value;"),
    blocked("values.forEach(consume);"),
    blocked("namespace Domain { export const id = 1; }"),
  ],
});

tester.run("core/no-undef-init", core.rules["no-undef-init"], {
  valid: [
    "let value;",
    "const value = undefined;",
    "function inspect(undefined: unknown) { let value = undefined; }",
    "let value = void 0;",
  ],
  invalid: [
    {
      code: "let value = undefined;",
      output: "let value;",
      errors: [{ messageId: "unnecessaryUndefinedInit" }],
    },
    {
      code: "var value = undefined;",
      output: null,
      errors: [{ messageId: "unnecessaryUndefinedInit" }],
    },
    {
      code: "let value /* external contract */ = undefined;",
      output: null,
      errors: [{ messageId: "unnecessaryUndefinedInit" }],
    },
    {
      code: "let value: string | undefined = undefined;",
      output: "let value: string | undefined;",
      errors: [{ messageId: "unnecessaryUndefinedInit" }],
    },
  ],
});

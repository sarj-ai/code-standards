// vitest: shared-module-graph
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import namedReturn from "../src/rules/prefer-named-complex-return-type.js";
import namedCallback from "../src/rules/prefer-named-callback-domain.js";
import stringLoop from "../src/rules/no-string-concat-in-loop.js";
import collectionProperty from "../src/rules/no-in-operator-on-built-in-collections.js";
import literalLookup from "../src/rules/prefer-module-level-constant.js";
import declarationOrder from "../src/rules/stepdown.js";
import staticMatcher from "../src/rules/require-static-next-matcher.js";
import repeatedLiteral from "../src/rules/no-repeated-string-literal.js";
import identityReduce from "../src/rules/no-reduce-accumulator-copy.js";

type SyntaxRule =
  | typeof namedReturn
  | typeof namedCallback
  | typeof stringLoop
  | typeof literalLookup
  | typeof declarationOrder;
type ClosingRule = SyntaxRule | typeof staticMatcher | typeof repeatedLiteral;

function apply(
  rule: ClosingRule,
  source: string,
): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(
    source,
    [
      {
        files: ["**/*.ts"],
        languageOptions: { parser },
        plugins: { local: { rules: { check: rule } } },
        rules: { "local/check": "error" },
      },
    ],
    {
      filename:
        rule === staticMatcher ? "src/middleware.ts" : "src/closing-autofix.ts",
    },
  );
}

function evaluate(source: string, expression: string): unknown {
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ESNext,
      module: ts.ModuleKind.CommonJS,
    },
  }).outputText;
  return runInNewContext(`${compiled}\nJSON.stringify(${expression});`, {
    exports: {},
  });
}

it.each([
  namedReturn,
  namedCallback,
  stringLoop,
  literalLookup,
  declarationOrder,
  staticMatcher,
  repeatedLiteral,
])("converges on the authored correction for $name", (rule) => {
  const example = rule.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  if (example?.fixedFiles?.[0] === undefined || example.files[0] === undefined)
    throw new Error("Missing fixed example");
  const result = apply(rule, example.files[0].source);
  expect(result.fixed).toBe(true);
  expect(result.output).toBe(example.fixedFiles[0].source);
  expect(result.messages).toEqual([]);
  const repeated = apply(rule, result.output);
  expect(repeated.fixed).toBe(false);
  expect(repeated.output).toBe(result.output);
  expect(repeated.messages).toEqual([]);
});

it.each(["", "a", "𝄞", "\u0000", "\n", "same"])(
  "preserves literal string accumulation for %s",
  (fragment) => {
    const source = `export function render() { let output = 'prefix'; for (const item of [${JSON.stringify(fragment)}, 'tail']) { output += item; } return output; }`;
    const result = apply(stringLoop, source);
    expect(result.fixed).toBe(true);
    expect(evaluate(result.output, "exports.render()")).toBe(
      evaluate(source, "exports.render()"),
    );
  },
);

it("preserves repeated readonly lookup results without exposing identity", () => {
  const example = literalLookup.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  if (example?.fixedFiles?.[0] === undefined || example.files[0] === undefined)
    throw new Error("Missing lookup example");
  const expression =
    "['a','missing','c','a'].map((key) => exports.isAllowed(key))";
  expect(evaluate(example.fixedFiles[0].source, expression)).toBe(
    evaluate(example.files[0].source, expression),
  );
});

it("preserves Proxy has-trap count, key and property result", () => {
  const example = collectionProperty.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  if (example?.fixedFiles?.[0] === undefined || example.files[0] === undefined)
    throw new Error("Missing property example");
  const expression =
    "(() => { const keys = []; const target = new Proxy(new Map(), { has(value,key) { keys.push(key); return Reflect.has(value,key); } }); return [exports.hasSize(target),keys]; })()";
  expect(evaluate(example.fixedFiles[0].source, expression)).toBe(
    evaluate(example.files[0].source, expression),
  );
});

it("retains on-call default argument evaluation through declaration ordering", () => {
  const source =
    "function load(value = 2) { return value; } export function run(value = load()) { return load(value); }";
  const fixed = apply(declarationOrder, source);
  expect(fixed.fixed).toBe(true);
  const expression = "[exports.run(), exports.run(7), exports.run()]";
  expect(evaluate(fixed.output, expression)).toBe(evaluate(source, expression));
});

it.each(["/api/:path*", "/α/:path*", "/api/\\.json"])(
  "preserves the already authored matcher value %s",
  (route) => {
    const source = `const matcher = ${JSON.stringify(route)}; export const config = { matcher };`;
    const fixed = apply(staticMatcher, source);
    expect(fixed.fixed).toBe(true);
    expect(evaluate(fixed.output, "exports.config")).toBe(
      evaluate(source, "exports.config"),
    );
    expect(apply(staticMatcher, fixed.output).fixed).toBe(false);
  },
);

it("reuses the existing primitive value across every repeated return", () => {
  const example = repeatedLiteral.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  if (example?.files[0] === undefined)
    throw new Error("Missing existing constant example");
  const result = apply(repeatedLiteral, example.files[0].source);
  expect(result.fixed).toBe(true);
  const expression =
    "[exports.current(),exports.one(),exports.two(),exports.one()]";
  expect(evaluate(result.output, expression)).toBe(
    evaluate(example.files[0].source, expression),
  );
  expect(apply(repeatedLiteral, result.output).fixed).toBe(false);
});

it("preserves fresh identity collection results independently across calls", () => {
  const example = identityReduce.documentation?.examples.find(
    (entry) => entry.id === "safe-autofix",
  );
  if (example?.files[0] === undefined || example.fixedFiles?.[0] === undefined)
    throw new Error("Missing identity collection example");
  const expression =
    "(() => { const first=exports.collect(); const second=exports.collect(); first.push('local'); return [first,second,first!==second]; })()";
  expect(evaluate(example.fixedFiles[0].source, expression)).toBe(
    evaluate(example.files[0].source, expression),
  );
});

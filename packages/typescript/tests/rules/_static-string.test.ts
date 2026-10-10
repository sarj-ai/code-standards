// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";
import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { scopedStaticString, staticPropertyName, staticString } from "../../src/rules/_static-string.js";

const CASES = [
  { name: "literal member", code: "record.json;", expected: "json" },
  { name: "literal computed member", code: "record['json'];", expected: "json" },
  { name: "preserves literal expression decoding", code: "record['j' + 'son'];", expected: "json" },
  { name: "local const member", code: "const key = 'json'; record[key];", expected: "json" },
  { name: "local template member", code: "const key = `json`; record[key];", expected: "json" },
  { name: "stable local aliases", code: "const original = 'json'; const key = original; record[key];", expected: "json" },
  { name: "initializer lexical scope", code: "const original = 'json'; const key = original; function f() { const original = 'send'; record[key]; }", expected: "json" },
  { name: "inner key binding", code: "const key = 'json'; function f() { const key = 'send'; record[key]; }", expected: "send" },
  { name: "stable let", code: "let key = 'json'; record[key];", expected: "json" },
  { name: "mutated let abstains", code: "let key = 'json'; key = 'send'; record[key];", expected: null },
  { name: "Symbol abstains", code: "const key = Symbol('json'); record[key];", expected: null },
  { name: "function-derived key abstains", code: "String = () => 'send'; const key = String('json'); record[key];", expected: null },
  { name: "object-derived key abstains", code: "const settings = { key: 'json' }; const key = settings.key; record[key];", expected: null },
  { name: "unresolved parameter abstains", code: "function f(key) { record[key]; }", expected: null },
  { name: "alias cycle terminates", code: "const first = second; const second = first; record[first];", expected: null },
  { name: "literal property", code: "sink({ json: true });", expected: "json" },
  { name: "computed local property", code: "const key = 'json'; sink({ [key]: true });", expected: "json" },
  { name: "property initializer lexical scope", code: "const original = 'json'; const key = original; function f() { const original = 'send'; sink({ [key]: true }); }", expected: "json" },
  { name: "mutated property key abstains", code: "let key = 'json'; key = 'send'; sink({ [key]: true });", expected: null },
] as const;

describe("static property names", () => {
  for (const entry of CASES) {
    it(entry.name, () => {
      const found: (string | null)[] = [];
      const rule: TSESLint.RuleModule<string, []> = {
        meta: { type: "problem", schema: [], messages: {} },
        defaultOptions: [],
        create(context) {
          return {
            MemberExpression(node: TSESTree.MemberExpression) {
              if (node.object.type === AST_NODE_TYPES.Identifier && node.object.name === "record") {
                const name = staticPropertyName(node, context.sourceCode);
                expect(staticPropertyName(node, context.sourceCode)).toBe(name);
                found.push(name);
              }
            },
            Property(node: TSESTree.Property) {
              if (node.parent.type === AST_NODE_TYPES.ObjectExpression && node.parent.parent.type === AST_NODE_TYPES.CallExpression) {
                const name = staticPropertyName(node, context.sourceCode);
                expect(staticPropertyName(node, context.sourceCode)).toBe(name);
                found.push(name);
              }
            },
          };
        },
      };
      const messages = new Linter().verify(entry.code, [{
        files: ["**/*.ts"],
        languageOptions: { parser: tsParser, globals: { String: "writable", Symbol: "readonly" } },
        plugins: { proof: { rules: { capture: rule } } },
        rules: { "proof/capture": "error" },
      }], { filename: "src/example.ts" });
      expect(messages).toEqual([]);
      expect(found).toEqual([entry.expected]);
    });
  }
});

describe("scoped string values preserve the unscoped contract", () => {
  for (const [code, scoped, unscoped] of [
    ["sink('json');", "json", "json"],
    ["const key = 'json'; sink(key);", "json", null],
    ["const key = `json`; sink(key);", "json", null],
    ["String = () => 'send'; const key = String('json'); sink(key);", null, null],
    ["const key = 'j' + 'son'; sink(key);", null, null],
  ] as const) {
    it(code, () => {
      const found: (string | null)[] = [];
      const rule: TSESLint.RuleModule<string, []> = {
        meta: { type: "problem", schema: [], messages: {} }, defaultOptions: [],
        create(context) {
          return {
            CallExpression(node: TSESTree.CallExpression) {
              if (node.callee.type !== AST_NODE_TYPES.Identifier || node.callee.name !== "sink" || !node.arguments[0]) return;
              const value = scopedStaticString(node.arguments[0], context.sourceCode);
              expect(scopedStaticString(node.arguments[0], context.sourceCode)).toBe(value);
              found.push(value, staticString(node.arguments[0]));
            },
          };
        },
      };
      expect(new Linter().verify(code, [{
        files: ["**/*.ts"], languageOptions: { parser: tsParser },
        plugins: { proof: { rules: { capture: rule } } }, rules: { "proof/capture": "error" },
      }], { filename: "src/example.ts" })).toEqual([]);
      expect(found).toEqual([scoped, unscoped]);
    });
  }

  it("keeps changed source values distinct at one filename", () => {
    const found: (string | null)[] = [];
    const rule: TSESLint.RuleModule<string, []> = {
      meta: { type: "problem", schema: [], messages: {} }, defaultOptions: [],
      create(context) {
        return {
          CallExpression(node: TSESTree.CallExpression) {
            if (node.callee.type === AST_NODE_TYPES.Identifier && node.callee.name === "sink" && node.arguments[0]) {
              found.push(scopedStaticString(node.arguments[0], context.sourceCode));
            }
          },
        };
      },
    };
    const linter = new Linter();
    const config = [{
      files: ["**/*.ts"], languageOptions: { parser: tsParser },
      plugins: { proof: { rules: { capture: rule } } }, rules: { "proof/capture": "error" as const },
    }];
    for (const source of ["const key = 'json'; sink(key);", "const key = 'send'; sink(key);", "let key = 'json'; key = 'send'; sink(key);"]) {
      expect(linter.verify(source, config, { filename: "src/example.ts" })).toEqual([]);
    }
    expect(found).toEqual(["json", "send", null]);
  });
});

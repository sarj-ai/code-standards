import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { ASTUtils, TSESLint } from "@typescript-eslint/utils";
import type { TSESTree } from "@typescript-eslint/utils";
import { Linter } from "eslint";
import { expect, it } from "vitest";

import { createNativeRule, getTypeServices, hasSideEffect } from "../src/rules/_eslint-rule.js";
import { forEachAstChild } from "../src/rules/_for-each-ast-child.js";

function ruleUrl(name: string): string {
  return `https://example.invalid/rules/${name}`;
}

function metadata() {
  return {
    type: "problem" as const,
    docs: { description: "Check native TypeScript execution" },
    schema: [],
    messages: { probe: "Probe." },
  };
}

it("executes TypeScript selectors, reports and fixes through the native host", () => {
  const observed: string[] = [];
  const rule = createNativeRule<readonly [], "probe">({
    name: "native-typescript-selector",
    meta: { ...metadata(), fixable: "code" },
    create(context) {
      return {
        AccessorProperty(node) {
          observed.push(context.sourceCode.getText(node));
          context.report({ node, messageId: "probe", fix(fixer) {
            return fixer.replaceText(node, "replacement = 2;");
          } });
        },
      };
    },
  }, ruleUrl);
  const result = new Linter().verifyAndFix("class Example { accessor value: number = 1; }", {
    files: ["**/*.ts"],
    languageOptions: { parser },
    plugins: { probe: { rules: { rule } } },
    rules: { "probe/rule": "error" },
  }, { filename: "input.ts" });
  expect(result.messages).toEqual([]);
  expect(result.fixed).toBe(true);
  expect(result.output).toBe("class Example { replacement = 2; }");
  expect(observed).toEqual(["accessor value: number = 1;"]);
});

it("retains the actual typed program and parser-service maps", async () => {
  const root = await mkdtemp(join(tmpdir(), "native-eslint-services-"));
  const filename = join(root, "input.ts");
  const code = "export const value: number = 1;\n";
  try {
    await writeFile(filename, code);
    await writeFile(join(root, "tsconfig.json"), JSON.stringify({
      compilerOptions: { strict: true, target: "es2022", module: "nodenext", types: [] },
      include: ["input.ts"],
    }));
    let observed = false;
    const rule = createNativeRule<readonly [], "probe">({
      name: "typed-services", meta: metadata(),
      create(context) {
        const services = getTypeServices(context);
        expect(services).toBe(context.sourceCode.parserServices);
        expect(services.esTreeNodeToTSNodeMap.get(context.sourceCode.ast))
          .toBe(services.program.getSourceFile(filename));
        expect(services.tsNodeToESTreeNodeMap.get(services.esTreeNodeToTSNodeMap.get(context.sourceCode.ast)))
          .toBe(context.sourceCode.ast);
        observed = true;
        return {};
      },
    }, ruleUrl);
    expect(new Linter({ cwd: root }).verify(code, {
      files: ["**/*.ts"],
      languageOptions: { parser, parserOptions: { project: join(root, "tsconfig.json"), tsconfigRootDir: root } },
      plugins: { probe: { rules: { rule } } }, rules: { "probe/rule": "error" },
    }, { filename })).toEqual([]);
    expect(observed).toBe(true);
  } finally {
    parser.clearCaches();
    await rm(root, { recursive: true, force: true });
  }
});

it("matches pinned side-effect analysis on TypeScript children and fallback traversal", () => {
  const code = "class Value { accessor item: number = 1; [key] = target[field]; } const result = (left + right) satisfies number;";
  const parsed = parser.parseForESLint(code, { range: true, loc: true, tokens: true, comment: true });
  const source = new TSESLint.SourceCode({ text: code, ast: parsed.ast, visitorKeys: parsed.visitorKeys,
    scopeManager: parsed.scopeManager, parserServices: parsed.services });
  const modes = [{}, { considerGetters: true }, { considerImplicitTypeConversion: true },
    { considerGetters: true, considerImplicitTypeConversion: true }];
  let comparisons = 0;
  const pending: TSESTree.Node[] = [parsed.ast];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined) throw new Error("The AST traversal lost its next node.");
    for (const mode of modes) {
      expect(hasSideEffect(node, source, mode)).toBe(ASTUtils.hasSideEffect(node, source, mode));
      const fallback = { visitorKeys: {} };
      expect(hasSideEffect(node, fallback, mode)).toBe(ASTUtils.hasSideEffect(node, fallback, mode));
      comparisons += 2;
    }
    forEachAstChild(node, parsed.visitorKeys, child => { pending.push(child); });
  }
  expect(comparisons).toBeGreaterThan(100);
});

it("snapshots side-effect options and visitor keys once per invocation", () => {
  const code = "1 + object[key];";
  const { ast, visitorKeys } = parser.parseForESLint(code, { range: true, loc: true });
  let getters = 0, conversions = 0, keyReads = 0;
  const result = hasSideEffect(ast, { get visitorKeys() { keyReads += 1; return visitorKeys; } }, {
    get considerGetters() { getters += 1; return getters > 1; },
    get considerImplicitTypeConversion() { conversions += 1; return conversions > 1; },
  });
  expect(result).toBe(false);
  expect([getters, conversions, keyReads]).toEqual([1, 1, 1]);
});

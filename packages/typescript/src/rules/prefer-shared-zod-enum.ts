/**
 * @fileoverview prefer-shared-zod-enum — repeated literal enum domains can drift within one module.
 *
 * Port of the 18.x `prefer-shared-zod-enum` rule. Same algorithm; the
 * test/generated file gate and per-file state reset run in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-shared-zod-enum.test.ts
 */

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "prefer-shared-zod-enum";
type Identifier = Extract<Node, { type: "Identifier" }>;
interface Candidate { readonly node: ESTree.CallExpression; readonly named: boolean }

function literalDomain(node: ESTree.CallExpression): readonly string[] | null {
  if (node.arguments.length !== 1) return null;
  const first = node.arguments[0];
  const argument = first === undefined ? undefined : unwrapExpression(first);
  if (argument?.type !== "ArrayExpression" || argument.elements.length < 2) return null;
  const values: string[] = [];
  for (const element of argument.elements) {
    const value = element === null ? null : staticString(element);
    if (value === null) return null;
    values.push(value);
  }
  return values;
}

/** `const X = z.enum([…]).describe(…)`: the enum, through its method chain, initializes a module-level binding. */
function isModuleLevelNamedSchema(node: ESTree.CallExpression): boolean {
  const schema = methodChainEnd(node);
  const declarator = parentOf(schema);
  if (declarator?.type !== "VariableDeclarator" || declarator.init !== schema || declarator.id.type !== "Identifier") return false;
  const declaration = parentOf(declarator);
  return declaration?.type === "VariableDeclaration" && isModuleLevelStatement(declaration);
}

/** The outermost `node.a(…).b` expression that calls or reads methods on `node`. */
function methodChainEnd(node: Node): Node {
  let current = node;
  for (let parent = parentOf(current); parent?.type === "MemberExpression" && parent.object === current; parent = parentOf(current)) {
    current = parent;
    const call = parentOf(current);
    if (call?.type === "CallExpression" && call.callee === current) current = call;
  }
  return current;
}

function isModuleLevelStatement(statement: Node): boolean {
  const parent = parentOf(statement);
  return parent?.type === "Program" || (parent?.type === "ExportNamedDeclaration" && parentOf(parent)?.type === "Program");
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Give repeated literal Zod enum domains one reusable module-level schema.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      shareEnumDomain: "Extract this literal Zod enum to one module-level named schema and reuse it.",
    },
  },
  createOnce(context) {
    const zodBindings = new Set<TsVariable>();
    const candidates = new Map<string, Candidate[]>();
    const bindingOf = (node: Identifier): TsVariable | null => findVariable(context.sourceCode.getScope(node), node.name);

    return {
      before() {
        zodBindings.clear();
        candidates.clear();
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
      ImportDeclaration(node) {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "z")
          ) {
            const binding = bindingOf(specifier.local);
            if (binding !== null) zodBindings.add(binding);
          }
        }
      },
      CallExpression(node) {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression") return;
        const receiver = unwrapExpression(callee.object);
        if (receiver.type !== "Identifier" || getPropertyName(callee) !== "enum") return;
        const domain = literalDomain(node);
        if (domain === null) return;
        const binding = bindingOf(receiver);
        if (binding === null || !zodBindings.has(binding)) return;
        const key = JSON.stringify(domain);
        const group = candidates.get(key) ?? [];
        group.push({ node, named: isModuleLevelNamedSchema(node) });
        candidates.set(key, group);
      },
      "Program:exit"() {
        for (const group of candidates.values()) {
          if (group.length < 2) continue;
          const canonical = group.find((candidate) => candidate.named);
          for (const candidate of group) {
            if (candidate === canonical) continue;
            context.report({ node: candidate.node, messageId: "shareEnumDomain" });
          }
        }
      },
    };
  },
});

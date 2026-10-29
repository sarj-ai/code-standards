/**
 * @fileoverview no-discarded-validation-result — Consume Zod validation outcomes and transformed outputs instead of discarding them.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-discarded-validation-result.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { isZodModule } from "./_zod.js";

const CHANGING: ReadonlySet<string> = new Set(["transform", "default", "prefault", "catch", "coerce", "trim", "toLowerCase", "toUpperCase", "normalize", "preprocess"]);

export const NO_DISCARDED_VALIDATION_RESULT_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Consume Zod validation outcomes and transformed outputs instead of discarding them.",
  rationale: "Ignoring safeParse loses failure information; ignoring a transformed parse result leaves callers using values without the declared defaults, coercions or normalization.",
  remediation: "Capture or return the parsed output. Branch on safeParse success and use data. Plain throwing validation without output changes remains supported.",
  category: "correctness",
  limitations: [
    "Checks expression-statement parse/parseAsync/safeParse/safeParseAsync calls on import-proven Zod factories and immutable local schema aliases. Await wrappers are supported.",
    "Throwing parse is reported only for source-visible output-changing schema operations. Plain validation-only parse, imported schemas, custom validators, mutable bindings, generated files and opaque effects are excluded. No automatic variable or control flow is invented.",
  ],
  examples: [
    { id: "lost-transform", title: "The normalized output is discarded", outcome: "match", files: [{ path: "app.ts", source: "import { z } from 'zod'; z.string().trim().parse(raw);" }], focusPath: "app.ts", expectedCount: 1, public: true },
    { id: "used-transform", title: "Return the parsed value", outcome: "no-match", files: [{ path: "app.ts", source: "import { z } from 'zod'; function parse(raw: unknown) { return z.string().trim().parse(raw); }" }], focusPath: "app.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "discarded">({
  name: "no-discarded-validation-result",
  documentation: NO_DISCARDED_VALIDATION_RESULT_DOCUMENTATION,
  meta: { type: "problem", docs: { description: NO_DISCARDED_VALIDATION_RESULT_DOCUMENTATION.summary }, schema: [], messages: { discarded: "Consume this validation result; its outcome or transformed value is currently discarded." } },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    const sourceCode = context.sourceCode;
    function schema(node: TSESTree.Node, depth = 0): { changed: boolean } | null {
      if (depth > 24) return null;
      node = unwrapExpression(node);
      if (node.type === AST_NODE_TYPES.Identifier) {
        const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
        const definition = variable?.defs[0]?.node;
        if (variable?.defs.length !== 1) return null;
        if (definition?.type === AST_NODE_TYPES.ImportSpecifier && definition.parent.type === AST_NODE_TYPES.ImportDeclaration && definition.importKind !== "type" && definition.parent.importKind !== "type" && isZodModule(definition.parent.source.value)) return { changed: false };
        if (definition?.type === AST_NODE_TYPES.ImportNamespaceSpecifier && definition.parent.importKind !== "type" && isZodModule(definition.parent.source.value)) return { changed: false };
        if (definition?.type === AST_NODE_TYPES.VariableDeclarator && definition.parent.kind === "const" && definition.init !== null && definition.range[1] < node.range[0] && !variable.references.some(reference => reference.isWrite() && !reference.init)) return schema(definition.init, depth + 1);
        return null;
      }
      if (node.type === AST_NODE_TYPES.MemberExpression) {
        const owner = schema(node.object, depth + 1);
        return owner;
      }
      if (node.type !== AST_NODE_TYPES.CallExpression) return null;
      const owner = schema(node.callee, depth + 1);
      if (owner === null) return null;
      const invokedChange = node.callee.type === AST_NODE_TYPES.MemberExpression && CHANGING.has(ASTUtils.getPropertyName(node.callee) ?? "");
      const coerced = node.callee.type === AST_NODE_TYPES.MemberExpression && coercionNamespace(node.callee.object);
      const changedArgument = node.arguments.some(argument => {
        if (argument.type === AST_NODE_TYPES.ArrayExpression) return argument.elements.some(element => element !== null && schema(element, depth + 1)?.changed === true);
        if (argument.type === AST_NODE_TYPES.ObjectExpression) return argument.properties.some(property => property.type === AST_NODE_TYPES.Property && schema(property.value, depth + 1)?.changed === true);
        return schema(argument, depth + 1)?.changed === true;
      });
      return { changed: owner.changed || invokedChange || coerced || changedArgument };
    }
    function coercionNamespace(node: TSESTree.Node): boolean {
      let namespace = false;
      if (node.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(node) === "coerce") {
        namespace = true;
        node = node.object;
      }
      if (node.type !== AST_NODE_TYPES.Identifier) return false;
      const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
      const definition = variable?.defs[0]?.node;
      if (variable?.defs.length !== 1 || definition === undefined || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration || definition.parent.importKind === "type" || !isZodModule(definition.parent.source.value)) return false;
      if (definition.type === AST_NODE_TYPES.ImportNamespaceSpecifier) return namespace;
      if (definition.type !== AST_NODE_TYPES.ImportSpecifier || definition.importKind === "type") return false;
      const name = definition.imported.type === AST_NODE_TYPES.Identifier ? definition.imported.name : definition.imported.value;
      return namespace ? name === "z" : name === "coerce";
    }
    return {
      ExpressionStatement(statement) {
        let expression = unwrapExpression(statement.expression);
        if (expression.type === AST_NODE_TYPES.AwaitExpression) expression = unwrapExpression(expression.argument);
        if (expression.type !== AST_NODE_TYPES.CallExpression || expression.callee.type !== AST_NODE_TYPES.MemberExpression) return;
        const method = ASTUtils.getPropertyName(expression.callee);
        if (!new Set(["parse", "parseAsync", "safeParse", "safeParseAsync"]).has(method ?? "")) return;
        const owner = schema(expression.callee.object);
        if (owner !== null && (owner.changed || method?.startsWith("safe") === true)) context.report({ node: expression, messageId: "discarded" });
      },
    };
  },
});

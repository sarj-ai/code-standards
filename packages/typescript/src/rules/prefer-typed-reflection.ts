/**
 * @fileoverview prefer-typed-reflection — Prefer typed access when Reflect.get or Reflect.apply discards a known contract.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-typed-reflection.test.ts
 */
import {
  AST_NODE_TYPES,
  ASTUtils,
  ESLintUtils,
  type TSESTree,
} from "@typescript-eslint/utils";
import ts from "typescript";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { staticString } from "./_static-string.js";
import { unwrapExpression } from "./_unwrap-expression.js";

export const PREFER_TYPED_REFLECTION_DOCUMENTATION = {
  summary:
    "Prefer typed access when Reflect.get or Reflect.apply discards a known contract.",
  rationale:
    "Reflect.get and Reflect.apply can accept property or argument mistakes that normal typed access catches.",
  remediation:
    "Use direct typed property access or call the typed function, preserving receivers and evaluation semantics.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information. Inspects scope-resolved global Reflect.get with a literal key (including no-substitution templates and erased TypeScript wrappers) on a closed object type, and Reflect.apply with a known call signature and a literal argument array.",
    "Dynamic keys, open dictionaries, unknown/any/generic targets, explicit Reflect.get receivers, aliases, and nonliteral argument arrays are excluded. Deliberate proxy or metaprogramming calls need a local suppression. Automatic fixes cover comment-free nonoptional Reflect.get calls with a known existing property on an object. Immediate calls/tags, missing keys and Reflect.apply remain manual to preserve receiver and argument contracts.",
  ],
  examples: [
    {
      id: "before",
      title: "Preserve the explicit contract",
      outcome: "match",
      files: [
        {
          path: "src/example.ts",
          source:
            'declare const shipment: { status: string };\nconst status = Reflect.get(shipment, "status");',
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "after",
      title: "Use the direct contract",
      outcome: "no-match",
      files: [
        {
          path: "src/example.ts",
          source:
            "declare const shipment: { status: string };\nconst status = shipment.status;",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "declare const target: { id: string }; const id = Reflect.get(target, \"id\");" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "declare const target: { id: string }; const id = (target)[\"id\"];" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

function knownType(type: ts.Type): boolean {
  if (type.isUnion()) return type.types.every(knownType);
  return (
    (type.flags &
      (ts.TypeFlags.Any |
        ts.TypeFlags.Unknown |
        ts.TypeFlags.TypeParameter |
        ts.TypeFlags.Never)) ===
    0
  );
}

export default createRule<[], "avoid">({
  name: "prefer-typed-reflection",
  documentation: PREFER_TYPED_REFLECTION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: PREFER_TYPED_REFLECTION_DOCUMENTATION.summary },
    schema: [],
    messages: {
      avoid:
        "Reflection discards this known contract. Use typed property access or a typed call; preserve the invocation receiver and property semantics.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    if (
      !context.sourceCode.parserServices?.program ||
      !context.sourceCode.parserServices.esTreeNodeToTSNodeMap
    )
      return {};
    const services = ESLintUtils.getParserServices(context);
    if (!services.program) return {};
    const checker = services.program.getTypeChecker();
    const isReflect = (node: TSESTree.Node): boolean =>
      globalName(node, "Reflect") ||
      (node.type === AST_NODE_TYPES.MemberExpression &&
        ASTUtils.getPropertyName(node) === "Reflect" &&
        globalName(node.object, "globalThis"));

    const globalName = (node: TSESTree.Node, name: string): boolean =>
      node.type === AST_NODE_TYPES.Identifier &&
      node.name === name &&
      !ASTUtils.findVariable(context.sourceCode.getScope(node), name)?.defs
        .length;
    const closedObject = (type: ts.Type): boolean => {
      if (type.isUnion()) return type.types.every(closedObject);
      return (
        knownType(type) &&
        type.getProperties().length > 0 &&
        checker.getIndexInfosOfType(type).length === 0
      );
    };
    const inspectGet = (
      node: TSESTree.CallExpression,
      type: ts.Type,
    ): boolean => {
      const key = node.arguments[1] === undefined ? undefined : unwrapExpression(node.arguments[1]);
      return (
        node.arguments.length === 2 &&
        (staticString(key) !== null || (key?.type === AST_NODE_TYPES.Literal && typeof key.value === "number")) &&
        closedObject(type)
      );
    };
    const inspectApply = (
      node: TSESTree.CallExpression,
      type: ts.Type,
    ): boolean =>
      node.arguments.length === 3 &&
      node.arguments[2]?.type === AST_NODE_TYPES.ArrayExpression &&
      knownType(type) &&
      type
        .getCallSignatures()
        .some(
          (signature) =>
            signature.typeParameters === undefined &&
            signature.parameters.every((parameter) =>
              knownType(
                checker.getTypeOfSymbolAtLocation(
                  parameter,
                  services.esTreeNodeToTSNodeMap.get(node),
                ),
              ),
            ),
        );
    const getReplacement = (node: TSESTree.CallExpression, type: ts.Type, target: TSESTree.Expression): string | null => {
      if (node.optional || node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.optional ||
        context.sourceCode.getCommentsInside(node).length > 0) return null;
      let outer: TSESTree.Node = node;
      while (outer.parent.type === AST_NODE_TYPES.TSAsExpression || outer.parent.type === AST_NODE_TYPES.TSTypeAssertion ||
        outer.parent.type === AST_NODE_TYPES.TSSatisfiesExpression || outer.parent.type === AST_NODE_TYPES.TSNonNullExpression ||
        outer.parent.type === AST_NODE_TYPES.ChainExpression) outer = outer.parent;
      if ((outer.parent.type === AST_NODE_TYPES.UnaryExpression && outer.parent.operator === "delete") ||
        (outer.parent.type === AST_NODE_TYPES.CallExpression && outer.parent.callee === outer) ||
        (outer.parent.type === AST_NODE_TYPES.TaggedTemplateExpression && outer.parent.tag === outer)) return null;
      const writtenKey = node.arguments[1];
      if (writtenKey === undefined || writtenKey.type === AST_NODE_TYPES.SpreadElement) return null;
      const key = unwrapExpression(writtenKey);
      const name = staticString(key) ?? (key.type === AST_NODE_TYPES.Literal && typeof key.value === "number" ? String(key.value) : null);
      const members = type.isUnion() ? type.types : [type];
      if (name === null || !members.every((member) => (member.flags & ts.TypeFlags.Object) !== 0 && checker.getPropertyOfType(member, name) !== undefined)) return null;
      return `(${context.sourceCode.getText(target)})[${context.sourceCode.getText(writtenKey)}]`;
    };
    return {
      CallExpression(node): void {
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          !isReflect(node.callee.object)
        )
          return;
        const method = ASTUtils.getPropertyName(node.callee);
        const target = node.arguments[0];
        if (
          !target ||
          target.type === AST_NODE_TYPES.SpreadElement ||
          (method !== "get" && method !== "apply")
        )
          return;
        const type = checker.getTypeAtLocation(
          services.esTreeNodeToTSNodeMap.get(target),
        );
        if (
          method === "get" ? inspectGet(node, type) : inspectApply(node, type)
        )
          {
            const replacement = method === "get" ? getReplacement(node, type, target) : null;
            context.report({ node, messageId: "avoid", fix: replacement === null ? null : (fixer) => fixer.replaceText(node, replacement) });
          }
      },
    };
  },
});

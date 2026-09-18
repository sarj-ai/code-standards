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

export const PREFER_TYPED_REFLECTION_DOCUMENTATION = {
  summary:
    "Prefer typed access when Reflect.get or Reflect.apply discards a known contract.",
  rationale:
    "Reflect.get and Reflect.apply can accept property or argument mistakes that normal typed access catches.",
  remediation:
    "Use direct typed property access or call the typed function, preserving receivers and evaluation semantics.",
  category: "maintainability",
  limitations: [
    "Requires TypeScript type information. Inspects scope-resolved global Reflect.get with a literal key on a closed object type, and Reflect.apply with a known call signature and a literal argument array.",
    "Dynamic keys, open dictionaries, unknown/any/generic targets, explicit Reflect.get receivers, aliases, and nonliteral argument arrays are excluded. Deliberate proxy or metaprogramming calls need a local suppression. No autofix because receiver and evaluation semantics may differ.",
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
  ],
} as const satisfies RuleDocumentation;

function propertyName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier)
    return node.property.name;
  if (
    node.computed &&
    node.property.type === AST_NODE_TYPES.Literal &&
    typeof node.property.value === "string"
  )
    return node.property.value;
  return null;
}

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
    docs: { description: PREFER_TYPED_REFLECTION_DOCUMENTATION.summary },
    schema: [],
    messages: {
      avoid:
        "Reflection discards this known contract. Use typed property access or a typed call; preserve the invocation receiver and property semantics.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    if (
      !context.sourceCode.parserServices?.program ||
      !context.sourceCode.parserServices.esTreeNodeToTSNodeMap
    )
      return {};
    const services = ESLintUtils.getParserServices(context);
    if (!services.program) return {};
    const checker = services.program.getTypeChecker();
    const globalName = (node: TSESTree.Node, name: string): boolean =>
      node.type === AST_NODE_TYPES.Identifier &&
      node.name === name &&
      !ASTUtils.findVariable(context.sourceCode.getScope(node), name)?.defs
        .length;
    const isReflect = (node: TSESTree.Node): boolean =>
      globalName(node, "Reflect") ||
      (node.type === AST_NODE_TYPES.MemberExpression &&
        propertyName(node) === "Reflect" &&
        globalName(node.object, "globalThis"));
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
      const key = node.arguments[1];
      return (
        node.arguments.length === 2 &&
        key?.type === AST_NODE_TYPES.Literal &&
        (typeof key.value === "string" || typeof key.value === "number") &&
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
    return {
      CallExpression(node): void {
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          !isReflect(node.callee.object)
        )
          return;
        const method = propertyName(node.callee);
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
          context.report({ node, messageId: "avoid" });
      },
    };
  },
});

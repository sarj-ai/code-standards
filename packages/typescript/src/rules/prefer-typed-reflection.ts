/**
 * @fileoverview prefer-typed-reflection — prefer ordinary access and calls over static reflection.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-typed-reflection.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { arrayMethodTarget, resolveArrayBinding } from "./_array-method.js";
import { isGeneratedFile } from "./_paths.js";
import {
  classifyUnsafeDictionaryValue,
  createTypeEnvironment,
  type TypeEnvironment,
} from "./_dictionary-types.js";

export const PREFER_TYPED_REFLECTION_DOCUMENTATION = {
  summary:
    "Prefer direct access over literal-key Reflect.get and literal-argument Reflect.apply.",
  rationale:
    "Direct access lets the compiler check properties and arguments instead of discarding their contracts through reflection.",
  remediation:
    "Use direct property access or a direct call, preserving receiver and evaluation semantics.",
  category: "maintainability",
  limitations: [
    "Checks scope-resolved Reflect and globalThis.Reflect with a literal key or literal argument array. Explicit same-file unknown/any/object/empty-object annotations and lexical aliases are excluded; other target types are not inferred or imported.",
    "Dynamic keys, custom Reflect bindings, Reflect object aliases, explicit get receivers, and nonliteral argument arrays are excluded. No autofix changes proxy, receiver or evaluation behavior.",
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
            'declare const shipment: { status: string }; const status = Reflect.get(shipment, "status");',
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "after",
      title: "Use direct access",
      outcome: "no-match",
      files: [
        {
          path: "src/example.ts",
          source:
            "declare const shipment: { status: string }; const status = shipment.status;",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
function reflectOwner(sourceCode: SourceCode, node: ESTree.Node): boolean {
  if (globalName(sourceCode, node, "Reflect")) return true;
  const member = arrayMethodTarget(node);
  return (
    member?.name === "Reflect" &&
    globalName(sourceCode, member.object, "globalThis")
  );
}
function globalName(
  sourceCode: SourceCode,
  node: ESTree.Node,
  name: string,
): boolean {
  return (
    node.type === "Identifier" &&
    node.name === name &&
    !resolveArrayBinding(sourceCode, node)?.defs.length
  );
}

function hasOpaqueAnnotation(
  sourceCode: SourceCode,
  node: ESTree.Node,
  environment: TypeEnvironment,
): boolean {
  while (
    node.type === "ParenthesizedExpression" ||
    node.type === "TSNonNullExpression" ||
    node.type === "TSSatisfiesExpression"
  ) {
    node = node.expression;
  }
  if (node.type === "TSAsExpression" || node.type === "TSTypeAssertion") {
    return (
      classifyUnsafeDictionaryValue(node.typeAnnotation, environment) !== null
    );
  }
  const variable = resolveArrayBinding(sourceCode, node);
  return (
    variable?.identifiers.some((identifier) => {
      const annotation =
        identifier.type === "Identifier" ? identifier.typeAnnotation : null;
      return (
        annotation !== null &&
        annotation !== undefined &&
        classifyUnsafeDictionaryValue(
          annotation.typeAnnotation,
          environment,
        ) !== null
      );
    }) ?? false
  );
}
export default createRule({
  name: "prefer-typed-reflection",
  documentation: PREFER_TYPED_REFLECTION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: PREFER_TYPED_REFLECTION_DOCUMENTATION.summary },
    schema: [],
    messages: {
      avoid:
        "Prefer direct property access or a direct call over this literal reflection operation; preserve receiver and property semantics.",
    },
  },
  defaultOptions: [],
  createOnce(context) {
    let environment: TypeEnvironment | null = null;
    return {
      Program(node): void {
        environment = isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
          ? null
          : createTypeEnvironment(node, context.sourceCode.visitorKeys);
      },
      CallExpression(node): void {
        if (environment === null) return;
        const method = arrayMethodTarget(node.callee);
        if (method === null || !reflectOwner(context.sourceCode, method.object))
          return;
        const key = node.arguments[1];
        const literalGet =
          method.name === "get" &&
          node.arguments.length === 2 &&
          key?.type === "Literal" &&
          (typeof key.value === "string" || typeof key.value === "number");
        const literalApply =
          method.name === "apply" &&
          node.arguments.length === 3 &&
          node.arguments[2]?.type === "ArrayExpression";
        const target = node.arguments[0];
        if (
          (literalGet || literalApply) &&
          target !== undefined &&
          target.type !== "SpreadElement" &&
          !hasOpaqueAnnotation(context.sourceCode, target, environment)
        )
          context.report({ node, messageId: "avoid" });
      },
    };
  },
});

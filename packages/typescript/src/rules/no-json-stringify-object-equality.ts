/**
 * @fileoverview no-json-stringify-object-equality — avoid serialization as equality for locally known object values.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-json-stringify-object-equality.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";
import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  arrayMethodTarget,
  resolveArrayBinding,
  unwrapArrayExpression,
} from "./_array-method.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

export const NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Do not use JSON serialization as structural object equality.",
  rationale:
    "Property insertion order and serialization behavior can make equal objects compare unequal and collapse distinct values.",
  remediation:
    "Compare an explicit domain projection or use reviewed canonical serialization when JSON semantics are required.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Checks direct equality between two unshadowed JSON.stringify calls, including opaque arguments. Primitive literals and arrays made entirely of primitive literals are excluded syntactically.",
    "Stored results, JSON aliases, custom JSON objects, imported primitive-array types, tests and generated files are not resolved. Opaque comparisons are intentionally broader than the former typed policy.",
  ],
  examples: [
    {
      id: "domain-comparator",
      title: "Use an explicit structural comparator",
      outcome: "no-match",
      files: [
        {
          path: "src/compare.ts",
          source: "const same = sameRecord(actual, expected);",
        },
      ],
      focusPath: "src/compare.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "serialized-object-equality",
      title: "Do not compare object serialization",
      outcome: "match",
      files: [
        {
          path: "src/compare.ts",
          source:
            'const same = JSON.stringify({ id: "1", state: "ready" }) === JSON.stringify({ state: "ready", id: "1" });',
        },
      ],
      focusPath: "src/compare.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
const EQUALITY: ReadonlySet<string> = new Set(["==", "===", "!=", "!=="]);
function stringifyArgument(
  sourceCode: SourceCode,
  node: ESTree.Node,
): ESTree.Node | null {
  node = unwrapArrayExpression(node);
  if (node.type !== "CallExpression" || node.optional) return null;
  const method = arrayMethodTarget(node.callee);
  if (
    method?.name !== "stringify" ||
    method.object.type !== "Identifier" ||
    method.object.name !== "JSON" ||
    resolveArrayBinding(sourceCode, method.object)?.defs.length
  )
    return null;
  const argument = node.arguments[0];
  return argument !== undefined && argument.type !== "SpreadElement"
    ? argument
    : null;
}
function primitiveLiteral(node: ESTree.Node): boolean {
  node = unwrapArrayExpression(node);
  if (node.type === "Literal") return !("regex" in node);
  if (node.type === "TemplateLiteral") return node.expressions.length === 0;
  if (
    node.type === "UnaryExpression" &&
    ["+", "-", "!", "~", "void"].includes(node.operator)
  )
    return primitiveLiteral(node.argument);
  return (
    node.type === "ArrayExpression" &&
    node.elements.every(
      (element) =>
        element === null ||
        (element.type !== "SpreadElement" && primitiveLiteral(element)),
    )
  );
}
export default createRule({
  name: "no-json-stringify-object-equality",
  documentation: NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description: NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      serializedObjectEquality:
        "JSON serialization equality depends on representation, not object structure. Compare an explicit domain projection or use reviewed canonical serialization.",
    },
  },
  defaultOptions: [],
  createOnce(context) {
    let generated = false;
    return {
      Program(): void {
        generated = isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text);
      },
      BinaryExpression(node): void {
        if (
          !EQUALITY.has(node.operator) ||
          isTestFile(sourceOrigin(context).filename) ||
          generated
        )
          return;
        const left = stringifyArgument(context.sourceCode, node.left);
        const right = stringifyArgument(context.sourceCode, node.right);
        if (
          left !== null &&
          right !== null &&
          !(primitiveLiteral(left) && primitiveLiteral(right))
        )
          context.report({ node, messageId: "serializedObjectEquality" });
      },
    };
  },
});

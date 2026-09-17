/**
 * @fileoverview no-conditional-empty-object-spread — Build conditional properties explicitly instead of spreading an empty-object branch.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-conditional-empty-object-spread.test.ts
 */
import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

export const NO_CONDITIONAL_EMPTY_OBJECT_SPREAD_DOCUMENTATION = {
  summary:
    "Build conditional properties explicitly instead of spreading an empty-object branch.",
  rationale:
    "An empty-object conditional spread hides whether a property is omitted, which differs from assigning undefined.",
  remediation:
    "Construct the object explicitly and add the conditional fields only when the original condition holds, preserving evaluation order and ownership.",
  category: "style",
  limitations: [
    "Reports ternary expressions with an empty object branch directly spread into an object literal. Does not report array or argument spreads, logical spreads, or two nonempty alternatives.",
    "This is an explicit readability policy, not a claim that conditional spreads are incorrect. No autofix: rewriting can affect readonly types, expression placement, property order, getters, and object ownership.",
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
            "declare const includePage: boolean;\nconst query = { limit: 20, ...(includePage ? { page: 1 } : {}) };",
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
            "declare const includePage: boolean;\nconst query: { limit: number; page?: number } = { limit: 20 };\nif (includePage) query.page = 1;",
        },
      ],
      focusPath: "src/example.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function isEmptyObject(node: TSESTree.Expression): boolean {
  return (
    node.type === AST_NODE_TYPES.ObjectExpression &&
    node.properties.length === 0
  );
}

export default createRule<[], "avoid">({
  name: "no-conditional-empty-object-spread",
  documentation: NO_CONDITIONAL_EMPTY_OBJECT_SPREAD_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description: NO_CONDITIONAL_EMPTY_OBJECT_SPREAD_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      avoid:
        "Build conditional fields explicitly instead of spreading an empty object branch. Preserve omission and evaluation order.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    return {
      SpreadElement(node): void {
        if (
          node.parent.type !== AST_NODE_TYPES.ObjectExpression ||
          node.argument.type !== AST_NODE_TYPES.ConditionalExpression
        )
          return;
        if (
          isEmptyObject(node.argument.consequent) ||
          isEmptyObject(node.argument.alternate)
        )
          context.report({ node, messageId: "avoid" });
      },
    };
  },
});

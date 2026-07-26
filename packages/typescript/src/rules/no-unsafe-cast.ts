/**
 * @fileoverview Flag type-safety escape hatches that fully disable checking:
 *   1. `x as any` (and the `<any>x` assertion form) — silences every downstream
 *      error on the value.
 *   2. `x as unknown as T` double-casts — assert through `unknown`/`any` to reach
 *      an unrelated type, bypassing the compiler's structural check.
 *
 * `as const` is exempt — it narrows rather than widens and is the prescribed
 * pattern for literal inference.
 *
 * TEST FILES ARE EXEMPT. Corpus sweep (2220 files across zod / TanStack Query /
 * react-router / swr / zustand, 2026-07): 947 raw hits, 357 of them inside test
 * files, and the test-file ones are a different act entirely. A test asserts on
 * behaviour, not on types: it hands the subject a deliberately partial or
 * deliberately invalid value to drive a branch that a well-typed caller could
 * never reach, and `as any` is how you spell that.
 * `query/packages/preact-query/src/__tests__/HydrationBoundary.test.tsx:401`
 * (`<HydrationBoundary state={{} as any}>`, exercising the empty-state path) and
 * `zustand/tests/devtools.test.tsx` (71 hits, all mock wiring) are
 * representative. "Model the shape" is not advice a fixture can act on, so every
 * one of those reports is noise the author must suppress. The 590 hits in
 * production sources still fire.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import { AST_NODE_TYPES } from "@typescript-eslint/utils";

import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "asAny" | "doubleCast";

function isAnyAnnotation(node: TSESTree.TypeNode): boolean {
  return node.type === AST_NODE_TYPES.TSAnyKeyword;
}

function isConstAssertion(typeAnnotation: TSESTree.TypeNode): boolean {
  return (
    typeAnnotation.type === AST_NODE_TYPES.TSTypeReference &&
    typeAnnotation.typeName.type === AST_NODE_TYPES.Identifier &&
    typeAnnotation.typeName.name === "const"
  );
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<[], MessageIds>({
  name: "no-unsafe-cast",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `as any`/`<any>` casts and `as unknown as T` double-casts, which fully disable type checking.",
    },
    schema: [],
    messages: {
      asAny:
        "`as any` disables type checking on this value. Narrow with a type guard, model the shape, or cast to a specific type instead.",
      doubleCast:
        "`as unknown as T` double-cast bypasses the compiler's structural check. Prefer a runtime validator (e.g. a zod schema) or an accurate type at the boundary.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    function checkAssertion(
      node: TSESTree.TSAsExpression | TSESTree.TSTypeAssertion,
    ): void {
      if (isConstAssertion(node.typeAnnotation)) {
        return;
      }

      if (isAnyAnnotation(node.typeAnnotation)) {
        context.report({ node, messageId: "asAny" });
        return;
      }

      const inner = node.expression;
      if (
        inner.type === AST_NODE_TYPES.TSAsExpression ||
        inner.type === AST_NODE_TYPES.TSTypeAssertion
      ) {
        context.report({ node, messageId: "doubleCast" });
      }
    }

    return {
      TSAsExpression: checkAssertion,
      TSTypeAssertion: checkAssertion,
    };
  },
});

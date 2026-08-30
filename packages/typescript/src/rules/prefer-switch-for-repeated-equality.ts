/**
 * @fileoverview prefer-switch-for-repeated-equality — long equality dispatch chains obscure a finite set of cases.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-switch-for-repeated-equality.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferSwitch";
type Options = [];

export const PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION = {
  summary: "Prefer switch over long if/else-if chains that compare one value for strict equality.",
  rationale: "A switch makes finite dispatch cases visually uniform and easier to extend without duplicating the discriminant.",
  remediation: "Replace three or more strict-equality branches over the same discriminant with a switch; keep if statements for ranges, guards, and heterogeneous predicates.",
  category: "maintainability",
  limitations: [
    "Only direct if/else-if chains with at least three strict-equality tests are reported.",
    "Case values may be literals, enum-like member references, or upper-case named constants; dynamic expressions are excluded.",
    "The rule deliberately ignores compound predicates, loose equality, ranges, and chains that compare different discriminants.",
  ],
  examples: [
    { id: "switch-dispatch", title: "Make finite dispatch explicit", outcome: "no-match", files: [{ path: "src/render.ts", source: "switch (kind) { case 'a': return a(); case 'b': return b(); case 'c': return c(); default: return fallback(); }" }], focusPath: "src/render.ts", expectedCount: 0, public: true },
    { id: "repeated-equality", title: "Avoid repeating the discriminant", outcome: "match", files: [{ path: "src/render.ts", source: "if (kind === 'a') return a(); else if (kind === 'b') return b(); else if (kind === 'c') return c();" }], focusPath: "src/render.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function discriminantText(
  sourceCode: Readonly<{ getText(node: TSESTree.Node): string }>,
  test: TSESTree.Expression,
): string | null {
  if (test.type !== AST_NODE_TYPES.BinaryExpression || test.operator !== "===") return null;
  const leftIsCase = isCaseValue(test.left);
  const rightIsCase = isCaseValue(test.right);
  if (leftIsCase === rightIsCase) return null;
  return sourceCode.getText(leftIsCase ? test.right : test.left);
}

function isCaseValue(node: TSESTree.Expression | TSESTree.PrivateIdentifier): boolean {
  if (node.type === AST_NODE_TYPES.Literal) return true;
  if (node.type === AST_NODE_TYPES.Identifier) return /^[A-Z][A-Z0-9_]*$/u.test(node.name);
  if (node.type !== AST_NODE_TYPES.MemberExpression || node.computed) return false;
  return (
    node.property.type === AST_NODE_TYPES.Identifier &&
    (node.object.type === AST_NODE_TYPES.Identifier || isCaseValue(node.object))
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-switch-for-repeated-equality",
  documentation: PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Prefer switch over long if/else-if chains that compare one value for strict equality." },
    schema: [],
    messages: {
      preferSwitch: "This if/else-if chain repeatedly compares `{{discriminant}}`; use a switch for the finite cases.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      IfStatement(node): void {
        if (node.parent.type === AST_NODE_TYPES.IfStatement && node.parent.alternate === node) return;
        const first = discriminantText(context.sourceCode, node.test);
        if (first === null) return;
        let count = 1;
        let current = node.alternate;
        while (current?.type === AST_NODE_TYPES.IfStatement) {
          if (discriminantText(context.sourceCode, current.test) !== first) return;
          count += 1;
          current = current.alternate;
        }
        if (count >= 3) {
          context.report({ node, messageId: "preferSwitch", data: { discriminant: first } });
        }
      },
    };
  },
});

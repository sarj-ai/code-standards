/**
 * @fileoverview prefer-switch-for-repeated-equality — long equality dispatch chains obscure a finite set of cases.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-switch-for-repeated-equality.test.ts
 */

import type { ESTree } from "@oxlint/plugins";


import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferSwitch";
type Options = [];

export const PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer switch over long if/else-if chains that compare one value for strict equality.",
  rationale: "A switch makes finite dispatch cases visually uniform and easier to extend without duplicating the discriminant.",
  remediation: "Replace three or more strict-equality branches over the same discriminant with a switch; keep if statements for ranges, guards, and heterogeneous predicates.",
  category: "maintainability",
  limitations: [
    "Only direct if/else-if chains with at least three strict-equality tests are reported.",
    "The discriminant must be a bare identifier; calls, getters, indexed reads and other repeatedly evaluated expressions are excluded. Review case-value effects, selector mutation, branch scoping, and break/continue targets when converting manually; this is not an equivalence proof.",
    "Case values may be literals, enum-like member references, or upper-case named constants; dynamic expressions are excluded.",
    "The rule deliberately ignores compound predicates, loose equality, ranges, and chains that compare different discriminants.",
  ],
  examples: [
    { id: "switch-dispatch", title: "Make finite dispatch explicit", outcome: "no-match", files: [{ path: "src/render.ts", source: "switch (kind) { case 'a': return a(); case 'b': return b(); case 'c': return c(); default: return fallback(); }" }], focusPath: "src/render.ts", expectedCount: 0, public: true },
    { id: "repeated-equality", title: "Avoid repeating the discriminant", outcome: "match", files: [{ path: "src/render.ts", source: "if (kind === 'a') return a(); else if (kind === 'b') return b(); else if (kind === 'c') return c();" }], focusPath: "src/render.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function discriminantText(
  sourceCode: Readonly<{ getText(node: ESTree.Node): string }>,
  test: ESTree.Expression,
): string | null {
  if (test.type !== "BinaryExpression" || test.operator !== "===") return null;
  const leftIsCase = isCaseValue(test.left);
  const rightIsCase = isCaseValue(test.right);
  if (leftIsCase === rightIsCase) return null;
  const discriminant = leftIsCase ? test.right : test.left;
  return discriminant.type === "Identifier" ? sourceCode.getText(discriminant) : null;
}

function isCaseValue(node: ESTree.Expression | ESTree.PrivateIdentifier): boolean {
  if (node.type === "Literal") return true;
  if (node.type === "Identifier") return /^[A-Z][A-Z0-9_]*$/u.test(node.name);
  if (node.type !== "MemberExpression" || node.computed) return false;
  return (
    node.property.type === "Identifier" &&
    (node.object.type === "Identifier" || isCaseValue(node.object))
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
        if (node.parent?.type === "IfStatement" && node.parent.alternate === node) return;
        const first = discriminantText(context.sourceCode, node.test);
        if (first === null) return;
        let count = 1;
        let current = node.alternate;
        while (current?.type === "IfStatement") {
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

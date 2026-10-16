/**
 * @fileoverview prefer-switch-for-repeated-equality — long equality dispatch chains obscure a finite set of cases.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-switch-for-repeated-equality.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "preferSwitch";
type Options = [];

export const PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Prefer switch over long if/else-if chains that compare one value for strict equality.",
  rationale: "A switch makes finite dispatch cases visually uniform and easier to extend without duplicating the discriminant.",
  remediation: "Replace three or more strict-equality branches over the same discriminant with a switch; keep if statements for ranges, guards, and heterogeneous predicates.",
  category: "maintainability",
  limitations: [
    "Only direct if/else-if chains with at least three strict-equality tests are reported.",
    "The discriminant must be a resolved lexical variable or parameter; unresolved globals, calls, getters, and indexed reads are excluded. Preserve branch scopes and break/continue targets when converting manually; no autofix is offered.",
    "Case values must be primitive literals. Member references and named constants are excluded because evaluating them can observe getters or mutate the selector. Generated sources are excluded.",
    "The rule deliberately ignores compound predicates, loose equality, ranges, and chains that compare different discriminants.",
  ],
  examples: [
    { id: "switch-dispatch", title: "Make finite dispatch explicit", outcome: "no-match", files: [{ path: "src/render.ts", source: "function render(kind: string) { switch (kind) { case 'a': return 'alpha'; case 'b': return 'beta'; case 'c': return 'gamma'; default: return 'unknown'; } }" }], focusPath: "src/render.ts", expectedCount: 0, public: true },
    { id: "repeated-equality", title: "Avoid repeating the discriminant", outcome: "match", files: [{ path: "src/render.ts", source: "function render(kind: string) { if (kind === 'a') return 'alpha'; else if (kind === 'b') return 'beta'; else if (kind === 'c') return 'gamma'; return 'unknown'; }" }], focusPath: "src/render.ts", expectedCount: 1, public: true },
    { id: "escaped-middle", scenarioId: "native-discriminant", title: "Use native identifier identity", outcome: "match", files: [{ path: "src/dispatch.ts", source: "function probe(kind){if(kind==='a')return 1;else if(\\u006bind==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));" }], focusPath: "src/dispatch.ts", expectedCount: 1, public: true },
    { id: "different-discriminants", scenarioId: "native-discriminant", title: "Use native identifier identity", outcome: "no-match", files: [{ path: "src/dispatch.ts", source: "function probe(kind){const other=\"other\";if(kind==='a')return 1;else if(other==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));" }], focusPath: "src/dispatch.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function discriminantName(
  test: TSESTree.Expression,
): string | null {
  if (test.type !== AST_NODE_TYPES.BinaryExpression || test.operator !== "===") return null;
  const leftIsCase = isCaseValue(test.left);
  const rightIsCase = isCaseValue(test.right);
  if (leftIsCase === rightIsCase) return null;
  const discriminant = leftIsCase ? test.right : test.left;
  return discriminant.type === AST_NODE_TYPES.Identifier ? discriminant.name : null;
}

function isCaseValue(node: TSESTree.Expression | TSESTree.PrivateIdentifier): boolean {
  return node.type === AST_NODE_TYPES.Literal && !("regex" in node);
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
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    return {
      IfStatement(node): void {
        if (node.parent.type === AST_NODE_TYPES.IfStatement && node.parent.alternate === node) return;
        const first = discriminantName(node.test);
        if (first === null) return;
        const binding = ASTUtils.findVariable(context.sourceCode.getScope(node), first);
        if (binding === null || binding.defs.length !== 1 || binding.scope.type === "global") return;
        const [definition] = binding.defs;
        if (definition?.type !== "Parameter" && definition?.type !== "Variable") return;
        let count = 1;
        let current = node.alternate;
        while (current?.type === AST_NODE_TYPES.IfStatement) {
          if (discriminantName(current.test) !== first) return;
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

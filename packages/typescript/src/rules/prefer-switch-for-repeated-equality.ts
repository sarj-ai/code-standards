/**
 * @fileoverview prefer-switch-for-repeated-equality — long equality dispatch chains obscure a finite set of cases.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-switch-for-repeated-equality.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, ESLintUtils, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import ts from "typescript";

import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
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
  autofix: "safe",
  limitations: [
    "Only direct if/else-if chains with at least three strict-equality tests are reported.",
    "The discriminant must be a resolved lexical variable or parameter; unresolved globals, calls, getters, and indexed reads are excluded. Automatic conversion requires terminating compared branches and an explicit final else or type-proven open discriminant, preserving branch scopes and excluding comments, break statements, and function declarations.",
    "Case values must be primitive literals. Member references and named constants are excluded because evaluating them can observe getters or mutate the selector. Generated sources are excluded.",
    "The rule deliberately ignores compound predicates, loose equality, ranges, and chains that compare different discriminants.",
  ],
  examples: [
    { id: "switch-dispatch", title: "Make finite dispatch explicit", outcome: "no-match", files: [{ path: "src/render.ts", source: "function render(kind: string) { switch (kind) { case 'a': return 'alpha'; case 'b': return 'beta'; case 'c': return 'gamma'; default: return 'unknown'; } }" }], focusPath: "src/render.ts", expectedCount: 0, public: true },
    { id: "repeated-equality", title: "Avoid repeating the discriminant", outcome: "match", files: [{ path: "src/render.ts", source: "function render(kind: string) { if (kind === 'a') return 'alpha'; else if (kind === 'b') return 'beta'; else if (kind === 'c') return 'gamma'; return 'unknown'; }" }], focusPath: "src/render.ts", expectedCount: 1, public: true },
    { id: "escaped-middle", scenarioId: "native-discriminant", title: "Use native identifier identity", outcome: "match", files: [{ path: "src/dispatch.ts", source: "function probe(kind){if(kind==='a')return 1;else if(\\u006bind==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));" }], focusPath: "src/dispatch.ts", expectedCount: 1, public: true },
    { id: "different-discriminants", scenarioId: "native-discriminant", title: "Use native identifier identity", outcome: "no-match", files: [{ path: "src/dispatch.ts", source: "function probe(kind){const other=\"other\";if(kind==='a')return 1;else if(other==='b')return 2;else if(kind==='c')return 3;return 0;}\nconsole.log(JSON.stringify([\"a\",\"b\",\"c\",\"d\"].map(probe)));" }], focusPath: "src/dispatch.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "function probe(kind: string) { if (kind === 'a') return 1; else if (kind === 'b') return 2; else if (kind === 'c') return 3; return 0; }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "function probe(kind: string) { switch (kind) {\ncase 'a': { return 1; }\ncase 'b': { return 2; }\ncase 'c': { return 3; }\n} return 0; }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
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

function switchText(node: TSESTree.IfStatement, sourceCode: Readonly<TSESLint.SourceCode>, services: ParserServicesWithTypeInformation | null): string | null {
  if (sourceCode.getCommentsInside(node).length > 0 || hasUnsafeSwitchControl(node)) return null;
  const chain = switchCases(node);
  if (chain === null || (chain.fallback === null && !hasOpenDiscriminant(chain.discriminant, services))) return null;
  const chunks = chain.cases.map(({ value, branch }) =>
    `case ${sourceCode.getText(value)}: ${branch.type === AST_NODE_TYPES.BlockStatement ? sourceCode.getText(branch) : `{ ${sourceCode.getText(branch)} }`}`);
  const fallback = chain.fallback;
  if (fallback !== null) chunks.push(`default: ${fallback.type === AST_NODE_TYPES.BlockStatement ? sourceCode.getText(fallback) : `{ ${sourceCode.getText(fallback)} }`}`);
  return `switch (${sourceCode.getText(chain.discriminant)}) {\n${chunks.join("\n")}\n}`;
}

function switchCases(node: TSESTree.IfStatement) {
  if (node.test.type !== AST_NODE_TYPES.BinaryExpression) return null;
  const discriminant = isCaseValue(node.test.left) ? node.test.right : node.test.left as TSESTree.Expression;
  const cases: { readonly value: TSESTree.Expression | TSESTree.PrivateIdentifier; readonly branch: TSESTree.Statement }[] = [];
  let current = node;
  while (true) {
    if (current.test.type !== AST_NODE_TYPES.BinaryExpression || !terminatesBranch(current.consequent)) return null;
    const test = current.test;
    const value = isCaseValue(test.left) ? test.left : test.right;
    cases.push({ value, branch: current.consequent });
    if (current.alternate?.type !== AST_NODE_TYPES.IfStatement) return { discriminant, cases, fallback: current.alternate };
    current = current.alternate;
  }
}

function terminatesBranch(statement: TSESTree.Statement | undefined): boolean {
  if (statement === undefined) return false;
  if (statement.type === AST_NODE_TYPES.ReturnStatement || statement.type === AST_NODE_TYPES.ThrowStatement ||
    statement.type === AST_NODE_TYPES.ContinueStatement) return true;
  if (statement.type === AST_NODE_TYPES.BlockStatement) return terminatesBranch(statement.body.at(-1));
  return statement.type === AST_NODE_TYPES.IfStatement && statement.alternate !== null &&
    terminatesBranch(statement.consequent) && terminatesBranch(statement.alternate);
}

function hasUnsafeSwitchControl(node: TSESTree.Node): boolean {
  return node.type === AST_NODE_TYPES.BreakStatement || node.type === AST_NODE_TYPES.FunctionDeclaration ||
    forEachOwnAstChild(node, hasUnsafeSwitchControl);
}

function hasOpenDiscriminant(node: TSESTree.Expression, services: ParserServicesWithTypeInformation | null): boolean {
  if (services === null) return false;
  const type = services.program.getTypeChecker().getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node));
  const openFlags = ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.String | ts.TypeFlags.Number | ts.TypeFlags.BigInt | ts.TypeFlags.ESSymbol;
  return (type.isUnion() ? type.types : [type]).some((part) => (part.flags & openFlags) !== 0);
}

export default createRule<Options, MessageIds>({
  name: "prefer-switch-for-repeated-equality",
  documentation: PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: "Prefer switch over long if/else-if chains that compare one value for strict equality." },
    schema: [],
    messages: {
      preferSwitch: "This if/else-if chain repeatedly compares `{{discriminant}}`; use a switch for the finite cases.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    let services: ParserServicesWithTypeInformation | null;
    try { services = ESLintUtils.getParserServices(context); } catch { services = null; }
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
          const replacement = switchText(node, context.sourceCode, services);
          context.report({
            node, messageId: "preferSwitch", data: { discriminant: first },
            fix: replacement === null ? null : (fixer) => fixer.replaceText(node, replacement),
          });
        }
      },
    };
  },
});

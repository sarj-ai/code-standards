/**
 * @fileoverview no-excessive-cognitive-complexity — nested control flow increases the context a reader must retain.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-excessive-cognitive-complexity.test.ts
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { forEachAstChild } from "./_for-each-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type FunctionNode = TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression;
interface ComplexityPoint {
  readonly line: number;
  readonly amount: number;
  readonly construct: string;
}

const ERROR_COMPLEXITY = 20;
const MAX_CONTRIBUTORS = 3;

export const NO_EXCESSIVE_COGNITIVE_COMPLEXITY_DOCUMENTATION = {
  summary: `Report an error for function bodies with cognitive complexity above ${ERROR_COMPLEXITY}.`,
  rationale: "Nested control flow increases the context a reader must retain while following a function.",
  remediation: "Scores up to 20 pass; 21 or more are errors. Examples are fictional; domain types are omitted. Refactor one function at a time, starting with its largest contributors. First simplify control flow and reduce nesting within the function. Extract a helper only when it clarifies a cohesive responsibility or enables meaningful reuse; do not split code solely to lower the score. Use lookup tables only for equivalent pure dispatch. Preserve APIs, side effects, evaluation order, and exception behavior. Run relevant tests before and after; remeasure the original and extracted functions. Do not hide branches in dense expressions or add indirection just to lower a score.",
  category: "maintainability",
  limitations: [
    "Sarj metric, not exact Sonar compatibility: functions and callbacks are independent; calls, recursion, types, parameter defaults, decorators, and class initializers are not scored.",
    "Conditions, loops, catch clauses, switch statements, and conditional expressions add one plus nesting. Else-if and else add one; their bodies add nesting. Each run of like boolean operators adds one.",
    "Nullish coalescing and optional chaining are free. Labeled break/continue add one. Try, finally, return, unlabeled jumps, and await add no points themselves.",
    "Generated code is excluded; authored tests, React components, and all function lengths are checked. The threshold is a shared policy constant, not a correctness boundary.",
  ],
  examples: [
    { id: "nested-decisions", title: "Seven nested decisions exceed the error limit", outcome: "match", files: [{ path: "src/decision.ts", source: "function decide(a, b, c, d, e, f, g) { if (a) { if (b) { if (c) { if (d) { if (e) { if (f) { if (g) { act(); } } } } } } } }" }], focusPath: "src/decision.ts", expectedCount: 1, public: true },
    { id: "guard-decisions", title: "Guard clauses reduce nesting", outcome: "no-match", files: [{ path: "src/decision.ts", source: "function decide(a, b, c, d, e, f, g) { if (!a) return; if (!b) return; if (!c) return; if (!d) return; if (!e) return; if (!f) return; if (!g) return; act(); }" }], focusPath: "src/decision.ts", expectedCount: 0, public: true },
    {"id": "download-check-before", "scenarioId": "download-check", "title": "Synthetic download eligibility: score 21 (error)", "outcome": "match", "files": [{"path": "src/example.ts", "source": "function canDownload(item: Download): boolean {\n  if (item.published) {\n    if (item.licensed) {\n      if (item.available) {\n        if (!item.quarantined) {\n          if (item.bytes > 0) {\n            if (item.bytes <= 1000000) {\n              return true;\n            }\n          }\n        }\n      }\n    }\n  }\n  return false;\n}\n"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "download-check-after", "scenarioId": "download-check", "title": "Use early returns: score 6", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "function canDownload(item: Download): boolean {\n  if (!item.published) return false;\n  if (!item.licensed) return false;\n  if (!item.available) return false;\n  if (item.quarantined) return false;\n  if (!(item.bytes > 0)) return false;\n  if (!(item.bytes <= 1000000)) return false;\n  return true;\n}\n"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "catalog-labels-before", "scenarioId": "catalog-labels", "title": "Synthetic catalog traversal: score 21 (error)", "outcome": "match", "files": [{"path": "src/example.ts", "source": "function collectLabels(catalog: Catalog): string[] {\n  const labels: string[] = [];\n  for (const section of catalog.sections) {\n    for (const shelf of section.shelves) {\n      for (const item of shelf.items) {\n        if (item.visible) {\n          if (item.inStock) {\n            if (item.label !== \"\") {\n              labels.push(item.label);\n            }\n          }\n        }\n      }\n    }\n  }\n  return labels;\n}\n"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "catalog-labels-after", "scenarioId": "catalog-labels", "title": "Extract eligibility: traversal 10; predicate 3", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "function hasDisplayLabel(item: CatalogItem): boolean {\n  if (!item.visible) return false;\n  if (!item.inStock) return false;\n  if (item.label === \"\") return false;\n  return true;\n}\n\nfunction collectLabels(catalog: Catalog): string[] {\n  const labels: string[] = [];\n  for (const section of catalog.sections) {\n    for (const shelf of section.shelves) {\n      for (const item of shelf.items) {\n        if (hasDisplayLabel(item)) labels.push(item.label);\n      }\n    }\n  }\n  return labels;\n}\n"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;

export function functionComplexity(
  fn: FunctionNode,
  visitorKeys: Readonly<TSESLint.SourceCode.VisitorKeys>,
): readonly ComplexityPoint[] {
  const points: ComplexityPoint[] = [];
  function add(node: TSESTree.Node, nesting: number, construct: string): void {
    points.push({ line: node.loc.start.line, amount: nesting + 1, construct });
  }
  function logical(node: TSESTree.LogicalExpression, nesting: number): void {
    let previous: string | undefined;
    function flatten(expression: TSESTree.Node): void {
      if (expression.type !== AST_NODE_TYPES.LogicalExpression || expression.operator === "??") {
        visit(expression, nesting);
        return;
      }
      flatten(expression.left);
      if (previous !== expression.operator) add(expression, 0, expression.operator);
      previous = expression.operator;
      flatten(expression.right);
    }
    flatten(node);
  }
  function conditional(node: TSESTree.IfStatement, nesting: number): void {
    add(node, nesting, "if");
    let branch = node;
    while (true) {
      visit(branch.test, nesting);
      visit(branch.consequent, nesting + 1);
      const alternate = branch.alternate;
      if (alternate?.type === AST_NODE_TYPES.IfStatement) {
        add(alternate, 0, "else if");
        branch = alternate;
      } else {
        if (alternate !== null) {
          add(alternate, 0, "else");
          visit(alternate, nesting + 1);
        }
        return;
      }
    }
  }
  function visit(node: TSESTree.Node, nesting: number): void {
    switch (node.type) {
      case AST_NODE_TYPES.FunctionDeclaration:
      case AST_NODE_TYPES.FunctionExpression:
      case AST_NODE_TYPES.ArrowFunctionExpression:
      case AST_NODE_TYPES.ClassDeclaration:
      case AST_NODE_TYPES.ClassExpression:
        return;
      case AST_NODE_TYPES.IfStatement:
        conditional(node, nesting);
        return;
      case AST_NODE_TYPES.ForStatement:
        add(node, nesting, "loop");
        if (node.init !== null) visit(node.init, nesting);
        if (node.test !== null) visit(node.test, nesting);
        if (node.update !== null) visit(node.update, nesting);
        visit(node.body, nesting + 1);
        return;
      case AST_NODE_TYPES.ForInStatement:
      case AST_NODE_TYPES.ForOfStatement:
        add(node, nesting, "loop");
        visit(node.left, nesting);
        visit(node.right, nesting);
        visit(node.body, nesting + 1);
        return;
      case AST_NODE_TYPES.WhileStatement:
      case AST_NODE_TYPES.DoWhileStatement:
        add(node, nesting, "loop");
        visit(node.test, nesting);
        visit(node.body, nesting + 1);
        return;
      case AST_NODE_TYPES.CatchClause:
        add(node, nesting, "catch");
        visit(node.body, nesting + 1);
        return;
      case AST_NODE_TYPES.SwitchStatement:
        add(node, nesting, "switch");
        visit(node.discriminant, nesting);
        for (const branch of node.cases) visit(branch, nesting + 1);
        return;
      case AST_NODE_TYPES.ConditionalExpression:
        add(node, nesting, "conditional");
        visit(node.test, nesting);
        visit(node.consequent, nesting + 1);
        visit(node.alternate, nesting + 1);
        return;
      case AST_NODE_TYPES.LogicalExpression:
        if (node.operator !== "??") {
          logical(node, nesting);
          return;
        }
        break;
      case AST_NODE_TYPES.BreakStatement:
      case AST_NODE_TYPES.ContinueStatement:
        if (node.label !== null) add(node, 0, "labeled jump");
        return;
    }
    visitChildren(node, nesting);
  }
  function visitChildren(node: TSESTree.Node, nesting: number): void {
    forEachAstChild(node, visitorKeys, child => visit(child, nesting));
  }
  visit(fn.body, 0);
  return points;
}

export default createRule<[], "excessiveComplexity">({
  name: "no-excessive-cognitive-complexity",
  documentation: NO_EXCESSIVE_COGNITIVE_COMPLEXITY_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_EXCESSIVE_COGNITIVE_COMPLEXITY_DOCUMENTATION.summary },
    schema: [],
    messages: {
      excessiveComplexity: "Cognitive complexity {{score}} exceeds {{limit}}. Largest contributors: {{detail}}. Start with the largest contributors: simplify control flow and flatten nesting. Extract a helper only when it clarifies a cohesive responsibility or enables meaningful reuse, never solely to lower the score. Do not hide branches in dense expressions. Preserve behavior and public APIs, run relevant tests before and after, then remeasure.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    function check(node: FunctionNode): void {
      const points = functionComplexity(node, context.sourceCode.visitorKeys);
      const score = points.reduce((sum, point) => sum + point.amount, 0);
      if (score <= ERROR_COMPLEXITY) return;
      const detail = points.toSorted((left, right) => right.amount - left.amount)
        .slice(0, MAX_CONTRIBUTORS)
        .map((point) => `L${point.line} +${point.amount} ${point.construct}`).join("; ");
      context.report({ loc: node.loc.start, messageId: "excessiveComplexity", data: { score, limit: ERROR_COMPLEXITY, detail } });
    }
    return { FunctionDeclaration: check, FunctionExpression: check, ArrowFunctionExpression: check };
  },
});

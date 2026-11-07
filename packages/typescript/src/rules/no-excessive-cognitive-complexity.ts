/**
 * @fileoverview no-excessive-cognitive-complexity — nested control flow increases the context a reader must retain.
 *
 * Port of the 18.x `no-excessive-cognitive-complexity` rule. The rule is
 * untyped, so the port covers all of it. Scoring mirrors the original walk;
 * contributor lines are read only for the reported top contributors.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { forEachAstChild, type VisitorKeys } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";

const NAME = "no-excessive-cognitive-complexity";

type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;

interface ComplexityPoint {
  readonly node: Node;
  readonly amount: number;
  readonly construct: string;
}

type LoopNode = ESTree.ForStatement | ESTree.ForInStatement | ESTree.ForOfStatement | ESTree.WhileStatement | ESTree.DoWhileStatement;

/** Nested functions and classes are scored on their own. */
const SEPARATELY_SCORED: ReadonlySet<string> = new Set([
  "FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression", "ClassDeclaration", "ClassExpression",
]);

const ERROR_COMPLEXITY = 20;
const MAX_CONTRIBUTORS = 3;

/** The loop's header expressions in source order, scored at the loop's own nesting. */
function loopHeader(node: LoopNode): readonly (Node | null)[] {
  switch (node.type) {
    case "ForStatement":
      return [node.init, node.test, node.update];
    case "ForInStatement":
    case "ForOfStatement":
      return [node.left, node.right];
    default:
      return [node.test];
  }
}

/** Score one function body; nested functions and classes are scored on their own. */
function functionComplexity(fn: FunctionNode, visitorKeys: VisitorKeys): readonly ComplexityPoint[] {
  const points: ComplexityPoint[] = [];
  function add(node: Node, nesting: number, construct: string): void {
    points.push({ node, amount: nesting + 1, construct });
  }
  function conditional(node: ESTree.IfStatement, nesting: number): void {
    add(node, nesting, "if");
    let branch = node;
    while (true) {
      visit(branch.test, nesting);
      visit(branch.consequent, nesting + 1);
      const alternate = branch.alternate;
      if (alternate?.type === "IfStatement") {
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
  function visit(node: Node, nesting: number): void {
    if (SEPARATELY_SCORED.has(node.type)) return;
    if (!scoreStatement(node, nesting) && !scoreExpression(node, nesting)) {
      forEachAstChild(node, visitorKeys, (child) => visit(child, nesting));
    }
  }

  /** Score a control-flow statement and its children; false for any other node. */
  function scoreStatement(node: Node, nesting: number): boolean {
    switch (node.type) {
      case "IfStatement":
        conditional(node, nesting);
        return true;
      case "ForStatement":
      case "ForInStatement":
      case "ForOfStatement":
      case "WhileStatement":
      case "DoWhileStatement":
        loop(node, nesting);
        return true;
      case "CatchClause":
        add(node, nesting, "catch");
        visit(node.body, nesting + 1);
        return true;
      case "SwitchStatement":
        add(node, nesting, "switch");
        visit(node.discriminant, nesting);
        for (const branch of node.cases) visit(branch, nesting + 1);
        return true;
      case "BreakStatement":
      case "ContinueStatement":
        if (node.label !== null) add(node, 0, "labeled jump");
        return true;
      default:
        return false;
    }
  }

  /** Score a conditional or a short-circuit chain and its children; false for any other node. */
  function scoreExpression(node: Node, nesting: number): boolean {
    if (node.type === "ConditionalExpression") {
      add(node, nesting, "conditional");
      visit(node.test, nesting);
      visit(node.consequent, nesting + 1);
      visit(node.alternate, nesting + 1);
      return true;
    }
    if (node.type !== "LogicalExpression" || node.operator === "??") return false;
    logical(node, nesting);
    return true;
  }

  function loop(node: LoopNode, nesting: number): void {
    add(node, nesting, "loop");
    for (const header of loopHeader(node)) if (header !== null) visit(header, nesting);
    visit(node.body, nesting + 1);
  }

  function logical(node: ESTree.LogicalExpression, nesting: number): void {
    let previous: string | undefined;
    function flatten(expression: Node): void {
      if (expression.type !== "LogicalExpression" || expression.operator === "??") {
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
  // The parser guarantees a body on every scored function; overload signatures have none.
  if (fn.body !== null) visit(fn.body, 0);
  return points;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: `Report an error for function bodies with cognitive complexity above ${ERROR_COMPLEXITY}.`,
      url: docsUrl(NAME),
    },
    schema: [],
    defaultOptions: [],
    messages: {
      excessiveComplexity: "Cognitive complexity {{score}} exceeds {{limit}}. Largest contributors: {{detail}}. Start with the largest contributors: simplify control flow and flatten nesting. Extract a helper only when it clarifies a cohesive responsibility or enables meaningful reuse, never solely to lower the score. Do not hide branches in dense expressions. Preserve behavior and public APIs, run relevant tests before and after, then remeasure.",
    },
  },
  createOnce(context) {
    function check(node: FunctionNode): void {
      const points = functionComplexity(node, context.sourceCode.visitorKeys);
      let score = 0;
      for (const point of points) score += point.amount;
      if (score <= ERROR_COMPLEXITY) return;
      const detail = points.toSorted((left, right) => right.amount - left.amount)
        .slice(0, MAX_CONTRIBUTORS)
        .map((point) => `L${point.node.loc.start.line} +${point.amount} ${point.construct}`).join("; ");
      context.report({ loc: node.loc.start, messageId: "excessiveComplexity", data: { score, limit: ERROR_COMPLEXITY, detail } });
    }
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      FunctionDeclaration: check,
      FunctionExpression: check,
      ArrowFunctionExpression: check,
    };
  },
});

/**
 * @fileoverview no-string-concat-in-loop — `+=` on a string inside a loop rebuilds the whole string every pass, which is O(n^2).
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-string-concat-in-loop.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";
import type { Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noStringConcatInLoop";
type Options = readonly [];

const LOOP_NODE_TYPES: ReadonlySet<string> = new Set([
  "ForStatement",
  "ForOfStatement",
  "ForInStatement",
  "WhileStatement",
  "DoWhileStatement",
]);

/** Resolves an identifier through its enclosing scopes. */
function findVariable(
  scope: Scope.Scope,
  name: string,
): Scope.Variable | undefined {
  let current: Scope.Scope | null = scope;
  while (current !== null) {
    const variable = current.variables.find((v) => v.name === name);
    if (variable !== undefined) {
      return variable;
    }
    current = current.upper;
  }
  return undefined;
}

/** Requires exactly one variable declaration with a string-literal initializer. */
function isStringInitializedVariable(variable: Scope.Variable): boolean {
  if (variable.defs.length !== 1) {
    return false;
  }
  const def = variable.defs[0];
  if (def === undefined || def.type !== "Variable") {
    return false;
  }
  const declarator = def.node;
  if (declarator.type !== "VariableDeclarator") {
    return false;
  }
  return isStringLiteralInit(declarator.init);
}

/** Checks whether an initializer is a string or template literal. */
function isStringLiteralInit(node: TSESTree.Expression | null): boolean {
  if (node === null) {
    return false;
  }
  if (node.type === "TemplateLiteral") {
    return true;
  }
  if (node.type === "Literal") {
    return typeof node.value === "string";
  }
  return false;
}

/** Recognizes longhand accumulation such as `s = s + x`. */
function isConcatOntoTarget(
  rhs: TSESTree.Expression,
  target: string,
): boolean {
  if (rhs.type === "TemplateLiteral") {
    return rhs.expressions.some(
      (expression) =>
        expression.type === "Identifier" && expression.name === target,
    );
  }
  if (rhs.type !== "BinaryExpression" || rhs.operator !== "+") {
    return false;
  }
  return isConcatOperand(rhs.left, target) || isConcatOperand(rhs.right, target);
}

/** Finds a target identifier in a chained `+` expression. */
function isConcatOperand(
  node: TSESTree.Expression | TSESTree.PrivateIdentifier,
  target: string,
): boolean {
  if (node.type === "Identifier") {
    return node.name === target;
  }
  if (node.type === "BinaryExpression" && node.operator === "+") {
    return (
      isConcatOperand(node.left, target) || isConcatOperand(node.right, target)
    );
  }
  return false;
}

/** Checks whether the loop creates a fresh accumulator on every iteration. */
function isDeclaredInsideLoop(
  variable: Scope.Variable,
  loop: TSESTree.Node,
): boolean {
  const def = variable.defs[0];
  if (def === undefined) {
    return false;
  }
  const body = (
    loop as
      | TSESTree.ForStatement
      | TSESTree.ForOfStatement
      | TSESTree.ForInStatement
      | TSESTree.WhileStatement
      | TSESTree.DoWhileStatement
  ).body;
  const [declStart, declEnd] = def.node.range;
  const [bodyStart, bodyEnd] = body.range;
  return declStart >= bodyStart && declEnd <= bodyEnd;
}

/** Finds the nearest loop whose body contains the assignment. */
function enclosingLoop(node: TSESTree.Node): TSESTree.Node | null {
  let child: TSESTree.Node = node;
  let parent = node.parent;
  while (parent !== undefined && parent !== null) {
    if (LOOP_NODE_TYPES.has(parent.type)) {
      const loop = parent as
        | TSESTree.ForStatement
        | TSESTree.ForOfStatement
        | TSESTree.ForInStatement
        | TSESTree.WhileStatement
        | TSESTree.DoWhileStatement;
      if (loop.body === child) {
        return loop;
      }
    }
    child = parent;
    parent = parent.parent;
  }
  return null;
}

export default createRule<Options, MessageIds>({
  name: "no-string-concat-in-loop",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow O(n^2) string building via `+=` on a string variable inside a loop; push parts to an array and `join` instead.",
    },
    schema: [],
    messages: {
      noStringConcatInLoop:
        "Avoid building a string with `+=` inside a loop — this is O(n^2). Push the parts onto an array and use `arr.join(\"\")` after the loop.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    // Report each accumulator once per loop.
    const reported = new WeakMap<TSESTree.Node, Set<string>>();

    return {
      AssignmentExpression(node: TSESTree.AssignmentExpression): void {
        // The LHS must be a plain variable reference.
        if (node.left.type !== "Identifier") {
          return;
        }
        // Accept both the compound `s += x` and the longhand `s = s + x`; any
        // other operator/shape (`s = x + y`, `s -= x`, ...) is not accumulation.
        const isAccumulation =
          node.operator === "+=" ||
          (node.operator === "=" &&
            isConcatOntoTarget(node.right, node.left.name));
        if (!isAccumulation) {
          return;
        }
        // Must occur inside a loop body, else it's a one-shot append.
        const loop = enclosingLoop(node);
        if (loop === null) {
          return;
        }

        const scope = context.sourceCode.getScope(node);
        const variable = findVariable(scope, node.left.name);
        // Conservative: can't resolve the declaration -> don't flag.
        if (variable === undefined) {
          return;
        }
        if (!isStringInitializedVariable(variable)) {
          return;
        }
        if (isDeclaredInsideLoop(variable, loop)) {
          return;
        }

        let seen = reported.get(loop);
        if (seen === undefined) {
          seen = new Set<string>();
          reported.set(loop, seen);
        }
        if (seen.has(node.left.name)) {
          return;
        }
        seen.add(node.left.name);

        context.report({
          node,
          messageId: "noStringConcatInLoop",
        });
      },
    };
  },
});

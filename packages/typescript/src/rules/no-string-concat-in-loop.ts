/**
 * @fileoverview no-string-concat-in-loop — `+=` on a string inside a loop rebuilds the whole string every pass, which is O(n^2).
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-string-concat-in-loop.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/no-string-concat-in-loop.md
 */

import { type TSESTree } from "@typescript-eslint/utils";
import type { Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noStringConcatInLoop";
type Options = readonly [];

const LOOP_NODE_TYPES = new Set<string>([
  "ForStatement",
  "ForOfStatement",
  "ForInStatement",
  "WhileStatement",
  "DoWhileStatement",
]);

/**
 * Returns true if the given expression node is a string-producing literal:
 * a string `Literal` (`""`, `"..."`, `'...'`) or a `TemplateLiteral`.
 */
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

/**
 * Walk the chain of enclosing scopes to find the variable definition for the
 * given identifier name. Returns the resolved `Variable`, or `undefined` if it
 * cannot be found (e.g. an undeclared global or an out-of-scope reference).
 */
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

/**
 * Returns true if the variable was declared with a string-literal initializer.
 * Conservative: if the variable has no single string-initialized declarator
 * (no init, non-literal init, multiple conflicting declarators), returns false.
 */
function isStringInitializedVariable(variable: Scope.Variable): boolean {
  // A variable can technically have multiple declarators (e.g. via `var`
  // hoisting / redeclaration). Only treat it as string-initialized when there
  // is exactly one declarator and it has a string-literal initializer.
  if (variable.defs.length !== 1) {
    return false;
  }
  const def = variable.defs[0];
  if (def === undefined || def.type !== "Variable") {
    // Parameters, function names, imports, etc. — type unknown, don't flag.
    return false;
  }
  const declarator = def.node;
  if (declarator.type !== "VariableDeclarator") {
    return false;
  }
  return isStringLiteralInit(declarator.init);
}

/**
 * Returns true if `target` appears as a direct operand of a `+` expression
 * (following left-associative `+` chains, e.g. `s + a + b`). Used to recognize
 * the longhand `s = s + <...>` reassignment, which has the same O(n^2) cost as
 * `s += <...>`. A non-`+` operand (`foo.s`, `s.slice()`, `x + y`) does not match.
 */
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

/**
 * Returns true if `rhs` is a `+` `BinaryExpression` in which `target` appears as
 * an operand — the reassignment shape `s = s + x` / `s = x + s` / `s = s + a + b`.
 */
function isConcatOntoTarget(
  rhs: TSESTree.Expression,
  target: string,
): boolean {
  if (rhs.type !== "BinaryExpression" || rhs.operator !== "+") {
    return false;
  }
  return isConcatOperand(rhs.left, target) || isConcatOperand(rhs.right, target);
}

/**
 * Returns true when the accumulator's declaration lives inside `loop`'s BODY, so
 * a fresh string is bound on every iteration.
 *
 * `let s = ""` before the loop is the cross-iteration accumulator this rule
 * targets. `let s = ""` inside the body is not: the `+=` runs a bounded number of
 * times against a string that is discarded at the end of the pass, and there is
 * no quadratic growth to remove — the parts are usually already collected into an
 * array afterwards. Compared by source range, which is exact for a declaration
 * that is lexically nested in the body.
 */
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

/**
 * Returns true if `node` is contained within the body of a loop statement.
 * Walks ancestors and, for each loop, ensures the node is inside the loop's
 * BODY (not its test/init/update clauses, which run a bounded number of times
 * relative to the body and aren't the antipattern we target).
 */
function enclosingLoop(node: TSESTree.Node): TSESTree.Node | null {
  let child: TSESTree.Node = node;
  let parent = node.parent;
  while (parent !== undefined && parent !== null) {
    if (LOOP_NODE_TYPES.has(parent.type)) {
      // `body` is the property that holds the looped statements for every
      // loop variant we care about.
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

    // One defect per (accumulator, loop) — see @fileoverview. Keyed on the loop
    // node so sibling loops over the same variable each keep their report.
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
        // The O(n^2) claim requires the accumulator to SURVIVE across iterations.
        // One declared inside the loop body is a fresh string every pass, so its
        // length is bounded by one iteration's work and `join` cannot replace it.
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

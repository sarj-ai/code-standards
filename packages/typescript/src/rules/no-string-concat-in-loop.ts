/**
 * @fileoverview Disallow string accumulation via `+=` inside a loop, which is
 * the classic O(n^2) string-building antipattern: each `+=` rebuilds the whole
 * string. Push the parts onto an array and `arr.join("")` after the loop
 * instead.
 *
 * This is a purely SYNTACTIC rule — it uses scope analysis (not the type
 * service) to confirm the left-hand side was declared with a string-literal
 * initializer (`let s = ""`, `= "..."`, or a template literal). It is
 * deliberately conservative: when the initializer type cannot be determined
 * (no initializer, a non-literal expression, a parameter, etc.) the `+=` is
 * NOT flagged. This mirrors the Python rule SARJ002.
 *
 * Both the compound `s += x` and the equivalent longhand `s = s + x` (a plain
 * `=` assignment whose RHS is a `+` `BinaryExpression` with the target as one
 * operand) are detected — they have identical O(n^2) behavior. A plain
 * `s = x + y` (target absent from the RHS) is NOT flagged.
 *
 * AT MOST ONE REPORT PER (accumulator, loop). A single loop that appends in
 * several branches is ONE defect with ONE fix — replace the accumulator with an
 * array of parts — so N reports on it are N-1 copies of the same finding, and
 * silencing it costs N disable comments. Corpus sweep (2220 files across zod /
 * TanStack Query / react-router / swr / zustand, 2026-07): 62 raw reports
 * collapsed to 21 distinct defects. `react-router/packages/react-router-fs-routes/flatRoutes.ts`
 * alone produced 23 reports; `react-router/packages/react-router/lib/server-runtime/cookies.ts:221-231`
 * produced 6, all of them the one percent-encoder loop appending `result` from
 * four branches. This matches the one-report-per-loop policy `no-sequential-await`
 * already follows.
 *
 * EXEMPTION — AN ACCUMULATOR DECLARED INSIDE THE LOOP BODY (bulbul PR #4111).
 * The O(n^2) claim requires the accumulator to survive across iterations. A
 * `let s = "..."` declared *inside* the body is rebound to a fresh string every
 * pass, so the `+=` runs a bounded number of times on a string that is discarded
 * at the end of the iteration — there is no quadratic growth for `join` to
 * remove, and the parts are typically already being collected into an array.
 * Evidence:
 * `typescript/packages/app/src/lib/lexical/plugins/utils/serializes-state-to-text.ts:16`,
 * where `let sectionText = \`## ${…}\`` is declared in the body, appended to at
 * most once behind an `if (body)`, and then pushed onto `textParts` for a
 * `textParts.join()` after the loop. The disable there reads "single conditional
 * append to a per-iteration string; result is collected via textParts.join below,
 * not O(n²)" — the rule had nothing to offer.
 *
 * The Python twin SARJ002 (`inefficient_string_concat_in_loop`) has drawn this
 * same line since it shipped: "A target that is freshly (re)bound earlier in the
 * same loop body … is loop-local: it starts empty each iteration, so the growth
 * is bounded, not cross-iteration accumulation." The two rules now agree.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import type { Scope } from "@typescript-eslint/utils/ts-eslint";

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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
        // Only flag when we can confirm the LHS was string-initialized; a
        // numeric initializer (or anything non-string) is intentionally
        // excluded to avoid false positives.
        if (!isStringInitializedVariable(variable)) {
          return;
        }
        // The O(n^2) claim requires the accumulator to SURVIVE across iterations.
        // One declared inside the loop body is a fresh string every pass, so its
        // length is bounded by one iteration's work and `join` cannot replace it.
        // See @fileoverview for the PR #4111 evidence.
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

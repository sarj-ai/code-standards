/**
 * @fileoverview no-conditional-in-test — a conditional that can route around an assertion lets a test pass without checking its claim.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-conditional-in-test.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "noConditionalInTest";
type Options = readonly [];

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);

/** Members whose callbacks define suites or lifecycle work rather than tests. */
const NON_TEST_MEMBERS: ReadonlySet<string> = new Set([
  "afterAll",
  "afterEach",
  "beforeAll",
  "beforeEach",
  "describe",
]);

const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);

/** Roots of assertion calls: `expect(x)`, `assert.ok(x)`, `expectTypeOf<T>()`. */
const ASSERTION_ROOTS: ReadonlySet<string> = new Set([
  "expect",
  "expectTypeOf",
  "assert",
  "assertType",
]);

/** Assertions that exist only in the type system and are erased at run time. */
const TYPE_ASSERTION_ROOTS: ReadonlySet<string> = new Set([
  "expectTypeOf",
  "assertType",
]);

function nearestEnclosingFunction(node: TSESTree.Node): TSESTree.Node | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (FUNCTION_TYPES.has(current.type)) {
      return current;
    }
  }
  return null;
}

/** The base callee name of a call, unwrapping `.only` / `.skip` / `.each` chains. */
function testCallerName(callee: TSESTree.Node): string | null {
  if (callee.type === AST_NODE_TYPES.Identifier) {
    return callee.name;
  }
  if (callee.type === AST_NODE_TYPES.MemberExpression) {
    return testCallerName(callee.object);
  }
  if (callee.type === AST_NODE_TYPES.CallExpression) {
    return testCallerName(callee.callee);
  }
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) {
    return testCallerName(callee.tag);
  }
  return null;
}

/** Return whether any member in a chained callee identifies suite or lifecycle work. */
function hasNonTestMember(callee: TSESTree.Node): boolean {
  if (callee.type === AST_NODE_TYPES.MemberExpression) {
    if (
      !callee.computed &&
      callee.property.type === AST_NODE_TYPES.Identifier &&
      NON_TEST_MEMBERS.has(callee.property.name)
    ) {
      return true;
    }
    return hasNonTestMember(callee.object);
  }
  if (callee.type === AST_NODE_TYPES.CallExpression) {
    return hasNonTestMember(callee.callee);
  }
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) {
    return hasNonTestMember(callee.tag);
  }
  return false;
}

/** True when `fn` is the callback argument of an `it` or `test` call. */
function isTestBody(fn: TSESTree.Node): boolean {
  const call = fn.parent;
  if (
    call?.type !== AST_NODE_TYPES.CallExpression ||
    !call.arguments.some((argument) => argument === fn)
  ) {
    return false;
  }
  if (hasNonTestMember(call.callee)) {
    return false;
  }
  const name = testCallerName(call.callee);
  return name !== null && TEST_CALLERS.has(name);
}

/** Walk `node`'s subtree until `predicate` matches. */
function subtreeMatches(
  node: TSESTree.Node,
  predicate: (current: TSESTree.Node) => boolean,
  descendIntoFunctions = true,
): boolean {
  let found = false;
  const visit = (current: TSESTree.Node): void => {
    if (found) {
      return;
    }
    if (predicate(current)) {
      found = true;
      return;
    }
    for (const key of Object.keys(current)) {
      if (key === "parent") {
        continue;
      }
      if (
        !descendIntoFunctions &&
        FUNCTION_TYPES.has(current.type) &&
        key === "body"
      ) {
        continue;
      }
      const value = (current as unknown as Record<string, unknown>)[key];
      if (Array.isArray(value)) {
        for (const child of value) {
          if (
            typeof child === "object" &&
            child !== null &&
            typeof (child as { type?: unknown }).type === "string"
          ) {
            visit(child as TSESTree.Node);
          }
        }
      } else if (
        typeof value === "object" &&
        value !== null &&
        typeof (value as { type?: unknown }).type === "string"
      ) {
        visit(value as TSESTree.Node);
      }
      if (found) {
        return;
      }
    }
  };
  visit(node);
  return found;
}

/** The leftmost identifier a reference chain is rooted at: `!r.a.b` -> `r`. */
function rootIdentifier(node: TSESTree.Node): string | null {
  switch (node.type) {
    case AST_NODE_TYPES.Identifier:
      return node.name;
    case AST_NODE_TYPES.MemberExpression:
      return rootIdentifier(node.object);
    case AST_NODE_TYPES.UnaryExpression:
      return rootIdentifier(node.argument);
    case AST_NODE_TYPES.AwaitExpression:
      return rootIdentifier(node.argument);
    case AST_NODE_TYPES.ChainExpression:
    case AST_NODE_TYPES.TSNonNullExpression:
    case AST_NODE_TYPES.TSAsExpression:
      return rootIdentifier(node.expression);
    case AST_NODE_TYPES.BinaryExpression:
    case AST_NODE_TYPES.LogicalExpression:
      return rootIdentifier(node.left);
    case AST_NODE_TYPES.CallExpression:
      return rootIdentifier(node.callee);
    default:
      return null;
  }
}

/** The identifier a call is rooted at: `expect(x).not.toBe(y)` -> `expect`. */
function calleeRootName(call: TSESTree.CallExpression): string | null {
  let current: TSESTree.Node = call.callee;
  for (;;) {
    if (current.type === AST_NODE_TYPES.Identifier) {
      return current.name;
    }
    if (current.type === AST_NODE_TYPES.MemberExpression) {
      current = current.object;
      continue;
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      current = current.callee;
      continue;
    }
    if (
      current.type === AST_NODE_TYPES.ChainExpression ||
      current.type === AST_NODE_TYPES.TSNonNullExpression
    ) {
      current = current.expression;
      continue;
    }
    return null;
  }
}

const isAssertionCall = (node: TSESTree.Node): boolean =>
  node.type === AST_NODE_TYPES.CallExpression &&
  ASSERTION_ROOTS.has(calleeRootName(node) ?? "");

const isTypeAssertionCall = (node: TSESTree.Node): boolean =>
  node.type === AST_NODE_TYPES.CallExpression &&
  TYPE_ASSERTION_ROOTS.has(calleeRootName(node) ?? "");

const containsAssertion = (node: TSESTree.Node): boolean =>
  subtreeMatches(node, isAssertionCall);

const containsRuntimeAssertion = (node: TSESTree.Node): boolean =>
  subtreeMatches(
    node,
    (current) => isAssertionCall(current) && !isTypeAssertionCall(current),
  );

/** `test.skip(...)`, `this.skip()`, `ctx.skip()` — an explicit test escape. */
const containsSkipCall = (node: TSESTree.Node): boolean =>
  subtreeMatches(
    node,
    (current) =>
      current.type === AST_NODE_TYPES.CallExpression &&
      current.callee.type === AST_NODE_TYPES.MemberExpression &&
      !current.callee.computed &&
      current.callee.property.type === AST_NODE_TYPES.Identifier &&
      current.callee.property.name === "skip",
  );

/**
 * `return` / `continue` / `break` in the branch's own scope — the ways a branch
 * can cut the rest of the test short. A `return` inside a nested callback does
 * not leave the test, so the walk stops at function boundaries.
 */
const containsEscape = (node: TSESTree.Node): boolean =>
  subtreeMatches(
    node,
    (current) =>
      current.type === AST_NODE_TYPES.ReturnStatement ||
      current.type === AST_NODE_TYPES.ContinueStatement ||
      current.type === AST_NODE_TYPES.BreakStatement ||
      current.type === AST_NODE_TYPES.ThrowStatement,
    false,
  );

/** The statements of a branch, whether or not it is wrapped in a block. */
function branchStatements(
  branch: TSESTree.Statement,
): readonly TSESTree.Statement[] {
  return branch.type === AST_NODE_TYPES.BlockStatement ? branch.body : [branch];
}

/** The statement immediately before `node` among its siblings, if any. */
function previousSibling(node: TSESTree.Statement): TSESTree.Node | null {
  const parent = node.parent;
  let siblings: readonly TSESTree.Node[] | null = null;
  if (
    parent.type === AST_NODE_TYPES.BlockStatement ||
    parent.type === AST_NODE_TYPES.Program ||
    parent.type === AST_NODE_TYPES.StaticBlock
  ) {
    siblings = parent.body;
  } else if (parent.type === AST_NODE_TYPES.SwitchCase) {
    siblings = parent.consequent;
  }
  if (siblings === null) {
    return null;
  }
  const index = siblings.indexOf(node);
  return index > 0 ? (siblings[index - 1] ?? null) : null;
}

/**
 * Guard 1 — a narrowing `if` pinned by the assertion directly above it. The
 * preceding statement must assert on the same value the `if` narrows, so the
 * branch's direction is already established by a check that can fail.
 */
function isPinnedNarrowingGuard(node: TSESTree.IfStatement): boolean {
  const testRoot = rootIdentifier(node.test);
  if (testRoot === null) {
    return false;
  }
  const previous = previousSibling(node);
  if (previous === null || previous.type !== AST_NODE_TYPES.ExpressionStatement) {
    return false;
  }
  let matched = false;
  subtreeMatches(previous, (current) => {
    if (
      current.type !== AST_NODE_TYPES.CallExpression ||
      !ASSERTION_ROOTS.has(calleeRootName(current) ?? "")
    ) {
      return false;
    }
    const subject = current.arguments[0];
    if (subject === undefined) {
      return false;
    }
    if (rootIdentifier(subject) === testRoot) {
      matched = true;
      return true;
    }
    return false;
  });
  return matched;
}

/** Guard 2 — the branch is an assertion spelled as a throw; the test stops here. */
function isThrowingGuard(node: TSESTree.IfStatement): boolean {
  if (node.alternate !== null) {
    return false;
  }
  const statements = branchStatements(node.consequent);
  return (
    statements.length === 1 &&
    statements[0]?.type === AST_NODE_TYPES.ThrowStatement
  );
}

/** Every statement in `branch` is a bare type-level assertion call. */
function isTypeAssertionBranch(branch: TSESTree.Statement): boolean {
  const statements = branchStatements(branch);
  return (
    statements.length > 0 &&
    statements.every(
      (statement) =>
        statement.type === AST_NODE_TYPES.ExpressionStatement &&
        isTypeAssertionCall(statement.expression),
    )
  );
}

/** Guard 4 — narrowing around assertions that are erased at run time. */
function isTypeLevelNarrowing(node: TSESTree.IfStatement): boolean {
  return (
    isTypeAssertionBranch(node.consequent) &&
    (node.alternate === null || isTypeAssertionBranch(node.alternate))
  );
}

/** A branch that asserts nothing and cannot cut the test short. */
const isInertBranch = (branch: TSESTree.Statement): boolean =>
  !containsAssertion(branch) &&
  !containsEscape(branch) &&
  !containsSkipCall(branch);

/**
 * Does the branch only REWRITE state — assign, update, delete, declare?
 *
 * Guard 5 is named "state normalization", and "no assertion and no escape" is a
 * strictly weaker test than that name implies: a branch full of ACTIONS asserts
 * nothing and escapes nothing either, and it is precisely the branch that makes
 * one test take two paths through the UI.
 */
function isNormalizationStatement(statement: TSESTree.Statement): boolean {
  if (statement.type === AST_NODE_TYPES.VariableDeclaration) {
    return true;
  }
  if (statement.type === AST_NODE_TYPES.BlockStatement) {
    return statement.body.every(isNormalizationStatement);
  }
  if (statement.type !== AST_NODE_TYPES.ExpressionStatement) {
    return false;
  }
  const { expression } = statement;
  return (
    expression.type === AST_NODE_TYPES.AssignmentExpression ||
    expression.type === AST_NODE_TYPES.UpdateExpression ||
    (expression.type === AST_NODE_TYPES.UnaryExpression &&
      expression.operator === "delete")
  );
}

/**
 * Guard 5 — state normalization. The branch has no assertion to skip, no way
 * out of the test, and does nothing but rewrite state. Deliberately narrow: a
 * branch that returns, breaks, continues, calls `.skip(`, or DOES something is
 * exactly the defect this rule exists for and is NOT exempt.
 */
function isInertNormalization(node: TSESTree.IfStatement): boolean {
  const branches = [node.consequent, node.alternate].filter(
    (branch): branch is TSESTree.Statement => branch !== null,
  );
  return branches.every(
    (branch) => isInertBranch(branch) && isNormalizationStatement(branch),
  );
}

/**
 * Known-safe structural guards checked before the assertion-skipping predicate.
 */
function isExemptIfStatement(node: TSESTree.IfStatement): boolean {
  return (
    isPinnedNarrowingGuard(node) ||
    isThrowingGuard(node) ||
    isTypeLevelNarrowing(node) ||
    isInertNormalization(node)
  );
}

/** Report only when a branch can actually bypass a runtime assertion or the test. */
function skipsAssertionOrTest(node: TSESTree.IfStatement): boolean {
  const branches = [node.consequent, node.alternate].filter(
    (branch): branch is TSESTree.Statement => branch !== null,
  );
  if (
    branches.some(
      (branch) => containsEscape(branch) || containsSkipCall(branch),
    )
  ) {
    return true;
  }
  const asserted = branches.map(containsRuntimeAssertion);
  return asserted.some(Boolean) &&
    (node.alternate === null || !asserted.every(Boolean));
}

function switchSkipsAssertion(node: TSESTree.SwitchStatement): boolean {
  const asserted = node.cases.map((caseNode) =>
    caseNode.consequent.some(containsRuntimeAssertion),
  );
  if (!asserted.some(Boolean)) return false;
  return node.cases.every((caseNode) => caseNode.test !== null) ||
    !asserted.every(Boolean);
}

function conditionalSkipsAssertion(
  node: TSESTree.ConditionalExpression,
): boolean {
  const consequent = containsRuntimeAssertion(node.consequent);
  const alternate = containsRuntimeAssertion(node.alternate);
  return consequent !== alternate;
}

/**
 * Guard 3 — `??` never reports (it is a default, never control flow over an
 * assertion), and `&&` / `||` report only in the shape that can actually skip an
 * assertion: a bare `a && expect(a).toBe(1);` statement.
 */
function isShortCircuitedAssertion(node: TSESTree.LogicalExpression): boolean {
  return (
    node.operator !== "??" &&
    node.parent.type === AST_NODE_TYPES.ExpressionStatement &&
    containsAssertion(node.right)
  );
}

export default createRule<Options, MessageIds>({
  name: "no-conditional-in-test",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow test conditionals that can skip a runtime assertion or exit the test before one runs.",
    },
    schema: [],
    messages: {
      noConditionalInTest:
        "This conditional can skip a runtime assertion or exit the test before it runs. Make the assertion unconditional or split the test.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename)) {
      return {};
    }
    const report = (node: TSESTree.Node): void => {
      const enclosing = nearestEnclosingFunction(node);
      if (enclosing === null || !isTestBody(enclosing)) {
        return;
      }
      context.report({ node, messageId: "noConditionalInTest" });
    };
    return {
      IfStatement(node: TSESTree.IfStatement): void {
        if (isExemptIfStatement(node) || !skipsAssertionOrTest(node)) {
          return;
        }
        report(node);
      },
      SwitchStatement(node: TSESTree.SwitchStatement): void {
        if (switchSkipsAssertion(node)) report(node);
      },
      ConditionalExpression(node: TSESTree.ConditionalExpression): void {
        if (conditionalSkipsAssertion(node)) report(node);
      },
      LogicalExpression(node: TSESTree.LogicalExpression): void {
        if (!isShortCircuitedAssertion(node)) {
          return;
        }
        report(node);
      },
    };
  },
});

/**
 * @fileoverview Disallow conditional logic in a test body, where it can hide an
 * assertion that never runs.
 *
 * The rule only looks inside the callback of an `it` / `test` call. Conditionals
 * in `describe` bodies, in `beforeEach` / `beforeAll`, and in helper functions
 * declared inside a test are deliberately NOT reported — those are setup and
 * factory code, not the assertion path.
 *
 * ## Measurement
 *
 * A seeded random read of 50 of the rule's 2,344 findings across 17 repositories
 * (6 first-party, plus zod, trpc, dub, openstatus, formbricks, documenso, unkey,
 * midday, papermark, cal.com, hono) put the false-positive rate at 84%. The
 * false positives fell into four shapes, each of which is now exempt. In every
 * one of them the conditional cannot hide an assertion, which is the entire
 * hazard the rule is about.
 *
 *   1. **Narrowing guard pinned by the assertion above it** — 1,097 of 2,344
 *      (46.8%), 22 of the 50 read. `expect(r.success).toBe(false); if (!r.success)
 *      { expect(r.error...) }`. The `if` is a tax paid to the type checker, not a
 *      branch: had the discriminant gone the other way the PRECEDING assertion
 *      would already have failed, so the guarded assertions cannot be silently
 *      skipped. Exempt when the immediately preceding statement is an
 *      `ExpressionStatement` containing an `expect(...)` whose argument has the
 *      same root identifier as the `if` test.
 *      e.g. `zod/packages/zod/src/v4/classic/tests/union.test.ts:32`,
 *      `formbricks/apps/web/modules/api/v2/auth/tests/authenticate-request.test.ts:64`.
 *      Recall cost: the UNPINNED form still fires, and that is the shape worth
 *      firing on — `zod/packages/zod/src/v4/classic/tests/transform.test.ts:80`
 *      guards a `safeParse` result with no assertion above it, so the whole test
 *      passes vacuously when the parse unexpectedly succeeds.
 *
 *   2. **An assertion spelled as a throwing guard** — 223 (9.5%).
 *      `if (!fetcher) throw new Error("fetcher missing")` is a failure, not a
 *      branch: the test cannot continue past it. Exempt when the consequent is
 *      (a block containing only) a `throw` and there is no `else`.
 *      e.g. `openstatus/packages/status-fetcher/__tests__/integration.test.ts:205`,
 *      `hono/src/helper/streaming/sse.test.tsx:381`.
 *
 *   3. **`??` / `||` defaults** — 268 (11.4%). `data.monitors || []`, `code ?? ""`
 *      in fixture construction is a default value, not control flow over an
 *      assertion. `??` no longer reports at all; `&&` / `||` report only when the
 *      logical expression is the whole of an `ExpressionStatement` and its right
 *      operand contains an assertion — i.e. the `a && expect(a).toBe(1)` shape,
 *      which really can skip an assertion.
 *      e.g. `openstatus/apps/server/src/routes/v1/monitor/__tests__/monitor.test.ts:1979`,
 *      `cal.com/apps/web/playwright/oauth-provider.e2e.ts:561`.
 *
 *   4. **Type-level narrowing** — `hono/src/types.test.ts` alone contributes 150,
 *      all `if (res.status === 200) { expectTypeOf(await res.json()).toEqualTypeOf<...>() }`.
 *      `expectTypeOf` / `assertType` are erased at run time, so a branch around
 *      them cannot skip anything that executes. Exempt when every statement in
 *      the consequent is such a call.
 *
 *   5. **State normalization with no assertion and no escape** — 249 (10.6%).
 *      `if (json.error.data.stack) { json.error.data.stack = "[redacted]"; }`
 *      before a snapshot (`trpc/packages/tests/server/adapters/standalone.test.ts:252`).
 *      There is no assertion inside to skip and no way out of the test. Exempt
 *      ONLY when the branch contains neither an assertion nor `return` /
 *      `continue` / `break` / a `.skip(` call.
 *
 * That last carve-out is load-bearing. Without it the rule loses its best true
 * positives, which are exactly the branches that ESCAPE the test:
 * `formbricks/packages/cache/src/cache-integration.test.ts:536`
 * (`if (!isRedisAvailable) { logger.info("Skipping..."); return; }` — the test
 * reports success having asserted nothing) and
 * `cal.com/apps/web/playwright/reschedule.e2e.ts:288`
 * (`if (!locationVideoCallUrl) return;`, which upstream itself annotates
 * `// FIXME: This should be consistent or skip the whole test`). Both are pinned
 * as `invalid` fixtures below, as is the unpinned narrowing guard from (1).
 *
 * Measured over the same corpus after the change: 2,344 -> 359 findings (1,985
 * suppressed, 84.7%). `hono/src/types.test.ts` alone drops from 150 to 0, all of
 * it shape (4). Spot-checked recall on the cited files: the three true positives
 * above still report at exactly those lines, and the five false-positive sites
 * are silent.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "noConditionalInTest";
type Options = readonly [];

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);

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

/** The nearest enclosing function of `node`. */
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

/** True when `fn` is the callback argument of an `it` or `test` call. */
function isTestBody(fn: TSESTree.Node): boolean {
  const call = fn.parent;
  if (
    call?.type !== AST_NODE_TYPES.CallExpression ||
    !call.arguments.some((argument) => argument === fn)
  ) {
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
      current.type === AST_NODE_TYPES.BreakStatement,
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
      current.callee.type !== AST_NODE_TYPES.Identifier ||
      current.callee.name !== "expect"
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
 * Guard 5 — state normalization. The branch has no assertion to skip and no way
 * out of the test, so it cannot hide anything. Deliberately narrow: a branch
 * that returns, breaks, continues, or calls `.skip(` is exactly the true
 * positive this rule exists for and is NOT exempt.
 */
function isInertNormalization(node: TSESTree.IfStatement): boolean {
  return (
    isInertBranch(node.consequent) &&
    (node.alternate === null || isInertBranch(node.alternate))
  );
}

function isExemptIfStatement(node: TSESTree.IfStatement): boolean {
  return (
    isPinnedNarrowingGuard(node) ||
    isThrowingGuard(node) ||
    isTypeLevelNarrowing(node) ||
    isInertNormalization(node)
  );
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-conditional-in-test",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow conditional logic (if, switch, ternary) in test bodies, which can hide missing assertions or test multiple code paths.",
    },
    schema: [],
    messages: {
      noConditionalInTest:
        "Avoid using conditional logic in tests. It can obscure intent and hide unexecuted assertions. Split the test instead.",
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
        if (isExemptIfStatement(node)) {
          return;
        }
        report(node);
      },
      SwitchStatement(node: TSESTree.SwitchStatement): void {
        report(node);
      },
      ConditionalExpression(node: TSESTree.ConditionalExpression): void {
        report(node);
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

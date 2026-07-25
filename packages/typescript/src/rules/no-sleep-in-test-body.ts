/**
 * @fileoverview TS port of SARJ031 (`no-sleep-in-test-body`). A real timed sleep
 * placed directly in a test body — `await new Promise((r) => setTimeout(r, 50))`
 * or `await sleep(200)` — is the canonical flaky-test pattern. The delay is a
 * guess about how long some other work takes: too short and the test fails on a
 * loaded CI runner, too long and every run pays for it. Either way the test is
 * asserting on wall-clock time rather than on the signal it actually cares about.
 *
 * The fix is to synchronize on the signal: await the promise the code returns,
 * await the flushed microtask queue, or drive time deterministically with
 * `vi.useFakeTimers()` + `await vi.advanceTimersByTimeAsync(ms)`, which makes the
 * elapsed time exact and the test instant.
 *
 * Fires only on the exact shape:
 *
 * - `new Promise(...)` whose executor body is a `setTimeout(resolve, <n>)`, or a
 *   call to a bare `sleep`/`delay`/`wait`/`pause` helper, where
 * - the delay is a **nonzero numeric literal** — `setTimeout(r, 0)` is a
 *   macrotask yield used to flush the event loop, not a timing guess, and a
 *   non-literal `sleep(configuredDelay)` is a deliberate parameterised wait, and
 * - the **nearest enclosing function is the callback of an `it`/`test`** (any
 *   `.only`/`.skip`/`.each` variant) or of a `beforeEach`/`afterEach` hook.
 *
 * The nearest-enclosing-function gate is the critical false-positive guard, and
 * it is ported deliberately: a sleep inside a nested helper or fake declared
 * within the test (`const slowFetch = async () => { await sleep(50); ... }`) is
 * *simulating* latency in order to exercise a timeout or cancellation path. That
 * is the intended use of a delay in a test, not a flaky synchronization, and it
 * must not fire. Because the check keys off the nearest enclosing function, such
 * a helper is excluded automatically. The `new Promise` executor arrow is not
 * treated as an enclosing function — it is part of the sleep idiom itself.
 *
 * Applies only in test files.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "noSleepInTestBody";
type Options = readonly [];

/** Free-function sleep helpers. A `sleep(50)` reads as a sleep whatever its module. */
const SLEEP_HELPERS: ReadonlySet<string> = new Set(["sleep", "delay", "wait", "pause"]);

/** Test-case and per-test-hook callers whose callback body is "the test body". */
const TEST_CALLERS: ReadonlySet<string> = new Set([
  "it",
  "test",
  "beforeEach",
  "afterEach",
]);

const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);

/** True for a nonzero numeric literal — the timing guess, as opposed to a `0` yield. */
function isNonzeroNumericLiteral(node: TSESTree.Node | undefined): boolean {
  return node?.type === AST_NODE_TYPES.Literal && typeof node.value === "number" && node.value !== 0;
}

/** True when `node` is `setTimeout(<anything>, <nonzero literal>)`. */
function isTimedSetTimeout(node: TSESTree.Node): boolean {
  return (
    node.type === AST_NODE_TYPES.CallExpression &&
    node.callee.type === AST_NODE_TYPES.Identifier &&
    node.callee.name === "setTimeout" &&
    node.arguments.length >= 2 &&
    isNonzeroNumericLiteral(node.arguments[1])
  );
}

/**
 * True when `node` is `new Promise((r) => setTimeout(r, n))` — including the
 * block-bodied `{ setTimeout(r, n); }` spelling.
 */
function isPromiseSleep(node: TSESTree.NewExpression): boolean {
  if (node.callee.type !== AST_NODE_TYPES.Identifier || node.callee.name !== "Promise") {
    return false;
  }
  const executor = node.arguments[0];
  if (
    executor?.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
    executor?.type !== AST_NODE_TYPES.FunctionExpression
  ) {
    return false;
  }
  const body = executor.body;
  if (body.type !== AST_NODE_TYPES.BlockStatement) {
    return isTimedSetTimeout(body);
  }
  return body.body.some(
    (stmt) => stmt.type === AST_NODE_TYPES.ExpressionStatement && isTimedSetTimeout(stmt.expression),
  );
}

/** True when `node` is `sleep(n)` / `delay(n)` with a nonzero numeric literal. */
function isHelperSleep(node: TSESTree.CallExpression): boolean {
  return (
    node.callee.type === AST_NODE_TYPES.Identifier &&
    SLEEP_HELPERS.has(node.callee.name) &&
    node.arguments.length >= 1 &&
    isNonzeroNumericLiteral(node.arguments[0])
  );
}

/** The nearest enclosing function of `node`, skipping the `new Promise` executor. */
function nearestEnclosingFunction(node: TSESTree.Node): TSESTree.Node | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (!FUNCTION_TYPES.has(current.type)) {
      continue;
    }
    const grandparent = current.parent;
    const isPromiseExecutor =
      grandparent?.type === AST_NODE_TYPES.NewExpression && isPromiseSleep(grandparent);
    if (!isPromiseExecutor) {
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

/** True when `fn` is the callback argument of an `it`/`test`/per-test-hook call. */
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-sleep-in-test-body",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow a fixed timed sleep directly in a test body; it flakes under CI load. Synchronize on the signal or use fake timers.",
    },
    schema: [],
    messages: {
      noSleepInTestBody:
        "A fixed sleep in a test body asserts on wall-clock time and flakes under CI load. Await the promise the code returns, or drive time with `vi.useFakeTimers()` + `await vi.advanceTimersByTimeAsync(ms)`.",
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
      context.report({ node, messageId: "noSleepInTestBody" });
    };
    return {
      NewExpression(node: TSESTree.NewExpression): void {
        if (isPromiseSleep(node)) {
          report(node);
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        if (isHelperSleep(node)) {
          report(node);
        }
      },
    };
  },
});

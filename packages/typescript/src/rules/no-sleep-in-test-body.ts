/**
 * @fileoverview no-sleep-in-test-body — a fixed sleep asserts on wall-clock time rather than on the signal, so the test flakes under CI load.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-sleep-in-test-body.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "noSleepInTestBody";
type Options = readonly [];

export const noSleepInTestBodyDocumentation = {
  summary: "Disallow a fixed timed sleep directly in a test body; it flakes under CI load. Synchronize on the signal or use fake timers.",
  rationale: "Wall-clock delays make test correctness depend on scheduler and machine speed.",
  remediation: "Await the observable signal or advance deterministic fake timers.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only fixed nonzero sleeps directly inside test and per-test hook callbacks are checked; nested fakes and parameterized delays are excluded."],
  examples: [
    { id: "fake-timer", title: "Advance time deterministically", outcome: "no-match", files: [{ path: "src/retry.test.ts", source: "it('retries', async () => { vi.useFakeTimers(); const result = retry(); await vi.advanceTimersByTimeAsync(50); await result; });" }], focusPath: "src/retry.test.ts", expectedCount: 0, public: true },
    { id: "fixed-sleep", title: "Do not wait for wall-clock time", outcome: "match", files: [{ path: "src/retry.test.ts", source: "it('retries', async () => { await sleep(50); expect(done()).toBe(true); });" }], focusPath: "src/retry.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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

/** True when the sleep itself controls the test body rather than serving as injected test data. */
function isImmediatelyConsumedSleep(node: TSESTree.Node): boolean {
  const parent = node.parent;
  if (parent?.type === AST_NODE_TYPES.AwaitExpression ||
      parent?.type === AST_NODE_TYPES.ReturnStatement ||
      parent?.type === AST_NODE_TYPES.ExpressionStatement) {
    return true;
  }
  return parent?.type === AST_NODE_TYPES.ArrowFunctionExpression && parent.body === node;
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

export default createRule<Options, MessageIds>({
  name: "no-sleep-in-test-body",
  documentation: noSleepInTestBodyDocumentation,
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
      if (!isImmediatelyConsumedSleep(node)) {
        return;
      }
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

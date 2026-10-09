/**
 * @fileoverview no-sleep-in-test-body — a fixed sleep asserts on wall-clock time rather than on the signal, so the test flakes under CI load.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-sleep-in-test-body.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { directArgumentCall, outerExpression, unwrapExpression } from "./_unwrap-expression.js";

import { runtimeTestFrameworkName } from "./_test-mock-provenance.js";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "noSleepInTestBody";
type Options = readonly [];

export const NO_SLEEP_IN_TEST_BODY_DOCUMENTATION = {
  summary: "Avoid fixed timed sleeps directly in test bodies; synchronize on observable behavior or use controlled timers.",
  rationale: "Wall-clock delays make test correctness depend on scheduler and machine speed.",
  remediation: "Await the observable signal, or advance fake timers when supported and restore real timers in finally or a teardown hook.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only fixed nonzero sleeps directly inside test and per-test hook callbacks are checked; nested fakes, parameterized delays, local helper bindings, and Promise executors with additional work or rejection callbacks are excluded."],
  examples: [
    { id: "fake-timer", title: "Advance controlled time and restore real timers", outcome: "no-match", files: [{ path: "src/retry.test.ts", source: "it('retries', async () => { vi.useFakeTimers(); try { const result = retry(); await vi.advanceTimersByTimeAsync(50); await result; } finally { vi.useRealTimers(); } });" }], focusPath: "src/retry.test.ts", expectedCount: 0, public: true },
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
  node = node === undefined ? undefined : unwrapExpression(node);
  return node?.type === AST_NODE_TYPES.Literal && typeof node.value === "number" && node.value !== 0;
}

/**
 * True when `node` is `new Promise((r) => setTimeout(r, n))` — including the
 * block-bodied `{ setTimeout(r, n); }` spelling.
 */
function isPromiseSleep(node: TSESTree.NewExpression): boolean {
  const unwrappedNodeCallee = unwrapExpression(node.callee);
  if (unwrappedNodeCallee?.type !== AST_NODE_TYPES.Identifier || unwrappedNodeCallee.name !== "Promise") {
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
  const resolve = executor.params[0];
  if (executor.params.length !== 1 || resolve?.type !== AST_NODE_TYPES.Identifier || resolve.name === "setTimeout") return false;
  const statement = body.type === AST_NODE_TYPES.BlockStatement && body.body.length === 1 ? body.body[0] : null;
  const timer = body.type !== AST_NODE_TYPES.BlockStatement ? body : statement?.type === AST_NODE_TYPES.ExpressionStatement ? statement.expression : null;
  return timer?.type === AST_NODE_TYPES.CallExpression && isTimedSetTimeout(timer) &&
    timer.arguments[0]?.type === AST_NODE_TYPES.Identifier && timer.arguments[0].name === resolve.name;
}

function isTimedSetTimeout(node: TSESTree.Node): boolean {
  const unwrappedNodeCallee = node.type === "CallExpression" || node.type === "NewExpression" ? unwrapExpression(node.callee) : null;
  return (
    node.type === AST_NODE_TYPES.CallExpression &&
    unwrappedNodeCallee?.type === AST_NODE_TYPES.Identifier &&
    unwrappedNodeCallee.name === "setTimeout" &&
    node.arguments.length >= 2 &&
    isNonzeroNumericLiteral(node.arguments[1])
  );
}

/** True when `node` is `sleep(n)` / `delay(n)` with a nonzero numeric literal. */
function isHelperSleep(node: TSESTree.CallExpression): boolean {
  const unwrappedNodeCallee = unwrapExpression(node.callee);
  return (
    unwrappedNodeCallee.type === AST_NODE_TYPES.Identifier &&
    SLEEP_HELPERS.has(unwrappedNodeCallee.name) &&
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
  const parent = outerExpression(node).parent;
  if (parent?.type === AST_NODE_TYPES.AwaitExpression ||
      parent?.type === AST_NODE_TYPES.ReturnStatement ||
      parent?.type === AST_NODE_TYPES.ExpressionStatement) {
    return true;
  }
  return parent?.type === AST_NODE_TYPES.ArrowFunctionExpression && parent.body === node;
}

/** True when `fn` is the callback argument of an `it`/`test`/per-test-hook call. */
function isTestBody(fn: TSESTree.Node, source: Readonly<TSESLint.SourceCode>): boolean {
  const call = directArgumentCall(fn);
  if (call === null) return false;
  const name = testCallerName(call.callee, source);
  return name !== null && TEST_CALLERS.has(name);
}

/** The base callee name of a call, unwrapping `.only` / `.skip` / `.each` chains. */
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["only", "skip", "each", "concurrent", "sequential", "fails", "skipIf", "runIf"]);

function testCallerName(callee: TSESTree.Node, source: Readonly<TSESLint.SourceCode>): string | null {
  callee = unwrapExpression(callee);
  if (callee.type === AST_NODE_TYPES.Identifier) {
    const name = runtimeTestFrameworkName(source, callee, "test");
    return name !== null && TEST_CALLERS.has(name) ? name : null;
  }
  if (callee.type === AST_NODE_TYPES.MemberExpression) {
    const member = ASTUtils.getPropertyName(callee);
    return member !== null && TEST_MODIFIERS.has(member) ? testCallerName(callee.object, source) : null;
  }
  if (callee.type === AST_NODE_TYPES.CallExpression) return testCallerName(callee.callee, source);
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) return testCallerName(callee.tag, source);
  return null;
}

export default createRule<Options, MessageIds>({
  name: "no-sleep-in-test-body",
  documentation: NO_SLEEP_IN_TEST_BODY_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Avoid fixed timed sleeps directly in test bodies; synchronize on observable behavior or use controlled timers.",
    },
    schema: [],
    messages: {
      noSleepInTestBody:
        "A fixed sleep depends on wall-clock timing and can be flaky under load. Await observable completion or use controlled fake timers, restoring real timers afterward.",
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
      if (enclosing === null || !isTestBody(enclosing, context.sourceCode)) {
        return;
      }
      context.report({ node, messageId: "noSleepInTestBody" });
    };
    return {
      NewExpression(node: TSESTree.NewExpression): void {
        if (isPromiseSleep(node)) {
          const constructor = ASTUtils.findVariable(context.sourceCode.getScope(node), "Promise");
          const timer = ASTUtils.findVariable(context.sourceCode.getScope(node), "setTimeout");
          if ((constructor?.defs.length ?? 0) > 0 || (timer?.defs.length ?? 0) > 0) return;
          report(node);
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        if (isHelperSleep(node)) {
          if (unwrappedNodeCallee.type !== AST_NODE_TYPES.Identifier) return;
          const variable = ASTUtils.findVariable(context.sourceCode.getScope(node), unwrappedNodeCallee.name);
          if (variable?.defs.some((definition) => definition.type !== "ImportBinding")) return;
          report(node);
        }
      },
    };
  },
});

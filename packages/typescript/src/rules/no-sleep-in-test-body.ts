/**
 * @fileoverview no-sleep-in-test-body — a fixed sleep asserts on wall-clock time rather than on the signal, so the test flakes under CI load.
 *
 * Port of the 18.x `no-sleep-in-test-body` rule. The rule is untyped,
 * so the port covers all of it.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { directArgumentCall, outerExpression, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { runtimeTestFrameworkName, vitestFixtureTestName } from "../utils/test-mock-provenance.js";

const NAME = "no-sleep-in-test-body";

const SLEEP_HELPERS: ReadonlySet<string> = new Set(["sleep", "delay", "wait", "pause"]);

/** Test-case and per-test-hook callers whose callback body is "the test body". */
const TEST_CALLERS: ReadonlySet<string> = new Set([
  "it",
  "test",
  "beforeEach",
  "afterEach",
]);

const FUNCTION_TYPES: ReadonlySet<string> = new Set([
  "FunctionDeclaration",
  "FunctionExpression",
  "ArrowFunctionExpression",
]);

/** True for a nonzero numeric literal — the timing guess, as opposed to a `0` yield. */
function isNonzeroNumericLiteral(node: Node | undefined): boolean {
  node = node === undefined ? undefined : unwrapExpression(node);
  return node?.type === "Literal" && typeof node.value === "number" && node.value !== 0;
}

/**
 * True when `node` is `new Promise((r) => setTimeout(r, n))` — including the
 * block-bodied `{ setTimeout(r, n); }` spelling.
 */
function isPromiseSleep(node: ESTree.NewExpression): boolean {
  const executor = promiseExecutor(node);
  const body = executor?.body ?? null;
  const resolve = executor?.params[0];
  if (body === null || executor?.params.length !== 1 || resolve?.type !== "Identifier" || resolve.name === "setTimeout") return false;
  const timer = executorTimer(body);
  return timer?.type === "CallExpression" && isTimedSetTimeout(timer) &&
    timer.arguments[0]?.type === "Identifier" && timer.arguments[0].name === resolve.name;
}

/** The inline executor function of `new Promise(executor)`, else null. */
function promiseExecutor(node: ESTree.NewExpression): ESTree.ArrowFunctionExpression | ESTree.Function | null {
  const callee = unwrapExpression(node.callee);
  const executor = node.arguments[0];
  if (callee.type !== "Identifier" || callee.name !== "Promise") return null;
  return executor?.type === "ArrowFunctionExpression" || executor?.type === "FunctionExpression" ? executor : null;
}

/** The executor's only expression: the concise body or a single expression statement. */
function executorTimer(body: Node): Node | null {
  if (body.type !== "BlockStatement") return body;
  const statement = body.body.length === 1 ? body.body[0] : null;
  return statement?.type === "ExpressionStatement" ? statement.expression : null;
}

function isTimedSetTimeout(node: ESTree.CallExpression): boolean {
  const unwrappedNodeCallee = unwrapExpression(node.callee);
  return (
    unwrappedNodeCallee.type === "Identifier" &&
    unwrappedNodeCallee.name === "setTimeout" &&
    node.arguments.length >= 2 &&
    isNonzeroNumericLiteral(node.arguments[1])
  );
}

/** The helper name when `node` is `sleep(n)` / `delay(n)` with a nonzero numeric literal. */
function helperSleepName(node: ESTree.CallExpression): string | null {
  const callee = unwrapExpression(node.callee);
  return callee.type === "Identifier" && SLEEP_HELPERS.has(callee.name) && isNonzeroNumericLiteral(node.arguments[0])
    ? callee.name
    : null;
}

/** The nearest enclosing function of `node`, skipping the `new Promise` executor. */
function nearestEnclosingFunction(node: Node): Node | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (!FUNCTION_TYPES.has(current.type)) {
      continue;
    }
    const grandparent = current.parent;
    const isPromiseExecutor =
      grandparent?.type === "NewExpression" && isPromiseSleep(grandparent);
    if (!isPromiseExecutor) {
      return current;
    }
  }
  return null;
}

/** True when the sleep itself controls the test body rather than serving as injected test data. */
function isImmediatelyConsumedSleep(node: Node): boolean {
  const parent = outerExpression(node).parent;
  if (parent?.type === "AwaitExpression" ||
      parent?.type === "ReturnStatement" ||
      parent?.type === "ExpressionStatement") {
    return true;
  }
  return parent?.type === "ArrowFunctionExpression" && parent.body === node;
}

/** True when `fn` is the callback argument of an `it`/`test`/per-test-hook call. */
function isTestBody(fn: Node, source: Readonly<SourceCode>): boolean {
  const call = directArgumentCall(fn);
  if (call === null) return false;
  return testCallerName(call.callee, source) !== null;
}

/** The base callee name of a call, unwrapping `.only` / `.skip` / `.each` chains. */
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["only", "skip", "each", "for", "concurrent", "sequential", "fails", "skipIf", "runIf"]);

function testCallerName(callee: Node, source: Readonly<SourceCode>): string | null {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") {
    const name = runtimeTestFrameworkName(source, callee, "test") ?? vitestFixtureTestName(source, callee);
    return name !== null && TEST_CALLERS.has(name) ? name : null;
  }
  if (callee.type === "MemberExpression") {
    const member = getPropertyName(callee);
    const receiver = unwrapExpression(callee.object);
    if ((member === "beforeEach" || member === "afterEach") && receiver.type === "Identifier" &&
        vitestFixtureTestName(source, receiver) !== null) return member;
    return member !== null && TEST_MODIFIERS.has(member) ? testCallerName(callee.object, source) : null;
  }
  if (callee.type === "CallExpression") return testCallerName(callee.callee, source);
  if (callee.type === "TaggedTemplateExpression") return testCallerName(callee.tag, source);
  return null;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Avoid fixed timed sleeps directly in test bodies; synchronize on observable behavior or use controlled timers.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noSleepInTestBody:
        "A fixed sleep depends on wall-clock timing and can be flaky under load. Await observable completion or use controlled fake timers, restoring real timers afterward.",
    },
  },
  createOnce(context) {
    const report = (node: Node): void => {
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
      before() {
        if (!isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        return undefined;
      },
      NewExpression(node: ESTree.NewExpression): void {
        if (isPromiseSleep(node)) {
          const scope = context.sourceCode.getScope(node);
          const constructor = findVariable(scope, "Promise");
          const timer = findVariable(scope, "setTimeout");
          if ((constructor?.defs.length ?? 0) > 0 || (timer?.defs.length ?? 0) > 0) return;
          report(node);
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        const helper = helperSleepName(node);
        if (helper === null) return;
        const variable = findVariable(context.sourceCode.getScope(node), helper);
        if (variable?.defs.some((definition) => definition.type !== "ImportBinding")) return;
        report(node);
      },
    };
  },
});

/**
 * @fileoverview no-unsignaled-poll — polling spy state races a deadline instead of awaiting the event that records it.
 *
 * Ported from interfere-inc/landmines `no-unsignaled-poll` (MIT), limited to spy and mock state.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { getPropertyName } from "../utils/static-string.js";
import {
  importedTestMockNamespace,
  isUnshadowedTestMockGlobal,
  runtimeTestFrameworkName,
} from "../utils/test-mock-provenance.js";

const NAME = "no-unsignaled-poll";

const SPY_MATCHERS: ReadonlySet<string> = new Set([
  "toBeCalled", "toBeCalledTimes", "toBeCalledWith", "lastCalledWith", "nthCalledWith",
  "toHaveBeenCalled", "toHaveBeenCalledOnce", "toHaveBeenCalledTimes", "toHaveBeenCalledWith",
  "toHaveBeenCalledExactlyOnceWith", "toHaveBeenLastCalledWith", "toHaveBeenNthCalledWith",
  "toHaveBeenCalledBefore", "toHaveBeenCalledAfter",
  "toReturn", "toReturnTimes", "toReturnWith", "lastReturnedWith", "nthReturnedWith",
  "toHaveReturned", "toHaveReturnedTimes", "toHaveReturnedWith", "toHaveLastReturnedWith", "toHaveNthReturnedWith",
  "toHaveResolved", "toHaveResolvedTimes", "toHaveResolvedWith", "toHaveLastResolvedWith", "toHaveNthResolvedWith",
]);

const MOCK_STATE: ReadonlySet<string> = new Set([
  "calls", "results", "settledResults", "instances", "contexts", "invocationCallOrder", "lastCall",
]);

const POLL_WAITERS: ReadonlySet<string> = new Set(["waitFor", "waitUntil"]);

/** `vi.waitFor`/`vi.waitUntil` on Vitest's namespace, or `expect.poll` on a test framework's `expect`. */
function isPollCall(node: ESTree.CallExpression, source: Readonly<SourceCode>): boolean {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return false;
  const receiver = unwrapExpression(callee.object);
  const method = getPropertyName(callee);
  if (receiver.type !== "Identifier" || method === null) return false;
  if (POLL_WAITERS.has(method)) {
    return importedTestMockNamespace(source, receiver) === "vitest" ||
      receiver.name === "vi" && isUnshadowedTestMockGlobal(source, receiver);
  }
  return method === "poll" && runtimeTestFrameworkName(source, receiver, "assertion") === "expect";
}

/** The poll call whose inline callback is the nearest function around `node`, else null. */
function enclosingPollCallback(node: Node, source: Readonly<SourceCode>): ESTree.CallExpression | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type !== "ArrowFunctionExpression" && current.type !== "FunctionExpression") continue;
    const argument = outerExpression(current);
    const call = parentOf(argument);
    return call?.type === "CallExpression" && call.arguments[0] === argument && isPollCall(call, source) ? call : null;
  }
  return null;
}

/** The call at the root of `expect(x).not.resolves.matcher`. */
function assertionBase(callee: ESTree.MemberExpression): Node {
  let object = unwrapExpression(callee.object);
  while (object.type === "MemberExpression") object = unwrapExpression(object.object);
  return object;
}

/** `expect(x)` or `expect.soft(x)` on a test framework's `expect`. */
function isExpectCall(node: ESTree.CallExpression, source: Readonly<SourceCode>): boolean {
  let callee = unwrapExpression(node.callee);
  if (callee.type === "MemberExpression" && getPropertyName(callee) === "soft") callee = unwrapExpression(callee.object);
  return callee.type === "Identifier" && runtimeTestFrameworkName(source, callee, "assertion") === "expect";
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Await the event a test depends on instead of polling spy or mock state until a deadline.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noUnsignaledPoll:
        "Do not poll spy or mock state until a deadline. Await the operation, or resolve a promise from the test double and await that signal.",
    },
  },
  createOnce(context) {
    const reported = new Set<Node>();
    const report = (poll: ESTree.CallExpression): void => {
      if (reported.has(poll)) return;
      reported.add(poll);
      context.report({ node: poll, messageId: "noUnsignaledPoll" });
    };
    return {
      before() {
        reported.clear();
        if (!isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression") return;
        const matcher = getPropertyName(callee);
        if (matcher === null || !SPY_MATCHERS.has(matcher)) return;
        const base = assertionBase(callee);
        if (base.type !== "CallExpression") return;
        const source = context.sourceCode;
        if (isPollCall(base, source)) {
          report(base);
          return;
        }
        if (!isExpectCall(base, source)) return;
        const poll = enclosingPollCallback(node, source);
        if (poll !== null) report(poll);
      },
      MemberExpression(node: ESTree.MemberExpression): void {
        const property = getPropertyName(node);
        const object = unwrapExpression(node.object);
        if (property === null || !MOCK_STATE.has(property) || object.type !== "MemberExpression" ||
            getPropertyName(object) !== "mock") return;
        const poll = enclosingPollCallback(node, context.sourceCode);
        if (poll !== null) report(poll);
      },
    };
  },
});

/** @fileoverview no-message-origin-string-matching — bind incoming origin checks to actual browser message events. */
import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName, scopedStaticString } from "../utils/static-string.js";

const NAME = "no-message-origin-string-matching";
const GLOBALS: ReadonlySet<string> = new Set(["window", "self", "globalThis"]);
const STRING_MATCHERS: ReadonlySet<string> = new Set(["startsWith", "endsWith", "includes"]);

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Compare incoming browser message origins against exact trusted origins.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      originMatch:
        "A prefix, suffix or substring match does not establish a trusted message origin. Compare exact allowlisted origins, or parse the origin and validate the intended scheme, host and port.",
    },
  },
  createOnce(context) {
    let events: Set<TsVariable>;
    return {
      before(): boolean | void {
        events = new Set();
        if (
          isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)
        )
          return false;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const source = context.sourceCode;
        const event = messageParameter(node, source);
        if (event !== null) events.add(event);
        const callee = unwrapExpression(node.callee);
        if (
          callee.type !== "MemberExpression" ||
          !STRING_MATCHERS.has(getPropertyName(callee) ?? "")
        )
          return;
        const origin = unwrapExpression(callee.object);
        if (origin.type !== "MemberExpression" || getPropertyName(origin) !== "origin") return;
        const receiver = unwrapExpression(origin.object);
        if (receiver.type !== "Identifier") return;
        const binding = findVariable(source.getScope(receiver), receiver.name);
        if (binding !== null && events.has(binding))
          context.report({ node, messageId: "originMatch" });
      },
    };
  },
});

function messageParameter(call: ESTree.CallExpression, source: SourceCode): TsVariable | null {
  const callee = unwrapExpression(call.callee);
  const ambientCall =
    callee.type === "Identifier" && callee.name === "addEventListener" && isAmbient(callee, source);
  const globalCall =
    callee.type === "MemberExpression" &&
    getPropertyName(callee) === "addEventListener" &&
    callee.object.type === "Identifier" &&
    GLOBALS.has(callee.object.name) &&
    isAmbient(callee.object, source);
  const [type, listener] = call.arguments;
  if (
    (!ambientCall && !globalCall) ||
    type === undefined ||
    scopedStaticString(type, source) !== "message" ||
    listener === undefined
  )
    return null;
  const callback = unwrapExpression(listener);
  if (callback.type !== "ArrowFunctionExpression" && callback.type !== "FunctionExpression")
    return null;
  if (callback.body === null) return null;
  const [parameter] = callback.params;
  if (parameter?.type !== "Identifier") return null;
  const binding = findVariable(source.getScope(callback.body), parameter.name);
  return binding?.references.some((reference) => reference.isWrite()) ? null : binding;
}

function isAmbient(node: Node & { name: string }, source: SourceCode): boolean {
  const binding = findVariable(source.getScope(node), node.name);
  return binding === null || binding.defs.length === 0;
}

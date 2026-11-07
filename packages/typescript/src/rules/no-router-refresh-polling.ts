/**
 * @fileoverview no-router-refresh-polling — polling should fetch named data instead of refreshing the whole route.
 *
 * Port of the 18.x `no-router-refresh-polling` rule. Untyped.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { directArgumentCall, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { stableValueBinding } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "no-router-refresh-polling";

type Identifier = Extract<Node, { type: "Identifier" }>;
type Callback = ESTree.ArrowFunctionExpression | ESTree.Function;

function enclosingIntervalCallback(sourceCode: SourceCode, node: Node): Callback | null {
  for (let ancestor = parentOf(node); ancestor !== null; ancestor = parentOf(ancestor)) {
    if (ancestor.type === "FunctionDeclaration") return null;
    if (ancestor.type !== "ArrowFunctionExpression" && ancestor.type !== "FunctionExpression") continue;
    const parent = directArgumentCall(ancestor);
    return parent !== null && parent.arguments[0] === outerExpression(ancestor) &&
      isIntervalCallee(sourceCode, parent.callee) ? ancestor : null;
  }
  return null;
}

function isIntervalCallee(sourceCode: SourceCode, callee: Node): boolean {
  const node = unwrapExpression(callee);
  return node.type === "Identifier" && node.name === "setInterval" &&
      isUnshadowedGlobal(sourceCode, node) ||
    node.type === "MemberExpression" &&
      node.object.type === "Identifier" &&
      (node.object.name === "window" || node.object.name === "globalThis") &&
      isUnshadowedGlobal(sourceCode, node.object) &&
      getPropertyName(node) === "setInterval";
}

function isUnshadowedGlobal(sourceCode: SourceCode, node: Identifier): boolean {
  const variable = findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Do not poll by calling a Next.js router's refresh method from a timer.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { routerRefreshPolling: "Poll the named fetch or server action instead of calling router.refresh() from a timer." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let routerHooks = new Set<TsVariable>();
    let routers = new Set<TsVariable>();
    let reportedCallbacks = new WeakSet<Callback>();

    return {
      before() {
        sourceCode = context.sourceCode;
        routerHooks = new Set();
        routers = new Set();
        reportedCallbacks = new WeakSet();
        const file = { filename: context.filename, cwd: context.cwd };
        return !(isTestFile(file) || isGeneratedFile(file, sourceCode.text));
      },
      ImportDeclaration(node) {
        if (node.source.value !== "next/navigation") return;
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "useRouter") {
            const variable = findVariable(sourceCode.getScope(specifier.local), specifier.local.name);
            if (variable !== null) routerHooks.add(variable);
          }
        }
      },
      VariableDeclarator(node) {
        // A router only counts once its hook import has been seen.
        if (routerHooks.size === 0) return;
        const initializer = node.init === null ? null : unwrapExpression(node.init);
        if (node.id.type === "Identifier" && initializer?.type === "CallExpression") {
          const hookCallee = unwrapExpression(initializer.callee);
          if (hookCallee.type !== "Identifier") return;
          const hook = findVariable(sourceCode.getScope(hookCallee), hookCallee.name);
          const router = findVariable(sourceCode.getScope(node.id), node.id.name);
          if (hook !== null && router !== null && routerHooks.has(hook) && stableValueBinding(router)) routers.add(router);
        }
      },
      CallExpression(node) {
        if (routers.size === 0) return;
        const callee = unwrapExpression(node.callee);
        const receiver = callee.type === "MemberExpression" ? unwrapExpression(callee.object) : callee;
        if (callee.type !== "MemberExpression" || receiver.type !== "Identifier" || getPropertyName(callee) !== "refresh") return;
        const router = findVariable(sourceCode.getScope(receiver), receiver.name);
        if (router === null || !routers.has(router)) return;
        const callback = enclosingIntervalCallback(sourceCode, node);
        if (callback !== null && !reportedCallbacks.has(callback)) {
          reportedCallbacks.add(callback);
          context.report({ node: callback, messageId: "routerRefreshPolling" });
        }
      },
    };
  },
});

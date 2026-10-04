/**
 * @fileoverview no-router-refresh-polling — polling should fetch named data instead of refreshing the whole route.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-router-refresh-polling.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import { nodeAncestors } from "./_scope.js";
import type { ESTree, Scope, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "routerRefreshPolling";
type Options = readonly [];

export const NO_ROUTER_REFRESH_POLLING_DOCUMENTATION = {
  summary: "Do not poll by calling a Next.js router's refresh method from a timer.",
  rationale: "A route refresh refetches and rerenders the whole route on every tick instead of loading the named resource that changed.",
  remediation: "Call the dedicated fetch or server action from the timer and keep the polling interval in a named constant.",
  category: "performance",
  limitations: ["Only router bindings created from next/navigation useRouter and direct setInterval or window.setInterval callbacks are inspected; generated and test files are excluded."],
  examples: [
    { id: "poll-named-action", title: "Poll a named resource", outcome: "no-match", files: [{ path: "src/status.tsx", source: '"use client"; import { useEffect } from "react"; function Status() { useEffect(() => { const timer = setInterval(() => fetchStatus(), POLLING_INTERVAL_MS); return () => clearInterval(timer); }, []); return null; }' }], focusPath: "src/status.tsx", expectedCount: 0, public: true },
    { id: "poll-router-refresh", title: "Do not poll the whole route", outcome: "match", files: [{ path: "src/status.tsx", source: '"use client"; import { useEffect } from "react"; import { useRouter } from "next/navigation"; function Status() { const router = useRouter(); useEffect(() => { const timer = setInterval(() => router.refresh(), POLLING_INTERVAL_MS); return () => clearInterval(timer); }, [router]); return null; }' }], focusPath: "src/status.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function importedName(node: ESTree.ImportSpecifier): string | null {
  return node.imported.type === "Identifier" ? node.imported.name : String(node.imported.value);
}

function enclosingIntervalCallback(
  sourceCode: Readonly<{
    getScope(node: ESTree.Node): Scope;
  }>,
  node: ESTree.Node,
): ESTree.ArrowFunctionExpression | ESTree.Function | null {
  const ancestors = nodeAncestors(node);
  for (let index = ancestors.length - 1; index >= 0; index -= 1) {
    const ancestor = ancestors[index];
    if (ancestor?.type === "FunctionDeclaration") return null;
    if (
      ancestor?.type !== "ArrowFunctionExpression" &&
      ancestor?.type !== "FunctionExpression"
    ) continue;
    const parent = ancestor.parent;
    return parent.type === "CallExpression" && parent.arguments[0] === ancestor &&
      isIntervalCallee(sourceCode, parent.callee) ? ancestor : null;
  }
  return null;
}

function isIntervalCallee(
  sourceCode: Readonly<{ getScope(node: ESTree.Node): Scope }>,
  node: ESTree.Expression,
): boolean {
  return node.type === "Identifier" && node.name === "setInterval" &&
      isUnshadowedGlobal(sourceCode, node) ||
    node.type === "MemberExpression" &&
      !node.computed &&
      node.object.type === "Identifier" &&
      (node.object.name === "window" || node.object.name === "globalThis") &&
      isUnshadowedGlobal(sourceCode, node.object) &&
      node.property.type === "Identifier" &&
      node.property.name === "setInterval";
}

function isUnshadowedGlobal(
  sourceCode: Readonly<{ getScope(node: ESTree.Node): Scope }>,
  node: ESTree.BindingIdentifier,
): boolean {
  const variable = findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

export default createRule<Options, MessageIds>({
  name: "no-router-refresh-polling",
  documentation: NO_ROUTER_REFRESH_POLLING_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Do not poll by calling a Next.js router's refresh method from a timer." },
    schema: [],
    messages: { routerRefreshPolling: "Poll the named fetch or server action instead of calling router.refresh() from a timer." },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(sourceOrigin(context).filename) || isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};
    const routerHooks = new Set<Variable>();
    const routers = new Set<Variable>();
    const reportedCallbacks = new WeakSet<ESTree.ArrowFunctionExpression | ESTree.Function>();

    return {
      ImportDeclaration(node): void {
        if (node.source.value !== "next/navigation") return;
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportSpecifier" && importedName(specifier) === "useRouter") {
            const variable = findVariable(context.sourceCode.getScope(specifier.local), specifier.local.name);
            if (variable !== null) routerHooks.add(variable);
          }
        }
      },
      VariableDeclarator(node): void {
        if (
          node.id.type === "Identifier" &&
          node.init?.type === "CallExpression" &&
          node.init.callee.type === "Identifier"
        ) {
          const hook = findVariable(context.sourceCode.getScope(node.init.callee), node.init.callee.name);
          const router = findVariable(context.sourceCode.getScope(node.id), node.id.name);
          if (hook !== null && router !== null && routerHooks.has(hook)) routers.add(router);
        }
      },
      CallExpression(node): void {
        if (
          node.callee.type !== "MemberExpression" || node.callee.computed ||
          node.callee.object.type !== "Identifier" ||
          node.callee.property.type !== "Identifier" || node.callee.property.name !== "refresh"
        ) return;
        const router = findVariable(
          context.sourceCode.getScope(node.callee.object),
          node.callee.object.name,
        );
        if (router === null || !routers.has(router) || router.references.some((reference) => reference.isWrite() && reference.init !== true)) return;
        const callback = enclosingIntervalCallback(context.sourceCode, node);
        if (callback !== null && !reportedCallbacks.has(callback)) {
          reportedCallbacks.add(callback);
          context.report({ node: callback, messageId: "routerRefreshPolling" });
        }
      },
    };
  },
});

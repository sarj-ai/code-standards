/**
 * @fileoverview no-router-refresh-polling — polling should fetch named data instead of refreshing the whole route.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-router-refresh-polling.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "routerRefreshPolling";
type Options = readonly [];

export const noRouterRefreshPollingDocumentation = {
  summary: "Do not poll by calling a Next.js router's refresh method from a timer.",
  rationale: "A route refresh refetches and rerenders the whole route on every tick instead of loading the named resource that changed.",
  remediation: "Call the dedicated fetch or server action from the timer and keep the polling interval in a named constant.",
  category: "performance",
  limitations: ["Only router bindings created from next/navigation useRouter and direct setInterval or window.setInterval callbacks are inspected; generated and test files are excluded."],
  examples: [
    { id: "poll-named-action", title: "Poll a named action", outcome: "no-match", files: [{ path: "src/status.tsx", source: 'import { useRouter } from "next/navigation"; const router = useRouter(); setInterval(() => fetchStatus(), POLLING_INTERVAL_MS);' }], focusPath: "src/status.tsx", expectedCount: 0, public: true },
    { id: "poll-router-refresh", title: "Do not poll the whole route", outcome: "match", files: [{ path: "src/status.tsx", source: 'import { useRouter } from "next/navigation"; const router = useRouter(); setInterval(() => router.refresh(), POLLING_INTERVAL_MS);' }], focusPath: "src/status.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function importedName(node: TSESTree.ImportSpecifier): string | null {
  return node.imported.type === AST_NODE_TYPES.Identifier ? node.imported.name : String(node.imported.value);
}

function enclosingIntervalCallback(
  sourceCode: Readonly<{
    getAncestors(node: TSESTree.Node): readonly TSESTree.Node[];
    getScope(node: TSESTree.Node): TSESLint.Scope.Scope;
  }>,
  node: TSESTree.Node,
): TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression | null {
  const ancestors = sourceCode.getAncestors(node);
  for (let index = ancestors.length - 1; index >= 0; index -= 1) {
    const ancestor = ancestors[index];
    if (
      ancestor?.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
      ancestor?.type !== AST_NODE_TYPES.FunctionExpression
    ) continue;
    const parent = ancestor.parent;
    return parent.type === AST_NODE_TYPES.CallExpression && parent.arguments[0] === ancestor &&
      isIntervalCallee(sourceCode, parent.callee) ? ancestor : null;
  }
  return null;
}

function isIntervalCallee(
  sourceCode: Readonly<{ getScope(node: TSESTree.Node): TSESLint.Scope.Scope }>,
  node: TSESTree.Expression,
): boolean {
  return node.type === AST_NODE_TYPES.Identifier && node.name === "setInterval" &&
      isUnshadowedGlobal(sourceCode, node) ||
    node.type === AST_NODE_TYPES.MemberExpression &&
      !node.computed &&
      node.object.type === AST_NODE_TYPES.Identifier &&
      (node.object.name === "window" || node.object.name === "globalThis") &&
      isUnshadowedGlobal(sourceCode, node.object) &&
      node.property.type === AST_NODE_TYPES.Identifier &&
      node.property.name === "setInterval";
}

function isUnshadowedGlobal(
  sourceCode: Readonly<{ getScope(node: TSESTree.Node): TSESLint.Scope.Scope }>,
  node: TSESTree.Identifier,
): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

export default createRule<Options, MessageIds>({
  name: "no-router-refresh-polling",
  documentation: noRouterRefreshPollingDocumentation,
  meta: {
    type: "suggestion",
    docs: { description: "Do not poll by calling a Next.js router's refresh method from a timer." },
    schema: [],
    messages: { routerRefreshPolling: "Poll the named fetch or server action instead of calling router.refresh() from a timer." },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const routerHooks = new Set<TSESLint.Scope.Variable>();
    const routers = new Set<TSESLint.Scope.Variable>();
    const reportedCallbacks = new WeakSet<TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression>();

    return {
      ImportDeclaration(node): void {
        if (node.source.value !== "next/navigation") return;
        for (const specifier of node.specifiers) {
          if (specifier.type === AST_NODE_TYPES.ImportSpecifier && importedName(specifier) === "useRouter") {
            const variable = ASTUtils.findVariable(context.sourceCode.getScope(specifier.local), specifier.local.name);
            if (variable !== null) routerHooks.add(variable);
          }
        }
      },
      VariableDeclarator(node): void {
        if (
          node.id.type === AST_NODE_TYPES.Identifier &&
          node.init?.type === AST_NODE_TYPES.CallExpression &&
          node.init.callee.type === AST_NODE_TYPES.Identifier
        ) {
          const hook = ASTUtils.findVariable(context.sourceCode.getScope(node.init.callee), node.init.callee.name);
          const router = ASTUtils.findVariable(context.sourceCode.getScope(node.id), node.id.name);
          if (hook !== null && router !== null && routerHooks.has(hook)) routers.add(router);
        }
      },
      CallExpression(node): void {
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.computed ||
          node.callee.object.type !== AST_NODE_TYPES.Identifier ||
          node.callee.property.type !== AST_NODE_TYPES.Identifier || node.callee.property.name !== "refresh"
        ) return;
        const router = ASTUtils.findVariable(
          context.sourceCode.getScope(node.callee.object),
          node.callee.object.name,
        );
        if (router === null || !routers.has(router)) return;
        const callback = enclosingIntervalCallback(context.sourceCode, node);
        if (callback !== null && !reportedCallbacks.has(callback)) {
          reportedCallbacks.add(callback);
          context.report({ node: callback, messageId: "routerRefreshPolling" });
        }
      },
    };
  },
});

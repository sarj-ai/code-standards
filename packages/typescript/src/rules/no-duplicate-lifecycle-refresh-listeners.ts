/**
 * @fileoverview no-duplicate-lifecycle-refresh-listeners — tab activation must not refresh the same route twice.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-duplicate-lifecycle-refresh-listeners.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "duplicateLifecycleRefresh";
type Options = readonly [];
type LifecycleEvent = "focus" | "visibilitychange";
type ListenerOperation = "add" | "remove";
type CallbackFunction = TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression | TSESTree.FunctionDeclaration;
type Registrations = Partial<Record<LifecycleEvent, TSESTree.CallExpression>>;

export const NO_DUPLICATE_LIFECYCLE_REFRESH_LISTENERS_DOCUMENTATION = {
  summary: "Do not register one Next.js route-refresh callback for both focus and visibilitychange.",
  rationale: "A browser tab activation can emit both lifecycle signals and invoke the same route-wide refresh twice.",
  remediation: "Choose one lifecycle signal or route both signals through an explicitly debounced refresh policy.",
  category: "performance",
  limitations: ["Only active direct window focus and document visibilitychange statements in the same block whose shared identifier callback directly calls refresh on a next/navigation useRouter binding are inspected; matching direct removals are honored, and generated and test files are excluded."],
  examples: [
    { id: "single-lifecycle-signal", title: "Listen to one lifecycle signal", outcome: "no-match", files: [{ path: "src/refresh.ts", source: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener("focus", refresh);' }], focusPath: "src/refresh.ts", expectedCount: 0, public: true },
    { id: "duplicate-lifecycle-signals", title: "Do not duplicate a route refresh", outcome: "match", files: [{ path: "src/refresh.ts", source: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);' }], focusPath: "src/refresh.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function importedName(node: TSESTree.ImportSpecifier): string | null {
  return node.imported.type === AST_NODE_TYPES.Identifier ? node.imported.name : String(node.imported.value);
}

function registration(
  sourceCode: Readonly<{ getScope(node: TSESTree.Node): TSESLint.Scope.Scope }>,
  node: TSESTree.CallExpression,
): { operation: ListenerOperation; event: LifecycleEvent; callback: TSESTree.Identifier } | null {
  if (
    node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.computed ||
    node.callee.object.type !== AST_NODE_TYPES.Identifier ||
    !isUnshadowedGlobal(sourceCode, node.callee.object) ||
    node.callee.property.type !== AST_NODE_TYPES.Identifier ||
    (node.callee.property.name !== "addEventListener" && node.callee.property.name !== "removeEventListener") ||
    node.arguments.length < 2
  ) return null;
  const event = node.arguments[0];
  const callback = node.arguments[1];
  if (event === undefined || callback === undefined) return null;
  if (event.type !== AST_NODE_TYPES.Literal || typeof event.value !== "string" || callback.type !== AST_NODE_TYPES.Identifier) return null;
  const operation = node.callee.property.name === "addEventListener" ? "add" : "remove";
  if (node.callee.object.name === "window" && event.value === "focus") return { operation, event: "focus", callback };
  if (node.callee.object.name === "document" && event.value === "visibilitychange") return { operation, event: "visibilitychange", callback };
  return null;
}

function isUnshadowedGlobal(
  sourceCode: Readonly<{ getScope(node: TSESTree.Node): TSESLint.Scope.Scope }>,
  node: TSESTree.Identifier,
): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function statementContainer(node: TSESTree.CallExpression): TSESTree.Program | TSESTree.BlockStatement | null {
  const statement = node.parent;
  if (statement.type !== AST_NODE_TYPES.ExpressionStatement) return null;
  const container = statement.parent;
  return container.type === AST_NODE_TYPES.Program || container.type === AST_NODE_TYPES.BlockStatement
    ? container
    : null;
}

function enclosingFunction(
  sourceCode: Readonly<{ getAncestors(node: TSESTree.Node): readonly TSESTree.Node[] }>,
  node: TSESTree.Node,
): CallbackFunction | null {
  const ancestors = sourceCode.getAncestors(node);
  for (let index = ancestors.length - 1; index >= 0; index -= 1) {
    const ancestor = ancestors[index];
    if (
      ancestor?.type === AST_NODE_TYPES.ArrowFunctionExpression ||
      ancestor?.type === AST_NODE_TYPES.FunctionExpression ||
      ancestor?.type === AST_NODE_TYPES.FunctionDeclaration
    ) return ancestor;
  }
  return null;
}

export default createRule<Options, MessageIds>({
  name: "no-duplicate-lifecycle-refresh-listeners",
  documentation: NO_DUPLICATE_LIFECYCLE_REFRESH_LISTENERS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Do not register one Next.js route-refresh callback for both focus and visibilitychange." },
    schema: [],
    messages: { duplicateLifecycleRefresh: "This Next.js route-refresh callback handles focus and visibilitychange; tab activation can invoke it twice." },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const routerHooks = new Set<TSESLint.Scope.Variable>();
    const routers = new Set<TSESLint.Scope.Variable>();
    const functionCallbacks = new Map<CallbackFunction, TSESLint.Scope.Variable>();
    const refreshingCallbacks = new Set<TSESLint.Scope.Variable>();
    const registrations = new Map<TSESTree.Node, Map<TSESLint.Scope.Variable, Registrations>>();

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
        if (node.id.type !== AST_NODE_TYPES.Identifier) return;
        const variable = ASTUtils.findVariable(context.sourceCode.getScope(node.id), node.id.name);
        if (variable === null) return;
        if (node.init?.type === AST_NODE_TYPES.ArrowFunctionExpression || node.init?.type === AST_NODE_TYPES.FunctionExpression) {
          functionCallbacks.set(node.init, variable);
        }
        if (node.init?.type !== AST_NODE_TYPES.CallExpression || node.init.callee.type !== AST_NODE_TYPES.Identifier) return;
        const hook = ASTUtils.findVariable(context.sourceCode.getScope(node.init.callee), node.init.callee.name);
        if (hook !== null && routerHooks.has(hook)) routers.add(variable);
      },
      FunctionDeclaration(node): void {
        if (node.id === null) return;
        const variable = ASTUtils.findVariable(context.sourceCode.getScope(node.id), node.id.name);
        if (variable !== null) functionCallbacks.set(node, variable);
      },
      CallExpression(node): void {
        const item = registration(context.sourceCode, node);
        if (item !== null) {
          const callback = ASTUtils.findVariable(context.sourceCode.getScope(item.callback), item.callback.name);
          const container = statementContainer(node);
          if (callback !== null && container !== null) {
            const callbacks = registrations.get(container) ?? new Map<TSESLint.Scope.Variable, Registrations>();
            const events = callbacks.get(callback) ?? {};
            if (item.operation === "add") events[item.event] ??= node;
            else delete events[item.event];
            callbacks.set(callback, events);
            registrations.set(container, callbacks);
          }
        }

        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.computed ||
          node.callee.object.type !== AST_NODE_TYPES.Identifier ||
          node.callee.property.type !== AST_NODE_TYPES.Identifier || node.callee.property.name !== "refresh"
        ) return;
        const router = ASTUtils.findVariable(context.sourceCode.getScope(node.callee.object), node.callee.object.name);
        if (router === null || !routers.has(router)) return;
        const fn = enclosingFunction(context.sourceCode, node);
        if (fn === null) return;
        const callback = functionCallbacks.get(fn);
        if (callback !== undefined) refreshingCallbacks.add(callback);
      },
      "Program:exit"(): void {
        for (const callbacks of registrations.values()) {
          for (const [callback, events] of callbacks) {
            if (!refreshingCallbacks.has(callback) || events.focus === undefined || events.visibilitychange === undefined) continue;
            const focusStart = events.focus.range[0];
            const visibilityStart = events.visibilitychange.range[0];
            context.report({ node: focusStart > visibilityStart ? events.focus : events.visibilitychange, messageId: "duplicateLifecycleRefresh" });
          }
        }
      },
    };
  },
});

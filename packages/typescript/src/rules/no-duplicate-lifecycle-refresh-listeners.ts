/**
 * @fileoverview no-duplicate-lifecycle-refresh-listeners — tab activation must not refresh the same route twice.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-duplicate-lifecycle-refresh-listeners.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import { nodeAncestors } from "./_scope.js";
import type { ESTree, SourceCode, Scope, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "duplicateLifecycleRefresh";
type Options = readonly [];
type LifecycleEvent = "focus" | "visibilitychange";
type ListenerOperation = "add" | "remove";
type CallbackFunction = ESTree.ArrowFunctionExpression | ESTree.Function;
type Registrations = Partial<Record<LifecycleEvent, ESTree.CallExpression>>;

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

function importedName(node: ESTree.ImportSpecifier): string | null {
  return node.imported.type === "Identifier" ? node.imported.name : String(node.imported.value);
}

function registration(
  sourceCode: Readonly<{ getScope(node: ESTree.Node): Scope }>,
  node: ESTree.CallExpression,
): { operation: ListenerOperation; event: LifecycleEvent; callback: ESTree.BindingIdentifier } | null {
  if (
    node.callee.type !== "MemberExpression" || node.callee.computed ||
    node.callee.object.type !== "Identifier" ||
    !isUnshadowedGlobal(sourceCode, node.callee.object) ||
    node.callee.property.type !== "Identifier" ||
    (node.callee.property.name !== "addEventListener" && node.callee.property.name !== "removeEventListener") ||
    node.arguments.length < 2
  ) return null;
  const event = node.arguments[0];
  const callback = node.arguments[1];
  if (event === undefined || callback === undefined) return null;
  if (event.type !== "Literal" || typeof event.value !== "string" || callback.type !== "Identifier") return null;
  const operation = node.callee.property.name === "addEventListener" ? "add" : "remove";
  if (node.callee.object.name === "window" && event.value === "focus") return { operation, event: "focus", callback };
  if (node.callee.object.name === "document" && event.value === "visibilitychange") return { operation, event: "visibilitychange", callback };
  return null;
}

function isUnshadowedGlobal(
  sourceCode: Readonly<{ getScope(node: ESTree.Node): Scope }>,
  node: ESTree.BindingIdentifier,
): boolean {
  const variable = findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function statementContainer(node: ESTree.CallExpression): ESTree.Program | ESTree.BlockStatement | null {
  const statement = node.parent;
  if (statement.type !== "ExpressionStatement") return null;
  const container = statement.parent;
  return container.type === "Program" || container.type === "BlockStatement"
    ? container
    : null;
}

function enclosingFunction(
  _sourceCode: Readonly<SourceCode>,
  node: ESTree.Node,
): CallbackFunction | null {
  const ancestors = nodeAncestors(node);
  for (let index = ancestors.length - 1; index >= 0; index -= 1) {
    const ancestor = ancestors[index];
    if (
      ancestor?.type === "ArrowFunctionExpression" ||
      ancestor?.type === "FunctionExpression" ||
      ancestor?.type === "FunctionDeclaration"
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
    if (isTestFile(sourceOrigin(context).filename) || isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};
    const routerHooks = new Set<Variable>();
    const routers = new Set<Variable>();
    const functionCallbacks = new Map<CallbackFunction, Variable>();
    const refreshingCallbacks = new Set<Variable>();
    const registrations = new Map<ESTree.Node, Map<Variable, Registrations>>();

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
        if (node.id.type !== "Identifier") return;
        const variable = findVariable(context.sourceCode.getScope(node.id), node.id.name);
        if (variable === null || variable.references.some((reference) => reference.isWrite() && !reference.init)) return;
        if (node.init?.type === "ArrowFunctionExpression" || node.init?.type === "FunctionExpression") {
          functionCallbacks.set(node.init, variable);
        }
        if (node.init?.type !== "CallExpression" || node.init.callee.type !== "Identifier") return;
        const hook = findVariable(context.sourceCode.getScope(node.init.callee), node.init.callee.name);
        if (hook !== null && routerHooks.has(hook)) routers.add(variable);
      },
      FunctionDeclaration(node): void {
        if (node.id === null) return;
        const variable = findVariable(context.sourceCode.getScope(node.id), node.id.name);
        if (variable !== null && !variable.references.some((reference) => reference.isWrite() && !reference.init)) functionCallbacks.set(node, variable);
      },
      CallExpression(node): void {
        const item = registration(context.sourceCode, node);
        if (item !== null) {
          const callback = findVariable(context.sourceCode.getScope(item.callback), item.callback.name);
          const container = statementContainer(node);
          if (callback !== null && container !== null) {
            const callbacks = registrations.get(container) ?? new Map<Variable, Registrations>();
            const events = callbacks.get(callback) ?? {};
            if (item.operation === "add") events[item.event] ??= node;
            else delete events[item.event];
            callbacks.set(callback, events);
            registrations.set(container, callbacks);
          }
        }

        if (
          node.callee.type !== "MemberExpression" || node.callee.computed ||
          node.callee.object.type !== "Identifier" ||
          node.callee.property.type !== "Identifier" || node.callee.property.name !== "refresh"
        ) return;
        const router = findVariable(context.sourceCode.getScope(node.callee.object), node.callee.object.name);
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

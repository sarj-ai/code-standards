/**
 * @fileoverview no-duplicate-lifecycle-refresh-listeners — tab activation must not schedule the same refresh twice.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-duplicate-lifecycle-refresh-listeners.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "duplicateLifecycleRefresh";
type Options = readonly [];
type LifecycleEvent = "focus" | "visibilitychange";

export const noDuplicateLifecycleRefreshListenersDocumentation = {
  summary: "Do not register the same callback for both focus and visibilitychange in one scope.",
  rationale: "A browser tab activation emits both lifecycle signals and can duplicate every fetch or server action the shared callback triggers.",
  remediation: "Choose one lifecycle signal or route both signals through an explicitly deduped refresh policy.",
  category: "performance",
  limitations: ["Only direct window focus and document visibilitychange registrations with the same identifier callback in one lexical scope are inspected; generated and test files are excluded."],
  examples: [
    { id: "single-lifecycle-signal", title: "Listen to one lifecycle signal", outcome: "no-match", files: [{ path: "src/refresh.ts", source: 'window.addEventListener("focus", refresh);' }], focusPath: "src/refresh.ts", expectedCount: 0, public: true },
    { id: "duplicate-lifecycle-signals", title: "Do not duplicate a refresh", outcome: "match", files: [{ path: "src/refresh.ts", source: 'window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);' }], focusPath: "src/refresh.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function registration(node: TSESTree.CallExpression): { event: LifecycleEvent; callback: TSESTree.Identifier } | null {
  if (
    node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.computed ||
    node.callee.object.type !== AST_NODE_TYPES.Identifier ||
    node.callee.property.type !== AST_NODE_TYPES.Identifier ||
    node.callee.property.name !== "addEventListener" ||
    node.arguments.length < 2
  ) return null;
  const event = node.arguments[0];
  const callback = node.arguments[1];
  if (event === undefined || callback === undefined) return null;
  if (event.type !== AST_NODE_TYPES.Literal || typeof event.value !== "string" || callback.type !== AST_NODE_TYPES.Identifier) return null;
  if (node.callee.object.name === "window" && event.value === "focus") return { event: "focus", callback };
  if (node.callee.object.name === "document" && event.value === "visibilitychange") return { event: "visibilitychange", callback };
  return null;
}

function lexicalOwner(sourceCode: Readonly<{ getAncestors(node: TSESTree.Node): readonly TSESTree.Node[] }>, node: TSESTree.Node): TSESTree.Node {
  const ancestors = sourceCode.getAncestors(node);
  for (let index = ancestors.length - 1; index >= 0; index -= 1) {
    const ancestor = ancestors[index];
    if (
      ancestor !== undefined &&
      (ancestor.type === AST_NODE_TYPES.Program || ancestor.type === AST_NODE_TYPES.FunctionDeclaration ||
        ancestor.type === AST_NODE_TYPES.FunctionExpression || ancestor.type === AST_NODE_TYPES.ArrowFunctionExpression)
    ) return ancestor;
  }
  return node;
}

export default createRule<Options, MessageIds>({
  name: "no-duplicate-lifecycle-refresh-listeners",
  documentation: noDuplicateLifecycleRefreshListenersDocumentation,
  meta: {
    type: "suggestion",
    docs: { description: "Do not register the same callback for both focus and visibilitychange in one scope." },
    schema: [],
    messages: { duplicateLifecycleRefresh: "The same callback handles focus and visibilitychange in this scope; tab activation can invoke it twice." },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const seen = new Map<TSESTree.Node, Map<TSESLint.Scope.Variable | string, LifecycleEvent>>();
    return {
      CallExpression(node): void {
        const item = registration(node);
        if (item === null) return;
        const owner = lexicalOwner(context.sourceCode, node);
        const callbacks = seen.get(owner) ?? new Map<TSESLint.Scope.Variable | string, LifecycleEvent>();
        const variable = ASTUtils.findVariable(
          context.sourceCode.getScope(item.callback),
          item.callback.name,
        );
        const key = variable ?? item.callback.name;
        const previous = callbacks.get(key);
        if (previous !== undefined && previous !== item.event) {
          context.report({ node, messageId: "duplicateLifecycleRefresh" });
          return;
        }
        callbacks.set(key, item.event);
        seen.set(owner, callbacks);
      },
    };
  },
});

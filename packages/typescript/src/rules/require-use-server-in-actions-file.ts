/**
 * @fileoverview require-use-server-in-actions-file — route action modules must establish the server boundary.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/require-use-server-in-actions-file.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "requireUseServerInActionsFile";
type Options = readonly [];

const ACTION_MODULE_RE = /(?:^|\/)app\/.*\/(?:actions|[^/]+-actions)\.[cm]?[jt]s$/u;

export const requireUseServerInActionsFileDocumentation = {
  summary: "route action module missing the use server directive",
  rationale:
    "An exported async function is not callable as a Server Action merely because its file is named actions.ts. Without the module directive, a client import can fail or pull server-only implementation details across the client boundary.",
  remediation: "Put 'use server' at the start of the route action module.",
  category: "correctness",
  limitations: [
    "Only exported async functions in actions.ts or *-actions.ts below an app directory are checked; other naming schemes and inline Server Actions are intentionally outside the rule.",
  ],
  examples: [
    {
      id: "server-action-module",
      title: "Mark the action module as server-only",
      outcome: "no-match",
      files: [{ path: "app/orders/actions.ts", source: "'use server';\nexport async function cancelOrder() {}\n" }],
      focusPath: "app/orders/actions.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "unmarked-action-module",
      title: "Do not rely on the filename to create a Server Action",
      outcome: "match",
      files: [{ path: "app/orders/actions.ts", source: "export async function cancelOrder() {}\n" }],
      focusPath: "app/orders/actions.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function isExportedAsyncFunction(node: TSESTree.ExportNamedDeclaration): boolean {
  const declaration = node.declaration;
  if (declaration?.type === "FunctionDeclaration") return declaration.async;
  return (
    declaration?.type === "VariableDeclaration" &&
    declaration.declarations.some((item) =>
      item.init?.type === "ArrowFunctionExpression" || item.init?.type === "FunctionExpression" ? item.init.async : false,
    )
  );
}

export default createRule<Options, MessageIds>({
  name: "require-use-server-in-actions-file",
  documentation: requireUseServerInActionsFileDocumentation,
  meta: {
    type: "problem",
    docs: { description: requireUseServerInActionsFileDocumentation.summary },
    schema: [],
    messages: {
      requireUseServerInActionsFile:
        "This route action module exports an async function but is missing a leading 'use server' directive.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      Program(node): void {
        const filename = context.filename.replaceAll("\\", "/");
        if (!ACTION_MODULE_RE.test(filename)) return;
        if (node.body.some((statement) => statement.type === "ExpressionStatement" && statement.directive === "use server")) return;
        const exportedAction = node.body.find(
          (statement): statement is TSESTree.ExportNamedDeclaration =>
            statement.type === "ExportNamedDeclaration" && isExportedAsyncFunction(statement),
        );
        if (exportedAction) context.report({ node: exportedAction, messageId: "requireUseServerInActionsFile" });
      },
    };
  },
});

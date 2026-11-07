/**
 * @fileoverview require-use-server-in-actions-file — route action modules must establish the server boundary.
 *
 * Port of the 18.x `require-use-server-in-actions-file` rule. Same
 * algorithm; the action-module filename gate runs in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-use-server-in-actions-file.test.ts
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "require-use-server-in-actions-file";
const ACTION_MODULE_RE = /(?:^|\/)app\/.*\/(?:actions|[^/]+-actions)\.[cm]?[jt]s$/u;

type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;

function isUseServerDirective(statement: Node): boolean {
  return statement.type === "ExpressionStatement" && statement.directive === "use server";
}

function unmarked(fn: FunctionNode): boolean {
  const body = fn.body as Node | null;
  return fn.async && !(body?.type === "BlockStatement" && (body.body as readonly Node[]).some(isUseServerDirective));
}

function isExportedAsyncFunction(node: ESTree.ExportNamedDeclaration): boolean {
  const declaration = node.declaration;
  if (declaration?.type === "FunctionDeclaration") return unmarked(declaration);
  return (
    declaration?.type === "VariableDeclaration" &&
    declaration.declarations.some((item) =>
      item.init?.type === "ArrowFunctionExpression" || item.init?.type === "FunctionExpression" ? unmarked(item.init) : false,
    )
  );
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "route action module missing the use server directive",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      requireUseServerInActionsFile:
        "This route action module exports an async function but is missing a leading 'use server' directive.",
    },
  },
  createOnce(context) {
    return {
      before() {
        if (!ACTION_MODULE_RE.test(context.filename.replaceAll("\\", "/"))) return false;
        return undefined;
      },
      Program(node) {
        const body = node.body as readonly Node[];
        if (body.some(isUseServerDirective)) return;
        const exportedAction = body.find(
          (statement) => statement.type === "ExportNamedDeclaration" && isExportedAsyncFunction(statement),
        );
        if (exportedAction) context.report({ node: exportedAction, messageId: "requireUseServerInActionsFile" });
      },
    };
  },
});

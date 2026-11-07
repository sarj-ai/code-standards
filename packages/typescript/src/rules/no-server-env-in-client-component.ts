/**
 * @fileoverview no-server-env-in-client-component — client bundles cannot read server-only settings.
 *
 * Port of the 18.x `no-server-env-in-client-component` rule; the
 * client-module flag is set per file in `Program`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-server-env-in-client-component.test.ts
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";

const SERVER_ENV_MODULE_RE = /(?:^|\/)(?:server-env|server-settings)(?:\.[cm]?[jt]sx?)?$/;

function isClientModule(program: ESTree.Program): boolean {
  return program.body.some(
    (statement) => statement.type === "ExpressionStatement" && statement.directive === "use client",
  );
}

function isTypeOnlyImport(node: ESTree.ImportDeclaration): boolean {
  return (
    node.importKind === "type" ||
    (node.specifiers.length > 0 &&
      node.specifiers.every(
        (specifier) => specifier.type === "ImportSpecifier" && specifier.importKind === "type",
      ))
  );
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "server-only environment settings imported by a client component",
      url: docsUrl("no-server-env-in-client-component"),
    },
    schema: [],
    messages: {
      noServerEnvInClientComponent:
        "A 'use client' module cannot import server-only settings. Pass public data from a Server Component or use a validated client-settings module.",
    },
  },
  createOnce(context) {
    let clientModule = false;
    return {
      Program(node: ESTree.Program): void {
        clientModule = isClientModule(node);
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (
          clientModule &&
          !isTypeOnlyImport(node) &&
          SERVER_ENV_MODULE_RE.test(node.source.value)
        ) {
          context.report({ node, messageId: "noServerEnvInClientComponent" });
        }
      },
    };
  },
});

/**
 * @fileoverview no-server-env-in-client-component — client bundles cannot import or re-export server-only settings.
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

type ModuleDependency =
  | ESTree.ImportDeclaration
  | ESTree.ExportNamedDeclaration
  | ESTree.ExportAllDeclaration;

function isTypeOnlyExport(
  node: ESTree.ExportNamedDeclaration | ESTree.ExportAllDeclaration,
): boolean {
  return (
    node.exportKind === "type" ||
    (node.type === "ExportNamedDeclaration" &&
      node.specifiers.length > 0 &&
      node.specifiers.every((specifier) => specifier.exportKind === "type"))
  );
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "server-only environment settings imported or re-exported by a client module",
      url: docsUrl("no-server-env-in-client-component"),
    },
    schema: [],
    messages: {
      noServerEnvInClientComponent:
        "Do not import or re-export server-only settings from a 'use client' module; use validated client settings.",
    },
  },
  createOnce(context) {
    let clientModule = false;

    function checkDependency(node: ModuleDependency): void {
      if (!clientModule || node.source === null) return;
      const typeOnly =
        node.type === "ImportDeclaration" ? isTypeOnlyImport(node) : isTypeOnlyExport(node);
      if (!typeOnly && SERVER_ENV_MODULE_RE.test(node.source.value)) {
        context.report({ node, messageId: "noServerEnvInClientComponent" });
      }
    }

    return {
      Program(node: ESTree.Program): void {
        clientModule = isClientModule(node);
      },
      ImportDeclaration: checkDependency,
      ExportNamedDeclaration: checkDependency,
      ExportAllDeclaration: checkDependency,
    };
  },
});

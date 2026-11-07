/**
 * @fileoverview no-server-file-uploads — keep native File handling on the client.
 *
 * Port of the 18.x `no-server-file-uploads` rule. The rule is untyped,
 * so the port covers all of it. Module-level facts (server boundary, File
 * aliases) are computed in `before()`.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { findVariable, staticPropertyName } from "../utils/static-string.js";

const NAME = "no-server-file-uploads";

type Identifier = ESTree.IdentifierReference | ESTree.BindingIdentifier | ESTree.IdentifierName;

function hasDirective(statements: readonly ESTree.Program["body"][number][], directive: string): boolean {
  for (const statement of statements) {
    // The directive prologue ends at the first statement that is not a directive.
    if (statement.type !== "ExpressionStatement" || typeof statement.directive !== "string") return false;
    if (statement.directive === directive) return true;
  }
  return false;
}

function isValueSpecifier(specifier: ESTree.ImportDeclarationSpecifier): boolean {
  return specifier.type !== "ImportSpecifier" || specifier.importKind !== "type";
}

function serverImport(statement: ESTree.Program["body"][number]): boolean {
  if (statement.type !== "ImportDeclaration" || statement.importKind === "type") return false;
  const source = statement.source.value;
  if (source === "server-only") return statement.specifiers.length === 0 || statement.specifiers.some(isValueSpecifier);
  if (source === "next/server") return statement.specifiers.some(isValueSpecifier);
  return statement.specifiers.some((specifier) => {
    if (specifier.type !== "ImportSpecifier" || specifier.importKind === "type") return false;
    const name = importSpecifierName(specifier);
    return (source === "hono" && name === "Hono") || (source === "@hono/zod-openapi" && name === "OpenAPIHono");
  });
}

function isBufferImport(node: ESTree.ImportDeclaration): boolean {
  return node.source.value === "node:buffer" || node.source.value === "buffer";
}

export default defineRule({
  meta: {
    type: "problem",
    docs: { description: "Keep native File handling outside explicit server boundaries.", url: docsUrl(NAME) },
    schema: [],
    messages: { serverFile: "Keep File handling in the browser and upload directly to object storage with an authorized signed URL; accept object keys and metadata on the server." },
  },
  createOnce(context) {
    let mayReferenceFile = false;
    let moduleServer = false;
    const fileNames = new Set<string>();

    function inServer(node: Node): boolean {
      if (moduleServer) return true;
      for (let ancestor = parentOf(node); ancestor !== null; ancestor = parentOf(ancestor)) {
        if ((ancestor.type === "FunctionDeclaration" || ancestor.type === "FunctionExpression" || ancestor.type === "ArrowFunctionExpression") &&
          ancestor.body?.type === "BlockStatement" && hasDirective(ancestor.body.body, "use server")) return true;
      }
      return false;
    }

    function nativeFile(identifier: Identifier): boolean {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      if (variable === null || variable.defs.length === 0) return identifier.name === "File";
      return variable.defs.length === 1 && variable.defs.some((definition) => {
        if (definition.type !== "ImportBinding" || definition.parent?.type !== "ImportDeclaration" || !isBufferImport(definition.parent)) return false;
        const specifier = definition.node;
        return specifier.type === "ImportSpecifier" &&
          importSpecifierName(specifier) === "File";
      });
    }

    function nativeNamespace(identifier: Identifier): boolean {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      if (variable === null || variable.defs.length === 0) return identifier.name === "globalThis";
      return variable.defs.length === 1 && variable.defs.some((definition) =>
        definition.type === "ImportBinding" && definition.parent?.type === "ImportDeclaration" && isBufferImport(definition.parent) &&
        (definition.node.type === "ImportNamespaceSpecifier" || definition.node.type === "ImportDefaultSpecifier"),
      );
    }

    return {
      before() {
        const sourceCode = context.sourceCode;
        // A reference to File, or to an alias imported as File, spells `File` or an escaped identifier in the text.
        mayReferenceFile = sourceCode.text.includes("File") || sourceCode.text.includes("\\u");
        const program = sourceCode.ast;
        moduleServer = !hasDirective(program.body, "use client") &&
          (hasDirective(program.body, "use server") || program.body.some(serverImport));
        fileNames.clear();
        fileNames.add("File");
        for (const statement of program.body) {
          if (statement.type !== "ImportDeclaration" || !isBufferImport(statement)) continue;
          for (const specifier of statement.specifiers) {
            if (specifier.type === "ImportSpecifier" &&
              importSpecifierName(specifier) === "File") fileNames.add(specifier.local.name);
          }
        }
      },
      "Program:exit"(): void {
        if (!mayReferenceFile) return;
        for (const scope of context.sourceCode.scopeManager?.scopes ?? []) {
          for (const reference of scope.references) {
            const identifier = reference.identifier;
            if (identifier.type !== "Identifier" || !fileNames.has(identifier.name) || !inServer(identifier)) continue;
            if (nativeFile(identifier)) context.report({ node: identifier, messageId: "serverFile" });
          }
        }
      },
      MemberExpression(node: ESTree.MemberExpression): void {
        if (node.object.type === "Identifier" && staticPropertyName(node, context.sourceCode) === "File" && nativeNamespace(node.object) && inServer(node)) {
          context.report({ node, messageId: "serverFile" });
        }
      },
      TSQualifiedName(node: ESTree.TSQualifiedName): void {
        if (node.right.name === "File" && node.left.type === "Identifier" && nativeNamespace(node.left) && inServer(node)) {
          context.report({ node, messageId: "serverFile" });
        }
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        if (node.id.type !== "ObjectPattern" || node.init?.type !== "Identifier") return;
        for (const property of node.id.properties) {
          if (property.type === "Property" && staticPropertyName(property as unknown as ESTree.ObjectProperty, context.sourceCode) === "File" &&
            nativeNamespace(node.init) && inServer(node)) {
            context.report({ node: property, messageId: "serverFile" });
          }
        }
      },
    };
  },
});

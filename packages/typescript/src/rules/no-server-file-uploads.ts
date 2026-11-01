/**
 * @fileoverview no-server-file-uploads — keep native File handling on the client.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-server-file-uploads.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { staticPropertyName } from "./_static-string.js";

type MessageIds = "serverFile";
type Options = readonly [];

export const NO_SERVER_FILE_UPLOADS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep native File handling outside explicit server boundaries.",
  rationale: "Accepting uploaded files routes their bytes through application workers, consuming connections, memory or temporary disk. Direct signed-URL uploads keep that transfer in object storage.",
  remediation: "Issue an authorized, short-lived signed URL; upload the browser File directly to storage, then submit its object key and metadata. Use Blob for server-generated binary content.",
  category: "architecture",
  limitations: [
    "Checks native File references in use-server modules/functions, server-only modules, and modules importing runtime Next.js server or Hono server constructors. Explicit use-client modules keep browser File access. Filenames and variable names do not establish a server boundary.",
    "Recognizes unshadowed File/globalThis.File and named or namespace File imports from node:buffer or buffer. Local definitions and unrelated File imports are excluded. Capturing the native constructor is reported at the capture; arbitrary re-exports and dynamic loaders are not resolved.",
    "Does not ban FormData, Blob, string-only forms, local file inputs or browser previews. The separate LIB120 dependency policy covers dedicated server multipart-upload libraries.",
    "This is an architectural restriction on native File use in known server boundaries, including local File construction. It cannot prove that a URL is signed, detect every raw-byte upload or enforce object ownership, expiration, size, checksum and post-upload validation.",
    "No automatic rewrite is offered because storage authorization and completion validation require application-specific logic.",
  ],
  references: [
    "https://developer.mozilla.org/en-US/docs/Web/API/File",
    "https://hono.dev/examples/file-upload",
    "https://docs.cloud.google.com/storage/docs/access-control/signed-urls",
  ],
  examples: [
    {
      id: "browser-signed-url",
      scenarioId: "direct-upload",
      title: "Send the browser File directly to storage",
      outcome: "no-match",
      files: [{ path: "app/upload.ts", source: "'use client'; export async function upload(file: File, signedUrl: string) { await fetch(signedUrl, { method: 'PUT', body: file, signal: AbortSignal.timeout(60000) }); }" }],
      focusPath: "app/upload.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "server-file-parameter",
      scenarioId: "direct-upload",
      title: "Accept an object key instead of file bytes",
      outcome: "match",
      files: [{ path: "app/actions.ts", source: "'use server'; export async function upload(file: File) { return file.name; }" }],
      focusPath: "app/actions.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "hono-file-validation",
      scenarioId: "handler-metadata",
      title: "Do not receive a file through a Hono route",
      outcome: "match",
      files: [{ path: "src/server.ts", source: "import { Hono } from 'hono'; const app = new Hono(); app.post('/upload', async (c) => { const body = await c.req.parseBody(); return c.json({ uploaded: body.file instanceof File }); });" }],
      focusPath: "src/server.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "server-object-metadata",
      scenarioId: "handler-metadata",
      title: "Finalize a previously authorized upload",
      outcome: "no-match",
      files: [{ path: "app/actions.ts", source: "'use server'; export async function complete(objectKey: string) { return validateUploadedObject(objectKey); }" }],
      focusPath: "app/actions.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function hasDirective(statements: readonly TSESTree.Statement[], directive: string): boolean {
  for (const statement of statements) {
    if (statement.type !== AST_NODE_TYPES.ExpressionStatement || statement.directive === undefined) return false;
    if (statement.directive === directive) return true;
  }
  return false;
}

function serverImport(statement: TSESTree.ProgramStatement): boolean {
  if (statement.type !== AST_NODE_TYPES.ImportDeclaration || statement.importKind === "type") return false;
  const source = statement.source.value;
  if (source === "server-only") return statement.specifiers.length === 0 || statement.specifiers.some(
    (specifier) => specifier.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind !== "type",
  );
  if (source === "next/server") return statement.specifiers.some(
    (specifier) => specifier.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind !== "type",
  );
  return statement.specifiers.some((specifier) => {
    if (specifier.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind === "type") return false;
    const name = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
    return (source === "hono" && name === "Hono") || (source === "@hono/zod-openapi" && name === "OpenAPIHono");
  });
}

function isBufferImport(node: TSESTree.ImportDeclaration): boolean {
  return node.source.value === "node:buffer" || node.source.value === "buffer";
}

export default createRule<Options, MessageIds>({
  name: "no-server-file-uploads",
  documentation: NO_SERVER_FILE_UPLOADS_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_SERVER_FILE_UPLOADS_DOCUMENTATION.summary },
    schema: [],
    messages: { serverFile: "Keep File handling in the browser and upload directly to object storage with an authorized signed URL; accept object keys and metadata on the server." },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    const program = sourceCode.ast;
    const moduleServer = !hasDirective(program.body, "use client") &&
      (hasDirective(program.body, "use server") || program.body.some(serverImport));
    const fileNames = new Set(["File"]);
    for (const statement of program.body) {
      if (statement.type !== AST_NODE_TYPES.ImportDeclaration || !isBufferImport(statement)) continue;
      for (const specifier of statement.specifiers) {
        if (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
          (specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value) === "File") fileNames.add(specifier.local.name);
      }
    }

    function inServer(node: TSESTree.Node): boolean {
      if (moduleServer) return true;
      for (const ancestor of sourceCode.getAncestors(node)) {
        if ((ancestor.type === AST_NODE_TYPES.FunctionDeclaration || ancestor.type === AST_NODE_TYPES.FunctionExpression || ancestor.type === AST_NODE_TYPES.ArrowFunctionExpression) &&
          ancestor.body?.type === AST_NODE_TYPES.BlockStatement && hasDirective(ancestor.body.body, "use server")) return true;
      }
      return false;
    }

    function nativeFile(identifier: TSESTree.Identifier): boolean {
      const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
      if (variable === null || variable.defs.length === 0) return identifier.name === "File";
      return variable.defs.length === 1 && variable.defs.some((definition) => {
        if (definition.type !== "ImportBinding" || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration || !isBufferImport(definition.parent)) return false;
        const specifier = definition.node;
        return specifier.type === AST_NODE_TYPES.ImportSpecifier &&
          (specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value) === "File";
      });
    }

    function nativeNamespace(identifier: TSESTree.Identifier): boolean {
      const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
      if (variable === null || variable.defs.length === 0) return identifier.name === "globalThis";
      return variable.defs.length === 1 && variable.defs.some((definition) =>
        definition.type === "ImportBinding" && definition.parent.type === AST_NODE_TYPES.ImportDeclaration && isBufferImport(definition.parent) &&
        (definition.node.type === AST_NODE_TYPES.ImportNamespaceSpecifier || definition.node.type === AST_NODE_TYPES.ImportDefaultSpecifier),
      );
    }

    return {
      "Program:exit"(): void {
        for (const scope of sourceCode.scopeManager?.scopes ?? []) {
          for (const reference of scope.references) {
            const identifier = reference.identifier;
            if (identifier.type !== AST_NODE_TYPES.Identifier || !fileNames.has(identifier.name) || !inServer(identifier)) continue;
            if (nativeFile(identifier)) context.report({ node: identifier, messageId: "serverFile" });
          }
        }
      },
      MemberExpression(node: TSESTree.MemberExpression): void {
        if (node.object.type === AST_NODE_TYPES.Identifier && staticPropertyName(node, sourceCode) === "File" && nativeNamespace(node.object) && inServer(node)) {
          context.report({ node, messageId: "serverFile" });
        }
      },
      TSQualifiedName(node: TSESTree.TSQualifiedName): void {
        if (node.right.name === "File" && node.left.type === AST_NODE_TYPES.Identifier && nativeNamespace(node.left) && inServer(node)) {
          context.report({ node, messageId: "serverFile" });
        }
      },
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        if (node.id.type !== AST_NODE_TYPES.ObjectPattern || node.init?.type !== AST_NODE_TYPES.Identifier || !nativeNamespace(node.init) || !inServer(node)) return;
        for (const property of node.id.properties) {
          if (property.type === AST_NODE_TYPES.Property && staticPropertyName(property, sourceCode) === "File") {
            context.report({ node: property, messageId: "serverFile" });
          }
        }
      },
    };
  },
});

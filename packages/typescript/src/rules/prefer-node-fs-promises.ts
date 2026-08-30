/**
 * @fileoverview prefer-node-fs-promises — synchronous filesystem calls block the Node.js event loop.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-node-fs-promises.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "preferAsyncFs";
type Options = [];

export const PREFER_NODE_FS_PROMISES_DOCUMENTATION = {
  summary: "Prefer promise-based Node.js filesystem APIs over synchronous calls in production modules.",
  rationale: "Synchronous filesystem work blocks the event loop and can stall unrelated daemon, server, and worker tasks.",
  remediation: "Import the promise API from node:fs/promises and await it; use FileHandle.sync only where a documented durability boundary requires it.",
  category: "performance",
  limitations: [
    "Tests and generated files are excluded.",
    "ESLint rule implementations under src/rules are excluded because visitor creation and execution are synchronous by contract.",
    "The rule covers static ESM imports and member calls through namespace/default imports from node:fs; CommonJS require flows are not inferred.",
  ],
  examples: [
    { id: "async-read", title: "Use the promise API", outcome: "no-match", files: [{ path: "src/store.ts", source: "import { readFile } from 'node:fs/promises'; export async function load(path: string) { return readFile(path, 'utf8'); }" }], focusPath: "src/store.ts", expectedCount: 0, public: true },
    { id: "sync-read", title: "Do not block on a synchronous read", outcome: "match", files: [{ path: "src/store.ts", source: "import { readFileSync } from 'node:fs'; export function load(path: string) { return readFileSync(path, 'utf8'); }" }], focusPath: "src/store.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function memberName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  if (node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string") {
    return node.property.value;
  }
  return null;
}

export default createRule<Options, MessageIds>({
  name: "prefer-node-fs-promises",
  documentation: PREFER_NODE_FS_PROMISES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Prefer promise-based Node.js filesystem APIs over synchronous calls in production modules." },
    schema: [],
    messages: {
      preferAsyncFs: "Node filesystem API `{{name}}` is synchronous; use the promise API and await it.",
    },
  },
  defaultOptions: [],
  create(context) {
    const normalizedFilename = context.filename.replaceAll("\\", "/");
    if (
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text) ||
      normalizedFilename.includes("src/rules/")
    )
      return {};
    const namespaces = new Set<string>();
    return {
      ImportDeclaration(node): void {
        if (node.source.value !== "node:fs" && node.source.value !== "fs") return;
        const synchronousImports: string[] = [];
        for (const specifier of node.specifiers) {
          if (specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier || specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier) {
            namespaces.add(specifier.local.name);
            continue;
          }
          if (
            specifier.type === AST_NODE_TYPES.ImportSpecifier &&
            specifier.imported.type === AST_NODE_TYPES.Identifier &&
            specifier.imported.name.endsWith("Sync")
          ) synchronousImports.push(specifier.imported.name);
        }
        if (synchronousImports.length > 0) {
          context.report({
            node,
            messageId: "preferAsyncFs",
            data: { name: synchronousImports.join(", ") },
          });
        }
      },
      MemberExpression(node): void {
        if (node.object.type !== AST_NODE_TYPES.Identifier || !namespaces.has(node.object.name)) return;
        const name = memberName(node);
        if (name?.endsWith("Sync") === true) {
          context.report({ node, messageId: "preferAsyncFs", data: { name } });
        }
      },
    };
  },
});

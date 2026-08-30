/**
 * @fileoverview prefer-node-crypto-hash — one-shot hashing should use Node's stateless built-in API.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-node-crypto-hash.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferNodeCryptoHash";
type Options = readonly [];

export const PREFER_NODE_CRYPTO_HASH_DOCUMENTATION = {
  summary: "Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary.",
  rationale: "A createHash-update-digest chain allocates mutable streaming state for a single in-memory value; Node's built-in hash function expresses the one-shot operation directly and can use its optimized fast path.",
  remediation: "Import hash from node:crypto and replace a single-update chain with hash(algorithm, value, encoding). Keep createHash for streams or multiple incremental updates.",
  category: "performance",
  limitations: [
    "Only direct ESM imports and namespace imports from node:crypto are analyzed.",
    "Only a literal algorithm with exactly one update call is reported; streaming and incremental hashes remain valid.",
  ],
  examples: [
    { id: "one-shot-hash", title: "Use Node's one-shot hash API", outcome: "no-match", files: [{ path: "case.ts", source: "import { hash } from 'node:crypto'; export const digest = hash('sha256', 'value', 'hex');" }], focusPath: "case.ts", expectedCount: 0, public: true },
    { id: "mutable-one-shot-chain", title: "Avoid mutable state for one value", outcome: "match", files: [{ path: "case.ts", source: "import { createHash } from 'node:crypto'; export const digest = createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "prefer-node-crypto-hash",
  documentation: PREFER_NODE_CRYPTO_HASH_DOCUMENTATION,
  meta: { type: "problem", docs: { description: PREFER_NODE_CRYPTO_HASH_DOCUMENTATION.summary }, schema: [], messages: { preferNodeCryptoHash: 'Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary.' } },
  defaultOptions: [],
  create(context) {
    const directImports = new Set<string>();
    const namespaceImports = new Set<string>();
    return {
      ImportDeclaration(node): void {
        if (node.source.value !== "node:crypto") return;
        for (const specifier of node.specifiers) {
          if (specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier) {
            namespaceImports.add(specifier.local.name);
          } else if (
            specifier.type === AST_NODE_TYPES.ImportSpecifier &&
            importedName(specifier.imported) === "createHash"
          ) {
            directImports.add(specifier.local.name);
          }
        }
      },
      CallExpression(node): void {
        if (!isMemberCall(node, "digest")) return;
        const update = node.callee.object;
        if (
          update.type !== AST_NODE_TYPES.CallExpression ||
          update.arguments.length !== 1 ||
          !isMemberCall(update, "update")
        )
          return;
        const create = update.callee.object;
        if (
          create.type !== AST_NODE_TYPES.CallExpression ||
          create.arguments.length !== 1 ||
          create.arguments[0]?.type !== AST_NODE_TYPES.Literal ||
          typeof create.arguments[0].value !== "string" ||
          !isCreateHashCall(create, directImports, namespaceImports)
        )
          return;
        context.report({ node, messageId: "preferNodeCryptoHash" });
      },
    };
  },
});

function importedName(node: TSESTree.Identifier | TSESTree.StringLiteral): string {
  return node.type === AST_NODE_TYPES.Identifier ? node.name : node.value;
}

function isMemberCall(
  node: TSESTree.CallExpression,
  name: string,
): node is TSESTree.CallExpression & {
  callee: TSESTree.MemberExpression;
} {
  return (
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    node.callee.property.name === name
  );
}

function isCreateHashCall(
  node: TSESTree.CallExpression,
  directImports: ReadonlySet<string>,
  namespaceImports: ReadonlySet<string>,
): boolean {
  if (node.callee.type === AST_NODE_TYPES.Identifier)
    return directImports.has(node.callee.name);
  return (
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.object.type === AST_NODE_TYPES.Identifier &&
    namespaceImports.has(node.callee.object.name) &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    node.callee.property.name === "createHash"
  );
}

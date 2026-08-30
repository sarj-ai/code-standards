/**
 * @fileoverview prefer-node-crypto-hash — one-shot hashing should use Node's stateless built-in API.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-node-crypto-hash.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferNodeCryptoHash";
type Options = readonly [];

export const PREFER_NODE_CRYPTO_HASH_DOCUMENTATION = {
  summary: "Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary.",
  rationale: "A createHash-update-digest chain allocates mutable streaming state for a single in-memory value; Node's built-in hash function expresses the one-shot operation directly and can use its optimized fast path.",
  remediation: "Import hash from node:crypto and replace a single-update chain with hash(algorithm, value, encoding). Keep createHash for streams or multiple incremental updates.",
  category: "performance",
  limitations: [
    "Only bindings and inline calls with statically proven provenance from crypto or node:crypto are analyzed; arbitrary assignments and dynamic module specifiers are excluded.",
    "Only a literal algorithm with exactly one update call is reported; streaming and incremental hashes remain valid.",
  ],
  examples: [
    { id: "one-shot-hash", title: "Use Node's one-shot hash API", outcome: "no-match", files: [{ path: "case.ts", source: "import { hash } from 'node:crypto'; export const digest = hash('sha256', 'value', 'hex');" }], focusPath: "case.ts", expectedCount: 0, public: true },
    { id: "mutable-one-shot-chain", title: "Avoid mutable state for one value", outcome: "match", files: [{ path: "case.ts", source: "import { createHash } from 'node:crypto'; export const digest = createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type ScopeVariable = TSESLint.Scope.Variable;

function memberName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  if (
    node.computed &&
    node.property.type === AST_NODE_TYPES.Literal &&
    typeof node.property.value === "string"
  ) {
    return node.property.value;
  }
  return null;
}

function isCryptoLoader(
  node: TSESTree.Expression,
  resolve: (identifier: TSESTree.Identifier) => ScopeVariable | null,
): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression || node.arguments.length !== 1) return false;
  const [argument] = node.arguments;
  if (
    argument === undefined ||
    argument.type === AST_NODE_TYPES.SpreadElement ||
    !isCryptoSpecifier(argument)
  ) {
    return false;
  }
  if (node.callee.type === AST_NODE_TYPES.Identifier) {
    return (
      node.callee.name === "require" &&
      isUnshadowedBuiltinIdentifier(node.callee, resolve)
    );
  }
  return (
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    node.callee.object.type === AST_NODE_TYPES.Identifier &&
    node.callee.object.name === "process" &&
    isUnshadowedBuiltinIdentifier(node.callee.object, resolve) &&
    memberName(node.callee) === "getBuiltinModule"
  );
}

function isCryptoSpecifier(node: TSESTree.Expression): boolean {
  return (
    node.type === AST_NODE_TYPES.Literal &&
    (node.value === "crypto" || node.value === "node:crypto")
  );
}

function isUnshadowedBuiltinIdentifier(
  identifier: TSESTree.Identifier,
  resolve: (identifier: TSESTree.Identifier) => ScopeVariable | null,
): boolean {
  const variable = resolve(identifier);
  return variable === null || variable.defs.length === 0;
}

function propertyName(node: TSESTree.Property): string | null {
  if (!node.computed && node.key.type === AST_NODE_TYPES.Identifier) return node.key.name;
  if (node.key.type === AST_NODE_TYPES.Literal && typeof node.key.value === "string") {
    return node.key.value;
  }
  return null;
}

export default createRule<Options, MessageIds>({
  name: "prefer-node-crypto-hash",
  documentation: PREFER_NODE_CRYPTO_HASH_DOCUMENTATION,
  meta: { type: "problem", docs: { description: PREFER_NODE_CRYPTO_HASH_DOCUMENTATION.summary }, schema: [], messages: { preferNodeCryptoHash: 'Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary.' } },
  defaultOptions: [],
  create(context) {
    const directBindings = new Set<ScopeVariable>();
    const namespaceBindings = new Set<ScopeVariable>();

    function resolve(identifier: TSESTree.Identifier): ScopeVariable | null {
      return ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function record(
      identifier: TSESTree.Identifier,
      destination: Set<ScopeVariable>,
    ): void {
      const variable = resolve(identifier);
      if (variable !== null) destination.add(variable);
    }

    return {
      ImportDeclaration(node): void {
        if (node.source.value !== "crypto" && node.source.value !== "node:crypto") return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier
          ) {
            record(specifier.local, namespaceBindings);
          } else if (
            specifier.type === AST_NODE_TYPES.ImportSpecifier &&
            importedName(specifier.imported) === "createHash"
          ) {
            record(specifier.local, directBindings);
          }
        }
      },
      VariableDeclarator(node): void {
        if (
          node.parent.kind !== "const" ||
          node.init === null ||
          !isCryptoLoader(node.init, resolve)
        ) {
          return;
        }
        if (node.id.type === AST_NODE_TYPES.Identifier) {
          record(node.id, namespaceBindings);
          return;
        }
        if (node.id.type !== AST_NODE_TYPES.ObjectPattern) return;
        for (const property of node.id.properties) {
          if (
            property.type === AST_NODE_TYPES.Property &&
            propertyName(property) === "createHash" &&
            property.value.type === AST_NODE_TYPES.Identifier
          ) {
            record(property.value, directBindings);
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
          !isCreateHashCall(
            create,
            directBindings,
            namespaceBindings,
            resolve,
          )
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
    memberName(node.callee) === name
  );
}

function isCreateHashCall(
  node: TSESTree.CallExpression,
  directBindings: ReadonlySet<ScopeVariable>,
  namespaceBindings: ReadonlySet<ScopeVariable>,
  resolve: (identifier: TSESTree.Identifier) => ScopeVariable | null,
): boolean {
  if (node.callee.type === AST_NODE_TYPES.Identifier) {
    const variable = resolve(node.callee);
    return variable !== null && directBindings.has(variable);
  }
  if (
    node.callee.type !== AST_NODE_TYPES.MemberExpression ||
    memberName(node.callee) !== "createHash"
  ) {
    return false;
  }
  if (isCryptoLoader(node.callee.object, resolve)) return true;
  if (node.callee.object.type !== AST_NODE_TYPES.Identifier) return false;
  const variable = resolve(node.callee.object);
  return (
    variable !== null &&
    namespaceBindings.has(variable)
  );
}

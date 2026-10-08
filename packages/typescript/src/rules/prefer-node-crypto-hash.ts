/**
 * @fileoverview prefer-node-crypto-hash — one-shot hashing should use Node's stateless built-in API.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-node-crypto-hash.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { unwrapExpression } from "./_unwrap-expression.js";
import { staticString } from "./_static-string.js";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "preferNodeCryptoHash";
type Options = readonly [];

export const PREFER_NODE_CRYPTO_HASH_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary.",
  rationale: "A createHash-update-digest chain allocates mutable streaming state for a single in-memory value; Node's built-in hash function expresses the one-shot operation directly and can use its optimized fast path.",
  remediation: "On a supported Node runtime, consider hash(algorithm, value, encoding). Preserve the output encoding explicitly: digest() returns a Buffer, while hash defaults to hex. Keep createHash for streams or multiple updates.",
  category: "performance",
  limitations: [
    "Only bindings and inline calls with statically proven provenance from crypto or node:crypto are analyzed; arbitrary assignments and dynamic module specifiers are excluded.",
    "Only a literal algorithm with exactly one update call is reported; streaming and incremental hashes remain valid.",
    "Runtime support and output encoding require manual review; no autofix or guaranteed speedup is promised.",
  ],
  references: ["https://nodejs.org/api/crypto.html#cryptohashalgorithm-data-options"],
  examples: [
    { id: "one-shot-hash", title: "Use Node's one-shot hash API", outcome: "no-match", files: [{ path: "case.ts", source: "import { hash } from 'node:crypto'; export const digest = hash('sha256', 'value', 'hex');" }], focusPath: "case.ts", expectedCount: 0, public: true },
    { id: "mutable-one-shot-chain", title: "Avoid mutable state for one value", outcome: "match", files: [{ path: "case.ts", source: "import { createHash } from 'node:crypto'; export const digest = createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type ScopeVariable = TSESLint.Scope.Variable;

function isCryptoLoader(
  node: TSESTree.Expression,
  resolve: (identifier: TSESTree.Identifier) => ScopeVariable | null,
): boolean {
  const unwrappedNodeCallee = node.type === "CallExpression" || node.type === "NewExpression" ? unwrapExpression(node.callee) : null;
  if (node.type !== AST_NODE_TYPES.CallExpression || node.arguments.length !== 1) return false;
  const [argument] = node.arguments;
  if (
    argument === undefined ||
    argument.type === AST_NODE_TYPES.SpreadElement ||
    !isCryptoSpecifier(argument)
  ) {
    return false;
  }
  if (unwrappedNodeCallee?.type === AST_NODE_TYPES.Identifier) {
    return (
      unwrappedNodeCallee.name === "require" &&
      isUnshadowedBuiltinIdentifier(unwrappedNodeCallee, resolve)
    );
  }
  return (
    unwrappedNodeCallee?.type === AST_NODE_TYPES.MemberExpression &&
    unwrappedNodeCallee.object.type === AST_NODE_TYPES.Identifier &&
    unwrappedNodeCallee.object.name === "process" &&
    isUnshadowedBuiltinIdentifier(unwrappedNodeCallee.object, resolve) &&
    ASTUtils.getPropertyName(unwrappedNodeCallee) === "getBuiltinModule"
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
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        if (unwrappedNodeCallee.type !== AST_NODE_TYPES.MemberExpression || !isMemberCall(node, "digest")) return;
        const update = unwrapExpression(unwrappedNodeCallee.object);
        if (
          update.type !== AST_NODE_TYPES.CallExpression ||
          update.arguments.length !== 1 ||
          !isMemberCall(update, "update")
        )
          return;
        const updateCallee = unwrapExpression(update.callee);
        if (updateCallee.type !== AST_NODE_TYPES.MemberExpression) return;
        const create = unwrapExpression(updateCallee.object);
        const algorithm = create.type === AST_NODE_TYPES.CallExpression && create.arguments[0] !== undefined ? unwrapExpression(create.arguments[0]) : null;
        if (
          create.type !== AST_NODE_TYPES.CallExpression ||
          create.arguments.length !== 1 ||
          staticString(algorithm ?? undefined) === null ||
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
): boolean {
  const unwrappedNodeCallee = unwrapExpression(node.callee);
  return (
    unwrappedNodeCallee.type === AST_NODE_TYPES.MemberExpression &&
    ASTUtils.getPropertyName(unwrappedNodeCallee) === name
  );
}

function isCreateHashCall(
  node: TSESTree.CallExpression,
  directBindings: ReadonlySet<ScopeVariable>,
  namespaceBindings: ReadonlySet<ScopeVariable>,
  resolve: (identifier: TSESTree.Identifier) => ScopeVariable | null,
): boolean {
  const unwrappedNodeCallee = unwrapExpression(node.callee);
  if (unwrappedNodeCallee.type === AST_NODE_TYPES.Identifier) {
    const variable = resolve(unwrappedNodeCallee);
    return variable !== null && directBindings.has(variable);
  }
  if (
    unwrappedNodeCallee.type !== AST_NODE_TYPES.MemberExpression ||
    ASTUtils.getPropertyName(unwrappedNodeCallee) !== "createHash"
  ) {
    return false;
  }
  if (isCryptoLoader(unwrappedNodeCallee.object, resolve)) return true;
  if (unwrappedNodeCallee.object.type !== AST_NODE_TYPES.Identifier) return false;
  const variable = resolve(unwrappedNodeCallee.object);
  return (
    variable !== null &&
    namespaceBindings.has(variable)
  );
}

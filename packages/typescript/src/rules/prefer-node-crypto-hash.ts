/**
 * @fileoverview prefer-node-crypto-hash — one-shot hashing should use Node's stateless built-in API.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-node-crypto-hash.test.ts
 */

import type { ESTree, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


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

type ScopeVariable = Variable;

function memberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  if (
    node.computed &&
    node.property.type === "Literal" &&
    typeof node.property.value === "string"
  ) {
    return node.property.value;
  }
  return null;
}

function isCryptoLoader(
  node: ESTree.Expression,
  resolve: (identifier: ESTree.BindingIdentifier) => ScopeVariable | null,
): boolean {
  if (node.type !== "CallExpression" || node.arguments.length !== 1) return false;
  const [argument] = node.arguments;
  if (
    argument === undefined ||
    argument.type === "SpreadElement" ||
    !isCryptoSpecifier(argument)
  ) {
    return false;
  }
  if (node.callee.type === "Identifier") {
    return (
      node.callee.name === "require" &&
      isUnshadowedBuiltinIdentifier(node.callee, resolve)
    );
  }
  return (
    node.callee.type === "MemberExpression" &&
    node.callee.object.type === "Identifier" &&
    node.callee.object.name === "process" &&
    isUnshadowedBuiltinIdentifier(node.callee.object, resolve) &&
    memberName(node.callee) === "getBuiltinModule"
  );
}

function isCryptoSpecifier(node: ESTree.Expression): boolean {
  return (
    node.type === "Literal" &&
    (node.value === "crypto" || node.value === "node:crypto")
  );
}

function isUnshadowedBuiltinIdentifier(
  identifier: ESTree.BindingIdentifier,
  resolve: (identifier: ESTree.BindingIdentifier) => ScopeVariable | null,
): boolean {
  const variable = resolve(identifier);
  return variable === null || variable.defs.length === 0;
}

function propertyName(node: ESTree.ObjectProperty | ESTree.BindingProperty): string | null {
  if (!node.computed && node.key.type === "Identifier") return node.key.name;
  if (node.key.type === "Literal" && typeof node.key.value === "string") {
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

    function resolve(identifier: ESTree.BindingIdentifier): ScopeVariable | null {
      return findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function record(
      identifier: ESTree.BindingIdentifier,
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
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier"
          ) {
            record(specifier.local, namespaceBindings);
          } else if (
            specifier.type === "ImportSpecifier" &&
            importedName(specifier.imported) === "createHash"
          ) {
            record(specifier.local, directBindings);
          }
        }
      },
      VariableDeclarator(node): void {
        if (
          node.parent?.type !== "VariableDeclaration" || node.parent.kind !== "const" ||
          node.init === null ||
          !isCryptoLoader(node.init, resolve)
        ) {
          return;
        }
        if (node.id.type === "Identifier") {
          record(node.id, namespaceBindings);
          return;
        }
        if (node.id.type !== "ObjectPattern") return;
        for (const property of node.id.properties) {
          if (
            property.type === "Property" &&
            propertyName(property) === "createHash" &&
            property.value.type === "Identifier"
          ) {
            record(property.value, directBindings);
          }
        }
      },
      CallExpression(node): void {
        if (!isMemberCall(node, "digest")) return;
        const update = node.callee.object;
        if (
          update.type !== "CallExpression" ||
          update.arguments.length !== 1 ||
          !isMemberCall(update, "update")
        )
          return;
        const create = update.callee.object;
        if (
          create.type !== "CallExpression" ||
          create.arguments.length !== 1 ||
          create.arguments[0]?.type !== "Literal" ||
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

function importedName(node: ESTree.BindingIdentifier | ESTree.StringLiteral): string {
  return node.type === "Identifier" ? node.name : node.value;
}

function isMemberCall(
  node: ESTree.CallExpression,
  name: string,
): node is ESTree.CallExpression & {
  callee: ESTree.MemberExpression;
} {
  return (
    node.callee.type === "MemberExpression" &&
    memberName(node.callee) === name
  );
}

function isCreateHashCall(
  node: ESTree.CallExpression,
  directBindings: ReadonlySet<ScopeVariable>,
  namespaceBindings: ReadonlySet<ScopeVariable>,
  resolve: (identifier: ESTree.BindingIdentifier) => ScopeVariable | null,
): boolean {
  if (node.callee.type === "Identifier") {
    const variable = resolve(node.callee);
    return variable !== null && directBindings.has(variable);
  }
  if (
    node.callee.type !== "MemberExpression" ||
    memberName(node.callee) !== "createHash"
  ) {
    return false;
  }
  if (isCryptoLoader(node.callee.object, resolve)) return true;
  if (node.callee.object.type !== "Identifier") return false;
  const variable = resolve(node.callee.object);
  return (
    variable !== null &&
    namespaceBindings.has(variable)
  );
}

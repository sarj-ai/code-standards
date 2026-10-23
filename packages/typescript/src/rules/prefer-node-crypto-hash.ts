/**
 * @fileoverview prefer-node-crypto-hash — one-shot hashing should use Node's stateless built-in API.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-node-crypto-hash.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { staticString } from "./_static-string.js";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { stableValueBinding, typeOnlyReference } from "./_stable-value-binding.js";

type MessageIds = "preferNodeCryptoHash";
type Options = readonly [];

export const PREFER_NODE_CRYPTO_HASH_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary.",
  rationale: "A createHash-update-digest chain allocates mutable streaming state for a single in-memory value; Node's built-in hash function expresses the one-shot operation directly and can use its optimized fast path.",
  remediation: "On a supported Node runtime, consider hash(algorithm, value, encoding). Preserve the output encoding explicitly: digest() returns a Buffer, while hash defaults to hex. Keep createHash for streams or multiple updates.",
  category: "performance",
  limitations: [
    "Only direct imports, const bindings, and inline calls with statically proven provenance from crypto or node:crypto are analyzed; arbitrary assignments and dynamic module specifiers are excluded.",
    "Only a literal algorithm with exactly one update call is reported; streaming and incremental hashes remain valid.",
    "Namespace bindings must remain read-only: visible writes, aliases, exports, inherited mutation or alias methods, unknown computed members, and other escaping uses are excluded; type-only references and direct member calls remain eligible.",
    "CommonJS loads and default imports share one mutable native module object. A visible unsafe use of that object excludes its other loads; ESM named exports remain separate unless visible native export synchronization can update them.",
    "Runtime support and output encoding require manual review; no autofix or guaranteed speedup is promised.",
  ],
  references: ["https://nodejs.org/api/crypto.html#cryptohashalgorithm-data-options"],
  examples: [
    { id: "one-shot-hash", title: "Use Node's one-shot hash API", outcome: "no-match", files: [{ path: "case.ts", source: "import { hash } from 'node:crypto'; export const digest = hash('sha256', 'value', 'hex');" }], focusPath: "case.ts", expectedCount: 0, public: true },
    { id: "mutable-one-shot-chain", title: "Avoid mutable state for one value", outcome: "match", files: [{ path: "case.ts", source: "import { createHash } from 'node:crypto'; export const digest = createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 1, public: true },
    { id: "native-namespace", scenarioId: "stable-native-namespace", title: "An unchanged namespace retains native provenance", outcome: "match", files: [{ path: "case.ts", source: "const crypto = require('node:crypto'); export const digest = crypto.createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 1, public: true },
    { id: "replaced-namespace-member", scenarioId: "stable-native-namespace", title: "A replaced member has a different contract", outcome: "no-match", files: [{ path: "case.ts", source: "const crypto = require('node:crypto'); crypto.createHash = () => ({ update() { return this; }, digest() { return 'custom'; } }); export const digest = crypto.createHash('sha256').update('value').digest('hex');" }], focusPath: "case.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

type ScopeVariable = TSESLint.Scope.Variable;
const UNSAFE_NAMESPACE_METHODS: ReadonlySet<string> = new Set(["__defineGetter__", "__defineSetter__", "valueOf"]);

/** A namespace that escapes can be changed through a use this rule cannot prove. */
function stableNamespace(variable: ScopeVariable): boolean {
  if (variable.defs.some((definition) => definition.type === "Variable" &&
    definition.parent.parent.type === AST_NODE_TYPES.ExportNamedDeclaration)) return false;
  return stableValueBinding(variable, (reference) => {
    if (typeOnlyReference(reference)) return true;
    const receiver = outerExpression(reference.identifier);
    return readonlyNamespaceUse(receiver);
  });
}

function readonlyNamespaceUse(receiver: TSESTree.Node): boolean {
  const member = receiver.parent;
  if (member?.type !== AST_NODE_TYPES.MemberExpression || member.object !== receiver) {
    return member?.type === AST_NODE_TYPES.UnaryExpression && member.operator === "typeof";
  }
  const use = outerExpression(member);
  const name = ASTUtils.getPropertyName(member);
  return name !== null && !UNSAFE_NAMESPACE_METHODS.has(name) &&
    use.parent?.type === AST_NODE_TYPES.CallExpression && use.parent.callee === use;
}

function readonlyLoaderUse(
  node: TSESTree.CallExpression,
  resolve: (identifier: TSESTree.Identifier) => ScopeVariable | null,
  stable: (variable: ScopeVariable) => boolean,
): boolean {
  const receiver = outerExpression(node);
  const parent = receiver.parent;
  if (parent?.type === AST_NODE_TYPES.VariableDeclarator && parent.init === receiver) {
    if (parent.id.type === AST_NODE_TYPES.ObjectPattern) return true;
    if (parent.id.type !== AST_NODE_TYPES.Identifier) return false;
    const variable = resolve(parent.id);
    return variable !== null && stable(variable);
  }
  return parent?.type === AST_NODE_TYPES.ExpressionStatement || readonlyNamespaceUse(receiver);
}

function namespaceDefaultMayEscape(variable: ScopeVariable): boolean {
  return variable.references.some((reference) => {
    if (typeOnlyReference(reference)) return false;
    const receiver = outerExpression(reference.identifier);
    const member = receiver.parent;
    if (member?.type !== AST_NODE_TYPES.MemberExpression || member.object !== receiver) {
      return member?.type !== AST_NODE_TYPES.UnaryExpression || member.operator !== "typeof";
    }
    const name = ASTUtils.getPropertyName(member);
    return (name === null || name === "default") && !readonlyNamespaceUse(outerExpression(member));
  });
}

function isBuiltinLoader(
  node: TSESTree.Expression,
  resolve: (identifier: TSESTree.Identifier) => ScopeVariable | null,
  builtin: "crypto" | "module" = "crypto",
): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression || node.arguments.length !== 1) return false;
  const [argument] = node.arguments;
  if (
    argument === undefined ||
    argument.type === AST_NODE_TYPES.SpreadElement ||
    !isBuiltinSpecifier(argument, builtin)
  ) {
    return false;
  }
  const unwrappedNodeCallee = unwrapExpression(node.callee);
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

function isBuiltinSpecifier(node: TSESTree.Expression, builtin: "crypto" | "module"): boolean {
  return (
    node.type === AST_NODE_TYPES.Literal &&
    (node.value === builtin || node.value === `node:${builtin}`)
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
    if (!context.sourceCode.text.includes("crypto") && !context.sourceCode.text.includes("\\")) return {};
    const directBindings = new Set<ScopeVariable>();
    const namespaceBindings = new Set<ScopeVariable>();
    const sharedBindings = new Set<ScopeVariable>();
    const syncBindings = new Set<ScopeVariable>();
    const moduleBindings = new Set<ScopeVariable>();
    const namespaceStability = new WeakMap<ScopeVariable, boolean>();
    const candidates: { node: TSESTree.CallExpression; shared: boolean }[] = [];
    const possibleSynchronizations: TSESTree.CallExpression[] = [];
    let sharedNamespaceUnsafe = false;

    function namespaceStable(variable: ScopeVariable): boolean {
      const cached = namespaceStability.get(variable);
      if (cached !== undefined) return cached;
      const stable = stableNamespace(variable);
      namespaceStability.set(variable, stable);
      return stable;
    }

    function resolve(identifier: TSESTree.Identifier): ScopeVariable | null {
      return ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function record(
      identifier: TSESTree.Identifier,
      destination: Set<ScopeVariable>,
      shared = false,
    ): void {
      const variable = resolve(identifier);
      if (variable === null) return;
      const stable = destination === namespaceBindings ? namespaceStable(variable) : stableValueBinding(variable);
      if (shared && destination === namespaceBindings && !stable) sharedNamespaceUnsafe = true;
      if (!stable) return;
      destination.add(variable);
      if (shared) sharedBindings.add(variable);
    }

    function recordModuleImports(specifiers: TSESTree.ImportDeclaration["specifiers"]): void {
      for (const specifier of specifiers) {
        if (specifier.type === AST_NODE_TYPES.ImportSpecifier) {
          if (importedName(specifier.imported) === "syncBuiltinESMExports") record(specifier.local, syncBindings);
          else if (importedName(specifier.imported) === "default") record(specifier.local, moduleBindings);
        } else record(specifier.local, moduleBindings);
      }
    }

    return {
      ImportDeclaration(node): void {
        if (node.source.value === "module" || node.source.value === "node:module") {
          recordModuleImports(node.specifiers);
          return;
        }
        if (node.source.value !== "crypto" && node.source.value !== "node:crypto") return;
        for (const specifier of node.specifiers) {
          const shared = specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier && importedName(specifier.imported) === "default");
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            shared
          ) {
            record(specifier.local, namespaceBindings, shared);
            const variable = resolve(specifier.local);
            if (!shared && variable !== null && namespaceDefaultMayEscape(variable)) sharedNamespaceUnsafe = true;
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
          (!isBuiltinLoader(node.init, resolve) && !isBuiltinLoader(node.init, resolve, "module"))
        ) {
          return;
        }
        const crypto = isBuiltinLoader(node.init, resolve);
        if (node.id.type === AST_NODE_TYPES.Identifier) {
          record(node.id, crypto ? namespaceBindings : moduleBindings, crypto);
          return;
        }
        if (node.id.type !== AST_NODE_TYPES.ObjectPattern) return;
        for (const property of node.id.properties) {
          if (
            property.type === AST_NODE_TYPES.Property &&
            propertyName(property) === (crypto ? "createHash" : "syncBuiltinESMExports") &&
            property.value.type === AST_NODE_TYPES.Identifier
          ) {
            record(property.value, crypto ? directBindings : syncBindings, crypto);
          }
        }
      },
      CallExpression(node): void {
        if (isBuiltinLoader(node, resolve) && !readonlyLoaderUse(node, resolve, namespaceStable)) sharedNamespaceUnsafe = true;
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        if (unwrappedNodeCallee.type === AST_NODE_TYPES.Identifier ||
          (unwrappedNodeCallee.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(unwrappedNodeCallee) === "syncBuiltinESMExports")) possibleSynchronizations.push(node);
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
          staticString(algorithm ?? undefined) === null
        )
          return;
        const provider = builtinCallProvider(create, directBindings, namespaceBindings, sharedBindings, resolve);
        if (provider !== null) candidates.push({ node, shared: provider === "shared" });
      },
      "Program:exit"(): void {
        const exportsMaySynchronize = sharedNamespaceUnsafe && possibleSynchronizations.some((node) =>
          builtinCallProvider(node, syncBindings, moduleBindings, sharedBindings, resolve, "module") !== null);
        for (const candidate of candidates) {
          if (!sharedNamespaceUnsafe || (!candidate.shared && !exportsMaySynchronize)) context.report({ node: candidate.node, messageId: "preferNodeCryptoHash" });
        }
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

function builtinCallProvider(
  node: TSESTree.CallExpression,
  directBindings: ReadonlySet<ScopeVariable>,
  namespaceBindings: ReadonlySet<ScopeVariable>,
  sharedBindings: ReadonlySet<ScopeVariable>,
  resolve: (identifier: TSESTree.Identifier) => ScopeVariable | null,
  builtin: "crypto" | "module" = "crypto",
): "shared" | "snapshot" | null {
  const unwrappedNodeCallee = unwrapExpression(node.callee);
  if (unwrappedNodeCallee.type === AST_NODE_TYPES.Identifier) {
    const variable = resolve(unwrappedNodeCallee);
    if (variable === null || !directBindings.has(variable)) return null;
    return sharedBindings.has(variable) ? "shared" : "snapshot";
  }
  if (
    unwrappedNodeCallee.type !== AST_NODE_TYPES.MemberExpression ||
    ASTUtils.getPropertyName(unwrappedNodeCallee) !== (builtin === "crypto" ? "createHash" : "syncBuiltinESMExports")
  ) {
    return null;
  }
  if (isBuiltinLoader(unwrappedNodeCallee.object, resolve, builtin)) return "shared";
  if (unwrappedNodeCallee.object.type !== AST_NODE_TYPES.Identifier) return null;
  const variable = resolve(unwrappedNodeCallee.object);
  if (variable === null || !namespaceBindings.has(variable)) return null;
  return sharedBindings.has(variable) ? "shared" : "snapshot";
}

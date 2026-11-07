/**
 * @fileoverview prefer-node-crypto-hash — one-shot hashing should use Node's stateless built-in API.
 *
 * Port of the 18.x `prefer-node-crypto-hash` rule. The rule is untyped.
 * The original's fix checks `typeArguments !== undefined`; Oxlint gives null
 * there, so under Oxlint the original never offers its fix. This port accepts
 * null and undefined, which matches the original under ESLint.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-node-crypto-hash.test.ts
 */

import type { FixFn } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { forEachOwnAstChild, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";
import { stableValueBinding, typeOnlyReference } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";
import { hasIdentifierNamed, hasOnlyDirectFactoryUses } from "../utils/unused-private-binding.js";

const NAME = "prefer-node-crypto-hash";

type ScopeVariable = TsVariable;
type Identifier = Extract<Node, { type: "Identifier" }>;
type Resolve = (identifier: Identifier) => ScopeVariable | null;
const UNSAFE_NAMESPACE_METHODS: ReadonlySet<string> = new Set(["__defineGetter__", "__defineSetter__", "valueOf"]);
const UNSAFE_AUTHORITY_IDENTIFIERS: readonly string[] = [
  "eval", "Object", "Reflect", "Function", "require", "process", "globalThis", "global", "vi", "jest", "mock", "doMock",
  "unstable_mockModule", "spyOn",
];
const UNSAFE_AUTHORITY_MEMBERS: ReadonlySet<string> = new Set([
  "prototype", "constructor", "__proto__", "mock", "doMock", "unstable_mockModule", "spyOn", "register", "registerHooks",
  "enableCompileCache",
]);
const SUPPORT_FILE_RE = /(?:^|[\\/])(?:support|test-support|test-utils|mocks|setup)(?:[\\/]|\.[cm]?[jt]sx?$)/iu;

/** A namespace that escapes can be changed through a use this rule cannot prove. */
function stableNamespace(variable: ScopeVariable): boolean {
  if (variable.defs.some((definition) => definition.type === "Variable" &&
    parentOf(definition.parent as Node)?.type === "ExportNamedDeclaration")) return false;
  return stableValueBinding(variable, (reference) => {
    if (typeOnlyReference(reference)) return true;
    const receiver = outerExpression(reference.identifier);
    return readonlyNamespaceUse(receiver);
  });
}

function readonlyNamespaceUse(receiver: Node): boolean {
  const member = parentOf(receiver);
  if (member?.type !== "MemberExpression" || member.object !== receiver) {
    return member?.type === "UnaryExpression" && member.operator === "typeof";
  }
  const use = outerExpression(member);
  const name = getPropertyName(member);
  const parent = parentOf(use);
  return name !== null && !UNSAFE_NAMESPACE_METHODS.has(name) &&
    parent?.type === "CallExpression" && parent.callee === use;
}

function readonlyLoaderUse(
  node: ESTree.CallExpression,
  resolve: Resolve,
  stable: (variable: ScopeVariable) => boolean,
): boolean {
  const receiver = outerExpression(node);
  const parent = parentOf(receiver);
  if (parent?.type === "VariableDeclarator" && parent.init === receiver) {
    if (parent.id.type === "ObjectPattern") return true;
    if (parent.id.type !== "Identifier") return false;
    const variable = resolve(parent.id);
    return variable !== null && stable(variable);
  }
  return parent?.type === "ExpressionStatement" || readonlyNamespaceUse(receiver);
}

function namespaceDefaultMayEscape(variable: ScopeVariable): boolean {
  return variable.references.some((reference) => {
    if (typeOnlyReference(reference)) return false;
    const receiver = outerExpression(reference.identifier);
    const member = parentOf(receiver);
    if (member?.type !== "MemberExpression" || member.object !== receiver) {
      return member?.type !== "UnaryExpression" || member.operator !== "typeof";
    }
    const name = getPropertyName(member);
    return (name === null || name === "default") && !readonlyNamespaceUse(outerExpression(member));
  });
}

function isBuiltinLoader(
  node: Node,
  resolve: Resolve,
  builtin: "crypto" | "module" = "crypto",
): boolean {
  if (node.type !== "CallExpression" || node.arguments.length !== 1) return false;
  const [argument] = node.arguments;
  if (
    argument === undefined ||
    argument.type === "SpreadElement" ||
    !isBuiltinSpecifier(argument, builtin)
  ) {
    return false;
  }
  const unwrappedNodeCallee = unwrapExpression(node.callee);
  if (unwrappedNodeCallee.type === "Identifier") {
    return (
      unwrappedNodeCallee.name === "require" &&
      isUnshadowedBuiltinIdentifier(unwrappedNodeCallee, resolve)
    );
  }
  return (
    unwrappedNodeCallee.type === "MemberExpression" &&
    unwrappedNodeCallee.object.type === "Identifier" &&
    unwrappedNodeCallee.object.name === "process" &&
    isUnshadowedBuiltinIdentifier(unwrappedNodeCallee.object, resolve) &&
    getPropertyName(unwrappedNodeCallee) === "getBuiltinModule"
  );
}

function isBuiltinSpecifier(node: Node, builtin: "crypto" | "module"): boolean {
  return (
    node.type === "Literal" &&
    (node.value === builtin || node.value === `node:${builtin}`)
  );
}

function isUnshadowedBuiltinIdentifier(identifier: Identifier, resolve: Resolve): boolean {
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

interface Candidate {
  readonly node: ESTree.CallExpression;
  readonly update: ESTree.CallExpression;
  readonly create: ESTree.CallExpression;
  readonly shared: boolean;
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { preferNodeCryptoHash: "Prefer the modern one-shot node:crypto hash API when streaming state is unnecessary." },
  },
  createOnce(context) {
    let directBindings = new Set<ScopeVariable>();
    let namespaceBindings = new Set<ScopeVariable>();
    let canonicalCreators = new Set<ScopeVariable>();
    let hashBindings = new Map<ScopeVariable, Identifier>();
    let unsafeAuthority: boolean | undefined;
    let sharedBindings = new Set<ScopeVariable>();
    let syncBindings = new Set<ScopeVariable>();
    let moduleBindings = new Set<ScopeVariable>();
    let namespaceStability = new WeakMap<ScopeVariable, boolean>();
    let candidates: Candidate[] = [];
    let possibleSynchronizations: ESTree.CallExpression[] = [];
    let sharedNamespaceUnsafe = false;

    function namespaceStable(variable: ScopeVariable): boolean {
      const cached = namespaceStability.get(variable);
      if (cached !== undefined) return cached;
      const stable = stableNamespace(variable);
      namespaceStability.set(variable, stable);
      return stable;
    }

    function resolve(identifier: Identifier): ScopeVariable | null {
      return findVariable(context.sourceCode.getScope(identifier), identifier.name);
    }

    function record(
      identifier: Identifier,
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

    function recordModuleImports(specifiers: ESTree.ImportDeclaration["specifiers"]): void {
      for (const specifier of specifiers) {
        if (specifier.type === "ImportSpecifier") {
          if (importSpecifierName(specifier) === "syncBuiltinESMExports") record(specifier.local, syncBindings);
          else if (importSpecifierName(specifier) === "default") record(specifier.local, moduleBindings);
        } else record(specifier.local, moduleBindings);
      }
    }

    function recordCanonicalImport(node: ESTree.ImportDeclaration): void {
      if (node.source.value !== "node:crypto" || node.importKind === "type") return;
      for (const specifier of node.specifiers) {
        if (specifier.type !== "ImportSpecifier" || specifier.importKind === "type") continue;
        const binding = resolve(specifier.local);
        if (binding === null) continue;
        const name = importSpecifierName(specifier);
        if (name === "hash") hashBindings.set(binding, specifier.local);
        if (name === "createHash") canonicalCreators.add(binding);
      }
    }

    function existingHashFix({ node, update, create }: Candidate): FixFn | null {
      if (hashBindings.size === 0 || canonicalCreators.size === 0) return null;
      const { sourceCode } = context;
      const constructor = unwrapExpression(create.callee);
      if (sourceCode.getCommentsInside(node).length > 0 || constructor.type !== "Identifier" ||
        !hasLiteralSha256HexArguments(node, update, create) || ![create, update, node].every(isPlainCall) ||
        hashMayBeRebound()) return null;
      const creator = resolve(constructor);
      if (creator === null || !canonicalCreators.has(creator) || !hasOnlyDirectFactoryUses(creator) ||
        !hasRetainedFactoryCall(creator, candidates.map((candidate) => candidate.node))) return null;
      const hash = visibleHashImport(node);
      if (hash === undefined) return null;
      // Each call has exactly one argument: algorithm, data, encoding.
      const args = [create, update, node].flatMap((call) => call.arguments).map((argument) => sourceCode.getText(argument));
      const text = `${sourceCode.getText(hash)}(${args.join(", ")})`;
      return (fixer) => fixer.replaceText(node, text);
    }

    /** Test, story, setup and mocking files, or files that reach crypto through reflection, may rebind `hash`. */
    function hashMayBeRebound(): boolean {
      const { sourceCode } = context;
      const file = { filename: context.filename, cwd: context.cwd };
      unsafeAuthority ??= hasUnsafeHashAuthority(sourceCode) || isGeneratedFile(file, sourceCode.text) ||
        isTestFile(file, ["fixtureTree"]) || isStoryFile(file, ["storyTree"]) || SUPPORT_FILE_RE.test(context.filename);
      return unsafeAuthority;
    }

    /** An imported `hash` already called directly elsewhere and visible, unshadowed, at `node`. */
    function visibleHashImport(node: Node): Identifier | undefined {
      const scope = context.sourceCode.getScope(node);
      for (const [binding, identifier] of hashBindings) {
        if (binding.references.some((reference) => reference.isValueReference && reference.isRead()) &&
          hasOnlyDirectFactoryUses(binding) && findVariable(scope, identifier.name) === binding) return identifier;
      }
      return undefined;
    }

    return {
      before() {
        const text = context.sourceCode.text;
        if (!text.includes("crypto") && !text.includes("\\")) return false;
        directBindings = new Set();
        namespaceBindings = new Set();
        canonicalCreators = new Set();
        hashBindings = new Map();
        unsafeAuthority = undefined;
        sharedBindings = new Set();
        syncBindings = new Set();
        moduleBindings = new Set();
        namespaceStability = new WeakMap();
        candidates = [];
        possibleSynchronizations = [];
        sharedNamespaceUnsafe = false;
        return undefined;
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        recordCanonicalImport(node);
        if (node.source.value === "module" || node.source.value === "node:module") {
          recordModuleImports(node.specifiers);
          return;
        }
        if (node.source.value !== "crypto" && node.source.value !== "node:crypto") return;
        for (const specifier of node.specifiers) {
          const shared = specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "default");
          if (specifier.type === "ImportNamespaceSpecifier" || shared) {
            record(specifier.local, namespaceBindings, shared);
            const variable = resolve(specifier.local);
            if (!shared && variable !== null && namespaceDefaultMayEscape(variable)) sharedNamespaceUnsafe = true;
          } else if (
            specifier.type === "ImportSpecifier" &&
            importSpecifierName(specifier) === "createHash"
          ) {
            record(specifier.local, directBindings);
          }
        }
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        if ((parentOf(node) as ESTree.VariableDeclaration).kind !== "const" || node.init === null) return;
        const crypto = isBuiltinLoader(node.init, resolve);
        if (!crypto && !isBuiltinLoader(node.init, resolve, "module")) return;
        if (node.id.type === "Identifier") {
          record(node.id, crypto ? namespaceBindings : moduleBindings, crypto);
          return;
        }
        if (node.id.type !== "ObjectPattern") return;
        for (const property of node.id.properties) {
          if (
            property.type === "Property" &&
            propertyName(property) === (crypto ? "createHash" : "syncBuiltinESMExports") &&
            property.value.type === "Identifier"
          ) {
            record(property.value, crypto ? directBindings : syncBindings, crypto);
          }
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (isBuiltinLoader(node, resolve) && !readonlyLoaderUse(node, resolve, namespaceStable)) sharedNamespaceUnsafe = true;
        const callee = unwrapExpression(node.callee);
        if (callee.type === "Identifier" ||
          (callee.type === "MemberExpression" && getPropertyName(callee) === "syncBuiltinESMExports")) possibleSynchronizations.push(node);
        const chain = digestChain(node);
        if (chain === null) return;
        const provider = builtinCallProvider(chain.create, directBindings, namespaceBindings, sharedBindings, resolve);
        if (provider !== null) candidates.push({ node, ...chain, shared: provider === "shared" });
      },
      "Program:exit"(): void {
        const exportsMaySynchronize = sharedNamespaceUnsafe && possibleSynchronizations.some((node) =>
          builtinCallProvider(node, syncBindings, moduleBindings, sharedBindings, resolve, "module") !== null);
        for (const candidate of candidates) {
          if (!sharedNamespaceUnsafe || (!candidate.shared && !exportsMaySynchronize)) {
            const fix = existingHashFix(candidate);
            context.report({ node: candidate.node, messageId: "preferNodeCryptoHash", ...(fix !== null && { fix }) });
          }
        }
      },
    };
  },
});


/** The `update` and `create` calls of `create(algorithm).update(data).digest(…)`. */
function digestChain(node: ESTree.CallExpression): Pick<Candidate, "update" | "create"> | null {
  const update = memberCallReceiver(node, "digest");
  if (update?.type !== "CallExpression" || update.arguments.length !== 1) return null;
  const create = memberCallReceiver(update, "update");
  if (create?.type !== "CallExpression" || create.arguments.length !== 1) return null;
  const [algorithm] = create.arguments;
  return algorithm !== undefined && staticString(unwrapExpression(algorithm)) !== null ? { update, create } : null;
}

/** The receiver of a `receiver.name(…)` call, past erased TypeScript wrappers. */
function memberCallReceiver(node: ESTree.CallExpression, name: string): Node | null {
  const callee = unwrapExpression(node.callee);
  return callee.type === "MemberExpression" && getPropertyName(callee) === name ? unwrapExpression(callee.object) : null;
}

/** `createHash("sha256").update("<string>").digest("hex")`. */
function hasLiteralSha256HexArguments(
  node: ESTree.CallExpression,
  update: ESTree.CallExpression,
  create: ESTree.CallExpression,
): boolean {
  const [algorithm] = create.arguments;
  const [data] = update.arguments;
  const [encoding] = node.arguments;
  return algorithm?.type === "Literal" && algorithm.value === "sha256" &&
    data?.type === "Literal" && typeof data.value === "string" &&
    node.arguments.length === 1 && encoding?.type === "Literal" && encoding.value === "hex";
}

/** No optional chaining and no type arguments, so the call can be rewritten as written. */
function isPlainCall(call: ESTree.CallExpression): boolean {
  const callee = unwrapExpression(call.callee);
  return !call.optional && !isPresent(call.typeArguments) && (callee.type !== "MemberExpression" || !callee.optional);
}

function builtinCallProvider(
  node: ESTree.CallExpression,
  directBindings: ReadonlySet<ScopeVariable>,
  namespaceBindings: ReadonlySet<ScopeVariable>,
  sharedBindings: ReadonlySet<ScopeVariable>,
  resolve: Resolve,
  builtin: "crypto" | "module" = "crypto",
): "shared" | "snapshot" | null {
  const unwrappedNodeCallee = unwrapExpression(node.callee);
  if (unwrappedNodeCallee.type === "Identifier") {
    const variable = resolve(unwrappedNodeCallee);
    if (variable === null || !directBindings.has(variable)) return null;
    return sharedBindings.has(variable) ? "shared" : "snapshot";
  }
  if (
    unwrappedNodeCallee.type !== "MemberExpression" ||
    getPropertyName(unwrappedNodeCallee) !== (builtin === "crypto" ? "createHash" : "syncBuiltinESMExports")
  ) {
    return null;
  }
  if (isBuiltinLoader(unwrappedNodeCallee.object, resolve, builtin)) return "shared";
  if (unwrappedNodeCallee.object.type !== "Identifier") return null;
  const variable = resolve(unwrappedNodeCallee.object);
  if (variable === null || !namespaceBindings.has(variable)) return null;
  return sharedBindings.has(variable) ? "shared" : "snapshot";
}

function hasUnsafeHashAuthority(sourceCode: SourceCode): boolean {
  const root = sourceCode.ast;
  if (UNSAFE_AUTHORITY_IDENTIFIERS.some((name) => hasIdentifierNamed(sourceCode, name)) || hasUnknownCryptoImport(root)) return true;
  const pending: Node[] = [root];
  const visited = new WeakSet<Node>();
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined || visited.has(node)) continue;
    visited.add(node);
    if (node.type === "ImportExpression" || node.type === "TSModuleDeclaration") return true;
    if (node.type === "MemberExpression") {
      const name = getPropertyName(node);
      if (name === null || UNSAFE_AUTHORITY_MEMBERS.has(name)) return true;
    }
    forEachOwnAstChild(node, (child) => { pending.push(child); }, (key) => key !== "tokens" && key !== "comments");
  }
  return false;
}

function hasUnknownCryptoImport(root: ESTree.Program): boolean {
  for (const statement of root.body) {
    if (statement.type !== "ImportDeclaration" || statement.importKind === "type") continue;
    if (statement.source.value !== "node:crypto" || statement.specifiers.length === 0) return true;
    if (statement.specifiers.some((specifier) => specifier.type !== "ImportSpecifier" ||
      (specifier.importKind !== "type" && !["createHash", "hash"].includes(importSpecifierName(specifier))))) return true;
  }
  return false;
}

function hasRetainedFactoryCall(binding: ScopeVariable, removed: readonly ESTree.CallExpression[]): boolean {
  return binding.references.some((reference) => {
    const identifier = reference.identifier;
    const parent = parentOf(identifier);
    if (!reference.isValueReference || !reference.isRead() || parent?.type !== "CallExpression" ||
      parent.callee !== identifier) return false;
    return !removed.some((node) => node.range[0] <= identifier.range[0] && identifier.range[1] <= node.range[1]);
  });
}

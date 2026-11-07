/**
 * @fileoverview _create-source-coupled-rule — shared factory for `source-coupled-test` and
 * `iac-source-coupled-test`.
 *
 * Oxlint port of `createSourceCoupledRule` in the 18.x `source-coupled-test` rule.
 * Same algorithm; per-file state is reset in `before()`, and the `:function`
 * selector is spelled as the three function node types it matches.
 */

import { posix, win32 } from "node:path";

import type { ESTree, Node, SarjRule, TsVariable } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName as importedName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const REPRESENTATION_DIR_RE = /(?:^|\/)(?:__fixtures__|fixtures?|goldens?|snapshots?)(?:\/|$)/iu;
const PATH_MODULES: ReadonlySet<string> = new Set(["path", "node:path"]);
const FS_MODULES: ReadonlySet<string> = new Set(["fs", "node:fs", "fs/promises", "node:fs/promises"]);
const FS_READERS: ReadonlySet<string> = new Set(["readFile", "readFileSync"]);
const TEXT_TRANSFORMS: ReadonlySet<string> = new Set([
  "slice",
  "substring",
  "substr",
  "toLowerCase",
  "toString",
  "toUpperCase",
  "trim",
  "trimEnd",
  "trimStart",
  "replace",
  "replaceAll",
  "split",
]);
const TEXT_PREDICATES: ReadonlySet<string> = new Set(["endsWith", "includes", "indexOf", "lastIndexOf", "match", "matchAll", "search", "startsWith"]);
const REGEXP_PREDICATES: ReadonlySet<string> = new Set(["exec", "test"]);
const EXPECT_MATCHERS: ReadonlySet<string> = new Set([
  "toBe",
  "toBeFalsy",
  "toBeGreaterThan",
  "toBeGreaterThanOrEqual",
  "toBeLessThan",
  "toBeLessThanOrEqual",
  "toBeNull",
  "toBeTruthy",
  "toContain",
  "toEqual",
  "toHaveLength",
  "toMatch",
  "toMatchSnapshot",
  "toStrictEqual",
]);
const EXPECT_MODIFIERS: ReadonlySet<string> = new Set(["not", "rejects", "resolves"]);
const ASSERT_MATCHERS: ReadonlySet<string> = new Set(["deepEqual", "doesNotMatch", "equal", "match", "notDeepEqual", "notEqual", "notStrictEqual", "ok", "strictEqual"]);
const EXPECT_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "vitest"]);
const ASSERT_MODULES: ReadonlySet<string> = new Set(["assert", "assert/strict", "node:assert", "node:assert/strict"]);
const URL_MODULES: ReadonlySet<string> = new Set(["node:url", "url"]);
const TEMP_DIRECTORY_FACTORIES: ReadonlySet<string> = new Set(["mkdtemp", "mkdtempSync"]);
const REPLACE_METHODS: ReadonlySet<string> = new Set(["replace", "replaceAll"]);
const EQUALITY_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);
const INEQUALITY_ASSERTIONS: ReadonlySet<string> = new Set(["notEqual", "notStrictEqual"]);

const MESSAGE = "Raw repository source text is the oracle. Reuse adequate existing validation; otherwise assert a distinct parsed or runtime contract. Preserve a deliberate representation contract with an exact justified suppression.";

type Argument = ESTree.Argument;

interface LexicalScope {
  readonly collections: Set<TsVariable>;
  readonly declared: Set<TsVariable>;
  readonly fsObjects: Set<TsVariable>;
  readonly fsReaders: Set<TsVariable>;
  readonly paths: Set<TsVariable>;
  readonly rawOrigins: Map<TsVariable, Set<string>>;
}

function unwrap(node: Node): Node {
  for (;;) {
    node = unwrapExpression(node);
    if (node.type === "AwaitExpression") node = node.argument;
    else if (node.type === "ChainExpression") node = node.expression;
    else return node;
  }
}

function stringValue(node: Node): string | null {
  const current = unwrap(node);
  if (current.type === "Literal" && typeof current.value === "string") return current.value;
  if (current.type === "TemplateLiteral" && current.expressions.length === 0) return current.quasis[0]?.value.cooked ?? null;
  if (current.type === "BinaryExpression" && current.operator === "+") {
    const left = stringValue(current.left);
    const right = stringValue(current.right);
    return left === null || right === null ? null : left + right;
  }
  return null;
}

function relativePathDepth(normalized: string, initialDepth: number): number | null {
  let relativeDepth = initialDepth;
  for (const part of normalized.split("/")) {
    if (part === "..") {
      if (relativeDepth === 0) return null;
      relativeDepth -= 1;
    } else if (part !== "" && part !== ".") relativeDepth += 1;
  }
  return relativeDepth;
}

function staticPathSuffix(pathArguments: readonly Argument[], builder: "join" | "resolve"): string | null {
  const trailing: string[] = [];
  for (const argument of pathArguments.toReversed()) {
    if (argument.type === "SpreadElement") return null;
    const segment = stringValue(argument);
    if (segment === null) break;
    trailing.unshift(segment);
    if (builder === "resolve" && posix.isAbsolute(segment.replaceAll("\\", "/"))) break;
  }
  return trailing.length > 0 ? trailing.join("/") : null;
}

function requireSource(node: Node): string | null {
  const current = unwrap(node);
  if (
    current.type !== "CallExpression" ||
    current.callee.type !== "Identifier" ||
    current.callee.name !== "require" ||
    current.arguments.length !== 1 ||
    current.arguments[0]?.type === "SpreadElement"
  ) return null;
  return stringValue(current.arguments[0] as Node);
}

function newScope(): LexicalScope {
  return { collections: new Set(), declared: new Set(), fsObjects: new Set(), fsReaders: new Set(), paths: new Set(), rawOrigins: new Map() };
}

function importedAssertionKind(specifier: Node): "assert" | "expect" | null {
  if (
    (specifier.type !== "ImportSpecifier" &&
      specifier.type !== "ImportDefaultSpecifier" &&
      specifier.type !== "ImportNamespaceSpecifier") ||
    specifier.parent.type !== "ImportDeclaration"
  ) return null;
  const source = specifier.parent.source.value;
  if (ASSERT_MODULES.has(source)) {
    if (specifier.type !== "ImportSpecifier") return "assert";
    const imported = importedName(specifier);
    if (imported === "strict" || ASSERT_MATCHERS.has(imported)) return "assert";
    return null;
  }
  if (!EXPECT_MODULES.has(source) || specifier.type !== "ImportSpecifier") return null;
  const imported = importedName(specifier);
  if (imported === "assert" || imported === "expect") return imported;
  return null;
}

/** `text.replace(literal, literal)` or `replaceAll`, with a string or regex pattern. */
function isLiteralReplace(call: ESTree.CallExpression): boolean {
  if (call.arguments.length !== 2) return false;
  const callee = unwrap(call.callee);
  const [pattern, replacement] = call.arguments;
  return callee.type === "MemberExpression" && REPLACE_METHODS.has(getPropertyName(callee) ?? "") &&
    pattern !== undefined && replacement !== undefined && pattern.type !== "SpreadElement" && replacement.type !== "SpreadElement" &&
    (stringValue(pattern) !== null || isRegexLiteral(pattern)) && stringValue(replacement) !== null;
}

/** Literal `regex` presence, as the original's `"regex" in pattern`. */
function isRegexLiteral(node: Node): boolean {
  return node.type === "Literal" && (node as { regex?: unknown }).regex != null;
}

export function createSourceCoupledRule(name: string, summary: string, sourceSuffixRe: RegExp): SarjRule {
  return {
    meta: {
      type: "suggestion",
      docs: { description: summary, url: docsUrl(name) },
      schema: [],
      messages: { rawSourceOracle: MESSAGE },
    },
    createOnce(context) {
      let referenceStability = new Map<TsVariable, boolean>();
      let scopes: LexicalScope[] = [newScope()];
      const reportedOrigins = new Set<string>();
      let cwd = "";

      const referenceStable = (variable: TsVariable): boolean => {
        const cached = referenceStability.get(variable);
        if (cached !== undefined) return cached;
        const stable = !variable.references.some((reference) => reference.isWrite() && reference.init !== true);
        referenceStability.set(variable, stable);
        return stable;
      };
      const bindingOf = (node: ESTree.IdentifierReference | ESTree.BindingIdentifier | ESTree.IdentifierName | Node): TsVariable | null =>
        findVariable(context.sourceCode.getScope(node), (node as { name: string }).name);
      /** The innermost lexical scope that declares the node's stable binding. */
      const declaringScope = (node: Node): { scope: LexicalScope; variable: TsVariable } | null => {
        const variable = bindingOf(node);
        if (variable === null || !referenceStable(variable)) return null;
        for (let index = scopes.length - 1; index >= 0; index--) {
          const scope = scopes[index]!;
          if (scope.declared.has(variable)) return { scope, variable };
        }
        return null;
      };
      const visible = (kind: "collections" | "fsObjects" | "fsReaders" | "paths", node: Node): boolean => {
        const declared = declaringScope(node);
        return declared !== null && declared.scope[kind].has(declared.variable);
      };
      const sourcePath = (node: Node): boolean => {
        const current = unwrap(node);
        const value = stringValue(current);
        if (value !== null) return sourcePathValue(value);
        if (current.type === "Identifier") return visible("paths", current);
        return (current.type === "CallExpression" || current.type === "NewExpression") && derivedSourcePath(current);
      };
      /** `join(…)`/`resolve(…)` to a source path, or `new URL(path)`/`fileURLToPath(path)` around one. */
      const derivedSourcePath = (current: ESTree.CallExpression | ESTree.NewExpression): boolean => {
        const callee = unwrapExpression(current.callee);
        const first = current.arguments[0];
        if (first === undefined || first.type === "SpreadElement" || callee.type !== "Identifier") return false;
        const pathBuilder = current.type === "CallExpression" ? nativePathBuilder(callee) : null;
        if (current.type === "CallExpression" && pathBuilder !== null) {
          if (temporaryDescendant(current, pathBuilder)) return false;
          const suffix = staticPathSuffix(current.arguments, pathBuilder);
          return suffix !== null && sourcePathValue(suffix);
        }
        const globalUrl = current.type === "NewExpression" && callee.name === "URL" && (bindingOf(callee)?.defs.length ?? 0) === 0;
        return (globalUrl || isFileUrlToPath(callee)) && sourcePath(first);
      };
      /** `fileURLToPath` imported from `url` or `node:url`. */
      const isFileUrlToPath = (callee: Node): boolean => bindingOf(callee)?.defs.some((definition) => {
        const specifier = definition.node;
        return specifier.type === "ImportSpecifier" && (specifier.imported as Node).type === "Identifier" &&
          importedName(specifier) === "fileURLToPath" && specifier.parent.type === "ImportDeclaration" &&
          URL_MODULES.has(specifier.parent.source.value);
      }) === true;
      const nativePathBuilder = (node: Node): "join" | "resolve" | null => {
        const imported = nativeImportedName(node, PATH_MODULES);
        return imported === "join" || imported === "resolve" ? imported : null;
      };
      const nativeImportedName = (node: Node, modules: ReadonlySet<string>): string | null => {
        const binding = bindingOf(node);
        if (binding === null || !referenceStable(binding)) return null;
        for (const definition of binding.defs) {
          const imported = definition.node;
          if (imported.type === "ImportSpecifier" &&
            (imported.imported as Node).type === "Identifier" &&
            imported.parent.type === "ImportDeclaration" && modules.has(imported.parent.source.value)) {
            return importedName(imported);
          }
        }
        return null;
      };
      const stableInitializer = (node: Node): Node | null => {
        const binding = bindingOf(node);
        if (binding === null || !referenceStable(binding) || binding.defs.length !== 1) return null;
        const definition = binding.defs[0]?.node;
        return definition?.type === "VariableDeclarator" ? definition.init : null;
      };
      const temporaryDirectory = (node: Node, depth = 0): boolean => {
        if (depth > 8) return false;
        const current = unwrap(node);
        if (current.type === "Identifier") {
          const initializer = stableInitializer(current);
          return initializer !== null && temporaryDirectory(initializer, depth + 1);
        }
        if (current.type !== "CallExpression") return false;
        const callee = unwrap(current.callee);
        if (callee.type !== "Identifier") return false;
        if (TEMP_DIRECTORY_FACTORIES.has(nativeImportedName(callee, FS_MODULES) ?? "")) return true;
        const builder = nativePathBuilder(callee);
        return builder !== null && temporaryDescendant(current, builder, depth + 1);
      };
      const temporaryDescendant = (node: ESTree.CallExpression, builder: "join" | "resolve", depth = 0): boolean => {
        if (depth > 8) return false;
        const [directory, ...segments] = node.arguments;
        if (directory === undefined || directory.type === "SpreadElement" || !temporaryDirectory(directory, depth)) return false;
        let relativeDepth = 0;
        for (const segment of segments) {
          if (segment.type === "SpreadElement") return false;
          const value = stringValue(segment);
          if (value === null) return false;
          const normalized = value.replaceAll("\\", "/");
          if (builder === "resolve" && (posix.isAbsolute(normalized) || win32.parse(normalized).root !== "")) return false;
          const nextDepth = relativePathDepth(normalized, relativeDepth);
          if (nextDepth === null) return false;
          relativeDepth = nextDepth;
        }
        return relativeDepth > 0;
      };
      const sourcePathValue = (value: string): boolean => {
        const normalized = posix.normalize(value.replaceAll("\\", "/"));
        return sourceSuffixRe.test(normalized) && !REPRESENTATION_DIR_RE.test(normalized) && !isGeneratedFile({ filename: normalized, cwd });
      };
      const rawOrigins = (node: Node): Set<string> => {
        const current = unwrap(node);
        if (current.type === "Identifier") return visibleRawOrigins(current);
        if (rawRead(current)) return new Set([`${current.range[0]}:${current.range[1]}`]);
        if (current.type === "BinaryExpression" && current.operator === "+") return new Set([...rawOrigins(current.left), ...rawOrigins(current.right)]);
        if (current.type === "MemberExpression" && getPropertyName(current) === "length") return rawOrigins(current.object);
        if (current.type !== "CallExpression") return new Set();
        const callee = unwrap(current.callee);
        if (callee.type !== "MemberExpression") return new Set();
        const calleeReceiver = unwrapExpression(callee.object);
        const property = getPropertyName(callee);
        return property !== null && TEXT_TRANSFORMS.has(property) ? rawOrigins(calleeReceiver) : new Set();
      };

      const rawRead = (node: Node): boolean => {
        const current = unwrap(node);
        if (current.type !== "CallExpression" || current.arguments.length === 0) return false;
        const callee = unwrap(current.callee);
        const calleeReceiver = callee.type === "MemberExpression" ? unwrapExpression(callee.object) : callee;
        if (callee.type === "Identifier") {
          return visible("fsReaders", callee) && sourcePath(current.arguments[0] as Node);
        }
        if (callee.type !== "MemberExpression") return false;
        const property = getPropertyName(callee);
        const object = unwrap(calleeReceiver);
        return property !== null && FS_READERS.has(property) && object.type === "Identifier" && visible("fsObjects", object) && sourcePath(current.arguments[0] as Node);
      };

      const visibleRawOrigins = (node: Node): Set<string> => {
        const declared = declaringScope(node);
        return declared?.scope.rawOrigins.get(declared.variable) ?? new Set();
      };
      const evidenceOrigins = (node: Node): Set<string> => {
        const current = unwrap(node);
        const direct = rawOrigins(current);
        if (direct.size > 0) return direct;
        if (current.type === "BinaryExpression" || current.type === "LogicalExpression") return new Set([...evidenceOrigins(current.left), ...evidenceOrigins(current.right)]);
        if (current.type === "UnaryExpression") return evidenceOrigins(current.argument);
        if (current.type !== "CallExpression") return new Set();
        const callee = unwrap(current.callee);
        if (callee.type !== "MemberExpression") return new Set();
        const calleeReceiver = unwrapExpression(callee.object);
        const property = getPropertyName(callee);
        if (property !== null && TEXT_PREDICATES.has(property)) return rawOrigins(calleeReceiver);
        if (property !== null && REGEXP_PREDICATES.has(property)) return new Set(current.arguments.flatMap((argument) => argument.type === "SpreadElement" ? [] : [...rawOrigins(argument)]));
        return new Set();
      };
      const rawAssertionOrigins = (node: ESTree.CallExpression): Set<string> => {
        const callee = unwrap(node.callee);
        if (callee.type === "Identifier" && assertionKind(callee) === "assert") return argumentEvidence(node.arguments);
        if (callee.type !== "MemberExpression") return new Set();
        const matcher = getPropertyName(callee);
        if (matcher === null) return new Set();
        const calleeReceiver = unwrapExpression(callee.object);
        let receiver = unwrap(calleeReceiver);
        while (receiver.type === "MemberExpression" && EXPECT_MODIFIERS.has(getPropertyName(receiver) ?? "")) receiver = unwrap(receiver.object);
        const expectCallee = receiver.type === "CallExpression" ? unwrapExpression(receiver.callee) : null;
        if (receiver.type === "CallExpression" && expectCallee?.type === "Identifier" && assertionKind(expectCallee) === "expect") {
          return expectAssertionOrigins(node, receiver, matcher, calleeReceiver);
        }
        return receiver.type === "Identifier" && assertionKind(receiver) === "assert" ? assertMethodOrigins(node, matcher) : new Set();
      };
      /** `assert.matcher(…)`; an inequality between a value and its literal mutation is a guard. */
      const assertMethodOrigins = (node: ESTree.CallExpression, matcher: string): Set<string> => {
        if (!ASSERT_MATCHERS.has(matcher)) return new Set();
        if (INEQUALITY_ASSERTIONS.has(matcher) && mutationGuard(node.arguments)) return new Set();
        return argumentEvidence(node.arguments);
      };
      /** `expect(actual)[.not].matcher(expected)`; a negated equality between a value and its literal mutation is a guard. */
      const expectAssertionOrigins = (node: ESTree.CallExpression, expectCall: ESTree.CallExpression, matcher: string, calleeReceiver: Node): Set<string> => {
        if (!EXPECT_MATCHERS.has(matcher)) return new Set();
        const operands = [...expectCall.arguments, ...node.arguments];
        const negated = calleeReceiver.type === "MemberExpression" && getPropertyName(calleeReceiver) === "not";
        if (EQUALITY_MATCHERS.has(matcher) && negated && mutationGuard(operands)) return new Set();
        return argumentEvidence(operands);
      };

      const argumentEvidence = (operands: readonly Argument[]): Set<string> =>
        new Set(operands.flatMap((argument) => argument.type === "SpreadElement" ? [] : [...evidenceOrigins(argument)]));

      const mutationGuard = (operands: readonly Argument[]): boolean => {
        if (operands.length !== 2) return false;
        const [left, right] = operands;
        if (left === undefined || right === undefined || left.type === "SpreadElement" || right.type === "SpreadElement" || (!literalMutation(left) && !literalMutation(right))) return false;
        const leftOrigins = rawOrigins(left);
        const rightOrigins = rawOrigins(right);
        return leftOrigins.size > 0 && leftOrigins.size === rightOrigins.size && [...leftOrigins].every((origin) => rightOrigins.has(origin));
      };

      const literalMutation = (node: Node, depth = 0): boolean => {
        if (depth > 8) return false;
        const current = unwrap(node);
        if (current.type === "Identifier") {
          const initializer = stableInitializer(current);
          return initializer !== null && literalMutation(initializer, depth + 1);
        }
        return current.type === "CallExpression" && isLiteralReplace(current);
      };

      const assertionKind = (node: Node & { name: string }): "assert" | "expect" | null => {
        const binding = bindingOf(node);
        if (binding === null || binding.defs.length === 0) {
          const identifier: string = node.name;
          return identifier === "assert" || identifier === "expect" ? identifier : null;
        }
        for (const definition of binding.defs) {
          const kind = importedAssertionKind(definition.node);
          if (kind !== null) return kind;
        }
        return null;
      };
      const declare = (node: Node, state: { collection?: boolean; fsObject?: boolean; fsReader?: boolean; path?: boolean; rawOrigins?: Set<string> }): void => {
        const variable = bindingOf(node);
        if (variable === null) return;
        const scope = currentScope();
        scope.declared.add(variable);
        scope.collections.delete(variable);
        scope.fsObjects.delete(variable);
        scope.fsReaders.delete(variable);
        scope.paths.delete(variable);
        scope.rawOrigins.delete(variable);
        if (state.collection === true) scope.collections.add(variable);
        if (state.fsObject === true) scope.fsObjects.add(variable);
        if (state.fsReader === true) scope.fsReaders.add(variable);
        if (state.path === true) scope.paths.add(variable);
        if (state.rawOrigins !== undefined && state.rawOrigins.size > 0) scope.rawOrigins.set(variable, state.rawOrigins);
      };

      const currentScope = (): LexicalScope => scopes.at(-1)!;
      const sourceCollection = (node: Node): boolean => {
        const current = unwrap(node);
        return current.type === "ArrayExpression" && current.elements.length > 0 &&
          current.elements.every((element) => element !== null && element.type !== "SpreadElement" && sourcePath(element));
      };
      const enterFunction = (): void => { scopes.push(newScope()); };
      const exitFunction = (): void => { scopes.pop(); };

      function declareFsReaders(pattern: ESTree.ObjectPattern): void {
        for (const property of pattern.properties) {
          if (property.type !== "Property" || property.value.type !== "Identifier") continue;
          const key = property.key as Node;
          const keyName = key.type === "Identifier" ? key.name : key.type === "Literal" ? String(key.value) : "";
          if (FS_READERS.has(keyName)) declare(property.value, { fsReader: true });
        }
      }

      return {
        before() {
          referenceStability = new Map();
          scopes = [newScope()];
          reportedOrigins.clear();
          cwd = context.cwd;
          const file = { filename: context.filename, cwd };
          return isTestFile(file) && !isGeneratedFile(file, context.sourceCode.text);
        },
        ImportDeclaration(node) {
          if (!FS_MODULES.has(node.source.value)) return;
          for (const specifier of node.specifiers) {
            if (specifier.type === "ImportSpecifier") {
              if (FS_READERS.has(importedName(specifier))) declare(specifier.local, { fsReader: true });
            } else {
              declare(specifier.local, { fsObject: true });
            }
          }
        },
        FunctionDeclaration: enterFunction,
        FunctionExpression: enterFunction,
        ArrowFunctionExpression: enterFunction,
        "FunctionDeclaration:exit": exitFunction,
        "FunctionExpression:exit": exitFunction,
        "ArrowFunctionExpression:exit": exitFunction,
        VariableDeclarator(node) {
          if (node.init === null) return;
          const required = requireSource(node.init);
          const initializer = unwrap(node.init);
          if (required !== null && initializer.type === "CallExpression" && initializer.callee.type === "Identifier" && (bindingOf(initializer.callee)?.defs.length ?? 0) > 0) return;
          if (required !== null && FS_MODULES.has(required) && node.id.type === "Identifier") {
            declare(node.id, { fsObject: true });
            return;
          }
          if (node.id.type === "ObjectPattern" && required !== null && FS_MODULES.has(required)) {
            declareFsReaders(node.id);
            return;
          }
          if (node.id.type !== "Identifier") return;
          declare(node.id, { collection: sourceCollection(node.init), path: sourcePath(node.init), rawOrigins: rawOrigins(node.init) });
        },
        AssignmentExpression(node) {
          if (node.left.type === "Identifier") declare(node.left, {});
        },
        ForOfStatement(node) {
          const right = unwrap(node.right);
          const collection = right.type === "Identifier" && visible("collections", right);
          const left = node.left.type === "VariableDeclaration" ? node.left.declarations[0]?.id : node.left;
          if (collection && left?.type === "Identifier") declare(left, { path: true });
        },
        CallExpression(node) {
          const origins = rawAssertionOrigins(node);
          if (origins.size === 0 || [...origins].every((origin) => reportedOrigins.has(origin))) return;
          for (const origin of origins) reportedOrigins.add(origin);
          context.report({ node, messageId: "rawSourceOracle" });
        },
      };
    },
  };
}

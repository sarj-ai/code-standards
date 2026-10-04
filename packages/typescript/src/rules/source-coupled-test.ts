/**
 * @fileoverview source-coupled-test — raw repository source text is not a behavioral oracle.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/source-coupled-test.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "rawSourceOracle";
type Options = readonly [];

const GENERAL_SOURCE_SUFFIX_RE = /\.(?:bash|sh|ya?ml|jsonc?|toml|py|[cm]?[jt]s)$/iu;
const FS_MODULES = new Set(["fs", "node:fs", "fs/promises", "node:fs/promises"]);
const FS_READERS = new Set(["readFile", "readFileSync"]);
const TEXT_TRANSFORMS = new Set([
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
const TEXT_PREDICATES = new Set(["endsWith", "includes", "indexOf", "lastIndexOf", "match", "matchAll", "search", "startsWith"]);
const REGEXP_PREDICATES = new Set(["exec", "test"]);
const EXPECT_MATCHERS = new Set([
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
const EXPECT_MODIFIERS = new Set(["not", "rejects", "resolves"]);
const ASSERT_MATCHERS = new Set(["deepEqual", "doesNotMatch", "equal", "match", "notDeepEqual", "notEqual", "notStrictEqual", "ok", "strictEqual"]);
const EXPECT_MODULES = new Set(["@jest/globals", "@playwright/test", "bun:test", "vitest"]);
const ASSERT_MODULES = new Set(["assert", "assert/strict", "node:assert", "node:assert/strict"]);

interface LexicalScope {
  readonly collections: Set<Variable>;
  readonly declared: Set<Variable>;
  readonly fsObjects: Set<Variable>;
  readonly fsReaders: Set<Variable>;
  readonly paths: Set<Variable>;
  readonly rawOrigins: Map<Variable, Set<string>>;
}

export const SOURCE_COUPLED_TEST_DOCUMENTATION = {
  summary: "Disallow raw repository source text as a test oracle; parse or execute the artifact instead.",
  rationale: "Substring and regex checks can pass on comments or unreachable configuration and fail after behavior-preserving formatting changes.",
  remediation: "Parse the artifact, execute its validator, or assert on another runtime contract.",
  category: "testing",
  limitations: [
    "The rule follows stable lexical bindings, static source paths, awaited reads, and common text operations. Reassigned bindings, dynamic paths, unknown path wrappers, iterator pipelines, and interprocedural flows remain unreported.",
    "Assertion roots are scope-resolved for supported test runners and Node assert imports; local or unknown helpers with assertion-like names are not inferred.",
    "When raw representation is genuinely the contract (for example a golden or compatibility sentinel), use an exact line suppression with the reason.",
  ],
  examples: [
    {
      id: "parsed-policy-contract",
      title: "Assert on parsed policy behavior",
      outcome: "no-match",
      files: [{ path: "src/policy.test.ts", source: "import { readFileSync } from 'node:fs'; test('policy', () => { const policy = JSON.parse(readFileSync('policy.json', 'utf8')); expect(validate(policy)).toEqual([]); });" }],
      focusPath: "src/policy.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "workflow-substring-contract",
      title: "Do not prove workflow behavior with a regex",
      outcome: "match",
      files: [{ path: "src/policy.test.ts", source: "import { readFileSync } from 'node:fs'; test('policy', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toMatch(/permissions/); });" }],
      focusPath: "src/policy.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function staticMemberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  if (node.computed && node.property.type === "Literal" && typeof node.property.value === "string") return node.property.value;
  return null;
}

function unwrap(node: ESTree.Node): ESTree.Node {
  if (node.type === "AwaitExpression") return unwrap(node.argument);
  if (node.type === "ChainExpression") return unwrap(node.expression);
  if (
    node.type === "TSAsExpression" ||
    node.type === "TSNonNullExpression" ||
    node.type === "TSTypeAssertion"
  ) return unwrap(node.expression);
  return node;
}

function stringValue(node: ESTree.Node): string | null {
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

function importSource(node: ESTree.ImportDeclaration): string | null {
  return typeof node.source.value === "string" ? node.source.value : null;
}

function requireSource(node: ESTree.Node): string | null {
  const current = unwrap(node);
  if (
    current.type !== "CallExpression" ||
    current.callee.type !== "Identifier" ||
    current.callee.name !== "require" ||
    current.arguments.length !== 1 ||
    current.arguments[0]?.type === "SpreadElement"
  ) return null;
  return stringValue(current.arguments[0] as ESTree.Node);
}

function newScope(): LexicalScope {
  return { collections: new Set(), declared: new Set(), fsObjects: new Set(), fsReaders: new Set(), paths: new Set(), rawOrigins: new Map() };
}

export function createSourceCoupledRule(
  name: string,
  documentation: RuleDocumentation,
  sourceSuffixRe: RegExp,
) {
  return createRule<Options, MessageIds>({
  name,
  documentation,
  meta: {
    type: "suggestion",
    docs: { description: documentation.summary },
    schema: [],
    messages: { rawSourceOracle: "Raw repository source text is the oracle. Parse or execute the artifact so comments, formatting, and unreachable blocks cannot satisfy the contract." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(sourceOrigin(context).filename) || isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};

    const scopes: LexicalScope[] = [newScope()];
    const reportedOrigins = new Set<string>();
    const currentScope = (): LexicalScope => scopes.at(-1) ?? scopes[0]!;
    const bindingOf = (node: ESTree.BindingIdentifier) => findVariable(context.sourceCode.getScope(node), node.name);
    const assertionKind = (node: ESTree.BindingIdentifier): "assert" | "expect" | null => {
      const binding = bindingOf(node);
      if (binding === null || binding.defs.length === 0) {
        return node.name === "assert" || node.name === "expect" ? node.name : null;
      }
      for (const definition of binding.defs) {
        const kind = importedAssertionKind(definition.node);
        if (kind !== null) return kind;
      }
      return null;
    };
    const visible = (kind: "collections" | "fsObjects" | "fsReaders" | "paths", node: ESTree.BindingIdentifier): boolean => {
      const name = bindingOf(node);
      if (name === null || name.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
      for (let index = scopes.length - 1;index >= 0;index--) {
        const scope = scopes[index]!;
        if (scope.declared.has(name)) return scope[kind].has(name);
      }
      return false;
    };
    const visibleRawOrigins = (node: ESTree.BindingIdentifier): Set<string> => {
      const name = bindingOf(node);
      if (name === null || name.references.some((reference) => reference.isWrite() && reference.init !== true)) return new Set();
      for (let index = scopes.length - 1;index >= 0;index--) {
        const scope = scopes[index]!;
        if (scope.declared.has(name)) return scope.rawOrigins.get(name) ?? new Set();
      }
      return new Set();
    };
    const sourcePath = (node: ESTree.Node): boolean => {
      const current = unwrap(node);
      const value = stringValue(current);
      if (value !== null) return sourceSuffixRe.test(value);
      if (current.type === "Identifier") return visible("paths", current);
      if (current.type === "CallExpression" || current.type === "NewExpression") {
        const callee = current.callee;
        const first = current.arguments[0];
        if (first === undefined || first.type === "SpreadElement") return false;
        if (current.type === "NewExpression" && callee.type === "Identifier" && callee.name === "URL" && (bindingOf(callee)?.defs.length ?? 0) === 0) return sourcePath(first);
        if (callee.type === "Identifier" && bindingOf(callee)?.defs.some((definition) =>
          definition.node.type === "ImportSpecifier" && definition.node.imported.type === "Identifier" &&
          definition.node.imported.name === "fileURLToPath" && definition.node.parent?.type === "ImportDeclaration" &&
          ["node:url", "url"].includes(String(definition.node.parent.source.value)))) return sourcePath(first);
      }
      return false;
    };
    const rawRead = (node: ESTree.Node): boolean => {
      const current = unwrap(node);
      if (current.type !== "CallExpression" || current.arguments.length === 0) return false;
      const callee = unwrap(current.callee);
      if (callee.type === "Identifier") {
        return visible("fsReaders", callee) && sourcePath(current.arguments[0] as ESTree.Node);
      }
      if (callee.type !== "MemberExpression") return false;
      const name = staticMemberName(callee);
      const object = unwrap(callee.object);
      return name !== null && FS_READERS.has(name) && object.type === "Identifier" && visible("fsObjects", object) && sourcePath(current.arguments[0] as ESTree.Node);
    };
    const rawOrigins = (node: ESTree.Node): Set<string> => {
      const current = unwrap(node);
      if (current.type === "Identifier") return visibleRawOrigins(current);
      if (rawRead(current)) return new Set([`${current.range[0]}:${current.range[1]}`]);
      if (current.type === "BinaryExpression" && current.operator === "+") return new Set([...rawOrigins(current.left), ...rawOrigins(current.right)]);
      if (current.type === "MemberExpression" && staticMemberName(current) === "length") return rawOrigins(current.object);
      if (current.type !== "CallExpression") return new Set();
      const callee = unwrap(current.callee);
      if (callee.type !== "MemberExpression") return new Set();
      const name = staticMemberName(callee);
      return name !== null && TEXT_TRANSFORMS.has(name) ? rawOrigins(callee.object) : new Set();
    };
    const evidenceOrigins = (node: ESTree.Node): Set<string> => {
      const current = unwrap(node);
      const direct = rawOrigins(current);
      if (direct.size > 0) return direct;
      if (current.type === "BinaryExpression" || current.type === "LogicalExpression") return new Set([...evidenceOrigins(current.left), ...evidenceOrigins(current.right)]);
      if (current.type === "UnaryExpression") return evidenceOrigins(current.argument);
      if (current.type !== "CallExpression") return new Set();
      const callee = unwrap(current.callee);
      if (callee.type !== "MemberExpression") return new Set();
      const name = staticMemberName(callee);
      if (name !== null && TEXT_PREDICATES.has(name)) return rawOrigins(callee.object);
      if (name !== null && REGEXP_PREDICATES.has(name)) return new Set(current.arguments.flatMap((argument) => argument.type === "SpreadElement" ? [] : [...rawOrigins(argument)]));
      return new Set();
    };
    const rawAssertionOrigins = (node: ESTree.CallExpression): Set<string> => {
      const callee = unwrap(node.callee);
      if (callee.type === "Identifier" && assertionKind(callee) === "assert") {
        return new Set(node.arguments.flatMap((argument) => argument.type === "SpreadElement" ? [] : [...evidenceOrigins(argument)]));
      }
      if (callee.type !== "MemberExpression") return new Set();
      const matcher = staticMemberName(callee);
      if (matcher === null) return new Set();
      let receiver = unwrap(callee.object);
      while (receiver.type === "MemberExpression" && EXPECT_MODIFIERS.has(staticMemberName(receiver) ?? "")) receiver = unwrap(receiver.object);
      if (receiver.type === "CallExpression" && receiver.callee.type === "Identifier" && assertionKind(receiver.callee) === "expect") {
        if (!EXPECT_MATCHERS.has(matcher)) return new Set();
        return new Set([...receiver.arguments, ...node.arguments].flatMap((argument) => argument.type === "SpreadElement" ? [] : [...evidenceOrigins(argument)]));
      }
      if (receiver.type !== "Identifier" || assertionKind(receiver) !== "assert" || !ASSERT_MATCHERS.has(matcher)) return new Set();
      return new Set(node.arguments.flatMap((argument) => argument.type === "SpreadElement" ? [] : [...evidenceOrigins(argument)]));
    };
    const declare = (node: ESTree.BindingIdentifier, state: { collection?: boolean; fsObject?: boolean; fsReader?: boolean; path?: boolean; rawOrigins?: Set<string> }): void => {
      const name = bindingOf(node);
      if (name === null) return;
      const scope = currentScope();
      scope.declared.add(name);
      scope.collections.delete(name);
      scope.fsObjects.delete(name);
      scope.fsReaders.delete(name);
      scope.paths.delete(name);
      scope.rawOrigins.delete(name);
      if (state.collection === true) scope.collections.add(name);
      if (state.fsObject === true) scope.fsObjects.add(name);
      if (state.fsReader === true) scope.fsReaders.add(name);
      if (state.path === true) scope.paths.add(name);
      if (state.rawOrigins !== undefined && state.rawOrigins.size > 0) {
        scope.rawOrigins.set(name, state.rawOrigins);
      }
    };
    const sourceCollection = (node: ESTree.Node): boolean => {
      const current = unwrap(node);
      return current.type === "ArrayExpression" && current.elements.length > 0 && current.elements.every((element) => element !== null && element.type !== "SpreadElement" && sourcePath(element));
    };
    const enterFunction = (): void => {
      scopes.push(newScope());
    };
    const exitFunction = (): void => { scopes.pop(); };

    function declareFsReaders(pattern: ESTree.ObjectPattern): void {
      for (const property of pattern.properties) {
        if (property.type !== "Property" || property.value.type !== "Identifier") continue;
        const key = property.key.type === "Identifier" ? property.key.name : property.key.type === "Literal" ? String(property.key.value) : "";
        if (FS_READERS.has(key)) declare(property.value, { fsReader: true });
      }
    }

    return {
      ImportDeclaration(node): void {
        const source = importSource(node);
        if (source === null || !FS_MODULES.has(source)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportSpecifier") {
            const imported = specifier.imported.type === "Identifier" ? specifier.imported.name : String(specifier.imported.value);
            if (FS_READERS.has(imported)) declare(specifier.local, { fsReader: true });
          } else {
            declare(specifier.local, { fsObject: true });
          }
        }
      },
      ":function": enterFunction,
      ":function:exit": exitFunction,
      VariableDeclarator(node): void {
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
      AssignmentExpression(node): void {
        if (node.left.type === "Identifier") declare(node.left, {});
      },
      ForOfStatement(node): void {
        const right = unwrap(node.right);
        const collection = right.type === "Identifier" && visible("collections", right);
        const left = node.left.type === "VariableDeclaration" ? node.left.declarations[0]?.id : node.left;
        if (collection && left?.type === "Identifier") declare(left, { path: true });
      },
      CallExpression(node): void {
        const origins = rawAssertionOrigins(node);
        if (origins.size === 0 || [...origins].every((origin) => reportedOrigins.has(origin))) return;
        for (const origin of origins) reportedOrigins.add(origin);
        context.report({ node, messageId: "rawSourceOracle" });
      },
    };
  },
  });
}

export default createSourceCoupledRule(
  "source-coupled-test",
  SOURCE_COUPLED_TEST_DOCUMENTATION,
  GENERAL_SOURCE_SUFFIX_RE,
);

function importedAssertionKind(specifier: ESTree.Node): "assert" | "expect" | null {
  if (
    (specifier.type !== "ImportSpecifier" &&
      specifier.type !== "ImportDefaultSpecifier" &&
      specifier.type !== "ImportNamespaceSpecifier") ||
    specifier.parent?.type !== "ImportDeclaration"
  ) return null;
  const source = importSource(specifier.parent);
  if (source !== null && ASSERT_MODULES.has(source)) {
    if (specifier.type !== "ImportSpecifier") return "assert";
    const imported = specifier.imported.type === "Identifier" ? specifier.imported.name : String(specifier.imported.value);
    if (imported === "strict" || ASSERT_MATCHERS.has(imported)) return "assert";
    return null;
  }
  if (source === null || !EXPECT_MODULES.has(source) || specifier.type !== "ImportSpecifier") return null;
  const imported = specifier.imported.type === "Identifier" ? specifier.imported.name : String(specifier.imported.value);
  if (imported === "assert" || imported === "expect") return imported;
  return null;
}

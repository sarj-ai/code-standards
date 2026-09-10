/**
 * @fileoverview source-coupled-test — raw repository source text is not a behavioral oracle.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/source-coupled-test.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

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
  readonly collections: Set<TSESLint.Scope.Variable>;
  readonly declared: Set<TSESLint.Scope.Variable>;
  readonly fsObjects: Set<TSESLint.Scope.Variable>;
  readonly fsReaders: Set<TSESLint.Scope.Variable>;
  readonly paths: Set<TSESLint.Scope.Variable>;
  readonly rawOrigins: Map<TSESLint.Scope.Variable, Set<string>>;
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

function staticMemberName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  if (node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string") return node.property.value;
  return null;
}

function unwrap(node: TSESTree.Node): TSESTree.Node {
  if (node.type === AST_NODE_TYPES.AwaitExpression) return unwrap(node.argument);
  if (node.type === AST_NODE_TYPES.ChainExpression) return unwrap(node.expression);
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression ||
    node.type === AST_NODE_TYPES.TSTypeAssertion
  ) return unwrap(node.expression);
  return node;
}

function stringValue(node: TSESTree.Node): string | null {
  const current = unwrap(node);
  if (current.type === AST_NODE_TYPES.Literal && typeof current.value === "string") return current.value;
  if (current.type === AST_NODE_TYPES.TemplateLiteral && current.expressions.length === 0) return current.quasis[0]?.value.cooked ?? null;
  if (current.type === AST_NODE_TYPES.BinaryExpression && current.operator === "+") {
    const left = stringValue(current.left);
    const right = stringValue(current.right);
    return left === null || right === null ? null : left + right;
  }
  return null;
}

function importSource(node: TSESTree.ImportDeclaration): string | null {
  return typeof node.source.value === "string" ? node.source.value : null;
}

function requireSource(node: TSESTree.Node): string | null {
  const current = unwrap(node);
  if (
    current.type !== AST_NODE_TYPES.CallExpression ||
    current.callee.type !== AST_NODE_TYPES.Identifier ||
    current.callee.name !== "require" ||
    current.arguments.length !== 1 ||
    current.arguments[0]?.type === AST_NODE_TYPES.SpreadElement
  ) return null;
  return stringValue(current.arguments[0] as TSESTree.Node);
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
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};

    const scopes: LexicalScope[] = [newScope()];
    const reportedOrigins = new Set<string>();
    const currentScope = (): LexicalScope => scopes.at(-1) ?? scopes[0]!;
    const bindingOf = (node: TSESTree.Identifier) => ASTUtils.findVariable(context.sourceCode.getScope(node), node.name);
    const assertionKind = (node: TSESTree.Identifier): "assert" | "expect" | null => {
      const binding = bindingOf(node);
      if (binding === null || binding.defs.length === 0) {
        return node.name === "assert" || node.name === "expect" ? node.name : null;
      }
      for (const definition of binding.defs) {
        const specifier = definition.node;
        if (
          (specifier.type !== AST_NODE_TYPES.ImportSpecifier &&
            specifier.type !== AST_NODE_TYPES.ImportDefaultSpecifier &&
            specifier.type !== AST_NODE_TYPES.ImportNamespaceSpecifier) ||
          specifier.parent.type !== AST_NODE_TYPES.ImportDeclaration
        ) continue;
        const source = importSource(specifier.parent);
        if (source !== null && ASSERT_MODULES.has(source)) {
          if (specifier.type !== AST_NODE_TYPES.ImportSpecifier) return "assert";
          const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : String(specifier.imported.value);
          if (imported === "strict" || ASSERT_MATCHERS.has(imported)) return "assert";
          continue;
        }
        if (source === null || !EXPECT_MODULES.has(source) || specifier.type !== AST_NODE_TYPES.ImportSpecifier) continue;
        const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : String(specifier.imported.value);
        if (imported === "assert" || imported === "expect") return imported;
      }
      return null;
    };
    const visible = (kind: "collections" | "fsObjects" | "fsReaders" | "paths", node: TSESTree.Identifier): boolean => {
      const name = bindingOf(node);
      if (name === null || name.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
      for (let index = scopes.length - 1; index >= 0; index--) {
        const scope = scopes[index]!;
        if (scope.declared.has(name)) return scope[kind].has(name);
      }
      return false;
    };
    const visibleRawOrigins = (node: TSESTree.Identifier): Set<string> => {
      const name = bindingOf(node);
      if (name === null || name.references.some((reference) => reference.isWrite() && reference.init !== true)) return new Set();
      for (let index = scopes.length - 1; index >= 0; index--) {
        const scope = scopes[index]!;
        if (scope.declared.has(name)) return scope.rawOrigins.get(name) ?? new Set();
      }
      return new Set();
    };
    const sourcePath = (node: TSESTree.Node): boolean => {
      const current = unwrap(node);
      const value = stringValue(current);
      if (value !== null) return sourceSuffixRe.test(value);
      if (current.type === AST_NODE_TYPES.Identifier) return visible("paths", current);
      if (current.type === AST_NODE_TYPES.CallExpression || current.type === AST_NODE_TYPES.NewExpression) {
        const callee = current.callee;
        const first = current.arguments[0];
        if (first === undefined || first.type === AST_NODE_TYPES.SpreadElement) return false;
        if (current.type === AST_NODE_TYPES.NewExpression && callee.type === AST_NODE_TYPES.Identifier && callee.name === "URL" && (bindingOf(callee)?.defs.length ?? 0) === 0) return sourcePath(first);
        if (callee.type === AST_NODE_TYPES.Identifier && bindingOf(callee)?.defs.some((definition) =>
          definition.node.type === AST_NODE_TYPES.ImportSpecifier && definition.node.imported.type === AST_NODE_TYPES.Identifier &&
          definition.node.imported.name === "fileURLToPath" && definition.node.parent.type === AST_NODE_TYPES.ImportDeclaration &&
          ["node:url", "url"].includes(String(definition.node.parent.source.value)))) return sourcePath(first);
      }
      return false;
    };
    const rawRead = (node: TSESTree.Node): boolean => {
      const current = unwrap(node);
      if (current.type !== AST_NODE_TYPES.CallExpression || current.arguments.length === 0) return false;
      const callee = unwrap(current.callee);
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return visible("fsReaders", callee) && sourcePath(current.arguments[0] as TSESTree.Node);
      }
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      const name = staticMemberName(callee);
      const object = unwrap(callee.object);
      return name !== null && FS_READERS.has(name) && object.type === AST_NODE_TYPES.Identifier && visible("fsObjects", object) && sourcePath(current.arguments[0] as TSESTree.Node);
    };
    const rawOrigins = (node: TSESTree.Node): Set<string> => {
      const current = unwrap(node);
      if (current.type === AST_NODE_TYPES.Identifier) return visibleRawOrigins(current);
      if (rawRead(current)) return new Set([`${current.range[0]}:${current.range[1]}`]);
      if (current.type === AST_NODE_TYPES.BinaryExpression && current.operator === "+") return new Set([...rawOrigins(current.left), ...rawOrigins(current.right)]);
      if (current.type === AST_NODE_TYPES.MemberExpression && staticMemberName(current) === "length") return rawOrigins(current.object);
      if (current.type !== AST_NODE_TYPES.CallExpression) return new Set();
      const callee = unwrap(current.callee);
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return new Set();
      const name = staticMemberName(callee);
      return name !== null && TEXT_TRANSFORMS.has(name) ? rawOrigins(callee.object) : new Set();
    };
    const evidenceOrigins = (node: TSESTree.Node): Set<string> => {
      const current = unwrap(node);
      const direct = rawOrigins(current);
      if (direct.size > 0) return direct;
      if (current.type === AST_NODE_TYPES.BinaryExpression || current.type === AST_NODE_TYPES.LogicalExpression) return new Set([...evidenceOrigins(current.left), ...evidenceOrigins(current.right)]);
      if (current.type === AST_NODE_TYPES.UnaryExpression) return evidenceOrigins(current.argument);
      if (current.type !== AST_NODE_TYPES.CallExpression) return new Set();
      const callee = unwrap(current.callee);
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return new Set();
      const name = staticMemberName(callee);
      if (name !== null && TEXT_PREDICATES.has(name)) return rawOrigins(callee.object);
      if (name !== null && REGEXP_PREDICATES.has(name)) return new Set(current.arguments.flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...rawOrigins(argument)]));
      return new Set();
    };
    const rawAssertionOrigins = (node: TSESTree.CallExpression): Set<string> => {
      const callee = unwrap(node.callee);
      if (callee.type === AST_NODE_TYPES.Identifier && assertionKind(callee) === "assert") {
        return new Set(node.arguments.flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...evidenceOrigins(argument)]));
      }
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return new Set();
      const matcher = staticMemberName(callee);
      if (matcher === null) return new Set();
      let receiver = unwrap(callee.object);
      while (receiver.type === AST_NODE_TYPES.MemberExpression && EXPECT_MODIFIERS.has(staticMemberName(receiver) ?? "")) receiver = unwrap(receiver.object);
      if (receiver.type === AST_NODE_TYPES.CallExpression && receiver.callee.type === AST_NODE_TYPES.Identifier && assertionKind(receiver.callee) === "expect") {
        if (!EXPECT_MATCHERS.has(matcher)) return new Set();
        return new Set([...receiver.arguments, ...node.arguments].flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...evidenceOrigins(argument)]));
      }
      if (receiver.type !== AST_NODE_TYPES.Identifier || assertionKind(receiver) !== "assert" || !ASSERT_MATCHERS.has(matcher)) return new Set();
      return new Set(node.arguments.flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...evidenceOrigins(argument)]));
    };
    const declare = (node: TSESTree.Identifier, state: { collection?: boolean; fsObject?: boolean; fsReader?: boolean; path?: boolean; rawOrigins?: Set<string> }): void => {
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
    const sourceCollection = (node: TSESTree.Node): boolean => {
      const current = unwrap(node);
      return current.type === AST_NODE_TYPES.ArrayExpression && current.elements.length > 0 && current.elements.every((element) => element !== null && element.type !== AST_NODE_TYPES.SpreadElement && sourcePath(element));
    };
    const enterFunction = (): void => {
      scopes.push(newScope());
    };
    const exitFunction = (): void => { scopes.pop(); };

    return {
      ImportDeclaration(node): void {
        const source = importSource(node);
        if (source === null || !FS_MODULES.has(source)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === AST_NODE_TYPES.ImportSpecifier) {
            const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : String(specifier.imported.value);
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
        if (required !== null && initializer.type === AST_NODE_TYPES.CallExpression && initializer.callee.type === AST_NODE_TYPES.Identifier && (bindingOf(initializer.callee)?.defs.length ?? 0) > 0) return;
        if (required !== null && FS_MODULES.has(required) && node.id.type === AST_NODE_TYPES.Identifier) {
          declare(node.id, { fsObject: true });
          return;
        }
        if (node.id.type === AST_NODE_TYPES.ObjectPattern && required !== null && FS_MODULES.has(required)) {
          for (const property of node.id.properties) {
            if (property.type !== AST_NODE_TYPES.Property || property.value.type !== AST_NODE_TYPES.Identifier) continue;
            const key = property.key.type === AST_NODE_TYPES.Identifier ? property.key.name : property.key.type === AST_NODE_TYPES.Literal ? String(property.key.value) : "";
            if (FS_READERS.has(key)) declare(property.value, { fsReader: true });
          }
          return;
        }
        if (node.id.type !== AST_NODE_TYPES.Identifier) return;
        declare(node.id, { collection: sourceCollection(node.init), path: sourcePath(node.init), rawOrigins: rawOrigins(node.init) });
      },
      AssignmentExpression(node): void {
        if (node.left.type === AST_NODE_TYPES.Identifier) declare(node.left, {});
      },
      ForOfStatement(node): void {
        const right = unwrap(node.right);
        const collection = right.type === AST_NODE_TYPES.Identifier && visible("collections", right);
        const left = node.left.type === AST_NODE_TYPES.VariableDeclaration ? node.left.declarations[0]?.id : node.left;
        if (collection && left?.type === AST_NODE_TYPES.Identifier) declare(left, { path: true });
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

/**
 * @fileoverview source-coupled-test — raw repository source text is not a behavioral oracle.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/source-coupled-test.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "rawSourceOracle";
type Options = readonly [];

const SOURCE_SUFFIX_RE = /\.(?:bash|hcl|sh|tf|tfvars|ya?ml|py|[cm]?[jt]s)$/iu;
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

interface LexicalScope {
  readonly collections: Set<string>;
  readonly declared: Set<string>;
  readonly fsObjects: Set<string>;
  readonly fsReaders: Set<string>;
  readonly paths: Set<string>;
  readonly rawOrigins: Map<string, Set<string>>;
}

export const sourceCoupledTestDocumentation = {
  summary: "Disallow raw repository source text as a test oracle; parse or execute the artifact instead.",
  rationale: "Substring and regex checks can pass on comments or unreachable configuration and fail after behavior-preserving formatting changes.",
  remediation: "Parse the artifact, execute its validator, or assert on Terraform plan JSON or another runtime contract.",
  category: "testing",
  limitations: [
    "The rule follows lexical aliases, source-path collections, awaited reads, and common text operations; interprocedural flows remain unreported.",
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
      id: "terraform-substring-contract",
      title: "Do not prove Terraform behavior with a regex",
      outcome: "match",
      files: [{ path: "src/policy.test.ts", source: "import { readFileSync } from 'node:fs'; test('policy', () => { const source = readFileSync('main.tf', 'utf8'); expect(source).toMatch(/prevent_destroy/); });" }],
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

export default createRule<Options, MessageIds>({
  name: "source-coupled-test",
  documentation: sourceCoupledTestDocumentation,
  meta: {
    type: "suggestion",
    docs: { description: sourceCoupledTestDocumentation.summary },
    schema: [],
    messages: { rawSourceOracle: "Raw repository source text is the oracle. Parse or execute the artifact so comments, formatting, and unreachable blocks cannot satisfy the contract." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};

    const scopes: LexicalScope[] = [newScope()];
    const reportedOrigins = new Set<string>();
    const currentScope = (): LexicalScope => scopes.at(-1) ?? scopes[0]!;
    const visible = (kind: "collections" | "fsObjects" | "fsReaders" | "paths", name: string): boolean => {
      for (let index = scopes.length - 1; index >= 0; index--) {
        const scope = scopes[index]!;
        if (scope.declared.has(name)) return scope[kind].has(name);
      }
      return false;
    };
    const visibleRawOrigins = (name: string): Set<string> => {
      for (let index = scopes.length - 1; index >= 0; index--) {
        const scope = scopes[index]!;
        if (scope.declared.has(name)) return scope.rawOrigins.get(name) ?? new Set();
      }
      return new Set();
    };
    const sourcePath = (node: TSESTree.Node): boolean => {
      const current = unwrap(node);
      const value = stringValue(current);
      if (value !== null) return SOURCE_SUFFIX_RE.test(value);
      if (current.type === AST_NODE_TYPES.Identifier) return visible("paths", current.name);
      if (current.type === AST_NODE_TYPES.BinaryExpression && current.operator === "+") {
        return sourcePath(current.left) || sourcePath(current.right);
      }
      if (current.type === AST_NODE_TYPES.TemplateLiteral) return current.expressions.some(sourcePath);
      if (current.type === AST_NODE_TYPES.CallExpression || current.type === AST_NODE_TYPES.NewExpression) {
        return current.arguments.some((argument) => argument.type !== AST_NODE_TYPES.SpreadElement && sourcePath(argument));
      }
      if (current.type === AST_NODE_TYPES.MemberExpression) return sourcePath(current.object);
      return false;
    };
    const rawRead = (node: TSESTree.Node): boolean => {
      const current = unwrap(node);
      if (current.type !== AST_NODE_TYPES.CallExpression || current.arguments.length === 0) return false;
      const callee = unwrap(current.callee);
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return visible("fsReaders", callee.name) && sourcePath(current.arguments[0] as TSESTree.Node);
      }
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      const name = staticMemberName(callee);
      const object = unwrap(callee.object);
      return name !== null && FS_READERS.has(name) && object.type === AST_NODE_TYPES.Identifier && visible("fsObjects", object.name) && sourcePath(current.arguments[0] as TSESTree.Node);
    };
    const rawOrigins = (node: TSESTree.Node): Set<string> => {
      const current = unwrap(node);
      if (current.type === AST_NODE_TYPES.Identifier) return visibleRawOrigins(current.name);
      if (rawRead(current)) return new Set([`${current.range[0]}:${current.range[1]}`]);
      if (current.type === AST_NODE_TYPES.BinaryExpression && current.operator === "+") return new Set([...rawOrigins(current.left), ...rawOrigins(current.right)]);
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
      if (callee.type === AST_NODE_TYPES.Identifier && callee.name === "assert") {
        return new Set(node.arguments.flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...evidenceOrigins(argument)]));
      }
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return new Set();
      const matcher = staticMemberName(callee);
      if (matcher === null) return new Set();
      let receiver = unwrap(callee.object);
      while (receiver.type === AST_NODE_TYPES.MemberExpression && EXPECT_MODIFIERS.has(staticMemberName(receiver) ?? "")) receiver = unwrap(receiver.object);
      if (receiver.type === AST_NODE_TYPES.CallExpression && receiver.callee.type === AST_NODE_TYPES.Identifier && receiver.callee.name === "expect") {
        if (!EXPECT_MATCHERS.has(matcher)) return new Set();
        return new Set([...receiver.arguments, ...node.arguments].flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...evidenceOrigins(argument)]));
      }
      if (receiver.type !== AST_NODE_TYPES.Identifier || receiver.name !== "assert" || !ASSERT_MATCHERS.has(matcher)) return new Set();
      return new Set(node.arguments.flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...evidenceOrigins(argument)]));
    };
    const declare = (name: string, state: { collection?: boolean; fsObject?: boolean; fsReader?: boolean; path?: boolean; rawOrigins?: Set<string> }): void => {
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
    const declaredNames = (node: TSESTree.Node): string[] => {
      const current = unwrap(node);
      if (current.type === AST_NODE_TYPES.Identifier) return [current.name];
      if (current.type === AST_NODE_TYPES.AssignmentPattern) return declaredNames(current.left);
      if (current.type === AST_NODE_TYPES.RestElement) return declaredNames(current.argument);
      if (current.type === AST_NODE_TYPES.ArrayPattern) return current.elements.flatMap((element) => element === null ? [] : declaredNames(element));
      if (current.type === AST_NODE_TYPES.ObjectPattern) return current.properties.flatMap((property) => property.type === AST_NODE_TYPES.RestElement ? declaredNames(property.argument) : declaredNames(property.value));
      return [];
    };
    const enterFunction = (node: TSESTree.ArrowFunctionExpression | TSESTree.FunctionDeclaration | TSESTree.FunctionExpression): void => {
      scopes.push(newScope());
      for (const parameter of node.params) for (const name of declaredNames(parameter)) declare(name, {});
    };
    const exitFunction = (): void => { scopes.pop(); };

    return {
      ImportDeclaration(node): void {
        const source = importSource(node);
        if (source === null || !FS_MODULES.has(source)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type === AST_NODE_TYPES.ImportSpecifier) {
            const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : String(specifier.imported.value);
            if (FS_READERS.has(imported)) declare(specifier.local.name, { fsReader: true });
          } else {
            declare(specifier.local.name, { fsObject: true });
          }
        }
      },
      ":function": enterFunction,
      ":function:exit": exitFunction,
      VariableDeclarator(node): void {
        if (node.init === null) return;
        const required = requireSource(node.init);
        if (required !== null && FS_MODULES.has(required) && node.id.type === AST_NODE_TYPES.Identifier) {
          declare(node.id.name, { fsObject: true });
          return;
        }
        if (node.id.type === AST_NODE_TYPES.ObjectPattern && required !== null && FS_MODULES.has(required)) {
          for (const property of node.id.properties) {
            if (property.type !== AST_NODE_TYPES.Property || property.value.type !== AST_NODE_TYPES.Identifier) continue;
            const key = property.key.type === AST_NODE_TYPES.Identifier ? property.key.name : property.key.type === AST_NODE_TYPES.Literal ? String(property.key.value) : "";
            if (FS_READERS.has(key)) declare(property.value.name, { fsReader: true });
          }
          return;
        }
        if (node.id.type !== AST_NODE_TYPES.Identifier) return;
        declare(node.id.name, { collection: sourceCollection(node.init), path: sourcePath(node.init), rawOrigins: rawOrigins(node.init) });
      },
      AssignmentExpression(node): void {
        if (node.left.type === AST_NODE_TYPES.Identifier) declare(node.left.name, { path: sourcePath(node.right), rawOrigins: rawOrigins(node.right) });
      },
      ForOfStatement(node): void {
        const right = unwrap(node.right);
        const collection = right.type === AST_NODE_TYPES.Identifier && visible("collections", right.name);
        const left = node.left.type === AST_NODE_TYPES.VariableDeclaration ? node.left.declarations[0]?.id : node.left;
        if (collection && left?.type === AST_NODE_TYPES.Identifier) declare(left.name, { path: true });
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

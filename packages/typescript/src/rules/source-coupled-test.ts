/**
 * @fileoverview source-coupled-test — raw repository source text is not a behavioral oracle.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/source-coupled-test.test.ts
 */

import { posix, win32 } from "node:path";

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "rawSourceOracle";
type Options = readonly [];

// Terraform JSON has a dedicated oracle owner; JSONC remains general source.
const GENERAL_SOURCE_SUFFIX_RE = /\.(?:bash|sh|ya?ml|jsonc|toml|py|css|html|[cm]?[jt]s|[jt]sx)$|(?<!\.(?:tf|tftest))\.json$/iu;
const REPRESENTATION_DIR_RE = /(?:^|\/)(?:__fixtures__|fixtures?|goldens?|snapshots?)(?:\/|$)/iu;
const PATH_MODULES = new Set(["path", "node:path"]);
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
  remediation: "Reuse adequate existing validation; otherwise assert a distinct parsed or runtime contract. Preserve deliberate representation contracts with an exact justified suppression.",
  category: "testing",
  limitations: [
    "The rule follows stable lexical bindings, static source paths including JSX/TSX, CSS and HTML, awaited reads, and common text operations. Named imports of node:path/path join and resolve are followed when their complete trailing static path proves a source suffix. Reassigned bindings, dynamic trailing segments, namespace path wrappers, unknown path wrappers, iterator pipelines, and interprocedural flows remain unreported.",
    "Assertion roots are scope-resolved for supported test runners and Node assert imports; local or unknown helpers with assertion-like names are not inferred.",
    "Known fixture, golden, snapshot, and generated source paths are representation contracts and remain unreported; dot segments in the known path are normalized first.",
    "Contained static paths, including stable nested join/resolve descendants, beneath a native mkdtemp/mkdtempSync result are generated artifacts. Absolute or drive-anchored resolve segments and traversal above the proven directory remain unproven. Literal replace/replaceAll nonidentity guards comparing the same raw read remain unreported; fixed-string comparisons remain candidates.",
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

function unwrap(node: TSESTree.Node): TSESTree.Node {
  for (;;) {
    node = unwrapExpression(node);
    if (node.type === AST_NODE_TYPES.AwaitExpression) node = node.argument;
    else if (node.type === AST_NODE_TYPES.ChainExpression) node = node.expression;
    else return node;
  }
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

function staticPathSuffix(pathArguments: readonly TSESTree.CallExpressionArgument[], builder: "join" | "resolve"): string | null {
  const trailing: string[] = [];
  for (const argument of pathArguments.toReversed()) {
    if (argument.type === AST_NODE_TYPES.SpreadElement) return null;
    const segment = stringValue(argument);
    if (segment === null) break;
    trailing.unshift(segment);
    if (builder === "resolve" && posix.isAbsolute(segment.replaceAll("\\", "/"))) break;
  }
  return trailing.length > 0 ? trailing.join("/") : null;
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
    messages: { rawSourceOracle: "Raw repository source text is the oracle. Reuse adequate existing validation; otherwise assert a distinct parsed or runtime contract. Preserve a deliberate representation contract with an exact justified suppression." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context) || isGeneratedFile(context, context.sourceCode.text)) return {};

    const referenceStability = new WeakMap<TSESLint.Scope.Variable, boolean>();
    const referenceStable = (variable: TSESLint.Scope.Variable): boolean => {
      const cached = referenceStability.get(variable);
      if (cached !== undefined) return cached;
      const stable = !variable.references.some((reference) => reference.isWrite() && reference.init !== true);
      referenceStability.set(variable, stable);
      return stable;
    };
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
        const kind = importedAssertionKind(definition.node);
        if (kind !== null) return kind;
      }
      return null;
    };
    const visible = (kind: "collections" | "fsObjects" | "fsReaders" | "paths", node: TSESTree.Identifier): boolean => {
      const name = bindingOf(node);
      if (name === null || !referenceStable(name)) return false;
      for (let index = scopes.length - 1;index >= 0;index--) {
        const scope = scopes[index]!;
        if (scope.declared.has(name)) return scope[kind].has(name);
      }
      return false;
    };
    const visibleRawOrigins = (node: TSESTree.Identifier): Set<string> => {
      const name = bindingOf(node);
      if (name === null || !referenceStable(name)) return new Set();
      for (let index = scopes.length - 1;index >= 0;index--) {
        const scope = scopes[index]!;
        if (scope.declared.has(name)) return scope.rawOrigins.get(name) ?? new Set();
      }
      return new Set();
    };
    const sourcePath = (node: TSESTree.Node): boolean => {
      const current = unwrap(node);
      const value = stringValue(current);
      if (value !== null) return sourcePathValue(value);
      if (current.type === AST_NODE_TYPES.Identifier) return visible("paths", current);
      if (current.type !== AST_NODE_TYPES.CallExpression && current.type !== AST_NODE_TYPES.NewExpression) return false;
      const callee = unwrapExpression(current.callee);
      const first = current.arguments[0];
      if (first === undefined || first.type === AST_NODE_TYPES.SpreadElement) return false;
      const pathBuilder = callee.type === AST_NODE_TYPES.Identifier ? nativePathBuilder(callee) : null;
      if (current.type === AST_NODE_TYPES.CallExpression && pathBuilder !== null) {
        if (temporaryDescendant(current, pathBuilder)) return false;
        const suffix = staticPathSuffix(current.arguments, pathBuilder);
        return suffix !== null && sourcePathValue(suffix);
      }
      if (current.type === AST_NODE_TYPES.NewExpression && callee.type === AST_NODE_TYPES.Identifier && callee.name === "URL" && (bindingOf(callee)?.defs.length ?? 0) === 0) return sourcePath(first);
      if (callee.type === AST_NODE_TYPES.Identifier && bindingOf(callee)?.defs.some((definition) =>
        definition.node.type === AST_NODE_TYPES.ImportSpecifier && definition.node.imported.type === AST_NODE_TYPES.Identifier &&
        definition.node.imported.name === "fileURLToPath" && definition.node.parent.type === AST_NODE_TYPES.ImportDeclaration &&
        ["node:url", "url"].includes(String(definition.node.parent.source.value)))) return sourcePath(first);
      return false;
    };
    const nativePathBuilder = (node: TSESTree.Identifier): "join" | "resolve" | null => {
      const imported = nativeImportedName(node, PATH_MODULES);
      return imported === "join" || imported === "resolve" ? imported : null;
    };
    const nativeImportedName = (node: TSESTree.Identifier, modules: ReadonlySet<string>): string | null => {
      const binding = bindingOf(node);
      if (binding === null || !referenceStable(binding)) return null;
      for (const definition of binding.defs) {
        const imported = definition.node;
        if (imported.type === AST_NODE_TYPES.ImportSpecifier &&
          imported.imported.type === AST_NODE_TYPES.Identifier &&
          imported.parent.type === AST_NODE_TYPES.ImportDeclaration && modules.has(String(imported.parent.source.value))) {
          return imported.imported.name;
        }
      }
      return null;
    };
    const stableInitializer = (node: TSESTree.Identifier): TSESTree.Expression | null => {
      const binding = bindingOf(node);
      if (binding === null || !referenceStable(binding) || binding.defs.length !== 1) return null;
      const definition = binding.defs[0]?.node;
      return definition?.type === AST_NODE_TYPES.VariableDeclarator ? definition.init : null;
    };
    const temporaryDirectory = (node: TSESTree.Node, depth = 0): boolean => {
      if (depth > 8) return false;
      const current = unwrap(node);
      if (current.type === AST_NODE_TYPES.Identifier) {
        const initializer = stableInitializer(current);
        return initializer !== null && temporaryDirectory(initializer, depth + 1);
      }
      if (current.type !== AST_NODE_TYPES.CallExpression) return false;
      const callee = unwrap(current.callee);
      if (callee.type !== AST_NODE_TYPES.Identifier) return false;
      if (["mkdtemp", "mkdtempSync"].includes(nativeImportedName(callee, FS_MODULES) ?? "")) return true;
      const builder = nativePathBuilder(callee);
      return builder !== null && temporaryDescendant(current, builder, depth + 1);
    };
    const temporaryDescendant = (node: TSESTree.CallExpression, builder: "join" | "resolve", depth = 0): boolean => {
      if (depth > 8) return false;
      const [directory, ...segments] = node.arguments;
      if (directory === undefined || directory.type === AST_NODE_TYPES.SpreadElement || !temporaryDirectory(directory, depth)) return false;
      let relativeDepth = 0;
      for (const segment of segments) {
        if (segment.type === AST_NODE_TYPES.SpreadElement) return false;
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
      return sourceSuffixRe.test(normalized) && !REPRESENTATION_DIR_RE.test(normalized) && !isGeneratedFile({ filename: normalized, cwd: context.cwd });
    };
    const rawRead = (node: TSESTree.Node): boolean => {
      const current = unwrap(node);
      if (current.type !== AST_NODE_TYPES.CallExpression || current.arguments.length === 0) return false;
      const callee = unwrap(current.callee);
      const calleeReceiver = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return visible("fsReaders", callee) && sourcePath(current.arguments[0] as TSESTree.Node);
      }
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      const name = ASTUtils.getPropertyName(callee);
      const object = unwrap(calleeReceiver);
      return name !== null && FS_READERS.has(name) && object.type === AST_NODE_TYPES.Identifier && visible("fsObjects", object) && sourcePath(current.arguments[0] as TSESTree.Node);
    };
    const rawOrigins = (node: TSESTree.Node): Set<string> => {
      const current = unwrap(node);
      if (current.type === AST_NODE_TYPES.Identifier) return visibleRawOrigins(current);
      if (rawRead(current)) return new Set([`${current.range[0]}:${current.range[1]}`]);
      if (current.type === AST_NODE_TYPES.BinaryExpression && current.operator === "+") return new Set([...rawOrigins(current.left), ...rawOrigins(current.right)]);
      if (current.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(current) === "length") return rawOrigins(current.object);
      if (current.type !== AST_NODE_TYPES.CallExpression) return new Set();
      const callee = unwrap(current.callee);
      const calleeReceiver = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return new Set();
      const name = ASTUtils.getPropertyName(callee);
      return name !== null && TEXT_TRANSFORMS.has(name) ? rawOrigins(calleeReceiver) : new Set();
    };
    const evidenceOrigins = (node: TSESTree.Node): Set<string> => {
      const current = unwrap(node);
      const direct = rawOrigins(current);
      if (direct.size > 0) return direct;
      if (current.type === AST_NODE_TYPES.BinaryExpression || current.type === AST_NODE_TYPES.LogicalExpression) return new Set([...evidenceOrigins(current.left), ...evidenceOrigins(current.right)]);
      if (current.type === AST_NODE_TYPES.UnaryExpression) return evidenceOrigins(current.argument);
      if (current.type !== AST_NODE_TYPES.CallExpression) return new Set();
      const callee = unwrap(current.callee);
      const calleeReceiver = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return new Set();
      const name = ASTUtils.getPropertyName(callee);
      if (name !== null && TEXT_PREDICATES.has(name)) return rawOrigins(calleeReceiver);
      if (name !== null && REGEXP_PREDICATES.has(name)) return new Set(current.arguments.flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...rawOrigins(argument)]));
      return new Set();
    };
    const literalMutation = (node: TSESTree.Node, depth = 0): boolean => {
      if (depth > 8) return false;
      const current = unwrap(node);
      if (current.type === AST_NODE_TYPES.Identifier) {
        const initializer = stableInitializer(current);
        return initializer !== null && literalMutation(initializer, depth + 1);
      }
      if (current.type !== AST_NODE_TYPES.CallExpression || current.arguments.length !== 2) return false;
      const callee = unwrap(current.callee);
      const [pattern, replacement] = current.arguments;
      return callee.type === AST_NODE_TYPES.MemberExpression && ["replace", "replaceAll"].includes(ASTUtils.getPropertyName(callee) ?? "") &&
        pattern !== undefined && replacement !== undefined && pattern.type !== AST_NODE_TYPES.SpreadElement && replacement.type !== AST_NODE_TYPES.SpreadElement &&
        (stringValue(pattern) !== null || (pattern.type === AST_NODE_TYPES.Literal && "regex" in pattern)) && stringValue(replacement) !== null;
    };
    const mutationGuard = (operands: readonly TSESTree.CallExpressionArgument[]): boolean => {
      if (operands.length !== 2) return false;
      const [left, right] = operands;
      if (left === undefined || right === undefined || left.type === AST_NODE_TYPES.SpreadElement || right.type === AST_NODE_TYPES.SpreadElement || (!literalMutation(left) && !literalMutation(right))) return false;
      const leftOrigins = rawOrigins(left);
      const rightOrigins = rawOrigins(right);
      return leftOrigins.size > 0 && leftOrigins.size === rightOrigins.size && [...leftOrigins].every((origin) => rightOrigins.has(origin));
    };
    const rawAssertionOrigins = (node: TSESTree.CallExpression): Set<string> => {
      const callee = unwrap(node.callee);
      const calleeReceiver = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
      if (callee.type === AST_NODE_TYPES.Identifier && assertionKind(callee) === "assert") {
        return new Set(node.arguments.flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...evidenceOrigins(argument)]));
      }
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return new Set();
      const matcher = ASTUtils.getPropertyName(callee);
      if (matcher === null) return new Set();
      let receiver = unwrap(calleeReceiver);
      while (receiver.type === AST_NODE_TYPES.MemberExpression && EXPECT_MODIFIERS.has(ASTUtils.getPropertyName(receiver) ?? "")) receiver = unwrap(receiver.object);
      const expectCallee = receiver.type === AST_NODE_TYPES.CallExpression ? unwrapExpression(receiver.callee) : null;
      if (receiver.type === AST_NODE_TYPES.CallExpression && expectCallee?.type === AST_NODE_TYPES.Identifier && assertionKind(expectCallee) === "expect") {
        if (!EXPECT_MATCHERS.has(matcher)) return new Set();
        if (["toBe", "toEqual", "toStrictEqual"].includes(matcher) && calleeReceiver.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(calleeReceiver) === "not" && mutationGuard([...receiver.arguments, ...node.arguments])) return new Set();
        return new Set([...receiver.arguments, ...node.arguments].flatMap((argument) => argument.type === AST_NODE_TYPES.SpreadElement ? [] : [...evidenceOrigins(argument)]));
      }
      if (receiver.type !== AST_NODE_TYPES.Identifier || assertionKind(receiver) !== "assert" || !ASSERT_MATCHERS.has(matcher)) return new Set();
      if (["notEqual", "notStrictEqual"].includes(matcher) && mutationGuard(node.arguments)) return new Set();
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

    function declareFsReaders(pattern: TSESTree.ObjectPattern): void {
      for (const property of pattern.properties) {
        if (property.type !== AST_NODE_TYPES.Property || property.value.type !== AST_NODE_TYPES.Identifier) continue;
        const key = property.key.type === AST_NODE_TYPES.Identifier ? property.key.name : property.key.type === AST_NODE_TYPES.Literal ? String(property.key.value) : "";
        if (FS_READERS.has(key)) declare(property.value, { fsReader: true });
      }
    }

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
          declareFsReaders(node.id);
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

function importedAssertionKind(specifier: TSESTree.Node): "assert" | "expect" | null {
  if (
    (specifier.type !== AST_NODE_TYPES.ImportSpecifier &&
      specifier.type !== AST_NODE_TYPES.ImportDefaultSpecifier &&
      specifier.type !== AST_NODE_TYPES.ImportNamespaceSpecifier) ||
    specifier.parent.type !== AST_NODE_TYPES.ImportDeclaration
  ) return null;
  const source = importSource(specifier.parent);
  if (source !== null && ASSERT_MODULES.has(source)) {
    if (specifier.type !== AST_NODE_TYPES.ImportSpecifier) return "assert";
    const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : String(specifier.imported.value);
    if (imported === "strict" || ASSERT_MATCHERS.has(imported)) return "assert";
    return null;
  }
  if (source === null || !EXPECT_MODULES.has(source) || specifier.type !== AST_NODE_TYPES.ImportSpecifier) return null;
  const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : String(specifier.imported.value);
  if (imported === "assert" || imported === "expect") return imported;
  return null;
}

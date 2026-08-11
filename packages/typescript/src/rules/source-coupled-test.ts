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

const SOURCE_SUFFIX_RE = /\.(?:tf|tfvars|hcl|ya?ml|py|[cm]?[jt]s)$/iu;
const TEXT_TRANSFORMS = new Set(["toLowerCase", "toUpperCase", "trim", "trimEnd", "trimStart", "replace", "replaceAll"]);
const TEXT_PREDICATES = new Set(["endsWith", "includes", "indexOf", "match", "search", "startsWith"]);
const EXPECT_MATCHERS = new Set(["toBe", "toContain", "toEqual", "toMatch", "toMatchSnapshot", "toStrictEqual"]);
const ASSERT_MATCHERS = new Set(["equal", "match", "strictEqual"]);

export const sourceCoupledTestDocumentation = {
  summary: "Disallow raw repository source text as a test oracle; parse or execute the artifact instead.",
  rationale: "Substring and regex checks can pass on comments or unreachable configuration and fail after behavior-preserving formatting changes.",
  remediation: "Parse the artifact, execute its validator, or assert on Terraform plan JSON or another runtime contract.",
  category: "testing",
  limitations: [
    "The rule follows local aliases and common text normalization only; dynamic paths and interprocedural flows remain unreported.",
    "When raw representation is genuinely the contract (for example a golden or compatibility sentinel), use an exact line suppression with the reason.",
  ],
  examples: [
    {
      id: "parsed-policy-contract",
      title: "Assert on parsed policy behavior",
      outcome: "no-match",
      files: [{ path: "src/policy.test.ts", source: "test('policy', () => { const policy = JSON.parse(readFileSync('policy.json', 'utf8')); expect(validate(policy)).toEqual([]); });" }],
      focusPath: "src/policy.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "terraform-substring-contract",
      title: "Do not prove Terraform behavior with a regex",
      outcome: "match",
      files: [{ path: "src/policy.test.ts", source: "test('policy', () => { const source = readFileSync('main.tf', 'utf8'); expect(source).toMatch(/prevent_destroy/); });" }],
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

function containsSourceSuffix(node: TSESTree.Node): boolean {
  let found = false;
  visit(node, (current) => {
    if (current.type === AST_NODE_TYPES.Literal && typeof current.value === "string" && SOURCE_SUFFIX_RE.test(current.value)) found = true;
    if (current.type === AST_NODE_TYPES.TemplateLiteral && current.expressions.length === 0 && SOURCE_SUFFIX_RE.test(current.quasis[0]?.value.cooked ?? "")) found = true;
  });
  return found;
}

function rawRead(node: TSESTree.Node): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression) return false;
  const callee = node.callee;
  const name = callee.type === AST_NODE_TYPES.Identifier ? callee.name : callee.type === AST_NODE_TYPES.MemberExpression ? staticMemberName(callee) : null;
  return (name === "readFileSync" || name === "readFile") && containsSourceSuffix(node);
}

function derivedRaw(node: TSESTree.Node, rawNames: ReadonlySet<string>): boolean {
  if (node.type === AST_NODE_TYPES.Identifier) return rawNames.has(node.name);
  if (node.type !== AST_NODE_TYPES.CallExpression || node.callee.type !== AST_NODE_TYPES.MemberExpression) return false;
  const name = staticMemberName(node.callee);
  return name !== null && TEXT_TRANSFORMS.has(name) && containsRawName(node.callee.object, rawNames);
}

function containsRawName(node: TSESTree.Node, rawNames: ReadonlySet<string>): boolean {
  let found = false;
  visit(node, (current) => {
    if (current.type === AST_NODE_TYPES.Identifier && rawNames.has(current.name)) found = true;
  });
  return found;
}

function rawTextExpression(node: TSESTree.Node, rawNames: ReadonlySet<string>): boolean {
  if (node.type === AST_NODE_TYPES.Identifier) return rawNames.has(node.name);
  if (node.type !== AST_NODE_TYPES.CallExpression || node.callee.type !== AST_NODE_TYPES.MemberExpression) return false;
  const name = staticMemberName(node.callee);
  return name !== null && (TEXT_TRANSFORMS.has(name) || TEXT_PREDICATES.has(name)) && rawTextExpression(node.callee.object, rawNames);
}

function visit(node: TSESTree.Node, callback: (node: TSESTree.Node) => void): void {
  callback(node);
  for (const [key, value] of Object.entries(node)) {
    if (key === "parent") continue;
    for (const child of Array.isArray(value) ? value : [value]) {
      if (typeof child === "object" && child !== null && typeof (child as { type?: unknown }).type === "string") visit(child as TSESTree.Node, callback);
    }
  }
}

function isRawAssertion(node: TSESTree.CallExpression, rawNames: ReadonlySet<string>): boolean {
  if (node.callee.type !== AST_NODE_TYPES.MemberExpression) return false;
  const matcher = staticMemberName(node.callee);
  if (matcher === null) return false;
  const receiver = node.callee.object;
  if (receiver.type === AST_NODE_TYPES.CallExpression && receiver.callee.type === AST_NODE_TYPES.Identifier && receiver.callee.name === "expect") {
    return EXPECT_MATCHERS.has(matcher) && [...receiver.arguments, ...node.arguments].some((argument) => argument.type !== AST_NODE_TYPES.SpreadElement && rawTextExpression(argument, rawNames));
  }
  return receiver.type === AST_NODE_TYPES.Identifier && receiver.name === "assert" && ASSERT_MATCHERS.has(matcher) && node.arguments.some((argument) => argument.type !== AST_NODE_TYPES.SpreadElement && rawTextExpression(argument, rawNames));
}

function enclosingFunction(node: TSESTree.Node): TSESTree.Node | null {
  let current: TSESTree.Node | undefined = node;
  while (current.parent !== undefined && current.parent !== null) {
    current = current.parent;
    if (
      current.type === AST_NODE_TYPES.ArrowFunctionExpression ||
      current.type === AST_NODE_TYPES.FunctionExpression ||
      current.type === AST_NODE_TYPES.FunctionDeclaration
    ) {
      return current;
    }
  }
  return null;
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
    const fileRawNames = new Set<string>();
    const functionRawNames = new WeakMap<TSESTree.Node, Set<string>>();
    const reportedFunctions = new WeakSet<TSESTree.Node>();
    const visibleRawNames = (node: TSESTree.Node): Set<string> => {
      const names = new Set(fileRawNames);
      const owner = enclosingFunction(node);
      for (const name of owner === null ? [] : (functionRawNames.get(owner) ?? [])) names.add(name);
      return names;
    };
    const recordRawName = (node: TSESTree.Node, name: string): void => {
      const owner = enclosingFunction(node);
      if (owner === null) {
        fileRawNames.add(name);
        return;
      }
      const names = functionRawNames.get(owner) ?? new Set<string>();
      names.add(name);
      functionRawNames.set(owner, names);
    };
    return {
      VariableDeclarator(node): void {
        if (node.id.type !== AST_NODE_TYPES.Identifier || node.init === null) return;
        if (rawRead(node.init) || derivedRaw(node.init, visibleRawNames(node))) recordRawName(node, node.id.name);
      },
      AssignmentExpression(node): void {
        if (node.left.type === AST_NODE_TYPES.Identifier && (rawRead(node.right) || derivedRaw(node.right, visibleRawNames(node)))) recordRawName(node, node.left.name);
      },
      CallExpression(node): void {
        if (!isRawAssertion(node, visibleRawNames(node))) return;
        const owner = enclosingFunction(node) ?? node;
        if (reportedFunctions.has(owner)) return;
        reportedFunctions.add(owner);
        context.report({ node, messageId: "rawSourceOracle" });
      },
    };
  },
});

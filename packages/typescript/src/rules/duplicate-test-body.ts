/**
 * @fileoverview duplicate-test-body — sibling tests with the same substantial body are copy-paste cases that should be parameterized.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/duplicate-test-body.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "duplicateTestBody";
type Options = readonly [];

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);
const OMITTED_AST_KEYS: ReadonlySet<string> = new Set([
  "end",
  "loc",
  "parent",
  "range",
  "raw",
  "start",
]);
const MIN_STATEMENTS = 3;
const MAX_NORMALIZED_STRING_LENGTH = 64;
const TEST_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "node:test", "vitest"]);

export const duplicateTestBodyDocumentation = {
  summary:
    "Disallow substantial sibling tests with the same body shape; express their differing inputs as a parameterized case table.",
  rationale:
    "Copy-pasted test bodies hide the cases that differ and allow equivalent assertions to drift independently.",
  remediation:
    "Move the varying inputs and expected values into a case table consumed by `test.each(...)` or `it.each(...)`.",
  category: "testing",
  limitations: [
    "The rule compares substantial sibling tests within one suite and skips inline snapshots and materially different comments.",
  ],
  examples: [
    {
      id: "parameterized-cases",
      title: "A case table shares one test body",
      outcome: "no-match",
      files: [{
        path: "src/user.test.ts",
        source: "test.each(['a', 'b'])('accepts %s', (value) => { const result = parse(value); expect(result.ok).toBe(true); expect(result.value).toBe(value); });",
      }],
      focusPath: "src/user.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "copied-sibling-tests",
      title: "Sibling tests repeat the same body",
      outcome: "match",
      files: [{
        path: "src/user.test.ts",
        source: "test('accepts a', () => { const value = 'a'; const result = parse(value); expect(result.ok).toBe(true); expect(result.value).toBe(value); });\ntest('accepts b', () => { const value = 'b'; const result = parse(value); expect(result.ok).toBe(true); expect(result.value).toBe(value); });",
      }],
      focusPath: "src/user.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function rootIdentifier(callee: TSESTree.Node): TSESTree.Identifier | null {
  if (callee.type === AST_NODE_TYPES.Identifier) return callee;
  if (callee.type === AST_NODE_TYPES.MemberExpression) return rootIdentifier(callee.object);
  if (callee.type === AST_NODE_TYPES.CallExpression) return rootIdentifier(callee.callee);
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) return rootIdentifier(callee.tag);
  return null;
}

function staticMemberName(member: TSESTree.MemberExpression): string | null {
  if (!member.computed && member.property.type === AST_NODE_TYPES.Identifier) return member.property.name;
  if (member.computed && member.property.type === AST_NODE_TYPES.Literal && typeof member.property.value === "string") {
    return member.property.value;
  }
  return null;
}

function normalizedAst(value: unknown, preserveLiteral = false): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => normalizedAst(item, preserveLiteral));
  }
  if (typeof value !== "object" || value === null) {
    return typeof value === "bigint" ? value.toString() : value;
  }
  const record = value as Record<string, unknown>;
  if (record["type"] === AST_NODE_TYPES.Literal && !preserveLiteral) {
    return normalizedLiteral(value as TSESTree.Literal);
  }
  const normalized: Record<string, unknown> = {};
  const preservesAssertionContract =
    record["type"] === AST_NODE_TYPES.CallExpression && isAssertionCall(value as TSESTree.CallExpression);
  for (const key of Object.keys(record).sort()) {
    if (OMITTED_AST_KEYS.has(key)) {
      continue;
    }
    const isPropertyName =
      key === "key" &&
      (record["type"] === AST_NODE_TYPES.Property ||
        record["type"] === AST_NODE_TYPES.MethodDefinition ||
        record["type"] === AST_NODE_TYPES.PropertyDefinition);
    const isComputedMemberName =
      key === "property" &&
      record["type"] === AST_NODE_TYPES.MemberExpression;
    normalized[key] = normalizedAst(
      record[key],
      preserveLiteral || preservesAssertionContract || isPropertyName || isComputedMemberName,
    );
  }
  return normalized;
}

function isAssertionCall(node: TSESTree.CallExpression): boolean {
  const root = rootIdentifier(node.callee);
  return root !== null && ["assert", "expect"].includes(root.name);
}

function isAssertionStatement(statement: TSESTree.Statement): boolean {
  if (statement.type !== AST_NODE_TYPES.ExpressionStatement) return false;
  const expression = statement.expression;
  return expression.type === AST_NODE_TYPES.CallExpression && isAssertionCall(expression);
}

function isTypeOnlyContractStatement(statement: TSESTree.Statement): boolean {
  return statement.type === AST_NODE_TYPES.TSTypeAliasDeclaration ||
    statement.type === AST_NODE_TYPES.TSInterfaceDeclaration;
}

function normalizedLiteral(node: TSESTree.Literal): unknown {
  if ("regex" in node) {
    return ["Literal", "regex", node.regex.pattern, node.regex.flags];
  }
  const value = node.value;
  if (typeof value === "string") {
    return value.includes("\n") || value.length > MAX_NORMALIZED_STRING_LENGTH
      ? ["Literal", "string", value]
      : ["Literal", "string"];
  }
  if (value === null) {
    return ["Literal", "null"];
  }
  return ["Literal", typeof value];
}

export interface DuplicateTestBodyCandidate {
  readonly body: TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression;
  readonly container: TSESTree.Program | TSESTree.BlockStatement;
  readonly fingerprint: string;
}

export function duplicateTestBodyCandidate(
  call: TSESTree.CallExpression,
  sourceCode: Readonly<TSESLint.SourceCode>,
): DuplicateTestBodyCandidate | null {
  if (call.parent?.type !== AST_NODE_TYPES.ExpressionStatement) return null;
  const container = call.parent.parent;
  if (container?.type !== AST_NODE_TYPES.Program && container?.type !== AST_NODE_TYPES.BlockStatement) return null;
  const root = rootIdentifier(call.callee);
  if (root === null || !isDuplicateTestFrameworkIdentifier(root, sourceCode)) return null;
  const candidate = testBody(call);
  if (candidate === null) return null;
  const body = candidate.body;
  if (
    body.body.type !== AST_NODE_TYPES.BlockStatement ||
    body.body.body.length < MIN_STATEMENTS ||
    body.body.body.every(isAssertionStatement) ||
    body.body.body.some(isTypeOnlyContractStatement)
  ) {
    return null;
  }
  const comments = sourceCode.getCommentsInside(body.body).map((comment) => [comment.type, comment.value]);
  const fingerprint = JSON.stringify([
    candidate.signature,
    body.async,
    body.generator,
    normalizedAst(body.params),
    normalizedAst(body.body.body),
    comments,
  ]);
  return { body, container, fingerprint };
}

function testBody(call: TSESTree.CallExpression): {
  readonly body: TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression;
  readonly signature: string;
} | null {
  const signature = testCallerSignature(call.callee);
  if (signature === null || hasEachMember(call.callee)) {
    return null;
  }
  const title = call.arguments[0];
  if (
    title?.type !== AST_NODE_TYPES.Literal &&
    title?.type !== AST_NODE_TYPES.TemplateLiteral
  ) {
    return null;
  }
  const callback = call.arguments.find(
    (argument): argument is TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression =>
      argument.type !== AST_NODE_TYPES.SpreadElement && FUNCTION_TYPES.has(argument.type),
  );
  if (callback === undefined || call.arguments.length !== 2 || containsInlineSnapshot(callback.body)) {
    return null;
  }
  return { body: callback, signature };
}

function testCallerSignature(callee: TSESTree.Node): string | null {
  if (callee.type === AST_NODE_TYPES.Identifier) {
    return TEST_CALLERS.has(callee.name) ? callee.name : null;
  }
  if (callee.type === AST_NODE_TYPES.MemberExpression) {
    const base = testCallerSignature(callee.object);
    const member = staticMemberName(callee);
    return base !== null && member !== null && TEST_MODIFIERS.has(member) ? `${base}.${member}` : null;
  }
  if (callee.type === AST_NODE_TYPES.CallExpression) {
    return testCallerSignature(callee.callee);
  }
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) {
    return testCallerSignature(callee.tag);
  }
  return null;
}

function hasEachMember(callee: TSESTree.Node): boolean {
  if (callee.type === AST_NODE_TYPES.MemberExpression) {
    if (staticMemberName(callee) === "each") {
      return true;
    }
    return hasEachMember(callee.object);
  }
  if (callee.type === AST_NODE_TYPES.CallExpression) {
    return hasEachMember(callee.callee);
  }
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) {
    return hasEachMember(callee.tag);
  }
  return false;
}

function containsInlineSnapshot(node: TSESTree.Node): boolean {
  if (
    node.type === AST_NODE_TYPES.MemberExpression &&
    staticMemberName(node) !== null &&
    ["toMatchInlineSnapshot", "toThrowErrorMatchingInlineSnapshot"].includes(staticMemberName(node) ?? "")
  ) {
    return true;
  }
  for (const [key, value] of Object.entries(node)) {
    if (key === "parent") continue;
    const children = Array.isArray(value) ? value : [value];
    for (const child of children) {
      if (typeof child === "object" && child !== null && typeof (child as { type?: unknown }).type === "string") {
        if (containsInlineSnapshot(child as TSESTree.Node)) return true;
      }
    }
  }
  return false;
}

function isDuplicateTestFrameworkIdentifier(
  identifier: TSESTree.Identifier,
  sourceCode: Readonly<TSESLint.SourceCode>,
): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length === 0) return true;
  return variable.defs.some((definition) => {
    let current: TSESTree.Node | null | undefined = definition.node;
    while (current != null && current.type !== AST_NODE_TYPES.ImportDeclaration) current = current.parent;
    return current?.type === AST_NODE_TYPES.ImportDeclaration &&
      typeof current.source.value === "string" && TEST_MODULES.has(current.source.value);
  });
}

export default createRule<Options, MessageIds>({
  name: "duplicate-test-body",
  documentation: duplicateTestBodyDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow substantial sibling tests with the same body shape; express their differing inputs as a parameterized case table.",
    },
    schema: [],
    messages: {
      duplicateTestBody:
        "This test duplicates a sibling test's body. Create one named test or subtest per case; use `test.each(...)` or `it.each(...)` where the runner supports it.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    const siblings = new Map<TSESTree.Node, Set<string>>();
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const candidate = duplicateTestBodyCandidate(node, context.sourceCode);
        if (candidate === null) return;
        const fingerprints = siblings.get(candidate.container) ?? new Set<string>();
        if (fingerprints.has(candidate.fingerprint)) {
          context.report({ node, messageId: "duplicateTestBody" });
        }
        fingerprints.add(candidate.fingerprint);
        siblings.set(candidate.container, fingerprints);
      },
    };
  },
});

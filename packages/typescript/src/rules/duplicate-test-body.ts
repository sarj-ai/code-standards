/**
 * @fileoverview duplicate-test-body — sibling tests with the same substantial body are copy-paste cases that should be parameterized.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/duplicate-test-body.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "duplicateTestBody";
type Options = readonly [];

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const FUNCTION_TYPES: ReadonlySet<ESTree.Node["type"]> = new Set([
  "FunctionExpression",
  "ArrowFunctionExpression",
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

export const DUPLICATE_TEST_BODY_DOCUMENTATION = {
  summary:
    "Disallow substantial sibling tests with the same body shape; express their differing inputs as a parameterized case table.",
  rationale:
    "Copy-pasted test bodies hide the cases that differ and allow equivalent assertions to drift independently.",
  remediation:
    "Consider a case table with one named test or subtest per case; preserve setup lifetime, test modifiers, and each case's assertions rather than deleting coverage.",
  category: "testing",
  limitations: [
    "The rule compares substantial sibling tests within one suite and skips inline snapshots and materially different comments.",
    "Matching normalized body shapes do not prove runtime equivalence or independent setup; parameterization is a manual review, not an automatic deletion.",
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

function rootIdentifier(callee: ESTree.Node): ESTree.BindingIdentifier | null {
  if (callee.type === "Identifier") return callee;
  if (callee.type === "MemberExpression") return rootIdentifier(callee.object);
  if (callee.type === "CallExpression") return rootIdentifier(callee.callee);
  if (callee.type === "TaggedTemplateExpression") return rootIdentifier(callee.tag);
  return null;
}

function staticMemberName(member: ESTree.MemberExpression): string | null {
  if (!member.computed && member.property.type === "Identifier") return member.property.name;
  if (member.computed && member.property.type === "Literal" && typeof member.property.value === "string") {
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
  if (record["type"] === "Literal" && !preserveLiteral) {
    return normalizedLiteral(value as (ESTree.BooleanLiteral | ESTree.NullLiteral | ESTree.NumericLiteral | ESTree.StringLiteral | ESTree.BigIntLiteral | ESTree.RegExpLiteral));
  }
  const normalized: Record<string, unknown> = {};
  const preservesAssertionContract =
    record["type"] === "CallExpression" && isAssertionCall(value as ESTree.CallExpression);
  for (const key of Object.keys(record).sort()) {
    if (OMITTED_AST_KEYS.has(key)) {
      continue;
    }
    const isPropertyName =
      key === "key" &&
      (record["type"] === "Property" ||
        record["type"] === "MethodDefinition" ||
        record["type"] === "PropertyDefinition");
    const isComputedMemberName =
      key === "property" &&
      record["type"] === "MemberExpression";
    normalized[key] = normalizedAst(
      record[key],
      preserveLiteral || preservesAssertionContract || isPropertyName || isComputedMemberName,
    );
  }
  return normalized;
}

function isAssertionCall(node: ESTree.CallExpression): boolean {
  const root = rootIdentifier(node.callee);
  return root !== null && ["assert", "expect"].includes(root.name);
}

function isAssertionStatement(statement: ESTree.Statement): boolean {
  if (statement.type !== "ExpressionStatement") return false;
  const expression = statement.expression;
  return expression.type === "CallExpression" && isAssertionCall(expression);
}

function isTypeOnlyContractStatement(statement: ESTree.Statement): boolean {
  return statement.type === "TSTypeAliasDeclaration" ||
    statement.type === "TSInterfaceDeclaration";
}

function normalizedLiteral(node: (ESTree.BooleanLiteral | ESTree.NullLiteral | ESTree.NumericLiteral | ESTree.StringLiteral | ESTree.BigIntLiteral | ESTree.RegExpLiteral)): readonly string[] {
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
  readonly body: ESTree.Function | ESTree.ArrowFunctionExpression;
  readonly container: ESTree.Program | ESTree.BlockStatement;
  readonly fingerprint: string;
}

export function duplicateTestBodyCandidate(
  call: ESTree.CallExpression,
  sourceCode: Readonly<SourceCode>,
): DuplicateTestBodyCandidate | null {
  if (call.parent?.type !== "ExpressionStatement") return null;
  const container = call.parent.parent;
  if (container?.type !== "Program" && container?.type !== "BlockStatement") return null;
  const root = rootIdentifier(call.callee);
  if (root === null || !isDuplicateTestFrameworkIdentifier(root, sourceCode)) return null;
  const candidate = testBody(call);
  if (candidate === null) return null;
  const body = candidate.body;
  if (
    body.body === null || body.body.type !== "BlockStatement" ||
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

function testBody(call: ESTree.CallExpression): {
  readonly body: ESTree.Function | ESTree.ArrowFunctionExpression;
  readonly signature: string;
} | null {
  const signature = testCallerSignature(call.callee);
  if (signature === null || hasEachMember(call.callee)) {
    return null;
  }
  const title = call.arguments[0];
  if (
    title?.type !== "Literal" &&
    title?.type !== "TemplateLiteral"
  ) {
    return null;
  }
  const callback = call.arguments.find(
    (argument): argument is ESTree.Function | ESTree.ArrowFunctionExpression =>
      argument.type !== "SpreadElement" && FUNCTION_TYPES.has(argument.type),
  );
  if (callback === undefined || callback.body === null || call.arguments.length !== 2 || containsInlineSnapshot(callback.body)) {
    return null;
  }
  return { body: callback, signature };
}

function testCallerSignature(callee: ESTree.Node): string | null {
  if (callee.type === "Identifier") {
    return TEST_CALLERS.has(callee.name) ? callee.name : null;
  }
  if (callee.type === "MemberExpression") {
    const base = testCallerSignature(callee.object);
    const member = staticMemberName(callee);
    return base !== null && member !== null && TEST_MODIFIERS.has(member) ? `${base}.${member}` : null;
  }
  if (callee.type === "CallExpression") {
    return testCallerSignature(callee.callee);
  }
  if (callee.type === "TaggedTemplateExpression") {
    return testCallerSignature(callee.tag);
  }
  return null;
}

function hasEachMember(callee: ESTree.Node): boolean {
  if (callee.type === "MemberExpression") {
    if (staticMemberName(callee) === "each") {
      return true;
    }
    return hasEachMember(callee.object);
  }
  if (callee.type === "CallExpression") {
    return hasEachMember(callee.callee);
  }
  if (callee.type === "TaggedTemplateExpression") {
    return hasEachMember(callee.tag);
  }
  return false;
}

function containsInlineSnapshot(node: ESTree.Node): boolean {
  if (
    node.type === "MemberExpression" &&
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
        if (containsInlineSnapshot(child as ESTree.Node)) return true;
      }
    }
  }
  return false;
}

function isDuplicateTestFrameworkIdentifier(
  identifier: ESTree.BindingIdentifier,
  sourceCode: Readonly<SourceCode>,
): boolean {
  const variable = findVariable(sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length === 0) return true;
  return variable.defs.some((definition) => {
    if (definition.node.type === "ImportDefaultSpecifier") return definition.parent?.type === "ImportDeclaration" && definition.parent.source.value === "node:test";
    if (definition.node.type !== "ImportSpecifier") return false;
    const imported = definition.node.imported;
    if (!TEST_CALLERS.has(imported.type === "Identifier" ? imported.name : String(imported.value))) return false;
    let current: ESTree.Node | null | undefined = definition.node;
    while (current != null && current.type !== "ImportDeclaration") current = current.parent;
    return current?.type === "ImportDeclaration" &&
      typeof current.source.value === "string" && TEST_MODULES.has(current.source.value);
  });
}

export default createRule<Options, MessageIds>({
  name: "duplicate-test-body",
  documentation: DUPLICATE_TEST_BODY_DOCUMENTATION,
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
    if (!isTestFile(sourceOrigin(context).filename) || isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) {
      return {};
    }
    const siblings = new Map<ESTree.Node, Set<string>>();
    return {
      CallExpression(node: ESTree.CallExpression): void {
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

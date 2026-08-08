/**
 * @fileoverview duplicate-test-body — sibling tests with the same substantial body are copy-paste cases that should be parameterized.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/duplicate-test-body.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";

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

function normalizedAst(value: unknown, preserveLiteral = false): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => normalizedAst(item));
  }
  if (typeof value !== "object" || value === null) {
    return typeof value === "bigint" ? value.toString() : value;
  }
  const record = value as Record<string, unknown>;
  if (record["type"] === AST_NODE_TYPES.Literal && !preserveLiteral) {
    return normalizedLiteral(value as TSESTree.Literal);
  }
  const normalized: Record<string, unknown> = {};
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
    normalized[key] = normalizedAst(record[key], isPropertyName || isComputedMemberName);
  }
  return normalized;
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

export default createRule<Options, MessageIds>({
  name: "duplicate-test-body",
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
    if (!isTestFile(context.filename)) {
      return {};
    }
    const siblings = new Map<TSESTree.Node, Set<string>>();
    const isFrameworkTest = (identifier: TSESTree.Identifier): boolean => {
      const variable = ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);
      if (variable === null || variable.defs.length === 0) return true;
      return variable.defs.some((definition) => {
        let current: TSESTree.Node | null | undefined = definition.node;
        while (current != null && current.type !== AST_NODE_TYPES.ImportDeclaration) current = current.parent;
        return current?.type === AST_NODE_TYPES.ImportDeclaration &&
          typeof current.source.value === "string" && TEST_MODULES.has(current.source.value);
      });
    };
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (node.parent?.type !== AST_NODE_TYPES.ExpressionStatement) {
          return;
        }
        const container = node.parent.parent;
        if (
          container?.type !== AST_NODE_TYPES.Program &&
          container?.type !== AST_NODE_TYPES.BlockStatement
        ) {
          return;
        }
        const root = rootIdentifier(node.callee);
        if (root === null || !isFrameworkTest(root)) return;
        const candidate = testBody(node);
        if (candidate === null) {
          return;
        }
        const body = candidate.body;
        if (
          body.body.type !== AST_NODE_TYPES.BlockStatement ||
          body.body.body.length < MIN_STATEMENTS
        ) {
          return;
        }
        const comments = context.sourceCode
          .getCommentsInside(body.body)
          .map((comment) => [comment.type, comment.value]);
        const fingerprint = JSON.stringify([
          candidate.signature,
          body.async,
          body.generator,
          normalizedAst(body.params),
          normalizedAst(body.body.body),
          comments,
        ]);
        const fingerprints = siblings.get(container) ?? new Set<string>();
        if (fingerprints.has(fingerprint)) {
          context.report({ node, messageId: "duplicateTestBody" });
        }
        fingerprints.add(fingerprint);
        siblings.set(container, fingerprints);
      },
    };
  },
});

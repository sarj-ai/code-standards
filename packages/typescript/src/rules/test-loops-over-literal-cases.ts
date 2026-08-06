/**
 * @fileoverview test-loops-over-literal-cases — a literal case loop hides independently reportable test cases inside one test.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/test-loops-over-literal-cases.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "literalCaseLoop";
type Options = readonly [];

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const ASSERTION_ROOTS: ReadonlySet<string> = new Set([
  "assert",
  "assertType",
  "expect",
  "expectTypeOf",
]);
const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);
const MIN_CASES = 2;
const TEST_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "node:test", "vitest"]);
const ASSERTION_MODULES: ReadonlySet<string> = new Set([...TEST_MODULES, "node:assert", "node:assert/strict"]);

function rootIdentifier(callee: TSESTree.Node): TSESTree.Identifier | null {
  if (callee.type === AST_NODE_TYPES.Identifier) return callee;
  if (callee.type === AST_NODE_TYPES.MemberExpression) return rootIdentifier(callee.object);
  if (callee.type === AST_NODE_TYPES.CallExpression) return rootIdentifier(callee.callee);
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) return rootIdentifier(callee.tag);
  return null;
}

function callerName(callee: TSESTree.Node): string | null {
  if (callee.type === AST_NODE_TYPES.Identifier) {
    return callee.name;
  }
  if (callee.type === AST_NODE_TYPES.MemberExpression) {
    return callerName(callee.object);
  }
  if (callee.type === AST_NODE_TYPES.CallExpression) {
    return callerName(callee.callee);
  }
  if (callee.type === AST_NODE_TYPES.TaggedTemplateExpression) {
    return callerName(callee.tag);
  }
  return null;
}

function staticMemberName(member: TSESTree.MemberExpression): string | null {
  if (!member.computed && member.property.type === AST_NODE_TYPES.Identifier) return member.property.name;
  if (member.computed && member.property.type === AST_NODE_TYPES.Literal && typeof member.property.value === "string") {
    return member.property.value;
  }
  return null;
}

function isTestCaller(callee: TSESTree.Node): boolean {
  if (callee.type === AST_NODE_TYPES.Identifier) return TEST_CALLERS.has(callee.name);
  if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
  const member = staticMemberName(callee);
  return member !== null && TEST_MODIFIERS.has(member) && isTestCaller(callee.object);
}

function isTestBody(node: TSESTree.Node, isFrameworkTest: (identifier: TSESTree.Identifier) => boolean): boolean {
  const call = node.parent;
  const root = call?.type === AST_NODE_TYPES.CallExpression ? rootIdentifier(call.callee) : null;
  return (
    call?.type === AST_NODE_TYPES.CallExpression &&
    call.arguments.some((argument) => argument === node) &&
    isTestCaller(call.callee) &&
    root !== null &&
    isFrameworkTest(root)
  );
}

function nearestEnclosingFunction(
  node: TSESTree.Node,
): TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (FUNCTION_TYPES.has(current.type)) {
      return current as TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression;
    }
  }
  return null;
}

function isStaticCase(node: TSESTree.Node): boolean {
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSTypeAssertion ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    return isStaticCase(node.expression);
  }
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      return true;
    case AST_NODE_TYPES.TemplateLiteral:
      return node.expressions.length === 0;
    case AST_NODE_TYPES.UnaryExpression:
      return (node.operator === "+" || node.operator === "-") && isStaticCase(node.argument);
    case AST_NODE_TYPES.ArrayExpression:
      return node.elements.every(
        (element) => element !== null && element.type !== AST_NODE_TYPES.SpreadElement && isStaticCase(element),
      );
    case AST_NODE_TYPES.ObjectExpression:
      return node.properties.every(
        (property) =>
          property.type === AST_NODE_TYPES.Property &&
          !property.computed &&
          property.value.type !== AST_NODE_TYPES.AssignmentPattern &&
          isStaticCase(property.value),
      );
    default:
      return false;
  }
}

function walkOwnScope(node: TSESTree.Node, predicate: (current: TSESTree.Node) => boolean): boolean {
  if (predicate(node)) {
    return true;
  }
  for (const key of Object.keys(node)) {
    if (key === "parent") {
      continue;
    }
    const value = (node as unknown as Record<string, unknown>)[key];
    const children = Array.isArray(value) ? value : [value];
    for (const child of children) {
      if (
        typeof child !== "object" ||
        child === null ||
        typeof (child as { type?: unknown }).type !== "string"
      ) {
        continue;
      }
      const childNode = child as TSESTree.Node;
      if (!FUNCTION_TYPES.has(childNode.type) && walkOwnScope(childNode, predicate)) {
        return true;
      }
    }
  }
  return false;
}

function isAssertion(
  node: TSESTree.Node,
  isFrameworkAssertion: (identifier: TSESTree.Identifier) => boolean,
): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression || !ASSERTION_ROOTS.has(callerName(node.callee) ?? "")) return false;
  const root = rootIdentifier(node.callee);
  return root !== null && isFrameworkAssertion(root);
}

function opensSubtest(node: TSESTree.Node, callbackParameters: ReadonlySet<string>): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression) {
    return false;
  }
  const callee = node.callee;
  return callee.type === AST_NODE_TYPES.MemberExpression &&
    staticMemberName(callee) === "test" &&
    callee.object.type === AST_NODE_TYPES.Identifier &&
    callbackParameters.has(callee.object.name) &&
    node.arguments.some(
      (argument) => argument.type !== AST_NODE_TYPES.SpreadElement && FUNCTION_TYPES.has(argument.type),
    );
}

const LOOP_CARRIED_CONTROL: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.AssignmentExpression,
  AST_NODE_TYPES.UpdateExpression,
  AST_NODE_TYPES.BreakStatement,
  AST_NODE_TYPES.ContinueStatement,
  AST_NODE_TYPES.ReturnStatement,
  AST_NODE_TYPES.ThrowStatement,
]);

export default createRule<Options, MessageIds>({
  name: "test-loops-over-literal-cases",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow assertions over an inline literal case loop in a test; parameterization reports and names every case independently.",
    },
    schema: [],
    messages: {
      literalCaseLoop:
        "This loop asserts over {{count}} inline cases, but the runner sees one test and stops at the first failure. Create one named test or subtest per case; use `test.each(...)` or `it.each(...)` where supported.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename)) {
      return {};
    }
    const isFrameworkIdentifier = (
      identifier: TSESTree.Identifier,
      modules: ReadonlySet<string>,
    ): boolean => {
      const variable = ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);
      if (variable === null || variable.defs.length === 0) return true;
      return variable.defs.some((definition) => {
        let current: TSESTree.Node | null | undefined = definition.node;
        while (current != null && current.type !== AST_NODE_TYPES.ImportDeclaration) current = current.parent;
        return current?.type === AST_NODE_TYPES.ImportDeclaration &&
          typeof current.source.value === "string" && modules.has(current.source.value);
      });
    };
    const isFrameworkTest = (identifier: TSESTree.Identifier): boolean => isFrameworkIdentifier(identifier, TEST_MODULES);
    const isFrameworkAssertion = (identifier: TSESTree.Identifier): boolean => isFrameworkIdentifier(identifier, ASSERTION_MODULES);
    return {
      ForOfStatement(node: TSESTree.ForOfStatement): void {
        const enclosing = nearestEnclosingFunction(node);
        if (enclosing === null || !isTestBody(enclosing, isFrameworkTest)) {
          return;
        }
        const cases = unwrapExpression(node.right);
        const callbackParameters = new Set(
          enclosing.params.flatMap((parameter) => parameter.type === AST_NODE_TYPES.Identifier ? [parameter.name] : []),
        );
        if (
          cases.type !== AST_NODE_TYPES.ArrayExpression ||
          cases.elements.length < MIN_CASES ||
          !cases.elements.every(
            (element) =>
              element !== null && element.type !== AST_NODE_TYPES.SpreadElement && isStaticCase(element),
          ) ||
          !walkOwnScope(node.body, (current) => isAssertion(current, isFrameworkAssertion)) ||
          walkOwnScope(node.body, (current) => opensSubtest(current, callbackParameters)) ||
          walkOwnScope(node.body, (current) => LOOP_CARRIED_CONTROL.has(current.type))
        ) {
          return;
        }
        context.report({
          node,
          messageId: "literalCaseLoop",
          data: { count: String(cases.elements.length) },
        });
      },
    };
  },
});

function unwrapExpression(node: TSESTree.Expression): TSESTree.Expression {
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSTypeAssertion ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    return unwrapExpression(node.expression);
  }
  return node;
}

/**
 * @fileoverview test-loops-over-literal-cases — a literal case loop hides independently reportable test cases inside one test.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/test-loops-over-literal-cases.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "literalCaseLoop";
type Options = readonly [];

export const TEST_LOOPS_OVER_LITERAL_CASES_DOCUMENTATION = {
  summary: "Disallow assertions over an inline literal case loop in a test; parameterization reports and names every case independently.",
  rationale: "A loop is reported as one test, so failures hide the individual case name and may stop later cases from running.",
  remediation: "Create one named parameterized test or runner-aware subtest for each literal case.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**"],
  limitations: ["Only inline literal for-of cases containing framework assertions are reported. References to setup or parameters owned by the enclosing test, and loops followed by statements in the same or enclosing block, are excluded because they can belong to an ordered scenario. External helper purity is not inferred."],
  examples: [
    { id: "parameterized-cases", title: "Use a parameterized test", outcome: "no-match", files: [{ path: "src/parser.test.ts", source: "test.each(['a', 'b'])('parses %s', (value) => { expect(parse(value)).toBe(value); });" }], focusPath: "src/parser.test.ts", expectedCount: 0, public: true },
    { id: "looped-cases", title: "Do not hide cases in a loop", outcome: "match", files: [{ path: "src/parser.test.ts", source: "test('parses', () => { for (const value of ['a', 'b']) { expect(parse(value)).toBe(value); } });" }], focusPath: "src/parser.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const ASSERTION_ROOTS: ReadonlySet<string> = new Set([
  "assert",
  "assertType",
  "expect",
  "expectTypeOf",
]);
const FUNCTION_TYPES: ReadonlySet<ESTree.Node["type"]> = new Set([
  "FunctionDeclaration",
  "FunctionExpression",
  "ArrowFunctionExpression",
]);
const MIN_CASES = 2;
const TEST_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "node:test", "vitest"]);
const ASSERTION_MODULES: ReadonlySet<string> = new Set([...TEST_MODULES, "node:assert", "node:assert/strict"]);

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

function isTestBody(node: ESTree.Node, isFrameworkTest: (identifier: ESTree.BindingIdentifier) => boolean): boolean {
  const call = node.parent;
  const root = call?.type === "CallExpression" ? rootIdentifier(call.callee) : null;
  return (
    call?.type === "CallExpression" &&
    call.arguments.some((argument) => argument === node) &&
    isTestCaller(call.callee) &&
    root !== null &&
    isFrameworkTest(root)
  );
}

function isTestCaller(callee: ESTree.Node): boolean {
  if (callee.type === "Identifier") return TEST_CALLERS.has(callee.name);
  if (callee.type !== "MemberExpression") return false;
  const member = staticMemberName(callee);
  return member !== null && TEST_MODIFIERS.has(member) && isTestCaller(callee.object);
}

function nearestEnclosingFunction(
  node: ESTree.Node,
): ESTree.Function | ESTree.ArrowFunctionExpression | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (FUNCTION_TYPES.has(current.type)) {
      return current as ESTree.Function | ESTree.ArrowFunctionExpression;
    }
  }
  return null;
}

function isStaticCase(node: ESTree.Node): boolean {
  if (
    node.type === "TSAsExpression" ||
    node.type === "TSTypeAssertion" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  ) {
    return isStaticCase(node.expression);
  }
  switch (node.type) {
    case "Literal":
      return true;
    case "TemplateLiteral":
      return node.expressions.length === 0;
    case "UnaryExpression":
      return (node.operator === "+" || node.operator === "-") && isStaticCase(node.argument);
    case "ArrayExpression":
      return node.elements.every(
        (element) => element !== null && element.type !== "SpreadElement" && isStaticCase(element),
      );
    case "ObjectExpression":
      return node.properties.every(
        (property) =>
          property.type === "Property" &&
          !property.computed &&
          isStaticCase(property.value),
      );
    default:
      return false;
  }
}

function walkOwnScope(node: ESTree.Node, predicate: (current: ESTree.Node) => boolean): boolean {
  if (predicate(node)) {
    return true;
  }
  return forEachOwnAstChild(node, child =>
    !FUNCTION_TYPES.has(child.type) && walkOwnScope(child, predicate));
}

function isAssertion(
  node: ESTree.Node,
  isFrameworkAssertion: (identifier: ESTree.BindingIdentifier) => boolean,
): boolean {
  if (node.type !== "CallExpression" || !ASSERTION_ROOTS.has(callerName(node.callee) ?? "")) return false;
  const root = rootIdentifier(node.callee);
  return root !== null && isFrameworkAssertion(root);
}

function callerName(callee: ESTree.Node): string | null {
  if (callee.type === "Identifier") {
    return callee.name;
  }
  if (callee.type === "MemberExpression") {
    return callerName(callee.object);
  }
  if (callee.type === "CallExpression") {
    return callerName(callee.callee);
  }
  if (callee.type === "TaggedTemplateExpression") {
    return callerName(callee.tag);
  }
  return null;
}

function opensSubtest(node: ESTree.Node, callbackParameters: ReadonlySet<string>): boolean {
  if (node.type !== "CallExpression") {
    return false;
  }
  const callee = node.callee;
  return callee.type === "MemberExpression" &&
    staticMemberName(callee) === "test" &&
    callee.object.type === "Identifier" &&
    callbackParameters.has(callee.object.name) &&
    node.arguments.some(
      (argument) => argument.type !== "SpreadElement" && FUNCTION_TYPES.has(argument.type),
    );
}

const LOOP_CARRIED_CONTROL: ReadonlySet<string> = new Set([
  "AssignmentExpression",
  "UpdateExpression",
  "BreakStatement",
  "ContinueStatement",
  "ReturnStatement",
  "ThrowStatement",
]);

export default createRule<Options, MessageIds>({
  name: "test-loops-over-literal-cases",
  documentation: TEST_LOOPS_OVER_LITERAL_CASES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow assertions over an inline literal case loop in a test; parameterization reports and names every case independently.",
    },
    schema: [],
    messages: {
      literalCaseLoop:
        "This loop asserts over {{count}} inline cases in one test; a thrown assertion may prevent later cases from running. Create one named test or subtest per independent case; use `test.each(...)` or `it.each(...)` where supported.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(sourceOrigin(context).filename)) {
      return {};
    }
    const isFrameworkIdentifier = (
      identifier: ESTree.BindingIdentifier,
      modules: ReadonlySet<string>,
    ): boolean => {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      if (variable === null || variable.defs.length === 0) return true;
      return variable.defs.some((definition) => {
        let current: ESTree.Node | null | undefined = definition.node;
        while (current != null && current.type !== "ImportDeclaration") current = current.parent;
        return current?.type === "ImportDeclaration" &&
          typeof current.source.value === "string" && modules.has(current.source.value);
      });
    };
    const isFrameworkTest = (identifier: ESTree.BindingIdentifier): boolean => isFrameworkIdentifier(identifier, TEST_MODULES);
    const isFrameworkAssertion = (identifier: ESTree.BindingIdentifier): boolean => isFrameworkIdentifier(identifier, ASSERTION_MODULES);
    return {
      ForOfStatement(node: ESTree.ForOfStatement): void {
        const enclosing = nearestEnclosingFunction(node);
        if (enclosing === null || !isTestBody(enclosing, isFrameworkTest)) {
          return;
        }
        for (let current: ESTree.Node | null | undefined = node; current !== undefined && current !== enclosing; current = current.parent) {
          if (current.parent?.type === "BlockStatement" && current.parent.body.at(-1) !== current) return;
        }
        const cases = unwrapExpression(node.right);
        const callbackParameters = new Set(
          enclosing.params.flatMap((parameter) => parameter.type === "Identifier" ? [parameter.name] : []),
        );
        if (
          cases.type !== "ArrayExpression" ||
          cases.elements.length < MIN_CASES ||
          !cases.elements.every(
            (element) =>
              element !== null && element.type !== "SpreadElement" && isStaticCase(element),
          ) ||
          !walkOwnScope(node.body, (current) => isAssertion(current, isFrameworkAssertion)) ||
          walkOwnScope(node.body, (current) => opensSubtest(current, callbackParameters)) ||
          walkOwnScope(node.body, (current) => LOOP_CARRIED_CONTROL.has(current.type))
        ) {
          return;
        }
        const capturesSetup = walkOwnScope(node.body, (current) => {
          if (current.type !== "Identifier") return false;
          const variable = findVariable(context.sourceCode.getScope(current), current.name);
          if (variable === null || !variable.references.some((reference) => reference.identifier === current)) return false;
          return variable.defs.some((definition) => {
            const declaration = definition.name;
            return declaration.range[0] >= enclosing.range[0] && declaration.range[1] <= enclosing.range[1] &&
              (declaration.range[0] < node.range[0] || declaration.range[1] > node.range[1]);
          });
        });
        if (capturesSetup) return;
        context.report({
          node,
          messageId: "literalCaseLoop",
          data: { count: String(cases.elements.length) },
        });
      },
    };
  },
});

function unwrapExpression(node: ESTree.Expression): ESTree.Expression {
  if (
    node.type === "TSAsExpression" ||
    node.type === "TSTypeAssertion" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  ) {
    return unwrapExpression(node.expression);
  }
  return node;
}

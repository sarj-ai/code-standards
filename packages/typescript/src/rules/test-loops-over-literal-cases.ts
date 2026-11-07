/**
 * @fileoverview test-loops-over-literal-cases — a literal case loop hides independently reportable test cases inside one test.
 *
 * Port of the 18.x `test-loops-over-literal-cases` rule. The rule is
 * untyped, so the port covers all of it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/test-loops-over-literal-cases.test.ts
 */

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { directArgumentCall, forEachOwnAstChild, isErasedExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";
import { acceptedTestFrameworkName, type Identifier } from "../utils/test-mock-provenance.js";

const NAME = "test-loops-over-literal-cases";

const TEST_CALLERS: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const ASSERTION_ROOTS: ReadonlySet<string> = new Set([
  "assert",
  "assertType",
  "expect",
  "expectTypeOf",
]);
const FUNCTION_TYPES: ReadonlySet<string> = new Set([
  "FunctionDeclaration",
  "FunctionExpression",
  "ArrowFunctionExpression",
]);
const MIN_CASES = 2;

function rootIdentifier(callee: Node): Identifier | null {
  callee = unwrapExpression(callee);
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

function isTestBody(node: Node, isFrameworkTest: (identifier: Identifier) => boolean): boolean {
  const call = directArgumentCall(node);
  const root = call === null ? null : rootIdentifier(call.callee);
  return (
    call !== null &&
    isTestCaller(call.callee, isFrameworkTest) &&
    root !== null &&
    isFrameworkTest(root)
  );
}

function isTestCaller(callee: Node, isFrameworkTest: (identifier: Identifier) => boolean): boolean {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") return isFrameworkTest(callee);
  if (callee.type !== "MemberExpression") return false;
  const member = staticMemberName(callee);
  return member !== null && TEST_MODIFIERS.has(member) && isTestCaller(callee.object, isFrameworkTest);
}

function isStaticCase(node: Node): boolean {
  if (isErasedExpression(node)) return isStaticCase(node.expression);
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
          (property.value as Node).type !== "AssignmentPattern" &&
          isStaticCase(property.value),
      );
    default:
      return false;
  }
}

function walkOwnScope(node: Node, predicate: (current: Node) => boolean): boolean {
  if (predicate(node)) {
    return true;
  }
  return forEachOwnAstChild(node, child =>
    !FUNCTION_TYPES.has(child.type) && walkOwnScope(child, predicate));
}

function isAssertion(
  node: Node,
  isFrameworkAssertion: (identifier: Identifier) => boolean,
): boolean {
  if (node.type !== "CallExpression") return false;
  const root = rootIdentifier(node.callee);
  return root !== null && isFrameworkAssertion(root);
}

function opensSubtest(node: Node, callbackParameters: ReadonlySet<string>): boolean {
  if (node.type !== "CallExpression") {
    return false;
  }
  const callee = unwrapExpression(node.callee);
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

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow assertions over an inline literal case loop in a test; parameterization reports and names every case independently.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      literalCaseLoop:
        "This loop asserts over {{count}} inline cases in one test; a thrown assertion may prevent later cases from running. Create one named test or subtest per independent case; use `test.each(...)` or `it.each(...)` where supported.",
    },
  },
  createOnce(context) {
    let referenceIdentifiers = new WeakMap<TsVariable, ReadonlySet<Node>>();
    const isReference = (variable: TsVariable, identifier: Node): boolean => {
      let identifiers = referenceIdentifiers.get(variable);
      if (identifiers === undefined) {
        identifiers = new Set(variable.references.map((reference) => reference.identifier as Node));
        referenceIdentifiers.set(variable, identifiers);
      }
      return identifiers.has(identifier);
    };
    const isFrameworkTest = (identifier: Identifier): boolean => acceptedTestFrameworkName(context.sourceCode, identifier, "test", TEST_CALLERS) !== null;
    const isFrameworkAssertion = (identifier: Identifier): boolean => acceptedTestFrameworkName(context.sourceCode, identifier, "assertion", ASSERTION_ROOTS) !== null;
    return {
      before() {
        if (!isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        referenceIdentifiers = new WeakMap();
        return undefined;
      },
      ForOfStatement(node: ESTree.ForOfStatement): void {
        const enclosing = enclosingFunction(node);
        if (enclosing === null || !isTestBody(enclosing, isFrameworkTest)) {
          return;
        }
        for (let current: Node | null = node; current !== null && current !== enclosing; current = parentOf(current)) {
          const parent = parentOf(current);
          if (parent?.type === "BlockStatement" && parent.body.at(-1) !== current) return;
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
          if (variable === null || !isReference(variable, current)) return false;
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

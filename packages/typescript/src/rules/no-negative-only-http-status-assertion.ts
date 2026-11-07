/**
 * @fileoverview no-negative-only-http-status-assertion — a test that only excludes 5xx accepts every other wrong status.
 *
 * Port of the 18.x `no-negative-only-http-status-assertion` rule. The
 * rule is untyped, so the port covers all of it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-negative-only-http-status-assertion.test.ts
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { directArgumentCall, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { nativeFetchReference } from "../utils/native-fetch-reference.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { runtimeTestFrameworkName, vitestFixtureTestName, type Identifier } from "../utils/test-mock-provenance.js";

const NAME = "no-negative-only-http-status-assertion";

const SERVER_ERROR_MIN = 500;
const SERVER_ERROR_MAX = 599;
const HTTP_STATUS_MIN = 100;
const EXACT_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);
const FETCH_MODULES: ReadonlySet<string> = new Set(["undici", "node-fetch"]);

type TestFunction = ESTree.ArrowFunctionExpression | ESTree.Function;

interface StatusAssertion {
  readonly response: TsVariable;
  readonly expected: number;
  readonly matcher: string;
  readonly negative: boolean;
}

function statusAssertion(source: SourceCode, call: ESTree.CallExpression): StatusAssertion | null {
  const expected = call.arguments[0];
  if (call.arguments.length !== 1 || expected?.type !== "Literal" || typeof expected.value !== "number" ||
      call.callee.type !== "MemberExpression") return null;
  const matcher = getPropertyName(call.callee);
  if (matcher === null) return null;
  let object = unwrapExpression(call.callee.object);
  const negative = object.type === "MemberExpression" && getPropertyName(object) === "not";
  if (negative && object.type === "MemberExpression") object = unwrapExpression(object.object);
  const response = expectedResponse(source, object);
  return response === null ? null : { response, expected: expected.value, matcher, negative };
}

/** The response whose `status` an `expect(response.status)` call checks. */
function expectedResponse(source: SourceCode, object: Node): TsVariable | null {
  if (object.type !== "CallExpression" || object.arguments.length !== 1 || object.callee.type !== "Identifier" ||
      runtimeTestFrameworkName(source, object.callee, "assertion") !== "expect") return null;
  const argument = object.arguments[0];
  return argument === undefined || argument.type === "SpreadElement" ? null : fetchResponse(source, argument);
}
function fetchResponse(source: SourceCode, value: Node): TsVariable | null {
  const node = unwrapExpression(value);
  if (node.type !== "MemberExpression" || getPropertyName(node) !== "status" || node.object.type !== "Identifier") return null;
  return responseBinding(source, node.object);
}
function responseBinding(source: SourceCode, node: Identifier, seen = new Set<TsVariable>()): TsVariable | null {
  const variable = findVariable(source.getScope(node), node.name);
  if (variable?.defs.length !== 1 || seen.has(variable) || variable.references.some(reference => reference.isWrite() && !reference.init)) return null;
  seen.add(variable);
  const [definition] = variable.defs;
  if (definition === undefined) return null;
  const parameterName = definition.name as Node;
  if (definition.type === "Parameter" && parameterName.type === "Identifier") {
    return isGlobalResponseType(source, parameterName.typeAnnotation?.typeAnnotation) ? variable : null;
  }
  const declarator = definition.node;
  if (declarator.type !== "VariableDeclarator" || (parentOf(declarator) as ESTree.VariableDeclaration).kind !== "const" || declarator.init === null) return null;
  return constResponse(source, variable, declarator.init, seen);
}
/** A const bound to a native response, an awaited one, or another such binding. */
function constResponse(source: SourceCode, variable: TsVariable, init: Node, seen: Set<TsVariable>): TsVariable | null {
  let initial = unwrapExpression(init);
  if (initial.type === "AwaitExpression") initial = unwrapExpression(initial.argument);
  if (initial.type === "Identifier") return responseBinding(source, initial, seen);
  return nativeResponse(initial, source) ? variable : null;
}
function isUnshadowedResponse(source: SourceCode, node: Node): boolean {
  return (findVariable(source.getScope(node), "Response")?.defs.length ?? 0) === 0;
}
function isGlobalResponseType(source: SourceCode, annotation: Node | undefined): boolean {
  return annotation?.type === "TSTypeReference" && annotation.typeName.type === "Identifier" &&
    annotation.typeName.name === "Response" && isUnshadowedResponse(source, annotation.typeName);
}
function nativeResponse(initial: Node, source: SourceCode): boolean {
  if (initial.type === "NewExpression") {
    return initial.callee.type === "Identifier" && initial.callee.name === "Response" && isUnshadowedResponse(source, initial.callee);
  }
  if (initial.type !== "CallExpression") return false;
  if (nativeFetchReference(initial.callee, source)) return true;
  if (initial.callee.type !== "Identifier") return false;
  const callee = initial.callee;
  const binding = findVariable(source.getScope(callee), callee.name);
  if (binding === null || binding.defs.length === 0) return callee.name === "fetch";
  return binding.defs.length === 1 && isImportedFetch(binding.defs[0]);
}
/** A value import of `fetch` from undici or node-fetch, or node-fetch's default export. */
function isImportedFetch(imported: TsVariable["defs"][number] | undefined): boolean {
  const declaration = imported?.parent;
  if (imported?.type !== "ImportBinding" || declaration?.type !== "ImportDeclaration" ||
      declaration.importKind === "type" || !FETCH_MODULES.has(declaration.source.value)) return false;
  const specifier = imported.node;
  if (specifier.type === "ImportDefaultSpecifier") return declaration.source.value === "node-fetch";
  return specifier.type === "ImportSpecifier" && specifier.importKind !== "type" && importSpecifierName(specifier) === "fetch";
}

function enclosingTest(source: SourceCode, node: Node): TestFunction | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "FunctionDeclaration") return null;
    if (current.type !== "ArrowFunctionExpression" && current.type !== "FunctionExpression") continue;
    const registration = directArgumentCall(current);
    const callee = registration?.callee;
    if (callee?.type !== "Identifier") return null;
    const name = runtimeTestFrameworkName(source, callee, "test") ?? vitestFixtureTestName(source, callee);
    return name === "test" || name === "it" ? current : null;
  }
  return null;
}

function hasExactStatus(source: SourceCode, test: TestFunction, response: TsVariable): boolean {
  if (test.body?.type !== "BlockStatement") return false;
  return test.body.body.some(statement => {
    if (statement.type !== "ExpressionStatement") return false;
    let expression = unwrapExpression(statement.expression);
    if (expression.type === "AwaitExpression") expression = unwrapExpression(expression.argument);
    if (expression.type !== "CallExpression") return false;
    const assertion = statusAssertion(source, expression);
    return assertion !== null && assertion.response === response && !assertion.negative && EXACT_MATCHERS.has(assertion.matcher) &&
      Number.isInteger(assertion.expected) && assertion.expected >= HTTP_STATUS_MIN && assertion.expected <= SERVER_ERROR_MAX;
  });
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Assert the intended HTTP status instead of only excluding a server error.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { expectedStatus: "This assertion only excludes a server error; assert the intended HTTP status for the same response." },
  },
  createOnce(context) {
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const assertion = statusAssertion(context.sourceCode, node);
        if (assertion === null) return;
        const negativeOnly = assertion.negative && EXACT_MATCHERS.has(assertion.matcher) && assertion.expected >= SERVER_ERROR_MIN && assertion.expected <= SERVER_ERROR_MAX ||
          !assertion.negative && assertion.matcher === "toBeLessThan" && assertion.expected === SERVER_ERROR_MIN;
        if (!negativeOnly) return;
        const test = enclosingTest(context.sourceCode, node);
        if (test !== null && !hasExactStatus(context.sourceCode, test, assertion.response)) context.report({ node, messageId: "expectedStatus" });
      },
    };
  },
});

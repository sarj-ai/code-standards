/**
 * @fileoverview no-negative-only-http-status-assertion — Assert the intended HTTP status instead of only excluding a server error.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-negative-only-http-status-assertion.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { nativeFetchReference } from "./_native-fetch-reference.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { runtimeTestFrameworkName, vitestFixtureTestName } from "./_test-mock-provenance.js";
import { directArgumentCall, unwrapExpression } from "./_unwrap-expression.js";

const SERVER_ERROR_MIN = 500;
const SERVER_ERROR_MAX = 599;
const HTTP_STATUS_MIN = 100;
const EXACT_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);
const FETCH_MODULES: ReadonlySet<string> = new Set(["undici", "node-fetch"]);

export const NO_NEGATIVE_ONLY_HTTP_STATUS_ASSERTION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Assert the intended HTTP status instead of only excluding a server error.",
  rationale: "A response can avoid status 500 while still fail with an unrelated 400, 401 or 404, so the test can pass without exercising the intended behavior.",
  remediation: "Assert the expected response status or a deliberately bounded success/error contract. Preserve negative assertions that supplement an exact assertion for the same response.",
  category: "testing",
  autofix: "none",
  limitations: [
    "Checks direct Vitest/Jest/Bun/Playwright expect assertions in recognized test callbacks on a const response obtained from native fetch, runtime-imported undici/node-fetch, or unshadowed new Response. Direct global Response parameter annotations and stable const response aliases are also resolved. A server-error exclusion or status below 500 needs an accompanying unconditional exact HTTP status assertion for the same binding.",
    "Dynamic clients, mutable response bindings, helper functions, nested callbacks, status constants and nonliteral expected statuses are excluded. No HTTP intent is inferred from a variable name alone.",
    "An exact expected status is never guessed or inserted automatically. Nonliteral and richer response oracles require review outside this narrow detector.",
  ],
  examples: [
    { id: "only-excludes-server-error", title: "A missing route can still pass this test", outcome: "match", files: [{ path: "src/api.test.ts", source: "import {test,expect} from 'vitest'; test('reads', async () => { const response = await fetch('/versions'); expect(response.status).not.toBe(500); });" }], focusPath: "src/api.test.ts", expectedCount: 1, public: true },
    { id: "expects-intended-status", title: "Assert the API's intended result", outcome: "no-match", files: [{ path: "src/api.test.ts", source: "import {test,expect} from 'vitest'; test('reads', async () => { const response = await fetch('/versions'); expect(response.status).toBe(200); });" }], focusPath: "src/api.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

interface StatusAssertion {
  readonly response: TSESLint.Scope.Variable;
  readonly expected: number;
  readonly matcher: string;
  readonly negative: boolean;
}

function statusAssertion(source: Readonly<TSESLint.SourceCode>, call: TSESTree.CallExpression): StatusAssertion | null {
  if (call.arguments.length !== 1 || call.arguments[0]?.type !== AST_NODE_TYPES.Literal || typeof call.arguments[0].value !== "number" ||
      call.callee.type !== AST_NODE_TYPES.MemberExpression) return null;
  const matcher = ASTUtils.getPropertyName(call.callee);
  if (matcher === null) return null;
  let object = unwrapExpression(call.callee.object);
  const negative = object.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(object) === "not";
  if (negative && object.type === AST_NODE_TYPES.MemberExpression) object = unwrapExpression(object.object);
  if (object.type !== AST_NODE_TYPES.CallExpression || object.arguments.length !== 1 || object.callee.type !== AST_NODE_TYPES.Identifier ||
      runtimeTestFrameworkName(source, object.callee, "assertion") !== "expect") return null;
  const argument = object.arguments[0];
  const response = argument === undefined || argument.type === AST_NODE_TYPES.SpreadElement ? null : fetchResponse(source, argument);
  return response === null ? null : { response, expected: call.arguments[0].value, matcher, negative };
}
function fetchResponse(source: Readonly<TSESLint.SourceCode>, value: TSESTree.Node): TSESLint.Scope.Variable | null {
  const node = unwrapExpression(value);
  if (node.type !== AST_NODE_TYPES.MemberExpression || ASTUtils.getPropertyName(node) !== "status" || node.object.type !== AST_NODE_TYPES.Identifier) return null;
  return responseBinding(source, node.object);
}
function responseBinding(source: Readonly<TSESLint.SourceCode>, node: TSESTree.Identifier, seen = new Set<TSESLint.Scope.Variable>()): TSESLint.Scope.Variable | null {
  const variable = ASTUtils.findVariable(source.getScope(node), node.name);
  const definition = variable?.defs[0]?.node;
  if (variable?.defs.length !== 1 || seen.has(variable) || variable.references.some(reference => reference.isWrite() && !reference.init)) return null;
  seen.add(variable);
  const parameter = variable.defs[0];
  if (parameter?.type === "Parameter" && parameter.name.type === AST_NODE_TYPES.Identifier) {
    const annotation = parameter.name.typeAnnotation?.typeAnnotation;
    return annotation?.type === AST_NODE_TYPES.TSTypeReference && annotation.typeName.type === AST_NODE_TYPES.Identifier && annotation.typeName.name === "Response" &&
      (ASTUtils.findVariable(source.getScope(annotation.typeName), "Response")?.defs.length ?? 0) === 0 ? variable : null;
  }
  if (definition?.type !== AST_NODE_TYPES.VariableDeclarator || definition.parent.kind !== "const" || definition.init === null) return null;
  let initial = unwrapExpression(definition.init);
  if (initial.type === AST_NODE_TYPES.AwaitExpression) initial = unwrapExpression(initial.argument);
  if (initial.type === AST_NODE_TYPES.Identifier) return responseBinding(source, initial, seen);
  return nativeResponse(initial, source) ? variable : null;
}
function nativeResponse(initial: TSESTree.Node, source: Readonly<TSESLint.SourceCode>): boolean {
  if (initial.type === AST_NODE_TYPES.NewExpression && initial.callee.type === AST_NODE_TYPES.Identifier && initial.callee.name === "Response" &&
    (ASTUtils.findVariable(source.getScope(initial.callee), "Response")?.defs.length ?? 0) === 0) return true;
  if (initial.type === AST_NODE_TYPES.CallExpression && nativeFetchReference(initial.callee, source)) return true;
  if (initial.type !== AST_NODE_TYPES.CallExpression || initial.callee.type !== AST_NODE_TYPES.Identifier) return false;
  const callee = initial.callee;
  const binding = ASTUtils.findVariable(source.getScope(callee), callee.name);
  if ((binding?.defs.length ?? 0) === 0) return callee.name === "fetch";
  const imported = binding?.defs[0];
  if (binding?.defs.length !== 1 || imported?.type !== "ImportBinding" || imported.parent.type !== AST_NODE_TYPES.ImportDeclaration ||
      imported.parent.importKind === "type" || !FETCH_MODULES.has(imported.parent.source.value)) return false;
  const specifier = imported.node;
  if (specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier) return imported.parent.source.value === "node-fetch";
  if (specifier.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind === "type") return false;
  const importedName = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
  return importedName === "fetch";
}

function enclosingTest(source: Readonly<TSESLint.SourceCode>, node: TSESTree.Node): TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (current.type === AST_NODE_TYPES.FunctionDeclaration) return null;
    if (current.type !== AST_NODE_TYPES.ArrowFunctionExpression && current.type !== AST_NODE_TYPES.FunctionExpression) continue;
    const registration = directArgumentCall(current);
    const callee = registration?.callee;
    if (callee?.type !== AST_NODE_TYPES.Identifier) return null;
    const name = runtimeTestFrameworkName(source, callee, "test") ?? vitestFixtureTestName(source, callee);
    return name === "test" || name === "it" ? current : null;
  }
  return null;
}

function hasExactStatus(source: Readonly<TSESLint.SourceCode>, test: TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression, response: TSESLint.Scope.Variable): boolean {
  if (test.body.type !== AST_NODE_TYPES.BlockStatement) return false;
  return test.body.body.some(statement => {
    if (statement.type !== AST_NODE_TYPES.ExpressionStatement) return false;
    let expression = unwrapExpression(statement.expression);
    if (expression.type === AST_NODE_TYPES.AwaitExpression) expression = unwrapExpression(expression.argument);
    if (expression.type !== AST_NODE_TYPES.CallExpression) return false;
    const assertion = statusAssertion(source, expression);
    return assertion !== null && assertion.response === response && !assertion.negative && EXACT_MATCHERS.has(assertion.matcher) &&
      Number.isInteger(assertion.expected) && assertion.expected >= HTTP_STATUS_MIN && assertion.expected <= SERVER_ERROR_MAX;
  });
}

export default createRule<[], "expectedStatus">({
  name: "no-negative-only-http-status-assertion",
  documentation: NO_NEGATIVE_ONLY_HTTP_STATUS_ASSERTION_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_NEGATIVE_ONLY_HTTP_STATUS_ASSERTION_DOCUMENTATION.summary },
    schema: [],
    messages: { expectedStatus: "This assertion only excludes a server error; assert the intended HTTP status for the same response." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context) || isGeneratedFile(context, context.sourceCode.text)) return {};
    return {
      CallExpression(node): void {
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

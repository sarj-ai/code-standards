/**
 * @fileoverview no-tautological-expect — supported literal-only assertions that are known to pass.
 *
 * Port of the 18.x `no-tautological-expect` rule. Same algorithm; the
 * test-file gate and the matcher-customization scan run in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-tautological-expect.test.ts
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { directArgumentCall, forEachAstChild, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { acceptedTestFrameworkName, EXPECT_ASSERTION } from "../utils/test-mock-provenance.js";

const NAME = "no-tautological-expect";

/** Matchers that take the expected value as their single argument. */
const EQUALITY_MATCHERS: ReadonlySet<string> = new Set(["toBe", "toEqual", "toStrictEqual"]);

/** Matchers that take no argument, so the receiver alone fixes the outcome. */
const ZERO_ARG_MATCHERS: ReadonlyMap<string, (value: unknown) => boolean> = new Map([
  ["toBeDefined", (value) => value !== undefined],
  ["toBeUndefined", (value) => value === undefined],
  ["toBeNull", (value) => value === null],
  ["toBeTruthy", (value) => Boolean(value)],
  ["toBeFalsy", (value) => !value],
  ["toBeNaN", (value) => typeof value === "number" && Number.isNaN(value)],
]);

/** Enough of the operand to identify it in the message without pasting a screenful. */
const OPERAND_PREVIEW_CHARS = 40;

/** Sign prefixes: `-1` is a unary expression, not a literal, but it is constant. */
const NUMERIC_SIGNS: ReadonlySet<string> = new Set(["-", "+"]);
const THROW_MATCHERS: ReadonlySet<string> = new Set(["toThrow", "toThrowError", "toThrowErrorMatchingSnapshot", "toThrowErrorMatchingInlineSnapshot"]);

type Identifier = Extract<Node, { type: "Identifier" }>;

function constDeclarator(node: Node | undefined): ESTree.VariableDeclarator | null {
  if (node?.type !== "VariableDeclarator" || node.id.type !== "Identifier") return null;
  const declaration = parentOf(node);
  return declaration?.type === "VariableDeclaration" && declaration.kind === "const" && node.init !== null ? node : null;
}

function resolveLiteral(node: Node, sourceCode: SourceCode, seen: Set<Node> = new Set()): Node | null {
  node = unwrapExpression(node);
  if (isLiteral(node)) return node;
  if (node.type !== "Identifier" || seen.has(node)) return null;
  seen.add(node);
  const variable = findVariable(sourceCode.getScope(node), node.name);
  if (variable?.defs.length !== 1) return null;
  const declarator = constDeclarator(variable.defs[0]?.node);
  if (declarator?.init == null || declarator.init.range[1] > node.range[0] ||
      variable.references.some((reference) => reference.isWrite() && !reference.init)) return null;
  const value = resolveLiteral(declarator.init, sourceCode, seen);
  return value !== null && !isStructuralLiteral(value) ? value : null;
}

function isLiteral(node: Node): boolean {
  switch (node.type) {
    case "Literal":
      return !("regex" in node);
    case "TemplateLiteral":
      return node.expressions.length === 0;
    case "UnaryExpression":
      return NUMERIC_SIGNS.has(node.operator) && node.argument.type === "Literal" && typeof node.argument.value === "number";
    case "ArrayExpression":
      return node.elements.every((element) => element !== null && isLiteral(element));
    case "ObjectExpression":
      return node.properties.every(
        (property) => property.type === "Property" && !property.computed && isLiteral(property.value),
      );
    default:
      return false;
  }
}

function isStructuralLiteral(node: Node): boolean {
  return node.type === "ArrayExpression" || node.type === "ObjectExpression";
}

/** Resolve one optional negation; async modifiers do not prove a literal outcome. */
function expectOperand(
  callee: ESTree.MemberExpression,
  sourceCode: SourceCode,
): { readonly operand: Node; readonly negated: boolean } | null {
  let receiver = unwrapExpression(callee.object);
  const negated = receiver.type === "MemberExpression" && getPropertyName(receiver) === "not";
  if (negated && receiver.type === "MemberExpression") receiver = unwrapExpression(receiver.object);
  if (receiver.type !== "CallExpression") return null;
  const expectCallee = unwrapExpression(receiver.callee);
  if (
    expectCallee.type !== "Identifier" ||
    acceptedTestFrameworkName(sourceCode, expectCallee, "assertion", EXPECT_ASSERTION) === null ||
    (receiver.arguments.length !== 1 && !hasStaticMessage(receiver, expectCallee, sourceCode))
  ) {
    return null;
  }
  const operand = receiver.arguments[0];
  return operand === undefined ? null : { operand, negated };
}

function hasStaticMessage(call: ESTree.CallExpression, callee: Identifier, source: SourceCode): boolean {
  if (call.arguments.length !== 2) return false;
  const definition = findVariable(source.getScope(callee), callee.name)?.defs[0];
  const declaration = definition?.parent;
  if (definition?.type !== "ImportBinding" || declaration?.type !== "ImportDeclaration" ||
      !["vitest", "@playwright/test"].includes(declaration.source.value)) return false;
  const message = call.arguments[1];
  const literal = message === undefined ? null : resolveLiteral(message, source);
  return literal?.type === "Literal" && typeof literal.value === "string" || literal?.type === "TemplateLiteral";
}

function isExceptionContract(node: Node, source: SourceCode): boolean {
  const callback = enclosingSyncCallback(node);
  const call = callback === null ? null : directArgumentCall(callback);
  const member = call === null || call.optional ? null : throwMatcherOf(call);
  if (member === null) return false;
  const invocation = parentOf(outerExpression(member));
  return invocation?.type === "CallExpression" && !invocation.optional &&
    unwrapExpression(expectOperand(member, source)?.operand ?? member) === callback;
}

/** The nearest enclosing synchronous callback; a function declaration is never an exception contract. */
function enclosingSyncCallback(node: Node): ESTree.ArrowFunctionExpression | ESTree.Function | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "FunctionDeclaration") return null;
    if (current.type === "ArrowFunctionExpression" || current.type === "FunctionExpression") {
      return current.async || current.generator ? null : current;
    }
  }
  return null;
}

/** The `toThrow`-family member, optionally behind `.not`, that `call` is the receiver of. */
function throwMatcherOf(call: ESTree.CallExpression): ESTree.MemberExpression | null {
  let member = parentOf(outerExpression(call));
  if (member?.type === "MemberExpression" && getPropertyName(member) === "not") member = parentOf(outerExpression(member));
  return member?.type === "MemberExpression" && !member.optional && THROW_MATCHERS.has(getPropertyName(member) ?? "") ? member : null;
}

function customizedMatchers(source: SourceCode): ReadonlySet<string> {
  const customized = new Set<string>();
  // Only `expect.extend` and `expect.addEqualityTesters` customize matchers; both names appear in the text unless escaped.
  if (!source.text.includes("extend") && !source.text.includes("addEqualityTesters") && !source.text.includes("\\u")) return customized;
  const visitorKeys = source.visitorKeys;
  const visit = (node: Node): void => {
    if (node.type === "CallExpression") collectCustomization(node, source, customized);
    forEachAstChild(node, visitorKeys, visit);
  };
  visit(source.ast);
  return customized;
}

function collectCustomization(node: ESTree.CallExpression, source: SourceCode, customized: Set<string>): void {
  const member = unwrapExpression(node.callee);
  if (member.type !== "MemberExpression") return;
  const receiver = unwrapExpression(member.object);
  if (receiver.type !== "Identifier" || acceptedTestFrameworkName(source, receiver, "assertion", EXPECT_ASSERTION) === null) return;
  const method = getPropertyName(member);
  const first = node.arguments[0];
  const argument = first === undefined ? null : unwrapExpression(first);
  if (method === "addEqualityTesters" && !(argument?.type === "ArrayExpression" && argument.elements.length === 0)) {
    customized.add("toEqual");
    customized.add("toStrictEqual");
  }
  if (method !== "extend") return;
  if (argument?.type !== "ObjectExpression") {
    customized.add("*");
    return;
  }
  for (const property of argument.properties) {
    const name = property.type === "Property" ? getPropertyName(property) : null;
    customized.add(name ?? "*");
  }
}

interface Tautology {
  readonly messageId: "tautologicalComparison" | "tautologicalMatcher";
  readonly data: Readonly<Record<string, string>>;
}

function tautology(
  node: ESTree.CallExpression,
  matcher: string,
  assertion: { readonly operand: Node; readonly negated: boolean },
  source: SourceCode,
): Tautology | null {
  const written = node.arguments.length === 1 ? node.arguments[0] : undefined;
  if (!assertion.negated && matcher === "toBe" && written !== undefined && hasConstSelfIdentity(assertion.operand, written, source)) {
    return { messageId: "tautologicalComparison", data: { matcher, reason: "the same immutable binding" } };
  }
  const operand = resolveLiteral(assertion.operand, source);
  if (operand === null) return null;
  const passes = ZERO_ARG_MATCHERS.get(matcher);
  if (passes !== undefined && node.arguments.length === 0 && passes(literalValue(operand)) !== assertion.negated) {
    return { messageId: "tautologicalMatcher", data: { matcher: `${assertion.negated ? "not." : ""}${matcher}` } };
  }
  if (assertion.negated || !EQUALITY_MATCHERS.has(matcher) || written === undefined || !isLiteralEquality(matcher, operand, written, source)) {
    return null;
  }
  return { messageId: "tautologicalComparison", data: { matcher, reason: "literal setup" } };
}

/** The runtime value of a node `isLiteral` accepts; arrays and objects only need to be a defined, truthy object. */
function literalValue(node: Node) {
  switch (node.type) {
    case "Literal": return node.value;
    case "TemplateLiteral": return node.quasis[0]?.value.cooked;
    case "UnaryExpression": {
      const magnitude = node.argument.type === "Literal" ? Number(node.argument.value) : Number.NaN;
      return node.operator === "-" ? -magnitude : magnitude;
    }
    default: return {};
  }
}

function hasConstSelfIdentity(actual: Node, expected: Node, source: SourceCode): boolean {
  actual = unwrapExpression(actual);
  expected = unwrapExpression(expected);
  if (actual.type !== "Identifier" || expected.type !== "Identifier") return false;
  const variable = findVariable(source.getScope(actual), actual.name);
  if (variable?.defs.length !== 1 || findVariable(source.getScope(expected), expected.name) !== variable) return false;
  const declarator = constDeclarator(variable.defs[0]?.node);
  return declarator?.init != null && declarator.init.range[1] <= Math.min(actual.range[0], expected.range[0]) &&
    !variable.references.some((reference) => reference.isWrite() && !reference.init);
}

/** Literal `toBe`/`toEqual`/`toStrictEqual` comparisons whose two sides are written identically. */
function isLiteralEquality(matcher: string, operand: Node, written: Node, source: SourceCode): boolean {
  const expected = resolveLiteral(written, source);
  if (expected === null || (matcher === "toBe" && (isStructuralLiteral(operand) || isStructuralLiteral(expected)))) return false;
  // Textual identity, not structural: `expect(1).toBe(1.0)` is a
  // deliberate statement about representation and is left alone.
  return source.getText(operand) === source.getText(expected);
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Disallow supported assertions fixed by literal setup or immutable self identity.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      tautologicalComparison:
        "`expect({{operand}}).{{matcher}}({{operand}})` is fixed by {{reason}} and does not observe behavior. Assert against an independent expectation or remove only the redundant assertion, preserving the action and other coverage.",
      tautologicalMatcher:
        "`expect({{operand}}).{{matcher}}()` is statically known to pass. Assert on a produced value or remove only the redundant assertion, preserving other coverage.",
    },
  },
  createOnce(context) {
    let customized: ReadonlySet<string> = new Set();

    /** The operand as written, collapsed to one line and elided for the message. */
    const preview = (node: Node): string => {
      const text = context.sourceCode.getText(node).replaceAll(/\s+/gu, " ");
      return text.length > OPERAND_PREVIEW_CHARS ? `${text.slice(0, OPERAND_PREVIEW_CHARS)}…` : text;
    };

    return {
      before() {
        if (!isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        customized = customizedMatchers(context.sourceCode);
        return undefined;
      },
      CallExpression(node) {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression") return;
        const matcher = getPropertyName(callee);
        if (matcher === null || (!ZERO_ARG_MATCHERS.has(matcher) && !EQUALITY_MATCHERS.has(matcher)) ||
            customized.has("*") || customized.has(matcher)) return;
        const assertion = expectOperand(callee, context.sourceCode);
        if (assertion === null || isExceptionContract(node, context.sourceCode)) return;
        const finding = tautology(node, matcher, assertion, context.sourceCode);
        if (finding !== null) {
          context.report({ node, messageId: finding.messageId, data: { operand: preview(assertion.operand), ...finding.data } });
        }
      },
    };
  },
});

/**
 * @fileoverview no-bare-return-from-test-catch — returning from a caught failure can silently pass the rest of a test.
 *
 * Port of the 18.x `no-bare-return-from-test-catch` rule. Same
 * algorithm; helpers take the file's `SourceCode` instead of the rule context,
 * and the test-file and generated-file gates run in `before()`.
 */

import { defineRule, type ESTree, type Identifier, type Node, type SourceCode } from "../types.js";
import { directArgumentCall, forEachOwnAstChild, outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { acceptedTestFrameworkName, runtimeTestFrameworkName } from "../utils/test-mock-provenance.js";

const NAME = "no-bare-return-from-test-catch";

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;

const TEST_NAMES: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const TEST_BUILDERS: ReadonlySet<string> = new Set(["each", "for", "runIf", "skipIf"]);
const ASSERTION_NAMES: ReadonlySet<string> = new Set(["assert", "assertType", "expect", "expectTypeOf"]);
const FUNCTION_TYPES: ReadonlySet<string> = new Set(["ArrowFunctionExpression", "FunctionExpression", "FunctionDeclaration"]);

function staticMemberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  if (node.computed && node.property.type === "Literal" && typeof node.property.value === "string") return node.property.value;
  return null;
}

function rootIdentifier(callee: Node): Identifier | null {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") return callee;
  if (callee.type === "MemberExpression" || callee.type === "CallExpression") return rootIdentifier(callee.type === "MemberExpression" ? callee.object : callee.callee);
  return null;
}

function isDirectTestCallback(node: FunctionNode, source: SourceCode): boolean {
  const call = directArgumentCall(node);
  if (call === null) return false;
  const root = testRoot(call.callee);
  return root !== null && acceptedTestFrameworkName(source, root, "test", TEST_NAMES) !== null;
}

function testRoot(callee: Node): Identifier | null {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") return callee;
  if (callee.type === "CallExpression" || callee.type === "TaggedTemplateExpression") {
    const builder = unwrapExpression(callee.type === "CallExpression" ? callee.callee : callee.tag);
    if (builder.type !== "MemberExpression") return null;
    const name = staticMemberName(builder);
    return name !== null && (callee.type === "TaggedTemplateExpression" ? name === "each" || name === "for" : TEST_BUILDERS.has(name))
      ? testRoot(builder.object) : null;
  }
  if (callee.type !== "MemberExpression") return null;
  const modifier = staticMemberName(callee);
  return modifier !== null && TEST_MODIFIERS.has(modifier) ? testRoot(callee.object) : null;
}

function nearestFunction(node: Node): Node | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) if (FUNCTION_TYPES.has(current.type)) return current;
  return null;
}

function enclosingCatchClause(node: Node, owner: FunctionNode): ESTree.CatchClause | null {
  for (let current = parentOf(node); current !== null && current !== owner; current = parentOf(current)) {
    if (current.type === "CatchClause") return current;
  }
  return null;
}

function walkOwnScope(node: Node, predicate: (current: Node) => boolean): boolean {
  if (predicate(node)) return true;
  return forEachOwnAstChild(node, child =>
    !FUNCTION_TYPES.has(child.type) && walkOwnScope(child, predicate));
}

function isAssertion(node: Node, source: SourceCode): boolean {
  if (node.type !== "CallExpression") return false;
  const root = rootIdentifier(node.callee);
  return root !== null && acceptedTestFrameworkName(source, root, "assertion", ASSERTION_NAMES) !== null;
}

/** An `assert(...)` call, or an `expect(...)` matcher chain, possibly negated with `.not`. */
function isErrorAssertionCall(expression: Node, source: SourceCode): boolean {
  if (expression.type !== "CallExpression") return false;
  const root = rootIdentifier(expression.callee);
  if (root === null || acceptedTestFrameworkName(source, root, "assertion", ASSERTION_NAMES) === null) return false;
  const assertionName = runtimeTestFrameworkName(source, root, "assertion");
  if (assertionName === "assert") return true;
  let operand = expression.callee.type === "MemberExpression" ? expression.callee.object : null;
  if (operand?.type === "MemberExpression" && staticMemberName(operand) === "not") operand = operand.object;
  return assertionName === "expect" && operand?.type === "CallExpression" && operand.callee === root;
}

/** Whether the catch block asserts on the caught error before this return. */
function assertsCaughtError(node: ESTree.ReturnStatement, catchClause: ESTree.CatchClause, source: SourceCode): boolean {
  const parameter = catchClause.param;
  const returnBlock = node.parent;
  if (parameter?.type !== "Identifier" || returnBlock?.type !== "BlockStatement") return false;
  const errorBinding = findVariable(source.getScope(parameter), parameter.name);
  // Short reference lists cost less to scan than to index.
  const errorReferences = errorBinding !== null && errorBinding.references.length > 32
    ? new Set(errorBinding.references.map((reference) => reference.identifier))
    : undefined;
  const isErrorReference = (current: Node): boolean => current.type === "Identifier" &&
    (errorReferences?.has(current) ?? errorBinding?.references.some((reference) => reference.identifier === current)) === true;
  return returnBlock.body.some((statement) => statement.range[1] <= node.range[0] &&
    statement.type === "ExpressionStatement" && isErrorAssertionCall(statement.expression, source) &&
    walkOwnScope(statement.expression, isErrorReference));
}

function isExplicitSkip(node: Node, source: SourceCode): boolean {
  if (node.type !== "CallExpression") return false;
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression" || staticMemberName(callee) !== "skip") return false;
  const root = rootIdentifier(callee.object);
  return root !== null && acceptedTestFrameworkName(source, root, "test", TEST_NAMES) !== null;
}

function isUnconditionalContextSkip(node: Node, owner: FunctionNode, source: SourceCode): boolean {
  if (node.type !== "CallExpression" || node.optional || !hasUnconditionalSkipArguments(node)) return false;
  const parameter = testContextParameter(owner, source);
  const callee = unwrapExpression(node.callee);
  if (parameter?.type === "Identifier") return isContextMemberSkip(callee, parameter, source);
  if (parameter?.type === "ObjectPattern") return isDestructuredSkip(callee, parameter, source);
  return false;
}

/** `skip()`, `skip(note)` or `skip(true[, note])`: a skip with no runtime condition. */
function hasUnconditionalSkipArguments(call: ESTree.CallExpression): boolean {
  const [argument] = call.arguments;
  if (argument === undefined) return true;
  const first = unwrapExpression(argument);
  if (first.type === "Literal" && first.value === true) return call.arguments.length <= 2;
  const note = first.type === "Literal" && typeof first.value === "string" ||
    first.type === "TemplateLiteral" && first.expressions.length === 0;
  return note && call.arguments.length === 1;
}

/** `context.skip()` on the test callback's context parameter. */
function isContextMemberSkip(callee: Node, parameter: Identifier, source: SourceCode): boolean {
  if (callee.type !== "MemberExpression" || callee.optional || staticMemberName(callee) !== "skip") return false;
  const receiver = unwrapExpression(callee.object);
  return receiver.type === "Identifier" && isStableParameterReference(receiver, parameter, source, true);
}

/** `skip()` destructured from the test callback's context parameter. */
function isDestructuredSkip(callee: Node, pattern: ESTree.ObjectPattern, source: SourceCode): boolean {
  if (callee.type !== "Identifier") return false;
  return pattern.properties.some((property) => property.type === "Property" &&
    getPropertyName(property) === "skip" && property.value.type === "Identifier" &&
    isStableParameterReference(callee, property.value, source, false));
}

function testContextParameter(owner: FunctionNode, source: SourceCode): ESTree.ParamPattern | null {
  const call = directArgumentCall(owner);
  if (call === null) return null;
  const root = testRoot(call.callee);
  if (root === null) return null;
  const binding = findVariable(source.getScope(root), root.name);
  const definition = binding?.defs[0];
  const runnerGlobal = binding === null || binding.defs.length === 0;
  const vitestImport = binding?.defs.length === 1 && definition?.node.type === "ImportSpecifier" &&
    definition.node.parent.type === "ImportDeclaration" && definition.node.parent.source.value === "vitest";
  if (!runnerGlobal && !vitestImport) return null;
  const position = contextParameterPosition(call.callee);
  return position === null ? null : owner.params[position] ?? null;
}

/** Vitest each spreads only case data; for appends its TestContext after one row. */
function contextParameterPosition(callee: Node): number | null {
  callee = unwrapExpression(callee);
  if (callee.type === "Identifier") return 0;
  if (callee.type === "MemberExpression") return contextParameterPosition(callee.object);
  if (callee.type !== "CallExpression" && callee.type !== "TaggedTemplateExpression") return null;
  const builder = unwrapExpression(callee.type === "CallExpression" ? callee.callee : callee.tag);
  if (builder.type !== "MemberExpression") return null;
  const name = staticMemberName(builder);
  const inherited = contextParameterPosition(builder.object);
  return name === "each" || inherited === null ? null : name === "for" ? 1 : inherited;
}

function isStableParameterReference(
  identifier: Identifier,
  parameter: Identifier,
  source: SourceCode,
  memberReceiver: boolean,
): boolean {
  const binding = findVariable(source.getScope(parameter), parameter.name);
  if (binding === null || binding !== findVariable(source.getScope(identifier), identifier.name)) return false;
  return binding.references.every((reference) => {
    if (reference.isWrite() && !reference.init) return false;
    return !memberReceiver || !writesSkipMember(reference.identifier);
  });
}

/** Whether this context reference reassigns, updates or deletes its `skip` (or a computed) member. */
function writesSkipMember(identifier: Node): boolean {
  const receiver = outerExpression(identifier);
  const member = receiver.parent;
  if (member?.type !== "MemberExpression" || member.object !== receiver) return false;
  const name = staticMemberName(member);
  if (name !== null && name !== "skip") return false;
  const use = outerExpression(member);
  const parent = parentOf(use);
  // A member expression always has a parent; Oxlint only types it nullable.
  if (parent === null) return false;
  return parent.type === "AssignmentExpression" && parent.left === use ||
    parent.type === "UpdateExpression" && parent.argument === use ||
    parent.type === "UnaryExpression" && parent.operator === "delete" && parent.argument === use;
}

function hasDominatingExplicitSkip(
  node: ESTree.ReturnStatement,
  owner: FunctionNode,
  source: SourceCode,
): boolean {
  const block = node.parent;
  if (block?.type !== "BlockStatement") return false;
  return block.body.some(
    (candidate) =>
      candidate.range[1] <= node.range[0] &&
      candidate.type === "ExpressionStatement" &&
      (isExplicitSkip(candidate.expression, source) || isUnconditionalContextSkip(candidate.expression, owner, source)),
  );
}

export default defineRule({
  meta: {
    type: "problem",
    docs: { description: "Disallow a bare return from a test catch block when it skips a later assertion.", url: docsUrl(NAME) },
    schema: [],
    messages: { bareReturnFromTestCatch: "This bare return can swallow the caught failure and skips a later assertion. Rethrow, assert on the error, or explicitly skip the test." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    return {
      before(): boolean | void {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, sourceCode.text)) return false;
      },
      ReturnStatement(node: ESTree.ReturnStatement): void {
        if (node.argument !== null) return;
        const owner = nearestFunction(node);
        if ((owner?.type !== "ArrowFunctionExpression" && owner?.type !== "FunctionExpression") || !isDirectTestCallback(owner, sourceCode)) return;
        const catchClause = enclosingCatchClause(node, owner);
        if (catchClause === null || assertsCaughtError(node, catchClause, sourceCode)) return;
        if (hasDominatingExplicitSkip(node, owner, sourceCode)) return;
        if (owner.body === null || !walkOwnScope(owner.body, (current) => current.range[0] > node.range[1] && isAssertion(current, sourceCode))) return;
        context.report({ node, messageId: "bareReturnFromTestCatch" });
      },
    };
  },
});

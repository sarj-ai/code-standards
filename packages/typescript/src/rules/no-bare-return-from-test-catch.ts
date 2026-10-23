/**
 * @fileoverview no-bare-return-from-test-catch — returning from a caught failure can silently pass the rest of a test.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-bare-return-from-test-catch.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { directArgumentCall, outerExpression, unwrapExpression } from "./_unwrap-expression.js";

import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { runtimeTestFrameworkName } from "./_test-mock-provenance.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "bareReturnFromTestCatch";
type Options = readonly [];
type FunctionNode = TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression;
type Context = Readonly<TSESLint.RuleContext<MessageIds, Options>>;

export const NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION = {
  summary: "Disallow a bare return from a test catch block when it skips a later assertion.",
  rationale: "An unasserted catch return can swallow a failure and skip later assertions; the complete test result also depends on other assertions and hooks.",
  remediation: "Rethrow the error, assert on it, or use the runner's explicit skip mechanism when the capability is optional.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only bare returns owned by an inline supported test callback and followed lexically by a framework assertion are reported, including each/for tables and runIf/skipIf builders. Custom builders and indirect callback references are excluded. A runner skip suppresses the finding only when it is an unconditional earlier statement in the return's block. Vitest imports and unshadowed runner globals support TestContext.skip on the first ordinary-test parameter or second for-table parameter, including a directly destructured skip alias; each-table data arguments, reassigned bindings, overwritten skip methods and dynamic skip conditions are excluded."],
  examples: [
    { id: "rethrow", title: "Preserve the failure", outcome: "no-match", files: [{ path: "src/codec.test.ts", source: "test('decodes', () => { try { decode(); } catch (error) { throw error; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 0, public: true },
    { id: "bare-return", title: "Do not silently pass", outcome: "match", files: [{ path: "src/codec.test.ts", source: "test('decodes', () => { try { decode(); } catch { return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 1, public: true },
    { id: "table-bare-return", scenarioId: "table-catch", title: "Case tables must preserve failures", outcome: "match", files: [{ path: "src/codec.test.ts", source: "test.each(['valid', 'invalid'])('decodes %s', (input) => { try { decode(input); } catch { return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 1, public: true },
    { id: "table-rethrow", scenarioId: "table-catch", title: "Each table case propagates its failure", outcome: "no-match", files: [{ path: "src/codec.test.ts", source: "test.each(['valid', 'invalid'])('decodes %s', (input) => { try { decode(input); } catch (error) { throw error; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 0, public: true },
    { id: "table-context-skip", scenarioId: "context-skip", title: "A Vitest context skip preserves an optional table case", outcome: "no-match", files: [{ path: "src/codec.test.ts", source: "import {test, expect} from 'vitest'; test.for(['optional'])('decodes %s', (input, context) => { try { decode(input); } catch { context.skip('codec unavailable'); return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 0, public: true },
    { id: "table-context-false-skip", scenarioId: "context-skip", title: "A false skip condition does not preserve the failure", outcome: "match", files: [{ path: "src/codec.test.ts", source: "import {test, expect} from 'vitest'; test.for(['optional'])('decodes %s', (input, context) => { try { decode(input); } catch { context.skip(false); return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const TEST_NAMES: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const TEST_BUILDERS: ReadonlySet<string> = new Set(["each", "for", "runIf", "skipIf"]);
const ASSERTION_NAMES: ReadonlySet<string> = new Set(["assert", "assertType", "expect", "expectTypeOf"]);
const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([AST_NODE_TYPES.ArrowFunctionExpression, AST_NODE_TYPES.FunctionExpression, AST_NODE_TYPES.FunctionDeclaration]);

function staticMemberName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  if (node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string") return node.property.value;
  return null;
}

function rootIdentifier(callee: TSESTree.Node): TSESTree.Identifier | null {
  callee = unwrapExpression(callee);
  if (callee.type === AST_NODE_TYPES.Identifier) return callee;
  if (callee.type === AST_NODE_TYPES.MemberExpression || callee.type === AST_NODE_TYPES.CallExpression) return rootIdentifier(callee.type === AST_NODE_TYPES.MemberExpression ? callee.object : callee.callee);
  return null;
}

function isDirectTestCallback(node: TSESTree.Node, context: Context): node is FunctionNode {
  if (node.type !== AST_NODE_TYPES.ArrowFunctionExpression && node.type !== AST_NODE_TYPES.FunctionExpression) return false;
  const call = directArgumentCall(node);
  if (call === null) return false;
  const root = testRoot(call.callee);
  return root !== null && TEST_NAMES.has(runtimeTestFrameworkName(context.sourceCode, root, "test") ?? "");
}

function testRoot(callee: TSESTree.Node): TSESTree.Identifier | null {
  callee = unwrapExpression(callee);
  if (callee.type === AST_NODE_TYPES.Identifier) return callee;
  if (callee.type === AST_NODE_TYPES.CallExpression || callee.type === AST_NODE_TYPES.TaggedTemplateExpression) {
    const builder = unwrapExpression(callee.type === AST_NODE_TYPES.CallExpression ? callee.callee : callee.tag);
    if (builder.type !== AST_NODE_TYPES.MemberExpression) return null;
    const name = staticMemberName(builder);
    return name !== null && (callee.type === AST_NODE_TYPES.TaggedTemplateExpression ? name === "each" || name === "for" : TEST_BUILDERS.has(name))
      ? testRoot(builder.object) : null;
  }
  if (callee.type !== AST_NODE_TYPES.MemberExpression) return null;
  const modifier = staticMemberName(callee);
  return modifier !== null && TEST_MODIFIERS.has(modifier) ? testRoot(callee.object) : null;
}

function nearestFunction(node: TSESTree.Node): TSESTree.Node | null {
  for (let current = node.parent; current !== undefined && current !== null; current = current.parent) if (FUNCTION_TYPES.has(current.type)) return current;
  return null;
}

function walkOwnScope(node: TSESTree.Node, predicate: (current: TSESTree.Node) => boolean): boolean {
  if (predicate(node)) return true;
  return forEachOwnAstChild(node, child =>
    !FUNCTION_TYPES.has(child.type) && walkOwnScope(child, predicate));
}

function isAssertion(node: TSESTree.Node, context: Context): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression) return false;
  const root = rootIdentifier(node.callee);
  return root !== null && ASSERTION_NAMES.has(runtimeTestFrameworkName(context.sourceCode, root, "assertion") ?? "");
}

function isExplicitSkip(node: TSESTree.Node, context: Context): boolean {
  const unwrappedNodeCallee = node.type === "CallExpression" || node.type === "NewExpression" ? unwrapExpression(node.callee) : null;
  if (node.type !== AST_NODE_TYPES.CallExpression || unwrappedNodeCallee?.type !== AST_NODE_TYPES.MemberExpression || staticMemberName(unwrappedNodeCallee) !== "skip") return false;
  const root = rootIdentifier(unwrappedNodeCallee.object);
  return root !== null && TEST_NAMES.has(runtimeTestFrameworkName(context.sourceCode, root, "test") ?? "");
}

function isUnconditionalContextSkip(node: TSESTree.Node, owner: FunctionNode, context: Context): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression || node.optional) return false;
  const first = node.arguments[0] === undefined ? undefined : unwrapExpression(node.arguments[0]);
  const note = first?.type === AST_NODE_TYPES.Literal && typeof first.value === "string" ||
    first?.type === AST_NODE_TYPES.TemplateLiteral && first.expressions.length === 0;
  const always = first?.type === AST_NODE_TYPES.Literal && first.value === true;
  if (node.arguments.length !== 0 && !(node.arguments.length === 1 && note) && !(node.arguments.length <= 2 && always)) return false;
  const parameter = testContextParameter(owner, context);
  const callee = unwrapExpression(node.callee);
  if (parameter?.type === AST_NODE_TYPES.Identifier && callee.type === AST_NODE_TYPES.MemberExpression &&
      !callee.optional && staticMemberName(callee) === "skip") {
    const receiver = unwrapExpression(callee.object);
    return receiver.type === AST_NODE_TYPES.Identifier && isStableParameterReference(receiver, parameter, context, true);
  }
  if (parameter?.type !== AST_NODE_TYPES.ObjectPattern || callee.type !== AST_NODE_TYPES.Identifier) return false;
  return parameter.properties.some((property) => property.type === AST_NODE_TYPES.Property &&
    ASTUtils.getPropertyName(property) === "skip" && property.value.type === AST_NODE_TYPES.Identifier &&
    isStableParameterReference(callee, property.value, context, false));
}

function testContextParameter(owner: FunctionNode, context: Context): TSESTree.Parameter | null {
  const call = directArgumentCall(owner);
  if (call === null) return null;
  const root = testRoot(call.callee);
  if (root === null) return null;
  const binding = ASTUtils.findVariable(context.sourceCode.getScope(root), root.name);
  const definition = binding?.defs[0];
  const runnerGlobal = binding === null || binding.defs.length === 0;
  const vitestImport = binding?.defs.length === 1 && definition?.node.type === AST_NODE_TYPES.ImportSpecifier &&
    definition.node.parent.type === AST_NODE_TYPES.ImportDeclaration && definition.node.parent.source.value === "vitest";
  if (!runnerGlobal && !vitestImport) return null;
  const position = contextParameterPosition(call.callee);
  return position === null ? null : owner.params[position] ?? null;
}

/** Vitest each spreads only case data; for appends its TestContext after one row. */
function contextParameterPosition(callee: TSESTree.Node): number | null {
  callee = unwrapExpression(callee);
  if (callee.type === AST_NODE_TYPES.Identifier) return 0;
  if (callee.type === AST_NODE_TYPES.MemberExpression) return contextParameterPosition(callee.object);
  if (callee.type !== AST_NODE_TYPES.CallExpression && callee.type !== AST_NODE_TYPES.TaggedTemplateExpression) return null;
  const builder = unwrapExpression(callee.type === AST_NODE_TYPES.CallExpression ? callee.callee : callee.tag);
  if (builder.type !== AST_NODE_TYPES.MemberExpression) return null;
  const name = staticMemberName(builder);
  const inherited = contextParameterPosition(builder.object);
  return name === "each" || inherited === null ? null : name === "for" ? 1 : inherited;
}

function isStableParameterReference(
  identifier: TSESTree.Identifier,
  parameter: TSESTree.Identifier,
  context: Context,
  memberReceiver: boolean,
): boolean {
  const source = context.sourceCode;
  const binding = ASTUtils.findVariable(source.getScope(parameter), parameter.name);
  if (binding === null || binding !== ASTUtils.findVariable(source.getScope(identifier), identifier.name)) return false;
  return binding.references.every((reference) => {
    if (reference.isWrite() && !reference.init) return false;
    if (!memberReceiver) return true;
    const receiver = outerExpression(reference.identifier);
    const member = receiver.parent;
    if (member?.type !== AST_NODE_TYPES.MemberExpression || member.object !== receiver) return true;
    const name = staticMemberName(member);
    if (name !== null && name !== "skip") return true;
    const use = outerExpression(member);
    const parent = use.parent;
    return !(parent.type === AST_NODE_TYPES.AssignmentExpression && parent.left === use) &&
      !(parent.type === AST_NODE_TYPES.UpdateExpression && parent.argument === use) &&
      !(parent.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "delete" && parent.argument === use);
  });
}

function hasDominatingExplicitSkip(
  node: TSESTree.ReturnStatement,
  owner: FunctionNode,
  context: Context,
): boolean {
  const block = node.parent;
  if (block?.type !== AST_NODE_TYPES.BlockStatement) return false;
  return block.body.some(
    (candidate) =>
      candidate.range[1] <= node.range[0] &&
      candidate.type === AST_NODE_TYPES.ExpressionStatement &&
      (isExplicitSkip(candidate.expression, context) || isUnconditionalContextSkip(candidate.expression, owner, context)),
  );
}

export default createRule<Options, MessageIds>({
  name: "no-bare-return-from-test-catch",
  documentation: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: "Disallow a bare return from a test catch block when it skips a later assertion." },
    schema: [],
    messages: { bareReturnFromTestCatch: "This bare return can swallow the caught failure and skips a later assertion. Rethrow, assert on the error, or explicitly skip the test." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context) || isGeneratedFile(context, context.sourceCode.text)) return {};
    return {
      ReturnStatement(node: TSESTree.ReturnStatement): void {
        if (node.argument !== null) return;
        const owner = nearestFunction(node);
        if (owner === null || !isDirectTestCallback(owner, context)) return;
        let catchClause: TSESTree.CatchClause | null = null;
        for (let current: TSESTree.Node | null | undefined = node.parent; current !== owner; current = current?.parent) {
          if (current?.type === AST_NODE_TYPES.CatchClause) { catchClause = current; break; }
          if (current === null || current === undefined) break;
        }
        if (catchClause === null) return;
        const parameter = catchClause.param;
        const returnBlock = node.parent;
        if (parameter?.type === AST_NODE_TYPES.Identifier && returnBlock?.type === AST_NODE_TYPES.BlockStatement) {
          const errorBinding = ASTUtils.findVariable(context.sourceCode.getScope(parameter), parameter.name);
          // Short reference lists cost less to scan than to index.
          const errorReferences = errorBinding !== null && errorBinding.references.length > 32
            ? new Set(errorBinding.references.map((reference) => reference.identifier))
            : undefined;
          const assertedError = returnBlock.body.some((statement) => {
            if (statement.range[1] > node.range[0] || statement.type !== AST_NODE_TYPES.ExpressionStatement) return false;
            const expression = statement.expression;
            if (expression.type !== AST_NODE_TYPES.CallExpression || !isAssertion(expression, context)) return false;
            const root = rootIdentifier(expression.callee);
            if (root === null) return false;
            const assertionName = runtimeTestFrameworkName(context.sourceCode, root, "assertion");
            let operand = expression.callee.type === AST_NODE_TYPES.MemberExpression ? expression.callee.object : null;
            if (operand?.type === AST_NODE_TYPES.MemberExpression && staticMemberName(operand) === "not") operand = operand.object;
            if (assertionName !== "assert" && (assertionName !== "expect" || operand?.type !== AST_NODE_TYPES.CallExpression || operand.callee !== root)) return false;
            return walkOwnScope(expression, (current) => current.type === AST_NODE_TYPES.Identifier && (errorReferences?.has(current) ?? errorBinding?.references.some((reference) => reference.identifier === current)) === true);
          });
          if (assertedError) return;
        }
        if (hasDominatingExplicitSkip(node, owner, context)) return;
        if (!walkOwnScope(owner.body, (current) => current.range[0] > node.range[1] && isAssertion(current, context))) return;
        context.report({ node, messageId: "bareReturnFromTestCatch" });
      },
    };
  },
});

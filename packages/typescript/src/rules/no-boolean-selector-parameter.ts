/**
 * @fileoverview no-boolean-selector-parameter — preserve boolean data and required contracts while identifying operation selectors.
 *
 * Port of the 18.x `no-boolean-selector-parameter` rule. Typed: the
 * original returns no visitors without a program, so without tsrs (or when
 * tsrs cannot hold the file) this port reports nothing. The walk finds the
 * directly tested parameters of single-statement selectors (all syntax);
 * `Program:exit` runs the original's type and contract checks for each over
 * tsrs's checker, then reports.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { hasSideEffect } from "../utils/has-side-effect.js";
import { isGeneratedFile } from "../utils/paths.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";
import { isBooleanDataSelection, isEligibleBooleanSelector } from "./_no-boolean-selector-parameter-contract.js";
import { literalSelectorFix } from "./_literal-selector-fix.js";

const NAME = "no-boolean-selector-parameter";

type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;
type Identifier = Node & { readonly type: "Identifier"; readonly name: string };

// Preserve the existing block-only onX object-property blind spot. Names do not
// establish callback ownership; the unchanged typed contract helper does that.
function preservesBlockObjectCallback(owner: FunctionNode): boolean {
  const property = parentOf(owner);
  if (property?.type !== "Property" || property.computed) return false;
  const key = property.key;
  const name = key.type === "Identifier" ? key.name :
    key.type === "Literal" && typeof key.value === "string" ? key.value : undefined;
  return name !== undefined && /^on[A-Z]/u.test(name);
}

function testIdentifier(test: Node): Identifier | undefined {
  const value = test.type === "UnaryExpression" && test.operator === "!" ? test.argument : test;
  return value.type === "Identifier" ? value : undefined;
}

/** The parameter test and the IfStatement or ConditionalExpression it decides, when the test is direct. */
function directTest(identifier: Identifier): { readonly test: Node; readonly selection: Node } | undefined {
  const parent = parentOf(identifier);
  const test = parent?.type === "UnaryExpression" && parent.operator === "!" ? parent : identifier;
  const selection = parentOf(test);
  return (selection?.type === "IfStatement" || selection?.type === "ConditionalExpression") && selection.test === test
    ? { test, selection } : undefined;
}

/** The if statement or conditional expression a single-statement body selects with. */
function singleStatementSelection(statement: Node | undefined): ESTree.IfStatement | ESTree.ConditionalExpression | null {
  if (statement?.type === "IfStatement") return statement;
  const selected = statement?.type === "ReturnStatement" ? statement.argument :
    statement?.type === "ExpressionStatement" ? statement.expression : null;
  return selected?.type === "ConditionalExpression" ? selected : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Prefer intention-revealing operations over a boolean parameter selecting between actions.",
      url: docsUrl(NAME),
    },
    schema: [],
    fixable: "code",
    messages: {
      booleanSelector:
        'Consider separate intention-revealing operations instead of using "{{parameterName}}" to select an action. Preserve required contracts and boolean data.',
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    // Each tested identifier once, in walk order, as the original's `reported` set keeps it.
    let candidates = new Set<Identifier>();

    /** Collect the tested parameter when either branch of the selection has a side effect. */
    function collectEffectfulSelection(test: Node, consequent: Node, alternate: Node): void {
      if (!hasSideEffect(consequent, context.sourceCode) && !hasSideEffect(alternate, context.sourceCode)) return;
      const identifier = testIdentifier(test);
      if (identifier !== undefined && directTest(identifier) !== undefined) candidates.add(identifier);
    }

    function inspectSingleStatementBody(owner: FunctionNode): void {
      if (owner.body?.type !== "BlockStatement" || owner.body.body.length !== 1 || preservesBlockObjectCallback(owner)) return;
      const selection = singleStatementSelection(owner.body.body[0]);
      if (selection !== null && selection.alternate !== null) collectEffectfulSelection(selection.test, selection.consequent, selection.alternate);
    }

    /** The original's `report` checks, which need types. */
    function selects(identifier: Identifier, native: NativeTypes): boolean {
      const sourceCode = context.sourceCode;
      if (!isEligibleBooleanSelector(identifier, sourceCode, native)) return false;
      const selection = directTest(identifier)!.selection;
      return !(selection.type === "ConditionalExpression" &&
        isBooleanDataSelection(selection.consequent, selection.alternate, sourceCode, native));
    }

    return {
      before() {
        tsrs = null;
        candidates = new Set();
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      FunctionDeclaration: inspectSingleStatementBody,
      FunctionExpression: inspectSingleStatementBody,
      ArrowFunctionExpression: inspectSingleStatementBody,
      ConditionalExpression(node) {
        const callable = parentOf(node);
        if (callable?.type !== "ArrowFunctionExpression" || callable.body !== node) return;
        const owner = parentOf(callable);
        if ((owner?.type === "CallExpression" && owner.arguments.includes(callable)) || owner?.type === "JSXExpressionContainer") return;
        collectEffectfulSelection(node.test, node.consequent, node.alternate);
      },
      "Program:exit"() {
        if (candidates.size === 0 || tsrs === null) return;
        const tested = [...candidates];
        const found = tsrs.run((file) => {
          const native = nativeTypes(file);
          return tested.map((identifier) => selects(identifier, native));
        });
        if (found === null) return;
        tested.forEach((identifier, i) => {
          if (found[i] !== true) return;
          const fix = literalSelectorFix(context.sourceCode, identifier);
          context.report({
            node: identifier,
            messageId: "booleanSelector",
            data: { parameterName: identifier.name },
            ...(fix !== null && { fix }),
          });
        });
      },
    };
  },
});

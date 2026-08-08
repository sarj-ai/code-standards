/**
 * @fileoverview require-assert-never — a switch over a union whose `default` does no runtime work stops being exhaustive the day the union grows.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/require-assert-never.test.ts
 */

import {
  ESLintUtils,
  type ParserServicesWithTypeInformation,
  type TSESLint,
  type TSESTree,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";
import ts from "typescript";

import { createRule } from "./_docs.js";

type MessageIds = "missingAssertNever";
type Options = readonly [];

/** Empty statements and empty blocks are not runtime handling. */
const isRuntimeHandlingStatement = (statement: TSESTree.Statement): boolean => {
  if (statement.type === AST_NODE_TYPES.EmptyStatement) return false;
  if (
    statement.type === AST_NODE_TYPES.TSTypeAliasDeclaration ||
    statement.type === AST_NODE_TYPES.TSInterfaceDeclaration
  ) {
    return false;
  }
  if (statement.type === AST_NODE_TYPES.BlockStatement) {
    return statement.body.some(isRuntimeHandlingStatement);
  }
  return true;
};

/** An empty non-final default falls through to a case that handles it. */
const isFallthroughDefault = (
  node: TSESTree.SwitchStatement,
  defaultIndex: number,
): boolean => {
  const defaultCase = node.cases[defaultIndex];
  return (
    defaultCase !== undefined &&
    defaultCase.consequent.length === 0 &&
    defaultIndex < node.cases.length - 1
  );
};

/** Honor a comment that makes an empty default an intentional no-op. */
const isCommentOnlyNoopDefault = (
  defaultCase: TSESTree.SwitchCase,
  sourceCode: Readonly<TSESLint.SourceCode>,
): boolean => {
  if (defaultCase.consequent.length === 0) {
    const defaultToken = sourceCode.getFirstToken(defaultCase);
    const colonToken = defaultToken
      ? sourceCode.getTokenAfter(defaultToken)
      : null;
    return (
      colonToken !== null && sourceCode.getCommentsAfter(colonToken).length > 0
    );
  }
  const only = defaultCase.consequent[0];
  if (
    only !== undefined &&
    defaultCase.consequent.length === 1 &&
    only.type === AST_NODE_TYPES.BlockStatement &&
    !only.body.some(isRuntimeHandlingStatement)
  ) {
    return sourceCode.getCommentsInside(only).length > 0;
  }
  return false;
};

/** Prove that explicit cases cover every finite constituent of the discriminant. */
function isExhaustiveFiniteSwitch(
  node: TSESTree.SwitchStatement,
  services: ParserServicesWithTypeInformation,
): boolean {
  const checker = services.program.getTypeChecker();
  const discriminant = services.esTreeNodeToTSNodeMap.get(node.discriminant);
  const discriminantType = checker.getTypeAtLocation(discriminant);
  const constituents = discriminantType.isUnion()
    ? discriminantType.types
    : [discriminantType];
  if (constituents.length === 0) return false;

  const expected = new Set<string>();
  for (const constituent of constituents) {
    const key = finiteTypeKey(constituent, checker);
    if (key === null) return false;
    expected.add(key);
  }

  const handled = new Set<string>();
  for (const caseNode of node.cases) {
    if (caseNode.test === null) continue;
    const test = services.esTreeNodeToTSNodeMap.get(caseNode.test);
    const testType = checker.getTypeAtLocation(test);
    const alternatives = testType.isUnion() ? testType.types : [testType];
    for (const alternative of alternatives) {
      const key = finiteTypeKey(alternative, checker);
      if (key !== null) handled.add(key);
    }
  }
  return [...expected].every((key) => handled.has(key));
}

/** A stable key for a finite switch constituent; open primitive types return null. */
function finiteTypeKey(
  type: ts.Type,
  checker: ts.TypeChecker,
): string | null {
  const finiteFlags =
    ts.TypeFlags.StringLiteral |
    ts.TypeFlags.NumberLiteral |
    ts.TypeFlags.BooleanLiteral |
    ts.TypeFlags.EnumLiteral |
    ts.TypeFlags.UniqueESSymbol |
    ts.TypeFlags.Null |
    ts.TypeFlags.Undefined;
  return (type.flags & finiteFlags) !== 0 ? checker.typeToString(type) : null;
}

export default createRule<Options, MessageIds>({
  name: "require-assert-never",
  meta: {
    type: "problem",
    docs: {
      description:
        "Require an exhaustive-style switch whose `default` case does no runtime work to call `assertNever(_)` so that discriminated unions are exhaustively checked at compile time. Switches with a legitimate runtime default (a reducer's `return state`, an HTTP-status `return fallback()`, a `break`, a `throw`, etc.) are left alone.",
    },
    schema: [],
    messages: {
      missingAssertNever:
        "Empty switch `default` case — add runtime handling or call `assertNever()` so the discriminated union is exhaustively checked at compile time.",
    },
  },
  defaultOptions: [],
  create(context) {
    let services: ParserServicesWithTypeInformation;
    try {
      services = ESLintUtils.getParserServices(context);
    } catch {
      // Exhaustiveness cannot be proven from syntax alone. The typed strict
      // preset supplies services; standalone syntax-only use stays silent.
      return {};
    }

    return {
      SwitchStatement(node: TSESTree.SwitchStatement): void {
        const defaultIndex = node.cases.findIndex(
          (caseNode) => caseNode.test === null,
        );
        // Only present no-op defaults opt into this syntactic check.
        if (defaultIndex === -1) return;
        const defaultCase = node.cases[defaultIndex];
        if (defaultCase === undefined) return;

        // Any runtime work, including assertNever(), handles the default.
        if (defaultCase.consequent.some(isRuntimeHandlingStatement)) return;

        // A non-final empty default is handled by its following case.
        if (isFallthroughDefault(node, defaultIndex)) return;

        // Comments distinguish deliberate no-ops without requiring type info.
        if (isCommentOnlyNoopDefault(defaultCase, context.sourceCode)) return;
        if (!isExhaustiveFiniteSwitch(node, services)) return;

        context.report({
          node: defaultCase,
          messageId: "missingAssertNever",
        });
      },
    };
  },
});

/**
 * @fileoverview no-growing-array-spread-in-loop — review repeated copies of a growing local array in loops.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-growing-array-spread-in-loop.test.ts
 */
import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESTree,
} from "@typescript-eslint/utils";

import { getTypeServices } from "./_eslint-rule.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import {
  enclosingFunction,
  stableConstInitializer,
  typeOnlyReference,
} from "./_stable-value-binding.js";
import { hasIdentifierNamed } from "./_unused-private-binding.js";
import { unwrapExpression } from "./_unwrap-expression.js";

export const NO_GROWING_ARRAY_SPREAD_IN_LOOP_DOCUMENTATION = {
  summary:
    "Review repeated prefix copies of a growing fresh local array inside a loop.",
  rationale:
    "Repeatedly copying all accumulated elements can make append collection quadratic in the output size.",
  remediation:
    "Append into a fresh locally owned output when snapshot and observation semantics permit it.",
  category: "performance",
  defaultLevel: "warning",
  requiresTypeInformation: true,
  references: [
    "https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-reduce-accumulator-copy.ts",
  ],
  limitations: [
    "Initially checks a native-array for-of loop with a straight-line append-only body, a fresh local empty array outside that loop, a prefix spread followed by a definite element, and no other writes or observations across the loop.",
    "Inputs initially come from parameters, imports or declarations, optionally through plain const aliases. Locally literal-, property- and call-produced inputs are excluded while their bounds remain unproved. Retained snapshots, escaping arrays, resets, nested function references and object spreads remain outside this rule. Existing Unicorn concat-loop coverage and reducer copy analysis keep their own owners.",
    "A finding requests performance review; it is not a measured speedup claim. Corrections remain manual.",
  ],
  examples: [
    {
      id: "copy-prefix",
      title: "Repeated spread copies the accumulated rows",
      outcome: "match",
      files: [
        {
          path: "src/rows.ts",
          source:
            "export function collect(input: string[]) { let rows: string[] = []; for (const row of input) { rows = [...rows, row]; } return rows; }",
        },
      ],
      focusPath: "src/rows.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "append-rows",
      title: "Append into a fresh unobserved output",
      outcome: "no-match",
      files: [
        {
          path: "src/rows.ts",
          source:
            "export function collect(input: string[]) { const rows: string[] = []; for (const row of input) { rows.push(row); } return rows; }",
        },
      ],
      focusPath: "src/rows.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function nearestLoop(node: TSESTree.Node): TSESTree.Node | null {
  const owner = enclosingFunction(node);
  for (
    let current = node.parent;
    current !== undefined && current !== owner;
    current = current.parent
  ) {
    if (
      current.type === AST_NODE_TYPES.ForOfStatement ||
      current.type === AST_NODE_TYPES.ForInStatement ||
      current.type === AST_NODE_TYPES.ForStatement ||
      current.type === AST_NODE_TYPES.WhileStatement ||
      current.type === AST_NODE_TYPES.DoWhileStatement
    )
      return current;
  }
  return null;
}

export default createRule<[], "copy">({
  name: "no-growing-array-spread-in-loop",
  documentation: NO_GROWING_ARRAY_SPREAD_IN_LOOP_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description: NO_GROWING_ARRAY_SPREAD_IN_LOOP_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      copy: "This loop copies the growing array prefix. Consider appending into its fresh local output; preserve retained snapshots and observations.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isGeneratedFile(context, context.sourceCode.text) ||
      hasIdentifierNamed(context.sourceCode.ast, "eval") ||
      !context.sourceCode.parserServices?.program ||
      !context.sourceCode.parserServices.esTreeNodeToTSNodeMap
    )
      return {};
    const services = getTypeServices(context);
    if (services.program === null) return {};
    const checker = services.program.getTypeChecker();
    function inputHasUnknownExtent(
      node: TSESTree.Node,
      seen = new Set<TSESTree.Node>(),
    ): boolean {
      if (node.type !== AST_NODE_TYPES.Identifier || seen.has(node))
        return false;
      seen.add(node);
      const variable = ASTUtils.findVariable(
        context.sourceCode.getScope(node),
        node.name,
      );
      if (variable === null || variable.defs.length !== 1) return false;
      const definition = variable.defs[0];
      if (
        definition?.type === "Parameter" ||
        definition?.type === "ImportBinding"
      )
        return true;
      const local = stableConstInitializer(context.sourceCode, node);
      if (local !== null) return inputHasUnknownExtent(local.value, seen);
      return (
        definition?.node.type === AST_NODE_TYPES.VariableDeclarator &&
        definition.node.init === null
      );
    }
    return {
      AssignmentExpression(node: TSESTree.AssignmentExpression): void {
        if (
          node.operator !== "=" ||
          node.left.type !== AST_NODE_TYPES.Identifier
        )
          return;
        const value = unwrapExpression(node.right);
        if (
          value.type !== AST_NODE_TYPES.ArrayExpression ||
          value.elements.length < 2
        )
          return;
        const prefix = value.elements[0];
        if (
          prefix?.type !== AST_NODE_TYPES.SpreadElement ||
          value.elements
            .slice(1)
            .some(
              (element) =>
                element === null ||
                element.type === AST_NODE_TYPES.SpreadElement,
            )
        )
          return;
        const copied = unwrapExpression(prefix.argument);
        if (copied.type !== AST_NODE_TYPES.Identifier) return;
        const variable = ASTUtils.findVariable(
          context.sourceCode.getScope(node.left),
          node.left.name,
        );
        if (
          variable === null ||
          variable.defs.length !== 1 ||
          variable.scope.type === "global" ||
          ASTUtils.findVariable(
            context.sourceCode.getScope(copied),
            copied.name,
          ) !== variable
        )
          return;
        const definition = variable.defs[0]?.node;
        const loop = nearestLoop(node);
        if (
          definition?.type !== AST_NODE_TYPES.VariableDeclarator ||
          definition.id.type !== AST_NODE_TYPES.Identifier ||
          definition.parent.kind !== "let" ||
          definition.parent.parent.type ===
            AST_NODE_TYPES.ExportNamedDeclaration ||
          definition.init?.type !== AST_NODE_TYPES.ArrayExpression ||
          definition.init.elements.length !== 0 ||
          loop?.type !== AST_NODE_TYPES.ForOfStatement ||
          definition.range[1] >= loop.range[0] ||
          !checker.isArrayType(
            checker.getTypeAtLocation(
              services.esTreeNodeToTSNodeMap.get(node.left),
            ),
          )
        )
          return;
        const body =
          loop.body.type === AST_NODE_TYPES.BlockStatement
            ? loop.body.body.length === 1
              ? loop.body.body[0]
              : undefined
            : loop.body;
        if (
          body?.type !== AST_NODE_TYPES.ExpressionStatement ||
          body.expression !== node ||
          !inputHasUnknownExtent(loop.right) ||
          !checker.isArrayType(
            checker.getTypeAtLocation(
              services.esTreeNodeToTSNodeMap.get(loop.right),
            ),
          ) ||
          loop.right.type === AST_NODE_TYPES.ArrayExpression
        )
          return;
        const owner = enclosingFunction(definition);
        const owned = variable.references.every((reference) => {
          if (reference.init === true || typeOnlyReference(reference))
            return true;
          if (reference.isWrite()) return reference.identifier === node.left;
          if (reference.identifier === copied) return true;
          return (
            reference.identifier.parent.type !==
              AST_NODE_TYPES.ExportSpecifier &&
            reference.identifier.parent.type !==
              AST_NODE_TYPES.ExportDefaultDeclaration &&
            reference.identifier.range[0] >= loop.range[1] &&
            enclosingFunction(reference.identifier) === owner
          );
        });
        if (owned) context.report({ node: prefix, messageId: "copy" });
      },
    };
  },
});

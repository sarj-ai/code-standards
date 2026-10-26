/**
 * @fileoverview _empty-assertion-fix — reuse an authored no-op never guard.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

type OrdinaryFunction = TSESTree.FunctionDeclaration;

/** Reuse an authored no-op never guard without changing unexpected-value behavior. */
export function emptyAssertionFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.SwitchStatement,
  defaultCase: TSESTree.SwitchCase,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length > 0
  )
    return null;
  const [helper, statement] = sourceCode.ast.body;
  if (
    helper?.type !== AST_NODE_TYPES.FunctionDeclaration ||
    !isEmptyAssertion(helper) ||
    statement?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    statement.declaration?.type !== AST_NODE_TYPES.FunctionDeclaration
  )
    return null;
  const owner = statement.declaration;
  if (!isLiteralDispatch(owner, node, defaultCase)) return null;
  const parameter = owner.params[0];
  if (parameter?.type !== AST_NODE_TYPES.Identifier || helper.id === null)
    return null;
  const helperName = helper.id.name;
  const binding = ASTUtils.findVariable(
    sourceCode.getScope(defaultCase),
    helperName,
  );
  if (binding?.defs.length !== 1 || binding.defs[0]?.node !== helper)
    return null;
  const first = sourceCode.getFirstToken(defaultCase);
  const colon = first === null ? null : sourceCode.getTokenAfter(first);
  if (colon?.value !== ":") return null;
  return (fixer) =>
    fixer.insertTextAfter(colon, ` ${helperName}(${parameter.name});`);
}

function isOrdinary(node: OrdinaryFunction): boolean {
  return (
    !node.declare &&
    !node.async &&
    !node.generator &&
    node.typeParameters === undefined
  );
}

function isEmptyAssertion(node: OrdinaryFunction): boolean {
  const parameter = node.params[0];
  return (
    isOrdinary(node) &&
    node.id?.name === "assertNever" &&
    node.params.length === 1 &&
    parameter?.type === AST_NODE_TYPES.Identifier &&
    !parameter.optional &&
    parameter.typeAnnotation?.typeAnnotation.type ===
      AST_NODE_TYPES.TSNeverKeyword &&
    node.returnType?.typeAnnotation.type === AST_NODE_TYPES.TSVoidKeyword &&
    node.body.body.length === 0
  );
}

function isLiteralDispatch(
  owner: OrdinaryFunction,
  node: TSESTree.SwitchStatement,
  defaultCase: TSESTree.SwitchCase,
): boolean {
  const parameter = owner.params[0];
  const domain = literalDomain(parameter);
  if (
    !isOrdinary(owner) ||
    owner.params.length !== 1 ||
    parameter?.type !== AST_NODE_TYPES.Identifier ||
    parameter.optional ||
    domain === null ||
    owner.body.body.length !== 2 ||
    owner.body.body[0] !== node ||
    node.discriminant.type !== AST_NODE_TYPES.Identifier ||
    node.discriminant.name !== parameter.name ||
    node.cases.at(-1) !== defaultCase ||
    !isEmptyDefault(defaultCase)
  )
    return false;
  if (!isPrimitiveReturn(owner.body.body[1], owner.returnType)) return false;
  const handled = new Set<string>();
  for (const branch of node.cases.slice(0, -1)) {
    if (
      branch.test?.type !== AST_NODE_TYPES.Literal ||
      typeof branch.test.value !== "string" ||
      handled.has(branch.test.value) ||
      !domain.has(branch.test.value) ||
      branch.consequent.length !== 1 ||
      !isPrimitiveReturn(branch.consequent[0], owner.returnType)
    )
      return false;
    handled.add(branch.test.value);
  }
  return handled.size === domain.size;
}

function literalDomain(
  node: TSESTree.Parameter | undefined,
): Set<string> | null {
  if (node?.type !== AST_NODE_TYPES.Identifier) return null;
  const annotation = node.typeAnnotation?.typeAnnotation;
  if (annotation?.type !== AST_NODE_TYPES.TSUnionType) return null;
  const values = new Set<string>();
  for (const type of annotation.types) {
    if (
      type.type !== AST_NODE_TYPES.TSLiteralType ||
      type.literal.type !== AST_NODE_TYPES.Literal ||
      typeof type.literal.value !== "string" ||
      values.has(type.literal.value)
    )
      return null;
    values.add(type.literal.value);
  }
  return values.size >= 2 ? values : null;
}

function isEmptyDefault(node: TSESTree.SwitchCase): boolean {
  const only = node.consequent[0];
  return (
    node.test === null &&
    (node.consequent.length === 0 ||
      (node.consequent.length === 1 &&
        only?.type === AST_NODE_TYPES.BreakStatement &&
        only.label === null))
  );
}

function isPrimitiveReturn(
  node: TSESTree.Statement | undefined,
  annotation: TSESTree.TSTypeAnnotation | undefined,
): boolean {
  if (
    node?.type !== AST_NODE_TYPES.ReturnStatement ||
    node.argument?.type !== AST_NODE_TYPES.Literal
  )
    return false;
  const value = node.argument.value;
  switch (annotation?.typeAnnotation.type) {
    case AST_NODE_TYPES.TSNumberKeyword:
      return typeof value === "number" && Number.isFinite(value);
    case AST_NODE_TYPES.TSStringKeyword:
      return typeof value === "string";
    case AST_NODE_TYPES.TSBooleanKeyword:
      return typeof value === "boolean";
    default:
      return false;
  }
}

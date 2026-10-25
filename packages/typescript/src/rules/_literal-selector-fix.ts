/**
 * @fileoverview _literal-selector-fix — reuse authored operations for literal calls.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

/** Reuse already authored operations instead of an exclusively literal-called adapter. */
export function literalSelectorFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  parameter: TSESTree.Identifier,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== 4 ||
    sourceCode.getAllComments().length > 0
  )
    return null;
  const [first, second, declaration, statement] = sourceCode.ast.body;
  if (
    !isLiteralOperation(first) ||
    !isLiteralOperation(second) ||
    declaration?.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.declare ||
    declaration.kind !== "const" ||
    declaration.declarations.length !== 1 ||
    statement?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    statement.declaration?.type !== AST_NODE_TYPES.FunctionDeclaration
  )
    return null;
  const binding = declaration.declarations[0];
  if (
    binding?.id.type !== AST_NODE_TYPES.Identifier ||
    binding.id.typeAnnotation !== undefined ||
    !isSelector(binding.init, parameter)
  )
    return null;
  const branch = binding.init.body;
  const whenTrue = operation(sourceCode, branch.consequent, first, second);
  const whenFalse = operation(sourceCode, branch.alternate, first, second);
  if (whenTrue === null || whenFalse === null || whenTrue === whenFalse)
    return null;
  const calls = literalCallers(sourceCode, statement.declaration, binding);
  if (calls === null) return null;
  const gap = sourceCode.text.slice(declaration.range[1], statement.range[0]);
  if (!/^\s*$/u.test(gap)) return null;
  return (fixer) => [
    fixer.removeRange([declaration.range[0], statement.range[0]]),
    ...calls.map((call) =>
      fixer.replaceText(
        call,
        `${call.arguments[0]?.type === AST_NODE_TYPES.Literal && call.arguments[0].value === true ? whenTrue : whenFalse}()`,
      ),
    ),
  ];
}

function isLiteralOperation(
  node: TSESTree.Node | undefined,
): node is TSESTree.FunctionDeclaration {
  if (
    node?.type !== AST_NODE_TYPES.FunctionDeclaration ||
    node.id === null ||
    node.declare ||
    node.async ||
    node.generator ||
    node.params.length !== 0 ||
    node.typeParameters !== undefined ||
    node.returnType !== undefined ||
    node.body.body.length !== 1
  )
    return false;
  const returned = node.body.body[0];
  return (
    returned?.type === AST_NODE_TYPES.ReturnStatement &&
    returned.argument?.type === AST_NODE_TYPES.Literal &&
    typeof returned.argument.value === "string"
  );
}

function isSelector(
  node: TSESTree.Expression | null,
  parameter: TSESTree.Identifier,
): node is TSESTree.ArrowFunctionExpression & {
  body: TSESTree.ConditionalExpression;
} {
  if (node?.type !== AST_NODE_TYPES.ArrowFunctionExpression) return false;
  const actual = node.params[0];
  return (
    actual?.type === AST_NODE_TYPES.Identifier &&
    actual.name === parameter.name &&
    !node.async &&
    node.typeParameters === undefined &&
    node.returnType === undefined &&
    node.params.length === 1 &&
    !actual.optional &&
    actual.typeAnnotation?.typeAnnotation.type ===
      AST_NODE_TYPES.TSBooleanKeyword &&
    node.body.type === AST_NODE_TYPES.ConditionalExpression &&
    node.body.test === parameter
  );
}

function operation(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Expression,
  first: TSESTree.FunctionDeclaration,
  second: TSESTree.FunctionDeclaration,
): string | null {
  if (
    node.type !== AST_NODE_TYPES.CallExpression ||
    node.optional ||
    node.callee.type !== AST_NODE_TYPES.Identifier ||
    node.arguments.length !== 0 ||
    node.typeArguments !== undefined
  )
    return null;
  const variable = ASTUtils.findVariable(
    sourceCode.getScope(node),
    node.callee.name,
  );
  const target = variable?.defs[0]?.node;
  return variable?.defs.length === 1 && (target === first || target === second)
    ? sourceCode.getText(node.callee)
    : null;
}

function literalCallers(
  sourceCode: Readonly<TSESLint.SourceCode>,
  owner: TSESTree.FunctionDeclaration,
  binding: TSESTree.VariableDeclarator,
): TSESTree.CallExpression[] | null {
  if (
    owner.declare ||
    owner.async ||
    owner.generator ||
    owner.params.length !== 0 ||
    owner.typeParameters !== undefined ||
    owner.body.body.length !== 1 ||
    owner.returnType?.typeAnnotation.type !== AST_NODE_TYPES.TSArrayType ||
    owner.returnType.typeAnnotation.elementType.type !==
      AST_NODE_TYPES.TSStringKeyword
  )
    return null;
  const returned = owner.body.body[0];
  if (
    returned?.type !== AST_NODE_TYPES.ReturnStatement ||
    returned.argument?.type !== AST_NODE_TYPES.ArrayExpression
  )
    return null;
  const calls: TSESTree.CallExpression[] = [];
  const choices = new Set<boolean>();
  for (const item of returned.argument.elements) {
    if (
      item?.type !== AST_NODE_TYPES.CallExpression ||
      item.optional ||
      item.callee.type !== AST_NODE_TYPES.Identifier ||
      item.typeArguments !== undefined ||
      item.arguments.length !== 1 ||
      item.arguments[0]?.type !== AST_NODE_TYPES.Literal ||
      typeof item.arguments[0].value !== "boolean"
    )
      return null;
    const variable = ASTUtils.findVariable(
      sourceCode.getScope(item),
      item.callee.name,
    );
    if (variable?.defs.length !== 1 || variable.defs[0]?.node !== binding)
      return null;
    calls.push(item);
    choices.add(item.arguments[0].value);
  }
  return choices.size === 2 ? calls : null;
}

/**
 * @fileoverview _owned-fetch-fix — repair the receiver of one owned literal request.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

/** Repair a receiver only when the private stored callable is used by one literal request. */
export function ownedFetchFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Expression,
): TSESLint.ReportFixFunction | null {
  if (
    node.type !== AST_NODE_TYPES.Identifier ||
    node.name !== "fetch" ||
    sourceCode.ast.body.length !== 1 ||
    sourceCode.getAllComments().length > 0 ||
    (ASTUtils.findVariable(sourceCode.getScope(node), "fetch")?.defs.length ??
      0) !== 0 ||
    (ASTUtils.findVariable(sourceCode.getScope(node), "undefined")?.defs
      .length ?? 0) !== 0
  )
    return null;
  const statement = sourceCode.ast.body[0];
  if (
    statement?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    statement.declaration?.type !== AST_NODE_TYPES.FunctionDeclaration
  )
    return null;
  const owner = statement.declaration;
  if (
    owner.async ||
    owner.declare ||
    owner.generator ||
    owner.typeParameters !== undefined ||
    owner.params.length !== 0 ||
    owner.returnType !== undefined ||
    owner.body.body.length !== 2
  )
    return null;
  const [declaration, returned] = owner.body.body;
  if (
    declaration?.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.kind !== "const" ||
    declaration.declare ||
    declaration.declarations.length !== 1 ||
    returned?.type !== AST_NODE_TYPES.ReturnStatement
  )
    return null;
  const object = declaration.declarations[0];
  if (
    object?.id.type !== AST_NODE_TYPES.Identifier ||
    object.id.typeAnnotation !== undefined ||
    object.init?.type !== AST_NODE_TYPES.ObjectExpression ||
    object.init.properties.length !== 1
  )
    return null;
  const property = object.init.properties[0];
  if (
    property?.type !== AST_NODE_TYPES.Property ||
    property.computed ||
    property.kind !== "init" ||
    property.method ||
    property.value !== node
  )
    return null;
  const key = ASTUtils.getPropertyName(property);
  if (
    key === null ||
    key === "__proto__" ||
    !soleLiteralRequest(sourceCode, returned.argument, declaration, object, key)
  )
    return null;
  const replacement = property.shorthand
    ? `${sourceCode.getText(property.key)}: fetch.bind(undefined)`
    : "fetch.bind(undefined)";
  return (fixer) =>
    fixer.replaceText(property.shorthand ? property : node, replacement);
}

function soleLiteralRequest(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Expression | null,
  declaration: TSESTree.VariableDeclaration,
  object: TSESTree.VariableDeclarator,
  key: string,
): boolean {
  if (
    node?.type !== AST_NODE_TYPES.CallExpression ||
    node.optional ||
    node.typeArguments !== undefined ||
    node.arguments.length !== 1 ||
    node.callee.type !== AST_NODE_TYPES.MemberExpression ||
    node.callee.optional ||
    ASTUtils.getPropertyName(node.callee) !== key ||
    node.callee.object.type !== AST_NODE_TYPES.Identifier ||
    object.id.type !== AST_NODE_TYPES.Identifier ||
    node.callee.object.name !== object.id.name
  )
    return false;
  const input = node.arguments[0];
  if (
    input?.type !== AST_NODE_TYPES.Literal ||
    typeof input.value !== "string" ||
    !input.value.startsWith("data:")
  )
    return false;
  const identifier = object.id;
  const receiver = node.callee.object;
  const binding = sourceCode
    .getDeclaredVariables(declaration)
    .find((variable) => variable.name === identifier.name);
  return (
    binding !== undefined &&
    binding.defs.length === 1 &&
    binding.defs[0]?.node === object &&
    ASTUtils.findVariable(sourceCode.getScope(receiver), identifier.name) ===
      binding &&
    binding.references.every(
      (reference) =>
        reference.identifier === identifier ||
        reference.identifier === receiver,
    )
  );
}

/**
 * @fileoverview _static-matcher-fix — inline an authored primitive route.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

/** Inline an already authored primitive route in a complete, otherwise inert module. */
export function staticMatcherFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  property: TSESTree.Property,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length > 0 ||
    property.computed ||
    property.kind !== "init" ||
    property.method ||
    property.value.type !== AST_NODE_TYPES.Identifier
  )
    return null;
  const [statement, exported] = sourceCode.ast.body;
  if (
    statement?.type !== AST_NODE_TYPES.VariableDeclaration ||
    statement.kind !== "const" ||
    statement.declare ||
    statement.declarations.length !== 1 ||
    exported?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    exported.declaration?.type !== AST_NODE_TYPES.VariableDeclaration
  )
    return null;
  const route = statement.declarations[0];
  const config = exported.declaration;
  if (
    route?.id.type !== AST_NODE_TYPES.Identifier ||
    route.id.typeAnnotation !== undefined ||
    route.init?.type !== AST_NODE_TYPES.Literal ||
    typeof route.init.value !== "string" ||
    route.id.name !== property.value.name ||
    config.kind !== "const" ||
    config.declare ||
    config.declarations.length !== 1
  )
    return null;
  const declaration = config.declarations[0];
  if (
    declaration?.id.type !== AST_NODE_TYPES.Identifier ||
    declaration.id.name !== "config" ||
    declaration.id.typeAnnotation !== undefined ||
    declaration.init?.type !== AST_NODE_TYPES.ObjectExpression ||
    declaration.init.properties.length !== 1 ||
    declaration.init.properties[0] !== property
  )
    return null;
  const identifier = route.id;
  const binding = sourceCode
    .getDeclaredVariables(statement)
    .find((variable) => variable.name === identifier.name);
  if (
    binding === undefined ||
    binding.defs.length !== 1 ||
    binding.defs[0]?.node !== route ||
    ASTUtils.findVariable(
      sourceCode.getScope(property.value),
      property.value.name,
    ) !== binding ||
    binding.references.some(
      (reference) =>
        reference.identifier !== route.id &&
        reference.identifier !== property.value,
    )
  )
    return null;
  const value = sourceCode.getText(route.init);
  const replacement = property.shorthand
    ? `${sourceCode.getText(property.key)}: ${value}`
    : value;
  return (fixer) => [
    fixer.removeRange([statement.range[0], exported.range[0]]),
    fixer.replaceText(
      property.shorthand ? property : property.value,
      replacement,
    ),
  ];
}

/**
 * @fileoverview _existing-overload-brand-fix — reuse existing nominal overload types.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

const DECLARATION_COUNT = 4;
const PARAMETER_COUNT = 2;

/** Reuse an existing public overload's two nominal types without changing its API. */
export function existingOverloadBrandFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Node,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== DECLARATION_COUNT ||
    sourceCode.getAllComments().length > 0
  )
    return null;
  const declarations = sourceCode.ast.body.map((statement) =>
    statement.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? statement.declaration
      : null,
  );
  const [first, second, overload, implementation] = declarations;
  if (
    first?.type !== AST_NODE_TYPES.TSTypeAliasDeclaration ||
    second?.type !== AST_NODE_TYPES.TSTypeAliasDeclaration ||
    overload?.type !== AST_NODE_TYPES.TSDeclareFunction ||
    implementation?.type !== AST_NODE_TYPES.FunctionDeclaration ||
    implementation !== node ||
    !isEmptyImplementation(implementation) ||
    !isSingleOverload(overload, implementation) ||
    !isStringBrand(first) ||
    !isStringBrand(second) ||
    first.id.name === second.id.name
  )
    return null;
  const aliases = [first, second];
  const replacements: { node: TSESTree.TypeNode; text: string }[] = [];
  const used = new Set<string>();
  for (const [index, parameter] of implementation.params.entries()) {
    const promised = overload.params[index];
    if (
      parameter.type !== AST_NODE_TYPES.Identifier ||
      parameter.optional ||
      parameter.typeAnnotation?.typeAnnotation.type !==
        AST_NODE_TYPES.TSStringKeyword ||
      promised?.type !== AST_NODE_TYPES.Identifier ||
      promised.optional ||
      parameter.name !== promised.name ||
      promised.typeAnnotation?.typeAnnotation.type !==
        AST_NODE_TYPES.TSTypeReference
    )
      return null;
    const annotation = promised.typeAnnotation.typeAnnotation;
    const alias = aliases.find(
      (candidate) =>
        annotation.typeName.type === AST_NODE_TYPES.Identifier &&
        candidate.id.name === annotation.typeName.name,
    );
    if (
      alias === undefined ||
      annotation.typeArguments !== undefined ||
      used.has(alias.id.name) ||
      !sameTypeBinding(sourceCode, alias, annotation, parameter)
    )
      return null;
    used.add(alias.id.name);
    replacements.push({
      node: parameter.typeAnnotation.typeAnnotation,
      text: sourceCode.getText(annotation),
    });
  }
  return (fixer) =>
    replacements.map((replacement) =>
      fixer.replaceText(replacement.node, replacement.text),
    );
}

function isEmptyImplementation(node: TSESTree.FunctionDeclaration): boolean {
  return (
    !node.declare &&
    !node.async &&
    !node.generator &&
    node.typeParameters === undefined &&
    node.params.length === PARAMETER_COUNT &&
    node.id !== null &&
    node.body.body.length === 0 &&
    node.returnType?.typeAnnotation.type === AST_NODE_TYPES.TSVoidKeyword
  );
}

function isSingleOverload(
  node: TSESTree.TSDeclareFunction,
  implementation: TSESTree.FunctionDeclaration,
): boolean {
  return (
    !node.declare &&
    !node.async &&
    node.typeParameters === undefined &&
    node.params.length === PARAMETER_COUNT &&
    node.id?.name === implementation.id?.name &&
    node.returnType?.typeAnnotation.type === AST_NODE_TYPES.TSVoidKeyword
  );
}

function isStringBrand(node: TSESTree.TSTypeAliasDeclaration): boolean {
  const annotation = node.typeAnnotation;
  if (
    node.declare ||
    node.typeParameters !== undefined ||
    annotation.type !== AST_NODE_TYPES.TSIntersectionType ||
    annotation.types.length !== PARAMETER_COUNT
  )
    return false;
  const [carrier, brand] = annotation.types;
  if (
    carrier?.type !== AST_NODE_TYPES.TSStringKeyword ||
    brand?.type !== AST_NODE_TYPES.TSTypeLiteral ||
    brand.members.length !== 1
  )
    return false;
  const property = brand.members[0];
  if (property?.type !== AST_NODE_TYPES.TSPropertySignature) return false;
  const value = property.typeAnnotation?.typeAnnotation;
  return (
    property.key.type === AST_NODE_TYPES.Identifier &&
    !property.computed &&
    !property.optional &&
    !property.static &&
    property.accessibility === undefined &&
    property.readonly &&
    value?.type === AST_NODE_TYPES.TSTypeOperator &&
    value.operator === "unique" &&
    value.typeAnnotation?.type === AST_NODE_TYPES.TSSymbolKeyword
  );
}

function sameTypeBinding(
  sourceCode: Readonly<TSESLint.SourceCode>,
  alias: TSESTree.TSTypeAliasDeclaration,
  annotation: TSESTree.TSTypeReference,
  parameter: TSESTree.Identifier,
): boolean {
  const binding = sourceCode
    .getDeclaredVariables(alias)
    .find((variable) => variable.name === alias.id.name);
  return (
    binding?.defs.length === 1 &&
    binding.defs[0]?.node === alias &&
    ASTUtils.findVariable(sourceCode.getScope(annotation), alias.id.name) ===
      binding &&
    ASTUtils.findVariable(sourceCode.getScope(parameter), alias.id.name) ===
      binding
  );
}

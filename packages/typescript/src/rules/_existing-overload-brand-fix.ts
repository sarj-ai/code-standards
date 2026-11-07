/** @fileoverview _existing-overload-brand-fix — reuse existing nominal overload types. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";
import { plainFunctionBody } from "./_closed-module.js";

const DECLARATION_COUNT = 4;
const PARAMETER_COUNT = 2;

interface Replacement {
  readonly node: Node;
  readonly text: string;
}

/** Reuse an existing public overload's two nominal types without changing its API. */
export function existingOverloadBrandFix(
  sourceCode: SourceCode,
  node: Node,
): FixFn | null {
  if (
    sourceCode.ast.body.length !== DECLARATION_COUNT ||
    sourceCode.getAllComments().length > 0
  )
    return null;
  const declarations = sourceCode.ast.body.map((statement) =>
    statement.type === "ExportNamedDeclaration"
      ? statement.declaration
      : null,
  );
  const [first, second, overload, implementation] = declarations;
  if (
    first?.type !== "TSTypeAliasDeclaration" ||
    second?.type !== "TSTypeAliasDeclaration" ||
    overload?.type !== "TSDeclareFunction" ||
    implementation?.type !== "FunctionDeclaration" ||
    implementation !== node ||
    !isEmptyImplementation(implementation) ||
    !isSingleOverload(overload, implementation) ||
    !isStringBrand(first) ||
    !isStringBrand(second) ||
    first.id.name === second.id.name
  )
    return null;
  const aliases = [first, second];
  const replacements: Replacement[] = [];
  const used = new Set<string>();
  for (const [index, parameter] of implementation.params.entries()) {
    const replacement = brandReplacement(sourceCode, parameter, overload.params[index], aliases, used);
    if (replacement === null) return null;
    replacements.push(replacement);
  }
  return (fixer) =>
    replacements.map((replacement) =>
      fixer.replaceText(replacement.node, replacement.text),
    );
}

/** Retype a `string` parameter with the not yet used brand its overload promises. */
function brandReplacement(
  sourceCode: SourceCode,
  parameter: ESTree.ParamPattern,
  promised: ESTree.ParamPattern | undefined,
  aliases: readonly ESTree.TSTypeAliasDeclaration[],
  used: Set<string>,
): Replacement | null {
  if (
    parameter.type !== "Identifier" ||
    parameter.optional ||
    parameter.typeAnnotation?.typeAnnotation.type !== "TSStringKeyword" ||
    promised?.type !== "Identifier" ||
    promised.optional ||
    parameter.name !== promised.name ||
    promised.typeAnnotation?.typeAnnotation.type !== "TSTypeReference"
  )
    return null;
  const annotation = promised.typeAnnotation.typeAnnotation;
  const alias = aliases.find(
    (candidate) =>
      annotation.typeName.type === "Identifier" &&
      candidate.id.name === annotation.typeName.name,
  );
  if (
    alias === undefined ||
    isPresent(annotation.typeArguments) ||
    used.has(alias.id.name) ||
    !sameTypeBinding(sourceCode, alias, annotation, parameter)
  )
    return null;
  used.add(alias.id.name);
  return { node: parameter.typeAnnotation.typeAnnotation, text: sourceCode.getText(annotation) };
}

function isEmptyImplementation(node: ESTree.Function): boolean {
  return (
    plainFunctionBody(node)?.length === 0 &&
    node.params.length === PARAMETER_COUNT &&
    node.id !== null &&
    node.returnType?.typeAnnotation.type === "TSVoidKeyword"
  );
}

function isSingleOverload(
  node: ESTree.Function,
  implementation: ESTree.Function,
): boolean {
  return (
    !node.declare &&
    !node.async &&
    !isPresent(node.typeParameters) &&
    node.params.length === PARAMETER_COUNT &&
    node.id?.name === implementation.id?.name &&
    node.returnType?.typeAnnotation.type === "TSVoidKeyword"
  );
}

function isStringBrand(node: ESTree.TSTypeAliasDeclaration): boolean {
  const annotation = node.typeAnnotation;
  if (
    node.declare ||
    isPresent(node.typeParameters) ||
    annotation.type !== "TSIntersectionType" ||
    annotation.types.length !== PARAMETER_COUNT
  )
    return false;
  const [carrier, brand] = annotation.types;
  if (
    carrier?.type !== "TSStringKeyword" ||
    brand?.type !== "TSTypeLiteral" ||
    brand.members.length !== 1
  )
    return false;
  const property = brand.members[0];
  if (property?.type !== "TSPropertySignature") return false;
  const value = property.typeAnnotation?.typeAnnotation;
  return (
    property.key.type === "Identifier" &&
    !property.computed &&
    !property.optional &&
    !property.static &&
    !isPresent(property.accessibility) &&
    property.readonly &&
    value?.type === "TSTypeOperator" &&
    value.operator === "unique" &&
    value.typeAnnotation?.type === "TSSymbolKeyword"
  );
}

function sameTypeBinding(
  sourceCode: SourceCode,
  alias: ESTree.TSTypeAliasDeclaration,
  annotation: ESTree.TSTypeReference,
  parameter: Node,
): boolean {
  const binding = sourceCode
    .getDeclaredVariables(alias)
    .find((variable) => variable.name === alias.id.name);
  return (
    binding?.defs.length === 1 &&
    binding.defs[0]?.node === alias &&
    findVariable(sourceCode.getScope(annotation), alias.id.name) === binding &&
    findVariable(sourceCode.getScope(parameter), alias.id.name) === binding
  );
}

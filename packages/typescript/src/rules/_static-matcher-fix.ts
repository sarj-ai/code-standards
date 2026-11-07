/** @fileoverview _static-matcher-fix — inline an authored primitive route. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";
import { soleConstDeclarator } from "./_closed-module.js";

/** Inline an already authored primitive route in a complete, otherwise inert module. */
export function staticMatcherFix(sourceCode: Readonly<SourceCode>, property: ESTree.ObjectProperty): FixFn | null {
  const propertyValue = property.value;
  if (
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length > 0 ||
    property.computed ||
    property.kind !== "init" ||
    property.method ||
    propertyValue.type !== "Identifier"
  )
    return null;
  const [statement, exported] = sourceCode.ast.body;
  if (statement?.type !== "VariableDeclaration" || exported?.type !== "ExportNamedDeclaration" ||
    exported.declaration?.type !== "VariableDeclaration") return null;
  const route = soleConstDeclarator(statement);
  const declaration = soleConstDeclarator(exported.declaration);
  if (
    route?.id.type !== "Identifier" ||
    isPresent(route.id.typeAnnotation) ||
    route.init?.type !== "Literal" ||
    typeof route.init.value !== "string" ||
    route.id.name !== propertyValue.name ||
    declaration?.id.type !== "Identifier" ||
    declaration.id.name !== "config" ||
    isPresent(declaration.id.typeAnnotation) ||
    declaration.init?.type !== "ObjectExpression" ||
    declaration.init.properties.length !== 1 ||
    declaration.init.properties[0] !== property
  )
    return null;
  const identifier = route.id;
  const routeInit = route.init;
  const binding = sourceCode.getDeclaredVariables(statement).find((variable) => variable.name === identifier.name);
  if (
    binding === undefined ||
    binding.defs.length !== 1 ||
    binding.defs[0]?.node !== route ||
    findVariable(sourceCode.getScope(propertyValue), propertyValue.name) !== binding ||
    binding.references.some(
      (reference) => reference.identifier !== route.id && reference.identifier !== propertyValue,
    )
  )
    return null;
  const value = sourceCode.getText(routeInit);
  const replacement = property.shorthand ? `${sourceCode.getText(property.key)}: ${value}` : value;
  return (fixer) => [
    fixer.removeRange([statement.range[0], exported.range[0]]),
    fixer.replaceText(property.shorthand ? property : propertyValue, replacement),
  ];
}

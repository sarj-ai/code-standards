/** @fileoverview _existing-domain-comparison-fix — reuse a closed-domain comparator. */

import type { Fixer } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";
import { plainFunctionBody } from "./_closed-module.js";

const UNSAFE_FIELDS: ReadonlySet<string> = new Set([
  "__proto__",
  "constructor",
  "prototype",
]);

type Expression = ESTree.Expression;

/** Reuse an already exercised comparator for a closed string-literal record domain. */
export function existingDomainComparisonFix(
  sourceCode: SourceCode,
  comparison: ESTree.BinaryExpression,
): ((fixer: Fixer) => ReturnType<Fixer["replaceText"]>) | null {
  if (
    comparison.operator !== "===" ||
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length !== 0
  )
    return null;
  const [comparator, exported] = sourceCode.ast.body;
  if (
    comparator?.type !== "FunctionDeclaration" || !isOrdinary(comparator) ||
    exported?.type !== "ExportNamedDeclaration" ||
    exported.exportKind !== "value" ||
    exported.declaration?.type !== "FunctionDeclaration" || !isOrdinary(exported.declaration)
  )
    return null;
  const fields = comparatorFields(comparator);
  const elements = callerElements(exported.declaration);
  if (fields === null || elements === null || elements[1] !== comparison)
    return null;
  const existing = elements[0];
  if (
    existing?.type !== "CallExpression" ||
    !isComparatorCall(sourceCode, existing, comparator, fields)
  )
    return null;
  const left = serializedLiteral(sourceCode, comparison.left, fields);
  const right = serializedLiteral(sourceCode, comparison.right, fields);
  if (left === null || right === null) return null;
  const name = sourceCode.getText(existing.callee);
  return (fixer) =>
    fixer.replaceText(
      comparison,
      `${name}(${sourceCode.getText(left)}, ${sourceCode.getText(right)})`,
    );
}

/** A named plain function with a one-statement body. */
function isOrdinary(node: ESTree.Function): boolean {
  return node.id !== null && plainFunctionBody(node)?.length === 1;
}

function comparatorFields(node: ESTree.Function): readonly string[] | null {
  const [left, right] = node.params;
  if (
    node.params.length !== 2 ||
    left?.type !== "Identifier" ||
    right?.type !== "Identifier" ||
    left.name === right.name ||
    node.returnType?.typeAnnotation.type !== "TSBooleanKeyword"
  )
    return null;
  const fields = parameterFields(left);
  const otherFields = parameterFields(right);
  if (
    fields === null ||
    otherFields === null ||
    fields.length !== otherFields.length ||
    fields.some((field, index) => otherFields[index] !== field)
  )
    return null;
  const returned = node.body?.body[0];
  if (
    returned?.type !== "ReturnStatement" ||
    returned.argument === null
  )
    return null;
  const checks = conjunctions(returned.argument);
  return checks.length === fields.length &&
    checks.every((check, index) =>
      correspondingFields(check, left, right, fields[index]),
    )
    ? fields
    : null;
}

function parameterFields(parameter: ESTree.BindingIdentifier): readonly string[] | null {
  const annotation = parameter.typeAnnotation?.typeAnnotation;
  if (parameter.optional || annotation?.type !== "TSTypeLiteral")
    return null;
  const fields: string[] = [];
  for (const member of annotation.members) {
    if (
      member.type !== "TSPropertySignature" ||
      member.computed ||
      member.optional ||
      member.typeAnnotation?.typeAnnotation.type !== "TSStringKeyword"
    )
      return null;
    const name = fieldName(member.key);
    if (name === null || UNSAFE_FIELDS.has(name) || fields.includes(name))
      return null;
    fields.push(name);
  }
  return fields.includes("toJSON") && fields.length > 1 ? fields : null;
}

function fieldName(node: Node): string | null {
  if (node.type === "Identifier") return node.name;
  return node.type === "Literal" && typeof node.value === "string"
    ? node.value
    : null;
}

function conjunctions(expression: Expression): Expression[] {
  const checks: Expression[] = [];
  const pending = [expression];
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined) continue;
    if (current.type === "LogicalExpression" && current.operator === "&&") {
      pending.push(current.right, current.left);
    } else checks.push(current);
  }
  return checks;
}

function correspondingFields(
  node: Expression,
  left: ESTree.BindingIdentifier,
  right: ESTree.BindingIdentifier,
  field: string | undefined,
): boolean {
  return (
    node.type === "BinaryExpression" &&
    node.operator === "===" &&
    memberOf(node.left, left, field) &&
    memberOf(node.right, right, field)
  );
}

function memberOf(node: Node, parameter: ESTree.BindingIdentifier, field: string | undefined): boolean {
  return (
    node.type === "MemberExpression" &&
    !node.computed &&
    !node.optional &&
    node.object.type === "Identifier" &&
    node.object.name === parameter.name &&
    node.property.type === "Identifier" &&
    node.property.name === field
  );
}

function callerElements(node: ESTree.Function): Expression[] | null {
  if (
    node.params.length !== 0 ||
    node.returnType?.typeAnnotation.type !== "TSArrayType" ||
    node.returnType.typeAnnotation.elementType.type !== "TSBooleanKeyword"
  )
    return null;
  const returned = node.body?.body[0];
  const array = returned?.type === "ReturnStatement" ? returned.argument : null;
  if (array?.type !== "ArrayExpression" || array.elements.length !== 2)
    return null;
  const elements: Expression[] = [];
  for (const element of array.elements) {
    if (element === null || element.type === "SpreadElement")
      return null;
    elements.push(element);
  }
  return elements;
}

function isComparatorCall(
  sourceCode: SourceCode,
  call: ESTree.CallExpression,
  comparator: ESTree.Function,
  fields: readonly string[],
): boolean {
  if (
    call.optional ||
    isPresent(call.typeArguments) ||
    call.callee.type !== "Identifier" ||
    call.arguments.length !== 2
  )
    return false;
  const binding = findVariable(sourceCode.getScope(call), call.callee.name);
  return (
    binding?.defs.length === 1 &&
    binding.defs[0]?.node === comparator &&
    call.arguments.every((argument) => literalRecord(argument, fields))
  );
}

function literalRecord(node: Node, fields: readonly string[]): boolean {
  return (
    node.type === "ObjectExpression" &&
    node.properties.length === fields.length &&
    node.properties.every(
      (property, index) =>
        property.type === "Property" &&
        !property.computed &&
        !property.method &&
        !property.shorthand &&
        property.kind === "init" &&
        fieldName(property.key) === fields[index] &&
        property.value.type === "Literal" &&
        typeof property.value.value === "string",
    )
  );
}

function serializedLiteral(
  sourceCode: SourceCode,
  node: Node,
  fields: readonly string[],
): ESTree.ObjectExpression | null {
  if (
    node.type !== "CallExpression" ||
    node.optional ||
    isPresent(node.typeArguments) ||
    node.arguments.length !== 1 ||
    node.callee.type !== "MemberExpression" ||
    node.callee.computed ||
    node.callee.optional ||
    node.callee.object.type !== "Identifier" ||
    node.callee.object.name !== "JSON" ||
    node.callee.property.type !== "Identifier" ||
    node.callee.property.name !== "stringify"
  )
    return null;
  const binding = findVariable(sourceCode.getScope(node), "JSON");
  const argument = node.arguments[0];
  return (binding === null || binding.defs.length === 0) &&
    argument?.type === "ObjectExpression" &&
    literalRecord(argument, fields)
    ? argument
    : null;
}

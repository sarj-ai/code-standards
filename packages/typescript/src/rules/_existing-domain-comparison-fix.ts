/**
 * @fileoverview _existing-domain-comparison-fix — reuse a closed-domain comparator.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

const UNSAFE_FIELDS: ReadonlySet<string> = new Set([
  "__proto__",
  "constructor",
  "prototype",
]);

/** Reuse an already exercised comparator for a closed string-literal record domain. */
export function existingDomainComparisonFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  comparison: TSESTree.BinaryExpression,
): TSESLint.ReportFixFunction | null {
  if (
    comparison.operator !== "===" ||
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length !== 0
  )
    return null;
  const [comparator, exported] = sourceCode.ast.body;
  if (
    !isOrdinary(comparator) ||
    comparator.id === null ||
    exported?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    exported.exportKind !== "value" ||
    !isOrdinary(exported.declaration)
  )
    return null;
  const fields = comparatorFields(comparator);
  const elements = callerElements(exported.declaration);
  if (fields === null || elements === null || elements[1] !== comparison)
    return null;
  const existing = elements[0];
  if (
    existing?.type !== AST_NODE_TYPES.CallExpression ||
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

function isOrdinary(
  node: TSESTree.Node | null | undefined,
): node is TSESTree.FunctionDeclaration {
  return (
    node?.type === AST_NODE_TYPES.FunctionDeclaration &&
    node.id !== null &&
    !node.declare &&
    !node.async &&
    !node.generator &&
    node.typeParameters === undefined &&
    node.body.body.length === 1
  );
}

function comparatorFields(
  node: TSESTree.FunctionDeclaration,
): readonly string[] | null {
  const [left, right] = node.params;
  if (
    node.params.length !== 2 ||
    left?.type !== AST_NODE_TYPES.Identifier ||
    right?.type !== AST_NODE_TYPES.Identifier ||
    left.name === right.name ||
    node.returnType?.typeAnnotation.type !== AST_NODE_TYPES.TSBooleanKeyword
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
  const returned = node.body.body[0];
  if (
    returned?.type !== AST_NODE_TYPES.ReturnStatement ||
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

function parameterFields(
  parameter: TSESTree.Identifier,
): readonly string[] | null {
  const annotation = parameter.typeAnnotation?.typeAnnotation;
  if (parameter.optional || annotation?.type !== AST_NODE_TYPES.TSTypeLiteral)
    return null;
  const fields: string[] = [];
  for (const member of annotation.members) {
    if (
      member.type !== AST_NODE_TYPES.TSPropertySignature ||
      member.computed ||
      member.optional ||
      member.typeAnnotation?.typeAnnotation.type !==
        AST_NODE_TYPES.TSStringKeyword
    )
      return null;
    const name = fieldName(member.key);
    if (name === null || UNSAFE_FIELDS.has(name) || fields.includes(name))
      return null;
    fields.push(name);
  }
  return fields.includes("toJSON") && fields.length > 1 ? fields : null;
}

function fieldName(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.Identifier) return node.name;
  return node.type === AST_NODE_TYPES.Literal && typeof node.value === "string"
    ? node.value
    : null;
}

function conjunctions(expression: TSESTree.Expression): TSESTree.Expression[] {
  const checks: TSESTree.Expression[] = [];
  const pending = [expression];
  while (pending.length > 0) {
    const current = pending.pop();
    if (current === undefined) continue;
    if (
      current.type === AST_NODE_TYPES.LogicalExpression &&
      current.operator === "&&"
    ) {
      pending.push(current.right, current.left);
    } else checks.push(current);
  }
  return checks;
}

function correspondingFields(
  node: TSESTree.Expression,
  left: TSESTree.Identifier,
  right: TSESTree.Identifier,
  field: string | undefined,
): boolean {
  return (
    node.type === AST_NODE_TYPES.BinaryExpression &&
    node.operator === "===" &&
    memberOf(node.left, left, field) &&
    memberOf(node.right, right, field)
  );
}

function memberOf(
  node: TSESTree.Node,
  parameter: TSESTree.Identifier,
  field: string | undefined,
): boolean {
  return (
    node.type === AST_NODE_TYPES.MemberExpression &&
    !node.computed &&
    !node.optional &&
    node.object.type === AST_NODE_TYPES.Identifier &&
    node.object.name === parameter.name &&
    node.property.type === AST_NODE_TYPES.Identifier &&
    node.property.name === field
  );
}

function callerElements(
  node: TSESTree.FunctionDeclaration,
): TSESTree.Expression[] | null {
  if (
    node.params.length !== 0 ||
    node.returnType?.typeAnnotation.type !== AST_NODE_TYPES.TSArrayType ||
    node.returnType.typeAnnotation.elementType.type !==
      AST_NODE_TYPES.TSBooleanKeyword
  )
    return null;
  const returned = node.body.body[0];
  const array =
    returned?.type === AST_NODE_TYPES.ReturnStatement
      ? returned.argument
      : null;
  if (
    array?.type !== AST_NODE_TYPES.ArrayExpression ||
    array.elements.length !== 2
  )
    return null;
  const elements: TSESTree.Expression[] = [];
  for (const element of array.elements) {
    if (element === null || element.type === AST_NODE_TYPES.SpreadElement)
      return null;
    elements.push(element);
  }
  return elements;
}

function isComparatorCall(
  sourceCode: Readonly<TSESLint.SourceCode>,
  call: TSESTree.CallExpression,
  comparator: TSESTree.FunctionDeclaration,
  fields: readonly string[],
): boolean {
  if (
    call.optional ||
    call.typeArguments !== undefined ||
    call.callee.type !== AST_NODE_TYPES.Identifier ||
    call.arguments.length !== 2
  )
    return false;
  const binding = ASTUtils.findVariable(
    sourceCode.getScope(call),
    call.callee.name,
  );
  return (
    binding?.defs.length === 1 &&
    binding.defs[0]?.node === comparator &&
    call.arguments.every((argument) => literalRecord(argument, fields))
  );
}

function literalRecord(
  node: TSESTree.Node,
  fields: readonly string[],
): boolean {
  return (
    node.type === AST_NODE_TYPES.ObjectExpression &&
    node.properties.length === fields.length &&
    node.properties.every(
      (property, index) =>
        property.type === AST_NODE_TYPES.Property &&
        !property.computed &&
        !property.method &&
        !property.shorthand &&
        property.kind === "init" &&
        fieldName(property.key) === fields[index] &&
        property.value.type === AST_NODE_TYPES.Literal &&
        typeof property.value.value === "string",
    )
  );
}

function serializedLiteral(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Node,
  fields: readonly string[],
): TSESTree.ObjectExpression | null {
  if (
    node.type !== AST_NODE_TYPES.CallExpression ||
    node.optional ||
    node.typeArguments !== undefined ||
    node.arguments.length !== 1 ||
    node.callee.type !== AST_NODE_TYPES.MemberExpression ||
    node.callee.computed ||
    node.callee.optional ||
    node.callee.object.type !== AST_NODE_TYPES.Identifier ||
    node.callee.object.name !== "JSON" ||
    node.callee.property.type !== AST_NODE_TYPES.Identifier ||
    node.callee.property.name !== "stringify"
  )
    return null;
  const binding = ASTUtils.findVariable(sourceCode.getScope(node), "JSON");
  const argument = node.arguments[0];
  return (binding === null || binding.defs.length === 0) &&
    argument?.type === AST_NODE_TYPES.ObjectExpression &&
    literalRecord(argument, fields)
    ? argument
    : null;
}

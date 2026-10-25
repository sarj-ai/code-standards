/**
 * @fileoverview _labeled-tuple-object-fix — reuse an authored object contract for a tuple.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

const UNSAFE_NAMES: ReadonlySet<string> = new Set([
  "__proto__",
  "constructor",
  "prototype",
]);
const FIELD_COUNT = 2;

interface TupleFields {
  readonly labels: readonly TSESTree.Identifier[];
  readonly types: readonly TSESTree.TypeNode[];
  readonly values: readonly TSESTree.Literal[];
  readonly returned: TSESTree.ArrayExpression;
}

/** Migrate a closed tuple consumer using its already authored public object contract. */
export function labeledTupleObjectFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  annotation: TSESTree.TypeNode,
): TSESLint.ReportFixFunction | null {
  if (
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length > 0
  )
    return null;
  const [helper, statement] = sourceCode.ast.body;
  if (
    !isOrdinary(helper) ||
    statement?.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
    !isOrdinary(statement.declaration) ||
    helper.returnType?.typeAnnotation !== annotation
  )
    return null;
  const caller = statement.declaration;
  const fields = tupleFields(helper);
  const object = caller.returnType?.typeAnnotation;
  if (
    fields === null ||
    object?.type !== AST_NODE_TYPES.TSTypeLiteral ||
    !matchingObjectType(object, fields)
  )
    return null;
  const pattern = callerPattern(sourceCode, caller, helper, fields);
  if (pattern === null) return null;
  const properties: string[] = [];
  for (const [index, label] of fields.labels.entries()) {
    const value = fields.values[index];
    if (value === undefined) return null;
    properties.push(
      `${sourceCode.getText(label)}: ${sourceCode.getText(value)}`,
    );
  }
  const bindings = fields.labels.map((label) => sourceCode.getText(label));
  return (fixer) => [
    fixer.replaceText(annotation, sourceCode.getText(object)),
    fixer.replaceText(fields.returned, `{ ${properties.join(", ")} }`),
    fixer.replaceText(pattern, `{ ${bindings.join(", ")} }`),
  ];
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
    node.params.length === 0 &&
    node.typeParameters === undefined
  );
}

function tupleFields(helper: TSESTree.FunctionDeclaration): TupleFields | null {
  const tuple = helper.returnType?.typeAnnotation;
  const returned = helper.body.body[0];
  if (
    tuple?.type !== AST_NODE_TYPES.TSTupleType ||
    tuple.elementTypes.length !== FIELD_COUNT ||
    helper.body.body.length !== 1 ||
    returned?.type !== AST_NODE_TYPES.ReturnStatement ||
    returned.argument?.type !== AST_NODE_TYPES.ArrayExpression ||
    returned.argument.elements.length !== FIELD_COUNT
  )
    return null;
  const labels: TSESTree.Identifier[] = [];
  const types: TSESTree.TypeNode[] = [];
  const values: TSESTree.Literal[] = [];
  for (const [index, field] of tuple.elementTypes.entries()) {
    const value = returned.argument.elements[index];
    if (
      field.type !== AST_NODE_TYPES.TSNamedTupleMember ||
      field.optional ||
      value?.type !== AST_NODE_TYPES.Literal ||
      !primitiveValue(field.elementType, value) ||
      UNSAFE_NAMES.has(field.label.name) ||
      labels.some((label) => label.name === field.label.name)
    )
      return null;
    labels.push(field.label);
    types.push(field.elementType);
    values.push(value);
  }
  return { labels, types, values, returned: returned.argument };
}

function primitiveValue(
  type: TSESTree.TypeNode,
  value: TSESTree.Literal,
): boolean {
  switch (type.type) {
    case AST_NODE_TYPES.TSStringKeyword:
      return typeof value.value === "string";
    case AST_NODE_TYPES.TSNumberKeyword:
      return typeof value.value === "number" && Number.isFinite(value.value);
    case AST_NODE_TYPES.TSBooleanKeyword:
      return typeof value.value === "boolean";
    default:
      return false;
  }
}

function matchingObjectType(
  object: TSESTree.TSTypeLiteral,
  fields: TupleFields,
): boolean {
  return (
    object.members.length === FIELD_COUNT &&
    object.members.every(
      (member, index) =>
        member.type === AST_NODE_TYPES.TSPropertySignature &&
        !member.computed &&
        !member.optional &&
        member.key.type === AST_NODE_TYPES.Identifier &&
        member.key.name === fields.labels[index]?.name &&
        member.typeAnnotation?.typeAnnotation.type ===
          fields.types[index]?.type,
    )
  );
}

function callerPattern(
  sourceCode: Readonly<TSESLint.SourceCode>,
  caller: TSESTree.FunctionDeclaration,
  helper: TSESTree.FunctionDeclaration,
  fields: TupleFields,
): TSESTree.ArrayPattern | null {
  const [declaration, returned] = caller.body.body;
  if (
    caller.body.body.length !== 2 ||
    declaration?.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.declare ||
    declaration.kind !== "const" ||
    declaration.declarations.length !== 1 ||
    returned?.type !== AST_NODE_TYPES.ReturnStatement ||
    returned.argument?.type !== AST_NODE_TYPES.ObjectExpression ||
    !matchingReturn(returned.argument, fields)
  )
    return null;
  const binding = declaration.declarations[0];
  if (
    binding?.id.type !== AST_NODE_TYPES.ArrayPattern ||
    binding.id.typeAnnotation !== undefined ||
    binding.id.elements.length !== FIELD_COUNT ||
    !binding.id.elements.every(
      (element, index) =>
        element?.type === AST_NODE_TYPES.Identifier &&
        element.typeAnnotation === undefined &&
        element.name === fields.labels[index]?.name,
    )
  )
    return null;
  const call = binding.init;
  if (
    call?.type !== AST_NODE_TYPES.CallExpression ||
    call.optional ||
    call.typeArguments !== undefined ||
    call.arguments.length !== 0 ||
    call.callee.type !== AST_NODE_TYPES.Identifier
  )
    return null;
  const variable = ASTUtils.findVariable(
    sourceCode.getScope(call),
    call.callee.name,
  );
  return variable?.defs.length === 1 && variable.defs[0]?.node === helper
    ? binding.id
    : null;
}

function matchingReturn(
  object: TSESTree.ObjectExpression,
  fields: TupleFields,
): boolean {
  return (
    object.properties.length === FIELD_COUNT &&
    object.properties.every(
      (property, index) =>
        property.type === AST_NODE_TYPES.Property &&
        property.kind === "init" &&
        !property.method &&
        !property.computed &&
        property.shorthand &&
        property.key.type === AST_NODE_TYPES.Identifier &&
        property.value.type === AST_NODE_TYPES.Identifier &&
        property.key.name === fields.labels[index]?.name &&
        property.value.name === property.key.name,
    )
  );
}

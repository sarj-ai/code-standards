/** @fileoverview _labeled-tuple-object-fix — reuse an authored object contract for a tuple. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";
import { plainFunctionBody, soleConstDeclarator } from "./_closed-module.js";

const UNSAFE_NAMES: ReadonlySet<string> = new Set([
  "__proto__",
  "constructor",
  "prototype",
]);
const FIELD_COUNT = 2;

interface TupleFields {
  readonly labels: readonly ESTree.IdentifierName[];
  readonly types: readonly Node[];
  readonly values: readonly ESTree.Expression[];
  readonly returned: ESTree.ArrayExpression;
}

/** Migrate a closed tuple consumer using its already authored public object contract. */
export function labeledTupleObjectFix(
  sourceCode: SourceCode,
  annotation: Node,
): FixFn | null {
  if (
    sourceCode.ast.body.length !== 2 ||
    sourceCode.getAllComments().length > 0
  )
    return null;
  const [helper, statement] = sourceCode.ast.body;
  if (
    helper?.type !== "FunctionDeclaration" || !isOrdinary(helper) ||
    statement?.type !== "ExportNamedDeclaration" ||
    statement.declaration?.type !== "FunctionDeclaration" || !isOrdinary(statement.declaration) ||
    helper.returnType?.typeAnnotation !== annotation
  )
    return null;
  const caller = statement.declaration;
  const fields = tupleFields(helper);
  const object = caller.returnType?.typeAnnotation;
  if (
    fields === null ||
    object?.type !== "TSTypeLiteral" ||
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

/** A named plain function without parameters. */
function isOrdinary(node: ESTree.Function): boolean {
  return node.id !== null && node.params.length === 0 && plainFunctionBody(node) !== null;
}

function tupleFields(helper: ESTree.Function): TupleFields | null {
  const tuple = helper.returnType?.typeAnnotation;
  const statements = helper.body?.body ?? [];
  const returned = statements[0];
  if (
    tuple?.type !== "TSTupleType" ||
    tuple.elementTypes.length !== FIELD_COUNT ||
    statements.length !== 1 ||
    returned?.type !== "ReturnStatement" ||
    returned.argument?.type !== "ArrayExpression" ||
    returned.argument.elements.length !== FIELD_COUNT
  )
    return null;
  const labels: ESTree.IdentifierName[] = [];
  const types: Node[] = [];
  const values: ESTree.Expression[] = [];
  for (const [index, field] of tuple.elementTypes.entries()) {
    const value = returned.argument.elements[index];
    if (
      field.type !== "TSNamedTupleMember" ||
      field.optional ||
      value?.type !== "Literal" ||
      !primitiveValue(field.elementType, value.value) ||
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

function primitiveValue(type: Node, value: unknown): boolean {
  switch (type.type) {
    case "TSStringKeyword":
      return typeof value === "string";
    case "TSNumberKeyword":
      return typeof value === "number" && Number.isFinite(value);
    case "TSBooleanKeyword":
      return typeof value === "boolean";
    default:
      return false;
  }
}

function matchingObjectType(
  object: ESTree.TSTypeLiteral,
  fields: TupleFields,
): boolean {
  return (
    object.members.length === FIELD_COUNT &&
    object.members.every(
      (member, index) =>
        member.type === "TSPropertySignature" &&
        !member.computed &&
        !member.optional &&
        member.key.type === "Identifier" &&
        member.key.name === fields.labels[index]?.name &&
        member.typeAnnotation?.typeAnnotation.type ===
          fields.types[index]?.type,
    )
  );
}

function callerPattern(
  sourceCode: SourceCode,
  caller: ESTree.Function,
  helper: ESTree.Function,
  fields: TupleFields,
): ESTree.ArrayPattern | null {
  const statements = caller.body?.body ?? [];
  const [declaration, returned] = statements;
  if (
    statements.length !== 2 ||
    declaration?.type !== "VariableDeclaration" ||
    returned?.type !== "ReturnStatement" ||
    returned.argument?.type !== "ObjectExpression" ||
    !matchingReturn(returned.argument, fields)
  )
    return null;
  const binding = soleConstDeclarator(declaration);
  if (
    binding?.id.type !== "ArrayPattern" ||
    !isLabelPattern(binding.id, fields) ||
    !callsHelper(sourceCode, binding.init, helper)
  )
    return null;
  return binding.id;
}

/** `[first, second]` binding the tuple's labels in order, without annotations. */
function isLabelPattern(pattern: ESTree.ArrayPattern, fields: TupleFields): boolean {
  return (
    !isPresent(pattern.typeAnnotation) &&
    pattern.elements.length === FIELD_COUNT &&
    pattern.elements.every(
      (element, index) =>
        element?.type === "Identifier" &&
        !isPresent(element.typeAnnotation) &&
        element.name === fields.labels[index]?.name,
    )
  );
}

/** A plain `helper()` call that resolves to `helper`. */
function callsHelper(sourceCode: SourceCode, call: Node | null, helper: ESTree.Function): boolean {
  if (
    call?.type !== "CallExpression" ||
    call.optional ||
    isPresent(call.typeArguments) ||
    call.arguments.length !== 0 ||
    call.callee.type !== "Identifier"
  )
    return false;
  const variable = findVariable(sourceCode.getScope(call), call.callee.name);
  return variable?.defs.length === 1 && variable.defs[0]?.node === helper;
}

function matchingReturn(
  object: ESTree.ObjectExpression,
  fields: TupleFields,
): boolean {
  return (
    object.properties.length === FIELD_COUNT &&
    object.properties.every(
      (property, index) =>
        property.type === "Property" &&
        property.kind === "init" &&
        !property.method &&
        !property.computed &&
        property.shorthand &&
        property.key.type === "Identifier" &&
        property.value.type === "Identifier" &&
        property.key.name === fields.labels[index]?.name &&
        property.value.name === property.key.name,
    )
  );
}

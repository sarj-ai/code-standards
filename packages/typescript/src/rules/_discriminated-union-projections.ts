/** @fileoverview _discriminated-union-projections — advisory relationships between immutable state comparisons. */

import type { ESTree, Identifier, Node, SourceCode, TsVariable } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { isPresent } from "../utils/is-present.js";
import { enclosingFunction, isConstDeclaration, stableValueBinding, typeOnlyReference, writtenMember } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";
import type { TsrsFile, TsrsType } from "../utils/tsrs-services.js";
import { booleanType, objectContract, returnContract, returnedProperties } from "./_discriminated-union-returns.js";

type Producer = ESTree.ArrowFunctionExpression | ESTree.Function;
type Primitive = string | number;

interface Comparison {
  readonly field: string;
  readonly binding: TsVariable;
  readonly left: Identifier;
  readonly right: ESTree.Expression;
}

export interface ProjectedBooleanPair {
  readonly reportNode: Node;
  readonly left: Comparison;
  readonly right: Comparison;
}

/** One direct return, with all own return statements accounted for by the caller. */
export function projectedBooleanPairs(
  owner: Producer,
  returned: ESTree.ReturnStatement,
  source: SourceCode,
): readonly ProjectedBooleanPair[] {
  if (owner.async || owner.generator || isPresent(owner.typeParameters) || owner.body?.type !== "BlockStatement" ||
    parentOf(returned) !== owner.body || owner.body.body.at(-1) !== returned || returned.argument?.type !== "ObjectExpression") return [];
  const contract = returnContract(owner, source);
  const shape = contract === undefined ? undefined : objectContract(contract.members);
  if (shape === undefined || contract === undefined) return [];
  const properties = returnedProperties([returned.argument], shape)?.[0];
  if (properties === undefined) return [];
  const fields = [...shape.members].filter(([, member]) => !member.optional &&
    booleanType(member.typeAnnotation?.typeAnnotation, source));
  if (fields.length > 8) return [];
  const comparisons: Comparison[] = [];
  for (const [field] of fields) {
    const value = properties.get(field);
    if (value?.type !== "BinaryExpression" || value.operator !== "===" || value.left.type !== "Identifier" ||
      !constantSyntax(value.right, source)) continue;
    const binding = localSnapshot(value.left, owner, source);
    if (binding !== null) comparisons.push({ field, binding, left: value.left, right: value.right });
  }
  return comparisons.flatMap((left, index) => comparisons.slice(index + 1)
    .filter((right) => right.binding === left.binding).map((right) => ({ reportNode: contract.reportNode, left, right })));
}

/** Destructuring a primitive snapshot is safe; following mutable object members is not. */
function localSnapshot(identifier: Identifier, owner: Producer, source: SourceCode): TsVariable | null {
  const variable = findVariable(source.getScope(identifier), identifier.name);
  const declaration = variable?.defs[0]?.node;
  if (variable === null || variable.defs.length !== 1 || declaration?.type !== "VariableDeclarator" ||
    !isConstDeclaration(parentOf(declaration)) || !isPresent(declaration.init) ||
    enclosingFunction(declaration) !== owner || declaration.range[1] >= identifier.range[0] ||
    !stableValueBinding(variable)) return null;
  return variable;
}

/** No aliases, escapes, writes, dynamic reads or method calls through an enum namespace in this file. */
function constantSyntax(node: ESTree.Expression, source: SourceCode): boolean {
  if (node.type === "Literal") return typeof node.value === "string" || typeof node.value === "number" && Number.isFinite(node.value);
  if (node.type !== "MemberExpression" || node.computed || node.optional ||
    node.object.type !== "Identifier" || node.property.type !== "Identifier") return false;
  const variable = findVariable(source.getScope(node.object), node.object.name);
  const definition = variable?.defs[0]?.node;
  if (variable === null || variable.defs.length !== 1 ||
    (definition?.type !== "TSEnumDeclaration" && definition?.type !== "ImportSpecifier") ||
    !stableValueBinding(variable)) return false;
  return variable.references.every((reference) => {
    if (typeOnlyReference(reference)) return true;
    const member = parentOf(reference.identifier);
    if (member?.type !== "MemberExpression" || member.object !== reference.identifier || member.computed ||
      member.optional || writtenMember(member)) return false;
    const use = parentOf(member);
    return !((use?.type === "CallExpression" || use?.type === "NewExpression") && use.callee === member);
  });
}

/** Resolve declarations, not merely a value typed as `typeof SomeEnum` or a singleton-valued getter. */
function enumConstant(node: ESTree.Expression, native: NativeTypes): boolean {
  if (node.type !== "MemberExpression") return false;
  const root = native.node(node.object);
  const member = native.node(node.property);
  let symbol = root === undefined ? undefined : native.checker.getSymbolAtLocation(root);
  if (symbol === undefined || member === undefined) return false;
  if ((symbol.flags & native.sync.SymbolFlags.Alias) !== 0) symbol = native.checker.getAliasedSymbol(symbol);
  const declarations = symbol.declarations;
  if (declarations.length !== 1 || declarations[0]?.kind !== native.ast.SyntaxKind.EnumDeclaration) return false;
  const selected = native.checker.getSymbolAtLocation(member)?.declarations;
  return selected?.length === 1 && selected[0]?.kind === native.ast.SyntaxKind.EnumMember;
}

/** Batch all type requests through the rule suite's shared native service. No printed-type comparisons. */
export function projectedBooleanEvidence(file: TsrsFile, candidates: readonly ProjectedBooleanPair[]): readonly boolean[] {
  const nodes = candidates.flatMap(({ left, right }) => [left.left, right.left, left.right, right.right]);
  const types = file.typesOf(nodes);
  const unions = types.flatMap((type) => type !== undefined && type.isUnionType() ? [type] : []);
  const lists = file.batch(unions.map((type) => type.getTypes.gen()));
  let index = 0;
  const domains = types.map((type) => type === undefined ? undefined :
    primitiveValues(type.isUnionType() ? lists[index++] ?? [] : [type], file));
  const native = nativeTypes(file);
  const constants = new Map<ESTree.Expression, boolean>();
  function constant(node: ESTree.Expression, value: Primitive | undefined): boolean {
    if (node.type === "Literal") return node.value === value;
    let valid = constants.get(node);
    if (valid === undefined) {
      valid = enumConstant(node, native);
      constants.set(node, valid);
    }
    return valid;
  }
  return candidates.map(({ left, right }, ordinal) => {
    const [a, b, x, y] = domains.slice(ordinal * 4, ordinal * 4 + 4);
    const first = x?.[0];
    const second = y?.[0];
    return a !== undefined && b !== undefined && x?.length === 1 && y?.length === 1 &&
      first !== undefined && second !== undefined && first !== second &&
      constant(left.right, first) && constant(right.right, second) &&
      a.includes(first) && a.includes(second) && b.includes(first) && b.includes(second);
  });
}

/** Open, unknown, object, nullable, symbol and oversized domains remain outside the advisory contract. */
function primitiveValues(types: readonly TsrsType[], file: TsrsFile): readonly Primitive[] | undefined {
  if (types.length < 1 || types.length > 16) return undefined;
  const values: Primitive[] = [];
  for (const type of types) {
    if ((type.flags & (file.flags.StringLiteral | file.flags.NumberLiteral)) === 0) return undefined;
    const value = type.value;
    if (typeof value !== "string" && !(typeof value === "number" && Number.isFinite(value))) return undefined;
    values.push(value);
  }
  return values;
}

/**
 * @fileoverview _discriminated-union-returns — find finite, tag-specific producer shapes hidden by flat return contracts.
 *
 * Port of the 18.x `_discriminated-union-returns.ts` helper, used only by
 * prefer-discriminated-union. Optional AST fields are `null` under Oxlint, so
 * the `undefined` checks accept both.
 */

import type { ESTree, Node, Scope, SourceCode, TsDefinition } from "../types.js";
import { tsVariable } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";

type Producer = ESTree.ArrowFunctionExpression | ESTree.Function;
type Tag = string | number | boolean;

interface ReturnPaths {
  readonly objects: readonly ESTree.ObjectExpression[];
  readonly fallsThrough: boolean;
}

const MAX_PATH_VISITS = 2048;
const MAX_RETURN_OBJECTS = 256;
const MAX_PATH_DEPTH = 64;

class PathBudget {
  #visits = 0;
  #objects = 0;

  readonly sourceCode: SourceCode;

  constructor(sourceCode: SourceCode) {
    this.sourceCode = sourceCode;
  }

  within(depth: number): boolean {
    this.#visits += 1;
    return this.#visits <= MAX_PATH_VISITS && depth <= MAX_PATH_DEPTH;
  }

  recordObject(): boolean {
    this.#objects += 1;
    return this.#objects <= MAX_RETURN_OBJECTS;
  }
}

interface Contract {
  readonly members: readonly ESTree.TSSignature[];
  readonly reportNode: Node;
}

interface ObjectContract {
  readonly members: ReadonlyMap<string, ESTree.TSPropertySignature>;
  readonly optional: ReadonlySet<string>;
}

export interface DiscriminatedReturn {
  readonly reportNode: Node;
  readonly tag: string;
  readonly members: ReadonlyMap<string, ESTree.TSPropertySignature>;
  readonly returned: readonly ReadonlyMap<string, Node>[];
}

/** The evidence concerns this producer's returned variants, not every use of a shared type. */
export function discriminatedUnionReturns(node: Producer, sourceCode: SourceCode): DiscriminatedReturn | undefined {
  if (node.generator || !isPresent(node.body)) return undefined;
  const contract = returnContract(node, sourceCode);
  if (contract === undefined) return undefined;
  const budget = new PathBudget(sourceCode);
  const paths = node.body.type === "BlockStatement" ? statementsPaths(node.body.body, budget, 0) : {
    objects: returnedObjects(node.body, budget, 0) ?? [], fallsThrough: false,
  };
  if (paths === undefined || paths.fallsThrough || paths.objects.length < 2) return undefined;
  const shape = objectContract(contract.members);
  if (shape === undefined) return undefined;
  const returned = returnedProperties(paths.objects, shape);
  if (returned === undefined) return undefined;
  for (const [name, member] of shape.members) {
    if (member.optional) continue;
    const domain = tagDomain(member.typeAnnotation?.typeAnnotation);
    if (domain !== undefined && hasTagSpecificPayload(name, domain, shape.optional, returned)) {
      return { reportNode: contract.reportNode, tag: name, members: shape.members, returned };
    }
  }
  return undefined;
}

function returnContract(node: Producer, sourceCode: SourceCode): Contract | undefined {
  const annotation = node.returnType;
  if (!isPresent(annotation)) return undefined;
  let type = annotation.typeAnnotation;
  if (node.async && type.type === "TSTypeReference" && type.typeName.type === "Identifier" &&
    type.typeName.name === "Promise" && isPresent(type.typeArguments) && type.typeArguments.params.length === 1 && definitions(type, sourceCode).length === 0) {
    const inner = type.typeArguments.params[0];
    if (inner === undefined) return undefined;
    type = inner;
  }
  if (type.type === "TSTypeLiteral") return { members: type.members, reportNode: annotation };
  if (type.type !== "TSTypeReference" || isPresent(type.typeArguments)) return undefined;
  const bindings = definitions(type, sourceCode);
  if (bindings.length !== 1) return undefined;
  const declaration = bindings[0]?.node;
  if (declaration?.type === "TSTypeAliasDeclaration" && !isPresent(declaration.typeParameters) &&
    declaration.typeAnnotation.type === "TSTypeLiteral") {
    return { members: declaration.typeAnnotation.members, reportNode: declaration };
  }
  if (declaration?.type === "TSInterfaceDeclaration" && declaration.extends.length === 0 &&
    !isPresent(declaration.typeParameters)) {
    return { members: declaration.body.body, reportNode: declaration };
  }
  return undefined;
}

/** Resolve type-space bindings without confusing a value-space shadow with a type. */
function definitions(reference: ESTree.TSTypeReference, sourceCode: SourceCode): readonly TsDefinition[] {
  if (reference.typeName.type !== "Identifier") return [];
  let scope: Scope | null = sourceCode.getScope(reference);
  while (scope !== null) {
    const found = scope.set.get(reference.typeName.name);
    const binding = found === undefined ? undefined : tsVariable(found);
    const typeDefinitions = binding?.defs.filter((definition) => definition.isTypeDefinition) ?? [];
    if (typeDefinitions.length > 0 || binding?.isTypeVariable === true) return typeDefinitions;
    scope = scope.upper;
  }
  return [];
}

/** Validate that every declared field has a unique, locally known name and optionality. */
function objectContract(elements: readonly ESTree.TSSignature[]): ObjectContract | undefined {
  const members = new Map<string, ESTree.TSPropertySignature>();
  const optional = new Set<string>();
  for (const member of elements) {
    if (member.type !== "TSPropertySignature") return undefined;
    const name = propertyName(member);
    if (name === undefined || members.has(name)) return undefined;
    members.set(name, member);
    if (member.optional) optional.add(name);
  }
  return optional.size === 0 ? undefined : { members, optional };
}

/** Compare produced keys with the declared contract before inferring their tag relationship. */
function returnedProperties(
  objects: readonly ESTree.ObjectExpression[],
  contract: ObjectContract,
): readonly ReadonlyMap<string, Node>[] | undefined {
  const returned: ReadonlyMap<string, Node>[] = [];
  for (const object of objects) {
    const properties = objectProperties(object);
    if (properties === undefined) return undefined;
    if ([...properties.keys()].some((name) => !contract.members.has(name))) return undefined;
    if ([...contract.members].some(([name, member]) => !member.optional && !properties.has(name))) return undefined;
    if (hasEmptyPayload(properties, contract.optional)) return undefined;
    returned.push(properties);
  }
  return returned;
}

/** Spreads, accessors, computed keys and duplicates conceal the actual runtime key set. */
function objectProperties(object: ESTree.ObjectExpression): ReadonlyMap<string, Node> | undefined {
  const properties = new Map<string, Node>();
  for (const property of object.properties) {
    if (property.type !== "Property" || property.kind !== "init" || property.method) return undefined;
    const name = propertyName(property);
    if (name === undefined || name === "__proto__" || properties.has(name) || (property.value as Node).type === "AssignmentPattern") return undefined;
    properties.set(name, property.value);
  }
  return properties;
}

/** Explicitly empty values do not establish a useful required payload in a variant. */
function hasEmptyPayload(properties: ReadonlyMap<string, Node>, optional: ReadonlySet<string>): boolean {
  for (const name of optional) {
    const value = properties.get(name);
    if (value === undefined) continue;
    if (value.type === "Literal" && value.value === null) return true;
    if (value.type === "Identifier" && value.name === "undefined") return true;
    if (value.type === "UnaryExpression" && value.operator === "void") return true;
  }
  return false;
}

function tagDomain(node: ESTree.TSType | undefined): ReadonlySet<Tag> | undefined {
  if (node?.type === "TSBooleanKeyword") return new Set([true, false]);
  if (node?.type !== "TSUnionType") return undefined;
  const values = new Set<Tag>();
  for (const member of node.types) {
    if (member.type !== "TSLiteralType") return undefined;
    const value = literalTag(member.literal);
    if (value === undefined) return undefined;
    values.add(value);
  }
  return values.size > 1 ? values : undefined;
}

function hasTagSpecificPayload(
  tag: string,
  domain: ReadonlySet<Tag>,
  optional: ReadonlySet<string>,
  returned: readonly ReadonlyMap<string, Node>[],
): boolean {
  const variants = new Map<Tag, ReadonlySet<string>>();
  for (const properties of returned) {
    const value = properties.get(tag);
    const literal = value === undefined ? undefined : literalTag(value);
    if (literal === undefined || !domain.has(literal)) return false;
    const payload = new Set([...optional].filter((name) => properties.has(name)));
    const previous = variants.get(literal);
    if (previous !== undefined && (previous.size !== payload.size || [...previous].some((name) => !payload.has(name)))) return false;
    variants.set(literal, payload);
  }
  if (variants.size !== domain.size) return false;
  return [...optional].some((name) => {
    const presence = [...variants.values()].map((payload) => payload.has(name));
    return presence.includes(true) && presence.includes(false);
  });
}

/** Only analyze simple paths whose completion and return values are locally explicit. */
function statementPaths(statement: ESTree.Statement, budget: PathBudget, depth: number): ReturnPaths | undefined {
  if (!budget.within(depth)) return undefined;
  switch (statement.type) {
    case "ReturnStatement": {
      if (statement.argument === null) return undefined;
      const objects = returnedObjects(statement.argument, budget, depth + 1);
      return objects === undefined ? undefined : { objects, fallsThrough: false };
    }
    case "ThrowStatement": return { objects: [], fallsThrough: false };
    case "BlockStatement": return statementsPaths(statement.body, budget, depth + 1);
    case "SwitchStatement": return switchPaths(statement, budget, depth + 1);
    case "IfStatement": {
      if (statement.test.type === "Literal") return undefined;
      const consequent = statementPaths(statement.consequent, budget, depth + 1);
      const alternate = statement.alternate === null ? { objects: [], fallsThrough: true } : statementPaths(statement.alternate, budget, depth + 1);
      return consequent === undefined || alternate === undefined ? undefined : {
        objects: [...consequent.objects, ...alternate.objects],
        fallsThrough: consequent.fallsThrough || alternate.fallsThrough,
      };
    }
    case "ExpressionStatement":
    case "VariableDeclaration":
    case "FunctionDeclaration":
    case "EmptyStatement":
    case "DebuggerStatement": return { objects: [], fallsThrough: true };
    default: return undefined;
  }
}

/** Every switch arm must terminate; only empty labels may share the next body. */
function switchPaths(statement: ESTree.SwitchStatement, budget: PathBudget, depth: number): ReturnPaths | undefined {
  if (!budget.within(depth) || !reachableSwitch(statement, budget.sourceCode)) return undefined;
  const objects: ESTree.ObjectExpression[] = [];
  for (const branch of statement.cases) {
    if (!budget.within(depth + 1)) return undefined;
    if (branch.consequent.length === 0) continue;
    const paths = switchArmPaths(branch.consequent, budget, depth + 1);
    if (paths === undefined) return undefined;
    objects.push(...paths.objects);
  }
  return { objects, fallsThrough: false };
}

/** Broad immutable parameters prove literal cases and an unlisted default input. */
function reachableSwitch(statement: ESTree.SwitchStatement, sourceCode: SourceCode): boolean {
  if (statement.cases.length > MAX_PATH_VISITS) return false;
  const kind = broadSwitchInput(statement, sourceCode);
  return kind !== undefined && reachableSwitchLabels(statement, kind);
}

/** Restrict witnesses to the producer's unchanged broad input, before any narrowing. */
function broadSwitchInput(statement: ESTree.SwitchStatement, sourceCode: SourceCode): "string" | "number" | undefined {
  const body = statement.parent;
  if (body.type !== "BlockStatement" || body.body.length !== 1) return undefined;
  const owner = body.parent;
  if (owner.type !== "FunctionDeclaration" || owner.id === null) return undefined;
  const callable = findVariable(sourceCode.getScope(owner), owner.id.name);
  if (callable?.defs.length !== 1 || callable.defs[0]?.type !== "FunctionName" || callable.defs[0].node !== owner) return undefined;
  const input = statement.discriminant;
  if (input.type !== "Identifier") return undefined;
  const binding = findVariable(sourceCode.getScope(input), input.name);
  const definition = binding?.defs[0];
  if (binding?.defs.length !== 1 || definition?.type !== "Parameter" || definition.node !== owner ||
    definition.name.type !== "Identifier" || binding.references.some(reference => reference.isWrite())) return undefined;
  const type = definition.name.typeAnnotation?.typeAnnotation.type;
  return type === "TSStringKeyword" ? "string" : type === "TSNumberKeyword" ? "number" : undefined;
}

/** A finite list of literal cases leaves an admitted broad-input witness for default. */
function reachableSwitchLabels(statement: ESTree.SwitchStatement, kind: "string" | "number"): boolean {
  const labels = new Set<Tag>();
  let hasDefault = false;
  for (const branch of statement.cases) {
    if (branch.test === null) {
      if (hasDefault) return false;
      hasDefault = true;
      continue;
    }
    const value = literalTag(branch.test);
    if (typeof value !== kind || value === undefined || labels.has(value)) return false;
    labels.add(value);
  }
  return hasDefault && statement.cases.at(-1)?.consequent.length !== 0;
}

/** Nested conditions can contradict their switch label; do not invent another witness. */
function switchArmPaths(statements: readonly ESTree.Statement[], budget: PathBudget, depth: number): ReturnPaths | undefined {
  if (!budget.within(depth) || statements.length !== 1) return undefined;
  const statement = statements[0];
  if (statement?.type === "BlockStatement") return switchArmPaths(statement.body, budget, depth + 1);
  if (statement?.type === "ThrowStatement") return { objects: [], fallsThrough: false };
  if (statement?.type !== "ReturnStatement" || statement.argument?.type !== "ObjectExpression") return undefined;
  const objects = returnedObjects(statement.argument, budget, depth + 1);
  return objects === undefined ? undefined : { objects, fallsThrough: false };
}

function statementsPaths(statements: readonly ESTree.Statement[], budget: PathBudget, depth: number): ReturnPaths | undefined {
  if (!budget.within(depth)) return undefined;
  const objects: ESTree.ObjectExpression[] = [];
  for (const statement of statements) {
    const paths = statementPaths(statement, budget, depth + 1);
    if (paths === undefined) return undefined;
    objects.push(...paths.objects);
    if (!paths.fallsThrough) return { objects, fallsThrough: false };
  }
  return { objects, fallsThrough: true };
}

function returnedObjects(expression: ESTree.Expression, budget: PathBudget, depth: number): readonly ESTree.ObjectExpression[] | undefined {
  if (!budget.within(depth)) return undefined;
  if (expression.type === "ObjectExpression") {
    return budget.recordObject() ? [expression] : undefined;
  }
  if (expression.type !== "ConditionalExpression" || expression.test.type === "Literal") return undefined;
  const consequent = returnedObjects(expression.consequent, budget, depth + 1);
  const alternate = returnedObjects(expression.alternate, budget, depth + 1);
  return consequent === undefined || alternate === undefined ? undefined : [...consequent, ...alternate];
}


function propertyName(node: ESTree.ObjectProperty | ESTree.TSPropertySignature): string | undefined {
  if (node.computed) return undefined;
  if (node.key.type === "Identifier") return node.key.name;
  if (node.key.type === "Literal" && typeof node.key.value === "string") return node.key.value;
  return undefined;
}

function literalTag(node: Node): Tag | undefined {
  if (node.type !== "Literal") return undefined;
  return typeof node.value === "string" || typeof node.value === "number" || typeof node.value === "boolean"
    ? node.value : undefined;
}

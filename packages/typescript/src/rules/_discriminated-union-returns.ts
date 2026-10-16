/**
 * @fileoverview _discriminated-union-returns — find finite, tag-specific producer shapes hidden by flat return contracts.
 */
import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

type Producer = TSESTree.ArrowFunctionExpression | TSESTree.FunctionDeclaration | TSESTree.FunctionExpression;
type Tag = string | number | boolean;

interface ReturnPaths {
  readonly objects: readonly TSESTree.ObjectExpression[];
  readonly fallsThrough: boolean;
}

interface Contract {
  readonly members: readonly TSESTree.TypeElement[];
  readonly reportNode: TSESTree.Node;
}

interface ObjectContract {
  readonly members: ReadonlyMap<string, TSESTree.TSPropertySignature>;
  readonly optional: ReadonlySet<string>;
}

export interface DiscriminatedReturn {
  readonly reportNode: TSESTree.Node;
  readonly tag: string;
}

/** The evidence concerns this producer's returned variants, not every use of a shared type. */
export function discriminatedUnionReturns(node: Producer, sourceCode: TSESLint.SourceCode): DiscriminatedReturn | undefined {
  if (node.generator || node.body === undefined) return undefined;
  const contract = returnContract(node, sourceCode);
  if (contract === undefined) return undefined;
  const paths = node.body.type === AST_NODE_TYPES.BlockStatement ? blockPaths(node.body) : {
    objects: returnedObjects(node.body) ?? [], fallsThrough: false,
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
      return { reportNode: contract.reportNode, tag: name };
    }
  }
  return undefined;
}

function returnContract(node: Producer, sourceCode: TSESLint.SourceCode): Contract | undefined {
  const annotation = node.returnType;
  if (annotation === undefined) return undefined;
  let type = annotation.typeAnnotation;
  if (node.async && type.type === AST_NODE_TYPES.TSTypeReference && type.typeName.type === AST_NODE_TYPES.Identifier &&
    type.typeName.name === "Promise" && type.typeArguments?.params.length === 1 && definitions(type, sourceCode).length === 0) {
    const inner = type.typeArguments.params[0];
    if (inner === undefined) return undefined;
    type = inner;
  }
  if (type.type === AST_NODE_TYPES.TSTypeLiteral) return { members: type.members, reportNode: annotation };
  if (type.type !== AST_NODE_TYPES.TSTypeReference || type.typeArguments !== undefined) return undefined;
  const bindings = definitions(type, sourceCode);
  if (bindings.length !== 1) return undefined;
  const declaration = bindings[0]?.node;
  if (declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration && declaration.typeParameters === undefined &&
    declaration.typeAnnotation.type === AST_NODE_TYPES.TSTypeLiteral) {
    return { members: declaration.typeAnnotation.members, reportNode: declaration };
  }
  if (declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration && declaration.extends.length === 0 &&
    declaration.typeParameters === undefined) {
    return { members: declaration.body.body, reportNode: declaration };
  }
  return undefined;
}

/** Resolve type-space bindings without confusing a value-space shadow with a type. */
function definitions(reference: TSESTree.TSTypeReference, sourceCode: TSESLint.SourceCode): readonly TSESLint.Scope.Definition[] {
  if (reference.typeName.type !== AST_NODE_TYPES.Identifier) return [];
  let scope: TSESLint.Scope.Scope | null = sourceCode.getScope(reference);
  while (scope !== null) {
    const binding = scope.set.get(reference.typeName.name);
    const typeDefinitions = binding?.defs.filter((definition) => definition.isTypeDefinition) ?? [];
    if (typeDefinitions.length > 0 || binding?.isTypeVariable === true) return typeDefinitions;
    scope = scope.upper;
  }
  return [];
}

/** Validate that every declared field has a unique, locally known name and optionality. */
function objectContract(elements: readonly TSESTree.TypeElement[]): ObjectContract | undefined {
  const members = new Map<string, TSESTree.TSPropertySignature>();
  const optional = new Set<string>();
  for (const member of elements) {
    if (member.type !== AST_NODE_TYPES.TSPropertySignature) return undefined;
    const name = propertyName(member);
    if (name === undefined || members.has(name)) return undefined;
    members.set(name, member);
    if (member.optional) optional.add(name);
  }
  return optional.size === 0 ? undefined : { members, optional };
}

/** Compare produced keys with the declared contract before inferring their tag relationship. */
function returnedProperties(
  objects: readonly TSESTree.ObjectExpression[],
  contract: ObjectContract,
): readonly ReadonlyMap<string, TSESTree.Node>[] | undefined {
  const returned: ReadonlyMap<string, TSESTree.Node>[] = [];
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
function objectProperties(object: TSESTree.ObjectExpression): ReadonlyMap<string, TSESTree.Node> | undefined {
  const properties = new Map<string, TSESTree.Node>();
  for (const property of object.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.kind !== "init" || property.method) return undefined;
    const name = propertyName(property);
    if (name === undefined || name === "__proto__" || properties.has(name) || property.value.type === AST_NODE_TYPES.AssignmentPattern) return undefined;
    properties.set(name, property.value);
  }
  return properties;
}

/** Explicitly empty values do not establish a useful required payload in a variant. */
function hasEmptyPayload(properties: ReadonlyMap<string, TSESTree.Node>, optional: ReadonlySet<string>): boolean {
  for (const name of optional) {
    const value = properties.get(name);
    if (value === undefined) continue;
    if (value.type === AST_NODE_TYPES.Literal && value.value === null) return true;
    if (value.type === AST_NODE_TYPES.Identifier && value.name === "undefined") return true;
    if (value.type === AST_NODE_TYPES.UnaryExpression && value.operator === "void") return true;
  }
  return false;
}

function tagDomain(node: TSESTree.TypeNode | undefined): ReadonlySet<Tag> | undefined {
  if (node?.type === AST_NODE_TYPES.TSBooleanKeyword) return new Set([true, false]);
  if (node?.type !== AST_NODE_TYPES.TSUnionType) return undefined;
  const values = new Set<Tag>();
  for (const member of node.types) {
    if (member.type !== AST_NODE_TYPES.TSLiteralType) return undefined;
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
  returned: readonly ReadonlyMap<string, TSESTree.Node>[],
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
function statementPaths(statement: TSESTree.Statement): ReturnPaths | undefined {
  switch (statement.type) {
    case AST_NODE_TYPES.ReturnStatement: {
      if (statement.argument === null) return undefined;
      const objects = returnedObjects(statement.argument);
      return objects === undefined ? undefined : { objects, fallsThrough: false };
    }
    case AST_NODE_TYPES.ThrowStatement: return { objects: [], fallsThrough: false };
    case AST_NODE_TYPES.BlockStatement: return blockPaths(statement);
    case AST_NODE_TYPES.IfStatement: {
      if (statement.test.type === AST_NODE_TYPES.Literal) return undefined;
      const consequent = statementPaths(statement.consequent);
      const alternate = statement.alternate === null ? { objects: [], fallsThrough: true } : statementPaths(statement.alternate);
      return consequent === undefined || alternate === undefined ? undefined : {
        objects: [...consequent.objects, ...alternate.objects],
        fallsThrough: consequent.fallsThrough || alternate.fallsThrough,
      };
    }
    case AST_NODE_TYPES.ExpressionStatement:
    case AST_NODE_TYPES.VariableDeclaration:
    case AST_NODE_TYPES.FunctionDeclaration:
    case AST_NODE_TYPES.EmptyStatement:
    case AST_NODE_TYPES.DebuggerStatement: return { objects: [], fallsThrough: true };
    default: return undefined;
  }
}

function blockPaths(block: TSESTree.BlockStatement): ReturnPaths | undefined {
  const objects: TSESTree.ObjectExpression[] = [];
  for (const statement of block.body) {
    const paths = statementPaths(statement);
    if (paths === undefined) return undefined;
    objects.push(...paths.objects);
    if (!paths.fallsThrough) return { objects, fallsThrough: false };
  }
  return { objects, fallsThrough: true };
}

function returnedObjects(expression: TSESTree.Expression): readonly TSESTree.ObjectExpression[] | undefined {
  if (expression.type === AST_NODE_TYPES.ObjectExpression) return [expression];
  if (expression.type !== AST_NODE_TYPES.ConditionalExpression || expression.test.type === AST_NODE_TYPES.Literal) return undefined;
  const consequent = returnedObjects(expression.consequent);
  const alternate = returnedObjects(expression.alternate);
  return consequent === undefined || alternate === undefined ? undefined : [...consequent, ...alternate];
}

function propertyName(node: TSESTree.Property | TSESTree.TSPropertySignature): string | undefined {
  if (node.computed) return undefined;
  if (node.key.type === AST_NODE_TYPES.Identifier) return node.key.name;
  if (node.key.type === AST_NODE_TYPES.Literal && typeof node.key.value === "string") return node.key.value;
  return undefined;
}

function literalTag(node: TSESTree.Node): Tag | undefined {
  if (node.type !== AST_NODE_TYPES.Literal) return undefined;
  return typeof node.value === "string" || typeof node.value === "number" || typeof node.value === "boolean"
    ? node.value : undefined;
}

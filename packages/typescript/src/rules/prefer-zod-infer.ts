/**
 * @fileoverview prefer-zod-infer — a hand-written type beside a Zod schema drifts silently the moment the schema gains a field.
 *
 * Port of the 18.x `prefer-zod-infer` rule. Same algorithm and visitors.
 * Oxlint sets absent optional fields (`typeParameters`, `typeArguments`,
 * `typeAnnotation`) to null where TS-ESTree leaves them undefined; the
 * original's `!== undefined` checks treat null as present, so under Oxlint it
 * never pairs a declaration. This port accepts both, as the original does under
 * ESLint.
 *
 * The typed companion `prefer-zod-parse-output-type` imports the exported
 * helpers.
 */

import type { FixFn } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { retainsNamedTypeUses } from "../utils/type-binding.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "prefer-zod-infer";

/** Absent optional AST field: undefined in TS-ESTree, null in Oxlint. */
function absent(value: unknown) {
  return value === undefined || value === null;
}

/** Chained methods that preserve a schema's inferred shape. */
const SHAPE_PRESERVING_METHODS: ReadonlySet<string> = new Set([
  "describe",
  "refine",
  "superRefine",
  "check",
  "meta",
  "register",
]);

/** Modifiers that make a member optional in the inferred type. */
const OPTIONAL_MODIFIERS: ReadonlySet<string> = new Set(["optional", "nullish"]);

/** Modifiers that admit `null`. */
const NULLABLE_MODIFIERS: ReadonlySet<string> = new Set(["nullable", "nullish"]);

/** Outer methods that preserve a static literal domain's inferred values. */
const DOMAIN_PRESERVING_MODIFIERS: ReadonlySet<string> = new Set([
  ...SHAPE_PRESERVING_METHODS,
  ...OPTIONAL_MODIFIERS,
  ...NULLABLE_MODIFIERS,
  "catch",
  "default",
  "prefault",
]);

/** Modifiers that replace the member's type outright. */
const RESHAPING_MODIFIERS: ReadonlySet<string> = new Set([
  "transform",
  "pipe",
  "preprocess",
  "brand",
  "overwrite",
  "readonly",
]);

/** Methods that reshape their receiver schema. */
const MODULE_LEVEL_RESHAPERS: ReadonlySet<string> = new Set(["transform", "pipe", "preprocess"]);

export function isPreferZodInferModuleReshaper(name: string): boolean {
  return MODULE_LEVEL_RESHAPERS.has(name);
}

/** Type names whose type arguments are hand-written types by construction. */
const ZOD_TYPE_CONSTRAINTS: ReadonlySet<string> = new Set([
  "ZodType",
  "ZodSchema",
  "ZodTypeAny",
  "ZodMiniType",
  "Schema",
]);

export function isPreferZodInferTypeConstraintName(name: string): boolean {
  return ZOD_TYPE_CONSTRAINTS.has(name);
}

/** Zod leaf constructors and the TS AST node their inferred type is written as. */
const LEAF_NODE_TYPES: Readonly<Record<string, readonly string[]>> = {
  string: ["TSStringKeyword"],
  email: ["TSStringKeyword"],
  url: ["TSStringKeyword"],
  uuid: ["TSStringKeyword"],
  ulid: ["TSStringKeyword"],
  cuid: ["TSStringKeyword"],
  cuid2: ["TSStringKeyword"],
  nanoid: ["TSStringKeyword"],
  iso: ["TSStringKeyword"],
  number: ["TSNumberKeyword"],
  int: ["TSNumberKeyword"],
  float32: ["TSNumberKeyword"],
  float64: ["TSNumberKeyword"],
  boolean: ["TSBooleanKeyword"],
  bigint: ["TSBigIntKeyword"],
  symbol: ["TSSymbolKeyword"],
  any: ["TSAnyKeyword"],
  unknown: ["TSUnknownKeyword"],
  never: ["TSNeverKeyword"],
  void: ["TSVoidKeyword"],
  null: ["TSNullKeyword"],
  undefined: ["TSUndefinedKeyword"],
  literal: ["TSLiteralType"],
  date: ["TSTypeReference"],
  array: ["TSArrayType", "TSTypeReference"],
  tuple: ["TSTupleType"],
  object: ["TSTypeLiteral", "TSTypeReference"],
  strictObject: ["TSTypeLiteral", "TSTypeReference"],
  looseObject: ["TSTypeLiteral", "TSTypeReference"],
  record: ["TSTypeReference", "TSTypeLiteral"],
  map: ["TSTypeReference"],
  set: ["TSTypeReference"],
  promise: ["TSTypeReference"],
  enum: ["TSUnionType", "TSTypeReference", "TSLiteralType"],
  nativeEnum: ["TSUnionType", "TSTypeReference", "TSLiteralType"],
  union: ["TSUnionType", "TSTypeReference"],
  discriminatedUnion: ["TSUnionType", "TSTypeReference"],
  intersection: ["TSIntersectionType", "TSTypeReference"],
};

/** Leaves whose values a static domain cannot list. */
const DYNAMIC_DOMAIN_LEAVES: ReadonlySet<string> = new Set(["nativeEnum", "union", "discriminatedUnion"]);

const NON_LEAF_COLLECTIONS: ReadonlySet<string> = new Set([
  "array", "tuple", "object", "strictObject", "looseObject", "record", "map", "set", "promise", "intersection",
]);

interface SchemaField {
  /** Exact primitive values for a static domain; null means domain values are dynamic. */
  readonly domain: ReadonlySet<string> | null | undefined;
  readonly optional: boolean;
  readonly nullable: boolean;
  /** The `z.<leaf>` constructor, or `null` when the member references another schema. */
  readonly leaf: string | null;
  readonly reshaped: boolean;
}

type TypeNode = ESTree.TSType;
type TwinDeclaration = ESTree.TSInterfaceDeclaration | ESTree.TSTypeAliasDeclaration;

function primitiveLiteralKey(node: Node): string | null {
  if (node.type !== "Literal") return null;
  const value = (node as { value: unknown }).value;
  if (value === null) return "null";
  switch (typeof value) {
    case "string":
      return `string:${value}`;
    case "number":
      return `number:${String(value)}`;
    case "boolean":
      return `boolean:${String(value)}`;
    case "bigint":
      return `bigint:${String(value)}`;
    default:
      return null;
  }
}

function exactDomain(keys: readonly (string | null)[]): ReadonlySet<string> | null {
  if (keys.length === 0 || keys.some((key) => key === null)) return null;
  const domain = new Set(keys as readonly string[]);
  return domain.size === keys.length ? domain : null;
}

/** Only const assertions preserve the literal types needed for enum inference. */
function enumLiteralExpression(node: Node): Node | null {
  if (node.type === "TSAsExpression") {
    const annotation = node.typeAnnotation;
    if (annotation.type !== "TSTypeReference" || annotation.typeName.type !== "Identifier" || annotation.typeName.name !== "const") return null;
    return enumLiteralExpression(node.expression);
  }
  if (node.type === "TSSatisfiesExpression" || node.type === "TSTypeAssertion") return null;
  return node;
}

/** `z.enum(["a", "b"] as const)` / `z.enum({ A: "a" })`: string values only. */
function enumCallDomain(call: ESTree.CallExpression): ReadonlySet<string> | null {
  const [writtenArgument] = call.arguments;
  if (writtenArgument === undefined || writtenArgument.type === "SpreadElement") return null;
  const argument = enumLiteralExpression(writtenArgument);
  if (argument?.type === "ArrayExpression") {
    return exactDomain(argument.elements.map((element) => {
      if (element === null || element.type === "SpreadElement") return null;
      const value = enumLiteralExpression(element);
      return value === null ? null : stringLiteralKey(value);
    }));
  }
  if (argument?.type === "ObjectExpression") {
    return exactDomain(argument.properties.map((property) =>
      property.type !== "Property" || property.computed || property.kind !== "init" || property.method || property.shorthand
        ? null
        : stringLiteralKey(property.value)));
  }
  return null;
}

function stringLiteralKey(node: Node): string | null {
  const key = primitiveLiteralKey(node);
  return key?.startsWith("string:") === true ? key : null;
}

function sameDomain(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  if (left.size !== right.size) return false;
  for (const value of left) {
    if (!right.has(value)) return false;
  }
  return true;
}

interface SchemaInfo {
  readonly name: string;
  readonly initializer: Node;
}

interface EnumSchemaInfo {
  readonly domain: ReadonlySet<string>;
  readonly name: string;
  readonly tokens: readonly string[];
}

interface InferredAliasInfo {
  readonly exported: boolean;
  readonly schemaName: string;
  readonly typeName: string;
}

interface LiteralUnionOccurrence {
  readonly domain: ReadonlySet<string>;
  readonly exported: boolean;
  readonly node: ESTree.TSUnionType;
  readonly owner: Node;
  readonly ownerName: string | null;
  readonly propertyName: string;
  readonly propertyTokens: readonly string[];
}

interface TypeMember {
  readonly optional: boolean;
  readonly nullable: boolean;
  readonly readonly: boolean;
  readonly annotation: TypeNode | null;
}

interface TypeDeclaration {
  readonly declaration: TwinDeclaration;
  readonly name: string;
  readonly node: Node;
}

interface RepeatedGroup {
  readonly alias: InferredAliasInfo;
  readonly occurrences: LiteralUnionOccurrence[];
  readonly schema: EnumSchemaInfo;
}

function isExportedDeclaration(node: Node): boolean {
  return parentOf(node)?.type === "ExportNamedDeclaration";
}

function isModuleLevelDeclaration(node: Node): boolean {
  const parent = parentOf(node);
  return parent?.type === "Program" ||
    (parent?.type === "ExportNamedDeclaration" && parentOf(parent)?.type === "Program");
}

export function isModuleLevelConst(node: ESTree.VariableDeclarator): boolean {
  const declaration = parentOf(node);
  return declaration?.type === "VariableDeclaration" && declaration.kind === "const" && isModuleLevelDeclaration(declaration);
}

/** `ZUserSchema` / `userSchema` / `ZUser` all describe the thing named `User`. */
function normalizeSchemaName(name: string): string {
  return name.replace(/Schema$/i, "").replace(/^Z(?=[A-Z])/, "").toLowerCase();
}

/** `UserType` is the same claim as `User`; nothing else is stripped. */
function normalizeTypeName(name: string): string {
  return name.replace(/Type$/, "").toLowerCase();
}

/** Strips `| null` / `| undefined` from a union and reports what it removed. */
function unwrapNullish(annotation: TypeNode): { readonly core: TypeNode | null; readonly nullable: boolean } {
  if (annotation.type !== "TSUnionType") {
    return { core: annotation, nullable: annotation.type === "TSNullKeyword" };
  }
  const rest: TypeNode[] = [];
  let nullable = false;
  for (const member of annotation.types) {
    if (member.type === "TSNullKeyword") {
      nullable = true;
      continue;
    }
    if (member.type === "TSUndefinedKeyword") continue;
    rest.push(member);
  }
  if (rest.length === 1) return { core: rest[0] ?? null, nullable };
  // A genuine union of two or more non-nullish members stays a union.
  return { core: rest.length === 0 ? null : annotation, nullable };
}

/** True only when the established rule owns this pair under its default options. */
export function preferZodInferOwnsDefaultTwin(input: {
  readonly constrained: boolean;
  readonly declaration: TwinDeclaration;
  readonly initializer: Node;
  readonly reshaped: boolean;
  readonly schemaName: string;
  readonly typeName: string;
  readonly zodNamespaces: ReadonlySet<string>;
}): boolean {
  if (input.constrained || input.reshaped || normalizeSchemaName(input.schemaName) !== normalizeTypeName(input.typeName)) {
    return false;
  }
  const fields = twinSchemaFields(input.initializer, input.zodNamespaces);
  const members = twinTypeMembers(input.declaration);
  if (fields === null || members === null || fields.size !== members.size) return false;
  for (const [name, field] of fields) {
    const member = members.get(name);
    if (
      member === undefined || field.reshaped || field.optional !== member.optional || field.nullable !== member.nullable ||
      member.readonly || leafAgrees(field, member.annotation) !== true
    ) {
      return false;
    }
  }
  return true;
}

/** Compares a TypeScript annotation with a known Zod leaf; `null` means unknown. */
function leafAgrees(field: SchemaField, annotation: TypeNode | null): boolean | null {
  if (field.domain === null) return false;
  if (field.domain !== undefined) {
    if (annotation === null) return false;
    const annotationDomain = typeLiteralDomain(annotation);
    return annotationDomain !== null && sameDomain(field.domain, annotationDomain);
  }
  const { leaf } = field;
  if (leaf !== null && NON_LEAF_COLLECTIONS.has(leaf)) return false;
  if (leaf === null || annotation === null) return null;
  const expected = LEAF_NODE_TYPES[leaf];
  if (expected === undefined) return null;
  const { core } = unwrapNullish(annotation);
  if (core === null) return null;
  if (leaf === "date") {
    return core.type === "TSTypeReference" && core.typeName.type === "Identifier" && core.typeName.name === "Date";
  }
  return expected.includes(core.type);
}

function typeLiteralDomain(annotation: TypeNode): ReadonlySet<string> | null {
  const members = annotation.type === "TSUnionType" ? annotation.types : [annotation];
  const keys: (string | null)[] = [];
  for (const member of members) {
    if (member.type === "TSNullKeyword") continue;
    if (member.type !== "TSLiteralType") return null;
    keys.push(primitiveLiteralKey(member.literal));
  }
  return exactDomain(keys);
}

function staticStringUnionDomain(node: TypeNode): ReadonlySet<string> | null {
  if (node.type !== "TSUnionType") return null;
  const keys = node.types.map((member) => member.type === "TSLiteralType" ? stringLiteralKey(member.literal) : null);
  const domain = exactDomain(keys);
  return domain !== null && domain.size >= 2 ? domain : null;
}

function twinCallChain(node: Node, zodNamespaces: ReadonlySet<string>): readonly ESTree.CallExpression[] | null {
  const chain: ESTree.CallExpression[] = [];
  let current: Node = unwrapExpression(node);
  while (current.type === "CallExpression") {
    const callee = unwrapExpression(current.callee);
    if (callee.type !== "MemberExpression" || getPropertyName(callee) === null) return null;
    const calleeReceiver = unwrapExpression(callee.object);
    chain.push(current);
    if (calleeReceiver.type === "Identifier") {
      return zodNamespaces.has(calleeReceiver.name) ? chain.reverse() : null;
    }
    current = calleeReceiver;
  }
  return null;
}

function twinMethodName(call: ESTree.CallExpression): string {
  const callee = unwrapExpression(call.callee);
  return callee.type === "MemberExpression" ? getPropertyName(callee) ?? "" : "";
}

function twinSchemaFields(initializer: Node, zodNamespaces: ReadonlySet<string>): ReadonlyMap<string, SchemaField> | null {
  const chain = twinCallChain(initializer, zodNamespaces);
  if (chain === null || chain.length === 0) return null;
  const [base, ...rest] = chain;
  if (base === undefined) return null;
  const baseMethod = twinMethodName(base);
  if (baseMethod !== "object" && baseMethod !== "strictObject") return null;
  if (rest.some((call) => !SHAPE_PRESERVING_METHODS.has(twinMethodName(call)))) return null;
  const shape = base.arguments[0] === undefined ? undefined : unwrapExpression(base.arguments[0]);
  if (shape === undefined || shape.type !== "ObjectExpression") return null;
  const fields = new Map<string, SchemaField>();
  for (const property of shape.properties) {
    if (property.type !== "Property") return null;
    const name = getPropertyName(property);
    if (name === null) return null;
    fields.set(name, twinSchemaField(property.value, zodNamespaces));
  }
  return fields.size === 0 ? null : fields;
}

function twinSchemaField(node: Node, zodNamespaces: ReadonlySet<string>): SchemaField {
  const modifiers: string[] = [];
  let current: Node = unwrapExpression(node);
  let leaf: string | null = null;
  let leafCall: ESTree.CallExpression | null = null;
  while (current.type === "CallExpression") {
    const callee = unwrapExpression(current.callee);
    if (callee.type !== "MemberExpression") break;
    const name = getPropertyName(callee);
    if (name === null) break;
    const receiver = unwrapExpression(callee.object);
    if (receiver.type === "Identifier" && zodNamespaces.has(receiver.name)) {
      leaf = name;
      leafCall = current;
      break;
    }
    modifiers.push(name);
    current = receiver;
  }
  return {
    domain: modifiers.every((name) => DOMAIN_PRESERVING_MODIFIERS.has(name)) ? staticZodDomain(leaf, leafCall) : null,
    leaf,
    optional: modifiers.some((name) => OPTIONAL_MODIFIERS.has(name)),
    nullable: modifiers.some((name) => NULLABLE_MODIFIERS.has(name)),
    reshaped: modifiers.some((name) => RESHAPING_MODIFIERS.has(name)),
  };
}

function staticZodDomain(leaf: string | null, call: ESTree.CallExpression | null): ReadonlySet<string> | null | undefined {
  if (leaf === null || call === null) return undefined;
  if (leaf === "literal") return literalCallDomain(call);
  if (leaf === "enum") return enumCallDomain(call);
  return DYNAMIC_DOMAIN_LEAVES.has(leaf) ? null : undefined;
}

/** `z.literal("a")` / `z.literal(["a", 1])`. */
function literalCallDomain(call: ESTree.CallExpression): ReadonlySet<string> | null {
  const [argument] = call.arguments;
  if (argument === undefined || argument.type === "SpreadElement") return null;
  if (argument.type !== "ArrayExpression") return exactDomain([primitiveLiteralKey(argument)]);
  return exactDomain(argument.elements.map((element) =>
    element === null || element.type === "SpreadElement" ? null : primitiveLiteralKey(element)));
}

function twinTypeMembers(declaration: TwinDeclaration): ReadonlyMap<string, TypeMember> | null {
  const members = twinMemberSignatures(declaration);
  if (members === null) return null;
  const result = new Map<string, TypeMember>();
  for (const member of members) {
    if (member.type !== "TSPropertySignature" || member.computed) return null;
    const name = staticFieldName(member.key);
    if (name === null) return null;
    const annotation = member.typeAnnotation?.typeAnnotation ?? null;
    result.set(name, {
      optional: member.optional === true,
      nullable: annotation !== null && unwrapNullish(annotation).nullable,
      readonly: member.readonly === true,
      annotation,
    });
  }
  return result.size === 0 ? null : result;
}

/** The members of a non-generic interface without `extends`, or of a non-generic type literal alias. */
function twinMemberSignatures(declaration: TwinDeclaration): readonly ESTree.TSSignature[] | null {
  if (!absent(declaration.typeParameters)) return null;
  if (declaration.type === "TSInterfaceDeclaration") return (declaration.extends?.length ?? 0) > 0 ? null : declaration.body.body;
  return declaration.typeAnnotation.type === "TSTypeLiteral" ? declaration.typeAnnotation.members : null;
}

function nameTokens(name: string): readonly string[] {
  return name
    .replace(/([a-z\d])([A-Z])/gu, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/gu, "$1 $2")
    .split(/[^A-Za-z\d]+/u)
    .filter((token) => token !== "")
    .map((token) => token.toLowerCase());
}

function schemaNameTokens(name: string): readonly string[] {
  const tokens = nameTokens(name);
  const withoutPrefix = tokens[0] === "z" ? tokens.slice(1) : tokens;
  return withoutPrefix.at(-1) === "schema" ? withoutPrefix.slice(0, -1) : withoutPrefix;
}

function endsWithTokens(candidate: readonly string[], suffix: readonly string[]): boolean {
  return suffix.length >= 2 && candidate.length >= suffix.length &&
    suffix.every((segment, index) => candidate[candidate.length - suffix.length + index] === segment);
}

function staticFieldName(key: Node): string | null {
  if (key.type === "Identifier") return key.name;
  const value = key.type === "Literal" ? (key as { value: unknown }).value : null;
  return typeof value === "string" ? value : null;
}

export function collectConstrainedNames(node: TypeNode, names: Set<string>): void {
  if (node.type === "TSTypeReference") {
    if (node.typeName.type === "Identifier") names.add(node.typeName.name);
    for (const argument of node.typeArguments?.params ?? []) collectConstrainedNames(argument, names);
    return;
  }
  if (node.type === "TSArrayType") {
    collectConstrainedNames(node.elementType, names);
    return;
  }
  if (node.type === "TSUnionType" || node.type === "TSIntersectionType") {
    for (const member of node.types) collectConstrainedNames(member, names);
  }
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    fixable: "code",
    docs: {
      description: "Derive a type from its Zod schema with `z.infer` instead of hand-writing a twin declaration beside it.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          ignoreTypeNames: {
            description: "Regular expression patterns for type names to leave unchanged.",
            type: "array",
            items: { type: "string" },
          },
          requireIdenticalShape: {
            description: "Require the schema output and declared type to have identical property shapes.",
            type: "boolean",
          },
        },
      },
    ],
    messages: {
      handWrittenTwin:
        "`{{typeName}}` restates the shape of the Zod schema `{{schemaName}}` declared in this module. Derive it instead — `type {{typeName}} = z.infer<typeof {{schemaName}}>` — so a field added to the schema cannot silently leave the type behind.",
      repeatedEnumUnion:
        "`{{propertyName}}` repeats the literal domain already named by `{{typeName}}` and `{{schemaName}}` in multiple object types. Reuse `{{typeName}}` so the accepted values have one source of truth.",
    },
  },
  createOnce(context) {
    let ignorePatterns: RegExp[] = [];
    let requireIdenticalShape = true;
    let zodNamespaces = new Set<string>();
    let schemas: SchemaInfo[] = [];
    let enumSchemas: EnumSchemaInfo[] = [];
    let inferredAliases: InferredAliasInfo[] = [];
    let literalUnionOccurrences: LiteralUnionOccurrence[] = [];
    let typeDeclarations: TypeDeclaration[] = [];
    let enumTypeDeclarations: { readonly node: ESTree.TSTypeAliasDeclaration; readonly domain: ReadonlySet<string> }[] = [];
    /** Names intentionally constraining a `z.ZodType<...>`. */
    let constrainedTypeNames = new Set<string>();
    /** Schemas reshaped elsewhere in this module. */
    let reshapedSchemaNames = new Set<string>();

    function recordZodImport(node: ESTree.ImportDeclaration): void {
      if (!isZodModule(node.source.value)) return;
      for (const specifier of node.specifiers) {
        if (
          specifier.type === "ImportNamespaceSpecifier" || specifier.type === "ImportDefaultSpecifier" ||
          (specifier.type === "ImportSpecifier" && importSpecifierName(specifier) === "z")
        ) {
          zodNamespaces.add(specifier.local.name);
        }
      }
    }

    /** Extracts an exact, direct module-level `z.enum([…])` domain. */
    function enumSchemaDomain(init: Node): ReadonlySet<string> | null {
      if (init.type !== "CallExpression") return null;
      const chain = twinCallChain(init, zodNamespaces);
      if (chain === null || chain.length !== 1) return null;
      const [call] = chain;
      if (call === undefined || !absent(call.typeArguments) || twinMethodName(call) !== "enum") return null;
      const receiver = call.callee.type === "MemberExpression" ? call.callee.object : null;
      if (receiver?.type !== "Identifier" || !isImportBinding(receiver)) return null;
      const domain = enumCallDomain(call);
      return domain !== null && domain.size >= 2 ? domain : null;
    }

    function isImportBinding(identifier: Extract<Node, { type: "Identifier" }>): boolean {
      const binding = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      return binding?.defs.length === 1 && binding.defs[0]?.type === "ImportBinding";
    }

    /** Finds `z.infer<typeof Schema>` without relying on type services. */
    function inferredSchemaName(node: TypeNode): string | null {
      if (
        node.type !== "TSTypeReference" || node.typeName.type !== "TSQualifiedName" ||
        node.typeName.left.type !== "Identifier" || !zodNamespaces.has(node.typeName.left.name) ||
        node.typeName.right.name !== "infer"
      ) {
        return null;
      }
      const arguments_ = node.typeArguments?.params ?? [];
      const [argument] = arguments_;
      return arguments_.length === 1 && argument?.type === "TSTypeQuery" && argument.exprName.type === "Identifier"
        ? argument.exprName.name
        : null;
    }

    function recordLiteralUnions(members: readonly ESTree.TSSignature[], owner: Node, ownerName: string, exported: boolean): void {
      for (const member of members) {
        if (member.type !== "TSPropertySignature" || member.computed || member.optional || member.readonly || absent(member.typeAnnotation)) {
          continue;
        }
        const propertyName = staticFieldName(member.key);
        if (propertyName === null) continue;
        const propertyTokens = nameTokens(propertyName);
        if (propertyTokens.length < 2) continue;
        const annotation = member.typeAnnotation.typeAnnotation;
        const domain = staticStringUnionDomain(annotation);
        if (domain === null || annotation.type !== "TSUnionType") continue;
        literalUnionOccurrences.push({ domain, exported, node: annotation, owner, ownerName, propertyName, propertyTokens });
      }
    }

    function ignoredTypeName(name: string): boolean {
      return ignorePatterns.some((pattern) => pattern.test(name));
    }

    function reportTwins(): Set<string> {
      const twinTypeNames = new Set<string>();
      const byName = new Map<string, SchemaInfo>();
      for (const schema of schemas) {
        const key = normalizeSchemaName(schema.name);
        if (key !== "" && !byName.has(key)) byName.set(key, schema);
      }
      for (const declaration of typeDeclarations) {
        const schema = twinSchema(declaration, byName);
        if (schema === null) continue;
        twinTypeNames.add(declaration.name);
        const fix = twinFix(declaration, schema);
        context.report({
          node: declaration.node,
          messageId: "handWrittenTwin",
          ...(fix !== null && { fix }),
          data: { typeName: declaration.name, schemaName: schema.name },
        });
      }
      return twinTypeNames;
    }

    /** Replaces an unobserved private twin with `z.infer` through the schema's imported namespace. */
    function twinFix(declaration: TypeDeclaration, schema: SchemaInfo): FixFn | null {
      if (!requireIdenticalShape) return null;
      const sourceCode = context.sourceCode;
      const base = twinCallChain(schema.initializer, zodNamespaces)?.[0];
      const callee = base === undefined ? null : unwrapExpression(base.callee);
      const namespace = callee?.type === "MemberExpression" ? unwrapExpression(callee.object) : null;
      if (namespace?.type !== "Identifier") return null;
      const twin = declaration.declaration;
      if (!isImportBinding(namespace) ||
        !isUnusedPrivateBinding(sourceCode, twin, twin.id, context.filename) ||
        sourceCode.getCommentsInside(twin).length > 0 || !retainsNamedTypeUses(sourceCode, twin)) return null;
      return (fixer) => fixer.replaceText(twin,
        `type ${sourceCode.getText(twin.id)} = ${sourceCode.getText(namespace)}.infer<typeof ${schema.name}>;`);
    }

    /** The module schema this declaration restates, when the pair is reported. */
    function twinSchema(declaration: TypeDeclaration, byName: ReadonlyMap<string, SchemaInfo>): SchemaInfo | null {
      if (constrainedTypeNames.has(declaration.name) || ignoredTypeName(declaration.name)) return null;
      const schema = byName.get(normalizeTypeName(declaration.name));
      if (schema === undefined || reshapedSchemaNames.has(schema.name)) return null;
      if (!requireIdenticalShape) return schema;
      return preferZodInferOwnsDefaultTwin({
        constrained: false,
        declaration: declaration.declaration,
        initializer: schema.initializer,
        reshaped: false,
        schemaName: schema.name,
        typeName: declaration.name,
        zodNamespaces,
      }) ? schema : null;
    }

    function reportEnumTwins(): void {
      for (const { node, domain } of enumTypeDeclarations) {
        if (constrainedTypeNames.has(node.id.name) || ignoredTypeName(node.id.name)) continue;
        const typeKey = normalizeTypeName(node.id.name);
        const candidates = enumSchemas.filter((schema) =>
          normalizeSchemaName(schema.name) === typeKey && !reshapedSchemaNames.has(schema.name) && sameDomain(schema.domain, domain));
        const [schema] = candidates;
        if (candidates.length !== 1 || schema === undefined) continue;
        context.report({ node: node.id, messageId: "handWrittenTwin", data: { typeName: node.id.name, schemaName: schema.name } });
      }
    }

    function reportRepeatedUnions(twinTypeNames: ReadonlySet<string>): void {
      const aliasesBySchema = new Map<string, InferredAliasInfo[]>();
      for (const alias of inferredAliases) {
        const aliases = aliasesBySchema.get(alias.schemaName) ?? [];
        aliases.push(alias);
        aliasesBySchema.set(alias.schemaName, aliases);
      }
      const groups = new Map<string, RepeatedGroup>();
      for (const occurrence of literalUnionOccurrences) {
        const { ownerName } = occurrence;
        if (twinTypeNames.has(ownerName ?? "") || (ownerName !== null && ignoredTypeName(ownerName))) continue;
        const source = repeatedUnionSource(occurrence, aliasesBySchema);
        if (source === null) continue;
        const key = `${source.schema.name}\0${occurrence.propertyName}`;
        const group = groups.get(key);
        if (group === undefined) groups.set(key, { ...source, occurrences: [occurrence] });
        else group.occurrences.push(occurrence);
      }
      for (const { alias, occurrences, schema } of groups.values()) {
        // A repeat needs two distinct owners, by name and by node.
        const [first] = occurrences;
        if (first === undefined || new Set(occurrences.map(({ ownerName }) => ownerName)).size < 2 ||
          new Set(occurrences.map(({ owner }) => owner)).size < 2) continue;
        context.report({
          node: first.node,
          messageId: "repeatedEnumUnion",
          data: { propertyName: first.propertyName, schemaName: schema.name, typeName: alias.typeName },
        });
      }
    }

    /** The one enum schema, named by one inferred alias, whose domain this property union repeats. */
    function repeatedUnionSource(
      occurrence: LiteralUnionOccurrence,
      aliasesBySchema: ReadonlyMap<string, readonly InferredAliasInfo[]>,
    ): { readonly alias: InferredAliasInfo; readonly schema: EnumSchemaInfo } | null {
      const candidates = enumSchemas.filter((schema) =>
        sameDomain(schema.domain, occurrence.domain) && endsWithTokens(schema.tokens, occurrence.propertyTokens) &&
        (aliasesBySchema.get(schema.name)?.length ?? 0) === 1);
      const [schema] = candidates;
      if (candidates.length !== 1 || schema === undefined) return null;
      const [alias] = aliasesBySchema.get(schema.name) ?? [];
      // An exported contract cannot reuse a module-private alias.
      if (alias === undefined || (occurrence.exported && !alias.exported)) return null;
      return { alias, schema };
    }

    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isStoryFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        const options = context.options[0] as { readonly ignoreTypeNames?: readonly string[]; readonly requireIdenticalShape?: boolean } | undefined;
        ignorePatterns = (options?.ignoreTypeNames ?? []).map((source) => new RegExp(source, "u"));
        requireIdenticalShape = options?.requireIdenticalShape ?? true;
        zodNamespaces = new Set();
        schemas = [];
        enumSchemas = [];
        inferredAliases = [];
        literalUnionOccurrences = [];
        typeDeclarations = [];
        enumTypeDeclarations = [];
        constrainedTypeNames = new Set();
        reshapedSchemaNames = new Set();
        return undefined;
      },

      Program(node) {
        // Pre-index imports so legal import declarations placed after a schema
        // do not make recognition depend on traversal order.
        for (const statement of node.body) {
          if (statement.type === "ImportDeclaration") recordZodImport(statement);
        }
      },

      ImportDeclaration(node) {
        recordZodImport(node);
      },

      VariableDeclarator(node) {
        if (node.id.type !== "Identifier" || node.init === null || !isModuleLevelConst(node)) return;
        if (twinSchemaFields(node.init, zodNamespaces) !== null) schemas.push({ name: node.id.name, initializer: node.init });
        if (absent(node.id.typeAnnotation)) {
          const domain = enumSchemaDomain(node.init);
          if (domain !== null) enumSchemas.push({ domain, name: node.id.name, tokens: schemaNameTokens(node.id.name) });
        }
      },

      /** Records `XSchema.transform(...)` and equivalent module-level reshaping. */
      MemberExpression(node) {
        if (node.object.type !== "Identifier") return;
        const name = getPropertyName(node);
        if (name !== null && isPreferZodInferModuleReshaper(name)) reshapedSchemaNames.add(node.object.name);
      },

      /** Records every type argument carried by a Zod constraint. */
      TSTypeReference(node) {
        const { typeName } = node;
        const referenced = typeName.type === "Identifier"
          ? typeName.name
          : typeName.type === "TSQualifiedName" && typeName.right.type === "Identifier" ? typeName.right.name : null;
        if (referenced === null || !isPreferZodInferTypeConstraintName(referenced)) return;
        for (const argument of node.typeArguments?.params ?? []) collectConstrainedNames(argument, constrainedTypeNames);
      },

      TSInterfaceDeclaration(node) {
        if (!isModuleLevelDeclaration(node)) return;
        // Generics and `extends` cannot be replaced by direct schema inference.
        if (!absent(node.typeParameters) || (node.extends?.length ?? 0) > 0) return;
        if (twinTypeMembers(node) !== null) typeDeclarations.push({ declaration: node, name: node.id.name, node: node.id });
        recordLiteralUnions(node.body.body, node, node.id.name, isExportedDeclaration(node));
      },

      TSTypeAliasDeclaration(node) {
        if (!isModuleLevelDeclaration(node)) return;
        const generic = !absent(node.typeParameters);
        const enumDomain = generic ? null : staticStringUnionDomain(node.typeAnnotation);
        if (enumDomain !== null) enumTypeDeclarations.push({ node, domain: enumDomain });
        const schemaName = inferredSchemaName(node.typeAnnotation);
        if (schemaName !== null) {
          inferredAliases.push({ exported: isExportedDeclaration(node), schemaName, typeName: node.id.name });
        }
        if (generic || node.typeAnnotation.type !== "TSTypeLiteral") return;
        if (twinTypeMembers(node) !== null) typeDeclarations.push({ declaration: node, name: node.id.name, node: node.id });
        recordLiteralUnions(node.typeAnnotation.members, node, node.id.name, isExportedDeclaration(node));
      },

      "Program:exit"() {
        const twinTypeNames = reportTwins();
        reportEnumTwins();
        reportRepeatedUnions(twinTypeNames);
      },
    };
  },
});

/**
 * @fileoverview prefer-zod-infer — a hand-written type beside a Zod schema drifts silently the moment the schema gains a field.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-zod-infer.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "handWrittenTwin" | "repeatedEnumUnion";
type Options = readonly [
  {
    ignoreTypeNames?: readonly string[];
    requireIdenticalShape?: boolean;
  }?,
];

export const PREFER_ZOD_INFER_DOCUMENTATION = {
  summary: "Derive a type from its Zod schema with `z.infer` instead of hand-writing a twin declaration beside it.",
  rationale: "A derived type stays synchronized when the runtime schema changes.",
  remediation: "Replace the hand-written twin with `z.infer<typeof Schema>`.",
  category: "correctness",
  limitations: [
    "Only module-level const schemas and module-level type declarations are paired; local declarations are excluded rather than matched by spelling across scopes.",
    "By default every field must positively agree; collection, nested-object and referenced-schema equivalence is not inferred from outer syntax alone.",
    "This is a bounded syntactic comparison, not general type equivalence. Review schema input versus output, interface augmentation, and separately evolving domain contracts before replacing a declaration.",
  ],
  examples: [
    { id: "inferred-type", title: "Infer the schema type", outcome: "no-match", files: [{ path: "src/user.ts", source: 'import { z } from "zod"; const UserSchema = z.object({ id: z.string() }); type User = z.infer<typeof UserSchema>;' }], focusPath: "src/user.ts", expectedCount: 0, public: true },
    { id: "handwritten-twin", title: "Do not duplicate the schema shape", outcome: "match", files: [{ path: "src/user.ts", source: 'import { z } from "zod"; const UserSchema = z.object({ id: z.string() }); interface User { id: string }' }], focusPath: "src/user.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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
const OPTIONAL_MODIFIERS: ReadonlySet<string> = new Set([
  "optional",
  "nullish",
]);

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
const MODULE_LEVEL_RESHAPERS: ReadonlySet<string> = new Set([
  "transform",
  "pipe",
  "preprocess",
]);

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
const LEAF_NODE_TYPES: Readonly<Record<string, readonly AST_NODE_TYPES[]>> = {
  string: [AST_NODE_TYPES.TSStringKeyword],
  email: [AST_NODE_TYPES.TSStringKeyword],
  url: [AST_NODE_TYPES.TSStringKeyword],
  uuid: [AST_NODE_TYPES.TSStringKeyword],
  ulid: [AST_NODE_TYPES.TSStringKeyword],
  cuid: [AST_NODE_TYPES.TSStringKeyword],
  cuid2: [AST_NODE_TYPES.TSStringKeyword],
  nanoid: [AST_NODE_TYPES.TSStringKeyword],
  iso: [AST_NODE_TYPES.TSStringKeyword],
  number: [AST_NODE_TYPES.TSNumberKeyword],
  int: [AST_NODE_TYPES.TSNumberKeyword],
  float32: [AST_NODE_TYPES.TSNumberKeyword],
  float64: [AST_NODE_TYPES.TSNumberKeyword],
  boolean: [AST_NODE_TYPES.TSBooleanKeyword],
  bigint: [AST_NODE_TYPES.TSBigIntKeyword],
  symbol: [AST_NODE_TYPES.TSSymbolKeyword],
  any: [AST_NODE_TYPES.TSAnyKeyword],
  unknown: [AST_NODE_TYPES.TSUnknownKeyword],
  never: [AST_NODE_TYPES.TSNeverKeyword],
  void: [AST_NODE_TYPES.TSVoidKeyword],
  null: [AST_NODE_TYPES.TSNullKeyword],
  undefined: [AST_NODE_TYPES.TSUndefinedKeyword],
  literal: [AST_NODE_TYPES.TSLiteralType],
  date: [AST_NODE_TYPES.TSTypeReference],
  array: [AST_NODE_TYPES.TSArrayType, AST_NODE_TYPES.TSTypeReference],
  tuple: [AST_NODE_TYPES.TSTupleType],
  object: [AST_NODE_TYPES.TSTypeLiteral, AST_NODE_TYPES.TSTypeReference],
  strictObject: [AST_NODE_TYPES.TSTypeLiteral, AST_NODE_TYPES.TSTypeReference],
  looseObject: [AST_NODE_TYPES.TSTypeLiteral, AST_NODE_TYPES.TSTypeReference],
  record: [AST_NODE_TYPES.TSTypeReference, AST_NODE_TYPES.TSTypeLiteral],
  map: [AST_NODE_TYPES.TSTypeReference],
  set: [AST_NODE_TYPES.TSTypeReference],
  promise: [AST_NODE_TYPES.TSTypeReference],
  enum: [AST_NODE_TYPES.TSUnionType, AST_NODE_TYPES.TSTypeReference, AST_NODE_TYPES.TSLiteralType],
  nativeEnum: [AST_NODE_TYPES.TSUnionType, AST_NODE_TYPES.TSTypeReference, AST_NODE_TYPES.TSLiteralType],
  union: [AST_NODE_TYPES.TSUnionType, AST_NODE_TYPES.TSTypeReference],
  discriminatedUnion: [AST_NODE_TYPES.TSUnionType, AST_NODE_TYPES.TSTypeReference],
  intersection: [AST_NODE_TYPES.TSIntersectionType, AST_NODE_TYPES.TSTypeReference],
};

interface SchemaField {
  /** Exact primitive values for a static domain; null means domain values are dynamic. */
  readonly domain: ReadonlySet<string> | null | undefined;
  readonly optional: boolean;
  readonly nullable: boolean;
  /** The `z.<leaf>` constructor, or `null` when the member references another schema. */
  readonly leaf: string | null;
  readonly reshaped: boolean;
}

function primitiveLiteralKey(node: TSESTree.Node): string | null {
  if (node.type !== AST_NODE_TYPES.Literal) {
    return null;
  }
  if (node.value === null) {
    return "null";
  }
  switch (typeof node.value) {
    case "string":
      return `string:${node.value}`;
    case "number":
      return `number:${String(node.value)}`;
    case "boolean":
      return `boolean:${String(node.value)}`;
    case "bigint":
      return `bigint:${String(node.value)}`;
    default:
      return null;
  }
}

function exactDomain(keys: readonly (string | null)[]): ReadonlySet<string> | null {
  if (keys.length === 0 || keys.some((key) => key === null)) {
    return null;
  }
  const domain = new Set(keys as readonly string[]);
  return domain.size === keys.length ? domain : null;
}

function staticZodDomain(
  leaf: string | null,
  call: TSESTree.CallExpression | null,
): ReadonlySet<string> | null | undefined {
  if (leaf === null || call === null) {
    return undefined;
  }
  if (leaf === "literal") {
    const [argument] = call.arguments;
    if (argument === undefined || argument.type === AST_NODE_TYPES.SpreadElement) {
      return null;
    }
    if (argument.type === AST_NODE_TYPES.ArrayExpression) {
      return exactDomain(
        argument.elements.map((element) =>
          element === null || element.type === AST_NODE_TYPES.SpreadElement
            ? null
            : primitiveLiteralKey(element),
        ),
      );
    }
    return exactDomain([primitiveLiteralKey(argument)]);
  }
  if (leaf === "enum") {
    const [argument] = call.arguments;
    if (argument === undefined || argument.type === AST_NODE_TYPES.SpreadElement) {
      return null;
    }
    if (argument.type === AST_NODE_TYPES.ArrayExpression) {
      return exactDomain(
        argument.elements.map((element) => {
          if (element === null || element.type === AST_NODE_TYPES.SpreadElement) {
            return null;
          }
          const key = primitiveLiteralKey(element);
          return key?.startsWith("string:") === true ? key : null;
        }),
      );
    }
    if (argument.type === AST_NODE_TYPES.ObjectExpression) {
      return exactDomain(
        argument.properties.map((property) => {
          if (
            property.type !== AST_NODE_TYPES.Property ||
            property.computed ||
            property.kind !== "init" ||
            property.method ||
            property.shorthand
          ) {
            return null;
          }
          const key = primitiveLiteralKey(property.value);
          return key?.startsWith("string:") === true ? key : null;
        }),
      );
    }
    return null;
  }
  if (leaf === "nativeEnum" || leaf === "union" || leaf === "discriminatedUnion") {
    return null;
  }
  return undefined;
}

function sameDomain(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  if (left.size !== right.size) {
    return false;
  }
  for (const value of left) {
    if (!right.has(value)) {
      return false;
    }
  }
  return true;
}

interface SchemaInfo {
  readonly name: string;
  readonly fields: ReadonlyMap<string, SchemaField>;
  readonly initializer: TSESTree.Node;
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
  readonly node: TSESTree.TSUnionType;
  readonly owner: TSESTree.Node;
  readonly ownerName: string | null;
  readonly propertyName: string;
  readonly propertyTokens: readonly string[];
}

interface TypeMember {
  readonly optional: boolean;
  readonly nullable: boolean;
  readonly readonly: boolean;
  readonly annotation: TSESTree.TypeNode | null;
}

interface TypeDeclaration {
  readonly declaration: TSESTree.TSInterfaceDeclaration | TSESTree.TSTypeAliasDeclaration;
  readonly name: string;
  readonly node: TSESTree.Node;
  readonly members: ReadonlyMap<string, TypeMember>;
}

function isExportedDeclaration(node: TSESTree.Node): boolean {
  return node.parent?.type === AST_NODE_TYPES.ExportNamedDeclaration;
}

function isModuleLevelDeclaration(node: TSESTree.Node): boolean {
  const parent = node.parent;
  return parent?.type === AST_NODE_TYPES.Program ||
    (parent?.type === AST_NODE_TYPES.ExportNamedDeclaration && parent.parent.type === AST_NODE_TYPES.Program);
}

function isModuleLevelConst(node: TSESTree.VariableDeclarator): boolean {
  const declaration = node.parent;
  if (
    declaration.type !== AST_NODE_TYPES.VariableDeclaration ||
    declaration.kind !== "const"
  ) {
    return false;
  }
  const container = declaration.parent;
  return (
    container.type === AST_NODE_TYPES.Program ||
    (container.type === AST_NODE_TYPES.ExportNamedDeclaration &&
      container.parent.type === AST_NODE_TYPES.Program)
  );
}

/** `ZUserSchema` / `userSchema` / `ZUser` all describe the thing named `User`. */
export function normalizeSchemaName(name: string): string {
  return name
    .replace(/Schema$/i, "")
    .replace(/^Z(?=[A-Z])/, "")
    .toLowerCase();
}

/** `UserType` is the same claim as `User`; nothing else is stripped. */
export function normalizeTypeName(name: string): string {
  return name.replace(/Type$/, "").toLowerCase();
}

/** Strips `| null` / `| undefined` from a union and reports what it removed. */
function unwrapNullish(annotation: TSESTree.TypeNode): {
  readonly core: TSESTree.TypeNode | null;
  readonly nullable: boolean;
} {
  if (annotation.type !== AST_NODE_TYPES.TSUnionType) {
    return {
      core: annotation,
      nullable: annotation.type === AST_NODE_TYPES.TSNullKeyword,
    };
  }
  const rest: TSESTree.TypeNode[] = [];
  let nullable = false;
  for (const member of annotation.types) {
    if (member.type === AST_NODE_TYPES.TSNullKeyword) {
      nullable = true;
      continue;
    }
    if (member.type === AST_NODE_TYPES.TSUndefinedKeyword) {
      continue;
    }
    rest.push(member);
  }
  if (rest.length === 1) {
    return { core: rest[0] ?? null, nullable };
  }
  // A genuine union of two or more non-nullish members stays a union.
  return { core: rest.length === 0 ? null : annotation, nullable };
}

/** True only when the established rule owns this pair under its default options. */
export function preferZodInferOwnsDefaultTwin(input: {
  readonly constrained: boolean;
  readonly declaration: TSESTree.TSInterfaceDeclaration | TSESTree.TSTypeAliasDeclaration;
  readonly initializer: TSESTree.Node;
  readonly reshaped: boolean;
  readonly schemaName: string;
  readonly typeName: string;
  readonly zodNamespaces: ReadonlySet<string>;
}): boolean {
  if (
    input.constrained ||
    input.reshaped ||
    normalizeSchemaName(input.schemaName) !== normalizeTypeName(input.typeName)
  ) {
    return false;
  }
  const fields = twinSchemaFields(input.initializer, input.zodNamespaces);
  const members = twinTypeMembers(input.declaration);
  if (fields === null || members === null || fields.size !== members.size) return false;
  for (const [name, field] of fields) {
    const member = members.get(name);
    if (
      member === undefined ||
      field.reshaped ||
      field.optional !== member.optional ||
      field.nullable !== member.nullable ||
      member.readonly ||
      leafAgrees(field, member.annotation) !== true
    ) {
      return false;
    }
  }
  return true;
}

/** Compares a TypeScript annotation with a known Zod leaf; `null` means unknown. */
function leafAgrees(
  field: SchemaField,
  annotation: TSESTree.TypeNode | null,
): boolean | null {
  if (field.domain === null) {
    return false;
  }
  if (field.domain !== undefined) {
    if (annotation === null) {
      return false;
    }
    const annotationDomain = typeLiteralDomain(annotation);
    return annotationDomain !== null && sameDomain(field.domain, annotationDomain);
  }
  const { leaf } = field;
  if (leaf !== null && ["array", "tuple", "object", "strictObject", "looseObject", "record", "map", "set", "promise", "intersection"].includes(leaf)) {
    return false;
  }
  if (leaf === null || annotation === null) {
    return null;
  }
  const expected = LEAF_NODE_TYPES[leaf];
  if (expected === undefined) {
    return null;
  }
  const { core } = unwrapNullish(annotation);
  if (core === null) {
    return null;
  }
  if (leaf === "date") {
    return (
      core.type === AST_NODE_TYPES.TSTypeReference &&
      core.typeName.type === AST_NODE_TYPES.Identifier &&
      core.typeName.name === "Date"
    );
  }
  return expected.includes(core.type);
}

function typeLiteralDomain(annotation: TSESTree.TypeNode): ReadonlySet<string> | null {
  const members =
    annotation.type === AST_NODE_TYPES.TSUnionType
      ? annotation.types
      : [annotation];
  const keys: (string | null)[] = [];
  for (const member of members) {
    if (member.type === AST_NODE_TYPES.TSNullKeyword) {
      continue;
    }
    if (member.type !== AST_NODE_TYPES.TSLiteralType) {
      return null;
    }
    keys.push(primitiveLiteralKey(member.literal));
  }
  return exactDomain(keys);
}

function staticStringUnionDomain(
  node: TSESTree.TypeNode,
): ReadonlySet<string> | null {
  if (node.type !== AST_NODE_TYPES.TSUnionType) {
    return null;
  }
  const keys = node.types.map((member) => {
    if (member.type !== AST_NODE_TYPES.TSLiteralType) {
      return null;
    }
    const key = primitiveLiteralKey(member.literal);
    return key?.startsWith("string:") === true ? key : null;
  });
  const domain = exactDomain(keys);
  return domain !== null && domain.size >= 2 ? domain : null;
}

function twinCallChain(
  node: TSESTree.Node,
  zodNamespaces: ReadonlySet<string>,
): readonly TSESTree.CallExpression[] | null {
  const chain: TSESTree.CallExpression[] = [];
  let current: TSESTree.Node = node;
  while (current.type === AST_NODE_TYPES.CallExpression) {
    const callee = current.callee;
    if (
      callee.type !== AST_NODE_TYPES.MemberExpression ||
      callee.computed ||
      callee.property.type !== AST_NODE_TYPES.Identifier
    ) {
      return null;
    }
    chain.push(current);
    if (callee.object.type === AST_NODE_TYPES.Identifier) {
      return zodNamespaces.has(callee.object.name) ? chain.reverse() : null;
    }
    current = callee.object;
  }
  return null;
}

function twinMethodName(call: TSESTree.CallExpression): string {
  const callee = call.callee;
  return callee.type === AST_NODE_TYPES.MemberExpression &&
    callee.property.type === AST_NODE_TYPES.Identifier
    ? callee.property.name
    : "";
}

function twinSchemaFields(
  initializer: TSESTree.Node,
  zodNamespaces: ReadonlySet<string>,
): ReadonlyMap<string, SchemaField> | null {
  const chain = twinCallChain(initializer, zodNamespaces);
  if (chain === null || chain.length === 0) return null;
  const [base, ...rest] = chain;
  if (base === undefined) return null;
  const baseMethod = twinMethodName(base);
  if (baseMethod !== "object" && baseMethod !== "strictObject") return null;
  if (rest.some((call) => !SHAPE_PRESERVING_METHODS.has(twinMethodName(call)))) return null;
  const shape = base.arguments[0];
  if (shape === undefined || shape.type !== AST_NODE_TYPES.ObjectExpression) return null;
  const fields = new Map<string, SchemaField>();
  for (const property of shape.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.computed) return null;
    const { key } = property;
    const name =
      key.type === AST_NODE_TYPES.Identifier
        ? key.name
        : key.type === AST_NODE_TYPES.Literal && typeof key.value === "string"
          ? key.value
          : null;
    if (name === null) return null;
    fields.set(name, twinSchemaField(property.value, zodNamespaces));
  }
  return fields.size === 0 ? null : fields;
}

function twinSchemaField(
  node: TSESTree.Node,
  zodNamespaces: ReadonlySet<string>,
): SchemaField {
  const modifiers: string[] = [];
  let current: TSESTree.Node = node;
  let leaf: string | null = null;
  let leafCall: TSESTree.CallExpression | null = null;
  while (current.type === AST_NODE_TYPES.CallExpression) {
    const callee = current.callee;
    if (
      callee.type !== AST_NODE_TYPES.MemberExpression ||
      callee.computed ||
      callee.property.type !== AST_NODE_TYPES.Identifier
    ) {
      break;
    }
    const receiver = callee.object;
    if (receiver.type === AST_NODE_TYPES.Identifier && zodNamespaces.has(receiver.name)) {
      leaf = callee.property.name;
      leafCall = current;
      break;
    }
    modifiers.push(callee.property.name);
    current = receiver;
  }
  return {
    domain: modifiers.every((name) => DOMAIN_PRESERVING_MODIFIERS.has(name))
      ? staticZodDomain(leaf, leafCall)
      : null,
    leaf,
    optional: modifiers.some((name) => OPTIONAL_MODIFIERS.has(name)),
    nullable: modifiers.some((name) => NULLABLE_MODIFIERS.has(name)),
    reshaped: modifiers.some((name) => RESHAPING_MODIFIERS.has(name)),
  };
}

function twinTypeMembers(
  declaration: TSESTree.TSInterfaceDeclaration | TSESTree.TSTypeAliasDeclaration,
): ReadonlyMap<string, TypeMember> | null {
  let members: readonly TSESTree.TypeElement[];
  if (declaration.type === AST_NODE_TYPES.TSInterfaceDeclaration) {
    if (declaration.typeParameters !== undefined || (declaration.extends?.length ?? 0) > 0) return null;
    members = declaration.body.body;
  } else {
    if (
      declaration.typeParameters !== undefined ||
      declaration.typeAnnotation.type !== AST_NODE_TYPES.TSTypeLiteral
    ) {
      return null;
    }
    members = declaration.typeAnnotation.members;
  }
  const result = new Map<string, TypeMember>();
  for (const member of members) {
    if (member.type !== AST_NODE_TYPES.TSPropertySignature || member.computed) return null;
    const { key } = member;
    const name =
      key.type === AST_NODE_TYPES.Identifier
        ? key.name
        : key.type === AST_NODE_TYPES.Literal && typeof key.value === "string"
          ? key.value
          : null;
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

function nameTokens(name: string): readonly string[] {
  return (
    name
      .replace(/([a-z\d])([A-Z])/gu, "$1 $2")
      .replace(/([A-Z]+)([A-Z][a-z])/gu, "$1 $2")
      .split(/[^A-Za-z\d]+/u)
      .filter((token) => token !== "")
      .map((token) => token.toLowerCase())
  );
}

function schemaNameTokens(name: string): readonly string[] {
  const tokens = nameTokens(name);
  const withoutPrefix = tokens[0] === "z" ? tokens.slice(1) : tokens;
  return withoutPrefix.at(-1) === "schema"
    ? withoutPrefix.slice(0, -1)
    : withoutPrefix;
}

function endsWithTokens(
  candidate: readonly string[],
  suffix: readonly string[],
): boolean {
  return (
    suffix.length >= 2 &&
    candidate.length >= suffix.length &&
    suffix.every(
      (segment, index) =>
        candidate[candidate.length - suffix.length + index] === segment,
    )
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-zod-infer",
  documentation: PREFER_ZOD_INFER_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Derive a type from its Zod schema with `z.infer` instead of hand-writing a twin declaration beside it.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          ignoreTypeNames: {
            type: "array",
            items: { type: "string" },
          },
          requireIdenticalShape: { type: "boolean" },
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
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    const ignorePatterns = (optionsArg?.ignoreTypeNames ?? []).map(
      (source) => new RegExp(source, "u"),
    );
    const requireIdenticalShape = optionsArg?.requireIdenticalShape ?? true;

    if (
      isTestFile(context.filename) ||
      isStoryFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) {
      return {};
    }

    const zodNamespaces = new Set<string>();
    const schemas: SchemaInfo[] = [];
    const enumSchemas: EnumSchemaInfo[] = [];
    const inferredAliases: InferredAliasInfo[] = [];
    const literalUnionOccurrences: LiteralUnionOccurrence[] = [];
    const typeDeclarations: TypeDeclaration[] = [];
    /** Names intentionally constraining a `z.ZodType<...>`. */
    const constrainedTypeNames = new Set<string>();
    /** Schemas reshaped elsewhere in this module. */
    const reshapedSchemaNames = new Set<string>();

    function recordZodImport(node: TSESTree.ImportDeclaration): void {
      if (!isZodModule(node.source.value)) {
        return;
      }
      for (const specifier of node.specifiers) {
        if (
          specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
          specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
          (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
            specifier.imported.type === AST_NODE_TYPES.Identifier &&
            specifier.imported.name === "z")
        ) {
          zodNamespaces.add(specifier.local.name);
        }
      }
    }

    /** Extracts an exact, direct module-level `z.enum([…])` domain. */
    function enumSchemaDomain(
      init: TSESTree.Node,
    ): ReadonlySet<string> | null {
      const chain = twinCallChain(init, zodNamespaces);
      if (chain === null || chain.length !== 1) {
        return null;
      }
      const [call] = chain;
      if (call === undefined || twinMethodName(call) !== "enum") {
        return null;
      }
      const domain = staticZodDomain("enum", call);
      return domain instanceof Set && domain.size >= 2 ? domain : null;
    }

    /** Finds `z.infer<typeof Schema>` without relying on type services. */
    function inferredSchemaName(node: TSESTree.TypeNode): string | null {
      if (
        node.type !== AST_NODE_TYPES.TSTypeReference ||
        node.typeName.type !== AST_NODE_TYPES.TSQualifiedName ||
        node.typeName.left.type !== AST_NODE_TYPES.Identifier ||
        !zodNamespaces.has(node.typeName.left.name) ||
        node.typeName.right.name !== "infer"
      ) {
        return null;
      }
      const arguments_ = node.typeArguments?.params ?? [];
      const [argument] = arguments_;
      return arguments_.length === 1 &&
        argument?.type === AST_NODE_TYPES.TSTypeQuery &&
        argument.exprName.type === AST_NODE_TYPES.Identifier
        ? argument.exprName.name
        : null;
    }

    function recordLiteralUnions(
      members: readonly TSESTree.TypeElement[],
      owner: TSESTree.Node,
      ownerName: string,
      exported: boolean,
    ): void {
      for (const member of members) {
        if (
          member.type !== AST_NODE_TYPES.TSPropertySignature ||
          member.computed ||
          member.optional ||
          member.readonly ||
          member.typeAnnotation === undefined
        ) {
          continue;
        }
        const key = member.key;
        const propertyName =
          key.type === AST_NODE_TYPES.Identifier
            ? key.name
            : key.type === AST_NODE_TYPES.Literal &&
                typeof key.value === "string"
              ? key.value
              : null;
        if (propertyName === null) {
          continue;
        }
        const propertyTokens = nameTokens(propertyName);
        if (propertyTokens.length < 2) {
          continue;
        }
        const annotation = member.typeAnnotation.typeAnnotation;
        const domain = staticStringUnionDomain(annotation);
        if (domain === null || annotation.type !== AST_NODE_TYPES.TSUnionType) {
          continue;
        }
        literalUnionOccurrences.push({
          domain,
          exported,
          node: annotation,
          owner,
          ownerName,
          propertyName,
          propertyTokens,
        });
      }
    }

    function collectConstrainedNames(node: TSESTree.TypeNode): void {
      if (node.type === AST_NODE_TYPES.TSTypeReference) {
        if (node.typeName.type === AST_NODE_TYPES.Identifier) {
          constrainedTypeNames.add(node.typeName.name);
        }
        for (const argument of node.typeArguments?.params ?? []) {
          collectConstrainedNames(argument);
        }
        return;
      }
      if (node.type === AST_NODE_TYPES.TSArrayType) {
        collectConstrainedNames(node.elementType);
        return;
      }
      if (
        node.type === AST_NODE_TYPES.TSUnionType ||
        node.type === AST_NODE_TYPES.TSIntersectionType
      ) {
        for (const member of node.types) {
          collectConstrainedNames(member);
        }
      }
    }

    return {
      Program(node): void {
        // Pre-index imports so legal import declarations placed after a schema
        // do not make recognition depend on traversal order.
        for (const statement of node.body) {
          if (statement.type === AST_NODE_TYPES.ImportDeclaration) {
            recordZodImport(statement);
          }
        }
      },

      ImportDeclaration(node): void {
        recordZodImport(node);
      },

      VariableDeclarator(node): void {
        if (node.id.type !== AST_NODE_TYPES.Identifier || node.init == null || !isModuleLevelConst(node)) {
          return;
        }
        const fields = twinSchemaFields(node.init, zodNamespaces);
        if (fields !== null) {
          schemas.push({ name: node.id.name, fields, initializer: node.init });
        }
        if (isModuleLevelConst(node)) {
          const domain = enumSchemaDomain(node.init);
          const tokens = schemaNameTokens(node.id.name);
          if (domain !== null && tokens.length >= 2) {
            enumSchemas.push({ domain, name: node.id.name, tokens });
          }
        }
      },

      /** Records `XSchema.transform(...)` and equivalent module-level reshaping. */
      "MemberExpression[computed=false]"(node: TSESTree.MemberExpression): void {
        if (
          node.object.type === AST_NODE_TYPES.Identifier &&
          node.property.type === AST_NODE_TYPES.Identifier &&
          isPreferZodInferModuleReshaper(node.property.name)
        ) {
          reshapedSchemaNames.add(node.object.name);
        }
      },

      /** Records every type argument carried by a Zod constraint. */
      TSTypeReference(node): void {
        const { typeName } = node;
        const referenced =
          typeName.type === AST_NODE_TYPES.Identifier
            ? typeName.name
            : typeName.type === AST_NODE_TYPES.TSQualifiedName &&
                typeName.right.type === AST_NODE_TYPES.Identifier
              ? typeName.right.name
              : null;
        if (referenced === null || !isPreferZodInferTypeConstraintName(referenced)) {
          return;
        }
        for (const argument of node.typeArguments?.params ?? []) {
          collectConstrainedNames(argument);
        }
      },

      TSInterfaceDeclaration(node): void {
        if (!isModuleLevelDeclaration(node)) return;
        // Generics and `extends` cannot be replaced by direct schema inference.
        if (node.typeParameters !== undefined || (node.extends?.length ?? 0) > 0) {
          return;
        }
        const members = twinTypeMembers(node);
        if (members !== null) {
          typeDeclarations.push({ declaration: node, name: node.id.name, node: node.id, members });
        }
        recordLiteralUnions(
          node.body.body,
          node,
          node.id.name,
          isExportedDeclaration(node),
        );
      },

      TSTypeAliasDeclaration(node): void {
        if (!isModuleLevelDeclaration(node)) return;
        const schemaName = inferredSchemaName(node.typeAnnotation);
        if (schemaName !== null) {
          inferredAliases.push({
            exported: isExportedDeclaration(node),
            schemaName,
            typeName: node.id.name,
          });
        }
        if (
          node.typeParameters !== undefined ||
          node.typeAnnotation.type !== AST_NODE_TYPES.TSTypeLiteral
        ) {
          return;
        }
        const members = twinTypeMembers(node);
        if (members !== null) {
          typeDeclarations.push({ declaration: node, name: node.id.name, node: node.id, members });
        }
        recordLiteralUnions(
          node.typeAnnotation.members,
          node,
          node.id.name,
          isExportedDeclaration(node),
        );
      },

      "Program:exit"(): void {
        const twinTypeNames = new Set<string>();
        const byName = new Map<string, SchemaInfo>();
        for (const schema of schemas) {
          const key = normalizeSchemaName(schema.name);
          if (key !== "" && !byName.has(key)) {
            byName.set(key, schema);
          }
        }

        for (const declaration of typeDeclarations) {
          if (constrainedTypeNames.has(declaration.name)) {
            continue;
          }
          if (ignorePatterns.some((pattern) => pattern.test(declaration.name))) {
            continue;
          }
          const schema = byName.get(normalizeTypeName(declaration.name));
          if (schema === undefined || reshapedSchemaNames.has(schema.name)) {
            continue;
          }
          if (
            requireIdenticalShape
              ? !preferZodInferOwnsDefaultTwin({
                  constrained: constrainedTypeNames.has(declaration.name),
                  declaration: declaration.declaration,
                  initializer: schema.initializer,
                  reshaped: reshapedSchemaNames.has(schema.name),
                  schemaName: schema.name,
                  typeName: declaration.name,
                  zodNamespaces,
                })
              : false
          ) {
            continue;
          }
          twinTypeNames.add(declaration.name);
          context.report({
            node: declaration.node,
            messageId: "handWrittenTwin",
            data: { typeName: declaration.name, schemaName: schema.name },
          });
        }

        const aliasesBySchema = new Map<string, InferredAliasInfo[]>();
        for (const alias of inferredAliases) {
          const aliases = aliasesBySchema.get(alias.schemaName) ?? [];
          aliases.push(alias);
          aliasesBySchema.set(alias.schemaName, aliases);
        }

        interface RepeatedGroup {
          readonly alias: InferredAliasInfo;
          readonly occurrences: LiteralUnionOccurrence[];
          readonly schema: EnumSchemaInfo;
        }
        const groups = new Map<string, RepeatedGroup>();
        for (const occurrence of literalUnionOccurrences) {
          const { ownerName } = occurrence;
          if (
            twinTypeNames.has(ownerName ?? "") ||
            (ownerName !== null &&
              ignorePatterns.some((pattern) => pattern.test(ownerName)))
          ) {
            continue;
          }
          const candidates = enumSchemas.filter(
            (schema) =>
              sameDomain(schema.domain, occurrence.domain) &&
              endsWithTokens(schema.tokens, occurrence.propertyTokens) &&
              (aliasesBySchema.get(schema.name)?.length ?? 0) === 1,
          );
          const [schema] = candidates;
          if (candidates.length !== 1 || schema === undefined) {
            continue;
          }
          const [alias] = aliasesBySchema.get(schema.name) ?? [];
          if (alias === undefined || (occurrence.exported && !alias.exported)) {
            continue;
          }
          const key = `${schema.name}\0${occurrence.propertyName}`;
          const group = groups.get(key);
          if (group === undefined) {
            groups.set(key, { alias, occurrences: [occurrence], schema });
          } else {
            group.occurrences.push(occurrence);
          }
        }

        for (const { alias, occurrences, schema } of groups.values()) {
          if (
            new Set(occurrences.map(({ ownerName }) => ownerName)).size < 2 ||
            new Set(occurrences.map(({ owner }) => owner)).size < 2
          ) {
            continue;
          }
          const [first] = occurrences;
          if (first === undefined) {
            continue;
          }
          context.report({
            node: first.node,
            messageId: "repeatedEnumUnion",
            data: {
              propertyName: first.propertyName,
              schemaName: schema.name,
              typeName: alias.typeName,
            },
          });
        }
      },
    };
  },
});

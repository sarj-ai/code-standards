/**
 * @fileoverview prefer-zod-infer — a hand-written type beside a Zod schema drifts silently the moment the schema gains a field.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-zod-infer.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "handWrittenTwin";
type Options = readonly [
  {
    ignoreTypeNames?: readonly string[];
    requireIdenticalShape?: boolean;
  }?,
];

export const preferZodInferDocumentation = {
  summary: "Derive a type from its Zod schema with `z.infer` instead of hand-writing a twin declaration beside it.",
  rationale: "A derived type stays synchronized when the runtime schema changes.",
  remediation: "Replace the hand-written twin with `z.infer<typeof Schema>`.",
  category: "correctness",
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

/** Type names whose type arguments are hand-written types by construction. */
const ZOD_TYPE_CONSTRAINTS: ReadonlySet<string> = new Set([
  "ZodType",
  "ZodSchema",
  "ZodTypeAny",
  "ZodMiniType",
  "Schema",
]);

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
  readonly optional: boolean;
  readonly nullable: boolean;
  /** The `z.<leaf>` constructor, or `null` when the member references another schema. */
  readonly leaf: string | null;
  readonly reshaped: boolean;
}

interface SchemaInfo {
  readonly name: string;
  readonly fields: ReadonlyMap<string, SchemaField>;
}

interface TypeMember {
  readonly optional: boolean;
  readonly nullable: boolean;
  readonly readonly: boolean;
  readonly annotation: TSESTree.TypeNode | null;
}

interface TypeDeclaration {
  readonly name: string;
  readonly node: TSESTree.Node;
  readonly members: ReadonlyMap<string, TypeMember>;
}

/** `ZUserSchema` / `userSchema` / `ZUser` all describe the thing named `User`. */
function normalizeSchemaName(name: string): string {
  return name
    .replace(/Schema$/i, "")
    .replace(/^Z(?=[A-Z])/, "")
    .toLowerCase();
}

/** `UserType` is the same claim as `User`; nothing else is stripped. */
function normalizeTypeName(name: string): string {
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

/** Compares a TypeScript annotation with a known Zod leaf; `null` means unknown. */
function leafAgrees(
  leaf: string | null,
  annotation: TSESTree.TypeNode | null,
): boolean | null {
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

export default createRule<Options, MessageIds>({
  name: "prefer-zod-infer",
  documentation: preferZodInferDocumentation,
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
    const typeDeclarations: TypeDeclaration[] = [];
    /** Names intentionally constraining a `z.ZodType<...>`. */
    const constrainedTypeNames = new Set<string>();
    /** Schemas reshaped elsewhere in this module. */
    const reshapedSchemaNames = new Set<string>();

    /** The `z.…` call chain of `node`, base call first, or `null`. */
    function zodCallChain(
      node: TSESTree.Node,
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
        const receiver = callee.object;
        if (receiver.type === AST_NODE_TYPES.Identifier) {
          return zodNamespaces.has(receiver.name) ? chain.reverse() : null;
        }
        current = receiver;
      }
      return null;
    }

    /** The method name of a `z.foo()` / `.foo()` link in a chain. */
    function methodName(call: TSESTree.CallExpression): string {
      const callee = call.callee;
      return callee.type === AST_NODE_TYPES.MemberExpression &&
        callee.property.type === AST_NODE_TYPES.Identifier
        ? callee.property.name
        : "";
    }

    /** Modifier/leaf analysis of one `z.object({ key: <here> })` value. */
    function schemaField(node: TSESTree.Node): SchemaField {
      const modifiers: string[] = [];
      let current: TSESTree.Node = node;
      let leaf: string | null = null;

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
        if (
          receiver.type === AST_NODE_TYPES.Identifier &&
          zodNamespaces.has(receiver.name)
        ) {
          leaf = callee.property.name;
          break;
        }
        modifiers.push(callee.property.name);
        current = receiver;
      }

      return {
        leaf,
        optional: modifiers.some((name) => OPTIONAL_MODIFIERS.has(name)),
        nullable: modifiers.some((name) => NULLABLE_MODIFIERS.has(name)),
        reshaped: modifiers.some((name) => RESHAPING_MODIFIERS.has(name)),
      };
    }

    /** Extracts fields only from plain object literals with shape-preserving chains. */
    function schemaFields(
      init: TSESTree.Node,
    ): ReadonlyMap<string, SchemaField> | null {
      const chain = zodCallChain(init);
      if (chain === null || chain.length === 0) {
        return null;
      }
      const [base, ...rest] = chain;
      if (base === undefined) {
        return null;
      }
      const baseMethod = methodName(base);
      if (baseMethod !== "object" && baseMethod !== "strictObject") {
        return null;
      }
      if (rest.some((call) => !SHAPE_PRESERVING_METHODS.has(methodName(call)))) {
        return null;
      }
      const shape = base.arguments[0];
      if (shape === undefined || shape.type !== AST_NODE_TYPES.ObjectExpression) {
        return null;
      }

      const fields = new Map<string, SchemaField>();
      for (const property of shape.properties) {
        if (property.type !== AST_NODE_TYPES.Property || property.computed) {
          return null; // a spread or computed key hides members from us
        }
        const { key } = property;
        const name =
          key.type === AST_NODE_TYPES.Identifier
            ? key.name
            : key.type === AST_NODE_TYPES.Literal && typeof key.value === "string"
              ? key.value
              : null;
        if (name === null) {
          return null;
        }
        fields.set(name, schemaField(property.value));
      }
      return fields.size === 0 ? null : fields;
    }

    /** The property signatures of an object type, or `null` if any member is exotic. */
    function typeMembers(
      members: readonly TSESTree.TypeElement[],
    ): ReadonlyMap<string, TypeMember> | null {
      const result = new Map<string, TypeMember>();
      for (const member of members) {
        if (member.type !== AST_NODE_TYPES.TSPropertySignature || member.computed) {
          return null;
        }
        const { key } = member;
        const name =
          key.type === AST_NODE_TYPES.Identifier
            ? key.name
            : key.type === AST_NODE_TYPES.Literal && typeof key.value === "string"
              ? key.value
              : null;
        if (name === null) {
          return null;
        }
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

    /** True when the pair is close enough to call one a restatement of the other. */
    function isTwin(
      fields: ReadonlyMap<string, SchemaField>,
      members: ReadonlyMap<string, TypeMember>,
    ): boolean {
      if (!requireIdenticalShape) {
        return true;
      }
      if (fields.size !== members.size) {
        return false;
      }
      let agreements = 0;
      for (const [name, field] of fields) {
        const member = members.get(name);
        if (member === undefined) {
          return false;
        }
        // A reshaped member's inferred type is not what is written.
        if (field.reshaped) {
          return false;
        }
        if (field.optional !== member.optional) {
          return false;
        }
        if (field.nullable !== member.nullable) {
          return false;
        }
        if (member.readonly) {
          return false;
        }
        const agrees = leafAgrees(field.leaf, member.annotation);
        if (agrees === false) {
          return false;
        }
        if (agrees === true) {
          agreements += 1;
        }
      }
      // At least one member has to positively agree; a pair of types whose
      // members are all references to other symbols is a name coincidence.
      return agreements > 0;
    }

    return {
      ImportDeclaration(node): void {
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
      },

      VariableDeclarator(node): void {
        if (node.id.type !== AST_NODE_TYPES.Identifier || node.init == null) {
          return;
        }
        const fields = schemaFields(node.init);
        if (fields !== null) {
          schemas.push({ name: node.id.name, fields });
        }
      },

      /** Records `XSchema.transform(...)` and equivalent module-level reshaping. */
      "MemberExpression[computed=false]"(node: TSESTree.MemberExpression): void {
        if (
          node.object.type === AST_NODE_TYPES.Identifier &&
          node.property.type === AST_NODE_TYPES.Identifier &&
          MODULE_LEVEL_RESHAPERS.has(node.property.name)
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
        if (referenced === null || !ZOD_TYPE_CONSTRAINTS.has(referenced)) {
          return;
        }
        for (const argument of node.typeArguments?.params ?? []) {
          collectConstrainedNames(argument);
        }
      },

      TSInterfaceDeclaration(node): void {
        // Generics and `extends` cannot be replaced by direct schema inference.
        if (node.typeParameters !== undefined || (node.extends?.length ?? 0) > 0) {
          return;
        }
        const members = typeMembers(node.body.body);
        if (members !== null) {
          typeDeclarations.push({ name: node.id.name, node: node.id, members });
        }
      },

      TSTypeAliasDeclaration(node): void {
        if (
          node.typeParameters !== undefined ||
          node.typeAnnotation.type !== AST_NODE_TYPES.TSTypeLiteral
        ) {
          return;
        }
        const members = typeMembers(node.typeAnnotation.members);
        if (members !== null) {
          typeDeclarations.push({ name: node.id.name, node: node.id, members });
        }
      },

      "Program:exit"(): void {
        if (schemas.length === 0 || typeDeclarations.length === 0) {
          return;
        }
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
          if (!isTwin(schema.fields, declaration.members)) {
            continue;
          }
          context.report({
            node: declaration.node,
            messageId: "handWrittenTwin",
            data: { typeName: declaration.name, schemaName: schema.name },
          });
        }
      },
    };
  },
});

/**
 * @fileoverview Flag a hand-written `interface`/`type` that restates the shape
 * of a Zod schema declared in the same module. The type must be DERIVED:
 *
 *   const UserSchema = z.object({ id: z.string(), name: z.string() });
 *   interface User { id: string; name: string }   // twin — drifts silently
 *   type User = z.infer<typeof UserSchema>;       // derived — cannot drift
 *
 * The defect is silent: a field added to the schema and not to the twin fails
 * nothing at build time. The parsed value simply carries a member the type says
 * does not exist, and every read of it is a `never`-narrowed branch or a cast.
 *
 * MEASUREMENT (2026-07). The rule as shipped was run over 30,759 `.ts`/`.tsx`
 * files in seventeen repositories — seven maintained internally plus zod, trpc,
 * dub, openstatus, formbricks, documenso, unkey, midday, papermark and cal.com.
 * 3,622 of those files import Zod and hold 7,255 schemas, 3,432 `z.infer`
 * aliases (the convention is already the norm; this rule is the ratchet) and
 * 1,657 hand-written object types.
 *
 * IT REPORTS 5 TIMES, and all five are true positives, every one of them in a
 * public repository:
 *
 *   midday/packages/categories/src/types.ts:4       BaseCategory
 *   midday/packages/accounting/src/types.ts:256     BaseProviderConfig
 *   openstatus/packages/status-fetcher/src/types.ts:59  ApiConfig
 *   openstatus/packages/status-fetcher/src/types.ts:65  StatusPageEntry
 *   documenso/packages/lib/jobs/client/_internal/job.ts:5  SimpleTriggerJobOptions
 *
 * Each is a member-for-member restatement of a schema declared in the same
 * file — `interface BaseProviderConfig` sits directly under
 * `BaseProviderConfigSchema` with the doc comments copied across, and
 * openstatus's file introduces its pair under the comment "Interfaces using
 * derived types", which is exactly what they are not. Zero reports in the seven
 * internal repos: the pairs that exist there are all deliberate (see (d), (f)).
 *
 * WHAT EACH GUARD REMOVES, measured by disabling it and re-running the sweep:
 *
 *   (a) tests + generated files   +2   both in zod's own `object.test.ts`
 *   (f) `.transform()` sibling    +2   both in one internal module
 *   (b) generic type parameters   +0   (+1 at the looser tier below)
 *   (c) `z.ZodType<T>` arguments  +0   (see below — kept anyway)
 *
 * WHY NAME CORRELATION IS REQUIRED. The obvious alternative — flag any type
 * whose key set equals some schema's in the file, names ignored — was measured
 * on the same corpus with every other guard in place: 13 reports, 4 true
 * positives and 9 false. The 9 share one shape: a DB-row or wire-input type
 * that happens to share a key set with the response schema it is mapped into
 * (`{ id, name, roles }` on both sides of a mapping function, the nested member
 * types entirely different). Key-set coincidence is cheap at three or four
 * members; a matching NAME is what makes the pair a claim about the same thing.
 *
 * `requireIdenticalShape: false` drops the member-by-member comparison and
 * reports on name correlation alone: 8 hits on the same corpus, the 5 above
 * plus openstatus's `Monitor` (a five-member type against a three-key schema —
 * the one false positive), midday's `TaxRateConfig` (a twin that has ALREADY
 * drifted: the interface admits `null` where the schema's `z.enum` does not)
 * and cal.com's `CalendarState` (a real twin whose one `.transform()`ed member
 * the strict tier cannot verify). It is the right setting for a repo that wants
 * the drift caught rather than only the exact duplicates, at ~1 in 8 noise.
 *
 * GUARDS, each earned by a measured false positive:
 *
 *   (a) TESTS AND GENERATED FILES. 152 of the 171 name-correlated pairs in the
 *       corpus are in `*.test.ts` or generated output. A schema and a type
 *       declared side by side in a parser test are the two halves of the
 *       assertion, not a duplication — `zod/packages/zod/src/v4/classic/tests/
 *       object.test.ts:13` declares `type TestType` beside `const Test`.
 *   (b) GENERIC TYPES. `z.infer` cannot produce a type parameterised by the
 *       caller, so a generic twin is not a twin.
 *       `documenso/packages/lib/types/search-params.ts:50` declares
 *       `export type FindResultResponse<T>` over the keys of
 *       `ZFindResultResponse`, and the line above it reads "// Can't infer
 *       generics from Zod."
 *   (c) `z.ZodType<T>` ANNOTATIONS — the SUPPORTED direction for constraining a
 *       schema to an existing type. 446 annotation sites in the corpus (314 in
 *       unkey, 61 in cal.com); flagging `T` would tell an author to invert a
 *       dependency the language cannot invert. It removes nothing measurable
 *       today ONLY because cal.com, which uses the pattern at scale, prefixes
 *       the hand-written type with `T` (`TCreateInputSchema` beside
 *       `ZCreateInputSchema`) so the names never correlate. The moment a repo
 *       writes the ordinary `interface ApiKey` / `const apiKeySchema:
 *       z.ZodType<ApiKey>`, this guard is the only thing standing between the
 *       rule and backwards advice — hence it ships with a test rather than
 *       waiting for the report. ALL type arguments are collected, not just the
 *       first: cal.com's tRPC inputs use `z.ZodType<Output, Def, Input>`, and
 *       reading only the first names the wrong type
 *       (`packages/trpc/server/routers/viewer/bookings/get.schema.ts:29`).
 *   (d) SCHEMAS THAT ARE NOT PLAIN OBJECT LITERALS. `z.looseObject`,
 *       `.partial()`, `.passthrough()`, `.catchall()`, `.omit()`, `.merge()`
 *       and friends all mean the inferred type is deliberately not the shape
 *       written at the call site. The two internal pairs this removes are both
 *       `z.looseObject` LENIENT wire schemas (`.nullish()` on every field)
 *       beside the STRICT domain type a hand-written parse function returns —
 *       parse-don't-validate, working as intended.
 *   (e) PER-KEY OPTIONALITY AND TYPE DISAGREEMENT. A twin restates the shape;
 *       anything that disagrees is a deliberately different type. This is what
 *       removes the snake_case-wire vs camelCase-domain pairs — a shared base
 *       name, a shared member count, and almost no shared members.
 *   (f) SCHEMAS FED THROUGH `.transform()` ELSEWHERE IN THE MODULE. When a
 *       module declares `const XCamel = XSchema.transform(...)`, a hand-written
 *       `X` plausibly describes the POST-transform value, and `z.infer<typeof
 *       XSchema>` — what this rule would otherwise point at — is the wrong
 *       answer. Two internal reports, both in one module whose eight interfaces
 *       are the camelCase outputs of eight snake_case schemas.
 *   (g) INTERFACES WITH `extends`, and aliases that are not a bare object
 *       literal: a type that adds to or narrows a schema's shape is not
 *       restating it.
 *
 * ONE MEMBER MUST POSITIVELY AGREE. A pair whose members are all references to
 * other symbols (`role: Role` against `role: RoleSchema`) proves nothing about
 * the two being the same shape, so the rule needs at least one member whose Zod
 * leaf and TypeScript annotation demonstrably match before it reports.
 *
 * THE COST is recall, deliberately. cal.com's `CalendarState` is a genuine twin
 * that the strict tier stays quiet about because one member is
 * `z.string().optional().transform(...)`, and a hand-written type whose name
 * does not correlate with its schema (`FormValues` beside `formSchema`) is
 * never reached at all. Both are visible at `requireIdenticalShape: false`.
 *
 * THE INVERSE SMELL is real and NOT covered here: `const XSchema:
 * z.ZodType<HandWrittenX> = z.object({...})` forces the schema to satisfy a
 * hand-written type, which type-checks the schema against the type but leaves
 * the type hand-maintained — inference flowing the wrong way. It is legitimate
 * in generic library code (`schema?: z.ZodType<Schema>` as a parameter bound)
 * and a smell only when the argument is a concrete local type, so separating
 * the two needs its own measurement pass and its own rule.
 */

import {
  AST_NODE_TYPES,
  ESLintUtils,
  type TSESTree,
} from "@typescript-eslint/utils";

import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "handWrittenTwin";
type Options = readonly [
  {
    ignoreTypeNames?: readonly string[];
    requireIdenticalShape?: boolean;
  }?,
];

/**
 * Chained methods that leave a schema's inferred type alone. Everything else —
 * `.partial()`, `.omit()`, `.merge()`, `.transform()`, `.brand()`, … — means
 * the inferred type is deliberately not the object literal at the call site,
 * so the pair is none of this rule's business. See guard (d).
 */
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
  "default",
  "prefault",
  "catch",
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
]);

/** Methods whose receiver schema is being reshaped — see guard (f). */
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

/**
 * Whether the annotation is the shape `z.<leaf>()` infers. `null` means "cannot
 * tell" — a member that references another schema, or a leaf this table does
 * not model. Only a definite `false` blocks a report.
 */
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
  return expected.includes(core.type);
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/tree/main/packages/typescript#${name}`,
)<Options, MessageIds>({
  name: "prefer-zod-infer",
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
    /** Guard (c): every name mentioned inside a `z.ZodType<…>` type argument. */
    const constrainedTypeNames = new Set<string>();
    /** Guard (f): schemas this module pipes through a shape-changing method. */
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

    /** Guard (d): only a plain `z.object({...})` literal describes its own shape. */
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
        // Guard (d)/(e): a reshaped member's inferred type is not what is written.
        if (field.reshaped) {
          return false;
        }
        if (field.optional !== member.optional) {
          return false;
        }
        if (field.nullable !== member.nullable) {
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

      /** Guard (f): `XSchema.transform(...)` anywhere in the module. */
      "MemberExpression[computed=false]"(node: TSESTree.MemberExpression): void {
        if (
          node.object.type === AST_NODE_TYPES.Identifier &&
          node.property.type === AST_NODE_TYPES.Identifier &&
          MODULE_LEVEL_RESHAPERS.has(node.property.name)
        ) {
          reshapedSchemaNames.add(node.object.name);
        }
      },

      /** Guard (c): `z.ZodType<T>` and every other type argument it carries. */
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
        // Guard (b)/(g): generics and `extends` both mean "not a restatement".
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

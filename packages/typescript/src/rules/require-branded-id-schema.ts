/** @fileoverview require-branded-id-schema — preserve identifier roles at Zod parse boundaries. */

import { defineRule, type Context, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { identifierRole } from "./_nominal-id-roles.js";

const NAME = "require-branded-id-schema";
const DESCRIPTION = "Brand Zod identifier schemas so validated identifiers retain their domain.";
const SCHEMA_SUFFIX = "Schema";
const OBJECT_FACTORIES: ReadonlySet<string> = new Set(["object", "strictObject", "looseObject"]);
const STRING_FACTORIES: ReadonlySet<string> = new Set([
  "string", "uuid", "guid", "uuidv4", "uuidv6", "uuidv7",
  "nanoid", "cuid", "cuid2", "ulid", "xid", "ksuid",
]);
const SCALAR_METHODS: ReadonlySet<string> = new Set([
  ...STRING_FACTORIES,
  "min", "max", "length", "nonempty", "regex", "includes", "startsWith", "endsWith",
  "lowercase", "uppercase", "trim", "normalize", "toLowerCase", "toUpperCase",
  "int", "gt", "gte", "lt", "lte", "positive", "nonnegative", "negative",
  "nonpositive", "multipleOf", "step", "finite", "safe",
  "optional", "nullable", "nullish", "default", "prefault", "catch", "readonly",
  "refine", "superRefine", "check", "describe", "meta",
]);

type Carrier = "string" | "number";
type ScalarSchema = Carrier | "branded";

interface RawField {
  readonly carrier: Carrier;
  readonly key: Node;
  readonly role: string;
}

function schemaRole(name: string): string | undefined {
  return name.endsWith(SCHEMA_SUFFIX) ? identifierRole(name.slice(0, -SCHEMA_SUFFIX.length)) : undefined;
}

function zodFactory(callee: Node, source: SourceCode): string | null {
  if (callee.type === "Identifier") return zodImport(callee, source);
  return callee.type === "MemberExpression" && !callee.optional &&
    zodImport(callee.object, source) === "z" ? getPropertyName(callee) : null;
}

function zodImport(node: Node, source: SourceCode): string | null {
  if (node.type !== "Identifier") return null;
  const variable = findVariable(source.getScope(node), node.name);
  const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
  const declaration = definition === undefined ? null : parentOf(definition.node);
  if (
    definition?.type !== "ImportBinding" || declaration?.type !== "ImportDeclaration" ||
    declaration.importKind === "type" ||
    (declaration.source.value !== "zod" && declaration.source.value !== "zod/v4")
  ) return null;
  const specifier = definition.node;
  if (specifier.type === "ImportNamespaceSpecifier" || specifier.type === "ImportDefaultSpecifier") return "z";
  return specifier.type === "ImportSpecifier" && specifier.importKind !== "type"
    ? importSpecifierName(specifier)
    : null;
}

function scalarSchema(input: Node, source: SourceCode): ScalarSchema | undefined {
  let node = input;
  let branded = false;
  while (node.type === "CallExpression" && !node.optional) {
    const callee = node.callee;
    const factory = zodFactory(callee, source);
    if (factory === "number" || (factory !== null && STRING_FACTORIES.has(factory))) {
      if (branded) return "branded";
      return factory === "number" ? "number" : "string";
    }
    if (callee.type !== "MemberExpression" || callee.optional) return undefined;
    const method = getPropertyName(callee);
    if (method === "brand") branded = true;
    else if (method === null || !SCALAR_METHODS.has(method)) return undefined;
    node = callee.object;
  }
  return undefined;
}

function moduleConst(node: ESTree.VariableDeclarator): boolean {
  const declaration = parentOf(node);
  if (declaration?.type !== "VariableDeclaration" || declaration.kind !== "const") return false;
  const owner = parentOf(declaration);
  return (owner?.type === "ExportNamedDeclaration" ? parentOf(owner) : owner)?.type === "Program";
}

function primitive(node: Node): boolean {
  return node.type === "TSStringKeyword" || node.type === "TSNumberKeyword";
}

function checkAlias(node: ESTree.TSTypeAliasDeclaration, context: Context): void {
  if (!/(?:Id|_id)$/u.test(node.id.name) || identifierRole(node.id.name) === undefined) return;
  const type = node.typeAnnotation;
  if (primitive(type) || (type.type === "TSUnionType" && type.types.every(primitive))) {
    context.report({ node: node.id, messageId: "unbrandedIdSchema" });
  }
}

function checkShape(shape: ESTree.ObjectExpression, context: Context): void {
  const raw: RawField[] = [];
  const branded = new Set<string>();
  for (const [name, property] of directFields(shape)) {
    const role = identifierRole(name);
    if (role === undefined) continue;
    const { key, value } = property;
    const schema = scalarSchema(value, context.sourceCode);
    if (schema === "branded" || (value.type === "Identifier" && schemaRole(value.name) !== undefined)) {
      branded.add(role);
    } else if (schema !== undefined) {
      raw.push({ key, role, carrier: schema });
    }
  }

  const mixed = raw.find(({ role }) => branded.size > 1 || (branded.size === 1 && !branded.has(role)));
  if (mixed !== undefined) {
    context.report({ node: mixed.key, messageId: "mixedBrandedIds" });
    return;
  }
  const firstRoles = new Map<Carrier, string>();
  for (const { key, role, carrier } of raw) {
    const previous = firstRoles.get(carrier);
    if (previous !== undefined && previous !== role) {
      context.report({ node: key, messageId: "interchangeableIdSchemas" });
      return;
    }
    firstRoles.set(carrier, role);
  }
}

/** A spread or unknown computed key can replace fields declared before it. */
function directFields(shape: ESTree.ObjectExpression): Iterable<readonly [string, ESTree.ObjectProperty]> {
  const fields = new Map<string, ESTree.ObjectProperty>();
  for (const property of shape.properties) {
    const key = property.type === "Property" ? getPropertyName(property) : null;
    if (property.type !== "Property" || key === null) {
      fields.clear();
      continue;
    }
    fields.delete(key);
    if (!property.computed && property.kind === "init" && !property.method && identifierRole(key) !== undefined) {
      fields.set(key, property);
    }
  }
  return fields;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: { description: DESCRIPTION, url: docsUrl(NAME) },
    schema: [],
    messages: {
      unbrandedIdSchema: "Use a branded Zod schema to preserve this identifier domain after parsing.",
      mixedBrandedIds: "This object has branded and unbranded identifier fields. Use a branded Zod schema for the unbranded role.",
      interchangeableIdSchemas: "Distinct identifier roles share a primitive output type. Use distinct branded Zod schemas.",
    },
  },
  createOnce(context) {
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      VariableDeclarator(node: ESTree.VariableDeclarator) {
        if (node.id.type !== "Identifier" || node.init === null || schemaRole(node.id.name) === undefined || !moduleConst(node)) return;
        const schema = scalarSchema(node.init, context.sourceCode);
        if (schema === "string" || schema === "number") {
          context.report({ node: node.id, messageId: "unbrandedIdSchema" });
        }
      },
      TSTypeAliasDeclaration(node: ESTree.TSTypeAliasDeclaration) {
        checkAlias(node, context);
      },
      CallExpression(node: ESTree.CallExpression) {
        if (node.optional || node.arguments[0]?.type !== "ObjectExpression") return;
        const factory = zodFactory(node.callee, context.sourceCode);
        if (factory !== null && OBJECT_FACTORIES.has(factory)) checkShape(node.arguments[0], context);
      },
    };
  },
});

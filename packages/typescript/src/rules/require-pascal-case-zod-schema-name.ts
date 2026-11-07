/**
 * @fileoverview require-pascal-case-zod-schema-name — reusable schemas are runtime type contracts, not scalar constants.
 *
 * Port of the 18.x `require-pascal-case-zod-schema-name` rule. The rule
 * is untyped, so the port covers all of it.
 */

import type { Fix, Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type TsVariable } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { hasIdentifierNamed } from "../utils/unused-private-binding.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "require-pascal-case-zod-schema-name";

type Identifier = ESTree.IdentifierReference | ESTree.BindingIdentifier | ESTree.IdentifierName;

const PASCAL_SCHEMA_NAME_RE = /^[A-Z][A-Za-z0-9]*Schema$/;

/** Benchmark-local schemas are fixtures; require a complete path segment. */
const BENCHMARK_PATH_RE = /(^|[\\/])(?:benchmarks?|bench)[\\/]/;

/**
 * Terminal methods whose results are values, result envelopes, registries,
 * JSON objects, or functions rather than schemas.
 */
const NON_SCHEMA_TERMINALS: ReadonlySet<string> = new Set([
  "parse",
  "parseAsync",
  "safeParse",
  "safeParseAsync",
  "encode",
  "decode",
  "encodeAsync",
  "decodeAsync",
  "safeEncode",
  "safeDecode",
  "safeEncodeAsync",
  "safeDecodeAsync",
  "toJSONSchema",
  "registry",
  "implement",
  "flattenError",
  "formatError",
  "isNullable",
  "isOptional",
  "prettifyError",
  "treeifyError",
]);

const ZOD_SCHEMA_FACTORIES: ReadonlySet<string> = new Set([
  "any", "array", "base64", "base64url", "bigint", "boolean", "cidrv4", "cidrv6",
  "codec", "custom", "date", "discriminatedUnion", "email", "emoji", "enum", "file",
  "function", "hash", "hex", "hostname", "instanceof", "intersection", "ipv4", "ipv6",
  "json", "jwt", "lazy", "literal", "looseObject", "map", "nan", "nativeEnum", "never",
  "null", "nullable", "nullish", "number", "object", "optional", "partialRecord", "preprocess",
  "promise", "record", "set", "strictObject", "string", "stringbool", "symbol", "templateLiteral",
  "tuple", "undefined", "union", "unknown", "url", "uuid", "void",
]);

const ZOD_FACTORY_NAMESPACES: ReadonlySet<string> = new Set(["coerce", "iso"]);

const SCHEMA_RETURNING_METHODS: ReadonlySet<string> = new Set([
  "and", "array", "brand", "catch", "check", "clone", "default", "describe", "extend", "keyof",
  "meta", "nullable", "nullish", "omit", "optional", "or", "overwrite", "partial", "pick", "pipe",
  "prefault", "readonly", "refine", "register", "required", "safeExtend", "superRefine", "transform",
]);

/** Return the identifier at the root of a fluent call/member chain. */
const calleeChainRoot = (node: Node): Identifier | null => {
  let current: Node = node;

  for (;;) {
    current = unwrapExpression(current);
    if (current.type === "Identifier") {
      return current;
    }
    if (current.type === "MemberExpression") {
      current = current.object;
      continue;
    }
    if (current.type === "CallExpression") {
      current = unwrapExpression(current.callee);
      continue;
    }
    return null;
  }
};

const chainMemberNames = (node: Node): readonly string[] => {
  const names: string[] = [];
  let current = node;
  for (;;) {
    current = unwrapExpression(current);
    if (current.type === "MemberExpression") {
      const name = getPropertyName(current);
      if (name === null) return [];
      names.push(name);
      current = current.object;
      continue;
    }
    if (current.type === "CallExpression") {
      current = unwrapExpression(current.callee);
      continue;
    }
    break;
  }
  names.reverse();
  return names;
};


const isModuleDeclarator = (node: ESTree.VariableDeclarator): boolean => {
  const declaration = node.parent;
  if (declaration.type !== "VariableDeclaration") return false;
  const owner = declaration.parent;
  return owner.type === "Program" ||
    (owner.type === "ExportNamedDeclaration" && owner.parent.type === "Program");
};

/** `user_record` and `USER_RECORD` become `UserRecordSchema`. */
function pascalSchemaName(name: string): string {
  const words = name.replaceAll(/([a-z0-9])([A-Z])/gu, "$1_$2")
    .replaceAll(/([A-Z])([A-Z][a-z])/gu, "$1_$2").split("_").filter(Boolean);
  const pascal = words.map((word) => word[0]!.toUpperCase() + word.slice(1).toLowerCase()).join("");
  return pascal.endsWith("Schema") ? pascal : `${pascal}Schema`;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Require confirmed module-level Zod schema contracts to use PascalCase with a `Schema` suffix.",
      url: docsUrl(NAME),
    },
    schema: [],
    defaultOptions: [],
    messages: {
      requirePascalSchema: "Zod schema contracts must use PascalCase ending in Schema (for example, `MutationRouteBaseSchema`); reserve SCREAMING_SNAKE_CASE for scalar/table constants.",
    },
  },
  createOnce(context) {
    const zodBindings = new Set<TsVariable>();
    const schemaBindings = new Set<TsVariable>();

    function resolvedBinding(identifier: Identifier): TsVariable | null {
      return findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function recordZodBinding(identifier: Identifier): void {
      const binding = resolvedBinding(identifier);
      if (binding !== null) zodBindings.add(binding);
    }

    function isConfirmedSchema(expression: Node): boolean {
      const init = unwrapExpression(expression);
      if (init.type === "Identifier") return isSchemaBinding(init);
      if (init.type !== "CallExpression") return false;
      const callee = unwrapExpression(init.callee);
      if (callee.type !== "MemberExpression") {
        return false;
      }
      const terminal = getPropertyName(callee);
      if (terminal === null || NON_SCHEMA_TERMINALS.has(terminal)) return false;
      const names = chainMemberNames(callee);
      if (names.length === 0) return false;
      if (isZodChain(callee)) {
        return ZOD_SCHEMA_FACTORIES.has(names[0] ?? "") ||
          (ZOD_FACTORY_NAMESPACES.has(names[0] ?? "") && ZOD_SCHEMA_FACTORIES.has(names[1] ?? ""));
      }
      const root = calleeChainRoot(callee);
      return root !== null && isSchemaBinding(root) && SCHEMA_RETURNING_METHODS.has(terminal);
    }

    function isSchemaBinding(identifier: Identifier): boolean {
      const binding = resolvedBinding(identifier);
      return binding !== null && schemaBindings.has(binding);
    }

    function isZodChain(node: Node): boolean {
      const root = calleeChainRoot(node);
      if (root === null) return false;
      const binding = resolvedBinding(root);
      return binding !== null && zodBindings.has(binding);
    }

    function renameFix(node: ESTree.VariableDeclarator): ((fixer: Fixer) => Fix[]) | null {
      // Only reached for module declarators, whose parent is a VariableDeclaration.
      const declaration = node.parent as ESTree.VariableDeclaration;
      if (node.id.type !== "Identifier" || declaration.kind !== "const" ||
        declaration.parent.type !== "Program") return null;
      const binding = resolvedBinding(node.id);
      if (binding === null || binding.scope.type !== "module" ||
        !/^[A-Za-z_][A-Za-z0-9_]*$/u.test(node.id.name) ||
        hasIdentifierNamed(context.sourceCode, "eval")) return null;
      const name = pascalSchemaName(node.id.name);
      if (!PASCAL_SCHEMA_NAME_RE.test(name) || binding.scope.set.has(name) ||
        hasIdentifierNamed(context.sourceCode, name)) return null;
      const replacements = renameReplacements([node.id, ...binding.references.map((reference) => reference.identifier)], name);
      return replacements === null
        ? null
        : (fixer) => replacements.map((replacement) => fixer.replaceText(replacement.node, replacement.text));
    }

    /** One replacement per distinct identifier, or null when any of them cannot take `name` safely. */
    function renameReplacements(
      references: readonly Node[],
      name: string,
    ): readonly { readonly node: Identifier; readonly text: string }[] | null {
      const replacements = new Map<number, { readonly node: Identifier; readonly text: string }>();
      for (const reference of references) {
        if (reference.type !== "Identifier" ||
          findVariable(context.sourceCode.getScope(reference), name) !== null) return null;
        const parent = reference.parent;
        if (parent.type === "ExportSpecifier" || parent.type === "ExportDefaultDeclaration" ||
          (parent.type === "AssignmentPattern" && parent.parent.type === "Property" && parent.parent.shorthand)) return null;
        const shorthand = parent.type === "Property" && parent.shorthand && parent.value === reference;
        const text = shorthand ? `${context.sourceCode.getText(reference)}: ${name}` : name;
        replacements.set(reference.range[0], { node: reference, text });
      }
      return [...replacements.values()];
    }

    return {
      before() {
        // Test and benchmark schemas are local fixtures rather than APIs.
        const path = { filename: context.filename, cwd: context.cwd };
        if (
          isTestFile(path) ||
          BENCHMARK_PATH_RE.test(context.filename.replaceAll("\\", "/")) ||
          isGeneratedFile(path, context.sourceCode.text)
        ) {
          return false;
        }
        zodBindings.clear();
        schemaBindings.clear();
        return undefined;
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" &&
              importSpecifierName(specifier) === "z")
          ) {
            recordZodBinding(specifier.local);
          }
        }
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        if (!isModuleDeclarator(node)) return;
        const init = node.init;
        if (init === null) return;
        if (node.id.type !== "Identifier") return;
        if (!isConfirmedSchema(init)) return;
        const binding = resolvedBinding(node.id);
        if (binding !== null) schemaBindings.add(binding);
        if (PASCAL_SCHEMA_NAME_RE.test(node.id.name)) return;

        const fix = renameFix(node);
        context.report({
          node: node.id,
          messageId: "requirePascalSchema",
          ...(fix !== null && { fix }),
        });
      },
    };
  },
});

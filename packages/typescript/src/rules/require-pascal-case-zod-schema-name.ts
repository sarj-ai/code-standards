/**
 * @fileoverview require-pascal-case-zod-schema-name — reusable schemas are runtime type contracts, not scalar constants.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-pascal-case-zod-schema-name.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "requirePascalSchema";
type Options = readonly [];

export const REQUIRE_PASCAL_CASE_ZOD_SCHEMA_NAME_DOCUMENTATION = {
  summary: "Require confirmed module-level Zod schema contracts to use PascalCase with a `Schema` suffix.",
  rationale: "A reusable Zod schema is a runtime type contract. PascalCase mirrors that role; SCREAMING_SNAKE_CASE should remain reserved for scalar values and lookup tables.",
  remediation: "Rename the binding to PascalCase ending in `Schema` (for example, `MutationRouteBaseSchema`).",
  category: "style",
  aliases: ["zod-naming-convention"],
  autofix: "none",
  limitations: [
    "Only module-level bindings proven from a Zod import or a same-file proven schema are checked.",
    "Tests, benchmarks, generated files, imported schemas, re-export aliases, and arbitrary wrapper-factory results are excluded.",
    "Cross-file and exported renames are not safely file-local, so the rule has no autofix.",
  ],
  examples: [
    { id: "runtime-type-schema-name", title: "Name a reusable schema like a runtime type contract", outcome: "no-match", files: [{ path: "src/user.ts", source: "import { z } from 'zod';\nexport const UserSchema = z.object({ id: z.string() });" }], focusPath: "src/user.ts", expectedCount: 0, public: true },
    { id: "screaming-schema-name", title: "Do not name a schema like a scalar constant", outcome: "match", files: [{ path: "src/user.ts", source: "import { z } from 'zod';\nexport const USER_SCHEMA = z.object({ id: z.string() });" }], focusPath: "src/user.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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

/** Return the final method name in a call chain. */
const terminalMethodName = (callee: ESTree.MemberExpression): string | null =>
  !callee.computed && callee.property.type === "Identifier"
    ? callee.property.name
    : null;

/** Return the identifier at the root of a fluent call/member chain. */
const calleeChainRoot = (node: ESTree.Node): ESTree.BindingIdentifier | null => {
  let current: ESTree.Node = node;

  for (;;) {
    if (current.type === "Identifier") {
      return current;
    }
    if (current.type === "MemberExpression") {
      current = current.object;
      continue;
    }
    if (current.type === "CallExpression") {
      current = current.callee;
      continue;
    }
    return null;
  }
};

const chainMemberNames = (node: ESTree.Node): readonly string[] => {
  const names: string[] = [];
  let current = node;
  for (;;) {
    if (current.type === "MemberExpression") {
      if (current.computed || current.property.type !== "Identifier") return [];
      names.push(current.property.name);
      current = current.object;
      continue;
    }
    if (current.type === "CallExpression") {
      current = current.callee;
      continue;
    }
    break;
  }
  names.reverse();
  return names;
};

const unwrapExpression = (node: ESTree.Expression): ESTree.Expression => {
  let current = node;
  while (
    current.type === "TSAsExpression" ||
    current.type === "TSSatisfiesExpression" ||
    current.type === "TSNonNullExpression" ||
    current.type === "TSTypeAssertion"
  ) {
    current = current.expression;
  }
  return current;
};

const isModuleDeclarator = (node: ESTree.VariableDeclarator): boolean => {
  const declaration = node.parent;
  if (declaration.type !== "VariableDeclaration") return false;
  const owner = declaration.parent;
  return owner.type === "Program" ||
    (owner.type === "ExportNamedDeclaration" && owner.parent?.type === "Program");
};

export default createRule<Options, MessageIds>({
  name: "require-pascal-case-zod-schema-name",
  documentation: REQUIRE_PASCAL_CASE_ZOD_SCHEMA_NAME_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description: "Require confirmed module-level Zod schema contracts to use PascalCase with a `Schema` suffix.",
    },
    schema: [],
    messages: {
      requirePascalSchema: "Zod schema contracts must use PascalCase ending in Schema (for example, `MutationRouteBaseSchema`); reserve SCREAMING_SNAKE_CASE for scalar/table constants.",
    },
  },
  defaultOptions: [],
  create(context) {
    const zodBindings = new Set<Variable>();
    const schemaBindings = new Set<Variable>();

    function resolvedBinding(identifier: ESTree.BindingIdentifier): Variable | null {
      return findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function recordZodBinding(identifier: ESTree.BindingIdentifier): void {
      const binding = resolvedBinding(identifier);
      if (binding !== null) zodBindings.add(binding);
    }

    function isConfirmedSchema(expression: ESTree.Expression): boolean {
      const init = unwrapExpression(expression);
      if (init.type === "Identifier") return isSchemaBinding(init);
      if (init.type !== "CallExpression" || init.callee.type !== "MemberExpression") {
        return false;
      }
      const terminal = terminalMethodName(init.callee);
      if (terminal === null || NON_SCHEMA_TERMINALS.has(terminal)) return false;
      const names = chainMemberNames(init.callee);
      if (names.length === 0) return false;
      if (isZodChain(init.callee)) {
        return ZOD_SCHEMA_FACTORIES.has(names[0] ?? "") ||
          (ZOD_FACTORY_NAMESPACES.has(names[0] ?? "") && ZOD_SCHEMA_FACTORIES.has(names[1] ?? ""));
      }
      const root = calleeChainRoot(init.callee);
      return root !== null && isSchemaBinding(root) && SCHEMA_RETURNING_METHODS.has(terminal);
    }

    function isSchemaBinding(identifier: ESTree.BindingIdentifier): boolean {
      const binding = resolvedBinding(identifier);
      return binding !== null && schemaBindings.has(binding);
    }

    function isZodChain(node: ESTree.Node): boolean {
      const root = calleeChainRoot(node);
      if (root === null) return false;
      const binding = resolvedBinding(root);
      return binding !== null && zodBindings.has(binding);
    }

    // Test and benchmark schemas are local fixtures rather than APIs.
    if (
      isTestFile(sourceOrigin(context).filename) ||
      BENCHMARK_PATH_RE.test(sourceOrigin(context).filename.replaceAll("\\", "/")) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    ) {
      return {};
    }

    return {
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" &&
              (specifier.imported.type === "Identifier"
                ? specifier.imported.name === "z"
                : specifier.imported.value === "z"))
          ) {
            recordZodBinding(specifier.local);
          }
        }
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        if (!isModuleDeclarator(node)) return;
        const init = node.init;
        if (init === null || init === undefined) return;
        if (node.id.type !== "Identifier") return;
        if (!isConfirmedSchema(init)) return;
        const binding = resolvedBinding(node.id);
        if (binding !== null) schemaBindings.add(binding);
        if (PASCAL_SCHEMA_NAME_RE.test(node.id.name)) return;

        context.report({
          node: node.id,
          messageId: "requirePascalSchema",
        });
      },
    };
  },
});

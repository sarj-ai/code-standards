/**
 * @fileoverview zod-naming-convention — a schema you cannot recognise at its use site sends every reader back to the declaration.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/zod-naming-convention.test.ts
 */

import {
  type TSESLint,
  type TSESTree,
  AST_NODE_TYPES,
  ASTUtils,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import {
  isZodModule,
  ZOD_PREFIX_RE,
  ZOD_SCHEMA_NAME_RE,
  ZOD_SUFFIX_RE,
} from "./_zod.js";

type MessageIds = "zPrefix" | "schemaSuffix" | "zodSchemaName";
type Convention = "prefix" | "suffix" | "either";
type Options = readonly [
  {
    convention?: Convention;
  }?,
];

export const zodNamingConventionDocumentation = {
  summary: "Enforce a consistent Zod schema naming convention — a `Z` prefix (`ZUser`) or a `Schema` suffix (`userSchema`); both are accepted by default.",
  rationale: "A recognizable schema name distinguishes runtime validators from ordinary values at each use site.",
  remediation: "Rename the schema with a `Z` prefix or `Schema` suffix, according to the configured convention.",
  category: "style",
  examples: [
    { id: "recognizable-schema-name", title: "Mark the value as a schema", outcome: "no-match", files: [{ path: "src/user.ts", source: "import { z } from 'zod';\nconst userSchema = z.object({ id: z.string() });" }], focusPath: "src/user.ts", expectedCount: 0, public: true },
    { id: "unmarked-schema-name", title: "Do not hide the schema behind a value name", outcome: "match", files: [{ path: "src/user.ts", source: "import { z } from 'zod';\nconst user = z.object({ id: z.string() });" }], focusPath: "src/user.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const CONVENTIONS: Record<
  Convention,
  { readonly test: RegExp; readonly messageId: MessageIds }
> = {
  prefix: { test: ZOD_PREFIX_RE, messageId: "zPrefix" },
  suffix: { test: ZOD_SUFFIX_RE, messageId: "schemaSuffix" },
  either: { test: ZOD_SCHEMA_NAME_RE, messageId: "zodSchemaName" },
};

/** Names containing "schema" are already recognisable at the use site. */
const CONTAINS_SCHEMA_RE = /schema/i;

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

/** Return the final method name in a call chain. */
const terminalMethodName = (callee: TSESTree.MemberExpression): string | null =>
  !callee.computed && callee.property.type === AST_NODE_TYPES.Identifier
    ? callee.property.name
    : null;

/** Return the identifier at the root of a fluent call/member chain. */
const calleeChainRoot = (node: TSESTree.Node): TSESTree.Identifier | null => {
  let current: TSESTree.Node = node;

  for (;;) {
    if (current.type === AST_NODE_TYPES.Identifier) {
      return current;
    }
    if (current.type === AST_NODE_TYPES.MemberExpression) {
      current = current.object;
      continue;
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      current = current.callee;
      continue;
    }
    return null;
  }
};

export default createRule<Options, MessageIds>({
  name: "zod-naming-convention",
  documentation: zodNamingConventionDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Enforce a consistent Zod schema naming convention — a `Z` prefix (`ZUser`) or a `Schema` suffix (`userSchema`); both are accepted by default.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          convention: {
            type: "string",
            enum: ["prefix", "suffix", "either"],
          },
        },
      },
    ],
    messages: {
      zPrefix: "Zod schema names should start with Z (e.g. `ZUser`)",
      schemaSuffix: "Zod schema names should end with Schema (e.g. `userSchema`)",
      zodSchemaName:
        "Zod schema names should start with Z (`ZUser`) or end with Schema (`userSchema`)",
    },
  },
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    const convention = optionsArg?.convention ?? "either";
    const { test, messageId } = CONVENTIONS[convention];
    // A schema-containing name does not satisfy an explicitly prefix-only policy.
    const acceptsSchemaWord = convention !== "prefix";
    const zodBindings = new Set<TSESLint.Scope.Variable>();

    function resolvedBinding(identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function recordZodBinding(identifier: TSESTree.Identifier): void {
      const binding = resolvedBinding(identifier);
      if (binding !== null) zodBindings.add(binding);
    }

    function isZodChain(node: TSESTree.Node): boolean {
      const root = calleeChainRoot(node);
      if (root === null) return false;
      const binding = resolvedBinding(root);
      return binding !== null && zodBindings.has(binding);
    }

    // Test and benchmark schemas are local fixtures rather than APIs.
    if (
      isTestFile(context.filename) ||
      BENCHMARK_PATH_RE.test(context.filename.replaceAll("\\", "/")) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) {
      return {};
    }

    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              (specifier.imported.type === AST_NODE_TYPES.Identifier
                ? specifier.imported.name === "z"
                : specifier.imported.value === "z"))
          ) {
            recordZodBinding(specifier.local);
          }
        }
      },
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        const init = node.init;
        if (init === null || init === undefined) return;
        if (init.type !== AST_NODE_TYPES.CallExpression) return;

        const callee = init.callee;
        if (callee.type !== AST_NODE_TYPES.MemberExpression) return;

        if (!isZodChain(callee)) return;

        // Do not apply schema naming to calls that return non-schema values.
        const terminal = terminalMethodName(callee);
        if (terminal !== null && NON_SCHEMA_TERMINALS.has(terminal)) return;

        if (node.id.type !== AST_NODE_TYPES.Identifier) return;
        if (test.test(node.id.name)) return;
        // The name already identifies a schema in any casing.
        if (acceptsSchemaWord && CONTAINS_SCHEMA_RE.test(node.id.name)) return;

        context.report({
          node: node.id,
          messageId,
        });
      },
    };
  },
});

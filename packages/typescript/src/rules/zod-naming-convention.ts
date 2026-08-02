/**
 * @fileoverview zod-naming-convention — a schema you cannot recognise at its use site sends every reader back to the declaration.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/zod-naming-convention.test.ts
 */

import { type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { ZOD_PREFIX_RE, ZOD_SCHEMA_NAME_RE, ZOD_SUFFIX_RE } from "./_zod.js";

type MessageIds = "zPrefix" | "schemaSuffix" | "zodSchemaName";
type Convention = "prefix" | "suffix" | "either";
type Options = readonly [
  {
    convention?: Convention;
  }?,
];

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
]);

/** Return the final method name in a call chain. */
const terminalMethodName = (callee: TSESTree.MemberExpression): string | null =>
  !callee.computed && callee.property.type === AST_NODE_TYPES.Identifier
    ? callee.property.name
    : null;

/** Return whether a call chain originates from the bare `z` identifier. */
const calleeChainStartsWithZ = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node = node;

  while (current.type === AST_NODE_TYPES.MemberExpression) {
    const receiver: TSESTree.Node = current.object;
    if (receiver.type === AST_NODE_TYPES.Identifier && receiver.name === "z") {
      return true;
    }
    if (receiver.type === AST_NODE_TYPES.CallExpression) {
      current = receiver.callee;
      continue;
    }
    return false;
  }

  return false;
};

export default createRule<Options, MessageIds>({
  name: "zod-naming-convention",
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

    // Test and benchmark schemas are local fixtures rather than APIs.
    if (
      isTestFile(context.filename) ||
      BENCHMARK_PATH_RE.test(context.filename.replaceAll("\\", "/")) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) {
      return {};
    }

    return {
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        const init = node.init;
        if (init === null || init === undefined) return;
        if (init.type !== AST_NODE_TYPES.CallExpression) return;

        const callee = init.callee;
        if (callee.type !== AST_NODE_TYPES.MemberExpression) return;

        if (!calleeChainStartsWithZ(callee)) return;

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

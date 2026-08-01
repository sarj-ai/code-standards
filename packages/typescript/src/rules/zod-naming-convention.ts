/**
 * @fileoverview zod-naming-convention — a schema you cannot recognise at its use site sends every reader back to the declaration.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/zod-naming-convention.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/zod-naming-convention.md
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

/**
 * Guard (c): the binding already reads as a schema. `ZOD_SUFFIX_RE` is anchored
 * and case-sensitive by design (it is also the *recogniser* other rules use), so
 * it rejects `schema`, `schema1` and `numberSchemaOptional`. Those need no
 * rename — the whole point of the convention is that a reader spots a schema at
 * the use site, and every one of them does. Accepting them here only widens what
 * this rule tolerates; it never makes the shared recogniser stricter.
 */
const CONTAINS_SCHEMA_RE = /schema/i;

/**
 * Guard (d): micro-benchmark trees. A schema declared in a benchmark is a
 * throwaway local fed to a suite a few lines below — the same "no cross-module
 * use site for the convention to serve" argument as the test-file guard, on a
 * path `isTestFile` does not match. Kept local to this rule rather than pushed
 * into `_paths` because a benchmark is not a test: it is not exempt from
 * correctness rules, only from naming ones.
 *
 * Anchored on a PATH SEGMENT so `workbench/` and `benchmarking-report.ts` are
 * unaffected.
 */
const BENCHMARK_PATH_RE = /(^|[\\/])(?:benchmarks?|bench)[\\/]/;

/**
 * Guard (b): terminal methods on a `z.…` chain whose result is NOT a schema.
 * `.parse`/`.safeParse` return a parsed value or a result envelope, the codec
 * methods return the converted value, `z.toJSONSchema` returns a plain JSON
 * object, `z.registry()` returns a registry, and `.implement()` returns a
 * function. Naming any of them `xSchema` would be a lie.
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

/** The method name a call chain ends on, e.g. `safeParse` for `z.string().safeParse(x)`. */
const terminalMethodName = (callee: TSESTree.MemberExpression): string | null =>
  !callee.computed && callee.property.type === AST_NODE_TYPES.Identifier
    ? callee.property.name
    : null;

/**
 * Walks down a (possibly chained) callee like `z.object().extend().refine()` and
 * returns `true` if the chain originates from a bare `z` identifier — i.e. the
 * outermost MemberExpression on the chain has `z` as its receiver.
 */
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
    // Guard (c) relaxes the SUFFIX spelling, so it must not apply to a team that
    // explicitly asked for prefix-only — there `userschema` really is off-convention.
    const acceptsSchemaWord = convention !== "prefix";

    // Guard (a) / (d): a schema declared in a test or a benchmark is a local
    // fixture, not an API.
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

        // Guard (b): the chain ends on a call that yields a value/result, not a schema.
        const terminal = terminalMethodName(callee);
        if (terminal !== null && NON_SCHEMA_TERMINALS.has(terminal)) return;

        if (node.id.type !== AST_NODE_TYPES.Identifier) return;
        if (test.test(node.id.name)) return;
        // Guard (c): the name already reads as a schema in any casing.
        if (acceptsSchemaWord && CONTAINS_SCHEMA_RE.test(node.id.name)) return;

        context.report({
          node: node.id,
          messageId,
        });
      },
    };
  },
});

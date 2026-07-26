/**
 * @fileoverview Enforce a consistent naming convention for Zod schemas, so a
 * schema is recognisable at its use site without chasing the declaration.
 *
 * BOTH conventions are accepted by default (`convention: "either"`):
 *   - `Z`-prefix (`ZUser = z.object({...})`) — lets a schema and its inferred
 *     type share a base name (`type User = z.infer<typeof ZUser>`).
 *   - `Schema`-suffix (`userSchema`, `SubmitFormDataSchema`) — the dominant
 *     convention in the wider Zod ecosystem and in most existing codebases.
 *
 * Defaulting to prefix-only was wrong on both counts. It contradicted the rest
 * of the plugin — `require-zod-form-validation` accepts `/Schema$|^Z[A-Z]/` as
 * "this is a Zod schema" — and on a real 42k-LOC codebase that uniformly uses
 * the suffix it declared 220 symbols non-conforming with no defect behind any of
 * them. Both regexes now come from `_zod.ts` so the two rules cannot drift
 * apart again.
 *
 * A team that wants exactly one form sets `convention: "prefix"` or
 * `convention: "suffix"`; the point of the rule is consistency, and either
 * choice delivers it.
 *
 * FALSE POSITIVES FOUND BY A 2220-FILE CORPUS SWEEP (zod / TanStack Query /
 * react-router / swr / zustand, 2026-07). The rule fired 1816 times, ALL of
 * them in the `zod` repo and none of them a defect. Three guards remove them:
 *
 *   (a) TEST FILES — 1783 / 1816 hits. A schema declared inside a test is a
 *       throwaway fixture named `a`, `b`, `t1`, read three lines below its
 *       declaration; there is no cross-module use site for the convention to
 *       serve. `zod/packages/zod/src/v4/classic/tests/index.test.ts:782`
 *       (`const a = z.lazy(() => z.string())`) is representative — that file
 *       alone contributed 70 reports.
 *   (b) TERMINAL CALLS THAT DO NOT RETURN A SCHEMA — ~280 hits. The rule keyed
 *       off "the callee chain starts at `z`", which is also true of
 *       `z.string().safeParse(x)` (a RESULT), `z.toJSONSchema(s)` (a plain JSON
 *       object), `z.registry()` (a registry), `codec.encode(v)` / `.decode(v)`
 *       (a converted VALUE) and `z.function(...).implement(fn)` (a function).
 *       Demanding a `Schema` suffix on any of those is simply wrong.
 *       `zod/packages/zod/src/v3/tests/record.test.ts:166`
 *       (`const result1 = z.record(z.any()).parse({ foo: undefined })`).
 *   (c) NAMES THAT ALREADY SAY "SCHEMA" — 421 hits. `ZOD_SUFFIX_RE` is anchored
 *       AND case-sensitive, so `schema`, `schema1` and `numberSchemaOptional`
 *       were all declared non-conforming despite being unmistakable at a
 *       glance. `schema` alone accounts for 371 reports, e.g.
 *       `zod/packages/treeshake/zod-string.ts:3`. This widens only the ACCEPT
 *       side, so it cannot make `require-zod-form-validation` — which uses the
 *       shared `_zod.ts` recognisers to accept a receiver — reject anything it
 *       previously accepted.
 */

import { ESLintUtils, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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

    // Guard (a): a schema declared in a test is a local fixture, not an API.
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
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

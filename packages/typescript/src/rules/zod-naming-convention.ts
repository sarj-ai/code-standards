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
 */

import { ESLintUtils, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

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
    const { test, messageId } = CONVENTIONS[optionsArg?.convention ?? "either"];

    return {
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        const init = node.init;
        if (init === null || init === undefined) return;
        if (init.type !== AST_NODE_TYPES.CallExpression) return;

        const callee = init.callee;
        if (callee.type !== AST_NODE_TYPES.MemberExpression) return;

        if (!calleeChainStartsWithZ(callee)) return;

        if (node.id.type !== AST_NODE_TYPES.Identifier) return;
        if (test.test(node.id.name)) return;

        context.report({
          node: node.id,
          messageId,
        });
      },
    };
  },
});

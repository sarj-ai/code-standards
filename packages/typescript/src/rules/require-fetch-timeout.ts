/**
 * @fileoverview Require an abort `signal` on global `fetch()` calls. A fetch
 * without a timeout hangs forever when the upstream stalls, tying up the
 * request (or worker) with it. Pass `AbortSignal.timeout(ms)` — or a signal
 * from an `AbortController` — in the init object.
 *
 * Scope is deliberately narrow to keep false positives near zero:
 *   - Only bare `fetch(...)` identifier calls are checked. Member calls like
 *     Cloudflare Workers service bindings (`env.MY_SERVICE.fetch(...)`) or
 *     custom clients (`client.fetch(...)`) are skipped.
 *   - A call is flagged only when the init argument is absent, or is an
 *     object literal that provably lacks `signal` (no spread, no `signal`
 *     key). Anything dynamic (an identifier, a call result, a spread) is
 *     assumed to carry a signal.
 *
 * Wrapper modules that centralize timeout handling can be exempted via the
 * `allowIn` glob-pattern option.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "missingSignal";
type Options = readonly [
  {
    allowIn?: readonly string[];
  }?,
];

function matchesAnyPattern(
  filename: string,
  patterns: readonly string[],
): boolean {
  for (const pattern of patterns) {
    // Convert minimatch-ish globs to regex: ** -> .*, * -> [^/\\]*
    const regexSource = pattern
      .replace(/[.+^${}()|[\]\\]/g, "\\$&")
      .replace(/\*\*/g, "::DOUBLESTAR::")
      .replace(/\*/g, "[^/\\\\]*")
      .replace(/::DOUBLESTAR::/g, ".*");
    if (new RegExp(`^${regexSource}$`).test(filename)) {
      return true;
    }
  }
  return false;
}

/**
 * True when the init argument provably lacks an abort signal: it is an object
 * literal with no `signal` property and no spread element. Any other shape
 * (identifier, call, spread, conditional, ...) may carry a signal, so it is
 * treated as safe.
 */
function initProvablyLacksSignal(init: TSESTree.CallExpressionArgument): boolean {
  if (init.type !== AST_NODE_TYPES.ObjectExpression) {
    return false;
  }
  for (const prop of init.properties) {
    if (prop.type === AST_NODE_TYPES.SpreadElement) {
      return false;
    }
    if (
      (prop.key.type === AST_NODE_TYPES.Identifier &&
        prop.key.name === "signal") ||
      (prop.key.type === AST_NODE_TYPES.Literal && prop.key.value === "signal")
    ) {
      return false;
    }
    // A computed key could be "signal" at runtime; assume it is.
    if (prop.computed) {
      return false;
    }
  }
  return true;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "require-fetch-timeout",
  meta: {
    type: "problem",
    docs: {
      description:
        "Require an abort `signal` (e.g. `AbortSignal.timeout(ms)`) on global `fetch()` calls so stalled upstreams cannot hang the caller forever.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          allowIn: {
            type: "array",
            items: { type: "string" },
          },
        },
      },
    ],
    messages: {
      missingSignal:
        "This `fetch()` has no abort `signal` — a stalled upstream will hang it forever. Pass `{ signal: AbortSignal.timeout(ms) }` or a signal from an AbortController.",
    },
  },
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    const allowIn = optionsArg?.allowIn ?? [];
    if (allowIn.length > 0 && matchesAnyPattern(context.filename, allowIn)) {
      return {};
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (
          node.callee.type !== AST_NODE_TYPES.Identifier ||
          node.callee.name !== "fetch"
        ) {
          return;
        }

        const init = node.arguments[1];
        if (init === undefined || initProvablyLacksSignal(init)) {
          context.report({ node, messageId: "missingSignal" });
        }
      },
    };
  },
});

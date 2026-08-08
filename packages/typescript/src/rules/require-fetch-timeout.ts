/**
 * @fileoverview require-fetch-timeout — a `fetch` with no signal hangs for as long as the upstream stalls, holding the caller open with it.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/require-fetch-timeout.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "missingSignal";
type Options = readonly [
  {
    allowIn?: readonly string[];
  }?,
];

/** The explicit-global receivers of `<obj>.fetch(...)`. */
const GLOBAL_OBJECTS: ReadonlySet<string> = new Set([
  "globalThis",
  "window",
  "self",
]);

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

/** True for a string or template literal — a URL spelled inline. */
function isStringish(node: TSESTree.CallExpressionArgument): boolean {
  return (
    (node.type === AST_NODE_TYPES.Literal && typeof node.value === "string") ||
    node.type === AST_NODE_TYPES.TemplateLiteral
  );
}

export default createRule<Options, MessageIds>({
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
            description:
              "Glob patterns for wrapper modules exempt from the rule. Matched against the ABSOLUTE file path, so anchor with a `**/` prefix (e.g. `**/http-client.ts`).",
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
    // `isTestFile` knows jscodeshift's `__testfixtures__/` spelling, so the
    // local pattern this rule used to keep for it decided nothing.
    if (isTestFile(context.filename) || isScriptFile(context.filename)) {
      return {};
    }
    const allowIn = optionsArg?.allowIn ?? [];
    if (allowIn.length > 0 && matchesAnyPattern(context.filename, allowIn)) {
      return {};
    }

    /** True when `identifier` resolves to the global (no local binding shadows it). */
    function resolvesToGlobal(identifier: TSESTree.Identifier): boolean {
      const scope = context.sourceCode.getScope(identifier);
      const variable = ASTUtils.findVariable(scope, identifier.name);
      return variable === null || variable.defs.length === 0;
    }

    /** True for `fetch(...)` / `globalThis.fetch(...)` / `window.fetch(...)` /
     * `self.fetch(...)` where the receiver resolves to the global scope. */
    function isGlobalFetchCall(callee: TSESTree.Expression): boolean {
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return callee.name === "fetch" && resolvesToGlobal(callee);
      }
      return (
        callee.type === AST_NODE_TYPES.MemberExpression &&
        !callee.computed &&
        callee.property.type === AST_NODE_TYPES.Identifier &&
        callee.property.name === "fetch" &&
        callee.object.type === AST_NODE_TYPES.Identifier &&
        GLOBAL_OBJECTS.has(callee.object.name) &&
        resolvesToGlobal(callee.object)
      );
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isGlobalFetchCall(node.callee)) {
          return;
        }

        // Proxy passthrough: a lone non-string argument is a Request (or
        // equivalent) being forwarded — the inbound request owns the
        // lifetime, and a fresh signal cannot be attached without an init.
        const [first, init] = node.arguments;
        if (node.arguments.length === 1 && first !== undefined && !isStringish(first)) {
          return;
        }

        if (init === undefined || initProvablyLacksSignal(init)) {
          context.report({ node, messageId: "missingSignal" });
        }
      },
    };
  },
});

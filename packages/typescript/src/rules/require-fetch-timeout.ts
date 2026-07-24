/**
 * @fileoverview Require an abort `signal` on global `fetch()` calls. A fetch
 * without a timeout hangs forever when the upstream stalls, tying up the
 * request (or worker) with it. Pass `AbortSignal.timeout(ms)` — or a signal
 * from an `AbortController` — in the init object.
 *
 * Scope is deliberately narrow to keep false positives near zero:
 *   - Only calls that resolve to the *global* `fetch` are checked: bare
 *     `fetch(...)` (unless a local binding — import, parameter, variable —
 *     shadows it) plus the explicit global spellings `globalThis.fetch(...)`,
 *     `window.fetch(...)`, and `self.fetch(...)`. Other member calls like
 *     Cloudflare Workers service bindings (`env.MY_SERVICE.fetch(...)`) or
 *     custom clients (`client.fetch(...)`) are skipped.
 *   - A call is flagged only when the init argument is absent, or is an
 *     object literal that provably lacks `signal` (no spread, no `signal`
 *     key). Anything dynamic (an identifier, a call result, a spread) is
 *     assumed to carry a signal.
 *   - Single-argument calls whose argument is not a string/template literal
 *     are skipped: `fetch(request)` / `fetch(c.req.raw.clone())` are proxy
 *     passthroughs (Workers idiom) where the inbound Request governs the
 *     lifetime and attaching a fresh signal is impossible or wrong.
 *   - Test files and one-off tooling (`scripts/**`, `*.mjs`) are skipped —
 *     dev scripts die with the terminal, so hang-hardening is noise there.
 *
 * Wrapper modules that centralize timeout handling can be exempted via the
 * `allowIn` glob-pattern option.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  ESLintUtils,
  type TSESTree,
} from "@typescript-eslint/utils";

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

/** True for a string or template literal — a URL spelled inline. */
function isStringish(node: TSESTree.CallExpressionArgument): boolean {
  return (
    (node.type === AST_NODE_TYPES.Literal && typeof node.value === "string") ||
    node.type === AST_NODE_TYPES.TemplateLiteral
  );
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
      // Unresolved → implicit global. Resolved with zero defs → declared
      // global (languageOptions.globals). Any def is a local shadow.
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

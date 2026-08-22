/**
 * @fileoverview require-fetch-timeout — a `fetch` with no signal hangs for as long as the upstream stalls, holding the caller open with it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-fetch-timeout.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "missingSignal";
type Options = readonly [
  {
    allowIn?: readonly string[];
  }?,
];

export const REQUIRE_FETCH_TIMEOUT_DOCUMENTATION = {
  summary: "Require an abort `signal` (e.g. `AbortSignal.timeout(ms)`) on global `fetch()` calls so stalled upstreams cannot hang the caller forever.",
  rationale: "An unbounded request can occupy work indefinitely when an upstream stalls.",
  remediation: "Pass an abort signal, such as `AbortSignal.timeout(ms)`, in the fetch init.",
  category: "correctness",
  examples: [
    { id: "bounded-fetch", title: "Bound the request", outcome: "no-match", files: [{ path: "src/client.ts", source: "await fetch(url, { signal: AbortSignal.timeout(5000) });" }], focusPath: "src/client.ts", expectedCount: 0, public: true },
    { id: "unbounded-fetch", title: "Do not leave fetch unbounded", outcome: "match", files: [{ path: "src/client.ts", source: "await fetch('https://api.example.com/items');" }], focusPath: "src/client.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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

/** True for a URL spelled inline rather than a forwarded Request. */
function isInlineUrl(
  node: TSESTree.CallExpressionArgument,
  resolvesToGlobal: (identifier: TSESTree.Identifier) => boolean,
): boolean {
  return (
    (node.type === AST_NODE_TYPES.Literal && typeof node.value === "string") ||
    node.type === AST_NODE_TYPES.TemplateLiteral ||
    (node.type === AST_NODE_TYPES.NewExpression &&
      node.callee.type === AST_NODE_TYPES.Identifier &&
      node.callee.name === "URL" &&
      resolvesToGlobal(node.callee))
  );
}

export default createRule<Options, MessageIds>({
  name: "require-fetch-timeout",
  documentation: REQUIRE_FETCH_TIMEOUT_DOCUMENTATION,
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

    /** Prove a same-scope const object cannot acquire a signal before use. */
    function localConstInitProvablyLacksSignal(
      identifier: TSESTree.Identifier,
    ): boolean {
      const variable = ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
      if (variable?.defs.length !== 1) return false;
      const definition = variable.defs[0];
      if (
        definition?.type !== "Variable" ||
        definition.parent.kind !== "const" ||
        definition.node.init?.type !== AST_NODE_TYPES.ObjectExpression ||
        !initProvablyLacksSignal(definition.node.init)
      ) {
        return false;
      }
      for (const reference of variable.references) {
        const ref = reference.identifier;
        if (ref === identifier || ref === definition.name) continue;
        const member = ref.parent;
        if (
          member.type !== AST_NODE_TYPES.MemberExpression ||
          member.object !== ref ||
          member.computed ||
          member.property.type !== AST_NODE_TYPES.Identifier ||
          member.property.name === "signal" ||
          member.parent.type !== AST_NODE_TYPES.AssignmentExpression ||
          member.parent.left !== member
        ) {
          return false;
        }
      }
      return true;
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
        if (
          node.arguments.length === 1 &&
          first !== undefined &&
          !isInlineUrl(first, resolvesToGlobal)
        ) {
          return;
        }

        if (
          init === undefined ||
          initProvablyLacksSignal(init) ||
          (init.type === AST_NODE_TYPES.Identifier &&
            localConstInitProvablyLacksSignal(init))
        ) {
          context.report({ node, messageId: "missingSignal" });
        }
      },
    };
  },
});

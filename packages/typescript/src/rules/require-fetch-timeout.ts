/**
 * @fileoverview require-fetch-timeout — a `fetch` with no signal hangs for as long as the upstream stalls, holding the caller open with it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-fetch-timeout.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "missingSignal";
type Options = readonly [
  {
    allowIn?: readonly string[];
  }?,
];

export const REQUIRE_FETCH_TIMEOUT_DOCUMENTATION = {
  summary: "Require an explicit abort signal on locally analyzable global fetch calls.",
  rationale: "An unbounded request can occupy work indefinitely when an upstream stalls.",
  remediation: "Pass an abort signal, such as `AbortSignal.timeout(ms)`, in the fetch init.",
  category: "correctness",
  limitations: ["Signal presence establishes an explicit cancellation path, not a guaranteed timeout. Literal null, global undefined, and void 0 do not provide a signal. Unknown spreads and dynamic values are not inferred. Forwarded Request objects can carry an existing signal."],
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

function initProvablyLacksSignal(
  init: ESTree.Argument,
  resolvesToGlobal: (identifier: ESTree.BindingIdentifier) => boolean,
): boolean {
  if (init.type !== "ObjectExpression") return false;
  let lacksSignal = true;
  for (const prop of init.properties) {
    if (prop.type === "SpreadElement") {
      lacksSignal = false;
      continue;
    }
    const isSignal =
      (!prop.computed && prop.key.type === "Identifier" && prop.key.name === "signal") ||
      (prop.key.type === "Literal" && prop.key.value === "signal");
    if (isSignal) {
      const value = prop.value;
      lacksSignal = prop.kind === "init" && !prop.method && (
        (value.type === "Literal" && value.value === null) ||
        (value.type === "Identifier" && value.name === "undefined" && resolvesToGlobal(value)) ||
        (value.type === "UnaryExpression" && value.operator === "void" && value.argument.type === "Literal" && value.argument.value === 0)
      );
    } else if (prop.computed && prop.key.type !== "Literal") {
      lacksSignal = false;
    }
  }
  return lacksSignal;
}

/** True for a URL spelled inline rather than a forwarded Request. */
function isInlineUrl(
  node: ESTree.Argument,
  resolvesToGlobal: (identifier: ESTree.BindingIdentifier) => boolean,
): boolean {
  return (
    (node.type === "Literal" && typeof node.value === "string") ||
    node.type === "TemplateLiteral" ||
    (node.type === "NewExpression" &&
      node.callee.type === "Identifier" &&
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
        "Require an explicit abort signal on locally analyzable global fetch calls.",
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
        "This `fetch()` has no explicit abort signal. Pass `AbortSignal.timeout(ms)` for a deadline, or an owner-managed signal for cancellation.",
    },
  },
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    // `isTestFile` knows jscodeshift's `__testfixtures__/` spelling, so the
    // local pattern this rule used to keep for it decided nothing.
    if (isTestFile(sourceOrigin(context).filename) || isScriptFile(sourceOrigin(context).filename)) {
      return {};
    }
    const allowIn = optionsArg?.allowIn ?? [];
    if (allowIn.length > 0 && matchesAnyPattern(sourceOrigin(context).filename, allowIn)) {
      return {};
    }

    /** True when `identifier` resolves to the global (no local binding shadows it). */
    function resolvesToGlobal(identifier: ESTree.BindingIdentifier): boolean {
      const scope = context.sourceCode.getScope(identifier);
      const variable = findVariable(scope, identifier.name);
      return variable === null || variable.defs.length === 0;
    }

    /** True for `fetch(...)` / `globalThis.fetch(...)` / `window.fetch(...)` /
     * `self.fetch(...)` where the receiver resolves to the global scope. */
    function isGlobalFetchCall(callee: ESTree.Expression): boolean {
      if (callee.type === "Identifier") {
        return callee.name === "fetch" && resolvesToGlobal(callee);
      }
      return (
        callee.type === "MemberExpression" &&
        !callee.computed &&
        callee.property.type === "Identifier" &&
        callee.property.name === "fetch" &&
        callee.object.type === "Identifier" &&
        GLOBAL_OBJECTS.has(callee.object.name) &&
        resolvesToGlobal(callee.object)
      );
    }

    /** Prove a same-scope const object cannot acquire a signal before use. */
    function localConstInitProvablyLacksSignal(
      identifier: ESTree.BindingIdentifier,
    ): boolean {
      const variable = findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
      if (variable?.defs.length !== 1) return false;
      const definition = variable.defs[0];
      if (
        definition?.type !== "Variable" || definition.node.type !== "VariableDeclarator" ||
        definition.parent?.type !== "VariableDeclaration" || definition.parent.kind !== "const" ||
        definition.node.init?.type !== "ObjectExpression" ||
        !initProvablyLacksSignal(definition.node.init, resolvesToGlobal)
      ) {
        return false;
      }
      for (const reference of variable.references) {
        const ref = reference.identifier;
        if (ref === identifier || ref === definition.name) continue;
        const member = ref.parent;
        if (
          member.type !== "MemberExpression" ||
          member.object !== ref ||
          member.computed ||
          member.property.type !== "Identifier" ||
          member.property.name === "signal" ||
          member.parent?.type !== "AssignmentExpression" ||
          member.parent.left !== member
        ) {
          return false;
        }
      }
      return true;
    }

    function isForwardedRequest(argument: ESTree.Argument): boolean {
      let value = argument;
      if (value.type === "Identifier") {
        const binding = findVariable(context.sourceCode.getScope(value), value.name);
        const definition = binding?.defs.length === 1 ? binding.defs[0] : undefined;
        if (definition?.type !== "Variable" || definition.node.type !== "VariableDeclarator" || definition.parent?.type !== "VariableDeclaration" || definition.parent.kind !== "const" || definition.node.init === null || binding?.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
        value = definition.node.init;
      }
      return value.type === "NewExpression" && value.callee.type === "Identifier" && value.callee.name === "Request" && resolvesToGlobal(value.callee);
    }

    return {
      CallExpression(node: ESTree.CallExpression): void {
        if (!isGlobalFetchCall(node.callee)) {
          return;
        }

        // Proxy passthrough: a lone non-string argument is a Request (or
        // equivalent) being forwarded — the inbound request owns the
        // lifetime, and a fresh signal cannot be attached without an init.
        const [first, init] = node.arguments;
        if (
          first !== undefined &&
          ((node.arguments.length === 1 && !isInlineUrl(first, resolvesToGlobal)) || isForwardedRequest(first))
        ) {
          return;
        }

        if (
          init === undefined ||
          initProvablyLacksSignal(init, resolvesToGlobal) ||
          (init.type === "Identifier" &&
            localConstInitProvablyLacksSignal(init))
        ) {
          context.report({ node, messageId: "missingSignal" });
        }
      },
    };
  },
});

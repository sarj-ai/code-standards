/**
 * @fileoverview require-fetch-timeout — a `fetch` with no signal hangs for as long as the upstream stalls, holding the caller open with it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-fetch-timeout.test.ts
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { unwrapExpression } from "./_unwrap-expression.js";
import { nativeFetchReference } from "./_native-fetch-reference.js";
import { staticPropertyName } from "./_static-string.js";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isScriptFile, isTestFile, matchesAnyPattern } from "./_paths.js";

type MessageIds = "missingSignal";
type EmptySignal = "null" | "undefined";
type SignalState = EmptySignal | "absent" | "unknown";
type Options = readonly [
  {
    allowIn?: readonly string[];
  }?,
];

export const REQUIRE_FETCH_TIMEOUT_DOCUMENTATION = {
  summary:
    "Require an explicit abort signal on locally analyzable global fetch calls.",
  rationale:
    "An unbounded request can occupy work indefinitely when an upstream stalls.",
  remediation:
    "Pass an abort signal, such as `AbortSignal.timeout(ms)`, in the fetch init.",
  category: "correctness",
  limitations: [
    "Signal presence establishes an explicit cancellation path, not a guaranteed timeout. Literal null, global undefined, and void 0 do not provide a signal. Erased TypeScript wrappers preserve the same analysis. Unknown spreads and dynamic values are not inferred. Forwarded Request objects retain their signal unless an init explicitly resets it to null.",
    "Unshadowed native fetch members and bounded stable const aliases or destructuring are recognized. Reassigned, defaulted and unknown aliases and arbitrary forwarding functions are excluded.",
    "Visible writes, callable escapes, whole-global escapes and mutation capabilities anywhere in the file invalidate native fetch identity, including earlier captures. Known unrelated global member writes and typeof global checks do not. Static constructor members and destructuring projections invalidate the proof; indirect reflection and external monkeypatches are not inferred.",
    "Accessors and unproved prototypes are excluded because native option conversion can attach or replace a signal before it is read.",
  ],
  examples: [
    {
      id: "bounded-fetch",
      title: "Bound the request",
      outcome: "no-match",
      files: [
        {
          path: "src/client.ts",
          source: "await fetch(url, { signal: AbortSignal.timeout(5000) });",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "unbounded-fetch",
      title: "Do not leave fetch unbounded",
      outcome: "match",
      files: [
        {
          path: "src/client.ts",
          source: "await fetch('https://api.example.com/items');",
        },
      ],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;


function emptySignal(
  expression: TSESTree.Node,
  resolvesToGlobal: (identifier: TSESTree.Identifier) => boolean,
): EmptySignal | null {
  const value = unwrapExpression(expression);
  if (value.type === AST_NODE_TYPES.Literal && value.value === null)
    return "null";
  if (
    value.type === AST_NODE_TYPES.Identifier &&
    value.name === "undefined" &&
    resolvesToGlobal(value)
  )
    return "undefined";
  if (
    value.type === AST_NODE_TYPES.UnaryExpression &&
    value.operator === "void"
  ) {
    const argument = unwrapExpression(value.argument);
    if (argument.type === AST_NODE_TYPES.Literal && argument.value === 0)
      return "undefined";
  }
  return null;
}

function initSignalState(
  init: TSESTree.CallExpressionArgument,
  resolvesToGlobal: (identifier: TSESTree.Identifier) => boolean,
  sourceCode: Readonly<TSESLint.SourceCode>,
): SignalState {
  init = unwrapExpression(init);
  if (init.type !== AST_NODE_TYPES.ObjectExpression) return "unknown";
  let state: SignalState = "absent";
  for (const prop of init.properties) {
    if (prop.type === AST_NODE_TYPES.SpreadElement) {
      state = "unknown";
      continue;
    }
    if (prop.kind !== "init" || hasUnprovedPrototype(prop)) return "unknown";
    const name = staticPropertyName(prop, sourceCode);
    if (name === "signal") {
      state = !prop.method
        ? (emptySignal(prop.value, resolvesToGlobal) ?? "unknown")
        : "unknown";
    } else if (
      !prop.computed &&
      name === "__proto__" &&
      state === "absent"
    ) {
      state = "unknown";
    } else if (prop.computed && name === null) {
      state = "unknown";
    }
  }
  return state;
}

function hasUnprovedPrototype(property: TSESTree.Property): boolean {
  if (
    property.computed ||
    property.method ||
    property.shorthand ||
    ASTUtils.getPropertyName(property) !== "__proto__"
  )
    return false;
  const prototype = unwrapExpression(property.value);
  if (prototype.type === AST_NODE_TYPES.Literal && prototype.value === null)
    return false;
  if (prototype.type !== AST_NODE_TYPES.ObjectExpression) return true;
  return prototype.properties.some(
    (member) =>
      member.type === AST_NODE_TYPES.SpreadElement ||
      member.kind !== "init" ||
      (!member.computed && ASTUtils.getPropertyName(member) === "__proto__") ||
      (member.computed && member.key.type !== AST_NODE_TYPES.Literal),
  );
}

/** True for a URL spelled inline rather than a forwarded Request. */
function isInlineUrl(
  node: TSESTree.CallExpressionArgument,
  resolvesToGlobal: (identifier: TSESTree.Identifier) => boolean,
): boolean {
  node = unwrapExpression(node);
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
    if (isTestFile(context) || isScriptFile(context)) {
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

    /** Prove a same-scope const object cannot acquire a signal before use. */
    function localConstInitSignalState(
      identifier: TSESTree.Identifier,
    ): SignalState {
      const variable = ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
      if (variable?.defs.length !== 1) return "unknown";
      const definition = variable.defs[0];
      if (
        definition?.type !== "Variable" ||
        definition.parent.kind !== "const" ||
        definition.node.init === null ||
        unwrapExpression(definition.node.init).type !==
          AST_NODE_TYPES.ObjectExpression
      ) {
        return "unknown";
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
          member.property.name === "__proto__" ||
          member.parent.type !== AST_NODE_TYPES.AssignmentExpression ||
          member.parent.left !== member
        ) {
          return "unknown";
        }
      }
      return initSignalState(definition.node.init, resolvesToGlobal, context.sourceCode);
    }

    function isForwardedRequest(
      argument: TSESTree.CallExpressionArgument,
    ): boolean {
      let value = unwrapExpression(argument);
      if (value.type === AST_NODE_TYPES.Identifier) {
        const binding = ASTUtils.findVariable(
          context.sourceCode.getScope(value),
          value.name,
        );
        const definition =
          binding?.defs.length === 1 ? binding.defs[0] : undefined;
        if (
          definition?.type !== "Variable" ||
          definition.parent.kind !== "const" ||
          definition.node.init === null ||
          binding?.references.some(
            (reference) => reference.isWrite() && reference.init !== true,
          )
        )
          return false;
        value = unwrapExpression(definition.node.init);
      }
      if (value.type !== AST_NODE_TYPES.NewExpression) return false;
      const callee = unwrapExpression(value.callee);
      return (
        callee.type === AST_NODE_TYPES.Identifier &&
        callee.name === "Request" &&
        resolvesToGlobal(callee)
      );
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        if (!nativeFetchReference(unwrappedNodeCallee, context.sourceCode)) {
          return;
        }

        // Proxy passthrough: a lone non-string argument is a Request (or
        // equivalent) being forwarded — the inbound request owns the
        // lifetime, and a fresh signal cannot be attached without an init.
        const [first, rawInit] = node.arguments;
        const init =
          rawInit === undefined ? undefined : unwrapExpression(rawInit);
        const state =
          init === undefined
            ? "unknown"
            : init.type === AST_NODE_TYPES.Identifier
              ? localConstInitSignalState(init)
              : initSignalState(init, resolvesToGlobal, context.sourceCode);
        if (
          first !== undefined &&
          ((node.arguments.length === 1 &&
            !isInlineUrl(first, resolvesToGlobal)) ||
            (isForwardedRequest(first) && state !== "null"))
        ) {
          return;
        }

        if (
          init === undefined ||
          state !== "unknown" ||
          (first !== undefined &&
            isInlineUrl(first, resolvesToGlobal) &&
            emptySignal(init, resolvesToGlobal) !== null)
        ) {
          context.report({ node, messageId: "missingSignal" });
        }
      },
    };
  },
});

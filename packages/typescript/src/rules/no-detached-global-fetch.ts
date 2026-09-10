/**
 * @fileoverview no-detached-global-fetch — a host-provided fetch may require its global receiver.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-detached-global-fetch.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "detachedGlobalFetch";
type Options = readonly [];

export const NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION = {
  summary: "Preserve the receiver when the ambient global fetch is used as a value.",
  rationale: "Some host runtimes expose fetch as a receiver-sensitive callable, so storing or passing the bare function can fail only after deployment.",
  remediation: "Forward through `(input, init) => globalThis.fetch(input, init)` or bind the callable to its global receiver.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "The rule recognizes the unshadowed ambient fetch, globalThis.fetch, self.fetch, and window.fetch syntactically.",
    "Direct calls, explicit receiver binding or invocation, tests, scripts, generated files, and locally defined fetch implementations are excluded.",
    "The rule does not follow aliases or prove which JavaScript host executes a file.",
  ],
  examples: [
    {
      id: "forwarded-global-fetch",
      title: "Forward through the global receiver",
      outcome: "no-match",
      files: [{ path: "src/client.ts", source: "const request = (input: RequestInfo | URL, init?: RequestInit) => globalThis.fetch(input, init);" }],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "detached-global-fetch",
      title: "Do not detach the ambient fetch",
      outcome: "match",
      files: [{ path: "src/client.ts", source: "class Client { constructor(private readonly request: typeof fetch = fetch) {} }" }],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "self", "window"]);
const RECEIVER_METHODS: ReadonlySet<string> = new Set(["apply", "bind", "call"]);

export default createRule<Options, MessageIds>({
  name: "no-detached-global-fetch",
  documentation: NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: "Preserve the receiver when the ambient global fetch is used as a value." },
    schema: [],
    messages: {
      detachedGlobalFetch:
        "The ambient global `fetch` is being detached from its receiver. Forward through `globalThis.fetch(...)` or bind it to the global receiver.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (
      isTestFile(context.filename) ||
      isScriptFile(context.filename) ||
      isGeneratedFile(context.filename, sourceCode.text)
    ) {
      return {};
    }

    function resolvesToGlobal(identifier: TSESTree.Identifier): boolean {
      const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
      return variable === null || variable.defs.length === 0;
    }

    function isGlobalReceiver(node: TSESTree.Node): node is TSESTree.Identifier {
      return (
        node.type === AST_NODE_TYPES.Identifier &&
        GLOBAL_RECEIVERS.has(node.name) &&
        resolvesToGlobal(node)
      );
    }

    function isTypePosition(node: TSESTree.Node): boolean {
      let parent: TSESTree.Node | undefined = node.parent;
      while (parent !== undefined) {
        if (parent.type === AST_NODE_TYPES.TSTypeQuery) return true;
        if (!parent.type.startsWith("TS")) return false;
        parent = parent.parent;
      }
      return false;
    }

    function receiverOf(node: TSESTree.Identifier | TSESTree.MemberExpression): TSESTree.Identifier | null {
      if (node.type === AST_NODE_TYPES.Identifier) return null;
      return isGlobalReceiver(node.object) ? node.object : null;
    }

    function isDirectCall(node: TSESTree.Identifier | TSESTree.MemberExpression): boolean {
      return node.parent.type === AST_NODE_TYPES.CallExpression && node.parent.callee === node;
    }

    function isSafeExplicitReceiverUse(
      node: TSESTree.Identifier | TSESTree.MemberExpression,
    ): boolean {
      const member = node.parent;
      if (
        member.type !== AST_NODE_TYPES.MemberExpression ||
        member.object !== node ||
        member.computed ||
        member.property.type !== AST_NODE_TYPES.Identifier ||
        !RECEIVER_METHODS.has(member.property.name)
      ) {
        return false;
      }
      const invocation = member.parent;
      if (invocation.type !== AST_NODE_TYPES.CallExpression || invocation.callee !== member) {
        return false;
      }
      const receiver = invocation.arguments[0];
      if (receiver === undefined || receiver.type === AST_NODE_TYPES.SpreadElement) return false;
      if (node.type === AST_NODE_TYPES.MemberExpression) {
        const original = receiverOf(node);
        return original !== null && receiver.type === AST_NODE_TYPES.Identifier && receiver.name === original.name;
      }
      return isGlobalReceiver(receiver);
    }

    function reportIfDetached(node: TSESTree.Identifier | TSESTree.MemberExpression): void {
      if (isTypePosition(node) || isDirectCall(node) || isSafeExplicitReceiverUse(node)) return;
      context.report({ node, messageId: "detachedGlobalFetch" });
    }

    return {
      Identifier(node): void {
        if (node.name !== "fetch" || !resolvesToGlobal(node)) return;
        const parent = node.parent;
        if (
          parent.type === AST_NODE_TYPES.MemberExpression &&
          parent.property === node
        ) {
          return;
        }
        if (
          parent.type === AST_NODE_TYPES.Property &&
          parent.key === node &&
          !parent.computed &&
          !parent.shorthand
        ) {
          return;
        }
        reportIfDetached(node);
      },
      "MemberExpression[computed=false]"(node: TSESTree.MemberExpression): void {
        if (
          node.property.type !== AST_NODE_TYPES.Identifier ||
          node.property.name !== "fetch" ||
          !isGlobalReceiver(node.object)
        ) {
          return;
        }
        reportIfDetached(node);
      },
    };
  },
});

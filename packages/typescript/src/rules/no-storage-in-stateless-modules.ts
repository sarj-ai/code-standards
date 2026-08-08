/**
 * @fileoverview no-storage-in-stateless-modules — private storage inside a module a team declared stateless diverges from the system of record, silently.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-storage-in-stateless-modules.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

type MessageIds = "storageInStatelessModule";

export interface RuleOptions {
  readonly modules?: readonly string[];
  readonly methods?: readonly string[];
}

type Options = readonly [RuleOptions?];

const DEFAULT_METHODS: readonly string[] = [
  "prepare",
  "put",
  "getWithMetadata",
];

const MIN_ARGUMENTS: ReadonlyMap<string, number> = new Map([["put", 2]]);

/** Compile regex sources, skipping malformed entries rather than throwing. */
function compile(patterns: readonly string[]): RegExp[] {
  const compiled: RegExp[] = [];
  for (const pattern of patterns) {
    try {
      compiled.push(new RegExp(pattern));
    } catch {
      // Skip the malformed entry; the remaining patterns still apply.
    }
  }
  return compiled;
}

/** The flagged storage method name of `receiver.method(...)`, or null. */
function storageMethodName(
  node: TSESTree.CallExpression,
  methods: ReadonlySet<string>,
): string | null {
  const callee = node.callee;
  if (
    callee.type !== AST_NODE_TYPES.MemberExpression ||
    callee.computed ||
    callee.property.type !== AST_NODE_TYPES.Identifier
  ) {
    return null;
  }
  const name = callee.property.name;
  if (!methods.has(name)) {
    return null;
  }
  if (node.arguments.length < (MIN_ARGUMENTS.get(name) ?? 1)) {
    return null;
  }
  return name;
}

export default createRule<Options, MessageIds>({
  name: "no-storage-in-stateless-modules",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow SQL or key/value access inside modules a team has declared stateless; derive state from the systems of record instead. No-op until `modules` is configured.",
    },
    schema: [
      {
        type: "object",
        properties: {
          modules: {
            type: "array",
            items: { type: "string" },
            description:
              "Regex sources matched against the filename. Empty (the default) disables the rule.",
          },
          methods: {
            type: "array",
            items: { type: "string" },
            description: "Storage method names to flag. Replaces the defaults.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      storageInStatelessModule:
        "`{{method}}()` reaches for private storage inside a module declared stateless. Derive the state from a read against the system of record, or from a marker in the artefact this feature already produces.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    const modules = options?.modules ?? [];
    if (modules.length === 0) {
      return {};
    }

    const scoped = compile(modules);
    if (!scoped.some((re) => re.test(context.filename))) {
      return {};
    }

    const methods = new Set(options?.methods ?? DEFAULT_METHODS);

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const method = storageMethodName(node, methods);
        if (method !== null) {
          context.report({
            node,
            messageId: "storageInStatelessModule",
            data: { method },
          });
        }
      },
    };
  },
});

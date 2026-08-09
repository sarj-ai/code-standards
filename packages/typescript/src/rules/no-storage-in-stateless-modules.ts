/**
 * @fileoverview no-storage-in-stateless-modules — private storage inside a module a team declared stateless diverges from the system of record, silently.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-storage-in-stateless-modules.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

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

export const noStorageInStatelessModulesDocumentation = {
  summary: "Disallow SQL or key/value access inside configured stateless modules; derive state from a system of record instead.",
  rationale: "Private storage in a stateless workflow creates another source of truth that can silently diverge.",
  remediation: "Read from the system of record or derive state from an artifact the workflow already produces.",
  category: "architecture",
  limitations: ["The rule is disabled until module path patterns are configured and recognizes only configured storage method names."],
  examples: [
    { id: "system-of-record", title: "Read from the system of record", outcome: "no-match", files: [{ path: "src/engineer-digest/post.ts", source: "const issues = await linear.listIssues();" }], focusPath: "src/engineer-digest/post.ts", expectedCount: 0, public: true },
    { id: "private-storage", title: "Do not write private state in a stateless module", outcome: "match", files: [{ path: "src/engineer-digest/post.ts", source: "await kv.put('digest:last', timestamp);" }], focusPath: "src/engineer-digest/post.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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
  documentation: noStorageInStatelessModulesDocumentation,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow SQL or key/value access inside configured stateless modules; derive state from a system of record instead.",
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
    if (isTestFile(context.filename)) {
      return {};
    }
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

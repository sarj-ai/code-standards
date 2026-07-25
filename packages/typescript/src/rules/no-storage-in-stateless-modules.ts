/**
 * @fileoverview Keep modules that are stateless by design free of private
 * storage.
 *
 * Some features are stateless deliberately: they derive everything they need
 * from reads against the systems of record (Slack, Linear, GitHub, a CRM) plus
 * markers in the artefacts they themselves produced. The reason is operational
 * — such a feature can be re-run and back-filled freely, whereas a private
 * table or key/value namespace immediately diverges from what a human can
 * actually see and audit in the system of record. Adding a store to one of
 * these modules silently deletes that property, and nothing else in the
 * toolchain notices.
 *
 * WHAT IT CATCHES, inside the configured modules only
 *   db.prepare(sql)              // a SQL statement
 *   kv.put(key, value)           // a key/value write
 *   kv.getWithMetadata(key)      // a key/value read
 *
 * OPT-IN BY DESIGN
 * `modules` defaults to an EMPTY list, which makes the rule a no-op. That is
 * deliberate: the method names alone (`put`, `prepare`) carry no type
 * information, so the rule is only meaningful — and only quiet enough to live
 * in a shared preset — when it is pointed at the specific directories a team
 * has declared stateless.
 *
 *   "@sarj/no-storage-in-stateless-modules": ["error", {
 *     "modules": ["[\\\\/]engineer-digest[\\\\/]", "[\\\\/]digest[\\\\/]"]
 *   }]
 *
 * `modules` entries are regular-expression sources matched against the absolute
 * filename. `methods` overrides the storage method names if a driver names
 * things differently.
 *
 * NOT FLAGGED
 *   - Anything outside the configured modules.
 *   - `.put()` with fewer than two arguments — a one-argument `put` is more
 *     often a builder or queue helper than a key/value write.
 *
 * If a feature genuinely cannot be expressed statelessly, that is a design
 * conversation, not a disable comment.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "storageInStatelessModule";

export interface RuleOptions {
  /** Regex sources matched against the filename. Empty means the rule is off. */
  readonly modules?: readonly string[];
  /** Storage method names to flag. Replaces the defaults. */
  readonly methods?: readonly string[];
}

type Options = readonly [RuleOptions?];

const DEFAULT_METHODS: readonly string[] = [
  "prepare",
  "put",
  "getWithMetadata",
];

/**
 * Minimum argument count before a method call counts as storage access. `put`
 * needs a key AND a value; a single-argument `put` is usually something else.
 * Methods absent from this map need one argument.
 */
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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

/**
 * @fileoverview no-storage-in-stateless-modules — keep private storage out of modules declared stateless.
 *
 * Port of the 18.x `no-storage-in-stateless-modules` rule. The rule is untyped, so the port
 * covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { sqlTextOf, stripSqlNoise } from "../utils/sql.js";
import { getPropertyName } from "../utils/static-string.js";

const NAME = "no-storage-in-stateless-modules";

interface RuleOptions {
  readonly modules?: readonly string[];
  readonly methods?: readonly string[];
}

const DEFAULT_METHODS: readonly string[] = [
  "prepare",
  "put",
  "getWithMetadata",
];

const MIN_ARGUMENTS: ReadonlyMap<string, number> = new Map([["put", 2]]);

const SQL_STATEMENT_RE = /^\s*(?:SELECT|WITH|INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|PRAGMA|EXPLAIN)\b/iu;
const SQL_RECEIVER_RE = /^(?:db|database|connection)$/iu;
const IDENTIFIER_WORD_RE = /[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+/gu;

const STORAGE_RECEIVER_WORDS: ReadonlySet<string> = new Set([
  "bucket",
  "cache",
  "kv",
  "namespace",
  "r2",
  "redis",
  "storage",
  "store",
]);

/** The flagged storage method name of `receiver.method(...)`, or null. */
function storageMethodName(
  node: ESTree.CallExpression,
  methods: ReadonlySet<string>,
): string | null {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return null;
  const name = getPropertyName(callee);
  if (name === null || !methods.has(name)) {
    return null;
  }
  if (node.arguments.length < (MIN_ARGUMENTS.get(name) ?? 1)) {
    return null;
  }
  // `put` is shared by HTTP clients, queues, builders, and KV stores. Require
  // receiver evidence before treating this ambiguous name as storage access.
  if (name === "put" && !isStorageLikeReceiver(callee.object)) {
    return null;
  }
  if (name === "prepare" && !hasSqlPreparationEvidence(node, callee)) return null;
  return name;
}

/** Whether the receiver itself gives syntactic evidence of storage access. */
function isStorageLikeReceiver(
  node: Node,
): boolean {
  node = unwrapExpression(node);
  if (node.type === "Identifier") {
    return isStorageIdentifier(node.name);
  }
  if (node.type !== "MemberExpression") {
    return false;
  }
  const name = getPropertyName(node);
  if (name !== null && isStorageIdentifier(name)) {
    return true;
  }
  return isStorageLikeReceiver(node.object);
}

function isStorageIdentifier(name: string): boolean {
  return identifierWords(name).some((word) =>
    STORAGE_RECEIVER_WORDS.has(word.toLowerCase()),
  );
}

/** Split snake/camel/Pascal identifiers without treating `httpClient` as storage. */
function identifierWords(name: string): string[] {
  return name.match(IDENTIFIER_WORD_RE) ?? [name];
}

/** `prepare` is storage only for a SQL statement or a database-named receiver. */
function hasSqlPreparationEvidence(node: ESTree.CallExpression, callee: ESTree.MemberExpression): boolean {
  const argument = node.arguments[0];
  const text = argument === undefined ? null : sqlTextOf(argument);
  if (text !== null) return SQL_STATEMENT_RE.test(stripSqlNoise(text));
  const receiver = callee.object;
  const receiverName = receiver.type === "Identifier" ? receiver.name : receiver.type === "MemberExpression" ? getPropertyName(receiver) : null;
  return receiverName !== null && SQL_RECEIVER_RE.test(receiverName);
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description:
        "Disallow SQL or key/value access inside configured stateless modules; derive state from a system of record instead.",
      url: docsUrl(NAME),
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
  createOnce(context) {
    let methods: ReadonlySet<string> = new Set();
    return {
      before() {
        if (isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        const options = context.options[0] as RuleOptions | undefined;
        const modules = options?.modules ?? [];
        if (modules.length === 0) return false;
        // Compile every pattern first so invalid configuration fails loudly.
        const scoped = modules.map((pattern) => new RegExp(pattern));
        if (!scoped.some((re) => re.test(context.filename))) return false;
        methods = new Set(options?.methods ?? DEFAULT_METHODS);
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
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

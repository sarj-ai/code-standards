/**
 * @fileoverview no-raw-fetch-outside-clients — a bare `fetch` outside the client layer opts out of retry, timeout and status handling, and cannot be stubbed.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-raw-fetch-outside-clients.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/no-raw-fetch-outside-clients.md
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "rawFetch";

export interface RuleOptions {
  /** Regular-expression sources matched against the filename. */
  readonly allow?: readonly string[];
}

type Options = readonly [RuleOptions?];

/**
 * Path shapes that legitimately own outbound HTTP. Written as regex sources
 * (not globs) so they can express both path separators.
 *
 * Test files are NOT in this list — they are handled unconditionally by
 * `isTestFile`, so overriding `allow` cannot accidentally un-exempt them.
 */
const DEFAULT_ALLOW: readonly string[] = [
  "[\\\\/]clients?[\\\\/]",
  "-client\\.[cm]?[jt]sx?$",
  "[\\\\/]http-client\\.[cm]?[jt]sx?$",
  // The `api` spelling of the same client-layer convention: an `api/` directory,
  // a bare `api.ts`, or a `*-api.ts` / `*.api.ts` module.
  "[\\\\/]api[\\\\/]",
  "[\\\\/]api\\.[cm]?[jt]sx?$",
  "[-.]api\\.[cm]?[jt]sx?$",
  "[\\\\/]services?[\\\\/]",
  "[\\\\/](connectors|providers|integrations|adapters|fetchers)[\\\\/]",
  "[\\\\/]notifications[\\\\/]",
  "[Ss]ervice\\.[cm]?[jt]sx?$",
  "-(service|connector|adapter|sdk|fetcher)\\.[cm]?[jt]sx?$",
];

/**
 * Non-production trees the shared `isTestFile` predicate does not spell:
 * Playwright/Cypress suites and their helpers, and jscodeshift's input/output
 * fixtures (text a codemod transforms, not code that runs).
 */
const NON_PRODUCTION_TREE_RE =
  /[\\/](playwright|cypress|__testfixtures__)[\\/]/;

/** Receivers on which `.fetch()` is the global, not some cache/query API. */
const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set([
  "globalThis",
  "window",
  "self",
]);

const PRESIGNED_URL_NAME_RE = /(?:pre-?signed|signed|upload|download)Url$/i;

/** True when `node` is a call to the global `fetch`. */
function isGlobalFetchCall(node: TSESTree.CallExpression): boolean {
  const callee = node.callee;

  if (callee.type === "Identifier") {
    return callee.name === "fetch";
  }

  if (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.property.type === "Identifier" &&
    callee.property.name === "fetch" &&
    callee.object.type === "Identifier"
  ) {
    return GLOBAL_RECEIVERS.has(callee.object.name);
  }

  return false;
}

function identifierLikeName(node: TSESTree.Node): string | null {
  if (node.type === "Identifier") {
    return node.name;
  }
  if (
    node.type === "MemberExpression" &&
    !node.computed &&
    node.property.type === "Identifier"
  ) {
    return node.property.name;
  }
  return null;
}

/** True for a lone `fetch(new URL(...))` / `fetch(new Request(...))`. */
function isConstructedArgumentHandoff(node: TSESTree.CallExpression): boolean {
  const [first] = node.arguments;
  return (
    node.arguments.length === 1 &&
    first !== undefined &&
    first.type === AST_NODE_TYPES.NewExpression
  );
}

function isPresignedUrlTransfer(node: TSESTree.CallExpression): boolean {
  const first = node.arguments[0];
  if (first === undefined) {
    return false;
  }
  const name = identifierLikeName(first);
  return name !== null && PRESIGNED_URL_NAME_RE.test(name);
}

/**
 * Compile the configured patterns once per file. An invalid pattern is skipped
 * rather than thrown: a bad `allow` entry should not take the whole lint run
 * down, and the rule failing closed (still reporting) is the safe direction.
 */
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

export default createRule<Options, MessageIds>({
  name: "no-raw-fetch-outside-clients",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow calling the global `fetch` outside the client layer; route outbound HTTP through a client module that owns retry, timeout and status handling.",
    },
    schema: [
      {
        type: "object",
        properties: {
          allow: {
            type: "array",
            items: { type: "string" },
            description:
              "Regular-expression sources matched against the filename. Replaces the defaults.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      rawFetch:
        "Raw `fetch()` outside a client module. Route the call through a client (e.g. `clients/*-client.ts`) so it inherits retry, timeout and status handling and stays stubbable in tests.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    const filename = context.filename;

    if (isTestFile(filename) || NON_PRODUCTION_TREE_RE.test(filename)) {
      return {};
    }

    const patterns = options?.allow ?? DEFAULT_ALLOW;
    const allowed = compile(patterns);

    if (allowed.some((re) => re.test(filename))) {
      return {};
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (isPresignedUrlTransfer(node) || isConstructedArgumentHandoff(node)) {
          return;
        }
        if (isGlobalFetchCall(node)) {
          context.report({ node, messageId: "rawFetch" });
        }
      },
    };
  },
});

/**
 * @fileoverview Keep outbound HTTP behind a client module.
 *
 * A bare `fetch()` in a route handler, server action or component opts out of
 * whatever the codebase's client layer provides — retry/backoff, timeouts,
 * status handling, auth headers, structured log breadcrumbs. It is also the
 * shape that cannot be stubbed in a test without monkey-patching global
 * `fetch`, so the call site quietly becomes untestable.
 *
 * WHAT IT CATCHES
 *   fetch(url)                  // bare global
 *   globalThis.fetch(url)       // explicit global receiver
 *   window.fetch(url)
 *
 * NOT FLAGGED
 *   - Files whose path matches one of the `allow` patterns. The defaults cover
 *     the conventions we have seen in practice — a `clients/` directory, a
 *     `*-client.ts` module, an `http-client.*` wrapper — plus test files.
 *   - A method named `fetch` on some other receiver (`cache.fetch(k)`,
 *     `queryClient.fetch()`): only the global is HTTP.
 *   - `new Request(...)` / `axios(...)` and friends. This rule is about the
 *     global `fetch`, not about every HTTP library.
 *
 * CONFIGURATION
 * `allow` is a list of regular-expression sources matched against the absolute
 * filename, so a repo that keeps its client layer somewhere else can say so
 * rather than sprinkling disable comments:
 *
 *   "@sarj/no-raw-fetch-outside-clients": ["error", {
 *     "allow": ["[\\\\/]lib[\\\\/]api[\\\\/]", "-gateway\\\\.ts$"]
 *   }]
 *
 * Supplying `allow` REPLACES the defaults, so include the test patterns if you
 * still want test files exempt.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "rawFetch";

export interface RuleOptions {
  /** Regular-expression sources matched against the filename. */
  readonly allow?: readonly string[];
}

type Options = readonly [RuleOptions?];

/**
 * Path shapes that legitimately own outbound HTTP, plus test files. Written as
 * regex sources (not globs) so they can express both path separators.
 */
const DEFAULT_ALLOW: readonly string[] = [
  "[\\\\/]clients?[\\\\/]",
  "-client\\.[cm]?[jt]sx?$",
  "[\\\\/]http-client\\.[cm]?[jt]sx?$",
  "\\.test\\.",
  "\\.spec\\.",
  "[\\\\/]__tests__[\\\\/]",
  "[\\\\/]__mocks__[\\\\/]",
];

/** Receivers on which `.fetch()` is the global, not some cache/query API. */
const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set([
  "globalThis",
  "window",
  "self",
]);

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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
    const patterns = options?.allow ?? DEFAULT_ALLOW;
    const allowed = compile(patterns);
    const filename = context.filename;

    if (allowed.some((re) => re.test(filename))) {
      return {};
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (isGlobalFetchCall(node)) {
          context.report({ node, messageId: "rawFetch" });
        }
      },
    };
  },
});

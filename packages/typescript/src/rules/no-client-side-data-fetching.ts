/**
 * @fileoverview no-client-side-data-fetching — fetching in `useEffect` is a render -> effect -> fetch -> re-render waterfall with no server cache.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-client-side-data-fetching.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "noClientFetch";
type Options = readonly [];

export const noClientSideDataFetchingDocumentation = {
  summary: "Disallow direct data fetching inside `useEffect` or `useLayoutEffect`.",
  rationale:
    "Effect-driven reads begin after rendering and can create request waterfalls, duplicate fetches, and loading-state layout shifts.",
  remediation:
    "Fetch in a React Server Component or Server Action, or use a client cache such as SWR or React Query.",
  category: "performance",
  limitations: [
    "The rule recognizes common fetch clients syntactically and exempts analytics endpoints and non-GET `fetch` calls.",
  ],
  examples: [
    {
      id: "effect-without-fetch",
      title: "An effect performs no data request",
      outcome: "no-match",
      files: [{ path: "src/users.tsx", source: "import { useEffect } from 'react'; useEffect(() => { console.log('mounted'); }, []);" }],
      focusPath: "src/users.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "fetch-inside-effect",
      title: "An effect starts a data request",
      outcome: "match",
      files: [{ path: "src/users.tsx", source: "useEffect(() => { fetch('/api/users'); }, []);" }],
      focusPath: "src/users.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const FETCH_LIBS: ReadonlySet<string> = new Set(["axios", "ky", "superagent"]);

const HTTP_METHOD_NAMES: ReadonlySet<string> = new Set([
  "get",
  "post",
  "put",
  "delete",
  "patch",
  "request",
  "head",
  "options",
]);

// Matched against whole path SEGMENTS (split on `/` and `.`), never as raw
// substrings — otherwise `/api/login` ("log"), `/blog` ("log"), `/api/events`
// ("event"), `/catalog` ("log"), and `/api/shipping` ("ping") would be wrongly
// exempted.
const ANALYTICS_SEGMENTS: ReadonlySet<string> = new Set([
  "analytics",
  "telemetry",
  "track",
  "log",
  "ping",
  "beacon",
  "metrics",
  "event",
]);

function isEffectHookCall(node: TSESTree.CallExpression): boolean {
  const callee = node.callee;

  // useEffect(...) / useLayoutEffect(...)
  if (callee.type === AST_NODE_TYPES.Identifier) {
    return callee.name === "useEffect" || callee.name === "useLayoutEffect";
  }

  // React.useEffect(...) / React.useLayoutEffect(...)
  if (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.computed &&
    callee.object.type === AST_NODE_TYPES.Identifier &&
    callee.object.name === "React" &&
    callee.property.type === AST_NODE_TYPES.Identifier
  ) {
    return (
      callee.property.name === "useEffect" ||
      callee.property.name === "useLayoutEffect"
    );
  }

  return false;
}

function isFetchCall(node: TSESTree.CallExpression): boolean {
  const callee = node.callee;

  if (
    callee.type === AST_NODE_TYPES.Identifier &&
    callee.name === "fetch"
  ) {
    const method = readMethodProperty(node.arguments[1]);
    if (method !== null && method !== "GET") {
      return false;
    }
    return true;
  }

  // axios.get(...), ky.post(...), superagent.delete(...), ...
  if (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.computed &&
    callee.object.type === AST_NODE_TYPES.Identifier &&
    FETCH_LIBS.has(callee.object.name) &&
    callee.property.type === AST_NODE_TYPES.Identifier
  ) {
    // Only flag actual HTTP method calls — NOT `axios.create`, `axios.defaults`,
    // `axios.interceptors`, `axios.isAxiosError`, etc.
    return HTTP_METHOD_NAMES.has(callee.property.name);
  }

  // axios(config) / ky(config) — treat as request unless method is explicitly non-GET.
  if (
    callee.type === AST_NODE_TYPES.Identifier &&
    (callee.name === "axios" || callee.name === "ky")
  ) {
    const firstArg = node.arguments[0];
    const secondArg = node.arguments[1];
    let configArg: TSESTree.Node | undefined;
    if (firstArg?.type === AST_NODE_TYPES.ObjectExpression) {
      configArg = firstArg;
    } else if (secondArg?.type === AST_NODE_TYPES.ObjectExpression) {
      configArg = secondArg;
    }
    const method = readMethodProperty(configArg);
    if (method !== null && method !== "GET") {
      return false;
    }
    return true;
  }

  return false;
}

function readMethodProperty(
  optionsArg: TSESTree.Node | undefined,
): string | null {
  if (!optionsArg || optionsArg.type !== AST_NODE_TYPES.ObjectExpression) {
    return null;
  }
  for (const prop of optionsArg.properties) {
    if (prop.type !== AST_NODE_TYPES.Property) continue;
    if (prop.computed) continue;
    const key = prop.key;
    const matchesMethodKey =
      (key.type === AST_NODE_TYPES.Identifier && key.name === "method") ||
      (key.type === AST_NODE_TYPES.Literal && key.value === "method");
    if (!matchesMethodKey) continue;
    if (
      prop.value.type === AST_NODE_TYPES.Literal &&
      typeof prop.value.value === "string"
    ) {
      return prop.value.value.toUpperCase();
    }
    return null;
  }
  return null;
}

function isAnalyticsCall(node: TSESTree.CallExpression): boolean {
  const url = extractUrlString(node).toLowerCase();
  if (url === "") return false;
  // Split into path segments and file-extension parts; exempt only when a
  // WHOLE segment is a known analytics keyword.
  return url
    .split(/[/.]/)
    .some((segment) => ANALYTICS_SEGMENTS.has(segment));
}

function extractUrlString(node: TSESTree.CallExpression): string {
  const firstArg = node.arguments[0];
  if (!firstArg) return "";

  if (
    firstArg.type === AST_NODE_TYPES.Literal &&
    typeof firstArg.value === "string"
  ) {
    return firstArg.value;
  }
  if (firstArg.type === AST_NODE_TYPES.TemplateLiteral) {
    return firstArg.quasis.map((q) => q.value.cooked).join("");
  }
  if (firstArg.type === AST_NODE_TYPES.Identifier) {
    return firstArg.name;
  }
  return "";
}

export default createRule<Options, MessageIds>({
  name: "no-client-side-data-fetching",
  documentation: noClientSideDataFetchingDocumentation,
  meta: {
    type: "problem",
    docs: {
      description: "Disallow direct data fetching inside `useEffect` or `useLayoutEffect`.",
    },
    schema: [],
    messages: {
      noClientFetch:
        "Avoid direct data fetching inside useEffect / useLayoutEffect. This causes waterfalls and layout shifts. Prefer React Server Components, Server Actions, or client-side caching libraries like SWR or React Query.",
    },
  },
  defaultOptions: [],
  create(context) {
    let effectDepth = 0;
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (isEffectHookCall(node)) {
          effectDepth += 1;
          return;
        }
        if (effectDepth === 0) return;
        if (!isFetchCall(node)) return;
        if (isAnalyticsCall(node)) return;
        context.report({ node, messageId: "noClientFetch" });
      },
      "CallExpression:exit"(node: TSESTree.CallExpression): void {
        if (isEffectHookCall(node)) {
          effectDepth -= 1;
        }
      },
    };
  },
});

/**
 * @fileoverview no-client-side-data-fetching — fetching in `useEffect` is a render -> effect -> fetch -> re-render waterfall with no server cache.
 *
 * Port of the 18.x `no-client-side-data-fetching` rule. The rule is untyped, so the port
 * covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "no-client-side-data-fetching";

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

function isEffectHookCall(node: ESTree.CallExpression): boolean {
  const callee = unwrapExpression(node.callee);

  // useEffect(...) / useLayoutEffect(...)
  if (callee.type === "Identifier") {
    return callee.name === "useEffect" || callee.name === "useLayoutEffect";
  }

  // React.useEffect(...) / React.useLayoutEffect(...)
  if (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.object.type === "Identifier" &&
    callee.object.name === "React" &&
    callee.property.type === "Identifier"
  ) {
    return (
      callee.property.name === "useEffect" ||
      callee.property.name === "useLayoutEffect"
    );
  }

  return false;
}

function isFetchCall(node: ESTree.CallExpression): boolean {
  const callee = unwrapExpression(node.callee);
  if (callee.type === "MemberExpression") return isFetchLibraryMethod(callee);
  if (callee.type !== "Identifier") return false;
  if (callee.name === "fetch") return isGetRequest(node.arguments[1]);
  // axios(config) / ky(config) — treat as request unless method is explicitly non-GET.
  if (callee.name === "axios" || callee.name === "ky") {
    const [first, second] = node.arguments;
    return isGetRequest(first?.type === "ObjectExpression" ? first : second);
  }
  return false;
}

// axios.get(...), ky.post(...), superagent.delete(...), ... Only actual HTTP
// method calls — NOT `axios.create`, `axios.defaults`, `axios.interceptors`,
// `axios.isAxiosError`, etc.
function isFetchLibraryMethod(callee: ESTree.MemberExpression): boolean {
  return !callee.computed && callee.object.type === "Identifier" && FETCH_LIBS.has(callee.object.name) &&
    callee.property.type === "Identifier" && HTTP_METHOD_NAMES.has(callee.property.name);
}

/** Whether a request's options leave the method GET: no options object, no static method, or an explicit GET. */
function isGetRequest(options: Node | undefined): boolean {
  const method = readMethodProperty(options);
  return method === null || method === "GET";
}

function readMethodProperty(options: Node | undefined): string | null {
  if (options?.type !== "ObjectExpression") return null;
  const property = options.properties.find((prop) => prop.type === "Property" && !prop.computed &&
    (prop.key.type === "Identifier" && prop.key.name === "method" || prop.key.type === "Literal" && prop.key.value === "method"));
  const value = property?.type === "Property" ? property.value : null;
  return value?.type === "Literal" && typeof value.value === "string" ? value.value.toUpperCase() : null;
}

function isAnalyticsCall(node: ESTree.CallExpression): boolean {
  const url = extractUrlString(node).toLowerCase();
  if (url === "") return false;
  // Split into path segments and file-extension parts; exempt only when a
  // WHOLE segment is a known analytics keyword.
  return url
    .split(/[/.]/)
    .some((segment) => ANALYTICS_SEGMENTS.has(segment));
}

function extractUrlString(node: ESTree.CallExpression): string {
  const firstArg = node.arguments[0];
  if (!firstArg) return "";

  if (
    firstArg.type === "Literal" &&
    typeof firstArg.value === "string"
  ) {
    return firstArg.value;
  }
  if (firstArg.type === "TemplateLiteral") {
    return firstArg.quasis.map((q) => q.value.cooked).join("");
  }
  if (firstArg.type === "Identifier") {
    return firstArg.name;
  }
  return "";
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Disallow direct data fetching inside `useEffect` or `useLayoutEffect`.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noClientFetch:
        "Avoid direct data fetching inside useEffect / useLayoutEffect. This causes waterfalls and layout shifts. Prefer React Server Components, Server Actions, or client-side caching libraries like SWR or React Query.",
    },
  },
  createOnce(context) {
    let effectDepth = 0;
    return {
      before() {
        effectDepth = 0;
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (isEffectHookCall(node)) {
          effectDepth += 1;
          return;
        }
        if (effectDepth === 0) return;
        if (!isFetchCall(node)) return;
        if (isAnalyticsCall(node)) return;
        context.report({ node, messageId: "noClientFetch" });
      },
      "CallExpression:exit"(node: ESTree.CallExpression): void {
        if (isEffectHookCall(node)) {
          effectDepth -= 1;
        }
      },
    };
  },
});

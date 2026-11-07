/**
 * @fileoverview no-raw-fetch-outside-clients — a bare `fetch` outside the client layer opts out of retry, timeout and status handling, and cannot be stubbed.
 *
 * Port of the 18.x `no-raw-fetch-outside-clients` rule. The rule is untyped, so the port
 * covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { nativeFetchReference } from "../utils/native-fetch-reference.js";
import { isScriptFile, isTestFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";

const NAME = "no-raw-fetch-outside-clients";

interface RuleOptions {
  /** Regular-expression sources matched against the filename. */
  readonly allow?: readonly string[];
  /** Next.js basePath also configured for prefer-server-actions. */
  readonly basePath?: string;
}

/** Client-layer paths that may own outbound HTTP; test files are exempt separately. */
const DEFAULT_ALLOW: readonly string[] = [
  "[\\\\/]clients?[\\\\/]",
  "-client\\.[cm]?[jt]sx?$",
  "[\\\\/]http-client\\.[cm]?[jt]sx?$",
  "[\\\\/]api[\\\\/]",
  "[\\\\/]api\\.[cm]?[jt]sx?$",
  "[-.]api\\.[cm]?[jt]sx?$",
  "[\\\\/]services?[\\\\/]",
  "[\\\\/](connectors|providers|integrations|adapters|fetchers)[\\\\/]",
  "[\\\\/]notifications[\\\\/]",
  "[Ss]ervice\\.[cm]?[jt]sx?$",
  "-(service|connector|adapter|sdk|fetcher)\\.[cm]?[jt]sx?$",
  "[\\\\/][^\\\\/]*(?:Client|client)\\.[cm]?[jt]sx?$",
];

/** Additional non-production trees that may call `fetch` directly. */
const NON_PRODUCTION_TREE_RE =
  /[\\/](playwright|cypress|__testfixtures__)[\\/]/;

const PRESIGNED_URL_NAME_RE = /(?:pre-?signed|signed|upload|download)Url$/i;

const INTERNAL_MUTATION_METHODS: ReadonlySet<string> = new Set([
  "POST",
  "PUT",
  "DELETE",
  "PATCH",
]);

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

const SERVER_ACTION_SKIP_FILE_RE =
  /(?:\.test\.[jt]sx?$|\.spec\.[jt]sx?$|-(?:test|spec)\.[jt]sx?$|\/tests?\/|\/__tests__\/|\/__testfixtures__\/|\/scripts?\/|\/app\/api\/.*\/route\.[jt]sx?$|\/pages\/api\/)/;

export const NON_REACT_FRAMEWORK_RE =
  /^(?:@angular\/|@nestjs\/|vue$|vue\/|svelte$|svelte\/|solid-js$|solid-js\/|@ember\/|rxjs$|rxjs\/)/;

const BASE_PATH_RE = /^\/(?!$)(?!.*[?#])(?:[^/]+\/)*[^/]+$/u;

export function isValidBasePath(basePath: string): boolean {
  return BASE_PATH_RE.test(basePath) &&
    !basePath.split("/").some((segment) => segment === "." || segment === "..");
}

/** True for a lone `fetch(new URL(...))` / `fetch(new Request(...))`. */
function isConstructedArgumentHandoff(
  node: ESTree.CallExpression,
  resolvesToGlobal: (identifier: Node & { name: string }) => boolean,
): boolean {
  const [first] = node.arguments;
  return (
    node.arguments.length === 1 &&
    first !== undefined &&
    first.type === "NewExpression" &&
    first.callee.type === "Identifier" &&
    (first.callee.name === "URL" || first.callee.name === "Request") &&
    resolvesToGlobal(first.callee)
  );
}

const EFFECT_HOOKS: ReadonlySet<string> = new Set(["useEffect", "useLayoutEffect"]);

/** True for a non-analytics GET `fetch` inside the callback of the nearest enclosing effect hook. */
function effectOwns(node: ESTree.CallExpression): boolean {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "Identifier" || callee.name !== "fetch") return false;
  const method = readDirectMethod(node);
  if ((method !== null && method !== "GET") || isAnalyticsUrl(urlText(node.arguments[0]))) return false;
  for (let current: Node | null = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type !== "CallExpression" || !isEffectHook(unwrapExpression(current.callee))) continue;
    const callback = current.arguments[0];
    return callback !== undefined && callback.type !== "SpreadElement" &&
      node.range[0] >= callback.range[0] && node.range[1] <= callback.range[1];
  }
  return false;
}

/** The literal, template or identifier text a URL argument names, or "". */
function urlText(node: Node | undefined): string {
  if (node?.type === "Literal" && typeof node.value === "string") return node.value;
  if (node?.type === "TemplateLiteral") return node.quasis.map((quasi) => quasi.value.cooked).join("");
  return node?.type === "Identifier" ? node.name : "";
}

function isAnalyticsUrl(url: string): boolean {
  return url.toLowerCase().split(/[/.]/).some((segment) => ANALYTICS_SEGMENTS.has(segment));
}

/** `useEffect` / `useLayoutEffect`, bare or as a `React.` member. */
function isEffectHook(callee: Node): boolean {
  if (callee.type === "Identifier") return EFFECT_HOOKS.has(callee.name);
  return callee.type === "MemberExpression" && !callee.computed &&
    callee.object.type === "Identifier" && callee.object.name === "React" &&
    callee.property.type === "Identifier" && EFFECT_HOOKS.has(callee.property.name);
}

function readDirectMethod(node: ESTree.CallExpression): string | null {
  const init = node.arguments[1];
  if (init?.type !== "ObjectExpression") return null;
  for (const property of init.properties) {
    if (property.type !== "Property" || property.computed) continue;
    const key = property.key;
    const isMethod =
      (key.type === "Identifier" && key.name === "method") ||
      (key.type === "Literal" && key.value === "method");
    if (!isMethod) continue;
    return property.value.type === "Literal" &&
      typeof property.value.value === "string"
      ? property.value.value.toUpperCase()
      : null;
  }
  return null;
}

function isPresignedUrlTransfer(node: ESTree.CallExpression): boolean {
  const first = node.arguments[0];
  if (first === undefined) {
    return false;
  }
  const name = identifierLikeName(first);
  return name !== null && PRESIGNED_URL_NAME_RE.test(name);
}

function identifierLikeName(node: Node): string | null {
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

/** Compile valid allow patterns; malformed entries fail closed. */
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

const DEFAULT_ALLOWED = compile(DEFAULT_ALLOW);

function propertyValue(node: Node | null, name: string): Node | null {
  if (node?.type !== "ObjectExpression") return null;
  if (node.properties.some((property) => property.type !== "Property" || property.computed)) return null;
  for (const property of [...node.properties].reverse()) {
    if (property.type !== "Property" || property.computed) continue;
    const key = property.key;
    const keyName =
      key.type === "Identifier"
        ? key.name
        : key.type === "Literal" && typeof key.value === "string"
          ? key.value
          : null;
    if (keyName !== name) continue;
    const value = property.value as Node;
    return value.type === "AssignmentPattern" ||
      value.type === "ArrayPattern" ||
      value.type === "ObjectPattern"
      ? null
      : value;
  }
  return null;
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description:
        "Disallow calling the global `fetch` outside the client layer; route outbound HTTP through a client module that owns retry, timeout and status handling.",
      url: docsUrl(NAME),
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
          basePath: { description: "Static application URL base path without query strings, fragments or parent segments.",
            type: "string",
            pattern: "^/(?!$)(?!.*[?#])(?!(?:.*/)?\\.\\.?(?:/|$))(?:[^/]+/)*[^/]+$",
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
  createOnce(context) {
    let filename = "";
    let nonReactFramework = false;
    let hasUseClientDirective = false;
    let hasUseServerDirective = false;
    let importsServerOnly = false;
    let internalApiPrefixes: string[] = [];
    // Options arrive per file; recompile the allow list only when it changes.
    let allowPatterns: readonly string[] = DEFAULT_ALLOW;
    let allowed = DEFAULT_ALLOWED;

    function resolvesToGlobal(identifier: Node & { name: string }): boolean {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      return variable === null || variable.defs.length === 0;
    }

    function resolveNode(node: Node | null | undefined): Node | null {
      if (node == null) return null;
      if (node.type !== "Identifier") return node;
      const variable = findVariable(context.sourceCode.getScope(node), node.name);
      if (variable?.defs.length !== 1) return node;
      const definition = variable.defs[0];
      if (definition?.type !== "Variable") return node;
      const declarator = definition.node as ESTree.VariableDeclarator;
      const init = declarator.init;
      return (definition.parent as ESTree.VariableDeclaration).kind === "const" && init !== null &&
        !variable.references.some((reference) => reference.isWrite() && reference.init !== true) &&
        !(init.type === "ObjectExpression" && variable.references.some((reference) => reference.identifier !== node && reference.init !== true))
        ? init
        : node;
    }

    function serverActionOwns(node: ESTree.CallExpression): boolean {
      const unwrappedNodeCallee = unwrapExpression(node.callee);
      if (
        unwrappedNodeCallee.type !== "Identifier" ||
        unwrappedNodeCallee.name !== "fetch" ||
        !resolvesToGlobal(unwrappedNodeCallee) ||
        !hasUseClientDirective ||
        hasUseServerDirective ||
        importsServerOnly ||
        SERVER_ACTION_SKIP_FILE_RE.test(filename) ||
        nonReactFramework
      ) {
        return false;
      }
      const url = node.arguments[0];
      const init = node.arguments[1];
      if (
        url === undefined ||
        url.type === "SpreadElement" ||
        init === undefined ||
        init.type === "SpreadElement" ||
        !isInternalApiUrl(url)
      ) {
        return false;
      }
      return isMutationMethod(propertyValue(resolveNode(init), "method"));
    }

    function isMutationMethod(node: Node | null): boolean {
      const resolved = resolveNode(node);
      if (resolved?.type === "Literal") {
        return (
          typeof resolved.value === "string" &&
          INTERNAL_MUTATION_METHODS.has(resolved.value.toUpperCase())
        );
      }
      if (resolved?.type === "TemplateLiteral" && resolved.expressions.length === 0) {
        return INTERNAL_MUTATION_METHODS.has(
          resolved.quasis.map((quasi) => quasi.value.cooked).join("").toUpperCase(),
        );
      }
      if (resolved?.type === "ConditionalExpression") {
        return isMutationMethod(resolved.consequent) || isMutationMethod(resolved.alternate);
      }
      return (
        resolved?.type === "LogicalExpression" &&
        resolved.operator === "||" &&
        (isMutationMethod(resolved.left) || isMutationMethod(resolved.right))
      );
    }

    function isInternalApiUrl(node: Node | null): boolean {
      const resolved = resolveNode(node);
      if (resolved?.type === "Literal") {
        const value = resolved.value;
        return (
          typeof value === "string" &&
          internalApiPrefixes.some((prefix) => value === prefix || value.startsWith(`${prefix}/`))
        );
      }
      if (resolved?.type === "TemplateLiteral") {
        const prefix = resolved.quasis[0]?.value.cooked;
        return typeof prefix === "string" && internalApiPrefixes.some(
          (apiPrefix) => prefix === apiPrefix || prefix.startsWith(`${apiPrefix}/`),
        );
      }
      return (
        resolved?.type === "BinaryExpression" &&
        resolved.operator === "+" &&
        isInternalApiUrl(resolved.left)
      );
    }

    return {
      before() {
        filename = context.filename;
        if (
          isTestFile({ filename, cwd: context.cwd }) ||
          isScriptFile({ filename, cwd: context.cwd }) ||
          NON_PRODUCTION_TREE_RE.test(filename)
        ) {
          return false;
        }
        const options = context.options[0] as RuleOptions | undefined;
        const patterns = options?.allow ?? DEFAULT_ALLOW;
        if (patterns !== allowPatterns) {
          allowPatterns = patterns;
          allowed = compile(patterns);
        }
        if (allowed.some((re) => re.test(filename))) return false;
        const body = context.sourceCode.ast.body;
        nonReactFramework = body.some(
          (statement) =>
            statement.type === "ImportDeclaration" &&
            typeof statement.source.value === "string" &&
            NON_REACT_FRAMEWORK_RE.test(statement.source.value),
        );
        hasUseClientDirective = body.some(
          (statement) => statement.type === "ExpressionStatement" && statement.directive === "use client",
        );
        hasUseServerDirective = body.some(
          (statement) => statement.type === "ExpressionStatement" && statement.directive === "use server",
        );
        importsServerOnly = body.some(
          (statement) =>
            statement.type === "ImportDeclaration" &&
            typeof statement.source.value === "string" &&
            (statement.source.value === "server-only" || statement.source.value === "next/server"),
        );
        internalApiPrefixes = ["/api"];
        if (options?.basePath !== undefined && isValidBasePath(options.basePath)) {
          internalApiPrefixes.push(`${options.basePath}/api`);
        }
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (!nativeFetchReference(unwrapExpression(node.callee), context.sourceCode)) {
          return;
        }
        if (
          isPresignedUrlTransfer(node) ||
          isConstructedArgumentHandoff(node, resolvesToGlobal) ||
          effectOwns(node) ||
          serverActionOwns(node)
        ) {
          return;
        }
        context.report({ node, messageId: "rawFetch" });
      },
    };
  },
});

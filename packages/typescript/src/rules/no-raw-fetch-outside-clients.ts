/**
 * @fileoverview no-raw-fetch-outside-clients — a bare `fetch` outside the client layer opts out of retry, timeout and status handling, and cannot be stubbed.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-raw-fetch-outside-clients.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "rawFetch";

export interface RuleOptions {
  /** Regular-expression sources matched against the filename. */
  readonly allow?: readonly string[];
}

type Options = readonly [RuleOptions?];

export const noRawFetchOutsideClientsDocumentation = {
  summary: "Disallow calling the global `fetch` outside the client layer; route outbound HTTP through a client module that owns retry, timeout and status handling.",
  rationale: "Scattered fetch calls bypass shared transport policy and are harder to stub and observe consistently.",
  remediation: "Move the request into a client module and call that abstraction from application code.",
  category: "architecture",
  limitations: ["Tests, client-layer paths, constructed handoffs, and pre-signed URL transfers are excluded."],
  examples: [
    { id: "client-call", title: "Use a client abstraction", outcome: "no-match", files: [{ path: "src/routes/handler.ts", source: "const response = await billingClient.getInvoice(id);" }], focusPath: "src/routes/handler.ts", expectedCount: 0, public: true },
    { id: "raw-fetch", title: "Do not call global fetch here", outcome: "match", files: [{ path: "src/routes/handler.ts", source: "const response = await fetch('/api/invoices');" }], focusPath: "src/routes/handler.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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

/** Receivers on which `.fetch()` is the global, not some cache/query API. */
const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set([
  "globalThis",
  "window",
  "self",
]);

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

const NON_REACT_FRAMEWORK_RE =
  /^(?:@angular\/|@nestjs\/|vue$|vue\/|svelte$|svelte\/|solid-js$|solid-js\/|@ember\/|rxjs$|rxjs\/)/;

function isGlobalFetchCall(
  node: TSESTree.CallExpression,
  resolvesToGlobal: (identifier: TSESTree.Identifier) => boolean,
): boolean {
  const callee = node.callee;

  if (callee.type === "Identifier") {
    return callee.name === "fetch" && resolvesToGlobal(callee);
  }

  if (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.property.type === "Identifier" &&
    callee.property.name === "fetch" &&
    callee.object.type === "Identifier"
  ) {
    return (
      GLOBAL_RECEIVERS.has(callee.object.name) &&
      resolvesToGlobal(callee.object)
    );
  }

  return false;
}

/** True for a lone `fetch(new URL(...))` / `fetch(new Request(...))`. */
function isConstructedArgumentHandoff(
  node: TSESTree.CallExpression,
  resolvesToGlobal: (identifier: TSESTree.Identifier) => boolean,
): boolean {
  const [first] = node.arguments;
  return (
    node.arguments.length === 1 &&
    first !== undefined &&
    first.type === AST_NODE_TYPES.NewExpression &&
    first.callee.type === AST_NODE_TYPES.Identifier &&
    (first.callee.name === "URL" || first.callee.name === "Request") &&
    resolvesToGlobal(first.callee)
  );
}

function effectOwns(node: TSESTree.CallExpression): boolean {
  if (node.callee.type !== AST_NODE_TYPES.Identifier) return false;
  const method = readDirectMethod(node);
  if (method !== null && method !== "GET") return false;

  const first = node.arguments[0];
  let url = "";
  if (first?.type === AST_NODE_TYPES.Literal && typeof first.value === "string") {
    url = first.value;
  } else if (first?.type === AST_NODE_TYPES.TemplateLiteral) {
    url = first.quasis.map((quasi) => quasi.value.cooked).join("");
  } else if (first?.type === AST_NODE_TYPES.Identifier) {
    url = first.name;
  }
  if (
    url !== "" &&
    url
      .toLowerCase()
      .split(/[/.]/)
      .some((segment) => ANALYTICS_SEGMENTS.has(segment))
  ) {
    return false;
  }

  for (
    let current: TSESTree.Node | null | undefined = node.parent;
    current != null;
    current = current.parent
  ) {
    if (current.type !== AST_NODE_TYPES.CallExpression) continue;
    const callee = current.callee;
    const isEffect =
      (callee.type === AST_NODE_TYPES.Identifier &&
        (callee.name === "useEffect" || callee.name === "useLayoutEffect")) ||
      (callee.type === AST_NODE_TYPES.MemberExpression &&
        !callee.computed &&
        callee.object.type === AST_NODE_TYPES.Identifier &&
        callee.object.name === "React" &&
        callee.property.type === AST_NODE_TYPES.Identifier &&
        (callee.property.name === "useEffect" ||
          callee.property.name === "useLayoutEffect"));
    if (!isEffect) continue;
    const callback = current.arguments[0];
    return (
      callback !== undefined &&
      callback.type !== AST_NODE_TYPES.SpreadElement &&
      node.range[0] >= callback.range[0] &&
      node.range[1] <= callback.range[1]
    );
  }
  return false;
}

function readDirectMethod(node: TSESTree.CallExpression): string | null {
  const init = node.arguments[1];
  if (init?.type !== AST_NODE_TYPES.ObjectExpression) return null;
  for (const property of init.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.computed) continue;
    const key = property.key;
    const isMethod =
      (key.type === AST_NODE_TYPES.Identifier && key.name === "method") ||
      (key.type === AST_NODE_TYPES.Literal && key.value === "method");
    if (!isMethod) continue;
    return property.value.type === AST_NODE_TYPES.Literal &&
      typeof property.value.value === "string"
      ? property.value.value.toUpperCase()
      : null;
  }
  return null;
}

function isPresignedUrlTransfer(node: TSESTree.CallExpression): boolean {
  const first = node.arguments[0];
  if (first === undefined) {
    return false;
  }
  const name = identifierLikeName(first);
  return name !== null && PRESIGNED_URL_NAME_RE.test(name);
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

export default createRule<Options, MessageIds>({
  name: "no-raw-fetch-outside-clients",
  documentation: noRawFetchOutsideClientsDocumentation,
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

    if (
      isTestFile(filename) ||
      isScriptFile(filename) ||
      NON_PRODUCTION_TREE_RE.test(filename)
    ) {
      return {};
    }

    const patterns = options?.allow ?? DEFAULT_ALLOW;
    const allowed = compile(patterns);

    const nonReactFramework = context.sourceCode.ast.body.some(
      (statement) =>
        statement.type === AST_NODE_TYPES.ImportDeclaration &&
        typeof statement.source.value === "string" &&
        NON_REACT_FRAMEWORK_RE.test(statement.source.value),
    );

    function resolvesToGlobal(identifier: TSESTree.Identifier): boolean {
      const variable = ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
      return variable === null || variable.defs.length === 0;
    }

    function resolveNode(node: TSESTree.Node | undefined): TSESTree.Node | null {
      if (node === undefined) return null;
      if (node.type !== AST_NODE_TYPES.Identifier) return node;
      const variable = ASTUtils.findVariable(
        context.sourceCode.getScope(node),
        node.name,
      );
      if (variable?.defs.length !== 1) return node;
      const definition = variable.defs[0];
      return definition?.type === "Variable" && definition.node.init !== null
        ? definition.node.init
        : node;
    }

    function propertyValue(
      node: TSESTree.Node | null,
      name: string,
    ): TSESTree.Node | null {
      if (node?.type !== AST_NODE_TYPES.ObjectExpression) return null;
      for (const property of node.properties) {
        if (property.type !== AST_NODE_TYPES.Property || property.computed) continue;
        const key = property.key;
        const keyName =
          key.type === AST_NODE_TYPES.Identifier
            ? key.name
            : key.type === AST_NODE_TYPES.Literal && typeof key.value === "string"
              ? key.value
              : null;
        if (keyName !== name) continue;
        return property.value.type === AST_NODE_TYPES.AssignmentPattern ||
          property.value.type === AST_NODE_TYPES.ArrayPattern ||
          property.value.type === AST_NODE_TYPES.ObjectPattern
          ? null
          : property.value;
      }
      return null;
    }

    function isInternalApiUrl(node: TSESTree.Node | null): boolean {
      const resolved = resolveNode(node ?? undefined);
      if (resolved?.type === AST_NODE_TYPES.Literal) {
        return (
          typeof resolved.value === "string" &&
          /^\/(?!\/)(?:[^/]+\/)*api(?:\/|$)/.test(resolved.value)
        );
      }
      if (resolved?.type === AST_NODE_TYPES.TemplateLiteral) {
        const prefix = resolved.quasis[0]?.value.cooked;
        return typeof prefix === "string" && /^\/(?!\/)(?:[^/]+\/)*api(?:\/|$)/.test(prefix);
      }
      if (
        resolved?.type === AST_NODE_TYPES.CallExpression &&
        resolved.callee.type === AST_NODE_TYPES.Identifier &&
        resolved.callee.name === "withBase"
      ) {
        const first = resolved.arguments[0];
        return first !== undefined && first.type !== AST_NODE_TYPES.SpreadElement
          ? isInternalApiUrl(first)
          : false;
      }
      return (
        resolved?.type === AST_NODE_TYPES.BinaryExpression &&
        resolved.operator === "+" &&
        isInternalApiUrl(resolved.left)
      );
    }

    function isMutationMethod(node: TSESTree.Node | null): boolean {
      const resolved = resolveNode(node ?? undefined);
      if (resolved?.type === AST_NODE_TYPES.Literal) {
        return (
          typeof resolved.value === "string" &&
          INTERNAL_MUTATION_METHODS.has(resolved.value.toUpperCase())
        );
      }
      if (
        resolved?.type === AST_NODE_TYPES.TemplateLiteral &&
        resolved.expressions.length === 0
      ) {
        return INTERNAL_MUTATION_METHODS.has(
          resolved.quasis.map((quasi) => quasi.value.cooked).join("").toUpperCase(),
        );
      }
      if (resolved?.type === AST_NODE_TYPES.ConditionalExpression) {
        return (
          isMutationMethod(resolved.consequent) ||
          isMutationMethod(resolved.alternate)
        );
      }
      return (
        resolved?.type === AST_NODE_TYPES.LogicalExpression &&
        resolved.operator === "||" &&
        (isMutationMethod(resolved.left) || isMutationMethod(resolved.right))
      );
    }

    function serverActionOwns(node: TSESTree.CallExpression): boolean {
      if (
        node.callee.type !== AST_NODE_TYPES.Identifier ||
        SERVER_ACTION_SKIP_FILE_RE.test(filename) ||
        nonReactFramework
      ) {
        return false;
      }
      const url = node.arguments[0];
      const init = node.arguments[1];
      if (
        url === undefined ||
        url.type === AST_NODE_TYPES.SpreadElement ||
        init === undefined ||
        init.type === AST_NODE_TYPES.SpreadElement ||
        !isInternalApiUrl(url)
      ) {
        return false;
      }
      return isMutationMethod(propertyValue(resolveNode(init), "method"));
    }

    if (allowed.some((re) => re.test(filename))) {
      return {};
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isGlobalFetchCall(node, resolvesToGlobal)) {
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

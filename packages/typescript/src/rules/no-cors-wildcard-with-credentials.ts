/**
 * @fileoverview no-cors-wildcard-with-credentials — `Access-Control-Allow-Origin: *` together with credentials lets any site read authenticated responses.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-cors-wildcard-with-credentials.test.ts
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "corsWildcardWithCredentials";
type Options = readonly [];

export const noCorsWildcardWithCredentialsDocumentation = {
  summary: "Disallow wildcard CORS origins when credentials are enabled.",
  rationale:
    "Reflecting every origin while allowing credentials can let an untrusted site read authenticated cross-origin responses.",
  remediation: "Enumerate the trusted origins that may receive credentialed responses.",
  category: "security",
  limitations: [
    "The rule detects literal CORS option and header combinations within the same syntactic scope; it does not resolve runtime configuration.",
  ],
  examples: [
    {
      id: "trusted-origin-with-credentials",
      title: "Credentials are limited to a trusted origin",
      outcome: "no-match",
      files: [{ path: "src/server.ts", source: "app.use(cors({ origin: 'https://app.example.com', credentials: true }));" }],
      focusPath: "src/server.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "wildcard-origin-with-credentials",
      title: "Credentials are enabled for every origin",
      outcome: "match",
      files: [{ path: "src/server.ts", source: "app.use(cors({ origin: '*', credentials: true }));" }],
      focusPath: "src/server.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const ACAO_HEADER = "access-control-allow-origin";
const ACAC_HEADER = "access-control-allow-credentials";
const HEADER_SET_METHODS: ReadonlySet<string> = new Set(["setheader", "set", "append"]);

function isCredentialsTrueValue(node: TSESTree.Node): boolean {
  if (node.type === "Literal") {
    if (node.value === true) {
      return true;
    }
    if (typeof node.value === "string") {
      return node.value.trim().toLowerCase() === "true";
    }
  }
  return false;
}

function isStarLiteral(node: TSESTree.Node): boolean {
  return node.type === "Literal" && node.value === "*";
}

/**
 * Returns the (non-computed) string name of a property key, or `undefined`.
 */
function propertyKeyName(prop: TSESTree.Property): string | undefined {
  if (prop.computed) {
    return undefined;
  }
  const key = prop.key;
  if (key.type === "Identifier") {
    return key.name;
  }
  if (key.type === "Literal" && typeof key.value === "string") {
    return key.value;
  }
  return undefined;
}

function isCorsWildcardCredentialsCall(
  node: TSESTree.CallExpression | TSESTree.NewExpression,
): boolean {
  const name = calleeName(node);
  if (name === undefined || name.toLowerCase() !== "cors") {
    return false;
  }
  const options = node.arguments.find(
    (arg): arg is TSESTree.ObjectExpression => arg.type === "ObjectExpression",
  );
  if (options === undefined) {
    return false;
  }
  let hasCredentials = false;
  let hasWildcardOrigin = false;
  for (const prop of options.properties) {
    if (prop.type !== "Property") {
      continue;
    }
    const key = propertyKeyName(prop);
    if (key === "credentials" && isTrueLiteral(prop.value)) {
      hasCredentials = true;
    } else if (key === "origin" && subtreeContainsStarLiteral(prop.value)) {
      hasWildcardOrigin = true;
    }
  }
  return hasCredentials && hasWildcardOrigin;
}

/**
 * True only for the boolean literal `true` (not `1`, not a truthy expression).
 */
function isTrueLiteral(node: TSESTree.Node): boolean {
  return node.type === "Literal" && node.value === true;
}

function subtreeContainsStarLiteral(node: TSESTree.Node): boolean {
  if (isStarLiteral(node)) {
    return true;
  }
  for (const key of Object.keys(node)) {
    if (key === "parent" || key === "loc" || key === "range") {
      continue;
    }
    const value = (node as unknown as Record<string, unknown>)[key];
    if (Array.isArray(value)) {
      for (const child of value) {
        if (isNode(child) && subtreeContainsStarLiteral(child)) {
          return true;
        }
      }
    } else if (isNode(value) && subtreeContainsStarLiteral(value)) {
      return true;
    }
  }
  return false;
}

function isNode(value: unknown): value is TSESTree.Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/**
 * Extracts the callee's terminal identifier name for a call/new expression
 * (`cors` for `cors(...)` and `app.cors(...)`, `Cors` for `new Cors(...)`).
 */
function calleeName(
  node: TSESTree.CallExpression | TSESTree.NewExpression,
): string | undefined {
  const callee = node.callee;
  if (callee.type === "Identifier") {
    return callee.name;
  }
  if (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.property.type === "Identifier"
  ) {
    return callee.property.name;
  }
  return undefined;
}

/**
 * True if the ObjectExpression is a header map setting BOTH
 * `Access-Control-Allow-Origin: "*"` and
 * `Access-Control-Allow-Credentials: "true"` (case-insensitive keys).
 */
function isWildcardCredentialsHeaderObject(
  node: TSESTree.ObjectExpression,
): boolean {
  let wildcardOrigin = false;
  let credentialsTrue = false;
  for (const prop of node.properties) {
    if (prop.type !== "Property") {
      continue;
    }
    const key = propertyKeyName(prop);
    if (key === undefined) {
      continue;
    }
    const header = key.toLowerCase();
    if (header === ACAO_HEADER && isStarLiteral(prop.value)) {
      wildcardOrigin = true;
    } else if (header === ACAC_HEADER && isCredentialsTrueValue(prop.value)) {
      credentialsTrue = true;
    }
  }
  return wildcardOrigin && credentialsTrue;
}

type HeaderSetKind = "origin" | "credentials";

/**
 * Classifies a `x.setHeader(name, value)` / `x.set(name, value)` /
 * `x.append(name, value)` call as an ACAO-wildcard set, an ACAC-true set, or
 * neither.
 */
function classifyHeaderSetCall(
  node: TSESTree.CallExpression,
): HeaderSetKind | undefined {
  const callee = node.callee;
  if (
    callee.type !== "MemberExpression" ||
    callee.computed ||
    callee.property.type !== "Identifier" ||
    !HEADER_SET_METHODS.has(callee.property.name.toLowerCase())
  ) {
    return undefined;
  }
  const [nameArg, valueArg] = node.arguments;
  if (
    nameArg === undefined ||
    valueArg === undefined ||
    nameArg.type !== "Literal" ||
    typeof nameArg.value !== "string"
  ) {
    return undefined;
  }
  const header = nameArg.value.toLowerCase();
  if (header === ACAO_HEADER && isStarLiteral(valueArg)) {
    return "origin";
  }
  if (header === ACAC_HEADER && isCredentialsTrueValue(valueArg)) {
    return "credentials";
  }
  return undefined;
}

function enclosingScope(node: TSESTree.Node): TSESTree.Node | undefined {
  let current: TSESTree.Node | undefined = node.parent;
  while (current) {
    if (
      current.type === "FunctionDeclaration" ||
      current.type === "FunctionExpression" ||
      current.type === "ArrowFunctionExpression"
    ) {
      return current;
    }
    current = current.parent;
  }
  return undefined;
}

interface ScopeHeaderSets {
  originNodes: TSESTree.CallExpression[];
  credentialsNodes: TSESTree.CallExpression[];
}

type ReceiverHeaderSets = Map<string, ScopeHeaderSets>;

export default createRule<Options, MessageIds>({
  name: "no-cors-wildcard-with-credentials",
  documentation: noCorsWildcardWithCredentialsDocumentation,
  meta: {
    type: "problem",
    docs: {
      description: "Disallow wildcard CORS origins when credentials are enabled.",
    },
    schema: [],
    messages: {
      corsWildcardWithCredentials:
        'CORS reflects any Origin (`"*"`) while allowing credentials — any site can read authenticated responses. Enumerate explicit trusted origins instead of using `"*"` with credentials.',
    },
  },
  defaultOptions: [],
  create(context) {
    const scopeHeaderSets = new Map<TSESTree.Node | "module", ReceiverHeaderSets>();
    const variableIds = new WeakMap<TSESLint.Scope.Variable, number>();
    let nextVariableId = 0;

    function variableId(variable: TSESLint.Scope.Variable): number {
      const existing = variableIds.get(variable);
      if (existing !== undefined) return existing;
      const value = nextVariableId++;
      variableIds.set(variable, value);
      return value;
    }

    function receiverIdentity(node: TSESTree.Node): string | null {
      if (node.type === AST_NODE_TYPES.Identifier) {
        const variable = ASTUtils.findVariable(
          context.sourceCode.getScope(node),
          node.name,
        );
        return variable === null
          ? `global:${node.name}`
          : `variable:${variableId(variable)}`;
      }
      if (node.type === AST_NODE_TYPES.ThisExpression) return "this";
      if (
        node.type === AST_NODE_TYPES.MemberExpression &&
        !node.computed &&
        node.property.type === AST_NODE_TYPES.Identifier
      ) {
        const owner = receiverIdentity(node.object);
        return owner === null ? null : `${owner}.${node.property.name}`;
      }
      return null;
    }

    function recordHeaderSet(
      node: TSESTree.CallExpression,
      kind: HeaderSetKind,
    ): void {
      if (node.callee.type !== AST_NODE_TYPES.MemberExpression) return;
      const receiver = receiverIdentity(node.callee.object);
      if (receiver === null) return;
      const key = enclosingScope(node) ?? "module";
      let receivers = scopeHeaderSets.get(key);
      if (receivers === undefined) {
        receivers = new Map();
        scopeHeaderSets.set(key, receivers);
      }
      let entry = receivers.get(receiver);
      if (entry === undefined) {
        entry = { originNodes: [], credentialsNodes: [] };
        receivers.set(receiver, entry);
      }
      if (kind === "origin") {
        entry.originNodes.push(node);
      } else {
        entry.credentialsNodes.push(node);
      }
    }

    return {
      NewExpression(node: TSESTree.NewExpression): void {
        if (isCorsWildcardCredentialsCall(node)) {
          context.report({ node, messageId: "corsWildcardWithCredentials" });
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        if (isCorsWildcardCredentialsCall(node)) {
          context.report({ node, messageId: "corsWildcardWithCredentials" });
          return;
        }
        const kind = classifyHeaderSetCall(node);
        if (kind !== undefined) {
          recordHeaderSet(node, kind);
        }
      },
      ObjectExpression(node: TSESTree.ObjectExpression): void {
        if (isWildcardCredentialsHeaderObject(node)) {
          context.report({ node, messageId: "corsWildcardWithCredentials" });
        }
      },
      "Program:exit"(): void {
        for (const receivers of scopeHeaderSets.values()) {
          for (const { originNodes, credentialsNodes } of receivers.values()) {
            if (originNodes.length > 0 && credentialsNodes.length > 0) {
              for (const node of originNodes) {
                context.report({
                  node,
                  messageId: "corsWildcardWithCredentials",
                });
              }
            }
          }
        }
      },
    };
  },
});

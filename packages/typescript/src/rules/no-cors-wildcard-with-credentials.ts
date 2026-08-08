/**
 * @fileoverview no-cors-wildcard-with-credentials — `Access-Control-Allow-Origin: *` together with credentials lets any site read authenticated responses.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-cors-wildcard-with-credentials.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

type MessageIds = "corsWildcardWithCredentials";
type Options = readonly [];

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

export default createRule<Options, MessageIds>({
  name: "no-cors-wildcard-with-credentials",
  meta: {
    type: "problem",
    docs: {
      description:
        'Disallow CORS that reflects any Origin (`"*"`) while allowing credentials; any site could then read authenticated responses. Enumerate explicit trusted origins instead.',
    },
    schema: [],
    messages: {
      corsWildcardWithCredentials:
        'CORS reflects any Origin (`"*"`) while allowing credentials — any site can read authenticated responses. Enumerate explicit trusted origins instead of using `"*"` with credentials.',
    },
  },
  defaultOptions: [],
  create(context) {
    const scopeHeaderSets = new Map<TSESTree.Node | "module", ScopeHeaderSets>();

    function recordHeaderSet(
      node: TSESTree.CallExpression,
      kind: HeaderSetKind,
    ): void {
      const key = enclosingScope(node) ?? "module";
      let entry = scopeHeaderSets.get(key);
      if (entry === undefined) {
        entry = { originNodes: [], credentialsNodes: [] };
        scopeHeaderSets.set(key, entry);
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
        for (const { originNodes, credentialsNodes } of scopeHeaderSets.values()) {
          if (originNodes.length > 0 && credentialsNodes.length > 0) {
            for (const node of originNodes) {
              context.report({
                node,
                messageId: "corsWildcardWithCredentials",
              });
            }
          }
        }
      },
    };
  },
});

/**
 * @fileoverview no-insecure-random-id — `Math.random()` is predictable, so an id, token or key built from it is guessable.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-insecure-random-id.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "insecureRandomId";
type Options = readonly [];

const STRONG_SECURITY_PATTERN =
  /token|secret|csrf|password|passwd|apikey|api[-_]?key|nonce|salt|uuid|authid/i;

const NON_SECURITY_ID_PATTERN =
  /temp|tmp|cache|correlation|request|req|trace|execution|dev|hmr|mock|test|perf|marker/i;

/** Matches a static string fragment that reads as a path or DOM-id context. */
const PATH_OR_DOM_MARKER = /[\\/#]|\.[A-Za-z0-9]/;

/**
 * Returns true if `node` is a `Math.random()` CallExpression.
 */
function isMathRandomCall(node: TSESTree.Node): node is TSESTree.CallExpression {
  if (node.type !== "CallExpression") {
    return false;
  }
  const callee = node.callee;
  if (callee.type !== "MemberExpression" || callee.computed) {
    return false;
  }
  const { object, property } = callee;
  return (
    object.type === "Identifier" &&
    object.name === "Math" &&
    property.type === "Identifier" &&
    property.name === "random"
  );
}

/**
 * Returns true if `node` (a `Math.random()` call) is the base of a member
 * chain that calls `.toString(36)` somewhere above it, e.g.
 * `Math.random().toString(36)` or `Math.random().toString(36).slice(2)`.
 */
function isPartOfToString36Chain(node: TSESTree.Node): boolean {
  let current: TSESTree.Node = node;
  let parent = current.parent;

  while (parent) {
    if (
      parent.type === "MemberExpression" &&
      parent.object === current &&
      !parent.computed &&
      parent.property.type === "Identifier" &&
      parent.property.name === "toString"
    ) {
      const grandparent = parent.parent;
      if (
        grandparent &&
        grandparent.type === "CallExpression" &&
        grandparent.callee === parent
      ) {
        const firstArg = grandparent.arguments[0];
        if (firstArg && firstArg.type === "Literal" && firstArg.value === 36) {
          return true;
        }
      }
    }

    if (parent.type === "MemberExpression" && parent.object === current) {
      current = parent;
      parent = current.parent;
      continue;
    }
    if (parent.type === "CallExpression" && parent.callee === current) {
      current = parent;
      parent = current.parent;
      continue;
    }
    break;
  }

  return false;
}

/** Finds the nearest binding or property name without leaving its value. */
function findEnclosingName(node: TSESTree.Node): string | undefined {
  let current: TSESTree.Node = node;
  let parent = current.parent;

  while (parent) {
    if (parent.type === "VariableDeclarator" && parent.init === current) {
      if (parent.id.type === "Identifier") {
        return parent.id.name;
      }
      return undefined;
    }

    if (parent.type === "Property" && parent.value === current) {
      const key = parent.key;
      if (!parent.computed && key.type === "Identifier") {
        return key.name;
      }
      if (key.type === "Literal" && typeof key.value === "string") {
        return key.value;
      }
      return undefined;
    }

    if (parent.type === "PropertyDefinition" && parent.value === current) {
      const key = parent.key;
      if (!parent.computed && key.type === "Identifier") {
        return key.name;
      }
      if (key.type === "Literal" && typeof key.value === "string") {
        return key.value;
      }
      return undefined;
    }

    if (
      parent.type === "FunctionDeclaration" ||
      parent.type === "FunctionExpression" ||
      parent.type === "ArrowFunctionExpression" ||
      parent.type === "BlockStatement" ||
      parent.type === "ReturnStatement" ||
      parent.type === "ExpressionStatement"
    ) {
      return undefined;
    }

    current = parent;
    parent = current.parent;
  }

  return undefined;
}

/**
 * Returns true if the random value is concatenated into a string whose static
 * parts read as a filename/path/DOM id (contain a slash, backslash, `#`, or a
 * `.ext`-style fragment).
 */
function isConcatenatedIntoPathOrDomId(node: TSESTree.Node): boolean {
  const valueNode = climbValueChain(node);

  let current: TSESTree.Node = valueNode;
  let parent = current.parent;
  let top: TSESTree.Node | undefined;

  while (parent) {
    if (
      parent.type === "BinaryExpression" &&
      parent.operator === "+" &&
      (parent.left === current || parent.right === current)
    ) {
      top = parent;
      current = parent;
      parent = current.parent;
      continue;
    }
    if (parent.type === "TemplateLiteral") {
      top = parent;
      current = parent;
      parent = current.parent;
      continue;
    }
    break;
  }

  if (!top) {
    return false;
  }

  const parts: string[] = [];
  collectStaticStringParts(top, parts);
  return parts.some((part) => PATH_OR_DOM_MARKER.test(part));
}

function climbValueChain(node: TSESTree.Node): TSESTree.Node {
  let current: TSESTree.Node = node;
  let parent = current.parent;

  while (parent) {
    if (
      parent.type === "MemberExpression" &&
      parent.object === current &&
      !parent.computed
    ) {
      current = parent;
      parent = current.parent;
      continue;
    }
    if (parent.type === "CallExpression" && parent.callee === current) {
      current = parent;
      parent = current.parent;
      continue;
    }
    break;
  }

  return current;
}

/**
 * Collects the static string fragments of a `+` concatenation / template
 * literal subtree into `out`.
 */
function collectStaticStringParts(
  node: TSESTree.Node,
  out: string[],
): void {
  if (node.type === "Literal" && typeof node.value === "string") {
    out.push(node.value);
    return;
  }
  if (node.type === "TemplateLiteral") {
    for (const quasi of node.quasis) {
      out.push(quasi.value.cooked ?? quasi.value.raw);
    }
    return;
  }
  if (node.type === "BinaryExpression" && node.operator === "+") {
    collectStaticStringParts(node.left, out);
    collectStaticStringParts(node.right, out);
  }
}

export default createRule<Options, MessageIds>({
  name: "no-insecure-random-id",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow using `Math.random()` to generate identifiers, tokens, or secrets; use `crypto.randomUUID()` or `crypto.getRandomValues(...)` instead.",
    },
    schema: [],
    messages: {
      insecureRandomId:
        "`Math.random()` is not cryptographically secure and is predictable; do not use it to generate IDs, tokens, or secrets. Use `crypto.randomUUID()` or `crypto.getRandomValues(...)` instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename)) {
      return {};
    }
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isMathRandomCall(node)) {
          return;
        }

        const name = findEnclosingName(node);

        // Security signals take precedence over non-security signals.
        if (name !== undefined && STRONG_SECURITY_PATTERN.test(name)) {
          context.report({ node, messageId: "insecureRandomId" });
          return;
        }

        // Ignore ephemeral and correlation identifiers.
        if (name !== undefined && NON_SECURITY_ID_PATTERN.test(name)) {
          return;
        }

        // Ignore filename, path, and DOM-id fragments.
        if (isConcatenatedIntoPathOrDomId(node)) {
          return;
        }

        // The classic insecure random-id idiom.
        if (isPartOfToString36Chain(node)) {
          context.report({ node, messageId: "insecureRandomId" });
        }
      },
    };
  },
});

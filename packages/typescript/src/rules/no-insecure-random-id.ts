/**
 * @fileoverview no-insecure-random-id — `Math.random()` is predictable, so an id, token or key built from it is guessable.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-insecure-random-id.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "insecureRandomId";
type Options = readonly [];

export const NO_INSECURE_RANDOM_ID_DOCUMENTATION = {
  summary: "Disallow using `Math.random()` to generate identifiers, tokens, or secrets; use `crypto.randomUUID()` or `crypto.getRandomValues(...)` instead.",
  rationale: "Math.random is predictable and lacks the entropy required for security-sensitive values.",
  remediation: "Generate the value with crypto.randomUUID or crypto.getRandomValues.",
  category: "security",
  limitations: ["Ambiguous identifiers and test files are excluded to avoid flagging sampling and fixture data."],
  examples: [
    { id: "cryptographic-id", title: "Use the Web Crypto API", outcome: "no-match", files: [{ path: "src/session.ts", source: "const sessionToken = crypto.randomUUID();" }], focusPath: "src/session.ts", expectedCount: 0, public: true },
    { id: "predictable-token", title: "Do not derive a token from Math.random", outcome: "match", files: [{ path: "src/session.ts", source: "const sessionToken = Math.random();" }], focusPath: "src/session.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const STRONG_SECURITY_WORDS: ReadonlySet<string> = new Set([
  "apikey",
  "csrf",
  "nonce",
  "otp",
  "password",
  "passwd",
  "pin",
  "salt",
  "secret",
  "token",
  "uuid",
  "verificationcode",
]);

const NON_SECURITY_ID_WORDS: ReadonlySet<string> = new Set([
  "aria", "cache", "component", "correlation", "dev", "dialog", "dom",
  "element", "execution", "field", "form", "hmr", "input", "marker",
  "menu", "mock", "perf", "req", "request", "select", "tab", "temp",
  "test", "tmp", "trace",
]);

function nameWords(name: string): string[] {
  return name
    .replaceAll(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .split(/[^A-Za-z0-9]+/u)
    .filter(Boolean)
    .map((word) => word.toLowerCase());
}

function isStrongSecurityName(name: string): boolean {
  const words = nameWords(name);
  return (
    words.some((word) => STRONG_SECURITY_WORDS.has(word)) ||
    words.some((word, index) =>
      (word === "api" && words[index + 1] === "key") ||
      (word === "auth" && words[index + 1] === "id") ||
      (word === "verification" && words[index + 1] === "code"),
    )
  );
}

function isNonSecurityName(name: string): boolean {
  return nameWords(name).some((word) => NON_SECURITY_ID_WORDS.has(word));
}

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

/** Finds the nearest binding or property name without leaving its value. */
function findEnclosingNames(node: TSESTree.Node): string[] {
  const names: string[] = [];
  let directBinding = true;
  let current: TSESTree.Node = node;
  let parent = current.parent;

  while (parent) {
    if (parent.type === "VariableDeclarator" && parent.init === current) {
      if (directBinding && parent.id.type === "Identifier") {
        names.push(parent.id.name);
      }
    }

    if (parent.type === "Property" && parent.value === current) {
      const key = parent.key;
      if (!parent.computed && key.type === "Identifier") {
        names.push(key.name);
      }
      if (key.type === "Literal" && typeof key.value === "string") {
        names.push(key.value);
      }
      directBinding = false;
    }

    if (parent.type === "PropertyDefinition" && parent.value === current) {
      const key = parent.key;
      if (!parent.computed && key.type === "Identifier") {
        names.push(key.name);
      }
      if (key.type === "Literal" && typeof key.value === "string") {
        names.push(key.value);
      }
      directBinding = false;
    }

    if (parent.type === "AssignmentExpression" && parent.right === current) {
      if (directBinding && parent.left.type === "Identifier") names.push(parent.left.name);
      if (
        directBinding &&
        parent.left.type === "MemberExpression" &&
        !parent.left.computed &&
        parent.left.property.type === "Identifier"
      ) {
        names.push(parent.left.property.name);
      }
    }

    if (parent.type === "ObjectExpression" || parent.type === "ArrayExpression") {
      directBinding = false;
    }

    if (parent.type === "FunctionDeclaration") {
      if (directBinding && parent.id !== null) names.push(parent.id.name);
      return names;
    }

    if (parent.type === "ExpressionStatement") {
      return names;
    }

    current = parent;
    parent = current.parent;
  }

  return names;
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
  documentation: NO_INSECURE_RANDOM_ID_DOCUMENTATION,
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

        const names = findEnclosingNames(node);

        // Security signals take precedence over non-security signals.
        if (names.some(isStrongSecurityName)) {
          context.report({ node, messageId: "insecureRandomId" });
          return;
        }

        // Ignore ephemeral and correlation identifiers.
        if (names.some(isNonSecurityName)) {
          return;
        }

        // Ignore filename, path, and DOM-id fragments.
        if (isConcatenatedIntoPathOrDomId(node)) {
          return;
        }

        // A radix conversion alone does not prove that the value crosses a
        // security boundary. Ambiguous temporary/UI IDs intentionally miss.
      },
    };
  },
});

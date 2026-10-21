/**
 * @fileoverview no-insecure-random-id — `Math.random()` is predictable, so an id, token or key built from it is guessable.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-insecure-random-id.test.ts
 */

import { ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "insecureRandomId";
type Options = readonly [];

export const NO_INSECURE_RANDOM_ID_DOCUMENTATION = {
  summary: "Disallow using `Math.random()` to generate identifiers, tokens, or secrets; use `crypto.randomUUID()` or `crypto.getRandomValues(...)` instead.",
  rationale: "Math.random is predictable and lacks the entropy required for security-sensitive values.",
  remediation: "Generate the value with crypto.randomUUID or crypto.getRandomValues.",
  category: "security",
  limitations: ["Names select security-sensitive bindings heuristically; they do not prove sensitivity. Sampling in unrelated bindings or branch tests, locally shadowed Math objects, ambiguous identifiers and test files are excluded. This is not interprocedural data-flow analysis."],
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

function nameWords(name: string): string[] {
  return name
    .replaceAll(/([a-z0-9])([A-Z])/gu, "$1 $2")
    .split(/[^A-Za-z0-9]+/u)
    .filter(Boolean)
    .map((word) => word.toLowerCase());
}

/**
 * Returns true if `node` is a `Math.random()` CallExpression.
 */
function isMathRandomCall(node: TSESTree.Node): node is TSESTree.CallExpression {
  if (node.type !== "CallExpression") {
    return false;
  }
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") {
    return false;
  }
  const object = unwrapExpression(callee.object);
  return (
    object.type === "Identifier" &&
    object.name === "Math" &&
    ASTUtils.getPropertyName(callee) === "random"
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
      appendDirectBindingName(parent.id, directBinding, names);
      return names;
    }

    if ((parent.type === "Property" || parent.type === "PropertyDefinition") && parent.value === current) {
      appendPropertyName(parent, names);
      directBinding = false;
    }

    if (parent.type === "AssignmentExpression" && parent.right === current) {
      appendAssignedName(parent, directBinding, names);
    }

    if (parent.type === "ObjectExpression" || parent.type === "ArrayExpression") {
      directBinding = false;
    }

    if (parent.type === "FunctionDeclaration") {
      appendDirectBindingName(parent.id, directBinding, names);
      return names;
    }

    if (parent.type === "ExpressionStatement" || parent.type === "IfStatement" || parent.type === "ForStatement" || parent.type === "WhileStatement" || parent.type === "DoWhileStatement" || parent.type === "FunctionExpression" || parent.type === "ArrowFunctionExpression") {
      return names;
    }

    current = parent;
    parent = current.parent;
  }

  return names;
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
    if (isTestFile(context)) {
      return {};
    }
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (!isMathRandomCall(node)) {
          return;
        }
        if ((ASTUtils.findVariable(context.sourceCode.getScope(node), "Math")?.defs.length ?? 0) > 0) return;

        const names = findEnclosingNames(node);

        if (names.some(isStrongSecurityName)) {
          context.report({ node, messageId: "insecureRandomId" });
        }
      },
    };
  },
});

function appendPropertyName(property: TSESTree.Property | TSESTree.PropertyDefinition, names: string[]): void {
  const key = property.key;
  if (!property.computed && key.type === "Identifier") names.push(key.name);
  if (key.type === "Literal" && typeof key.value === "string") names.push(key.value);
}

function appendAssignedName(assignment: TSESTree.AssignmentExpression, directBinding: boolean, names: string[]): void {
  if (directBinding && assignment.left.type === "Identifier") names.push(assignment.left.name);
  if (directBinding && assignment.left.type === "MemberExpression" && ASTUtils.getPropertyName(assignment.left) !== null) {
    names.push((ASTUtils.getPropertyName(assignment.left) ?? ""));
  }
}

function appendDirectBindingName(id: TSESTree.Node | null, directBinding: boolean, names: string[]): void {
  if (directBinding && id?.type === "Identifier") names.push(id.name);
}

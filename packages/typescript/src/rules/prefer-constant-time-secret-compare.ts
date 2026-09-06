/**
 * @fileoverview prefer-constant-time-secret-compare — ordinary equality is not guaranteed constant-time for secret comparisons.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-constant-time-secret-compare.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isAuthSecretName, SECRET_WORDS, tokenize } from "./_secret-names.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "preferConstantTimeSecretCompare";
type Options = readonly [];

export const PREFER_CONSTANT_TIME_SECRET_COMPARE_DOCUMENTATION = {
  summary: "Prefer a supported constant-time comparison primitive for secret-like values.",
  rationale: "Ordinary equality offers no constant-time guarantee for comparing secrets.",
  remediation: "Compare equal-length cryptographic digests with a constant-time comparison primitive.",
  category: "security",
  limitations: ["This is name-based analysis, not proof of runtime sensitivity. Ambiguous token names require an authentication or cryptographic qualifier; test files and public sentinel comparisons are excluded."],
  examples: [
    { id: "constant-time-compare", title: "Use a constant-time comparison", outcome: "no-match", files: [{ path: "src/auth.ts", source: "if (await constantTimeEqual(presentedAccessToken, expectedAccessToken)) { allow(); }" }], focusPath: "src/auth.ts", expectedCount: 0, public: true },
    { id: "secret-equality", title: "Do not compare authentication tokens with equality", outcome: "match", files: [{ path: "src/auth.ts", source: "if (presentedAccessToken === expectedAccessToken) { allow(); }" }], focusPath: "src/auth.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const EQUALITY_OPERATORS: ReadonlySet<string> = new Set(["===", "!==", "==", "!="]);
const AUTH_TOKEN_QUALIFIERS: ReadonlySet<string> = new Set(["access", "refresh", "session", "admin", "csrf", "xsrf", "auth", "authentication", "signing", "api"]);

const SENTINEL_IDENTIFIERS: ReadonlySet<string> = new Set(["undefined", "NaN"]);

const SENTINEL_WORDS = /(^|_)(SENTINEL|EMPTY|NONE|NULL|UNSET|MISSING|PLACEHOLDER|DUMMY|FAKE|EXAMPLE)(_|$)/;

const SENTINEL_PREFIX_RE =
  /^(skip|sentinel|empty|none|missing|unset|placeholder|dummy|fake|example|noop)[A-Z]/;
const AST_NODE_TYPE_RE = /^(?:TS|JSX)?[A-Z][A-Za-z]*(?:Signature|Keyword|Expression|Declaration|Element|Literal|Identifier)$/;

/**
 * True when this operand makes the comparison a non-timing-attack surface:
 * any literal (string / number / boolean / null / regex), a template literal
 * with no substitutions, `undefined`/`NaN`, or an ALL-CAPS constant reference.
 */
function isExcludedOperand(node: TSESTree.Node): boolean {
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      return true;
    case AST_NODE_TYPES.TemplateLiteral:
      return node.expressions.length === 0;
    case AST_NODE_TYPES.Identifier:
      return (
        SENTINEL_IDENTIFIERS.has(node.name) ||
        SENTINEL_PREFIX_RE.test(node.name) ||
        isConstantReference(node.name)
      );
    case AST_NODE_TYPES.MemberExpression:
      return (
        !node.computed &&
        node.property.type === AST_NODE_TYPES.Identifier &&
        (SENTINEL_PREFIX_RE.test(node.property.name) ||
          isConstantReference(node.property.name))
      );
    default:
      return false;
  }
}

function isConstantReference(identifier: string): boolean {
  if (AST_NODE_TYPE_RE.test(identifier)) return true;
  if (isAuthSecretName(identifier) && !SENTINEL_WORDS.test(identifier)) return false;
  return identifier === identifier.toUpperCase() && /[A-Za-z]/.test(identifier);
}

/** The identifier a plain operand denotes, or null for anything else. */
function operandName(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.Identifier) {
    return node.name;
  }
  if (
    node.type === AST_NODE_TYPES.MemberExpression &&
    !node.computed &&
    node.property.type === AST_NODE_TYPES.Identifier
  ) {
    return node.property.name;
  }
  return null;
}

function isSecretOperand(node: TSESTree.Node): boolean {
  if (node.type === AST_NODE_TYPES.TemplateLiteral) {
    return node.expressions.some((expression) => isSecretOperand(expression));
  }
  const name = operandName(node);
  if (name === null || !isAuthSecretName(name)) return false;
  const words = tokenize(name);
  return !words.includes("token") || words.some((word) => AUTH_TOKEN_QUALIFIERS.has(word) || (word !== "token" && SECRET_WORDS.has(word)));
}

/** The secret identifier this comparison exposes, for the diagnostic message. */
function secretNameOf(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.TemplateLiteral) {
    for (const expression of node.expressions) {
      const nested = secretNameOf(expression);
      if (nested !== null) {
        return nested;
      }
    }
    return null;
  }
  return operandName(node);
}

export default createRule<Options, MessageIds>({
  name: "prefer-constant-time-secret-compare",
  documentation: PREFER_CONSTANT_TIME_SECRET_COMPARE_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Prefer a supported constant-time comparison primitive for secret-like values.",
    },
    schema: [],
    messages: {
      preferConstantTimeSecretCompare:
        "`{{operator}}` on secret-like `{{name}}` is not guaranteed constant-time. Use a constant-time comparison primitive supported by the target runtime and handle its input-length requirements.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename)) {
      return {};
    }
    return {
      BinaryExpression(node: TSESTree.BinaryExpression): void {
        if (!EQUALITY_OPERATORS.has(node.operator)) {
          return;
        }
        const { left, right } = node;
        if (isExcludedOperand(left) || isExcludedOperand(right)) {
          return;
        }
        const secret = [left, right].find((operand) => isSecretOperand(operand));
        if (secret === undefined) {
          return;
        }
        context.report({
          node,
          messageId: "preferConstantTimeSecretCompare",
          data: { operator: node.operator, name: secretNameOf(secret) ?? "" },
        });
      },
    };
  },
});

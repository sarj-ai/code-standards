/**
 * @fileoverview prefer-constant-time-secret-compare — `===` on a secret short-circuits on the first differing byte, so the response time leaks the secret.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-constant-time-secret-compare.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isAuthSecretName } from "./_secret-names.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "preferConstantTimeSecretCompare";
type Options = readonly [];

const EQUALITY_OPERATORS: ReadonlySet<string> = new Set(["===", "!==", "==", "!="]);

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
  return name !== null && isAuthSecretName(name);
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
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `===`/`!==` on a secret-like value; short-circuiting comparison leaks the secret through timing. Use a constant-time compare.",
    },
    schema: [],
    messages: {
      preferConstantTimeSecretCompare:
        "`{{operator}}` on secret `{{name}}` short-circuits on the first differing byte and leaks it through timing. Compare constant-time instead (`crypto.subtle.timingSafeEqual` over equal-length SHA-256 digests).",
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

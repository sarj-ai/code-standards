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

/**
 * Identifiers that are compile-time sentinels rather than runtime values.
 * `undefined`/`NaN` make the comparison a presence check; an ALL-CAPS name is a
 * named constant or enum member (`TOKEN_TYPE_SYSTEM`), and timing a compare
 * against a value the attacker already knows leaks nothing.
 */
const SENTINEL_IDENTIFIERS: ReadonlySet<string> = new Set(["undefined", "NaN"]);

/**
 * Words that mark a secret-SHAPED name as a placeholder rather than a live
 * credential: `TOKEN_SENTINEL`, `EMPTY_SECRET`, `PLACEHOLDER_API_KEY`. Comparing
 * against one of these is a presence check, not an authentication check, so it
 * stays excluded even though the secret-name heuristics match it.
 */
const SENTINEL_WORDS = /(^|_)(SENTINEL|EMPTY|NONE|NULL|UNSET|MISSING|PLACEHOLDER|DUMMY|FAKE|EXAMPLE)(_|$)/;

/**
 * The camelCase spelling of the same idea: a marker VALUE whose name happens to
 * end in a secret-shaped word. A library exports `skipToken` as a unique
 * `Symbol` and callers test identity against it — there are no bytes to compare
 * and nothing an attacker could learn from the timing.
 */
const SENTINEL_PREFIX_RE =
  /^(skip|sentinel|empty|none|missing|unset|placeholder|dummy|fake|example|noop)[A-Z]/;
const AST_NODE_TYPE_RE = /^(?:TS|JSX)?[A-Z][A-Za-z]*(?:Signature|Keyword|Expression|Declaration|Element|Literal|Identifier)$/;

/**
 * True when every cased character is upper-case and at least one letter exists —
 * AND the name is not itself secret-shaped.
 *
 * The ALL-CAPS carve-out exists for public named constants (`TOKEN_TYPE_SYSTEM`).
 * But environment secrets are conventionally SCREAMING_SNAKE too
 * (`ADMIN_TOKEN`, `ASHBY_API_KEY`, `SLACK_SIGNING_SECRET`), so an unqualified
 * ALL-CAPS bail-out made this rule blind to essentially every real secret
 * compare: `env.ADMIN_TOKEN === supplied` was silent while the camelCase
 * `env.adminToken === supplied` fired. That is the exact comparison this rule
 * exists to catch. Defer to the shared secret-name heuristics first.
 */
function isConstantReference(identifier: string): boolean {
  if (AST_NODE_TYPE_RE.test(identifier)) return true;
  if (isAuthSecretName(identifier) && !SENTINEL_WORDS.test(identifier)) return false;
  return identifier === identifier.toUpperCase() && /[A-Za-z]/.test(identifier);
}

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

/**
 * True when the operand names an authenticator worth a constant-time compare.
 *
 * A template literal counts when it interpolates one: `header === \`Bearer
 * ${adminToken}\`` is the canonical Workers auth check and is exactly as
 * timing-leaky as comparing the bare token, since the constant prefix only makes
 * the first bytes free.
 */
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

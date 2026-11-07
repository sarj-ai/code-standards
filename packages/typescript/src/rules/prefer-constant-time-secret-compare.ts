/**
 * @fileoverview prefer-constant-time-secret-compare — secret-like values are compared with a constant-time primitive.
 *
 * Port of the 18.x `prefer-constant-time-secret-compare` rule. Same
 * algorithm; test files are skipped in `before()`.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsDefinition } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { isAuthSecretName, SECRET_WORDS, tokenize } from "../utils/secret-names.js";
import { findVariable, getPropertyName, staticString } from "../utils/static-string.js";

const NAME = "prefer-constant-time-secret-compare";

type Identifier = Extract<Node, { type: "Identifier" }>;

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
function isExcludedOperand(node: Node): boolean {
  switch (node.type) {
    case "Literal":
      return true;
    case "TemplateLiteral":
      return node.expressions.length === 0;
    case "Identifier":
      return (
        SENTINEL_IDENTIFIERS.has(node.name) ||
        SENTINEL_PREFIX_RE.test(node.name) ||
        isConstantReference(node.name)
      );
    case "MemberExpression":
      return (
        !node.computed &&
        node.property.type === "Identifier" &&
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
function operandName(node: Node): string | null {
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

function isSecretOperand(node: Node): boolean {
  if (node.type === "TemplateLiteral") {
    return node.expressions.some((expression) => isSecretOperand(expression));
  }
  const name = operandName(node);
  return name !== null && isCredentialName(name);
}

/** A secret name; a bare `token` needs an auth qualifier (`accessToken`) or another secret word. */
function isCredentialName(name: string): boolean {
  if (!isAuthSecretName(name)) return false;
  const words = tokenize(name);
  return !words.includes("token") || words.some((word) => AUTH_TOKEN_QUALIFIERS.has(word) || (word !== "token" && SECRET_WORDS.has(word)));
}

/** The secret identifier this comparison exposes, for the diagnostic message. */
function secretNameOf(node: Node): string | null {
  if (node.type === "TemplateLiteral") {
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

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Prefer a supported constant-time comparison primitive for secret-like values.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferConstantTimeSecretCompare:
        "`{{operator}}` on secret-like `{{name}}` is not guaranteed constant-time. Use a constant-time comparison primitive supported by the target runtime and handle its input-length requirements.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    const variableOf = (node: Identifier) => findVariable(sourceCode.getScope(node), node.name);

    /** The one definition of a binding that is never reassigned, or null. */
    function soleDefinition(node: Identifier): TsDefinition | null {
      const binding = variableOf(node);
      if (binding?.defs.length !== 1 || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return null;
      return binding.defs[0] ?? null;
    }

    function credentialSource(node: Node, seen = new Set<Node>()): boolean {
      if (seen.has(node) || seen.size >= 8) return false;
      seen.add(node);
      if (isSecretOperand(node) && !isExcludedOperand(node)) return true;
      const expression = unwrapExpression(node);
      if (expression !== node) return credentialSource(expression, seen);
      if (node.type === "LogicalExpression" && node.operator === "??") return credentialSource(node.left, new Set(seen)) || credentialSource(node.right, new Set(seen));
      if (node.type === "Identifier") {
        const init = constInitializer(soleDefinition(node));
        return init !== null && credentialSource(init, seen);
      }
      return isCredentialHeaderRead(node);
    }

    /** `request.headers.get("authorization")` on a native or Next.js request. */
    function isCredentialHeaderRead(node: Node): boolean {
      if (node.type !== "CallExpression" || node.optional || node.arguments.length !== 1 ||
        node.callee.type !== "MemberExpression" || node.callee.optional ||
        getPropertyName(node.callee) !== "get") return false;
      const receiver = node.callee.object;
      const key = staticString(node.arguments[0]);
      return receiver.type === "MemberExpression" && !receiver.optional && getPropertyName(receiver) === "headers" &&
        key !== null && isCredentialName(key) && isNativeRequest(receiver.object);
    }

    function isNativeRequest(node: Node, seen = new Set<Node>()): boolean {
      if (seen.has(node) || seen.size >= 8) return false;
      seen.add(node);
      if (node.type === "NewExpression") return node.callee.type === "Identifier" && node.callee.name === "Request" && isGlobal(node.callee);
      if (node.type !== "Identifier") return false;
      const definition = soleDefinition(node);
      if (definition === null) return false;
      if (isRequestAnnotated(definition)) return true;
      const init = constInitializer(definition);
      return init !== null && isNativeRequest(init, seen);
    }

    /** `request: Request` (the global) or `request: NextRequest` imported from `next/server`. */
    function isRequestAnnotated(definition: TsDefinition): boolean {
      const annotation = definition.name.type === "Identifier" ? definition.name.typeAnnotation?.typeAnnotation : undefined;
      if (annotation?.type !== "TSTypeReference" || annotation.typeName.type !== "Identifier") return false;
      const name = annotation.typeName;
      if (name.name === "Request" && isGlobal(name)) return true;
      return isNextRequestImport(variableOf(name)?.defs[0]);
    }

    const isGlobal = (node: Identifier): boolean => (variableOf(node)?.defs.length ?? 0) === 0;

    return {
      before(): boolean | void {
        if (isTestFile({ filename: context.filename, cwd: context.cwd })) return false;
        sourceCode = context.sourceCode;
      },
      BinaryExpression(node: ESTree.BinaryExpression): void {
        if (!EQUALITY_OPERATORS.has(node.operator)) {
          return;
        }
        const { left, right } = node;
        const derivedLeft = credentialSource(left);
        const derivedRight = credentialSource(right);
        if ((isExcludedOperand(left) && !derivedLeft) || (isExcludedOperand(right) && !derivedRight)) return;
        const secret = derivedLeft ? left : derivedRight ? right : undefined;
        if (secret === undefined) {
          return;
        }
        context.report({
          node,
          messageId: "preferConstantTimeSecretCompare",
          data: { operator: node.operator, name: secretNameOf(secret) ?? "request credential" },
        });
      },
    };
  },
});


/** `import { NextRequest } from "next/server"`. */
function isNextRequestImport(imported: TsDefinition | undefined): boolean {
  return imported?.type === "ImportBinding" && imported.parent?.type === "ImportDeclaration" && imported.parent.source.value === "next/server" &&
    imported.node.type === "ImportSpecifier" && imported.node.imported.type === "Identifier" && imported.node.imported.name === "NextRequest";
}

/** The initializer of a `const` variable definition, or null when it is not one. */
function constInitializer(definition: TsDefinition | null): Node | null {
  if (definition?.type !== "Variable" || (definition.parent as ESTree.VariableDeclaration).kind !== "const") return null;
  return (definition.node as ESTree.VariableDeclarator).init;
}

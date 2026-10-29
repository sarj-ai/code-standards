/**
 * @fileoverview require-jwt-lifetime — Require an expiration claim or a maximum token age when returning a verified JWT.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-jwt-lifetime.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";

export const REQUIRE_JWT_LIFETIME_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Require an expiration claim or a maximum token age when returning a verified JWT.",
  rationale: "JOSE validates exp when present but does not require it by default, so otherwise valid tokens without an expiration may remain accepted indefinitely.",
  remediation: "Set requiredClaims: ['exp'] or a finite maxTokenAge in jwtVerify options. Keep issuer and audience checks appropriate to the protocol.",
  category: "security",
  references: ["https://github.com/panva/jose/blob/main/docs/jwt/verify/interfaces/JWTVerifyOptions.md"],
  limitations: [
    "Checks direct return or concise-arrow-return calls, including await, to runtime ESM-import-proven jose jwtVerify with absent options or a literal options object lacking both lifetime controls. Aliased imports and namespace imports are resolved lexically.",
    "Opaque options, spreads, local claim validation before return, custom verifiers, generated files and tests are excluded. Existing native jose validation is assumed. No automatic protocol policy is invented.",
  ],
  examples: [
    { id: "optional-expiration", title: "A signature alone does not require expiration", outcome: "match", files: [{ path: "auth.ts", source: "import { jwtVerify } from 'jose'; function verify(token, key) { return jwtVerify(token, key); }" }], focusPath: "auth.ts", expectedCount: 1, public: true },
    { id: "required-expiration", title: "Require the expiration claim", outcome: "no-match", files: [{ path: "auth.ts", source: "import { jwtVerify } from 'jose'; function verify(token, key) { return jwtVerify(token, key, { requiredClaims: ['exp'] }); }" }], focusPath: "auth.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "lifetime">({
  name: "require-jwt-lifetime",
  documentation: REQUIRE_JWT_LIFETIME_DOCUMENTATION,
  meta: { type: "problem", docs: { description: REQUIRE_JWT_LIFETIME_DOCUMENTATION.summary }, schema: [], messages: { lifetime: "Require the JWT exp claim or set maxTokenAge before returning this verification result." } },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || isTestFile(context.filename)) return {};
    const sourceCode = context.sourceCode;
    function inspect(input: TSESTree.Node | null): void {
      if (input === null) return;
      let node = unwrapExpression(input);
      if (node.type === AST_NODE_TYPES.AwaitExpression) node = unwrapExpression(node.argument);
      if (node.type !== AST_NODE_TYPES.CallExpression || !isVerifier(node.callee)) return;
      if (!missingLifetime(node.arguments[2])) return;
      context.report({ node, messageId: "lifetime" });
    }
    function isVerifier(node: TSESTree.Node): boolean {
      node = unwrapExpression(node);
      if (node.type === AST_NODE_TYPES.Identifier) {
        const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
        const declaration = variable?.defs[0]?.node;
        return variable?.defs.length === 1 && declaration?.type === AST_NODE_TYPES.ImportSpecifier && declaration.parent.type === AST_NODE_TYPES.ImportDeclaration && declaration.importKind !== "type" && declaration.parent.importKind !== "type" && declaration.parent.source.value === "jose" && declaration.imported.type === AST_NODE_TYPES.Identifier && declaration.imported.name === "jwtVerify";
      }
      if (node.type !== AST_NODE_TYPES.MemberExpression || ASTUtils.getPropertyName(node) !== "jwtVerify" || node.object.type !== AST_NODE_TYPES.Identifier) return false;
      const definition = ASTUtils.findVariable(sourceCode.getScope(node.object), node.object.name)?.defs[0]?.node;
      return definition?.type === AST_NODE_TYPES.ImportNamespaceSpecifier && definition.parent.importKind !== "type" && definition.parent.source.value === "jose";
    }
    function missingLifetime(options: TSESTree.CallExpressionArgument | undefined): boolean {
      if (options === undefined) return true;
      if (options.type !== AST_NODE_TYPES.ObjectExpression || options.properties.some(property => property.type !== AST_NODE_TYPES.Property || property.computed)) return false;
      return !options.properties.some(property => property.type === AST_NODE_TYPES.Property && lifetimeProperty(property));
    }
    function lifetimeProperty(property: TSESTree.Property): boolean {
      const name = property.key.type === AST_NODE_TYPES.Identifier ? property.key.name : property.key.type === AST_NODE_TYPES.Literal ? property.key.value : null;
      if (name === "maxTokenAge") {
        if (property.value.type !== AST_NODE_TYPES.Literal) return true;
        return typeof property.value.value === "number" && Number.isFinite(property.value.value) || typeof property.value.value === "string" && property.value.value.trim() !== "";
      }
      if (name !== "requiredClaims") return false;
      if (property.value.type !== AST_NODE_TYPES.ArrayExpression || property.value.elements.some(element => element?.type !== AST_NODE_TYPES.Literal)) return true;
      return property.value.elements.some(element => element?.type === AST_NODE_TYPES.Literal && element.value === "exp");
    }
    return {
      ReturnStatement(node) { inspect(node.argument); },
      ArrowFunctionExpression(node) { if (node.expression) inspect(node.body); },
    };
  },
});

/**
 * @fileoverview require-jwt-lifetime — Require an expiration claim or a maximum token age when returning a verified JWT.
 *
 * Port of the 18.x `require-jwt-lifetime` rule. The rule is untyped, so
 * the port covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "require-jwt-lifetime";

type Identifier = Extract<Node, { type: "Identifier" }>;

function isJoseValueImport(declaration: Node): boolean {
  return declaration.type === "ImportDeclaration" && declaration.importKind !== "type" && declaration.source.value === "jose";
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Require an expiration claim or a maximum token age when returning a verified JWT.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { lifetime: "Require the JWT exp claim or set maxTokenAge before returning this verification result." },
  },
  createOnce(context) {
    function inspect(input: Node | null): void {
      if (input === null) return;
      let node = unwrapExpression(input);
      if (node.type === "AwaitExpression") node = unwrapExpression(node.argument);
      if (node.type !== "CallExpression" || !isVerifier(node.callee)) return;
      if (!missingLifetime(node.arguments[2])) return;
      context.report({ node, messageId: "lifetime" });
    }
    function isVerifier(node: Node): boolean {
      node = unwrapExpression(node);
      if (node.type === "Identifier") return isNamedVerifierImport(node);
      return node.type === "MemberExpression" && getPropertyName(node) === "jwtVerify" &&
        node.object.type === "Identifier" && isJoseNamespace(node.object);
    }
    /** `import { jwtVerify } from "jose"`, as a value. */
    function isNamedVerifierImport(node: Identifier): boolean {
      const variable = findVariable(context.sourceCode.getScope(node), node.name);
      const specifier = variable?.defs.length === 1 ? variable.defs[0]?.node : undefined;
      return specifier?.type === "ImportSpecifier" && specifier.importKind !== "type" &&
        specifier.imported.type === "Identifier" && specifier.imported.name === "jwtVerify" && isJoseValueImport(specifier.parent);
    }
    /** `import * as jose from "jose"`, as a value. */
    function isJoseNamespace(node: Identifier): boolean {
      const specifier = findVariable(context.sourceCode.getScope(node), node.name)?.defs[0]?.node;
      return specifier?.type === "ImportNamespaceSpecifier" && isJoseValueImport(specifier.parent);
    }
    function missingLifetime(options: ESTree.Argument | undefined): boolean {
      if (options === undefined) return true;
      if (options.type !== "ObjectExpression" || options.properties.some(property => property.type !== "Property" || property.computed)) return false;
      return !options.properties.some(property => property.type === "Property" && lifetimeProperty(property));
    }
    function lifetimeProperty(property: ESTree.ObjectProperty): boolean {
      const name = property.key.type === "Identifier" ? property.key.name : property.key.type === "Literal" ? property.key.value : null;
      if (name === "maxTokenAge") {
        if (property.value.type !== "Literal") return true;
        return typeof property.value.value === "number" && Number.isFinite(property.value.value) || typeof property.value.value === "string" && property.value.value.trim() !== "";
      }
      if (name !== "requiredClaims") return false;
      if (property.value.type !== "ArrayExpression" || property.value.elements.some(element => element?.type !== "Literal")) return true;
      return property.value.elements.some(element => element?.type === "Literal" && element.value === "exp");
    }
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text) || isTestFile(context.filename)) return false;
        return undefined;
      },
      ReturnStatement(node) { inspect(node.argument); },
      ArrowFunctionExpression(node) { if (node.expression) inspect(node.body); },
    };
  },
});

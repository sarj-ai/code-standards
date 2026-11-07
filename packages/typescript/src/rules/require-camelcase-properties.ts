/**
 * @fileoverview require-camelcase-properties — application property syntax is camelCase unless a wire key is explicitly quoted.
 *
 * Port of the 18.x `require-camelcase-properties` rule. The rule is
 * untyped, so the port covers all of it.
 */

import type { Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "require-camelcase-properties";

const SNAKE_CASE_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/u;

interface PropertyNode {
  readonly computed?: boolean;
  readonly key: Node;
}

/** A member that is computed, an index signature, or already named `name`. */
function blocksRename(member: Node, name: string): boolean {
  if (member.type === "TSIndexSignature" || ("computed" in member && member.computed)) return true;
  if (!("key" in member)) return false;
  const { key } = member;
  return (key.type === "Identifier" && key.name === name) || (key.type === "Literal" && key.value === name);
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Require unquoted lower snake_case TypeScript properties and dot access to use camelCase.",
      url: docsUrl(NAME),
    },
    schema: [],
    defaultOptions: [],
    messages: {
      requireCamelcaseProperty:
        "Unquoted property `{{name}}` must use camelCase. Quote wire-format keys and use bracket access at external boundaries.",
    },
  },
  createOnce(context) {
    function checkPropertyNode(node: PropertyNode): void {
      if (node.computed === true || node.key.type !== "Identifier") return;
      const key = node.key;
      if (!SNAKE_CASE_RE.test(key.name)) return;
      const replacement = privateTypePropertyName(key);
      context.report({
        node: key,
        messageId: "requireCamelcaseProperty",
        data: { name: key.name },
        ...(replacement !== null && { fix: (fixer: Fixer) => fixer.replaceText(key, replacement) }),
      });
    }
    // Every visited node type below has `key` (and optionally `computed`).
    const checkProperty = (node: Node): void => checkPropertyNode(node as unknown as PropertyNode);

    function privateTypePropertyName(key: Node & { readonly name: string }): string | null {
      const declared = privateTypeOwner(key);
      if (declared === null) return null;
      const { container, owner } = declared;
      const name = key.name.replaceAll(/_([a-z0-9])/gu, (_match, letter: string) => letter.toUpperCase());
      // A `this` in the declaration or an existing token spelled like the new name blocks the rename.
      if (context.sourceCode.getTokens(owner).some((token) => token.value === "this" || token.value === name)) return null;
      const members: readonly Node[] = container.type === "TSInterfaceBody" ? container.body :
        container.type === "TSTypeLiteral" ? container.members : [];
      return members.some((member) => blocksRename(member, name)) ? null : name;
    }

    /** The member container and its unused, private interface or type alias, for a signature key. */
    function privateTypeOwner(key: Node): { readonly container: Node; readonly owner: Node } | null {
      const signature = key.parent;
      if (signature?.type !== "TSPropertySignature" && signature?.type !== "TSMethodSignature") return null;
      const container = signature.parent;
      const owner = container.parent;
      if (owner?.type !== "TSInterfaceDeclaration" && owner?.type !== "TSTypeAliasDeclaration") return null;
      if ((owner.type === "TSInterfaceDeclaration" && owner.extends.length > 0) ||
        !isUnusedPrivateBinding(context.sourceCode, owner, owner.id, context.filename)) return null;
      return { container, owner };
    }

    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      AccessorProperty: checkProperty,
      MemberExpression(node: ESTree.MemberExpression): void {
        if (!node.computed && node.property.type === "Identifier") {
          checkPropertyNode({ key: node.property });
        }
      },
      MethodDefinition: checkProperty,
      Property: checkProperty,
      PropertyDefinition: checkProperty,
      TSAbstractAccessorProperty: checkProperty,
      TSAbstractMethodDefinition: checkProperty,
      TSAbstractPropertyDefinition: checkProperty,
      TSMethodSignature: checkProperty,
      TSPropertySignature: checkProperty,
    };
  },
});

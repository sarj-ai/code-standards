/**
 * @fileoverview require-camelcase-properties — application property syntax is camelCase unless a wire key is explicitly quoted.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-camelcase-properties.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { isUnusedPrivateBinding } from "./_unused-private-binding.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "requireCamelcaseProperty";
type Options = readonly [];

export const REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Require unquoted lower snake_case TypeScript properties and dot access to use camelCase.",
  rationale: "Unquoted snake_case property syntax makes external wire naming indistinguishable from application-domain naming and lets inconsistent contracts spread through typed code.",
  remediation: "Rename application properties to camelCase. At an external wire boundary, make the exception explicit with a quoted key and bracket access.",
  category: "style",
  autofix: "safe",
  limitations: [
    "Quoted string keys and bracket access are treated as explicit external-wire boundaries.",
    "Computed, numeric, symbol, private, generated, and PascalCase property names are excluded. External-library ownership is not inferred: preserve its spelling using quoted keys and bracket access, or an exact local suppression.",
    "Automatic renaming is limited to an unused private interface or object type alias without heritage, exports, collisions, polymorphic this, computed/indexed keys, merged declarations, or eval. Runtime objects, referenced types and protocol boundaries remain manual.",
  ],
  examples: [
    {
      id: "camelcase-application-shape",
      title: "Use camelCase for an application-facing return shape",
      outcome: "no-match",
      files: [{ path: "src/calls-date-range.ts", source: "export function range(): { dateFrom: string; dateTo: string } { return { dateFrom: '', dateTo: '' }; }" }],
      focusPath: "src/calls-date-range.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "snake-case-application-shape",
      title: "Do not use unquoted wire casing as application property syntax",
      outcome: "match",
      files: [{ path: "src/calls-date-range.ts", source: "export function range(): { date_from: string; date_to: string } { return { dateFrom: '', dateTo: '' }; }" }],
      focusPath: "src/calls-date-range.ts",
      expectedCount: 2,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; interface Local { user_id: string }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; interface Local { userId: string }" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

const SNAKE_CASE_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/u;

interface PropertyNode {
  readonly computed?: boolean;
  readonly key: TSESTree.Node;
}

export default createRule<Options, MessageIds>({
  name: "require-camelcase-properties",
  documentation: REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION.summary },
    schema: [],
    messages: {
      requireCamelcaseProperty:
        "Unquoted property `{{name}}` must use camelCase. Quote wire-format keys and use bracket access at external boundaries.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};


    const checkProperty = (node: PropertyNode): void => {
      if (node.computed === true || node.key.type !== AST_NODE_TYPES.Identifier) return;
      if (!SNAKE_CASE_RE.test(node.key.name)) return;
      const replacement = privateTypePropertyName(node.key);
      context.report({
        node: node.key,
        messageId: "requireCamelcaseProperty",
        data: { name: node.key.name },
        fix: replacement === null ? null : (fixer) => fixer.replaceText(node.key, replacement),
      });
    };

    function privateTypePropertyName(key: TSESTree.Identifier): string | null {
      if (key.parent.type !== AST_NODE_TYPES.TSPropertySignature && key.parent.type !== AST_NODE_TYPES.TSMethodSignature) return null;
      const container = key.parent.parent;
      const owner = container.parent;
      if (owner.type !== AST_NODE_TYPES.TSInterfaceDeclaration && owner.type !== AST_NODE_TYPES.TSTypeAliasDeclaration) return null;
      if ((owner.type === AST_NODE_TYPES.TSInterfaceDeclaration && owner.extends.length > 0) ||
        !isUnusedPrivateBinding(context.sourceCode, owner, owner.id, context.filename)) return null;
      const name = key.name.replaceAll(/_([a-z0-9])/gu, (_match, letter: string) => letter.toUpperCase());
      if (context.sourceCode.getTokens(owner).some((token) => token.value === "this")) return null;
      const members = container.type === AST_NODE_TYPES.TSInterfaceBody ? container.body :
        container.type === AST_NODE_TYPES.TSTypeLiteral ? container.members : [];
      if (members.some((member) => member.type === AST_NODE_TYPES.TSIndexSignature ||
        ("computed" in member && member.computed) ||
        ("key" in member && ((member.key.type === AST_NODE_TYPES.Identifier && member.key.name === name) ||
          (member.key.type === AST_NODE_TYPES.Literal && member.key.value === name))))) return null;
      return context.sourceCode.getTokens(owner).some((token) => token.value === name) ? null : name;
    }


    return {
      AccessorProperty: checkProperty,
      MemberExpression(node: TSESTree.MemberExpression): void {
        if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) {
          checkProperty({ key: node.property });
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

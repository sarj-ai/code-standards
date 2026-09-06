/**
 * @fileoverview no-bespoke-api-case-conversion — direct snake/camel mirror mappings duplicate generated API client ownership.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-bespoke-api-case-conversion.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "noBespokeApiCaseConversion";
type Options = readonly [];

export const NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION = {
  summary:
    "Review direct snake_case/camelCase mirror mappings on explicitly API-typed adapter values.",
  rationale:
    "Duplicating wire-name translation can drift from an API client contract. When the SDK owns application-facing names, centralizing conversion avoids maintaining another mirror by hand.",
  remediation:
    "Move wire-name ownership and case conversion into the generated SDK/model layer; keep application adapters on the generated typed surface.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Only adapter/adapters files and receivers explicitly annotated with a scope-resolved type imported from an API/client/SDK/contract/generated module are checked. Unrelated imports, local type shadows, reassigned receivers and inferred receiver types are excluded.",
    "Only object properties that directly translate the same identifier between snake_case and lowerCamelCase are reported.",
    "Quoted/computed protocol keys, generated/vendor code, tests, fixtures, and indirect conversions are intentionally excluded.",
  ],
  examples: [
    {
      id: "generated-client-surface",
      title: "Use the generated client's application-facing property names",
      outcome: "no-match",
      files: [
        {
          path: "src/user-adapter.ts",
          source:
            "import type { User } from './generated-client';\nexport const toUser = (raw: User) => ({ displayName: raw.displayName });",
        },
      ],
      focusPath: "src/user-adapter.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "bespoke-wire-case-conversion",
      title: "Do not reproduce SDK case conversion in an application adapter",
      outcome: "match",
      files: [
        {
          path: "src/user-adapter.ts",
          source:
            "import type { User } from './api-contract';\nexport const toUser = (raw: User) => ({ displayName: raw.display_name });",
        },
      ],
      focusPath: "src/user-adapter.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const ADAPTER_BASENAME_RE = /(?:^|[-_.])adapters?(?:[-_.]|$)/i;
const API_BOUNDARY_IMPORT_RE = /(?:^|[/_.-])(?:api|client|sdk|contract|generated)(?:$|[/_.-])/i;
const SNAKE_CASE_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/;
const LOWER_CAMEL_CASE_RE = /^[a-z][A-Za-z0-9]*$/;

function propertyName(node: TSESTree.PropertyName): string | null {
  return node.type === AST_NODE_TYPES.Identifier ? node.name : null;
}

function memberName(node: TSESTree.Node): string | null {
  let current = node;
  while (
    current.type === AST_NODE_TYPES.TSAsExpression ||
    current.type === AST_NODE_TYPES.TSNonNullExpression ||
    current.type === AST_NODE_TYPES.TSTypeAssertion
  ) {
    current = current.expression;
  }
  if (
    current.type !== AST_NODE_TYPES.MemberExpression ||
    current.computed ||
    current.property.type !== AST_NODE_TYPES.Identifier
  ) {
    return null;
  }
  return current.property.name;
}

function isDirectCaseTranslation(left: string, right: string): boolean {
  if (SNAKE_CASE_RE.test(left) && LOWER_CAMEL_CASE_RE.test(right)) {
    return snakeToCamel(left) === right;
  }
  if (SNAKE_CASE_RE.test(right) && LOWER_CAMEL_CASE_RE.test(left)) {
    return snakeToCamel(right) === left;
  }
  return false;
}

function snakeToCamel(name: string): string {
  return name.replace(/_([a-z0-9])/g, (_match, character: string) => character.toUpperCase());
}

export default createRule<Options, MessageIds>({
  name: "no-bespoke-api-case-conversion",
  documentation: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.summary },
    schema: [],
    messages: {
      noBespokeApiCaseConversion:
        "This API-typed adapter value mirrors `{{wireName}}` and `{{applicationName}}`. If the SDK owns application-facing names, move this conversion to its model boundary.",
    },
  },
  defaultOptions: [],
  create(context) {
    const filename = context.filename.replaceAll("\\", "/");
    const basename = filename.slice(filename.lastIndexOf("/") + 1);
    if (
      !ADAPTER_BASENAME_RE.test(basename) ||
      isGeneratedFile(filename, context.sourceCode.text) ||
      isTestFile(filename, ["fixtureTree"])
    ) {
      return {};
    }

    const hasApiReceiver = (value: TSESTree.Node): boolean => {
      let current = value;
      while (true) {
        if (current.type === AST_NODE_TYPES.MemberExpression) current = current.object;
        else if (current.type === AST_NODE_TYPES.TSAsExpression || current.type === AST_NODE_TYPES.TSNonNullExpression || current.type === AST_NODE_TYPES.TSTypeAssertion) current = current.expression;
        else break;
      }
      if (current.type !== AST_NODE_TYPES.Identifier) return false;
      const binding = ASTUtils.findVariable(context.sourceCode.getScope(current), current.name);
      if (binding?.defs.length !== 1 || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
      const identifier = binding.defs[0]?.name;
      if (identifier?.type !== AST_NODE_TYPES.Identifier) return false;
      const annotation = identifier.typeAnnotation?.typeAnnotation;
      if (annotation?.type !== AST_NODE_TYPES.TSTypeReference) return false;
      let typeName = annotation.typeName;
      while (typeName.type === AST_NODE_TYPES.TSQualifiedName) typeName = typeName.left;
      if (typeName.type !== AST_NODE_TYPES.Identifier) return false;
      const typeBinding = ASTUtils.findVariable(context.sourceCode.getScope(typeName), typeName.name);
      return typeBinding?.defs.length === 1 && typeBinding.defs[0]?.type === "ImportBinding" && typeBinding.defs[0].parent.type === AST_NODE_TYPES.ImportDeclaration && API_BOUNDARY_IMPORT_RE.test(typeBinding.defs[0].parent.source.value);
    };
    return {
      Property(node: TSESTree.Property): void {
        if (node.computed || node.method || node.shorthand) return;
        const key = propertyName(node.key);
        const value = memberName(node.value);
        if (key === null || value === null || !isDirectCaseTranslation(key, value)) return;
        if (!hasApiReceiver(node.value)) return;
        const wireName = SNAKE_CASE_RE.test(key) ? key : value;
        const applicationName = wireName === key ? value : key;
        context.report({
          node: node.key,
          messageId: "noBespokeApiCaseConversion",
          data: { applicationName, wireName },
        });
      },
    };
  },
});

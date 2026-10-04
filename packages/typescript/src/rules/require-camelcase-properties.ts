/**
 * @fileoverview require-camelcase-properties — application property syntax is camelCase unless a wire key is explicitly quoted.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-camelcase-properties.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree } from "@oxlint/plugins";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "requireCamelcaseProperty";
type Options = readonly [];

export const REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Require unquoted lower snake_case TypeScript properties and dot access to use camelCase.",
  rationale: "Unquoted snake_case property syntax makes external wire naming indistinguishable from application-domain naming and lets inconsistent contracts spread through typed code.",
  remediation: "Rename application properties to camelCase. At an external wire boundary, make the exception explicit with a quoted key and bracket access.",
  category: "style",
  autofix: "none",
  limitations: [
    "Quoted string keys and bracket access are treated as explicit external-wire boundaries.",
    "Computed, numeric, symbol, private, generated, and PascalCase property names are excluded. External-library ownership is not inferred: preserve its spelling using quoted keys and bracket access, or an exact local suppression.",
    "Renaming a property can cross module or protocol boundaries, so the rule does not autofix.",
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
  ],
} as const satisfies RuleDocumentation;

const SNAKE_CASE_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/u;

interface PropertyNode {
  readonly computed?: boolean;
  readonly key: ESTree.Node;
}

export default createRule<Options, MessageIds>({
  name: "require-camelcase-properties",
  documentation: REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION.summary },
    schema: [],
    messages: {
      requireCamelcaseProperty:
        "Unquoted property `{{name}}` must use camelCase. Quote wire-format keys and use bracket access at external boundaries.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};

    const checkProperty = (node: ESTree.Node | PropertyNode): void => {
      if (!("key" in node)) return;
      if (("computed" in node && node.computed === true) || node.key.type !== "Identifier") return;
      if (!SNAKE_CASE_RE.test(node.key.name)) return;
      context.report({
        node: node.key,
        messageId: "requireCamelcaseProperty",
        data: { name: node.key.name },
      });
    };

    return {
      AccessorProperty: checkProperty,
      MemberExpression(node: ESTree.MemberExpression): void {
        if (!node.computed && node.property.type === "Identifier") {
          checkProperty({ key: node.property });
        }
      },
      MethodDefinition: checkProperty,
      Property: checkProperty,
      PropertyDefinition: checkProperty,
      TSMethodSignature: checkProperty,
      TSPropertySignature: checkProperty,
    };
  },
});

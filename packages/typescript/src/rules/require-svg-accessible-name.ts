/**
 * @fileoverview require-svg-accessible-name — statically proven UI policy violations receive actionable diagnostics.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-svg-accessible-name.test.ts
 */

import { AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  attributeNameStatus,
  attributeText,
  childrenNameStatus,
  isHidden,
  isPassedAsProp,
  hasHiddenAncestor,
} from "./_jsx-accessibility.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

export const REQUIRE_SVG_ACCESSIBLE_NAME_DOCUMENTATION = {
  summary:
    "Require a name or explicit decorative semantics on inline SVG elements.",
  rationale:
    "Meaningful graphics need a name; decorative graphics should not add unnamed content to the accessibility tree.",
  remediation:
    "Add aria-label, aria-labelledby, or a direct title child; mark decorative graphics aria-hidden or presentational.",
  category: "correctness",
  limitations: [
    "Only intrinsic svg elements are checked. Dynamic labels, forwarded props, and dynamic title content remain runtime concerns. IDs, CSS visibility and graphic meaning are not inferred. Tests, stories, fixtures and generated files are excluded. No automatic title or decorative marker is invented.",
  ],
  examples: [
    {
      id: "unnamed-svg",
      title: "Name meaningful graphics",
      outcome: "match",
      files: [{ path: "src/chart.tsx", source: "<svg><path /></svg>" }],
      focusPath: "src/chart.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "decorative-svg",
      title: "Identify decorative graphics",
      outcome: "no-match",
      files: [
        {
          path: "src/chart.tsx",
          source: '<svg aria-hidden="true"><path /></svg>',
        },
      ],
      focusPath: "src/chart.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<readonly [], "missingName">({
  name: "require-svg-accessible-name",
  documentation: REQUIRE_SVG_ACCESSIBLE_NAME_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: REQUIRE_SVG_ACCESSIBLE_NAME_DOCUMENTATION.summary },
    schema: [],
    messages: {
      missingName:
        "Give this SVG an accessible name or explicitly mark it decorative with aria-hidden or a presentational role.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isGeneratedFile(context.filename, context.sourceCode.text) ||
      isTestFile(context.filename) ||
      isStoryFile(context.filename)
    )
      return {};
    return {
      JSXElement(node): void {
        const opening = node.openingElement;
        if (
          opening.name.type !== AST_NODE_TYPES.JSXIdentifier ||
          opening.name.name !== "svg"
        )
          return;
        if (
          isPassedAsProp(node, context.sourceCode) ||
          hasHiddenAncestor(node, context.sourceCode)
        )
          return;
        if (
          isHidden(opening) ||
          ["none", "presentation"].includes(
            attributeText(opening, "role") ?? "",
          )
        )
          return;
        if (
          attributeNameStatus(opening, ["aria-label", "aria-labelledby"]) !==
          "empty"
        )
          return;
        const namedTitle = node.children.some(
          (child) =>
            child.type === AST_NODE_TYPES.JSXElement &&
            child.openingElement.name.type === AST_NODE_TYPES.JSXIdentifier &&
            child.openingElement.name.name === "title" &&
            childrenNameStatus(child.children, context.sourceCode, []) !==
              "empty",
        );
        if (namedTitle) return;
        context.report({ node: opening, messageId: "missingName" });
      },
    };
  },
});
